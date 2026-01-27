"""Tests for MCPClient encapsulation - G3 MCP Encapsulation Fix.

Verifies that:
1. MCPClient exposes is_connected as a public property
2. ConnectedServer.is_alive() uses the public API, not _transport
3. is_connected behaves correctly across the client lifecycle
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from nexus3.mcp.client import MCPClient
from nexus3.mcp.registry import ConnectedServer, MCPServerConfig


class TestMCPClientIsConnected:
    """Tests for MCPClient.is_connected property."""

    def test_is_connected_false_before_connect(self) -> None:
        """MCPClient.is_connected returns False before connect()."""
        # Create a mock transport that reports not connected
        mock_transport = MagicMock()
        type(mock_transport).is_connected = PropertyMock(return_value=False)

        client = MCPClient(mock_transport)

        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_is_connected_true_after_connect(self) -> None:
        """MCPClient.is_connected returns True after connect()."""
        # Create a mock transport that will be connected after connect()
        mock_transport = MagicMock()
        mock_transport.connect = AsyncMock()
        mock_transport.send = AsyncMock()
        mock_transport.receive = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "test", "version": "1.0"},
            },
        })
        type(mock_transport).is_connected = PropertyMock(return_value=True)

        client = MCPClient(mock_transport)
        await client.connect()

        assert client.is_connected is True

    @pytest.mark.asyncio
    async def test_is_connected_false_after_close(self) -> None:
        """MCPClient.is_connected returns False after close()."""
        # Create mock transport that tracks connection state
        connected = True

        def get_connected() -> bool:
            return connected

        mock_transport = MagicMock()
        mock_transport.connect = AsyncMock()
        mock_transport.send = AsyncMock()
        mock_transport.receive = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "test", "version": "1.0"},
            },
        })

        async def do_close() -> None:
            nonlocal connected
            connected = False

        mock_transport.close = do_close
        type(mock_transport).is_connected = PropertyMock(side_effect=get_connected)

        client = MCPClient(mock_transport)
        await client.connect()
        assert client.is_connected is True

        await client.close()
        assert client.is_connected is False

    def test_is_connected_with_no_transport(self) -> None:
        """is_connected handles missing transport gracefully.

        Note: In practice, MCPClient always has a transport (set in __init__).
        This tests the defensive code path.
        """
        mock_transport = MagicMock()
        type(mock_transport).is_connected = PropertyMock(return_value=False)

        client = MCPClient(mock_transport)

        # Manually simulate no transport (edge case)
        client._transport = None  # type: ignore[assignment]

        # Should return False, not raise
        assert client.is_connected is False


class TestConnectedServerUsesPublicAPI:
    """Tests that ConnectedServer.is_alive() uses public MCPClient API."""

    def test_connected_server_uses_public_api(self) -> None:
        """ConnectedServer.is_alive() uses MCPClient.is_connected, not _transport."""
        # Create a mock client with is_connected property
        mock_client = MagicMock(spec=MCPClient)
        is_connected_mock = PropertyMock(return_value=True)
        type(mock_client).is_connected = is_connected_mock

        config = MCPServerConfig(name="test", command=["echo", "test"])
        server = ConnectedServer(config=config, client=mock_client)

        # Call is_alive and verify it uses the public API
        result = server.is_alive()

        assert result is True
        # Verify is_connected was accessed (not _transport)
        is_connected_mock.assert_called()

    def test_connected_server_is_alive_false_when_disconnected(self) -> None:
        """ConnectedServer.is_alive() returns False when client is not connected."""
        mock_client = MagicMock(spec=MCPClient)
        type(mock_client).is_connected = PropertyMock(return_value=False)

        config = MCPServerConfig(name="test", command=["echo", "test"])
        server = ConnectedServer(config=config, client=mock_client)

        result = server.is_alive()

        assert result is False

    def test_no_direct_transport_access(self) -> None:
        """Verify is_alive() does not access client._transport directly.

        This test ensures the encapsulation fix is maintained by checking
        that the _transport attribute is never accessed.
        """
        mock_client = MagicMock(spec=MCPClient)
        type(mock_client).is_connected = PropertyMock(return_value=True)

        # Add _transport as an attribute that would fail if accessed
        mock_transport = MagicMock()
        mock_transport.is_connected = PropertyMock(
            side_effect=AssertionError("_transport should not be accessed directly")
        )
        mock_client._transport = mock_transport

        config = MCPServerConfig(name="test", command=["echo", "test"])
        server = ConnectedServer(config=config, client=mock_client)

        # This should work without triggering the assertion
        result = server.is_alive()
        assert result is True


class TestIsConnectedIntegration:
    """Integration tests for is_connected across the full lifecycle."""

    @pytest.mark.asyncio
    async def test_full_lifecycle_is_connected_states(self) -> None:
        """Test is_connected reflects correct state through full lifecycle."""
        # Track connection state
        connected = False

        def get_connected() -> bool:
            return connected

        mock_transport = MagicMock()

        async def do_connect() -> None:
            nonlocal connected
            connected = True

        async def do_close() -> None:
            nonlocal connected
            connected = False

        mock_transport.connect = do_connect
        mock_transport.close = do_close
        mock_transport.send = AsyncMock()
        mock_transport.receive = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "test", "version": "1.0"},
            },
        })
        type(mock_transport).is_connected = PropertyMock(side_effect=get_connected)

        client = MCPClient(mock_transport)

        # State 1: Before connect
        assert client.is_connected is False

        # State 2: After connect
        await client.connect()
        assert client.is_connected is True
        assert client.is_initialized is True

        # State 3: After close
        await client.close()
        assert client.is_connected is False
        assert client.is_initialized is False


class TestMCPClientNotificationFormat:
    """Tests for _notify() method MCP spec compliance.

    MCP spec requires notifications to omit the 'params' field entirely
    when there are no parameters, not send an empty object.
    """

    @pytest.mark.asyncio
    async def test_notify_omits_params_when_none(self) -> None:
        """_notify() should not include params field when None."""
        sent_messages: list[dict] = []

        mock_transport = MagicMock()
        mock_transport.send = AsyncMock(side_effect=lambda msg: sent_messages.append(msg))

        client = MCPClient(mock_transport)

        # Call _notify with no params (default None)
        await client._notify("test/notification")

        assert len(sent_messages) == 1
        notification = sent_messages[0]

        # Should have jsonrpc and method, but NOT params
        assert notification == {
            "jsonrpc": "2.0",
            "method": "test/notification",
        }
        assert "params" not in notification

    @pytest.mark.asyncio
    async def test_notify_omits_params_when_empty_dict(self) -> None:
        """_notify() should not include params field when empty dict."""
        sent_messages: list[dict] = []

        mock_transport = MagicMock()
        mock_transport.send = AsyncMock(side_effect=lambda msg: sent_messages.append(msg))

        client = MCPClient(mock_transport)

        # Call _notify with empty dict (should be treated same as None)
        await client._notify("test/notification", {})

        assert len(sent_messages) == 1
        notification = sent_messages[0]

        # Should have jsonrpc and method, but NOT params
        assert notification == {
            "jsonrpc": "2.0",
            "method": "test/notification",
        }
        assert "params" not in notification

    @pytest.mark.asyncio
    async def test_notify_includes_params_when_non_empty(self) -> None:
        """_notify() should include params field when non-empty."""
        sent_messages: list[dict] = []

        mock_transport = MagicMock()
        mock_transport.send = AsyncMock(side_effect=lambda msg: sent_messages.append(msg))

        client = MCPClient(mock_transport)

        # Call _notify with actual params
        await client._notify("test/notification", {"key": "value"})

        assert len(sent_messages) == 1
        notification = sent_messages[0]

        # Should have jsonrpc, method, AND params
        assert notification == {
            "jsonrpc": "2.0",
            "method": "test/notification",
            "params": {"key": "value"},
        }

    @pytest.mark.asyncio
    async def test_initialized_notification_has_no_params(self) -> None:
        """The 'notifications/initialized' notification should have no params.

        Per MCP spec: {"jsonrpc": "2.0", "method": "notifications/initialized"}
        NOT: {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        """
        sent_messages: list[dict] = []

        mock_transport = MagicMock()
        mock_transport.connect = AsyncMock()
        mock_transport.send = AsyncMock(side_effect=lambda msg: sent_messages.append(msg))
        mock_transport.receive = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "test", "version": "1.0"},
            },
        })
        type(mock_transport).is_connected = PropertyMock(return_value=True)

        client = MCPClient(mock_transport)
        await client.connect()

        # Find the initialized notification in sent messages
        initialized_notifications = [
            msg for msg in sent_messages
            if msg.get("method") == "notifications/initialized"
        ]

        assert len(initialized_notifications) == 1
        notification = initialized_notifications[0]

        # Should NOT have params field
        assert "params" not in notification
        assert notification == {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }


class TestMCPClientPagination:
    """Tests for P1.4: tools/list pagination support."""

    @pytest.mark.asyncio
    async def test_list_tools_single_page_no_cursor(self) -> None:
        """list_tools() handles single-page response (no nextCursor)."""
        sent_messages: list[dict] = []

        mock_transport = MagicMock()
        mock_transport.send = AsyncMock(side_effect=lambda msg: sent_messages.append(msg))
        mock_transport.receive = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [
                    {"name": "tool1", "description": "Tool 1", "inputSchema": {}},
                    {"name": "tool2", "description": "Tool 2", "inputSchema": {}},
                ],
            },
        })

        client = MCPClient(mock_transport)
        client._initialized = True  # Skip initialization

        tools = await client.list_tools()

        # Should have both tools
        assert len(tools) == 2
        assert tools[0].name == "tool1"
        assert tools[1].name == "tool2"

        # Should have made one request
        assert len(sent_messages) == 1
        request = sent_messages[0]
        assert request["method"] == "tools/list"
        # No cursor param on first request
        assert "params" not in request

    @pytest.mark.asyncio
    async def test_list_tools_multi_page_pagination(self) -> None:
        """list_tools() handles multi-page response with nextCursor."""
        sent_messages: list[dict] = []
        request_id = 0

        # First page: 2 tools with nextCursor
        # Second page: 1 tool, no nextCursor
        responses = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "tools": [
                        {"name": "tool1", "description": "Tool 1", "inputSchema": {}},
                        {"name": "tool2", "description": "Tool 2", "inputSchema": {}},
                    ],
                    "nextCursor": "page2",
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "tools": [
                        {"name": "tool3", "description": "Tool 3", "inputSchema": {}},
                    ],
                },
            },
        ]

        async def mock_receive() -> dict:
            nonlocal request_id
            response = responses[request_id]
            request_id += 1
            return response

        mock_transport = MagicMock()
        mock_transport.send = AsyncMock(side_effect=lambda msg: sent_messages.append(msg))
        mock_transport.receive = mock_receive

        client = MCPClient(mock_transport)
        client._initialized = True

        tools = await client.list_tools()

        # Should have all 3 tools from both pages
        assert len(tools) == 3
        assert tools[0].name == "tool1"
        assert tools[1].name == "tool2"
        assert tools[2].name == "tool3"

        # Should have made 2 requests
        assert len(sent_messages) == 2

        # First request: no cursor param
        assert sent_messages[0]["method"] == "tools/list"
        assert "params" not in sent_messages[0]

        # Second request: includes cursor param
        assert sent_messages[1]["method"] == "tools/list"
        assert sent_messages[1]["params"] == {"cursor": "page2"}

    @pytest.mark.asyncio
    async def test_list_tools_three_pages(self) -> None:
        """list_tools() handles more than 2 pages of pagination."""
        sent_messages: list[dict] = []
        request_id = 0

        responses = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "tools": [{"name": "a", "description": "", "inputSchema": {}}],
                    "nextCursor": "cursor1",
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "tools": [{"name": "b", "description": "", "inputSchema": {}}],
                    "nextCursor": "cursor2",
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 3,
                "result": {
                    "tools": [{"name": "c", "description": "", "inputSchema": {}}],
                    # No nextCursor - end of pagination
                },
            },
        ]

        async def mock_receive() -> dict:
            nonlocal request_id
            response = responses[request_id]
            request_id += 1
            return response

        mock_transport = MagicMock()
        mock_transport.send = AsyncMock(side_effect=lambda msg: sent_messages.append(msg))
        mock_transport.receive = mock_receive

        client = MCPClient(mock_transport)
        client._initialized = True

        tools = await client.list_tools()

        assert len(tools) == 3
        assert [t.name for t in tools] == ["a", "b", "c"]

        # Should have made 3 requests with correct cursors
        assert len(sent_messages) == 3
        assert "params" not in sent_messages[0]
        assert sent_messages[1]["params"] == {"cursor": "cursor1"}
        assert sent_messages[2]["params"] == {"cursor": "cursor2"}

    @pytest.mark.asyncio
    async def test_list_tools_empty_response(self) -> None:
        """list_tools() handles empty tools list."""
        mock_transport = MagicMock()
        mock_transport.send = AsyncMock()
        mock_transport.receive = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [],
            },
        })

        client = MCPClient(mock_transport)
        client._initialized = True

        tools = await client.list_tools()

        assert len(tools) == 0

    @pytest.mark.asyncio
    async def test_list_tools_caches_result(self) -> None:
        """list_tools() caches result in _tools attribute."""
        mock_transport = MagicMock()
        mock_transport.send = AsyncMock()
        mock_transport.receive = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [
                    {"name": "cached_tool", "description": "Test", "inputSchema": {}},
                ],
            },
        })

        client = MCPClient(mock_transport)
        client._initialized = True

        tools = await client.list_tools()

        # Both return value and cached property should have the tools
        assert len(tools) == 1
        assert len(client.tools) == 1
        assert client.tools[0].name == "cached_tool"
