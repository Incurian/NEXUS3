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

import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from nexus3.core.errors import NexusError, PathSecurityError
from nexus3.core.paths import validate_path

logger = logging.getLogger(__name__)
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

from pathlib import Path

from nexus3.core.permissions import AgentPermissions, PermissionDelta, ToolPermission
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
            logger.error("Unexpected error dispatching global method '%s': %s", request.method, e, exc_info=True)
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
                - cwd: Optional[str] - Working directory / sandbox root for the agent
                - allowed_write_paths: Optional[list[str]] - Paths where writes are allowed
                - model: Optional[str] - Model name/alias to use (from config.models or full ID)
                - initial_message: Optional[str] - Message to send immediately after creation

        Returns:
            Dict containing:
                - agent_id: str - The ID of the created agent
                - url: str - The URL to use for agent-specific RPC calls
                - response: Optional[dict] - Response from initial_message if provided

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
        cwd_param = params.get("cwd")
        allowed_write_paths = params.get("allowed_write_paths")
        model = params.get("model")
        initial_message = params.get("initial_message")

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
            # yolo is NOT allowed via RPC - only through interactive REPL
            valid_presets = {"trusted", "sandboxed", "worker"}
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

        # Validate model if provided
        if model is not None and not isinstance(model, str):
            raise InvalidParamsError(
                f"model must be string, got: {type(model).__name__}"
            )

        # Validate initial_message if provided
        if initial_message is not None and not isinstance(initial_message, str):
            raise InvalidParamsError(
                f"initial_message must be string, got: {type(initial_message).__name__}"
            )

        # Validate cwd if provided
        cwd_path: Path | None = None
        if cwd_param is not None:
            if not isinstance(cwd_param, str):
                raise InvalidParamsError(
                    f"cwd must be string, got: {type(cwd_param).__name__}"
                )
            try:
                # Use validate_path for consistent path resolution (follows symlinks)
                cwd_path = validate_path(cwd_param, allowed_paths=None)
            except PathSecurityError as e:
                raise InvalidParamsError(f"cwd invalid: {e.message}")
            if not cwd_path.exists():
                raise InvalidParamsError(f"cwd does not exist: {cwd_param}")
            if not cwd_path.is_dir():
                raise InvalidParamsError(f"cwd is not a directory: {cwd_param}")

        # Validate allowed_write_paths if provided
        write_paths: list[Path] | None = None
        if allowed_write_paths is not None:
            if not isinstance(allowed_write_paths, list):
                raise InvalidParamsError(
                    f"allowed_write_paths must be array, got: {type(allowed_write_paths).__name__}"
                )
            write_paths = []
            for i, wp in enumerate(allowed_write_paths):
                if not isinstance(wp, str):
                    raise InvalidParamsError(
                        f"allowed_write_paths[{i}] must be string, got: {type(wp).__name__}"
                    )
                write_paths.append(Path(wp).resolve())

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

            # SECURITY: Validate cwd is within parent's allowed paths
            if cwd_path is not None:
                parent_allowed = parent_permissions.effective_policy.allowed_paths
                if parent_allowed is not None:
                    try:
                        # Use validate_path for consistent containment check
                        validate_path(cwd_path, allowed_paths=parent_allowed)
                    except PathSecurityError:
                        raise InvalidParamsError(
                            f"cwd '{cwd_path}' is outside parent's allowed paths"
                        )

            # SECURITY: Validate write paths are within cwd (or parent's paths if no cwd)
            if write_paths:
                sandbox_root = cwd_path or Path.cwd()
                for wp in write_paths:
                    try:
                        wp.relative_to(sandbox_root)
                    except ValueError:
                        raise InvalidParamsError(
                            f"allowed_write_path '{wp}' is outside sandbox root '{sandbox_root}'"
                        )

        # Build delta from parameters (disable_tools and write permissions)
        delta: PermissionDelta | None = None
        delta_kwargs: dict[str, Any] = {}

        if disable_tools:
            delta_kwargs["disable_tools"] = disable_tools

        # Note: cwd is passed to AgentConfig and handled in resolve_preset,
        # not via delta (because SANDBOXED presets are frozen)

        # Build tool_overrides for write permissions
        # For sandboxed preset: read-only by default, write only to explicit paths
        # Note: preset defaults to "sandboxed" for RPC mode if not specified
        effective_preset = preset or "sandboxed"
        if effective_preset in ("sandboxed", "worker"):
            tool_overrides: dict[str, ToolPermission] = {}
            # If write_paths provided (even empty), use them; otherwise disable writes
            if write_paths is not None:
                for tool_name in ("write_file", "edit_file"):
                    tool_overrides[tool_name] = ToolPermission(
                        enabled=True,
                        allowed_paths=write_paths,
                    )
            else:
                # No write paths = read-only (disable write tools)
                for tool_name in ("write_file", "edit_file"):
                    tool_overrides[tool_name] = ToolPermission(enabled=False)
            delta_kwargs["tool_overrides"] = tool_overrides
        elif write_paths is not None:
            # For non-sandboxed presets, only apply if explicitly provided
            tool_overrides = {}
            for tool_name in ("write_file", "edit_file"):
                tool_overrides[tool_name] = ToolPermission(
                    enabled=True,
                    allowed_paths=write_paths,
                )
            delta_kwargs["tool_overrides"] = tool_overrides

        if delta_kwargs:
            delta = PermissionDelta(**delta_kwargs)

        # Create the agent through the pool
        config = AgentConfig(
            agent_id=agent_id,
            system_prompt=system_prompt,
            preset=preset,
            cwd=cwd_path,  # Pass cwd to AgentConfig for resolve_preset
            delta=delta,
            parent_permissions=parent_permissions,
            parent_agent_id=parent_agent_id,  # Pass actual parent agent ID
            model=model,  # Model name/alias for this agent
        )
        agent = await self._pool.create(agent_id=agent_id, config=config)

        result: dict[str, Any] = {
            "agent_id": agent.agent_id,
            "url": f"/agent/{agent.agent_id}",
        }

        # Send initial message if provided
        if initial_message:
            from nexus3.rpc.types import Request as RpcRequest
            send_request = RpcRequest(
                jsonrpc="2.0",
                method="send",
                params={"content": initial_message},
                id="initial_message",
            )
            response = await agent.dispatcher.dispatch(send_request)
            if response and response.result:
                result["response"] = response.result
            elif response and response.error:
                result["response"] = {"error": response.error}

        return result

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
