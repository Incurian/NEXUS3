"""Unit tests for SSE capability detection in connect_lobby.py."""

import httpx
import pytest

from nexus3.cli.connect_lobby import detect_sse_capability
from nexus3.client import ClientError


class TestDetectSSECapability:
    """Tests for the detect_sse_capability function."""

    @pytest.mark.asyncio
    async def test_returns_true_for_sse_endpoint(self):
        """Returns True when endpoint returns 200 with text/event-stream."""

        def mock_handler(request: httpx.Request) -> httpx.Response:
            assert "/agent/main/events" in str(request.url)
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"data: {}\n\n",
            )

        transport = httpx.MockTransport(mock_handler)
        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await detect_sse_capability(
                "http://localhost:8765",
                "main",
                api_key="test-key",
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_for_404(self):
        """Returns False when endpoint returns 404 (SSE not supported)."""

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        transport = httpx.MockTransport(mock_handler)
        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await detect_sse_capability(
                "http://localhost:8765",
                "main",
                api_key="test-key",
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_for_405(self):
        """Returns False when endpoint returns 405 (method not allowed)."""

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(405)

        transport = httpx.MockTransport(mock_handler)
        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await detect_sse_capability(
                "http://localhost:8765",
                "main",
                api_key="test-key",
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_raises_client_error_for_401(self):
        """Raises ClientError for 401 (authentication required)."""

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401)

        transport = httpx.MockTransport(mock_handler)
        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            with pytest.raises(ClientError, match="authentication failed"):
                await detect_sse_capability(
                    "http://localhost:8765",
                    "main",
                    api_key="bad-key",
                )

    @pytest.mark.asyncio
    async def test_raises_client_error_for_403(self):
        """Raises ClientError for 403 (forbidden)."""

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403)

        transport = httpx.MockTransport(mock_handler)
        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            with pytest.raises(ClientError, match="authentication failed"):
                await detect_sse_capability(
                    "http://localhost:8765",
                    "main",
                    api_key="forbidden-key",
                )

    @pytest.mark.asyncio
    async def test_returns_false_for_non_sse_content_type(self):
        """Returns False when content-type is not text/event-stream."""

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=b"{}",
            )

        transport = httpx.MockTransport(mock_handler)
        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await detect_sse_capability(
                "http://localhost:8765",
                "main",
                api_key="test-key",
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_strips_trailing_slash_from_url(self):
        """Properly handles server URL with trailing slash."""
        received_url = None

        def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal received_url
            received_url = str(request.url)
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )

        transport = httpx.MockTransport(mock_handler)
        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await detect_sse_capability(
                "http://localhost:8765/",  # Note trailing slash
                "main",
                api_key="test-key",
            )

        assert result is True
        # URL should not have double slashes
        assert "//agent" not in received_url
        assert "/agent/main/events" in received_url

    @pytest.mark.asyncio
    async def test_includes_authorization_header_when_api_key_provided(self):
        """Includes Bearer authorization header when api_key is provided."""
        received_auth = None

        def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal received_auth
            received_auth = request.headers.get("Authorization")
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )

        transport = httpx.MockTransport(mock_handler)
        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            await detect_sse_capability(
                "http://localhost:8765",
                "main",
                api_key="my-secret-key",
            )

        assert received_auth == "Bearer my-secret-key"

    @pytest.mark.asyncio
    async def test_no_auth_header_when_api_key_is_none(self):
        """Does not include Authorization header when api_key is None."""
        received_headers = None

        def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal received_headers
            received_headers = dict(request.headers)
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )

        transport = httpx.MockTransport(mock_handler)
        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            await detect_sse_capability(
                "http://localhost:8765",
                "main",
                api_key=None,
            )

        assert "authorization" not in {k.lower() for k in received_headers}

    @pytest.mark.asyncio
    async def test_returns_false_for_server_error(self):
        """Returns False for 5xx server errors."""

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        transport = httpx.MockTransport(mock_handler)
        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await detect_sse_capability(
                "http://localhost:8765",
                "main",
                api_key="test-key",
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_raises_client_error_for_connection_error(self):
        """Raises ClientError when connection fails."""

        def mock_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        transport = httpx.MockTransport(mock_handler)
        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            with pytest.raises(ClientError, match="Connection failed"):
                await detect_sse_capability(
                    "http://localhost:8765",
                    "main",
                    api_key="test-key",
                )

    @pytest.mark.asyncio
    async def test_builds_correct_url_from_components(self):
        """Builds correct /agent/{id}/events URL from server_url and agent_id."""
        received_url = None

        def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal received_url
            received_url = str(request.url)
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )

        transport = httpx.MockTransport(mock_handler)
        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            await detect_sse_capability(
                "http://127.0.0.1:9999",
                "worker-42",
                api_key=None,
            )

        assert received_url == "http://127.0.0.1:9999/agent/worker-42/events"
