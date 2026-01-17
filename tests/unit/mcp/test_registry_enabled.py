"""Tests for MCPServerRegistry enabled flag checking (BL-4).

Verifies that connect() refuses to connect to disabled servers.
"""

import pytest

from nexus3.core.errors import MCPConfigError
from nexus3.mcp.registry import MCPServerConfig, MCPServerRegistry


class TestRegistryEnabledFlag:
    """Test that connect() respects the enabled flag."""

    @pytest.mark.asyncio
    async def test_connect_raises_on_disabled_server(self) -> None:
        """Verify MCPConfigError when enabled=False."""
        registry = MCPServerRegistry()
        config = MCPServerConfig(
            name="disabled-server",
            command=["echo", "hello"],
            enabled=False,
        )

        with pytest.raises(MCPConfigError, match="disabled in configuration"):
            await registry.connect(config)

    @pytest.mark.asyncio
    async def test_connect_raises_on_disabled_http_server(self) -> None:
        """Verify MCPConfigError for disabled HTTP server."""
        registry = MCPServerRegistry()
        config = MCPServerConfig(
            name="disabled-http",
            url="http://localhost:9999",
            enabled=False,
        )

        with pytest.raises(MCPConfigError, match="'disabled-http' is disabled"):
            await registry.connect(config)

    @pytest.mark.asyncio
    async def test_connect_error_message_includes_server_name(self) -> None:
        """Verify error message includes the server name."""
        registry = MCPServerRegistry()
        config = MCPServerConfig(
            name="my-special-server",
            command=["test"],
            enabled=False,
        )

        with pytest.raises(MCPConfigError) as exc_info:
            await registry.connect(config)

        assert "my-special-server" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_disabled_check_happens_before_disconnect(self) -> None:
        """Verify disabled check happens before disconnecting existing server.

        If a server with the same name exists, we should NOT disconnect it
        if the new config is disabled.
        """
        registry = MCPServerRegistry()

        # Manually add a "connected" server to registry internals
        # This tests that the enabled check happens BEFORE the disconnect
        from unittest.mock import AsyncMock, MagicMock

        mock_client = MagicMock()
        mock_client.close = AsyncMock()

        from nexus3.mcp.registry import ConnectedServer

        existing = ConnectedServer(
            config=MCPServerConfig(name="test-server", command=["old"]),
            client=mock_client,
            skills=[],
        )
        registry._servers["test-server"] = existing

        # Try to connect with disabled config
        disabled_config = MCPServerConfig(
            name="test-server",
            command=["new"],
            enabled=False,
        )

        with pytest.raises(MCPConfigError, match="disabled"):
            await registry.connect(disabled_config)

        # The existing server should NOT have been disconnected
        assert "test-server" in registry._servers
        mock_client.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_enabled_true_proceeds_to_connect(self) -> None:
        """Verify connection proceeds when enabled=True (mocked transport)."""
        from unittest.mock import AsyncMock, MagicMock, patch

        registry = MCPServerRegistry()
        config = MCPServerConfig(
            name="enabled-server",
            command=["echo", "hello"],
            enabled=True,
        )

        # Mock the transport and client to avoid real connections
        mock_transport = MagicMock()
        mock_client = MagicMock()
        mock_client.connect = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[])

        with patch("nexus3.mcp.registry.StdioTransport", return_value=mock_transport):
            with patch("nexus3.mcp.registry.MCPClient", return_value=mock_client):
                server = await registry.connect(config)

        # Verify we got a connected server
        assert server.config.name == "enabled-server"
        assert "enabled-server" in registry._servers
        mock_client.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_enabled_default_is_true(self) -> None:
        """Verify that enabled defaults to True in MCPServerConfig."""
        config = MCPServerConfig(name="test", command=["echo"])
        assert config.enabled is True
