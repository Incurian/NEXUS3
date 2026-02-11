from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus3.ide.transport import WebSocketTransport


class TestWebSocketTransport:
    @pytest.mark.asyncio
    async def test_connect_sends_auth_header(self) -> None:
        mock_ws = AsyncMock()
        mock_ws.__aiter__ = AsyncMock(return_value=iter([]))
        mock_ws.protocol = MagicMock()

        async def fake_connect(*args, **kwargs):  # noqa: ANN002, ANN003
            return mock_ws

        with patch("nexus3.ide.transport.websockets.connect", side_effect=fake_connect) as mock_connect:
            transport = WebSocketTransport("ws://127.0.0.1:9999", "my-token")
            await transport.connect()

        mock_connect.assert_called_once_with(
            "ws://127.0.0.1:9999",
            additional_headers={"x-nexus3-ide-authorization": "my-token"},
            ping_interval=30,
            ping_timeout=10,
        )

    @pytest.mark.asyncio
    async def test_send_json(self) -> None:
        transport = WebSocketTransport("ws://127.0.0.1:9999", "token")
        transport._ws = AsyncMock()

        await transport.send({"method": "test", "params": {}})
        transport._ws.send.assert_called_once_with('{"method":"test","params":{}}')

    @pytest.mark.asyncio
    async def test_receive_from_queue(self) -> None:
        transport = WebSocketTransport("ws://127.0.0.1:9999", "token")
        msg = {"jsonrpc": "2.0", "id": 1, "result": {}}
        await transport._receive_queue.put(msg)

        received = await transport.receive()
        assert received == msg

    @pytest.mark.asyncio
    async def test_close_cleans_up(self) -> None:
        transport = WebSocketTransport("ws://127.0.0.1:9999", "token")
        transport._ws = AsyncMock()
        mock_task = MagicMock()
        transport._listener_task = mock_task

        await transport.close()
        assert transport._ws is None
        assert transport._listener_task is None
        mock_task.cancel.assert_called_once()

    def test_is_connected_false_when_no_ws(self) -> None:
        transport = WebSocketTransport("ws://127.0.0.1:9999", "token")
        assert transport.is_connected is False

    def test_is_connected_true(self) -> None:
        transport = WebSocketTransport("ws://127.0.0.1:9999", "token")
        transport._ws = MagicMock()
        transport._ws.protocol = MagicMock()
        assert transport.is_connected is True

    def test_is_connected_false_no_protocol(self) -> None:
        transport = WebSocketTransport("ws://127.0.0.1:9999", "token")
        transport._ws = MagicMock()
        transport._ws.protocol = None
        assert transport.is_connected is False
