"""Direct agent API for in-process communication (bypasses HTTP).

This module provides an in-process API that matches NexusClient's interface
but calls dispatchers directly instead of going through HTTP. This eliminates
the overhead of HTTP serialization and network round-trips for same-process
agent communication.

Usage:
    # In AgentPool.create(), inject into ServiceContainer:
    agent_api = DirectAgentAPI(pool, global_dispatcher)
    services.register("agent_api", agent_api)

    # In NexusSkill, use instead of NexusClient:
    if self._services.has("agent_api"):
        api = self._services.get("agent_api")
        result = await api.create_agent("worker-1")
        scoped = api.for_agent("worker-1")
        response = await scoped.send("Hello!")
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nexus3.rpc.types import Request

if TYPE_CHECKING:
    from nexus3.rpc.dispatcher import Dispatcher
    from nexus3.rpc.global_dispatcher import GlobalDispatcher
    from nexus3.rpc.pool import AgentPool

logger = logging.getLogger(__name__)


def _extract_result(response: Any) -> Any:
    """Extract result from Response, raising ClientError on error.

    Args:
        response: Response object from dispatcher.dispatch()

    Returns:
        The result field from the response.

    Raises:
        ClientError: If response is None or contains an error.
    """
    # Import here to avoid circular import (client.py imports rpc.auth)
    from nexus3.client import ClientError

    if response is None:
        raise ClientError("No response from dispatcher")
    if response.error:
        code = response.error.get("code", -1)
        message = response.error.get("message", "Unknown error")
        raise ClientError(f"RPC error {code}: {message}")
    return response.result


class AgentScopedAPI:
    """API scoped to a specific agent for send/cancel/get_tokens/etc.

    This class provides direct access to an agent's dispatcher, bypassing
    HTTP for in-process communication.
    """

    def __init__(self, pool: "AgentPool", agent_id: str) -> None:
        """Initialize agent-scoped API.

        Args:
            pool: The AgentPool to look up agents.
            agent_id: The target agent's ID.
        """
        self._pool = pool
        self._agent_id = agent_id

    def _get_dispatcher(self) -> "Dispatcher":
        """Get the dispatcher for this agent.

        Returns:
            The agent's Dispatcher instance.

        Raises:
            ClientError: If agent not found.
        """
        from nexus3.client import ClientError

        agent = self._pool.get(self._agent_id)
        if agent is None:
            raise ClientError(f"Agent not found: {self._agent_id}")
        return agent.dispatcher

    async def send(
        self,
        content: str,
        request_id: str | int | None = None,
        *,
        source: str | None = None,
        source_agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Send a message to the agent.

        Args:
            content: The message content.
            request_id: Optional request ID for tracking/cancellation.
            source: Source type for attribution (e.g., "nexus_send", "repl", "api").
            source_agent_id: ID of the agent that sent this message.

        Returns:
            The response dict with 'content' and 'request_id' keys.
        """
        dispatcher = self._get_dispatcher()
        params: dict[str, Any] = {"content": content}
        if request_id is not None:
            params["request_id"] = request_id
        if source is not None:
            params["source"] = source
        if source_agent_id is not None:
            params["source_agent_id"] = source_agent_id
        request = Request(
            jsonrpc="2.0",
            method="send",
            params=params,
            id=1,
        )
        response = await dispatcher.dispatch(request)
        return _extract_result(response)

    async def cancel(self, request_id: str | int | None = None) -> dict[str, Any]:
        """Cancel an in-progress request.

        Args:
            request_id: The request ID to cancel.

        Returns:
            The cancellation result.
        """
        dispatcher = self._get_dispatcher()
        params = {"request_id": request_id} if request_id is not None else None
        request = Request(
            jsonrpc="2.0",
            method="cancel",
            params=params,
            id=1,
        )
        response = await dispatcher.dispatch(request)
        return _extract_result(response)

    async def get_tokens(self) -> dict[str, Any]:
        """Get current token usage.

        Returns:
            Token usage breakdown dict.
        """
        dispatcher = self._get_dispatcher()
        request = Request(
            jsonrpc="2.0",
            method="get_tokens",
            params=None,
            id=1,
        )
        response = await dispatcher.dispatch(request)
        return _extract_result(response)

    async def get_context(self) -> dict[str, Any]:
        """Get current context state.

        Returns:
            Context state dict.
        """
        dispatcher = self._get_dispatcher()
        request = Request(
            jsonrpc="2.0",
            method="get_context",
            params=None,
            id=1,
        )
        response = await dispatcher.dispatch(request)
        return _extract_result(response)

    async def shutdown(self) -> dict[str, Any]:
        """Request graceful shutdown of the agent.

        Returns:
            Shutdown acknowledgment.
        """
        dispatcher = self._get_dispatcher()
        request = Request(
            jsonrpc="2.0",
            method="shutdown",
            params=None,
            id=1,
        )
        response = await dispatcher.dispatch(request)
        return _extract_result(response)


class DirectAgentAPI:
    """In-process API that calls dispatchers directly (bypasses HTTP).

    This class provides the same interface as NexusClient but calls
    GlobalDispatcher and per-agent Dispatchers directly instead of
    making HTTP requests.

    For agent-scoped operations (send, cancel, etc.), use for_agent()
    to get an AgentScopedAPI instance.
    """

    def __init__(
        self,
        pool: "AgentPool",
        global_dispatcher: "GlobalDispatcher",
        requester_id: str | None = None,
    ) -> None:
        """Initialize direct agent API.

        Args:
            pool: The AgentPool for looking up agents.
            global_dispatcher: The GlobalDispatcher for global methods.
            requester_id: ID of the agent making requests (for authorization).
                         Used when calling destroy_agent to verify ownership.
        """
        self._pool = pool
        self._global_dispatcher = global_dispatcher
        self._requester_id = requester_id

    def for_agent(self, agent_id: str) -> AgentScopedAPI:
        """Get an API scoped to a specific agent.

        Args:
            agent_id: The target agent's ID.

        Returns:
            AgentScopedAPI for the specified agent.
        """
        return AgentScopedAPI(self._pool, agent_id)

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
        """Create a new agent.

        Args:
            agent_id: The ID for the new agent.
            preset: Permission preset (trusted, sandboxed).
            disable_tools: List of tool names to disable.
            parent_agent_id: ID of parent agent for ceiling enforcement.
            cwd: Working directory / sandbox root.
            allowed_write_paths: Paths where writes are allowed.
            model: Model name/alias to use.
            initial_message: Message to send immediately after creation.

        Returns:
            Creation result with agent_id, url, and optionally response.
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

        request = Request(
            jsonrpc="2.0",
            method="create_agent",
            params=params,
            id=1,
        )
        response = await self._global_dispatcher.dispatch(request)
        return _extract_result(response)

    async def destroy_agent(self, agent_id: str) -> dict[str, Any]:
        """Destroy an agent.

        Authorization: Only self or parent can destroy an agent. External
        clients (requester_id=None) are treated as admin.

        Args:
            agent_id: The ID of the agent to destroy.

        Returns:
            Destruction result.
        """
        request = Request(
            jsonrpc="2.0",
            method="destroy_agent",
            params={"agent_id": agent_id},
            id=1,
        )
        response = await self._global_dispatcher.dispatch(request, self._requester_id)
        return _extract_result(response)

    async def list_agents(self) -> list[str]:
        """List all agents on the server.

        Returns:
            List of agent IDs.
        """
        request = Request(
            jsonrpc="2.0",
            method="list_agents",
            params=None,
            id=1,
        )
        response = await self._global_dispatcher.dispatch(request)
        result = _extract_result(response)
        # GlobalDispatcher returns {"agents": [...]}
        return result.get("agents", [])

    async def shutdown_server(self) -> dict[str, Any]:
        """Request graceful shutdown of the server.

        Returns:
            Shutdown acknowledgment.
        """
        request = Request(
            jsonrpc="2.0",
            method="shutdown_server",
            params=None,
            id=1,
        )
        response = await self._global_dispatcher.dispatch(request)
        return _extract_result(response)


class ClientAdapter:
    """Adapter that makes AgentAPI look like NexusClient.

    This adapter wraps DirectAgentAPI and optional AgentScopedAPI to provide
    the same interface as NexusClient. This allows existing skill code that
    uses the `operation=lambda client: client.METHOD(...)` pattern to work
    with both HTTP (NexusClient) and in-process (AgentAPI) paths.
    """

    def __init__(
        self,
        global_api: DirectAgentAPI,
        agent_api: AgentScopedAPI | None = None,
    ) -> None:
        """Initialize the adapter.

        Args:
            global_api: DirectAgentAPI for global methods.
            agent_api: Optional AgentScopedAPI for agent-scoped methods.
        """
        self._global = global_api
        self._agent = agent_api

    def _require_agent(self, method_name: str) -> AgentScopedAPI:
        """Get agent API, raising ClientError if not set."""
        from nexus3.client import ClientError

        if self._agent is None:
            raise ClientError(f"No agent context for {method_name}()")
        return self._agent

    # Agent-scoped methods (require agent_api)

    async def send(
        self,
        content: str,
        request_id: str | int | None = None,
        *,
        source: str | None = None,
        source_agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Send a message to the agent."""
        return await self._require_agent("send").send(
            content, request_id, source=source, source_agent_id=source_agent_id
        )

    async def cancel(self, request_id: str | int | None = None) -> dict[str, Any]:
        """Cancel an in-progress request."""
        return await self._require_agent("cancel").cancel(request_id)

    async def get_tokens(self) -> dict[str, Any]:
        """Get current token usage."""
        return await self._require_agent("get_tokens").get_tokens()

    async def get_context(self) -> dict[str, Any]:
        """Get current context state."""
        return await self._require_agent("get_context").get_context()

    async def shutdown(self) -> dict[str, Any]:
        """Request graceful shutdown of the agent."""
        return await self._require_agent("shutdown").shutdown()

    # Global methods (use global_api)

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
        """Create a new agent."""
        return await self._global.create_agent(
            agent_id=agent_id,
            preset=preset,
            disable_tools=disable_tools,
            parent_agent_id=parent_agent_id,
            cwd=cwd,
            allowed_write_paths=allowed_write_paths,
            model=model,
            initial_message=initial_message,
            wait_for_initial_response=wait_for_initial_response,
        )

    async def destroy_agent(self, agent_id: str) -> dict[str, Any]:
        """Destroy an agent."""
        return await self._global.destroy_agent(agent_id)

    async def list_agents(self) -> list[str]:
        """List all agents."""
        return await self._global.list_agents()

    async def shutdown_server(self) -> dict[str, Any]:
        """Request graceful shutdown of the server."""
        return await self._global.shutdown_server()
