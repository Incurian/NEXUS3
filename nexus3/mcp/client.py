"""MCP client implementation.

The MCPClient handles the MCP protocol lifecycle:
1. Connect to server via transport
2. Perform initialization handshake
3. Discover available tools
4. Execute tool calls
5. Clean shutdown

P2.9 SECURITY: Response ID matching - verifies response IDs match request IDs
to prevent response confusion attacks from malicious/buggy servers.

P2.10 SECURITY: Notification discarding - discards server notifications while
waiting for RPC responses to prevent response stream poisoning.

Usage:
    transport = StdioTransport(["python", "-m", "some_server"])
    async with MCPClient(transport) as client:
        tools = await client.list_tools()
        result = await client.call_tool("echo", {"message": "hello"})
"""

import asyncio
import logging
from typing import Any

from nexus3.core.errors import NexusError
from nexus3.mcp.protocol import (
    PROTOCOL_VERSION,
    MCPClientInfo,
    MCPPrompt,
    MCPPromptResult,
    MCPResource,
    MCPResourceContent,
    MCPServerInfo,
    MCPTool,
    MCPToolResult,
)
from nexus3.mcp.transport import MCPTransport

logger = logging.getLogger(__name__)

# P2.10 SECURITY: Maximum notifications to discard while waiting for a response.
# Prevents infinite loop from servers that only send notifications.
MAX_NOTIFICATIONS_TO_DISCARD: int = 100


class MCPError(NexusError):
    """Error from MCP protocol or server.

    Attributes:
        code: JSON-RPC error code (if from server).
        message: Human-readable error message.
    """

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class MCPClient:
    """Client for connecting to MCP servers.

    Handles the MCP protocol lifecycle including initialization,
    tool discovery, and tool invocation.

    Attributes:
        server_info: Information about the connected server.
        tools: List of available tools after list_tools() is called.
    """

    def __init__(
        self,
        transport: MCPTransport,
        client_info: MCPClientInfo | None = None,
    ):
        """Initialize MCP client.

        Args:
            transport: Transport layer for communication.
            client_info: Client identification (defaults to nexus3).
        """
        self._transport = transport
        self._client_info = client_info or MCPClientInfo()
        self._request_id = 0
        self._server_info: MCPServerInfo | None = None
        self._tools: list[MCPTool] = []
        self._resources: list[MCPResource] = []
        self._prompts: list[MCPPrompt] = []
        self._initialized = False

    async def connect(self, timeout: float = 30.0) -> None:
        """Connect to the server and perform initialization handshake.

        Call this directly when not using the context manager pattern.

        Args:
            timeout: Maximum time to wait for connection and initialization.
                     Default 30 seconds. Use 0 for no timeout.

        Raises:
            MCPError: If connection times out or fails.
        """
        async def _do_connect() -> None:
            await self._transport.connect()
            await self._initialize()

        if timeout > 0:
            try:
                await asyncio.wait_for(_do_connect(), timeout=timeout)
            except TimeoutError:
                # Try to clean up transport
                try:
                    await self._transport.close()
                except Exception as cleanup_err:
                    logger.warning(
                        "Failed to close transport during timeout cleanup: %s",
                        cleanup_err,
                    )
                raise MCPError(f"MCP connection timed out after {timeout}s") from None
        else:
            await _do_connect()

    async def close(self) -> None:
        """Close the connection to the server.

        Call this directly when not using the context manager pattern.
        """
        await self._transport.close()
        self._initialized = False

    async def reconnect(self, timeout: float = 30.0) -> None:
        """Close and reconnect to the server.

        Useful for recovering from stale connections without recreating
        the client object.

        Args:
            timeout: Maximum time to wait for reconnection. Default 30s.

        Raises:
            MCPError: If reconnection fails.
        """
        await self.close()
        await self.connect(timeout=timeout)

    async def ping(self) -> float:
        """Ping the server to check connectivity and measure latency.

        Returns:
            Round-trip time in milliseconds.

        Raises:
            MCPError: If server doesn't respond or returns error.
        """
        import time
        start = time.perf_counter()
        await self._call("ping")
        elapsed = time.perf_counter() - start
        return elapsed * 1000  # Convert to milliseconds

    async def __aenter__(self) -> "MCPClient":
        """Connect and initialize."""
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Close connection."""
        await self.close()

    async def _initialize(self) -> None:
        """Perform MCP initialization handshake.

        Sends initialize request, waits for response, then sends
        initialized notification.
        """
        # Send initialize request
        response = await self._call(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": self._client_info.to_dict(),
            },
        )

        # Parse server info
        self._server_info = MCPServerInfo.from_dict(response)

        # Send initialized notification (no response expected)
        await self._notify("notifications/initialized")

        self._initialized = True

    async def _call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make JSON-RPC call and wait for response.

        P2.9 SECURITY: Verifies response ID matches request ID.
        P2.10 SECURITY: Discards notifications while waiting for response.

        Note: We use send()/receive() pattern instead of request() to support
        notification discarding for stdio transport. HTTP transport's request()
        returns responses directly and doesn't need this loop, but stdio servers
        can interleave notifications. This pattern works for both transports.

        Args:
            method: RPC method name.
            params: Method parameters. If None or empty, params field is omitted.

        Returns:
            The 'result' field from the response.

        Raises:
            MCPError: If the server returns an error, response ID mismatches,
                     or too many notifications are received.
        """
        self._request_id += 1
        expected_id = self._request_id
        request: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": expected_id,
            "method": method,
        }
        if params:
            request["params"] = params

        await self._transport.send(request)

        # P2.10 SECURITY: Loop to discard notifications and find our response
        notifications_discarded = 0
        while True:
            response = await self._transport.receive()

            # P2.10 SECURITY: Discard notifications (messages without "id")
            # Notifications have "method" but no "id" field
            if "id" not in response and "method" in response:
                notifications_discarded += 1
                logger.debug(
                    "Discarded MCP notification while waiting for response: %s",
                    response.get("method"),
                )
                if notifications_discarded > MAX_NOTIFICATIONS_TO_DISCARD:
                    raise MCPError(
                        f"Received too many notifications ({notifications_discarded}) "
                        f"while waiting for response to request {expected_id}. "
                        "Server may be malfunctioning."
                    )
                continue

            # Discard error responses with null id (from non-compliant servers
            # that respond to notifications instead of ignoring them)
            if response.get("id") is None and "error" in response:
                notifications_discarded += 1
                logger.debug(
                    "Discarded null-id error response (likely notification error): %s",
                    response.get("error", {}).get("message", "unknown"),
                )
                if notifications_discarded > MAX_NOTIFICATIONS_TO_DISCARD:
                    raise MCPError(
                        f"Received too many spurious responses ({notifications_discarded}) "
                        f"while waiting for response to request {expected_id}. "
                        "Server may be malfunctioning."
                    )
                continue

            # P2.9 SECURITY: Verify response ID matches request ID
            response_id = response.get("id")
            if response_id != expected_id:
                raise MCPError(
                    f"Response ID mismatch: expected {expected_id}, got {response_id}. "
                    "Server may be malfunctioning or malicious."
                )

            # Found our response
            break

        # Handle error response
        if "error" in response:
            error = response["error"]
            raise MCPError(
                message=error.get("message", "Unknown error"),
                code=error.get("code"),
            )

        return response.get("result", {})

    async def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send notification (no response expected).

        Args:
            method: Notification method name.
            params: Notification parameters. Omitted from message if None or empty.
        """
        notification: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params:  # Only include if non-empty
            notification["params"] = params
        await self._transport.send(notification)

    async def list_tools(self) -> list[MCPTool]:
        """Discover available tools from server.

        Fetches and caches the list of tools the server provides.
        Handles pagination per MCP spec - loops until no nextCursor returned.

        Returns:
            List of available tools.

        Raises:
            MCPError: If the server returns an error.
        """
        all_tools: list[MCPTool] = []
        cursor: str | None = None

        while True:
            params: dict[str, Any] | None = None
            if cursor:
                params = {"cursor": cursor}

            result = await self._call("tools/list", params)

            tools_data = result.get("tools", [])
            all_tools.extend(MCPTool.from_dict(t) for t in tools_data)

            cursor = result.get("nextCursor")
            if not cursor:
                break

        self._tools = all_tools
        return self._tools

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> MCPToolResult:
        """Invoke a tool on the server.

        Args:
            name: Name of the tool to invoke.
            arguments: Tool arguments (empty dict if None).

        Returns:
            The tool result.

        Raises:
            MCPError: If the server returns an error.
        """
        result = await self._call(
            "tools/call",
            {
                "name": name,
                "arguments": arguments or {},
            },
        )

        return MCPToolResult.from_dict(result)

    async def list_resources(self) -> list[MCPResource]:
        """Discover available resources from server.

        Fetches and caches the list of resources the server provides.
        Handles pagination per MCP spec - loops until no nextCursor returned.

        Returns:
            List of available resources.

        Raises:
            MCPError: If the server returns an error.
        """
        all_resources: list[MCPResource] = []
        cursor: str | None = None

        while True:
            params: dict[str, Any] | None = None
            if cursor:
                params = {"cursor": cursor}

            result = await self._call("resources/list", params)

            resources_data = result.get("resources", [])
            all_resources.extend(MCPResource.from_dict(r) for r in resources_data)

            cursor = result.get("nextCursor")
            if not cursor:
                break

        self._resources = all_resources
        return self._resources

    async def read_resource(self, uri: str) -> list[MCPResourceContent]:
        """Read content of a resource.

        Args:
            uri: URI of the resource to read.

        Returns:
            List of resource content items (usually one).

        Raises:
            MCPError: If resource not found or read fails.
        """
        result = await self._call("resources/read", {"uri": uri})
        contents_data = result.get("contents", [])
        return [MCPResourceContent.from_dict(c) for c in contents_data]

    async def list_prompts(self) -> list[MCPPrompt]:
        """Discover available prompts from server.

        Fetches and caches the list of prompts the server provides.
        Handles pagination per MCP spec - loops until no nextCursor returned.

        Returns:
            List of available prompts.

        Raises:
            MCPError: If the server returns an error.
        """
        all_prompts: list[MCPPrompt] = []
        cursor: str | None = None

        while True:
            params: dict[str, Any] | None = None
            if cursor:
                params = {"cursor": cursor}

            result = await self._call("prompts/list", params)

            prompts_data = result.get("prompts", [])
            all_prompts.extend(MCPPrompt.from_dict(p) for p in prompts_data)

            cursor = result.get("nextCursor")
            if not cursor:
                break

        self._prompts = all_prompts
        return self._prompts

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> MCPPromptResult:
        """Get a prompt with filled arguments.

        Args:
            name: Name of the prompt to get.
            arguments: Arguments to fill into the prompt template.

        Returns:
            Prompt result with filled messages.

        Raises:
            MCPError: If prompt not found or arguments invalid.
        """
        params: dict[str, Any] = {"name": name}
        if arguments:
            params["arguments"] = arguments

        result = await self._call("prompts/get", params)
        return MCPPromptResult.from_dict(result)

    @property
    def server_info(self) -> MCPServerInfo | None:
        """Get server information (available after initialization)."""
        return self._server_info

    @property
    def tools(self) -> list[MCPTool]:
        """Get cached tools (call list_tools() first)."""
        return self._tools

    @property
    def resources(self) -> list[MCPResource]:
        """Get cached resources (call list_resources() first)."""
        return self._resources

    @property
    def prompts(self) -> list[MCPPrompt]:
        """Get cached prompts (call list_prompts() first)."""
        return self._prompts

    @property
    def is_initialized(self) -> bool:
        """Check if client has completed initialization."""
        return self._initialized

    @property
    def is_connected(self) -> bool:
        """Check if the transport is connected.

        Returns:
            True if transport exists and is connected.
        """
        return self._transport.is_connected if self._transport else False
