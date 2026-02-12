from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from nexus3.ide.connection import IDEConnection
from nexus3.ide.discovery import IDEInfo, discover_ides
from nexus3.ide.transport import WebSocketTransport
from nexus3.mcp.client import MCPClient

if TYPE_CHECKING:
    from nexus3.config.schema import IDEConfig

logger = logging.getLogger(__name__)


class IDEBridge:
    """Manages IDE discovery and connection lifecycle.

    Created once per SharedComponents. Not connected until auto_connect() or connect() called.
    """

    def __init__(self, config: IDEConfig) -> None:
        self._config = config
        self._connection: IDEConnection | None = None
        self._diff_lock = asyncio.Lock()  # Serialize openDiff requests
        self._last_cwd: Path | None = None  # For reconnection

    async def auto_connect(self, cwd: Path) -> IDEConnection | None:
        """Discover and connect to the best-matching IDE for the given cwd.

        Returns the connection if successful, None if disabled or no IDE found.
        """
        if not self._config.enabled or not self._config.auto_connect:
            return None
        self._last_cwd = cwd  # Remember for reconnection
        ides = discover_ides(cwd)
        if not ides:
            return None
        return await self.connect(ides[0])

    async def connect(self, ide_info: IDEInfo) -> IDEConnection:
        """Connect to a specific IDE instance."""
        if self._connection:
            await self.disconnect()
        transport = WebSocketTransport(
            url=f"ws://{ide_info.host}:{ide_info.port}",
            auth_token=ide_info.auth_token,
        )
        client = MCPClient(transport)
        await client.connect(timeout=10.0)  # Handles initialize handshake
        self._connection = IDEConnection(client, ide_info)
        logger.info("IDE connected: %s (port %d)", ide_info.ide_name, ide_info.port)
        return self._connection

    async def disconnect(self) -> None:
        """Disconnect from the current IDE."""
        if self._connection:
            await self._connection.close()
            self._connection = None

    async def reconnect_if_dead(self, cwd: Path | None = None) -> bool:
        """Attempt reconnection if currently disconnected.

        Returns True if connected (already or after reconnection).
        """
        if self.is_connected:
            return True
        effective_cwd = cwd or self._last_cwd
        if not effective_cwd:
            return False
        # Clean up old connection
        if self._connection:
            try:
                await self.disconnect()
            except Exception:
                self._connection = None
        # Re-discover
        ides = discover_ides(effective_cwd)
        if not ides:
            return False
        try:
            await self.connect(ides[0])
            logger.info("IDE reconnected after connection loss")
            return True
        except Exception:
            logger.debug("IDE reconnect failed", exc_info=True)
            return False

    @property
    def connection(self) -> IDEConnection | None:
        return self._connection

    @property
    def is_connected(self) -> bool:
        return self._connection is not None and self._connection.is_connected
