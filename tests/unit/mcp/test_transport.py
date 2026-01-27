"""
Unit tests for MCP transport implementations.

Tests the HTTPTransport.is_connected property to ensure it properly
detects stale connections by checking httpx.AsyncClient.is_closed.

Also tests the resolve_command() function for Windows command resolution.

Tests the StdioTransport CRLF handling to ensure proper parsing of
both Windows (CRLF) and Unix (LF) line endings.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from nexus3.mcp.transport import HTTPTransport, StdioTransport, resolve_command


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


class TestResolveCommand:
    """Tests for resolve_command() function (P2.0.2-P2.0.3 Windows command resolution)."""

    def test_resolve_command_returns_unchanged_on_unix(self) -> None:
        """resolve_command() returns command unchanged on non-Windows platforms."""
        with patch("nexus3.mcp.transport.sys.platform", "linux"):
            result = resolve_command(["npx", "some-server", "--flag"])
            assert result == ["npx", "some-server", "--flag"]

        with patch("nexus3.mcp.transport.sys.platform", "darwin"):
            result = resolve_command(["node", "script.js"])
            assert result == ["node", "script.js"]

    def test_resolve_command_resolves_executable_on_windows(self) -> None:
        """resolve_command() resolves executable path using shutil.which on Windows."""
        with patch("nexus3.mcp.transport.sys.platform", "win32"):
            with patch("nexus3.mcp.transport.shutil.which", return_value="C:\\nodejs\\npx.cmd"):
                result = resolve_command(["npx", "some-server"])
                assert result == ["C:\\nodejs\\npx.cmd", "some-server"]

    def test_resolve_command_preserves_arguments(self) -> None:
        """resolve_command() preserves all arguments when resolving on Windows."""
        with patch("nexus3.mcp.transport.sys.platform", "win32"):
            with patch("nexus3.mcp.transport.shutil.which", return_value="C:\\Program Files\\node\\npx.cmd"):
                result = resolve_command(["npx", "mcp-server", "--port", "8080", "--verbose"])
                assert result == [
                    "C:\\Program Files\\node\\npx.cmd",
                    "mcp-server",
                    "--port",
                    "8080",
                    "--verbose",
                ]

    def test_resolve_command_skips_already_resolved_exe(self) -> None:
        """resolve_command() skips resolution if command already has Windows extension."""
        with patch("nexus3.mcp.transport.sys.platform", "win32"):
            with patch("nexus3.mcp.transport.shutil.which") as mock_which:
                # .exe extension
                result = resolve_command(["C:\\nodejs\\node.exe", "script.js"])
                assert result == ["C:\\nodejs\\node.exe", "script.js"]
                mock_which.assert_not_called()

                # .cmd extension
                result = resolve_command(["npx.cmd", "server"])
                assert result == ["npx.cmd", "server"]
                mock_which.assert_not_called()

                # .bat extension
                result = resolve_command(["start.bat", "--arg"])
                assert result == ["start.bat", "--arg"]
                mock_which.assert_not_called()

                # .com extension
                result = resolve_command(["command.com"])
                assert result == ["command.com"]
                mock_which.assert_not_called()

                # Case-insensitive extension matching
                result = resolve_command(["NODE.EXE", "script.js"])
                assert result == ["NODE.EXE", "script.js"]
                mock_which.assert_not_called()

    def test_resolve_command_returns_unchanged_if_which_fails(self) -> None:
        """resolve_command() returns original command if shutil.which returns None."""
        with patch("nexus3.mcp.transport.sys.platform", "win32"):
            with patch("nexus3.mcp.transport.shutil.which", return_value=None):
                result = resolve_command(["unknown-command", "--flag"])
                assert result == ["unknown-command", "--flag"]

    def test_resolve_command_handles_empty_command(self) -> None:
        """resolve_command() returns empty list for empty command."""
        # On Unix
        with patch("nexus3.mcp.transport.sys.platform", "linux"):
            result = resolve_command([])
            assert result == []

        # On Windows
        with patch("nexus3.mcp.transport.sys.platform", "win32"):
            result = resolve_command([])
            assert result == []


class TestStdioTransportCRLF:
    """Tests for StdioTransport CRLF handling (Windows compatibility).

    P2.0.10: Verifies that receive() properly handles both CRLF (Windows)
    and LF (Unix) line endings when parsing JSON-RPC messages.
    """

    @pytest.mark.asyncio
    async def test_receive_handles_crlf_line_endings(self) -> None:
        """StdioTransport.receive() correctly parses JSON with CRLF line endings."""
        transport = StdioTransport(["echo"])

        # Simulate connected state with mock process
        transport._process = MagicMock()
        transport._process.returncode = None
        transport._process.stdout = MagicMock()
        transport._io_lock = asyncio.Lock()

        # Set buffer with CRLF-terminated JSON (Windows style)
        transport._read_buffer = b'{"jsonrpc":"2.0","result":{"status":"ok"},"id":1}\r\n'

        result = await transport.receive()

        assert result == {"jsonrpc": "2.0", "result": {"status": "ok"}, "id": 1}

    @pytest.mark.asyncio
    async def test_receive_handles_lf_line_endings(self) -> None:
        """StdioTransport.receive() correctly parses JSON with LF line endings."""
        transport = StdioTransport(["echo"])

        # Simulate connected state with mock process
        transport._process = MagicMock()
        transport._process.returncode = None
        transport._process.stdout = MagicMock()
        transport._io_lock = asyncio.Lock()

        # Set buffer with LF-terminated JSON (Unix style)
        transport._read_buffer = b'{"jsonrpc":"2.0","result":{"status":"ok"},"id":1}\n'

        result = await transport.receive()

        assert result == {"jsonrpc": "2.0", "result": {"status": "ok"}, "id": 1}

    @pytest.mark.asyncio
    async def test_receive_handles_mixed_crlf_lf(self) -> None:
        """StdioTransport.receive() handles multiple messages with mixed line endings."""
        transport = StdioTransport(["echo"])

        # Simulate connected state with mock process
        transport._process = MagicMock()
        transport._process.returncode = None
        transport._process.stdout = MagicMock()
        transport._io_lock = asyncio.Lock()

        # First message: CRLF (Windows)
        transport._read_buffer = b'{"jsonrpc":"2.0","result":"first","id":1}\r\n'
        result1 = await transport.receive()
        assert result1 == {"jsonrpc": "2.0", "result": "first", "id": 1}

        # Second message: LF (Unix)
        transport._read_buffer = b'{"jsonrpc":"2.0","result":"second","id":2}\n'
        result2 = await transport.receive()
        assert result2 == {"jsonrpc": "2.0", "result": "second", "id": 2}

        # Third message: CRLF again (alternate)
        transport._read_buffer = b'{"jsonrpc":"2.0","result":"third","id":3}\r\n'
        result3 = await transport.receive()
        assert result3 == {"jsonrpc": "2.0", "result": "third", "id": 3}

    @pytest.mark.asyncio
    async def test_receive_strips_crlf_before_json_parse(self) -> None:
        """Verify CRLF stripping happens before JSON parsing.

        Raw bytes contain CRLF, but json.loads() receives clean bytes.
        This is important because \\r in JSON would cause a parse error.
        """
        transport = StdioTransport(["echo"])

        # Simulate connected state with mock process
        transport._process = MagicMock()
        transport._process.returncode = None
        transport._process.stdout = MagicMock()
        transport._io_lock = asyncio.Lock()

        # Set buffer with CRLF - the \r would cause json.JSONDecodeError if not stripped
        # because \r is not valid in JSON outside of string literals
        raw_bytes = b'{"jsonrpc":"2.0","id":42,"result":null}\r\n'

        # Verify the raw bytes actually contain \r\n
        assert raw_bytes.endswith(b"\r\n")

        transport._read_buffer = raw_bytes

        # This should succeed because receive() strips CRLF before parsing
        result = await transport.receive()
        assert result == {"jsonrpc": "2.0", "id": 42, "result": None}

    @pytest.mark.asyncio
    async def test_receive_handles_consecutive_messages_in_buffer(self) -> None:
        """StdioTransport correctly buffers and parses consecutive messages.

        When multiple messages arrive together (common with buffered I/O),
        each receive() call should return one message and buffer the rest.
        """
        transport = StdioTransport(["echo"])

        # Simulate connected state with mock process
        transport._process = MagicMock()
        transport._process.returncode = None
        transport._process.stdout = MagicMock()
        transport._io_lock = asyncio.Lock()

        # Two messages in buffer: first with CRLF, second with LF
        transport._read_buffer = (
            b'{"jsonrpc":"2.0","id":1,"result":"a"}\r\n'
            b'{"jsonrpc":"2.0","id":2,"result":"b"}\n'
        )

        # First receive gets first message
        result1 = await transport.receive()
        assert result1 == {"jsonrpc": "2.0", "id": 1, "result": "a"}

        # Second message should still be in buffer
        assert transport._read_buffer == b'{"jsonrpc":"2.0","id":2,"result":"b"}\n'

        # Second receive gets second message
        result2 = await transport.receive()
        assert result2 == {"jsonrpc": "2.0", "id": 2, "result": "b"}

        # Buffer should now be empty
        assert transport._read_buffer == b""
