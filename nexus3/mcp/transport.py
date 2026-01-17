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
from abc import ABC, abstractmethod
from typing import Any

from nexus3.core.errors import NexusError
from nexus3.core.url_validator import UrlSecurityError, validate_url

logger = logging.getLogger(__name__)


class MCPTransportError(NexusError):
    """Error in MCP transport layer."""


# P2.12 SECURITY: Maximum line length for stdio transport.
# Prevents memory exhaustion from malicious/buggy servers.
# 10MB should be generous for any legitimate MCP message.
MAX_STDIO_LINE_LENGTH: int = 10 * 1024 * 1024  # 10 MB


# Environment variables always safe to pass to MCP servers.
# These are essential for subprocess execution but don't contain secrets.
SAFE_ENV_KEYS: frozenset[str] = frozenset({
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
    "TMP",        # Windows temp directory
    "TEMP",       # Windows temp directory
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
        # Lock for serializing I/O operations (clarity for concurrent callers)
        self._io_lock = asyncio.Lock()

    async def connect(self) -> None:
        """Start the subprocess."""
        # Build safe environment (explicit vars + passthrough + safe defaults)
        env = build_safe_env(
            explicit_env=self._explicit_env,
            passthrough=self._env_passthrough,
        )

        try:
            self._process = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=self._cwd,
            )
        except FileNotFoundError as e:
            raise MCPTransportError(f"MCP server command not found: {self._command[0]}") from e
        except Exception as e:
            raise MCPTransportError(f"Failed to start MCP server: {e}") from e

        # Start stderr reader (logs errors but doesn't block)
        self._stderr_task = asyncio.create_task(self._read_stderr())

    async def _read_stderr(self) -> None:
        """Read and log stderr from subprocess."""
        if self._process is None or self._process.stderr is None:
            return

        while True:
            try:
                line = await self._process.stderr.readline()
                if not line:
                    break
                # Log at DEBUG level for debugging MCP server issues
                text = line.decode(errors="replace").rstrip()
                if text:
                    logger.debug("MCP stderr [%s]: %s", self._command[0], text)
            except Exception as e:
                logger.debug("Stderr reader stopped: %s", e)
                break

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

        Returns:
            Line bytes (including newline if present).

        Raises:
            MCPTransportError: If line exceeds MAX_STDIO_LINE_LENGTH.
        """
        if self._process is None or self._process.stdout is None:
            return b""

        chunks: list[bytes] = []
        total_length = 0

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
                # Put back remaining data (after newline)
                # Note: asyncio.StreamReader doesn't support unread, but in
                # practice MCP messages are one-per-line so this is fine
                return b"".join(chunks)

            chunks.append(chunk)
            total_length += len(chunk)

    async def close(self) -> None:
        """Terminate subprocess."""
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass
            self._stderr_task = None

        if self._process is not None:
            # Try graceful shutdown first
            if self._process.stdin is not None:
                try:
                    self._process.stdin.close()
                    await self._process.stdin.wait_closed()
                except Exception as e:
                    logger.debug("Stdin close error (expected during shutdown): %s", e)

            # Give it a moment to exit
            try:
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except TimeoutError:
                # Force terminate
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=2.0)
                except TimeoutError:
                    self._process.kill()
                    await self._process.wait()

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
    ):
        """Initialize HTTPTransport.

        Args:
            url: Base URL of the MCP server.
            headers: Additional HTTP headers (e.g., for auth).
            timeout: Request timeout in seconds.

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
        self._client: Any = None  # httpx.AsyncClient
        self._pending_response: dict[str, Any] | None = None

    async def connect(self) -> None:
        """Create HTTP client (connection pool)."""
        try:
            import httpx
        except ImportError as e:
            raise MCPTransportError("httpx required for HTTP transport: pip install httpx") from e

        self._client = httpx.AsyncClient(
            timeout=self._timeout,
            headers={"Content-Type": "application/json", **self._headers},
        )

    async def send(self, message: dict[str, Any]) -> None:
        """Send JSON-RPC message via HTTP POST.

        The response is stored internally for the next receive() call.
        This maintains the send/receive pattern expected by MCPClient.

        For notifications (no id), the server may return 204 No Content.
        """
        if self._client is None:
            raise MCPTransportError("Transport not connected")

        try:
            data = json.dumps(message, separators=(",", ":"))
            response = await self._client.post(self._url, content=data)
            response.raise_for_status()

            # Handle 204 No Content (for notifications)
            if response.status_code == 204 or not response.content:
                self._pending_response = None
            else:
                self._pending_response = response.json()
        except Exception as e:
            raise MCPTransportError(f"HTTP request failed: {e}") from e

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

        try:
            data = json.dumps(message, separators=(",", ":"))
            response = await self._client.post(self._url, content=data)
            response.raise_for_status()

            # For requests (messages with 'id'), we expect a response body
            if response.status_code == 204 or not response.content:
                raise MCPTransportError("Server returned empty response for request")

            return response.json()
        except MCPTransportError:
            raise
        except Exception as e:
            raise MCPTransportError(f"HTTP request failed: {e}") from e

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def is_connected(self) -> bool:
        """Check if transport is connected."""
        return self._client is not None
