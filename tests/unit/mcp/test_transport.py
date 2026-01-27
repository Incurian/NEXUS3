"""
Unit tests for MCP transport implementations.

Tests the HTTPTransport.is_connected property to ensure it properly
detects stale connections by checking httpx.AsyncClient.is_closed.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from nexus3.mcp.transport import HTTPTransport


class TestHTTPTransportIsConnected:
    """Tests for HTTPTransport.is_connected property."""

    @pytest.fixture
    def mock_session_class(self) -> MagicMock:
        """Mock ClientSession for testing."""
        mock_session = MagicMock()
        mock_session.read = AsyncMock(return_value={})
        mock_session.initialize = AsyncMock()
        return mock_session

    def test_is_connected_false_before_connect(self, mock_session_class: MagicMock) -> None:
        """HTTPTransport.is_connected returns False before connect() is called."""
        transport = HTTPTransport("http://example.com")
        transport._session_class = mock_session_class

        # Before connect, _client is None
        assert transport._client is None
        assert transport.is_connected is False

    @pytest.mark.asyncio
    async def test_is_connected_true_after_connect(self, mock_session_class: MagicMock) -> None:
        """HTTPTransport.is_connected returns True after connect() is called."""
        transport = HTTPTransport("http://example.com")
        transport._session_class = mock_session_class

        # Mock httpx.AsyncClient
        mock_client = AsyncMock()
        mock_client.is_closed = False

        with patch("nexus3.mcp.transport.httpx.AsyncClient", return_value=mock_client):
            await transport.connect()

        # After connect, client exists and is not closed
        assert transport._client is not None
        assert transport._client.is_closed is False
        assert transport.is_connected is True

    @pytest.mark.asyncio
    async def test_is_connected_false_after_close(self, mock_session_class: MagicMock) -> None:
        """HTTPTransport.is_connected returns False after close() is called."""
        transport = HTTPTransport("http://example.com")
        transport._session_class = mock_session_class

        # Mock httpx.AsyncClient
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.aclose = AsyncMock()

        with patch("nexus3.mcp.transport.httpx.AsyncClient", return_value=mock_client):
            await transport.connect()
            assert transport.is_connected is True

            await transport.close()

        # After close, _client is set to None
        assert transport._client is None
        assert transport.is_connected is False

    @pytest.mark.asyncio
    async def test_is_connected_detects_closed_client(self, mock_session_class: MagicMock) -> None:
        """HTTPTransport.is_connected detects when httpx client is closed externally."""
        transport = HTTPTransport("http://example.com")
        transport._session_class = mock_session_class

        # Mock httpx.AsyncClient
        mock_client = AsyncMock()
        mock_client.is_closed = False

        with patch("nexus3.mcp.transport.httpx.AsyncClient", return_value=mock_client):
            await transport.connect()
            assert transport.is_connected is True

            # Simulate external closure (e.g., network error)
            mock_client.is_closed = True

            # is_connected should now return False
            assert transport.is_connected is False

    @pytest.mark.asyncio
    async def test_is_connected_with_stale_client_reference(self, mock_session_class: MagicMock) -> None:
        """HTTPTransport.is_connected returns False when client is closed but reference exists."""
        transport = HTTPTransport("http://example.com")
        transport._session_class = mock_session_class

        # Mock httpx.AsyncClient
        mock_client = AsyncMock()
        mock_client.is_closed = True  # Simulate a stale/closed client

        with patch("nexus3.mcp.transport.httpx.AsyncClient", return_value=mock_client):
            await transport.connect()

        # Even though _client is not None, is_closed is True
        assert transport._client is not None
        assert transport._client.is_closed is True
        assert transport.is_connected is False
