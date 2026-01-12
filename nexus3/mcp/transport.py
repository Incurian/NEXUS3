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
            except asyncio.TimeoutError:
                # Force terminate
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    self._process.kill()
                    await self._process.wait()

            self._process = None

    @property
    def is_connected(self) -> bool:
        """Check if transport is connected."""
        return self._process is not None and self._process.returncode is None


class HTTPTransport(MCPTransport):
    """Connect to remote MCP server via HTTP.

    Placeholder for HTTP-based MCP transport. MCP over HTTP typically
    uses Server-Sent Events (SSE) for server-to-client messages.

    Not yet implemented - stdio transport covers most use cases.
    """

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
    ):
        """Initialize HTTPTransport.

        Args:
            url: Base URL of the MCP server.
            headers: Additional HTTP headers (e.g., for auth).
        """
        self._url = url
        self._headers = headers or {}
        # Would use httpx.AsyncClient here

    async def connect(self) -> None:
        """Establish HTTP connection."""
        raise NotImplementedError("HTTP transport not yet implemented")

    async def send(self, message: dict[str, Any]) -> None:
        """Send JSON-RPC message via HTTP POST."""
        raise NotImplementedError("HTTP transport not yet implemented")

    async def receive(self) -> dict[str, Any]:
        """Receive JSON-RPC message (via SSE or polling)."""
        raise NotImplementedError("HTTP transport not yet implemented")

    async def close(self) -> None:
        """Close HTTP connection."""
        raise NotImplementedError("HTTP transport not yet implemented")
