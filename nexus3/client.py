"""Async HTTP client for communicating with Nexus JSON-RPC servers."""

from typing import Any, cast

import httpx

from nexus3.core.errors import NexusError
from nexus3.rpc.protocol import parse_response, serialize_request
from nexus3.rpc.types import Request, Response


class ClientError(NexusError):
    """Exception for client-side errors (connection, timeout, protocol)."""


class NexusClient:
    """Async HTTP client for Nexus JSON-RPC servers.

    Usage:
        async with NexusClient() as client:
            result = await client.send("Hello!")
            print(result)
    """

    def __init__(
        self,
        url: str = "http://127.0.0.1:8765",
        timeout: float = 60.0,
    ) -> None:
        """Initialize the client.

        Args:
            url: Base URL of the JSON-RPC server.
            timeout: Request timeout in seconds.
        """
        self._url = url
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._request_id = 0

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

        try:
            response = await self._client.post(
                self._url,
                content=serialize_request(request),
                headers={"Content-Type": "application/json"},
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
