"""Unit tests for MCP transport module."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus3.mcp.protocol import PROTOCOL_VERSION
from nexus3.mcp.transport import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BACKOFF,
    MAX_SESSION_ID_LENGTH,
    MCP_HTTP_HEADERS,
    RETRYABLE_STATUS_CODES,
    SAFE_ENV_KEYS,
    HTTPTransport,
    MCPTransportError,
    StdioTransport,
    build_safe_env,
)


class TestSafeEnvKeys:
    """Test the SAFE_ENV_KEYS constant."""

    def test_includes_path(self):
        """PATH is essential for finding executables."""
        assert "PATH" in SAFE_ENV_KEYS

    def test_includes_home(self):
        """HOME is needed for config file lookup."""
        assert "HOME" in SAFE_ENV_KEYS

    def test_includes_user(self):
        """USER identifies current user."""
        assert "USER" in SAFE_ENV_KEYS

    def test_includes_locale_vars(self):
        """Locale vars needed for character encoding."""
        assert "LANG" in SAFE_ENV_KEYS
        assert "LC_ALL" in SAFE_ENV_KEYS

    def test_does_not_include_api_keys(self):
        """API key vars should NOT be in safe keys."""
        assert "OPENROUTER_API_KEY" not in SAFE_ENV_KEYS
        assert "ANTHROPIC_API_KEY" not in SAFE_ENV_KEYS
        assert "OPENAI_API_KEY" not in SAFE_ENV_KEYS
        assert "AWS_SECRET_ACCESS_KEY" not in SAFE_ENV_KEYS
        assert "GITHUB_TOKEN" not in SAFE_ENV_KEYS

    def test_is_frozenset(self):
        """Should be immutable."""
        assert isinstance(SAFE_ENV_KEYS, frozenset)


class TestBuildSafeEnv:
    """Test the build_safe_env function."""

    def test_includes_only_safe_keys_by_default(self):
        """Without passthrough or explicit, only safe keys are included."""
        with patch.dict(os.environ, {
            "PATH": "/usr/bin",
            "HOME": "/home/user",
            "OPENROUTER_API_KEY": "secret-key",
            "GITHUB_TOKEN": "ghp_xxx",
        }, clear=True):
            env = build_safe_env()

            assert env.get("PATH") == "/usr/bin"
            assert env.get("HOME") == "/home/user"
            assert "OPENROUTER_API_KEY" not in env
            assert "GITHUB_TOKEN" not in env

    def test_explicit_env_included(self):
        """Explicit env vars are included."""
        with patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True):
            env = build_safe_env(explicit_env={"DATABASE_URL": "postgres://localhost/db"})

            assert env.get("DATABASE_URL") == "postgres://localhost/db"

    def test_passthrough_copies_from_host(self):
        """Passthrough vars are copied from host environment."""
        with patch.dict(os.environ, {
            "PATH": "/usr/bin",
            "GITHUB_TOKEN": "ghp_xxx",
            "AWS_KEY": "aws_secret",
        }, clear=True):
            env = build_safe_env(passthrough=["GITHUB_TOKEN"])

            assert env.get("GITHUB_TOKEN") == "ghp_xxx"
            assert "AWS_KEY" not in env  # Not in passthrough list

    def test_passthrough_ignores_missing_vars(self):
        """Passthrough vars that don't exist in host are ignored."""
        with patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True):
            env = build_safe_env(passthrough=["NONEXISTENT_VAR"])

            assert "NONEXISTENT_VAR" not in env

    def test_explicit_overrides_passthrough(self):
        """Explicit env has priority over passthrough."""
        with patch.dict(os.environ, {
            "PATH": "/usr/bin",
            "MY_VAR": "from_host",
        }, clear=True):
            env = build_safe_env(
                explicit_env={"MY_VAR": "explicit_value"},
                passthrough=["MY_VAR"],
            )

            assert env.get("MY_VAR") == "explicit_value"

    def test_explicit_overrides_safe_keys(self):
        """Explicit env has priority over safe keys."""
        with patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True):
            env = build_safe_env(explicit_env={"PATH": "/custom/path"})

            assert env.get("PATH") == "/custom/path"

    def test_empty_inputs(self):
        """Handles None and empty inputs gracefully."""
        with patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True):
            env = build_safe_env(explicit_env=None, passthrough=None)

            assert env.get("PATH") == "/usr/bin"

    def test_combined_usage(self):
        """Test realistic combined usage."""
        with patch.dict(os.environ, {
            "PATH": "/usr/bin",
            "HOME": "/home/user",
            "LANG": "en_US.UTF-8",
            "GITHUB_TOKEN": "ghp_real_token",
            "AWS_SECRET_ACCESS_KEY": "aws_secret",
            "OPENROUTER_API_KEY": "openrouter_key",
        }, clear=True):
            env = build_safe_env(
                explicit_env={"DATABASE_URL": "postgres://localhost/mydb"},
                passthrough=["GITHUB_TOKEN"],
            )

            # Safe keys
            assert env.get("PATH") == "/usr/bin"
            assert env.get("HOME") == "/home/user"
            assert env.get("LANG") == "en_US.UTF-8"

            # Passthrough
            assert env.get("GITHUB_TOKEN") == "ghp_real_token"

            # Explicit
            assert env.get("DATABASE_URL") == "postgres://localhost/mydb"

            # Should NOT be present
            assert "AWS_SECRET_ACCESS_KEY" not in env
            assert "OPENROUTER_API_KEY" not in env


class TestStdioTransportBuffering:
    """Test stdio transport read buffering.

    These tests verify that _read_bounded_line properly buffers data
    when multiple responses arrive in a single read() call - common
    with buffered I/O (especially WSL→Windows subprocess).
    """

    @pytest.mark.asyncio
    async def test_multi_response_in_single_read(self):
        """When read() returns multiple lines, each call gets one line."""
        transport = StdioTransport(["dummy"])
        transport._process = MagicMock()

        # Simulate reading two complete JSON-RPC responses in one chunk
        response1 = b'{"jsonrpc":"2.0","id":1,"result":{}}\n'
        response2 = b'{"jsonrpc":"2.0","id":2,"result":{"tools":[]}}\n'
        combined = response1 + response2

        # First read() returns both responses, subsequent reads return empty
        read_calls = [combined, b""]
        call_idx = 0

        async def mock_read(n):
            nonlocal call_idx
            if call_idx < len(read_calls):
                result = read_calls[call_idx]
                call_idx += 1
                return result
            return b""

        transport._process.stdout = MagicMock()
        transport._process.stdout.read = mock_read

        # First call should return first response
        line1 = await transport._read_bounded_line()
        assert line1 == response1

        # Second call should return buffered second response (no new read needed)
        line2 = await transport._read_bounded_line()
        assert line2 == response2

    @pytest.mark.asyncio
    async def test_partial_line_in_buffer(self):
        """Buffer handles partial lines that span multiple reads."""
        transport = StdioTransport(["dummy"])
        transport._process = MagicMock()

        # First read: incomplete line, Second read: rest of line + next line
        chunk1 = b'{"jsonrpc":"2.0",'
        chunk2 = b'"id":1,"result":{}}\n{"jsonrpc":"2.0","id":2}\n'

        read_calls = [chunk1, chunk2, b""]
        call_idx = 0

        async def mock_read(n):
            nonlocal call_idx
            if call_idx < len(read_calls):
                result = read_calls[call_idx]
                call_idx += 1
                return result
            return b""

        transport._process.stdout = MagicMock()
        transport._process.stdout.read = mock_read

        # First call should return complete first response
        line1 = await transport._read_bounded_line()
        assert line1 == b'{"jsonrpc":"2.0","id":1,"result":{}}\n'

        # Second call should return buffered second response
        line2 = await transport._read_bounded_line()
        assert line2 == b'{"jsonrpc":"2.0","id":2}\n'

    @pytest.mark.asyncio
    async def test_buffer_cleared_on_close(self):
        """Close clears any buffered data."""
        transport = StdioTransport(["dummy"])
        transport._read_buffer = b"leftover data"
        transport._process = None  # Already closed
        transport._stderr_task = None

        await transport.close()

        assert transport._read_buffer == b""

    @pytest.mark.asyncio
    async def test_complete_line_in_buffer_no_read_needed(self):
        """If buffer has complete line, no read() is called."""
        transport = StdioTransport(["dummy"])
        transport._process = MagicMock()

        # Pre-fill buffer with a complete line
        transport._read_buffer = b'{"id":1}\n{"id":2}\n'

        # read() should NOT be called
        read_called = False

        async def mock_read(n):
            nonlocal read_called
            read_called = True
            return b""

        transport._process.stdout = MagicMock()
        transport._process.stdout.read = mock_read

        line = await transport._read_bounded_line()

        assert line == b'{"id":1}\n'
        assert not read_called  # Buffer had complete line
        assert transport._read_buffer == b'{"id":2}\n'  # Rest still buffered


class TestMCPHTTPHeaders:
    """Test P1.7: MCP HTTP protocol headers."""

    def test_mcp_http_headers_constant_has_protocol_version(self):
        """MCP_HTTP_HEADERS contains the MCP-Protocol-Version header."""
        assert "MCP-Protocol-Version" in MCP_HTTP_HEADERS
        assert MCP_HTTP_HEADERS["MCP-Protocol-Version"] == PROTOCOL_VERSION

    def test_mcp_http_headers_constant_has_accept(self):
        """MCP_HTTP_HEADERS contains the Accept header."""
        assert "Accept" in MCP_HTTP_HEADERS
        assert MCP_HTTP_HEADERS["Accept"] == "application/json, text/event-stream"

    @pytest.mark.asyncio
    async def test_connect_includes_mcp_headers(self):
        """HTTPTransport.connect() includes MCP protocol headers."""
        transport = HTTPTransport("http://localhost:9000")

        # Patch httpx in the transport module where it's imported
        mock_client = MagicMock()
        with patch("nexus3.mcp.transport.httpx") as mock_httpx:
            mock_httpx.AsyncClient = MagicMock(return_value=mock_client)
            await transport.connect()

            # Verify AsyncClient was called with headers including MCP headers
            call_kwargs = mock_httpx.AsyncClient.call_args.kwargs
            headers = call_kwargs.get("headers", {})

            assert headers.get("Content-Type") == "application/json"
            assert headers.get("MCP-Protocol-Version") == PROTOCOL_VERSION
            assert headers.get("Accept") == "application/json, text/event-stream"

    @pytest.mark.asyncio
    async def test_user_headers_override_defaults(self):
        """User-provided headers can override default headers."""
        transport = HTTPTransport(
            "http://localhost:9000",
            headers={"Accept": "custom/accept", "X-Custom": "value"},
        )

        # Patch httpx in the transport module where it's imported
        mock_client = MagicMock()
        with patch("nexus3.mcp.transport.httpx") as mock_httpx:
            mock_httpx.AsyncClient = MagicMock(return_value=mock_client)
            await transport.connect()

            call_kwargs = mock_httpx.AsyncClient.call_args.kwargs
            headers = call_kwargs.get("headers", {})

            # User header overrides default
            assert headers.get("Accept") == "custom/accept"
            # Custom headers are included
            assert headers.get("X-Custom") == "value"
            # MCP version header is still present
            assert headers.get("MCP-Protocol-Version") == PROTOCOL_VERSION


class TestHTTPTransportSessionManagement:
    """Test P1.8: MCP HTTP session management."""

    def test_session_id_initially_none(self):
        """Session ID starts as None."""
        transport = HTTPTransport("http://localhost:9000")
        assert transport.session_id is None

    def test_validate_session_id_accepts_valid(self):
        """Valid session IDs are accepted."""
        transport = HTTPTransport("http://localhost:9000")

        assert transport._validate_session_id("abc123") is True
        assert transport._validate_session_id("session-id-123") is True
        assert transport._validate_session_id("session_id_456") is True
        assert transport._validate_session_id("ABC-xyz_789") is True

    def test_validate_session_id_rejects_empty(self):
        """Empty session IDs are rejected."""
        transport = HTTPTransport("http://localhost:9000")

        assert transport._validate_session_id("") is False
        assert transport._validate_session_id(None) is False  # type: ignore

    def test_validate_session_id_rejects_too_long(self):
        """Session IDs exceeding MAX_SESSION_ID_LENGTH are rejected."""
        transport = HTTPTransport("http://localhost:9000")

        # Just under limit
        valid_long = "a" * MAX_SESSION_ID_LENGTH
        assert transport._validate_session_id(valid_long) is True

        # Exceeds limit
        too_long = "a" * (MAX_SESSION_ID_LENGTH + 1)
        assert transport._validate_session_id(too_long) is False

    def test_validate_session_id_rejects_invalid_chars(self):
        """Session IDs with invalid characters are rejected."""
        transport = HTTPTransport("http://localhost:9000")

        # Invalid characters
        assert transport._validate_session_id("session id") is False  # space
        assert transport._validate_session_id("session/id") is False  # slash
        assert transport._validate_session_id("session;id") is False  # semicolon
        assert transport._validate_session_id("<script>") is False  # HTML
        assert transport._validate_session_id("id\x00null") is False  # null byte
        assert transport._validate_session_id("id\nline") is False  # newline

    def test_capture_session_id_stores_valid_id(self):
        """_capture_session_id stores valid session IDs."""
        transport = HTTPTransport("http://localhost:9000")

        # Mock headers
        headers = {"mcp-session-id": "test-session-123"}
        transport._capture_session_id(headers)

        assert transport.session_id == "test-session-123"

    def test_capture_session_id_ignores_invalid_id(self):
        """_capture_session_id ignores invalid session IDs."""
        transport = HTTPTransport("http://localhost:9000")

        # Set initial valid session
        transport._session_id = "original-session"

        # Try to set invalid session
        headers = {"mcp-session-id": "invalid session!"}
        transport._capture_session_id(headers)

        # Original session is preserved
        assert transport.session_id == "original-session"

    def test_capture_session_id_ignores_missing_header(self):
        """_capture_session_id does nothing when header is missing."""
        transport = HTTPTransport("http://localhost:9000")
        transport._session_id = "existing-session"

        headers = {"other-header": "value"}
        transport._capture_session_id(headers)

        assert transport.session_id == "existing-session"

    @pytest.mark.asyncio
    async def test_send_includes_session_id_in_request(self):
        """send() includes session ID in request headers when set."""
        transport = HTTPTransport("http://localhost:9000")
        transport._session_id = "my-session-id"

        # Mock the client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"result": "ok"}'
        mock_response.json.return_value = {"result": "ok"}
        mock_response.headers = {}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        transport._client = mock_client

        await transport.send({"method": "test"})

        # Verify session ID was included in headers
        call_kwargs = mock_client.post.call_args.kwargs
        headers = call_kwargs.get("headers", {})
        assert headers.get("mcp-session-id") == "my-session-id"

    @pytest.mark.asyncio
    async def test_send_no_session_header_when_none(self):
        """send() does not include session ID header when not set."""
        transport = HTTPTransport("http://localhost:9000")
        # session_id is None by default

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"result": "ok"}'
        mock_response.json.return_value = {"result": "ok"}
        mock_response.headers = {}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        transport._client = mock_client

        await transport.send({"method": "test"})

        # Verify no extra headers passed (or headers is None)
        call_kwargs = mock_client.post.call_args.kwargs
        headers = call_kwargs.get("headers")
        assert headers is None or "mcp-session-id" not in headers

    @pytest.mark.asyncio
    async def test_send_captures_session_id_from_response(self):
        """send() captures session ID from response headers."""
        transport = HTTPTransport("http://localhost:9000")
        assert transport.session_id is None

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"result": "ok"}'
        mock_response.json.return_value = {"result": "ok"}
        mock_response.headers = {"mcp-session-id": "new-session-456"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        transport._client = mock_client

        await transport.send({"method": "test"})

        assert transport.session_id == "new-session-456"

    @pytest.mark.asyncio
    async def test_request_includes_session_id(self):
        """request() includes session ID in request headers when set."""
        transport = HTTPTransport("http://localhost:9000")
        transport._session_id = "request-session"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"result": "ok"}'
        mock_response.json.return_value = {"result": "ok"}
        mock_response.headers = {}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        transport._client = mock_client

        await transport.request({"method": "test", "id": 1})

        call_kwargs = mock_client.post.call_args.kwargs
        headers = call_kwargs.get("headers", {})
        assert headers.get("mcp-session-id") == "request-session"

    @pytest.mark.asyncio
    async def test_request_captures_session_id_from_response(self):
        """request() captures session ID from response headers."""
        transport = HTTPTransport("http://localhost:9000")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"result": "ok"}'
        mock_response.json.return_value = {"result": "ok"}
        mock_response.headers = {"mcp-session-id": "response-session"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        transport._client = mock_client

        await transport.request({"method": "test", "id": 1})

        assert transport.session_id == "response-session"

    @pytest.mark.asyncio
    async def test_session_persistence_across_requests(self):
        """Session ID persists across multiple requests."""
        transport = HTTPTransport("http://localhost:9000")

        # First response sets session ID
        mock_response1 = MagicMock()
        mock_response1.status_code = 200
        mock_response1.content = b'{"result": "1"}'
        mock_response1.json.return_value = {"result": "1"}
        mock_response1.headers = {"mcp-session-id": "persistent-session"}

        # Second response has no session header
        mock_response2 = MagicMock()
        mock_response2.status_code = 200
        mock_response2.content = b'{"result": "2"}'
        mock_response2.json.return_value = {"result": "2"}
        mock_response2.headers = {}

        mock_client = AsyncMock()
        mock_client.post.side_effect = [mock_response1, mock_response2]
        transport._client = mock_client

        # First request captures session
        await transport.request({"method": "test", "id": 1})
        assert transport.session_id == "persistent-session"

        # Second request uses captured session
        await transport.request({"method": "test", "id": 2})

        # Verify second request included the session ID
        second_call_kwargs = mock_client.post.call_args.kwargs
        headers = second_call_kwargs.get("headers", {})
        assert headers.get("mcp-session-id") == "persistent-session"

        # Session ID still set
        assert transport.session_id == "persistent-session"


class TestHTTPTransportRetryConstants:
    """Test P1.10: HTTP retry configuration constants."""

    def test_default_max_retries(self):
        """Default max retries is 3."""
        assert DEFAULT_MAX_RETRIES == 3

    def test_default_retry_backoff(self):
        """Default retry backoff is 1.0 seconds."""
        assert DEFAULT_RETRY_BACKOFF == 1.0

    def test_retryable_status_codes(self):
        """Retryable status codes include 429 and 5xx server errors."""
        assert 429 in RETRYABLE_STATUS_CODES  # Rate limit
        assert 500 in RETRYABLE_STATUS_CODES  # Internal server error
        assert 502 in RETRYABLE_STATUS_CODES  # Bad gateway
        assert 503 in RETRYABLE_STATUS_CODES  # Service unavailable
        assert 504 in RETRYABLE_STATUS_CODES  # Gateway timeout

    def test_non_retryable_client_errors(self):
        """Client errors (4xx except 429) should not be retryable."""
        assert 400 not in RETRYABLE_STATUS_CODES  # Bad request
        assert 401 not in RETRYABLE_STATUS_CODES  # Unauthorized
        assert 403 not in RETRYABLE_STATUS_CODES  # Forbidden
        assert 404 not in RETRYABLE_STATUS_CODES  # Not found


class TestHTTPTransportRetryConfiguration:
    """Test P1.10: HTTP retry configuration in HTTPTransport."""

    def test_default_retry_params(self):
        """HTTPTransport uses default retry params when not specified."""
        transport = HTTPTransport("http://localhost:9000")
        assert transport._max_retries == DEFAULT_MAX_RETRIES
        assert transport._retry_backoff == DEFAULT_RETRY_BACKOFF

    def test_custom_retry_params(self):
        """HTTPTransport accepts custom retry params."""
        transport = HTTPTransport(
            "http://localhost:9000",
            max_retries=5,
            retry_backoff=2.0,
        )
        assert transport._max_retries == 5
        assert transport._retry_backoff == 2.0

    def test_is_retryable_status_true_for_retryable_codes(self):
        """_is_retryable_status returns True for retryable codes."""
        transport = HTTPTransport("http://localhost:9000")

        for code in [429, 500, 502, 503, 504]:
            assert transport._is_retryable_status(code) is True

    def test_is_retryable_status_false_for_non_retryable_codes(self):
        """_is_retryable_status returns False for non-retryable codes."""
        transport = HTTPTransport("http://localhost:9000")

        for code in [200, 201, 400, 401, 403, 404, 405]:
            assert transport._is_retryable_status(code) is False

    def test_calculate_retry_delay_exponential_backoff(self):
        """_calculate_retry_delay uses exponential backoff."""
        transport = HTTPTransport("http://localhost:9000", retry_backoff=1.0)

        # Attempt 0: ~1s (1.0 * 2^0 = 1.0, plus 0-10% jitter)
        delay0 = transport._calculate_retry_delay(0)
        assert 1.0 <= delay0 <= 1.1

        # Attempt 1: ~2s (1.0 * 2^1 = 2.0, plus 0-10% jitter)
        delay1 = transport._calculate_retry_delay(1)
        assert 2.0 <= delay1 <= 2.2

        # Attempt 2: ~4s (1.0 * 2^2 = 4.0, plus 0-10% jitter)
        delay2 = transport._calculate_retry_delay(2)
        assert 4.0 <= delay2 <= 4.4

    def test_calculate_retry_delay_with_custom_backoff(self):
        """_calculate_retry_delay respects custom backoff value."""
        transport = HTTPTransport("http://localhost:9000", retry_backoff=0.5)

        # Attempt 0: ~0.5s (0.5 * 2^0 = 0.5, plus 0-10% jitter)
        delay0 = transport._calculate_retry_delay(0)
        assert 0.5 <= delay0 <= 0.55


class TestHTTPTransportRetryBehavior:
    """Test P1.10: HTTP retry behavior in send() and request()."""

    @pytest.mark.asyncio
    async def test_send_retries_on_429(self):
        """send() retries on 429 Too Many Requests."""
        transport = HTTPTransport(
            "http://localhost:9000",
            max_retries=2,
            retry_backoff=0.01,  # Fast for testing
        )

        # First call returns 429, second returns 200
        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        mock_response_429.headers = {}

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.content = b'{"result": "ok"}'
        mock_response_200.json.return_value = {"result": "ok"}
        mock_response_200.headers = {}

        mock_client = AsyncMock()
        mock_client.post.side_effect = [mock_response_429, mock_response_200]
        transport._client = mock_client

        await transport.send({"method": "test"})

        # Should have been called twice
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_send_retries_on_503(self):
        """send() retries on 503 Service Unavailable."""
        transport = HTTPTransport(
            "http://localhost:9000",
            max_retries=2,
            retry_backoff=0.01,
        )

        mock_response_503 = MagicMock()
        mock_response_503.status_code = 503
        mock_response_503.headers = {}

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.content = b'{"result": "ok"}'
        mock_response_200.json.return_value = {"result": "ok"}
        mock_response_200.headers = {}

        mock_client = AsyncMock()
        mock_client.post.side_effect = [mock_response_503, mock_response_200]
        transport._client = mock_client

        await transport.send({"method": "test"})

        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_send_no_retry_on_400(self):
        """send() does not retry on 400 Bad Request (client error)."""
        transport = HTTPTransport(
            "http://localhost:9000",
            max_retries=2,
            retry_backoff=0.01,
        )

        mock_response_400 = MagicMock()
        mock_response_400.status_code = 400
        mock_response_400.headers = {}
        mock_response_400.raise_for_status.side_effect = Exception("400 Bad Request")

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response_400
        transport._client = mock_client

        with pytest.raises(MCPTransportError):
            await transport.send({"method": "test"})

        # Should only be called once (no retry)
        assert mock_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_send_exhausts_retries(self):
        """send() fails after exhausting retries."""
        transport = HTTPTransport(
            "http://localhost:9000",
            max_retries=2,
            retry_backoff=0.01,
        )

        mock_response_503 = MagicMock()
        mock_response_503.status_code = 503
        mock_response_503.headers = {}
        mock_response_503.raise_for_status.side_effect = Exception("503 Service Unavailable")

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response_503
        transport._client = mock_client

        with pytest.raises(MCPTransportError):
            await transport.send({"method": "test"})

        # Should be called 3 times (initial + 2 retries)
        assert mock_client.post.call_count == 3

    @pytest.mark.asyncio
    async def test_send_retries_on_transport_error(self):
        """send() retries on httpx.TransportError."""
        import httpx

        transport = HTTPTransport(
            "http://localhost:9000",
            max_retries=2,
            retry_backoff=0.01,
        )

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.content = b'{"result": "ok"}'
        mock_response_200.json.return_value = {"result": "ok"}
        mock_response_200.headers = {}

        mock_client = AsyncMock()
        # First call raises TransportError, second succeeds
        mock_client.post.side_effect = [
            httpx.TransportError("Connection reset"),
            mock_response_200,
        ]
        transport._client = mock_client

        await transport.send({"method": "test"})

        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_send_transport_error_exhausts_retries(self):
        """send() fails after exhausting retries on TransportError."""
        import httpx

        transport = HTTPTransport(
            "http://localhost:9000",
            max_retries=2,
            retry_backoff=0.01,
        )

        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.TransportError("Connection refused")
        transport._client = mock_client

        with pytest.raises(MCPTransportError) as exc_info:
            await transport.send({"method": "test"})

        assert "after 3 attempts" in str(exc_info.value)
        assert mock_client.post.call_count == 3

    @pytest.mark.asyncio
    async def test_request_retries_on_500(self):
        """request() retries on 500 Internal Server Error."""
        transport = HTTPTransport(
            "http://localhost:9000",
            max_retries=2,
            retry_backoff=0.01,
        )

        mock_response_500 = MagicMock()
        mock_response_500.status_code = 500
        mock_response_500.headers = {}

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.content = b'{"result": "ok"}'
        mock_response_200.json.return_value = {"result": "ok"}
        mock_response_200.headers = {}

        mock_client = AsyncMock()
        mock_client.post.side_effect = [mock_response_500, mock_response_200]
        transport._client = mock_client

        result = await transport.request({"method": "test", "id": 1})

        assert result == {"result": "ok"}
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_request_retries_on_transport_error(self):
        """request() retries on httpx.TransportError."""
        import httpx

        transport = HTTPTransport(
            "http://localhost:9000",
            max_retries=2,
            retry_backoff=0.01,
        )

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.content = b'{"result": "ok"}'
        mock_response_200.json.return_value = {"result": "ok"}
        mock_response_200.headers = {}

        mock_client = AsyncMock()
        mock_client.post.side_effect = [
            httpx.TransportError("Network error"),
            mock_response_200,
        ]
        transport._client = mock_client

        result = await transport.request({"method": "test", "id": 1})

        assert result == {"result": "ok"}
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_request_no_retry_on_404(self):
        """request() does not retry on 404 Not Found."""
        transport = HTTPTransport(
            "http://localhost:9000",
            max_retries=2,
            retry_backoff=0.01,
        )

        mock_response_404 = MagicMock()
        mock_response_404.status_code = 404
        mock_response_404.headers = {}
        mock_response_404.raise_for_status.side_effect = Exception("404 Not Found")

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response_404
        transport._client = mock_client

        with pytest.raises(MCPTransportError):
            await transport.request({"method": "test", "id": 1})

        assert mock_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_request_exhausts_retries(self):
        """request() fails after exhausting retries."""
        transport = HTTPTransport(
            "http://localhost:9000",
            max_retries=2,
            retry_backoff=0.01,
        )

        mock_response_502 = MagicMock()
        mock_response_502.status_code = 502
        mock_response_502.headers = {}
        mock_response_502.raise_for_status.side_effect = Exception("502 Bad Gateway")

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response_502
        transport._client = mock_client

        with pytest.raises(MCPTransportError):
            await transport.request({"method": "test", "id": 1})

        assert mock_client.post.call_count == 3

    @pytest.mark.asyncio
    async def test_zero_retries_no_retry(self):
        """With max_retries=0, no retries are attempted."""
        transport = HTTPTransport(
            "http://localhost:9000",
            max_retries=0,
            retry_backoff=0.01,
        )

        mock_response_503 = MagicMock()
        mock_response_503.status_code = 503
        mock_response_503.headers = {}
        mock_response_503.raise_for_status.side_effect = Exception("503 Service Unavailable")

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response_503
        transport._client = mock_client

        with pytest.raises(MCPTransportError):
            await transport.send({"method": "test"})

        # Only 1 attempt, no retries
        assert mock_client.post.call_count == 1
