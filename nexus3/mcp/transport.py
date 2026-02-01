"""MCP transport layer.

Provides transport implementations for MCP communication:
- StdioTransport: Launch MCP server as subprocess, communicate via stdin/stdout
- HTTPTransport: Connect to remote MCP server via HTTP (placeholder)

MCP uses newline-delimited JSON-RPC 2.0 messages.

P2.12 SECURITY: Stdio transport enforces maximum line length to prevent
memory exhaustion from malicious/buggy servers sending extremely long lines.
"""

import asyncio
import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from collections import deque
from typing import Any

import httpx

from nexus3.core.errors import NexusError
from nexus3.core.url_validator import UrlSecurityError, validate_url
from nexus3.mcp.protocol import PROTOCOL_VERSION

logger = logging.getLogger(__name__)


class MCPTransportError(NexusError):
    """Error in MCP transport layer."""


# P2.12 SECURITY: Maximum line length for stdio transport.
# Prevents memory exhaustion from malicious/buggy servers.
# 10MB should be generous for any legitimate MCP message.
MAX_STDIO_LINE_LENGTH: int = 10 * 1024 * 1024  # 10 MB

# P1.10: HTTP retry configuration for transient failures.
# Retry on server errors and rate limiting, but not client errors.
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_RETRY_BACKOFF: float = 1.0
RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

# P1.7: MCP-specific HTTP headers required by the protocol spec.
# These are added to every HTTP request to MCP servers.
MCP_HTTP_HEADERS: dict[str, str] = {
    "MCP-Protocol-Version": PROTOCOL_VERSION,
    "Accept": "application/json, text/event-stream",
}

# P1.8: Session ID validation constants.
# MCP session IDs should be alphanumeric with optional dashes/underscores.
# Max length prevents unbounded memory growth from malicious servers.
MAX_SESSION_ID_LENGTH: int = 256
SESSION_ID_PATTERN: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9_-]+$")


# Environment variables always safe to pass to MCP servers.
# These are essential for subprocess execution but don't contain secrets.
SAFE_ENV_KEYS: frozenset[str] = frozenset({
    # Cross-platform
    "PATH",       # Find executables
    "HOME",       # User home directory (config files)
    "USER",       # Current username
    "LOGNAME",    # Login name (same as USER on most systems)
    "LANG",       # Locale (character encoding)
    "LC_ALL",     # Locale override
    "LC_CTYPE",   # Character classification locale
    "TERM",       # Terminal type
    "SHELL",      # Default shell
    "TMPDIR",     # Temporary directory
    "TMP",        # Temp directory (cross-platform)
    "TEMP",       # Temp directory (cross-platform)
    # Windows-specific (P2.0.1)
    "USERPROFILE",  # Windows user home directory
    "APPDATA",      # Windows roaming app data
    "LOCALAPPDATA", # Windows local app data
    "PATHEXT",      # Windows executable extensions (.exe, .cmd, .bat)
    "SYSTEMROOT",   # Windows system root (C:\Windows)
    "COMSPEC",      # Windows command interpreter (cmd.exe)
})


def build_safe_env(
    explicit_env: dict[str, str] | None = None,
    passthrough: list[str] | None = None,
) -> dict[str, str]:
    """Build a safe environment dict for MCP server subprocesses.

    SECURITY: MCP servers receive only:
    1. Safe system variables (PATH, HOME, etc.)
    2. Explicitly declared env vars from mcp.json
    3. Explicitly passthrough vars from mcp.json

    This prevents accidental leakage of secrets like API keys.

    Args:
        explicit_env: Explicit env vars declared in config (merged last).
        passthrough: Env var names to copy from host environment.

    Returns:
        Safe environment dict for subprocess.
    """
    env: dict[str, str] = {}

    # 1. Always include safe system variables
    for key in SAFE_ENV_KEYS:
        if key in os.environ:
            env[key] = os.environ[key]

    # 2. Add passthrough vars from host (user explicitly opted in)
    if passthrough:
        for key in passthrough:
            if key in os.environ:
                env[key] = os.environ[key]

    # 3. Explicit env vars override everything (highest priority)
    if explicit_env:
        env.update(explicit_env)

    return env


# Windows command aliases: commands that should be translated on Windows
# when the original command is not found
_WINDOWS_COMMAND_ALIASES: dict[str, str] = {
    "python3": "python",  # Windows typically only has 'python', not 'python3'
    "pip3": "pip",        # Same for pip
}


def resolve_command(command: list[str]) -> list[str]:
    """Resolve command for cross-platform execution.

    P2.0.2-P2.0.3: On Windows, executable extensions (.cmd, .bat, .exe) are not
    automatically resolved by create_subprocess_exec. This uses shutil.which to
    find the actual executable path, respecting PATHEXT.

    Additionally, translates Unix-style commands to Windows equivalents when the
    original command is not found (e.g., python3 → python, pip3 → pip).

    Args:
        command: Command and arguments list.

    Returns:
        Command list with resolved executable path (on Windows) or unchanged (on Unix).
    """
    if sys.platform != "win32" or not command:
        return command

    executable = command[0]

    # Skip if already has a known Windows executable extension
    if any(executable.lower().endswith(ext) for ext in (".exe", ".cmd", ".bat", ".com")):
        return command

    # Try to resolve using which (respects PATHEXT on Windows)
    resolved = shutil.which(executable)
    if resolved:
        return [resolved] + command[1:]

    # If not found, try Windows alias (e.g., python3 → python)
    alias = _WINDOWS_COMMAND_ALIASES.get(executable)
    if alias:
        resolved = shutil.which(alias)
        if resolved:
            logger.debug("Resolved %s → %s on Windows", executable, resolved)
            return [resolved] + command[1:]

    return command


class MCPTransport(ABC):
    """Abstract base class for MCP transports.

    All transports provide async send/receive of JSON-RPC messages
    as Python dicts.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish the connection."""
        ...

    @abstractmethod
    async def send(self, message: dict[str, Any]) -> None:
        """Send a JSON-RPC message."""
        ...

    @abstractmethod
    async def receive(self) -> dict[str, Any]:
        """Receive a JSON-RPC message.

        Blocks until a message is available.
        """
        ...

    async def request(self, message: dict[str, Any]) -> dict[str, Any]:
        """Send a request and wait for its response.

        Default implementation uses send()/receive() for backwards compatibility.
        Subclasses may override for better semantics (e.g., HTTP request/response).

        Args:
            message: JSON-RPC request message (must have 'id' field)

        Returns:
            JSON-RPC response message
        """
        await self.send(message)
        return await self.receive()

    @abstractmethod
    async def close(self) -> None:
        """Close the transport."""
        ...

    async def __aenter__(self) -> "MCPTransport":
        """Context manager entry - connect."""
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Context manager exit - close."""
        await self.close()


class StdioTransport(MCPTransport):
    """Launch MCP server as subprocess, communicate via stdin/stdout.

    This is the primary transport for local MCP servers. The server is
    launched as a subprocess with JSON-RPC messages exchanged via
    newline-delimited JSON on stdin/stdout.

    SECURITY: By default, MCP servers receive only safe environment variables
    (PATH, HOME, USER, etc.) - NOT the full host environment. This prevents
    accidental leakage of API keys and secrets.

    To pass additional env vars to the server:
    - Use `env` parameter for explicit key-value pairs
    - Use `env_passthrough` for vars to copy from host environment

    Attributes:
        command: Command and arguments to launch the server.
        env: Explicit environment variables for the subprocess.
        env_passthrough: Names of host env vars to copy to subprocess.
        cwd: Working directory for the subprocess.
    """

    def __init__(
        self,
        command: list[str],
        env: dict[str, str] | None = None,
        env_passthrough: list[str] | None = None,
        cwd: str | None = None,
    ):
        """Initialize StdioTransport.

        Args:
            command: Command and arguments to launch the MCP server.
            env: Explicit environment variables (highest priority).
            env_passthrough: Names of host env vars to pass through.
            cwd: Working directory for the subprocess.
        """
        self._command = command
        self._explicit_env = env
        self._env_passthrough = env_passthrough
        self._cwd = cwd
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        # P1.9.6: Buffer stderr lines for error context (last 20 lines)
        self._stderr_buffer: deque[str] = deque(maxlen=20)
        # Lock for serializing I/O operations (clarity for concurrent callers)
        self._io_lock = asyncio.Lock()
        # Buffer for data read past newline (fixes multi-response buffering)
        self._read_buffer: bytes = b""

    async def connect(self) -> None:
        """Start the subprocess."""
        # Build safe environment (explicit vars + passthrough + safe defaults)
        env = build_safe_env(
            explicit_env=self._explicit_env,
            passthrough=self._env_passthrough,
        )

        # P2.0.2-P2.0.3: Resolve command for Windows (.cmd, .bat extension handling)
        resolved_command = resolve_command(self._command)

        try:
            # P2.0.5: Platform-specific process group handling
            if sys.platform == "win32":
                # Windows: CREATE_NEW_PROCESS_GROUP allows sending CTRL_BREAK_EVENT
                # P9: CREATE_NO_WINDOW prevents cmd.exe window from flashing
                self._process = await asyncio.create_subprocess_exec(
                    *resolved_command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                    cwd=self._cwd,
                    creationflags=(
                        subprocess.CREATE_NEW_PROCESS_GROUP |
                        subprocess.CREATE_NO_WINDOW
                    ),
                )
            else:
                # Unix: start_new_session creates new process group for clean termination
                self._process = await asyncio.create_subprocess_exec(
                    *resolved_command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                    cwd=self._cwd,
                    start_new_session=True,
                )
        except FileNotFoundError as e:
            raise MCPTransportError(f"MCP server command not found: {self._command[0]}") from e
        except Exception as e:
            raise MCPTransportError(f"Failed to start MCP server: {e}") from e

        # Start stderr reader (logs errors but doesn't block)
        self._stderr_task = asyncio.create_task(self._read_stderr())

    async def _read_stderr(self) -> None:
        """Read and log stderr from subprocess.

        P1.9.6: Buffers last 20 lines for error context in addition to logging.
        """
        if self._process is None or self._process.stderr is None:
            return

        while True:
            try:
                line = await self._process.stderr.readline()
                if not line:
                    break
                # Decode and strip whitespace
                text = line.decode(errors="replace").rstrip()
                if text:
                    # P1.9.6: Buffer for error context
                    self._stderr_buffer.append(text)
                    # Log at DEBUG level for debugging MCP server issues
                    logger.debug("MCP stderr [%s]: %s", self._command[0], text)
            except Exception as e:
                logger.debug("Stderr reader stopped: %s", e)
                break

    @property
    def stderr_lines(self) -> list[str]:
        """Return buffered stderr lines for error context.

        P1.9.6: Returns the last 20 lines of stderr output from the MCP server.
        Useful for providing context when errors occur.
        """
        return list(self._stderr_buffer)

    async def send(self, message: dict[str, Any]) -> None:
        """Write JSON-RPC message to stdin.

        Uses I/O lock to serialize concurrent sends.
        """
        if self._process is None or self._process.stdin is None:
            raise MCPTransportError("Transport not connected")

        async with self._io_lock:
            try:
                data = json.dumps(message, separators=(",", ":")) + "\n"
                self._process.stdin.write(data.encode("utf-8"))
                await self._process.stdin.drain()
            except Exception as e:
                raise MCPTransportError(f"Failed to send message: {e}") from e

    async def receive(self) -> dict[str, Any]:
        """Read JSON-RPC message from stdout.

        P2.12 SECURITY: Enforces MAX_STDIO_LINE_LENGTH to prevent memory
        exhaustion from extremely long lines.

        P2.0.4: Handles both LF and CRLF line endings (Windows compatibility).

        Uses I/O lock to serialize concurrent receives.
        """
        if self._process is None or self._process.stdout is None:
            raise MCPTransportError("Transport not connected")

        async with self._io_lock:
            try:
                line = await self._read_bounded_line()
                if not line:
                    # Process ended
                    returncode = self._process.returncode
                    raise MCPTransportError(f"MCP server closed (exit code: {returncode})")

                # P2.0.4: Strip CRLF/LF before JSON parsing (Windows compatibility)
                line = line.rstrip(b"\r\n")
                return json.loads(line.decode("utf-8"))
            except json.JSONDecodeError as e:
                raise MCPTransportError(f"Invalid JSON from server: {e}") from e
            except MCPTransportError:
                raise
            except Exception as e:
                raise MCPTransportError(f"Failed to receive message: {e}") from e

    async def _read_bounded_line(self) -> bytes:
        """Read a line with bounded length.

        P2.12 SECURITY: Prevents memory exhaustion by limiting line length.

        Properly buffers data read past the newline for subsequent reads.
        This is critical when multiple responses arrive in quick succession
        (common with buffered I/O, especially WSL→Windows subprocess).

        Returns:
            Line bytes (including newline if present).

        Raises:
            MCPTransportError: If line exceeds MAX_STDIO_LINE_LENGTH.
        """
        if self._process is None or self._process.stdout is None:
            return b""

        chunks: list[bytes] = []
        total_length = 0

        # Check if we have buffered data from a previous read
        if self._read_buffer:
            newline_idx = self._read_buffer.find(b"\n")
            if newline_idx >= 0:
                # Complete line in buffer - return it and update buffer
                line = self._read_buffer[: newline_idx + 1]
                self._read_buffer = self._read_buffer[newline_idx + 1 :]
                return line
            # No complete line in buffer - use it as starting chunk
            chunks.append(self._read_buffer)
            total_length = len(self._read_buffer)
            self._read_buffer = b""

        while True:
            # Read up to remaining allowed bytes or 64KB chunk
            remaining = MAX_STDIO_LINE_LENGTH - total_length
            if remaining <= 0:
                raise MCPTransportError(
                    f"MCP server line exceeds maximum length ({MAX_STDIO_LINE_LENGTH} bytes). "
                    "Server may be malfunctioning or malicious."
                )

            chunk_size = min(remaining, 65536)  # 64KB chunks
            chunk = await self._process.stdout.read(chunk_size)

            if not chunk:
                # EOF - return what we have
                return b"".join(chunks)

            # Check for newline in chunk
            newline_idx = chunk.find(b"\n")
            if newline_idx >= 0:
                # Found newline - return complete line
                chunks.append(chunk[: newline_idx + 1])
                # Buffer remaining data (after newline) for next read
                self._read_buffer = chunk[newline_idx + 1 :]
                return b"".join(chunks)

            chunks.append(chunk)
            total_length += len(chunk)

    async def close(self) -> None:
        """Terminate subprocess."""
        self._read_buffer = b""  # Clear any buffered data

        if self._stderr_task is not None:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass
            self._stderr_task = None

        if self._process is not None:
            # Close all pipes explicitly (Windows ProactorEventLoop requires this)
            # Close stdin first to signal EOF to subprocess
            if self._process.stdin is not None:
                try:
                    self._process.stdin.close()
                    await self._process.stdin.wait_closed()
                except Exception as e:
                    logger.debug("Stdin close error (expected during shutdown): %s", e)

            # Close stdout and stderr to prevent "unclosed transport" warnings on Windows
            if self._process.stdout is not None:
                try:
                    self._process.stdout.feed_eof()
                except Exception:
                    pass  # May already be closed
            if self._process.stderr is not None:
                try:
                    self._process.stderr.feed_eof()
                except Exception:
                    pass  # May already be closed

            # Give it a moment to exit gracefully
            try:
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except TimeoutError:
                # Use cross-platform process tree termination
                from nexus3.core.process import terminate_process_tree
                await terminate_process_tree(self._process)

            self._process = None

    @property
    def is_connected(self) -> bool:
        """Check if transport is connected."""
        return self._process is not None and self._process.returncode is None


class HTTPTransport(MCPTransport):
    """Connect to remote MCP server via HTTP.

    MCP over HTTP uses:
    - POST requests for client→server JSON-RPC calls
    - Synchronous responses (server responds to each POST)

    This is a simpler model than SSE - each send() is paired with
    a receive() in the same HTTP request/response cycle.

    Attributes:
        url: Base URL of the MCP server (e.g., http://localhost:9000).
        headers: Additional HTTP headers (e.g., for auth).
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff: float = DEFAULT_RETRY_BACKOFF,
    ):
        """Initialize HTTPTransport.

        Args:
            url: Base URL of the MCP server.
            headers: Additional HTTP headers (e.g., for auth).
            timeout: Request timeout in seconds.
            max_retries: Maximum number of retries for transient failures (default 3).
            retry_backoff: Base delay in seconds for exponential backoff (default 1.0).

        Raises:
            MCPTransportError: If URL is invalid or blocked (SSRF protection).
        """
        # P1: SSRF validation - allow localhost since MCP servers are often local
        try:
            validate_url(url, allow_localhost=True)
        except UrlSecurityError as e:
            raise MCPTransportError(f"Invalid MCP server URL: {e}") from e

        self._url = url.rstrip("/")
        self._headers = headers or {}
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._client: Any = None  # httpx.AsyncClient
        self._pending_response: dict[str, Any] | None = None
        # P1.8: MCP session ID tracking (returned by server, sent in subsequent requests)
        self._session_id: str | None = None

    async def connect(self) -> None:
        """Create HTTP client (connection pool)."""
        # P1.7: Include MCP protocol headers alongside Content-Type and user headers
        combined_headers = {
            "Content-Type": "application/json",
            **MCP_HTTP_HEADERS,
            **self._headers,  # User headers override defaults
        }
        self._client = httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=False,  # SECURITY: Prevent redirect-based SSRF bypass
            headers=combined_headers,
        )

    async def send(self, message: dict[str, Any]) -> None:
        """Send JSON-RPC message via HTTP POST.

        The response is stored internally for the next receive() call.
        This maintains the send/receive pattern expected by MCPClient.

        For notifications (no id), the server may return 204 No Content.

        P1.8: Includes session ID header if set, and captures session ID
        from response for subsequent requests.

        P1.10: Retries on transient failures (5xx, 429) with exponential backoff.
        """
        if self._client is None:
            raise MCPTransportError("Transport not connected")

        data = json.dumps(message, separators=(",", ":"))

        # P1.8: Include session ID in request headers if we have one
        req_headers: dict[str, str] = {}
        if self._session_id:
            req_headers["mcp-session-id"] = self._session_id

        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.post(
                    self._url, content=data, headers=req_headers if req_headers else None
                )

                # P1.10: Retry on transient failures with backoff
                if self._is_retryable_status(response.status_code) and attempt < self._max_retries:
                    delay = self._calculate_retry_delay(attempt)
                    logger.debug(
                        "HTTP %d on attempt %d, retrying in %.2fs",
                        response.status_code,
                        attempt + 1,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                response.raise_for_status()

                # P1.8: Extract and store session ID from response (with validation)
                self._capture_session_id(response.headers)

                # Handle 204 No Content (for notifications)
                if response.status_code == 204 or not response.content:
                    self._pending_response = None
                else:
                    self._pending_response = response.json()
                return

            except httpx.TransportError as e:
                last_error = e
                if attempt < self._max_retries:
                    delay = self._calculate_retry_delay(attempt)
                    logger.debug(
                        "Transport error on attempt %d (%s), retrying in %.2fs",
                        attempt + 1,
                        e,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise MCPTransportError(
                    f"HTTP request failed after {self._max_retries + 1} attempts: {e}"
                ) from e
            except Exception as e:
                raise MCPTransportError(f"HTTP request failed: {e}") from e

        # Should not reach here, but handle edge case
        if last_error:
            raise MCPTransportError(
                f"HTTP request failed after {self._max_retries + 1} attempts: {last_error}"
            ) from last_error

    async def receive(self) -> dict[str, Any]:
        """Return the response from the last send().

        HTTP transport is synchronous - each POST gets a response.
        This method returns the response that was stored by send().
        """
        if self._pending_response is None:
            raise MCPTransportError("No pending response (call send() first)")

        response = self._pending_response
        self._pending_response = None
        return response

    async def request(self, message: dict[str, Any]) -> dict[str, Any]:
        """Send request and return response directly.

        HTTP is inherently request/response, so this is more natural than
        send/receive. Unlike send(), this method does NOT use the shared
        _pending_response slot, making it safe for concurrent requests.

        P1.8: Includes session ID header if set, and captures session ID
        from response for subsequent requests.

        P1.10: Retries on transient failures (5xx, 429) with exponential backoff.

        Args:
            message: JSON-RPC request message

        Returns:
            JSON-RPC response message

        Raises:
            MCPTransportError: If transport not connected, request fails,
                              or server returns empty response for a request.
        """
        if self._client is None:
            raise MCPTransportError("Transport not connected")

        data = json.dumps(message, separators=(",", ":"))

        # P1.8: Include session ID in request headers if we have one
        req_headers: dict[str, str] = {}
        if self._session_id:
            req_headers["mcp-session-id"] = self._session_id

        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.post(
                    self._url, content=data, headers=req_headers if req_headers else None
                )

                # P1.10: Retry on transient failures with backoff
                if self._is_retryable_status(response.status_code) and attempt < self._max_retries:
                    delay = self._calculate_retry_delay(attempt)
                    logger.debug(
                        "HTTP %d on attempt %d, retrying in %.2fs",
                        response.status_code,
                        attempt + 1,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                response.raise_for_status()

                # P1.8: Extract session ID from response (with validation)
                self._capture_session_id(response.headers)

                # For requests (messages with 'id'), we expect a response body
                if response.status_code == 204 or not response.content:
                    raise MCPTransportError("Server returned empty response for request")

                return response.json()

            except httpx.TransportError as e:
                last_error = e
                if attempt < self._max_retries:
                    delay = self._calculate_retry_delay(attempt)
                    logger.debug(
                        "Transport error on attempt %d (%s), retrying in %.2fs",
                        attempt + 1,
                        e,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise MCPTransportError(
                    f"HTTP request failed after {self._max_retries + 1} attempts: {e}"
                ) from e
            except MCPTransportError:
                raise
            except Exception as e:
                raise MCPTransportError(f"HTTP request failed: {e}") from e

        # Should not reach here, but handle edge case
        if last_error:
            raise MCPTransportError(
                f"HTTP request failed after {self._max_retries + 1} attempts: {last_error}"
            ) from last_error
        raise MCPTransportError(f"HTTP request failed after {self._max_retries + 1} attempts")

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def is_connected(self) -> bool:
        """Check if transport is connected."""
        if self._client is None:
            return False
        return not self._client.is_closed

    @property
    def session_id(self) -> str | None:
        """Get the current MCP session ID (if available).

        P1.8: Session ID is returned by the server and must be included
        in subsequent requests for session continuity.
        """
        return self._session_id

    def _validate_session_id(self, session_id: str) -> bool:
        """Validate MCP session ID format.

        P1.8 SECURITY: Prevents session ID injection attacks and log pollution.
        Session IDs should be alphanumeric with optional dashes/underscores,
        and limited to MAX_SESSION_ID_LENGTH bytes.

        Args:
            session_id: The session ID string to validate.

        Returns:
            True if valid, False otherwise.
        """
        if not session_id:
            return False

        # Check length limit
        if len(session_id) > MAX_SESSION_ID_LENGTH:
            logger.warning(
                "Rejecting session ID: too long (%d > %d)",
                len(session_id),
                MAX_SESSION_ID_LENGTH,
            )
            return False

        # Check format (alphanumeric, dash, underscore only)
        if not SESSION_ID_PATTERN.match(session_id):
            logger.warning("Rejecting session ID: invalid format")
            return False

        return True

    def _capture_session_id(self, headers: Any) -> None:
        """Capture and validate session ID from response headers.

        P1.8: MCP servers may return a session ID that must be included
        in subsequent requests. This method extracts and validates it.

        Args:
            headers: Response headers (httpx.Headers or similar mapping).
        """
        session_id = headers.get("mcp-session-id")
        if session_id and self._validate_session_id(session_id):
            self._session_id = session_id

    def _is_retryable_status(self, status_code: int) -> bool:
        """Check if HTTP status code is retryable.

        P1.10: Only retry on server errors (5xx) and rate limiting (429).
        Client errors (4xx except 429) are not retried as they indicate
        a problem with the request itself.

        Args:
            status_code: HTTP response status code.

        Returns:
            True if the request should be retried.
        """
        return status_code in RETRYABLE_STATUS_CODES

    def _calculate_retry_delay(self, attempt: int) -> float:
        """Calculate retry delay with exponential backoff and jitter.

        P1.10: Uses exponential backoff (base * 2^attempt) with random
        jitter (0-10% of delay) to prevent thundering herd.

        Args:
            attempt: Current attempt number (0-indexed).

        Returns:
            Delay in seconds before next retry.
        """
        delay: float = self._retry_backoff * (2 ** attempt)
        jitter: float = random.uniform(0, 0.1 * delay)
        return delay + jitter
