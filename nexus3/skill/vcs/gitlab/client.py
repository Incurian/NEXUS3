"""Async HTTP client for GitLab API."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator
from urllib.parse import quote

import httpx

from nexus3.core.url_validator import validate_url
from nexus3.skill.vcs.config import GitLabInstance


class GitLabAPIError(Exception):
    """GitLab API error with status code and message."""

    def __init__(self, status_code: int, message: str, response_body: Any = None):
        self.status_code = status_code
        self.message = message
        self.response_body = response_body
        super().__init__(f"GitLab API error {status_code}: {message}")


class GitLabClient:
    """
    Async HTTP client for GitLab REST API.

    Features:
    - Async-native with httpx
    - SSRF protection via URL validation
    - Automatic pagination
    - Retry with exponential backoff
    - Connection pooling
    """

    DEFAULT_TIMEOUT = 30.0
    DEFAULT_PER_PAGE = 20
    MAX_PER_PAGE = 100
    MAX_RETRIES = 3
    RETRY_BACKOFF = 1.5

    def __init__(
        self,
        instance: GitLabInstance,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self._instance = instance
        self._base_url = instance.url.rstrip("/") + "/api/v4"
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = None
        self._token: str | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Lazily create HTTP client."""
        if self._http is None or self._http.is_closed:
            # Resolve token
            self._token = self._instance.get_token()
            if not self._token:
                raise GitLabAPIError(401, "No GitLab token configured")

            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                headers={
                    "PRIVATE-TOKEN": self._token,
                    "User-Agent": "NEXUS3-GitLab-Client/1.0",
                },
                # Don't follow redirects automatically (security)
                follow_redirects=False,
            )
        return self._http

    async def close(self) -> None:
        """Close HTTP client."""
        if self._http and not self._http.is_closed:
            await self._http.aclose()
            self._http = None

    async def __aenter__(self) -> "GitLabClient":
        await self._ensure_client()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    def _encode_path(self, project_or_group: str) -> str:
        """URL-encode project/group path (e.g., 'group/subgroup/repo')."""
        return quote(project_or_group, safe="")

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        retry: int = 0,
    ) -> Any:
        """
        Make HTTP request with retry logic.

        Returns parsed JSON response.
        Raises GitLabAPIError on failure.
        """
        client = await self._ensure_client()
        url = f"{self._base_url}{path}"

        # Validate URL before request (defense in depth)
        validate_url(url, allow_localhost=True, allow_private=False)

        try:
            response = await client.request(
                method=method,
                url=url,
                params=params,
                json=json,
            )

            # Handle rate limiting
            if response.status_code == 429:
                if retry < self.MAX_RETRIES:
                    retry_after = int(response.headers.get("Retry-After", 5))
                    await asyncio.sleep(min(retry_after, 60))
                    return await self._request(method, path, params, json, retry + 1)
                raise GitLabAPIError(429, "Rate limit exceeded")

            # Handle server errors with retry
            if response.status_code >= 500:
                if retry < self.MAX_RETRIES:
                    await asyncio.sleep(self.RETRY_BACKOFF ** retry)
                    return await self._request(method, path, params, json, retry + 1)

            # Handle client errors
            if response.status_code >= 400:
                try:
                    body = response.json()
                    message = body.get("message", body.get("error", str(body)))
                except Exception:
                    body = None
                    message = response.text
                raise GitLabAPIError(response.status_code, message, body)

            # Return JSON response (or None for 204)
            if response.status_code == 204:
                return None
            return response.json()

        except httpx.TimeoutException:
            if retry < self.MAX_RETRIES:
                await asyncio.sleep(self.RETRY_BACKOFF ** retry)
                return await self._request(method, path, params, json, retry + 1)
            raise GitLabAPIError(0, "Request timeout")

        except httpx.RequestError as e:
            raise GitLabAPIError(0, f"Request failed: {e}")

    async def get(self, path: str, **params: Any) -> Any:
        """GET request."""
        return await self._request("GET", path, params=params or None)

    async def post(self, path: str, **data: Any) -> Any:
        """POST request."""
        return await self._request("POST", path, json=data or None)

    async def put(self, path: str, **data: Any) -> Any:
        """PUT request."""
        return await self._request("PUT", path, json=data or None)

    async def delete(self, path: str) -> Any:
        """DELETE request."""
        return await self._request("DELETE", path)

    async def paginate(
        self,
        path: str,
        limit: int = DEFAULT_PER_PAGE,
        **params: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Auto-paginate through results.

        Yields individual items up to `limit` total.
        """
        per_page = min(limit, self.MAX_PER_PAGE)
        page = 1
        count = 0

        while count < limit:
            params["page"] = page
            params["per_page"] = per_page

            results = await self.get(path, **params)

            if not results:
                break

            for item in results:
                yield item
                count += 1
                if count >= limit:
                    break

            if len(results) < per_page:
                break

            page += 1

    # =========================================================================
    # Convenience methods for common endpoints
    # =========================================================================

    async def get_current_user(self) -> dict[str, Any]:
        """Get authenticated user info."""
        return await self.get("/user")

    async def get_project(self, project: str) -> dict[str, Any]:
        """Get project by path or ID."""
        return await self.get(f"/projects/{self._encode_path(project)}")

    async def list_projects(
        self,
        owned: bool = False,
        membership: bool = False,
        search: str | None = None,
        limit: int = DEFAULT_PER_PAGE,
    ) -> list[dict[str, Any]]:
        """List accessible projects."""
        params: dict[str, Any] = {}
        if owned:
            params["owned"] = True
        if membership:
            params["membership"] = True
        if search:
            params["search"] = search

        return [item async for item in self.paginate("/projects", limit=limit, **params)]
