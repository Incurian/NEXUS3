"""Tests for GitLab HTTP client."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from nexus3.skill.vcs.config import GitLabInstance
from nexus3.skill.vcs.gitlab.client import GitLabAPIError, GitLabClient


class TestGitLabClientInit:
    """Tests for GitLabClient initialization."""

    def test_init_with_instance(self) -> None:
        """GitLabClient initializes with GitLabInstance."""
        instance = GitLabInstance(url="https://gitlab.com", token="test-token")
        client = GitLabClient(instance)

        assert client._base_url == "https://gitlab.com/api/v4"
        assert client._timeout == GitLabClient.DEFAULT_TIMEOUT
        assert client._http is None  # Lazy init

    def test_init_strips_trailing_slash(self) -> None:
        """Base URL strips trailing slash."""
        instance = GitLabInstance(url="https://gitlab.com/", token="test-token")
        client = GitLabClient(instance)

        assert client._base_url == "https://gitlab.com/api/v4"

    def test_init_custom_timeout(self) -> None:
        """Custom timeout is used."""
        instance = GitLabInstance(url="https://gitlab.com", token="test-token")
        client = GitLabClient(instance, timeout=60.0)

        assert client._timeout == 60.0


class TestGitLabClientConnection:
    """Tests for client connection management."""

    @pytest.mark.asyncio
    async def test_ensure_client_creates_on_first_call(self) -> None:
        """_ensure_client creates HTTP client lazily."""
        instance = GitLabInstance(url="https://gitlab.com", token="test-token")
        client = GitLabClient(instance)

        assert client._http is None

        with patch("nexus3.skill.vcs.gitlab.client.httpx.AsyncClient") as mock_class:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_class.return_value = mock_client

            result = await client._ensure_client()

            assert result is mock_client
            mock_class.assert_called_once()
            # Verify headers are set
            call_kwargs = mock_class.call_args.kwargs
            assert "PRIVATE-TOKEN" in call_kwargs["headers"]
            assert call_kwargs["headers"]["PRIVATE-TOKEN"] == "test-token"
            assert call_kwargs["follow_redirects"] is False  # Security

    @pytest.mark.asyncio
    async def test_ensure_client_reuses_existing(self) -> None:
        """_ensure_client reuses existing client."""
        instance = GitLabInstance(url="https://gitlab.com", token="test-token")
        client = GitLabClient(instance)

        mock_http = AsyncMock()
        mock_http.is_closed = False
        client._http = mock_http
        client._token = "test-token"

        with patch("nexus3.skill.vcs.gitlab.client.httpx.AsyncClient") as mock_class:
            result = await client._ensure_client()

            assert result is mock_http
            mock_class.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_client_recreates_when_closed(self) -> None:
        """_ensure_client recreates client if closed."""
        instance = GitLabInstance(url="https://gitlab.com", token="test-token")
        client = GitLabClient(instance)

        old_http = AsyncMock()
        old_http.is_closed = True
        client._http = old_http

        with patch("nexus3.skill.vcs.gitlab.client.httpx.AsyncClient") as mock_class:
            new_http = AsyncMock()
            new_http.is_closed = False
            mock_class.return_value = new_http

            result = await client._ensure_client()

            assert result is new_http
            mock_class.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_client_raises_without_token(self) -> None:
        """_ensure_client raises if no token configured."""
        instance = GitLabInstance(url="https://gitlab.com")  # No token
        client = GitLabClient(instance)

        with pytest.raises(GitLabAPIError) as exc_info:
            await client._ensure_client()

        assert exc_info.value.status_code == 401
        assert "No GitLab token" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_close_closes_client(self) -> None:
        """close() properly closes HTTP client."""
        instance = GitLabInstance(url="https://gitlab.com", token="test-token")
        client = GitLabClient(instance)

        mock_http = AsyncMock()
        mock_http.is_closed = False
        mock_http.aclose = AsyncMock()
        client._http = mock_http

        await client.close()

        mock_http.aclose.assert_called_once()
        assert client._http is None

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """GitLabClient works as async context manager."""
        instance = GitLabInstance(url="https://gitlab.com", token="test-token")

        with patch("nexus3.skill.vcs.gitlab.client.httpx.AsyncClient") as mock_class:
            mock_http = AsyncMock()
            mock_http.is_closed = False
            mock_http.aclose = AsyncMock()
            mock_class.return_value = mock_http

            async with GitLabClient(instance) as client:
                assert client._http is mock_http

            mock_http.aclose.assert_called_once()


class TestGitLabClientRequests:
    """Tests for HTTP request methods."""

    @pytest.fixture
    def client_with_mock_http(self) -> tuple[GitLabClient, AsyncMock]:
        """Create client with mocked HTTP."""
        instance = GitLabInstance(url="https://gitlab.com", token="test-token")
        client = GitLabClient(instance)

        mock_http = AsyncMock()
        mock_http.is_closed = False
        client._http = mock_http
        client._token = "test-token"

        return client, mock_http

    @pytest.mark.asyncio
    async def test_get_request(self, client_with_mock_http: tuple[GitLabClient, AsyncMock]) -> None:
        """get() makes GET request and returns JSON."""
        client, mock_http = client_with_mock_http

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"key": "value"}
        mock_http.request.return_value = mock_response

        result = await client.get("/user")

        assert result == {"key": "value"}
        mock_http.request.assert_called_once()
        call_kwargs = mock_http.request.call_args.kwargs
        assert call_kwargs["method"] == "GET"
        assert call_kwargs["url"] == "https://gitlab.com/api/v4/user"

    @pytest.mark.asyncio
    async def test_get_with_params(self, client_with_mock_http: tuple[GitLabClient, AsyncMock]) -> None:
        """get() passes query parameters."""
        client, mock_http = client_with_mock_http

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_http.request.return_value = mock_response

        await client.get("/projects", search="test", per_page=10)

        call_kwargs = mock_http.request.call_args.kwargs
        assert call_kwargs["params"] == {"search": "test", "per_page": 10}

    @pytest.mark.asyncio
    async def test_post_request(self, client_with_mock_http: tuple[GitLabClient, AsyncMock]) -> None:
        """post() makes POST request with JSON body."""
        client, mock_http = client_with_mock_http

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": 1}
        mock_http.request.return_value = mock_response

        result = await client.post("/projects/1/issues", title="Test", description="Body")

        assert result == {"id": 1}
        call_kwargs = mock_http.request.call_args.kwargs
        assert call_kwargs["method"] == "POST"
        assert call_kwargs["json"] == {"title": "Test", "description": "Body"}

    @pytest.mark.asyncio
    async def test_put_request(self, client_with_mock_http: tuple[GitLabClient, AsyncMock]) -> None:
        """put() makes PUT request with JSON body."""
        client, mock_http = client_with_mock_http

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": 1, "state": "closed"}
        mock_http.request.return_value = mock_response

        result = await client.put("/projects/1/issues/1", state_event="close")

        assert result["state"] == "closed"
        call_kwargs = mock_http.request.call_args.kwargs
        assert call_kwargs["method"] == "PUT"
        assert call_kwargs["json"] == {"state_event": "close"}

    @pytest.mark.asyncio
    async def test_delete_request(self, client_with_mock_http: tuple[GitLabClient, AsyncMock]) -> None:
        """delete() makes DELETE request."""
        client, mock_http = client_with_mock_http

        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_http.request.return_value = mock_response

        result = await client.delete("/projects/1/issues/1")

        assert result is None  # 204 No Content
        call_kwargs = mock_http.request.call_args.kwargs
        assert call_kwargs["method"] == "DELETE"


class TestGitLabClientErrorHandling:
    """Tests for error handling."""

    @pytest.fixture
    def client_with_mock_http(self) -> tuple[GitLabClient, AsyncMock]:
        """Create client with mocked HTTP."""
        instance = GitLabInstance(url="https://gitlab.com", token="test-token")
        client = GitLabClient(instance)

        mock_http = AsyncMock()
        mock_http.is_closed = False
        client._http = mock_http
        client._token = "test-token"

        return client, mock_http

    @pytest.mark.asyncio
    async def test_401_unauthorized(self, client_with_mock_http: tuple[GitLabClient, AsyncMock]) -> None:
        """401 error raises GitLabAPIError."""
        client, mock_http = client_with_mock_http

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"message": "401 Unauthorized"}
        mock_response.text = "401 Unauthorized"
        mock_http.request.return_value = mock_response

        with pytest.raises(GitLabAPIError) as exc_info:
            await client.get("/user")

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_403_forbidden(self, client_with_mock_http: tuple[GitLabClient, AsyncMock]) -> None:
        """403 error raises GitLabAPIError."""
        client, mock_http = client_with_mock_http

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.json.return_value = {"message": "403 Forbidden"}
        mock_response.text = "403 Forbidden"
        mock_http.request.return_value = mock_response

        with pytest.raises(GitLabAPIError) as exc_info:
            await client.get("/projects/secret")

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_404_not_found(self, client_with_mock_http: tuple[GitLabClient, AsyncMock]) -> None:
        """404 error raises GitLabAPIError."""
        client, mock_http = client_with_mock_http

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"message": "404 Project Not Found"}
        mock_response.text = "Not Found"
        mock_http.request.return_value = mock_response

        with pytest.raises(GitLabAPIError) as exc_info:
            await client.get("/projects/nonexistent")

        assert exc_info.value.status_code == 404
        assert "Not Found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_429_rate_limit_with_retry(self, client_with_mock_http: tuple[GitLabClient, AsyncMock]) -> None:
        """429 rate limit triggers retry."""
        client, mock_http = client_with_mock_http

        # First call returns 429, second succeeds
        rate_limit_response = MagicMock()
        rate_limit_response.status_code = 429
        rate_limit_response.headers = {"Retry-After": "1"}

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"ok": True}

        mock_http.request.side_effect = [rate_limit_response, success_response]

        # Patch asyncio.sleep to avoid actual delay
        with patch("nexus3.skill.vcs.gitlab.client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.get("/user")

        assert result == {"ok": True}
        assert mock_http.request.call_count == 2

    @pytest.mark.asyncio
    async def test_429_rate_limit_max_retries(self, client_with_mock_http: tuple[GitLabClient, AsyncMock]) -> None:
        """429 raises after max retries."""
        client, mock_http = client_with_mock_http

        rate_limit_response = MagicMock()
        rate_limit_response.status_code = 429
        rate_limit_response.headers = {"Retry-After": "1"}

        # Always return 429
        mock_http.request.return_value = rate_limit_response

        with patch("nexus3.skill.vcs.gitlab.client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(GitLabAPIError) as exc_info:
                await client.get("/user")

        assert exc_info.value.status_code == 429
        assert "Rate limit" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_500_server_error_retry(self, client_with_mock_http: tuple[GitLabClient, AsyncMock]) -> None:
        """500 server error triggers retry."""
        client, mock_http = client_with_mock_http

        error_response = MagicMock()
        error_response.status_code = 500
        error_response.json.return_value = {"error": "Internal Server Error"}
        error_response.text = "Internal Server Error"

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"ok": True}

        mock_http.request.side_effect = [error_response, success_response]

        with patch("nexus3.skill.vcs.gitlab.client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.get("/user")

        assert result == {"ok": True}
        assert mock_http.request.call_count == 2

    @pytest.mark.asyncio
    async def test_timeout_error_retry(self, client_with_mock_http: tuple[GitLabClient, AsyncMock]) -> None:
        """Timeout triggers retry."""
        client, mock_http = client_with_mock_http

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"ok": True}

        mock_http.request.side_effect = [httpx.TimeoutException("timeout"), success_response]

        with patch("nexus3.skill.vcs.gitlab.client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.get("/user")

        assert result == {"ok": True}
        assert mock_http.request.call_count == 2

    @pytest.mark.asyncio
    async def test_timeout_error_max_retries(self, client_with_mock_http: tuple[GitLabClient, AsyncMock]) -> None:
        """Timeout raises after max retries."""
        client, mock_http = client_with_mock_http

        mock_http.request.side_effect = httpx.TimeoutException("timeout")

        with patch("nexus3.skill.vcs.gitlab.client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(GitLabAPIError) as exc_info:
                await client.get("/user")

        assert exc_info.value.status_code == 0
        assert "timeout" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_request_error(self, client_with_mock_http: tuple[GitLabClient, AsyncMock]) -> None:
        """Request error raises GitLabAPIError."""
        client, mock_http = client_with_mock_http

        mock_http.request.side_effect = httpx.RequestError("Connection refused")

        with pytest.raises(GitLabAPIError) as exc_info:
            await client.get("/user")

        assert exc_info.value.status_code == 0
        assert "Request failed" in exc_info.value.message


class TestGitLabClientPagination:
    """Tests for pagination."""

    @pytest.fixture
    def client_with_mock_http(self) -> tuple[GitLabClient, AsyncMock]:
        """Create client with mocked HTTP."""
        instance = GitLabInstance(url="https://gitlab.com", token="test-token")
        client = GitLabClient(instance)

        mock_http = AsyncMock()
        mock_http.is_closed = False
        client._http = mock_http
        client._token = "test-token"

        return client, mock_http

    @pytest.mark.asyncio
    async def test_paginate_single_page(self, client_with_mock_http: tuple[GitLabClient, AsyncMock]) -> None:
        """paginate() yields items from single page."""
        client, mock_http = client_with_mock_http

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": 1},
            {"id": 2},
            {"id": 3},
        ]
        mock_http.request.return_value = mock_response

        items = [item async for item in client.paginate("/projects")]

        assert len(items) == 3
        assert items[0]["id"] == 1

    @pytest.mark.asyncio
    async def test_paginate_multiple_pages(self, client_with_mock_http: tuple[GitLabClient, AsyncMock]) -> None:
        """paginate() fetches multiple pages.

        Pagination continues when page returns exactly per_page items.
        per_page = min(limit, MAX_PER_PAGE) = min(limit, 100)

        With limit=200, per_page=100. Need page1 to return 100 items for page2 to be fetched.
        """
        client, mock_http = client_with_mock_http

        # With limit=200, per_page=100. Page1 returns 100 (full), page2 returns 50 (partial).
        # Total should be 150 items (100 + 50), limited by page2 being partial.
        page1 = MagicMock()
        page1.status_code = 200
        page1.json.return_value = [{"id": i} for i in range(1, 101)]  # 100 items (full page)

        page2 = MagicMock()
        page2.status_code = 200
        page2.json.return_value = [{"id": i} for i in range(101, 151)]  # 50 items (partial)

        mock_http.request.side_effect = [page1, page2]

        items = [item async for item in client.paginate("/projects", limit=200)]

        # Gets 100 from page1 + 50 from page2 = 150 (stops because page2 < per_page)
        assert len(items) == 150
        assert mock_http.request.call_count == 2

    @pytest.mark.asyncio
    async def test_paginate_respects_limit(self, client_with_mock_http: tuple[GitLabClient, AsyncMock]) -> None:
        """paginate() stops at limit."""
        client, mock_http = client_with_mock_http

        page1 = MagicMock()
        page1.status_code = 200
        page1.json.return_value = [{"id": i} for i in range(1, 21)]  # 20 items

        mock_http.request.return_value = page1

        items = [item async for item in client.paginate("/projects", limit=5)]

        assert len(items) == 5
        # Should only need one request since first page has enough items
        assert mock_http.request.call_count == 1

    @pytest.mark.asyncio
    async def test_paginate_empty_response(self, client_with_mock_http: tuple[GitLabClient, AsyncMock]) -> None:
        """paginate() handles empty response."""
        client, mock_http = client_with_mock_http

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_http.request.return_value = mock_response

        items = [item async for item in client.paginate("/projects")]

        assert len(items) == 0

    @pytest.mark.asyncio
    async def test_paginate_partial_page_stops(self, client_with_mock_http: tuple[GitLabClient, AsyncMock]) -> None:
        """paginate() stops when page has fewer items than per_page."""
        client, mock_http = client_with_mock_http

        # Page with fewer items than requested per_page indicates last page
        page1 = MagicMock()
        page1.status_code = 200
        page1.json.return_value = [{"id": i} for i in range(1, 11)]  # 10 items

        mock_http.request.return_value = page1

        items = [item async for item in client.paginate("/projects", limit=50)]

        assert len(items) == 10
        # Should stop after first page since it returned less than per_page
        assert mock_http.request.call_count == 1


class TestGitLabClientEncoding:
    """Tests for URL encoding."""

    def test_encode_path_simple(self) -> None:
        """Simple paths are encoded."""
        instance = GitLabInstance(url="https://gitlab.com", token="test-token")
        client = GitLabClient(instance)

        assert client._encode_path("group/project") == "group%2Fproject"

    def test_encode_path_nested(self) -> None:
        """Nested paths are encoded."""
        instance = GitLabInstance(url="https://gitlab.com", token="test-token")
        client = GitLabClient(instance)

        assert client._encode_path("org/team/project") == "org%2Fteam%2Fproject"

    def test_encode_path_special_chars(self) -> None:
        """Special characters are encoded."""
        instance = GitLabInstance(url="https://gitlab.com", token="test-token")
        client = GitLabClient(instance)

        # Spaces, dots, etc. should be encoded
        assert client._encode_path("my project") == "my%20project"


class TestGitLabClientGetRaw:
    """Tests for get_raw() method (returns text, not JSON)."""

    @pytest.fixture
    def client_with_mock_http(self) -> tuple[GitLabClient, AsyncMock]:
        """Create client with mocked HTTP."""
        instance = GitLabInstance(url="https://gitlab.com", token="test-token")
        client = GitLabClient(instance)

        mock_http = AsyncMock()
        mock_http.is_closed = False
        client._http = mock_http
        client._token = "test-token"

        return client, mock_http

    @pytest.mark.asyncio
    async def test_get_raw_returns_text(self, client_with_mock_http: tuple[GitLabClient, AsyncMock]) -> None:
        """get_raw() returns response text (for job logs etc)."""
        client, mock_http = client_with_mock_http

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Build started...\nRunning tests...\nBuild complete!"
        mock_http.request.return_value = mock_response

        result = await client.get_raw("/projects/1/jobs/1/trace")

        assert result == "Build started...\nRunning tests...\nBuild complete!"

    @pytest.mark.asyncio
    async def test_get_raw_error_handling(self, client_with_mock_http: tuple[GitLabClient, AsyncMock]) -> None:
        """get_raw() handles errors."""
        client, mock_http = client_with_mock_http

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"message": "Job not found"}
        mock_response.text = "Not Found"
        mock_http.request.return_value = mock_response

        with pytest.raises(GitLabAPIError) as exc_info:
            await client.get_raw("/projects/1/jobs/999/trace")

        assert exc_info.value.status_code == 404
