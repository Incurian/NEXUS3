"""Async HTTP client for communicating with Nexus JSON-RPC servers."""

import logging
from typing import Any, cast
from urllib.parse import urlparse

import httpx

from nexus3.core.errors import NexusError
from nexus3.core.url_validator import UrlSecurityError, validate_url
from nexus3.rpc.auth import discover_rpc_token
from nexus3.rpc.protocol import ParseError, parse_response, serialize_request
from nexus3.rpc.types import Request, Response

logger = logging.getLogger(__name__)


def _get_default_port() -> int:
    """Get default port from config, with fallback to 8765."""
    try:
        from nexus3.config.loader import load_config
        config = load_config()
        return config.server.port
    except Exception:
        return 8765


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
        url: str | None = None,
        timeout: float = 60.0,
        api_key: str | None = None,
        skip_url_validation: bool = False,
    ) -> None:
        """Initialize the client.

        Args:
            url: Base URL of the JSON-RPC server. If None, uses config default.
            timeout: Request timeout in seconds.
            api_key: Optional API key for authentication. If provided,
                     adds Authorization: Bearer <key> header to all requests.
            skip_url_validation: If True, skip URL security validation.
                     Use with caution - only for edge cases where standard
                     validation blocks legitimate URLs.

        Raises:
            ValueError: If URL fails security validation (and skip_url_validation=False).
        """
        if url is None:
            url = f"http://127.0.0.1:{_get_default_port()}"
        elif not skip_url_validation:
            # Validate URL for SSRF protection
            # Allow localhost (local server) and private networks (internal deployments)
            try:
                validate_url(url, allow_localhost=True, allow_private=True)
            except UrlSecurityError as e:
                raise ValueError(f"Invalid server URL: {e}") from e

        self._url = url
        self._timeout = timeout
        self._api_key = api_key
        self._client: httpx.AsyncClient | None = None
        self._request_id = 0
        logger.debug("NexusClient initialized: url=%s, timeout=%s", url, timeout)

    # Hosts considered safe for auto-auth (local token discovery)
    _LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

    @classmethod
    def _is_loopback(cls, host: str | None) -> bool:
        """Check if host is a loopback address (safe for auto-auth)."""
        if host is None:
            return True  # Default URL will be localhost
        return host.lower() in cls._LOOPBACK_HOSTS

    @classmethod
    def with_auto_auth(
        cls,
        url: str | None = None,
        timeout: float = 60.0,
    ) -> "NexusClient":
        """Create a client with auto-discovered API key.

        For loopback URLs (localhost, 127.0.0.1, ::1), attempts to discover
        the API key from:
        1. NEXUS3_API_KEY environment variable
        2. ~/.nexus3/rpc-{port}.token (port-specific)
        3. ~/.nexus3/rpc.token (default)

        For non-loopback URLs, auto-discovery is disabled to prevent token
        exfiltration. Use explicit api_key parameter for remote connections.

        Args:
            url: Base URL of the JSON-RPC server.
            timeout: Request timeout in seconds.

        Returns:
            NexusClient configured with discovered API key (or None if not found
            or if URL is non-loopback).
        """
        # Extract host and port from URL for safety check and key discovery
        parsed = urlparse(url) if url else None
        host = parsed.hostname if parsed else None
        port = (parsed.port if parsed else None) or _get_default_port()

        api_key: str | None = None

        # SECURITY: Only auto-discover tokens for loopback addresses
        # This prevents token exfiltration to remote servers via --connect
        if cls._is_loopback(host):
            api_key = discover_rpc_token(port=port)
            if api_key:
                logger.debug("Auto-discovered API key for port %d", port)
            else:
                logger.debug("No API key found for port %d", port)
        else:
            logger.warning(
                "Auto-auth disabled for non-loopback host '%s'. "
                "Use explicit api_key for remote connections.",
                host,
            )

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

        logger.debug("RPC call: method=%s, id=%s", method, request.id)
        try:
            response = await self._client.post(
                self._url,
                content=serialize_request(request),
                headers=headers,
            )
            return parse_response(response.text)
        except httpx.ConnectError as e:
            logger.warning("Connection failed to %s: %s", self._url, e)
            raise ClientError(f"Connection failed: {e}") from e
        except httpx.TimeoutException as e:
            logger.warning("Request timed out: method=%s, timeout=%s", method, self._timeout)
            raise ClientError(f"Request timed out: {e}") from e
        except ParseError as e:
            # Server returned non-JSON-RPC response (likely HTTP error)
            logger.warning("Invalid server response for method=%s: %s", method, e)
            raise ClientError(f"Invalid server response: {e}") from e

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
            logger.warning("RPC error %d: %s", code, message)
            raise ClientError(f"RPC error {code}: {message}")
        return response.result

    async def send(
        self,
        content: str,
        request_id: str | int | None = None,
        source: str | None = None,
        source_agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Send a message to the agent.

        Args:
            content: The message content.
            request_id: Optional request ID for tracking/cancellation.
            source: Source of the message (e.g., "nexus_send", "repl").
            source_agent_id: Agent ID of the sender (for agent-to-agent messages).

        Returns:
            The response dict with 'content' and optionally 'tokens'.
        """
        params: dict[str, Any] = {"content": content}
        if request_id is not None:
            params["request_id"] = request_id
        if source is not None:
            params["source"] = source
        if source_agent_id is not None:
            params["source_agent_id"] = source_agent_id
        response = await self._call("send", params)
        return cast(dict[str, Any], self._check(response))

    async def cancel(self, request_id: str | int | None = None) -> dict[str, Any]:
        """Cancel the current operation.

        Args:
            request_id: Optional request ID to cancel.

        Returns:
            The cancellation result.
        """
        params = {"request_id": request_id} if request_id is not None else None
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

    async def compact(self, force: bool = True) -> dict[str, Any]:
        """Force context compaction to reclaim token space.

        Useful for recovering stuck agents that have exceeded their context
        window. Summarizes old messages to reclaim tokens.

        Args:
            force: If True (default), compact even if under threshold.

        Returns:
            Compaction result with tokens_before, tokens_after, tokens_saved,
            or reason if nothing to compact.
        """
        response = await self._call("compact", {"force": force})
        return cast(dict[str, Any], self._check(response))

    async def get_messages(
        self,
        offset: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        """Get recent message history for transcript sync.

        Args:
            offset: Start index (default 0).
            limit: Number of messages to return (default 200, max 2000).

        Returns:
            Dict containing:
                - agent_id: The agent's ID
                - total: Total messages in context
                - offset: Requested offset
                - limit: Requested limit
                - messages: List of message dicts with index, role, content, tool_call_id
        """
        response = await self._call("get_messages", {"offset": offset, "limit": limit})
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
        parent_agent_id: str | None = None,
        cwd: str | None = None,
        allowed_write_paths: list[str] | None = None,
        model: str | None = None,
        initial_message: str | None = None,
        wait_for_initial_response: bool = False,
    ) -> dict[str, Any]:
        """Create a new agent on the server.

        Note: This should be called on the root URL (e.g., http://localhost:8765),
        not an agent-specific URL.

        Args:
            agent_id: The ID for the new agent.
            preset: Permission preset (trusted, sandboxed). Note: yolo
                is only available via interactive REPL, not programmatic API.
            disable_tools: List of tool names to disable for the agent.
            parent_agent_id: ID of the parent agent for ceiling enforcement.
                Server will look up parent's permissions from the pool.
            cwd: Working directory / sandbox root for the agent. For SANDBOXED
                preset, this becomes the only allowed path. Must be within
                parent's allowed paths.
            allowed_write_paths: List of paths where write_file/edit_file are
                allowed. For SANDBOXED agents, defaults to empty (read-only).
                Must be within cwd and parent's allowed paths.
            model: Model name/alias to use (from config.models or full model ID).
            initial_message: Message to send to the agent immediately after creation.
                By default (wait_for_initial_response=False), the message is queued
                and the call returns immediately with 'initial_request_id' and
                'initial_status'='queued'. Set wait_for_initial_response=True to
                block until the response is ready.
            wait_for_initial_response: If True, block until initial_message response
                is ready and include it in result['response']. Default False.

        Returns:
            Creation result with agent_id and url. If initial_message provided:
            - wait_for_initial_response=False: includes initial_request_id, initial_status
            - wait_for_initial_response=True: includes response dict
        """
        params: dict[str, Any] = {"agent_id": agent_id}
        if preset is not None:
            params["preset"] = preset
        if disable_tools is not None:
            params["disable_tools"] = disable_tools
        if parent_agent_id is not None:
            params["parent_agent_id"] = parent_agent_id
        if cwd is not None:
            params["cwd"] = cwd
        if allowed_write_paths is not None:
            params["allowed_write_paths"] = allowed_write_paths
        if model is not None:
            params["model"] = model
        if initial_message is not None:
            params["initial_message"] = initial_message
        if wait_for_initial_response:
            params["wait_for_initial_response"] = wait_for_initial_response
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
