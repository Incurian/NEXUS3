"""MCP transport layer.

Provides transport implementations for MCP communication:
- StdioTransport: Launch MCP server as subprocess, communicate via stdin/stdout
- HTTPTransport: Connect to remote MCP server via HTTP (placeholder)

MCP uses newline-delimited JSON-RPC 2.0 messages.
"""

import asyncio
import json
import os
from abc import ABC, abstractmethod
from typing import Any

from nexus3.core.errors import NexusError


class MCPTransportError(NexusError):
    """Error in MCP transport layer."""


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

    Attributes:
        command: Command and arguments to launch the server.
        env: Additional environment variables for the subprocess.
        cwd: Working directory for the subprocess.
    """

    def __init__(
        self,
        command: list[str],
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ):
        """Initialize StdioTransport.

        Args:
            command: Command and arguments to launch the MCP server.
            env: Additional environment variables (merged with current env).
            cwd: Working directory for the subprocess.
        """
        self._command = command
        self._extra_env = env or {}
        self._cwd = cwd
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        """Start the subprocess."""
        # Merge environment
        env = os.environ.copy()
        env.update(self._extra_env)

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
                # Could log this somewhere, for now just discard
                # In future, could emit to a callback
            except Exception:
                break

    async def send(self, message: dict[str, Any]) -> None:
        """Write JSON-RPC message to stdin."""
        if self._process is None or self._process.stdin is None:
            raise MCPTransportError("Transport not connected")

        try:
            data = json.dumps(message, separators=(",", ":")) + "\n"
            self._process.stdin.write(data.encode("utf-8"))
            await self._process.stdin.drain()
        except Exception as e:
            raise MCPTransportError(f"Failed to send message: {e}") from e

    async def receive(self) -> dict[str, Any]:
        """Read JSON-RPC message from stdout."""
        if self._process is None or self._process.stdout is None:
            raise MCPTransportError("Transport not connected")

        try:
            line = await self._process.stdout.readline()
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
                except Exception:
                    pass

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
        """
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

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def is_connected(self) -> bool:
        """Check if transport is connected."""
        return self._client is not None
