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
