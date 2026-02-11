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
    config.lock_dir_path = None
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
