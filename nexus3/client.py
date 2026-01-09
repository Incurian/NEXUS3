"""Async HTTP client for communicating with Nexus JSON-RPC servers."""

from typing import Any, cast
from urllib.parse import urlparse

import httpx

from nexus3.core.errors import NexusError
from nexus3.rpc.auth import discover_api_key
from nexus3.rpc.protocol import parse_response, serialize_request
from nexus3.rpc.types import Request, Response


class ClientError(NexusError):
    """Exception for client-side errors (connection, timeout, protocol)."""


class NexusClient:
    """Async HTTP client for Nexus JSON-RPC servers.

    Usage:
        async with NexusClient(api_key="nxk_...") as client:
            result = await client.send("Hello!")
            print(result)

        # Or with auto-discovery:
        async with NexusClient.with_auto_auth() as client:
            result = await client.send("Hello!")
    """

    def __init__(
        self,
        url: str = "http://127.0.0.1:8765",
        timeout: float = 60.0,
        api_key: str | None = None,
    ) -> None:
        """Initialize the client.

        Args:
            url: Base URL of the JSON-RPC server.
            timeout: Request timeout in seconds.
            api_key: Optional API key for authentication. If provided,
                     adds Authorization: Bearer <key> header to all requests.
        """
        self._url = url
        self._timeout = timeout
        self._api_key = api_key
        self._client: httpx.AsyncClient | None = None
        self._request_id = 0

    @classmethod
    def with_auto_auth(
        cls,
        url: str = "http://127.0.0.1:8765",
        timeout: float = 60.0,
    ) -> "NexusClient":
        """Create a client with auto-discovered API key.

        Attempts to discover the API key from:
        1. NEXUS3_API_KEY environment variable
        2. ~/.nexus3/server-{port}.key (port-specific)
        3. ~/.nexus3/server.key (default)

        Args:
            url: Base URL of the JSON-RPC server.
            timeout: Request timeout in seconds.

        Returns:
            NexusClient configured with discovered API key (or None if not found).
        """
        # Extract port from URL for key discovery
        parsed = urlparse(url)
        port = parsed.port or 8765
        api_key = discover_api_key(port=port)
        return cls(url=url, timeout=timeout, api_key=api_key)

    async def __aenter__(self) -> "NexusClient":
        """Enter async context, create httpx client."""
        self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit async context, close httpx client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _next_id(self) -> int:
        """Generate the next request ID."""
        self._request_id += 1
        return self._request_id

    async def _call(self, method: str, params: dict[str, Any] | None = None) -> Response:
        """Make a JSON-RPC call and return the response.

        Args:
            method: The RPC method name.
            params: Optional parameters for the method.

        Returns:
            The parsed Response object.

        Raises:
            ClientError: On connection error, timeout, or protocol error.
        """
        if self._client is None:
            raise ClientError("Client not initialized. Use 'async with' context manager.")

        request = Request(
            jsonrpc="2.0",
            method=method,
            params=params,
            id=self._next_id(),
        )

        # Build headers with optional auth
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        try:
            response = await self._client.post(
                self._url,
                content=serialize_request(request),
                headers=headers,
            )
            return parse_response(response.text)
        except httpx.ConnectError as e:
            raise ClientError(f"Connection failed: {e}") from e
        except httpx.TimeoutException as e:
            raise ClientError(f"Request timed out: {e}") from e

    def _check(self, response: Response) -> Any:
        """Extract result from response or raise ClientError on error.

        Args:
            response: The Response to check.

        Returns:
            The result field from the response.

        Raises:
            ClientError: If the response contains an error.
        """
        if response.error:
            code = response.error.get("code", -1)
            message = response.error.get("message", "Unknown error")
            raise ClientError(f"RPC error {code}: {message}")
        return response.result

    async def send(self, content: str, request_id: int | None = None) -> dict[str, Any]:
        """Send a message to the agent.

        Args:
            content: The message content.
            request_id: Optional request ID (auto-generated if not provided).

        Returns:
            The response dict with 'content' and optionally 'tokens'.
        """
        params: dict[str, Any] = {"content": content}
        response = await self._call("send", params)
        return cast(dict[str, Any], self._check(response))

    async def cancel(self, request_id: int | None = None) -> dict[str, Any]:
        """Cancel the current operation.

        Args:
            request_id: Optional request ID to cancel.

        Returns:
            The cancellation result.
        """
        params = {"request_id": request_id} if request_id else None
        response = await self._call("cancel", params)
        return cast(dict[str, Any], self._check(response))

    async def get_tokens(self) -> dict[str, Any]:
        """Get current token usage.

        Returns:
            Token usage breakdown dict.
        """
        response = await self._call("get_tokens")
        return cast(dict[str, Any], self._check(response))

    async def get_context(self) -> dict[str, Any]:
        """Get current context state.

        Returns:
            Context state dict.
        """
        response = await self._call("get_context")
        return cast(dict[str, Any], self._check(response))

    async def shutdown(self) -> dict[str, Any]:
        """Request graceful shutdown of the server.

        Returns:
            Shutdown acknowledgment.
        """
        response = await self._call("shutdown")
        return cast(dict[str, Any], self._check(response))

    # Global methods (called on root endpoint, not agent-specific)

    async def list_agents(self) -> list[str]:
        """List all agents on the server.

        Note: This should be called on the root URL (e.g., http://localhost:8765),
        not an agent-specific URL.

        Returns:
            List of agent IDs.
        """
        response = await self._call("list_agents")
        result = self._check(response)
        return cast(list[str], result.get("agents", []))

    async def create_agent(
        self,
        agent_id: str,
        preset: str | None = None,
        disable_tools: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new agent on the server.

        Note: This should be called on the root URL (e.g., http://localhost:8765),
        not an agent-specific URL.

        Args:
            agent_id: The ID for the new agent.
            preset: Permission preset (yolo, trusted, sandboxed, worker).
            disable_tools: List of tool names to disable for the agent.

        Returns:
            Creation result with agent_id.
        """
        params: dict[str, Any] = {"agent_id": agent_id}
        if preset is not None:
            params["preset"] = preset
        if disable_tools is not None:
            params["disable_tools"] = disable_tools
        response = await self._call("create_agent", params)
        return cast(dict[str, Any], self._check(response))

    async def destroy_agent(self, agent_id: str) -> dict[str, Any]:
        """Destroy an agent on the server.

        Note: This should be called on the root URL (e.g., http://localhost:8765),
        not an agent-specific URL.

        Args:
            agent_id: The ID of the agent to destroy.

        Returns:
            Destruction result.
        """
        response = await self._call("destroy_agent", {"agent_id": agent_id})
        return cast(dict[str, Any], self._check(response))

    async def shutdown_server(self) -> dict[str, Any]:
        """Request graceful shutdown of the entire server.

        Note: This should be called on the root URL (e.g., http://localhost:8765),
        not an agent-specific URL. This shuts down the entire server, not just
        an individual agent.

        Returns:
            Shutdown acknowledgment with success status.
        """
        response = await self._call("shutdown_server")
        return cast(dict[str, Any], self._check(response))
