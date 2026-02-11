from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection

from nexus3.mcp.transport import MCPTransport

logger = logging.getLogger(__name__)


class WebSocketTransport(MCPTransport):
    """WebSocket transport for IDE MCP communication."""

    def __init__(self, url: str, auth_token: str) -> None:
        self._url = url
        self._auth_token = auth_token
        self._ws: ClientConnection | None = None
        self._receive_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._listener_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        # Use await directly (NOT async with) since lifecycle is managed by connect/close
        self._ws = await websockets.connect(
            self._url,
            additional_headers={"x-nexus3-ide-authorization": self._auth_token},
            ping_interval=30,
            ping_timeout=10,
        )
        self._listener_task = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        """Background: read frames, put ALL messages on queue.

        IMPORTANT: Must queue ALL messages including notifications.
        MCPClient._call() (mcp/client.py:230) has its own notification-discarding
        loop that expects to see everything via receive(). Pre-filtering would break it.
        """
        assert self._ws is not None
        try:
            async for data in self._ws:
                # websockets v13+: recv() returns str for text frames
                msg = json.loads(data)
                await self._receive_queue.put(msg)
        except websockets.exceptions.ConnectionClosed:
            logger.debug("WebSocket connection closed")
        except Exception:
            logger.exception("WebSocket listener error")

    async def send(self, message: dict[str, Any]) -> None:
        assert self._ws is not None
        await self._ws.send(json.dumps(message, separators=(",", ":")))

    async def receive(self) -> dict[str, Any]:
        return await self._receive_queue.get()

    async def close(self) -> None:
        if self._listener_task:
            self._listener_task.cancel()
            self._listener_task = None
        if self._ws:
            await self._ws.close()
            self._ws = None

    @property
    def is_connected(self) -> bool:
        return (
            self._ws is not None
            and self._ws.protocol is not None
            and self._listener_task is not None
            and not self._listener_task.done()
        )
