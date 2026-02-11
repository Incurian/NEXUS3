from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus3.ide.bridge import IDEBridge
from nexus3.ide.discovery import IDEInfo


def _make_config(enabled: bool = True, auto_connect: bool = True) -> MagicMock:
    config = MagicMock()
    config.enabled = enabled
    config.auto_connect = auto_connect
    return config


def _make_ide_info(port: int = 9999) -> IDEInfo:
    return IDEInfo(
        pid=1234,
        workspace_folders=["/test"],
        ide_name="Test IDE",
        transport="ws",
        auth_token="test-token",
        port=port,
        lock_path=Path(f"/tmp/{port}.lock"),
    )


class TestIDEBridgeAutoConnect:
    @pytest.mark.asyncio
    async def test_disabled_returns_none(self) -> None:
        bridge = IDEBridge(_make_config(enabled=False))
        result = await bridge.auto_connect(Path("/test"))
        assert result is None

    @pytest.mark.asyncio
    async def test_auto_connect_disabled_returns_none(self) -> None:
        bridge = IDEBridge(_make_config(auto_connect=False))
        result = await bridge.auto_connect(Path("/test"))
        assert result is None

    @pytest.mark.asyncio
    async def test_no_ides_returns_none(self) -> None:
        bridge = IDEBridge(_make_config())
        with patch("nexus3.ide.bridge.discover_ides", return_value=[]):
            result = await bridge.auto_connect(Path("/test"))
        assert result is None

    @pytest.mark.asyncio
    async def test_connects_to_first_ide(self) -> None:
        bridge = IDEBridge(_make_config())
        ide_info = _make_ide_info()
        mock_conn = AsyncMock()

        with (
            patch("nexus3.ide.bridge.discover_ides", return_value=[ide_info]),
            patch.object(bridge, "connect", return_value=mock_conn) as mock_connect,
        ):
            result = await bridge.auto_connect(Path("/test"))

        assert result is mock_conn
        mock_connect.assert_called_once_with(ide_info)


class TestIDEBridgeConnect:
    @pytest.mark.asyncio
    async def test_connect_creates_connection(self) -> None:
        bridge = IDEBridge(_make_config())
        ide_info = _make_ide_info()

        mock_client = AsyncMock()
        with (
            patch("nexus3.ide.bridge.WebSocketTransport") as mock_transport_cls,
            patch("nexus3.ide.bridge.MCPClient", return_value=mock_client),
        ):
            conn = await bridge.connect(ide_info)

        assert conn is not None
        assert bridge.connection is conn
        mock_transport_cls.assert_called_once_with(
            url="ws://127.0.0.1:9999",
            auth_token="test-token",
        )
        mock_client.connect.assert_called_once_with(timeout=10.0)

    @pytest.mark.asyncio
    async def test_connect_disconnects_existing(self) -> None:
        bridge = IDEBridge(_make_config())
        old_conn = AsyncMock()
        bridge._connection = old_conn

        ide_info = _make_ide_info()
        mock_client = AsyncMock()
        with (
            patch("nexus3.ide.bridge.WebSocketTransport"),
            patch("nexus3.ide.bridge.MCPClient", return_value=mock_client),
        ):
            await bridge.connect(ide_info)

        old_conn.close.assert_called_once()


class TestIDEBridgeDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect(self) -> None:
        bridge = IDEBridge(_make_config())
        mock_conn = AsyncMock()
        bridge._connection = mock_conn

        await bridge.disconnect()
        mock_conn.close.assert_called_once()
        assert bridge.connection is None

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self) -> None:
        bridge = IDEBridge(_make_config())
        await bridge.disconnect()  # Should not raise


class TestIDEBridgeReconnect:
    @pytest.mark.asyncio
    async def test_reconnect_if_dead_already_connected(self) -> None:
        """Returns True without re-discovery when already connected."""
        bridge = IDEBridge(_make_config())
        mock_conn = MagicMock()
        mock_conn.is_connected = True
        bridge._connection = mock_conn

        with patch("nexus3.ide.bridge.discover_ides") as mock_discover:
            result = await bridge.reconnect_if_dead()

        assert result is True
        mock_discover.assert_not_called()

    @pytest.mark.asyncio
    async def test_reconnect_if_dead_finds_new_ide(self) -> None:
        bridge = IDEBridge(_make_config())
        bridge._last_cwd = Path("/test")
        ide_info = _make_ide_info()

        mock_client = AsyncMock()
        with (
            patch("nexus3.ide.bridge.discover_ides", return_value=[ide_info]),
            patch("nexus3.ide.bridge.WebSocketTransport"),
            patch("nexus3.ide.bridge.MCPClient", return_value=mock_client),
        ):
            result = await bridge.reconnect_if_dead()

        assert result is True
        assert bridge.is_connected or bridge._connection is not None

    @pytest.mark.asyncio
    async def test_reconnect_if_dead_no_ides_found(self) -> None:
        bridge = IDEBridge(_make_config())
        bridge._last_cwd = Path("/test")

        with patch("nexus3.ide.bridge.discover_ides", return_value=[]):
            result = await bridge.reconnect_if_dead()

        assert result is False

    @pytest.mark.asyncio
    async def test_reconnect_if_dead_connect_fails(self) -> None:
        bridge = IDEBridge(_make_config())
        bridge._last_cwd = Path("/test")
        ide_info = _make_ide_info()

        mock_client = AsyncMock()
        mock_client.connect.side_effect = ConnectionError("refused")
        with (
            patch("nexus3.ide.bridge.discover_ides", return_value=[ide_info]),
            patch("nexus3.ide.bridge.WebSocketTransport"),
            patch("nexus3.ide.bridge.MCPClient", return_value=mock_client),
        ):
            result = await bridge.reconnect_if_dead()

        assert result is False

    @pytest.mark.asyncio
    async def test_reconnect_if_dead_no_cwd(self) -> None:
        """Returns False when no cwd is available for re-discovery."""
        bridge = IDEBridge(_make_config())
        result = await bridge.reconnect_if_dead()
        assert result is False

    @pytest.mark.asyncio
    async def test_reconnect_if_dead_uses_explicit_cwd(self) -> None:
        """Prefers explicit cwd over stored _last_cwd."""
        bridge = IDEBridge(_make_config())
        bridge._last_cwd = Path("/old")
        ide_info = _make_ide_info()

        with (
            patch("nexus3.ide.bridge.discover_ides", return_value=[ide_info]) as mock_discover,
            patch.object(bridge, "connect", new_callable=AsyncMock),
        ):
            await bridge.reconnect_if_dead(cwd=Path("/new"))

        mock_discover.assert_called_once_with(Path("/new"))

    @pytest.mark.asyncio
    async def test_reconnect_cleans_up_old_connection(self) -> None:
        """Old dead connection is disconnected before re-discovery."""
        bridge = IDEBridge(_make_config())
        bridge._last_cwd = Path("/test")
        old_conn = MagicMock()
        old_conn.is_connected = False
        old_conn.close = AsyncMock()
        bridge._connection = old_conn

        with patch("nexus3.ide.bridge.discover_ides", return_value=[]):
            await bridge.reconnect_if_dead()

        old_conn.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_connect_stores_last_cwd(self) -> None:
        bridge = IDEBridge(_make_config())
        ide_info = _make_ide_info()

        with (
            patch("nexus3.ide.bridge.discover_ides", return_value=[ide_info]),
            patch.object(bridge, "connect", new_callable=AsyncMock),
        ):
            await bridge.auto_connect(Path("/my/project"))

        assert bridge._last_cwd == Path("/my/project")

    @pytest.mark.asyncio
    async def test_auto_connect_stores_cwd_even_when_no_ides(self) -> None:
        bridge = IDEBridge(_make_config())
        with patch("nexus3.ide.bridge.discover_ides", return_value=[]):
            await bridge.auto_connect(Path("/my/project"))
        assert bridge._last_cwd == Path("/my/project")


class TestIDEBridgeProperties:
    def test_is_connected_false_when_none(self) -> None:
        bridge = IDEBridge(_make_config())
        assert bridge.is_connected is False

    def test_is_connected_delegates(self) -> None:
        bridge = IDEBridge(_make_config())
        mock_conn = MagicMock()
        mock_conn.is_connected = True
        bridge._connection = mock_conn
        assert bridge.is_connected is True
