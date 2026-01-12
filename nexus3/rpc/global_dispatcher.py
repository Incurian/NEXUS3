"""JSON-RPC dispatcher for global (non-agent-specific) methods.

This dispatcher handles agent lifecycle management methods that operate
on the AgentPool rather than individual agent sessions:

- create_agent: Create a new agent instance
- destroy_agent: Destroy an existing agent
- list_agents: List all active agents
- shutdown_server: Signal the server to shut down

These methods are typically called before routing to agent-specific
dispatchers, or when the request doesn't target a specific agent.
"""

from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from nexus3.core.errors import NexusError
from nexus3.rpc.dispatcher import InvalidParamsError
from nexus3.rpc.protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    make_error_response,
    make_success_response,
)
from nexus3.rpc.types import Request, Response

if TYPE_CHECKING:
    from nexus3.rpc.pool import AgentPool

from nexus3.core.permissions import AgentPermissions, PermissionDelta
from nexus3.core.validation import ValidationError, validate_agent_id
from nexus3.rpc.pool import AgentConfig

# Type alias for handler functions
Handler = Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]


class GlobalDispatcher:
    """Handles global (non-agent-specific) RPC methods.

    This dispatcher manages agent lifecycle operations through the AgentPool.
    It follows the same dispatch pattern as the agent-specific Dispatcher
    but operates at the pool level rather than session level.

    Attributes:
        _pool: The AgentPool instance for managing agents.
        _handlers: Mapping of method names to handler functions.

    Example:
        pool = AgentPool()
        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="create_agent",
            params={"agent_id": "my-agent"},
            id=1,
        )
        response = await dispatcher.dispatch(request)
    """

    def __init__(self, pool: "AgentPool") -> None:
        """Initialize the global dispatcher.

        Args:
            pool: The AgentPool instance for managing agents.
        """
        self._pool = pool
        self._shutdown_requested = False
        self._handlers: dict[str, Handler] = {
            "create_agent": self._handle_create_agent,
            "destroy_agent": self._handle_destroy_agent,
            "list_agents": self._handle_list_agents,
            "shutdown_server": self._handle_shutdown_server,
        }

    def handles(self, method: str) -> bool:
        """Check if this dispatcher handles the given method.

        Args:
            method: The method name to check.

        Returns:
            True if this dispatcher handles the method, False otherwise.
        """
        return method in self._handlers

    async def dispatch(self, request: Request) -> Response | None:
        """Dispatch a request to the appropriate handler.

        Args:
            request: The parsed JSON-RPC request.

        Returns:
            A Response object, or None for notifications (requests without id).
        """
        # Look up handler
        handler = self._handlers.get(request.method)
        if handler is None:
            # Method not found
            if request.id is None:
                return None  # Notifications don't get error responses
            return make_error_response(
                request.id,
                METHOD_NOT_FOUND,
                f"Method not found: {request.method}",
            )

        # Execute handler
        try:
            params = request.params or {}
            result = await handler(params)

            # Return response (None for notifications)
            if request.id is None:
                return None
            return make_success_response(request.id, result)

        except InvalidParamsError as e:
            if request.id is None:
                return None
            return make_error_response(request.id, INVALID_PARAMS, str(e))

        except NexusError as e:
            if request.id is None:
                return None
            return make_error_response(request.id, INTERNAL_ERROR, e.message)

        except Exception as e:
            if request.id is None:
                return None
            return make_error_response(
                request.id,
                INTERNAL_ERROR,
                f"Internal error: {type(e).__name__}: {e}",
            )

    async def _handle_create_agent(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new agent.

        Creates a new agent instance in the pool. The agent will be assigned
        a unique ID (either provided or auto-generated) and will be accessible
        via its URL for subsequent RPC calls.

        Args:
            params: Optional parameters:
                - agent_id: Optional[str] - ID for the agent (auto-generated if omitted)
                - system_prompt: Optional[str] - System prompt override for this agent
                - preset: Optional[str] - Permission preset (yolo, trusted, sandboxed, worker)
                - disable_tools: Optional[list[str]] - Tools to disable for the agent
                - parent_agent_id: Optional[str] - ID of parent agent for ceiling enforcement

        Returns:
            Dict containing:
                - agent_id: str - The ID of the created agent
                - url: str - The URL to use for agent-specific RPC calls

        Raises:
            InvalidParamsError: If agent_id is provided but already exists,
                or if parameter types are invalid, or if requested permissions
                exceed parent ceiling.
        """
        agent_id = params.get("agent_id")
        system_prompt = params.get("system_prompt")
        preset = params.get("preset")
        disable_tools = params.get("disable_tools")
        parent_agent_id = params.get("parent_agent_id")

        # Validate agent_id if provided
        if agent_id is not None:
            if not isinstance(agent_id, str):
                raise InvalidParamsError(
                    f"agent_id must be string, got: {type(agent_id).__name__}"
                )
            # SECURITY: Validate agent_id format to prevent path traversal
            try:
                validate_agent_id(agent_id)
            except ValidationError as e:
                raise InvalidParamsError(e.message)

        # Validate system_prompt if provided
        if system_prompt is not None and not isinstance(system_prompt, str):
            raise InvalidParamsError(
                f"system_prompt must be string, got: {type(system_prompt).__name__}"
            )

        # Validate preset if provided
        if preset is not None:
            if not isinstance(preset, str):
                raise InvalidParamsError(
                    f"preset must be string, got: {type(preset).__name__}"
                )
            valid_presets = {"yolo", "trusted", "sandboxed", "worker"}
            if preset not in valid_presets:
                raise InvalidParamsError(
                    f"Invalid preset: {preset}. Valid: {sorted(valid_presets)}"
                )

        # Validate disable_tools if provided
        if disable_tools is not None:
            if not isinstance(disable_tools, list):
                raise InvalidParamsError(
                    f"disable_tools must be array, got: {type(disable_tools).__name__}"
                )
            for i, tool in enumerate(disable_tools):
                if not isinstance(tool, str):
                    raise InvalidParamsError(
                        f"disable_tools[{i}] must be string, got: {type(tool).__name__}"
                    )

        # Validate and look up parent_agent_id if provided
        # SECURITY: Look up parent permissions from pool instead of trusting RPC data
        parent_permissions: AgentPermissions | None = None
        if parent_agent_id is not None:
            if not isinstance(parent_agent_id, str):
                raise InvalidParamsError(
                    f"parent_agent_id must be string, got: {type(parent_agent_id).__name__}"
                )
            parent_agent = self._pool.get(parent_agent_id)
            if parent_agent is None:
                raise InvalidParamsError(f"Parent agent not found: {parent_agent_id}")
            parent_permissions = parent_agent.services.get("permissions")
            if parent_permissions is None:
                raise InvalidParamsError(
                    f"Parent agent '{parent_agent_id}' has no permissions configured"
                )

        # Build delta from disable_tools
        delta: PermissionDelta | None = None
        if disable_tools:
            delta = PermissionDelta(disable_tools=disable_tools)

        # Create the agent through the pool
        config = AgentConfig(
            agent_id=agent_id,
            system_prompt=system_prompt,
            preset=preset,
            delta=delta,
            parent_permissions=parent_permissions,
            parent_agent_id=parent_agent_id,  # Pass actual parent agent ID
        )
        agent = await self._pool.create(agent_id=agent_id, config=config)

        return {
            "agent_id": agent.agent_id,
            "url": f"/agent/{agent.agent_id}",
        }

    async def _handle_destroy_agent(self, params: dict[str, Any]) -> dict[str, Any]:
        """Destroy an agent.

        Removes an agent from the pool and cleans up its resources.
        Any in-progress requests for this agent will be cancelled.

        Args:
            params: Required parameters:
                - agent_id: str - ID of the agent to destroy

        Returns:
            Dict containing:
                - success: bool - True if agent was destroyed
                - agent_id: str - The ID of the destroyed agent

        Raises:
            InvalidParamsError: If agent_id is missing or invalid.
        """
        agent_id = params.get("agent_id")

        # Validate required parameter
        if agent_id is None:
            raise InvalidParamsError("Missing required parameter: agent_id")
        if not isinstance(agent_id, str):
            raise InvalidParamsError(
                f"agent_id must be string, got: {type(agent_id).__name__}"
            )

        # Destroy the agent through the pool
        success = await self._pool.destroy(agent_id)

        return {
            "success": success,
            "agent_id": agent_id,
        }

    async def _handle_list_agents(self, params: dict[str, Any]) -> dict[str, Any]:
        """List all agents.

        Returns information about all active agents in the pool.

        Args:
            params: Ignored (no parameters required).

        Returns:
            Dict containing:
                - agents: List of agent info dicts, each containing:
                    - agent_id: str - The agent's ID
                    - created_at: str - ISO 8601 timestamp of creation
                    - message_count: int - Number of messages in context
        """
        agents = self._pool.list()

        return {"agents": agents}

    async def _handle_shutdown_server(self, params: dict[str, Any]) -> dict[str, Any]:
        """Signal the server to shut down.

        Sets a flag that the HTTP server loop can check to initiate
        a graceful shutdown. The actual shutdown is handled by the
        server, not this dispatcher.

        Args:
            params: Ignored (no parameters required).

        Returns:
            Dict containing:
                - success: bool - Always True
                - message: str - Confirmation message
        """
        self._shutdown_requested = True
        return {
            "success": True,
            "message": "Server shutting down",
        }

    @property
    def shutdown_requested(self) -> bool:
        """Check if server shutdown has been requested.

        Returns:
            True if shutdown_server method has been called, False otherwise.
        """
        return self._shutdown_requested
