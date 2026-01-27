"""Tests for MCPServerRegistry and ConnectedServer.

Tests registry operations including reconnection and skill refresh.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from nexus3.mcp.protocol import MCPTool
from nexus3.mcp.registry import ConnectedServer, MCPServerConfig, MCPServerRegistry


class TestConnectedServerReconnect:
    """Tests for ConnectedServer.reconnect() method."""

    @pytest.mark.asyncio
    async def test_reconnect_calls_client_reconnect(self) -> None:
        """Verify reconnect() delegates to client.reconnect()."""
        mock_client = MagicMock()
        mock_client.reconnect = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[])
        mock_client.is_connected = True

        config = MCPServerConfig(name="test-server", command=["echo", "hello"])
        server = ConnectedServer(
            config=config,
            client=mock_client,
            skills=[],
        )

        # Call reconnect
        await server.reconnect(timeout=45.0)

        # Verify client.reconnect was called with correct timeout
        mock_client.reconnect.assert_called_once_with(timeout=45.0)
        mock_client.list_tools.assert_called_once()

    @pytest.mark.asyncio
    async def test_reconnect_refreshes_skills(self) -> None:
        """Verify reconnect() re-fetches tools and updates skills."""
        # Create mock tools
        tool1 = MCPTool(name="echo", description="Echo a message")
        tool2 = MCPTool(name="add", description="Add two numbers")

        mock_client = MagicMock()
        mock_client.reconnect = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[tool1, tool2])
        mock_client.is_connected = True

        config = MCPServerConfig(name="test-server", command=["echo", "hello"])
        server = ConnectedServer(
            config=config,
            client=mock_client,
            skills=[],  # Start with no skills
        )

        # Call reconnect
        await server.reconnect()

        # Verify skills were created from new tools
        assert len(server.skills) == 2
        assert server.skills[0].name == "mcp_test-server_echo"
        assert server.skills[1].name == "mcp_test-server_add"

    @pytest.mark.asyncio
    async def test_reconnect_replaces_old_skills(self) -> None:
        """Verify reconnect() replaces old skills with new ones."""
        # Initial tool
        old_tool = MCPTool(name="old", description="Old tool")

        # New tools after reconnect
        new_tool1 = MCPTool(name="new1", description="New tool 1")
        new_tool2 = MCPTool(name="new2", description="New tool 2")

        mock_client = MagicMock()
        mock_client.reconnect = AsyncMock()
        # Return different tools on second call
        mock_client.list_tools = AsyncMock(return_value=[new_tool1, new_tool2])
        mock_client.is_connected = True

        config = MCPServerConfig(name="test-server", command=["echo", "hello"])

        # Manually create skill adapter for old tool to simulate existing state
        from nexus3.mcp.skill_adapter import MCPSkillAdapter
        old_skill = MCPSkillAdapter(mock_client, old_tool, "test-server")

        server = ConnectedServer(
            config=config,
            client=mock_client,
            skills=[old_skill],
        )

        # Verify we start with 1 skill
        assert len(server.skills) == 1
        assert server.skills[0].name == "mcp_test-server_old"

        # Call reconnect
        await server.reconnect()

        # Verify skills were replaced with new tools
        assert len(server.skills) == 2
        assert server.skills[0].name == "mcp_test-server_new1"
        assert server.skills[1].name == "mcp_test-server_new2"

    @pytest.mark.asyncio
    async def test_reconnect_after_connection_dead(self) -> None:
        """Verify reconnect() works even if connection is dead."""
        mock_client = MagicMock()
        mock_client.reconnect = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[])

        config = MCPServerConfig(name="test-server", command=["echo", "hello"])
        server = ConnectedServer(
            config=config,
            client=mock_client,
            skills=[],
        )

        # Simulate dead connection
        mock_client.is_connected = False
        assert not server.is_alive()

        # Call reconnect
        await server.reconnect()

        # After reconnect, mark as alive
        mock_client.is_connected = True
        assert server.is_alive()

        # Verify reconnect was called
        mock_client.reconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_reconnect_uses_default_timeout(self) -> None:
        """Verify reconnect() uses 30s default timeout when not specified."""
        mock_client = MagicMock()
        mock_client.reconnect = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[])

        config = MCPServerConfig(name="test-server", command=["echo", "hello"])
        server = ConnectedServer(
            config=config,
            client=mock_client,
            skills=[],
        )

        # Call reconnect without timeout argument
        await server.reconnect()

        # Verify default timeout was used
        mock_client.reconnect.assert_called_once_with(timeout=30.0)


class TestRegistryReconnect:
    """Tests for registry-based reconnection scenarios."""

    @pytest.mark.asyncio
    async def test_registry_get_returns_reconnected_server(self) -> None:
        """Verify registry.get() returns server after reconnection."""
        from unittest.mock import patch

        registry = MCPServerRegistry()
        config = MCPServerConfig(name="test-server", command=["echo", "hello"])

        # Mock transport and client
        mock_transport = MagicMock()
        mock_client = MagicMock()
        mock_client.connect = AsyncMock()
        mock_client.reconnect = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[])
        mock_client.is_connected = True

        with patch("nexus3.mcp.registry.StdioTransport", return_value=mock_transport):
            with patch("nexus3.mcp.registry.MCPClient", return_value=mock_client):
                # Connect server
                server = await registry.connect(config)

                # Simulate connection dying
                mock_client.is_connected = False

                # Reconnect
                await server.reconnect()
                mock_client.is_connected = True

                # Verify we can still get it from registry
                retrieved = registry.get("test-server")
                assert retrieved is not None
                assert retrieved.is_alive()
                assert retrieved is server  # Same instance

    @pytest.mark.asyncio
    async def test_registry_check_connections_before_reconnect(self) -> None:
        """Verify check_connections() detects dead servers before manual reconnect."""
        from unittest.mock import patch

        registry = MCPServerRegistry()
        config = MCPServerConfig(name="test-server", command=["echo", "hello"])

        # Mock transport and client
        mock_transport = MagicMock()
        mock_client = MagicMock()
        mock_client.connect = AsyncMock()
        mock_client.reconnect = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[])
        mock_client.close = AsyncMock()
        mock_client.is_connected = True

        with patch("nexus3.mcp.registry.StdioTransport", return_value=mock_transport):
            with patch("nexus3.mcp.registry.MCPClient", return_value=mock_client):
                # Connect server
                server = await registry.connect(config)
                assert len(registry) == 1

                # Simulate connection dying
                mock_client.is_connected = False

                # Check connections should remove dead server
                dead = await registry.check_connections()
                assert dead == ["test-server"]
                assert len(registry) == 0
