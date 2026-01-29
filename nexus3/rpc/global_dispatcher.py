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

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import validate_path

logger = logging.getLogger(__name__)
from nexus3.rpc.dispatch_core import InvalidParamsError, dispatch_request
from nexus3.rpc.types import Request, Response

if TYPE_CHECKING:
    from nexus3.rpc.pool import AgentPool

from pathlib import Path

from nexus3.core.permissions import AgentPermissions, PermissionDelta, ToolPermission
from nexus3.core.validation import ValidationError, validate_agent_id
from nexus3.rpc.pool import Agent, AgentConfig, AuthorizationError
import asyncio
import uuid

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
        # Requester context set by dispatch() before calling handlers
        self._current_requester_id: str | None = None

    def handles(self, method: str) -> bool:
        """Check if this dispatcher handles the given method.

        Args:
            method: The method name to check.

        Returns:
            True if this dispatcher handles the method, False otherwise.
        """
        return method in self._handlers

    async def dispatch(
        self,
        request: Request,
        requester_id: str | None = None,
    ) -> Response | None:
        """Dispatch a request to the appropriate handler.

        Args:
            request: The parsed JSON-RPC request.
            requester_id: ID of the requesting agent (from X-Nexus-Agent header).
                         None for external clients (CLI, scripts).

        Returns:
            A Response object, or None for notifications (requests without id).
        """
        # Store requester context for handlers (esp. _handle_destroy_agent)
        self._current_requester_id = requester_id
        try:
            return await dispatch_request(request, self._handlers, "global method")
        finally:
            self._current_requester_id = None

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
                raise InvalidParamsError(e.message) from e

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
        if initial_message is not None:
            if not isinstance(initial_message, str):
                raise InvalidParamsError(
                    f"initial_message must be string, got: {type(initial_message).__name__}"
                )
            if not initial_message.strip():
                raise InvalidParamsError("initial_message cannot be empty")

        # Validate and look up parent_agent_id FIRST (needed for cwd resolution)
        # SECURITY: Look up parent permissions from pool instead of trusting RPC data
        parent_agent: Agent | None = None
        parent_permissions: AgentPermissions | None = None
        parent_cwd: Path | None = None
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
            # Get parent's cwd for resolving relative paths
            parent_cwd = parent_agent.services.get("cwd")

        # Validate cwd if provided
        cwd_path: Path | None = None
        if cwd_param is not None:
            if not isinstance(cwd_param, str):
                raise InvalidParamsError(
                    f"cwd must be string, got: {type(cwd_param).__name__}"
                )
            # Resolve relative cwd against parent's cwd (not server's cwd)
            cwd_input = Path(cwd_param)
            if not cwd_input.is_absolute() and parent_cwd is not None:
                cwd_param = str(parent_cwd / cwd_input)
            try:
                # Use validate_path for consistent path resolution (follows symlinks)
                cwd_path = validate_path(cwd_param, allowed_paths=None)
            except PathSecurityError as e:
                raise InvalidParamsError(f"cwd invalid: {e.message}") from e
            if not cwd_path.exists():
                raise InvalidParamsError(f"cwd does not exist: {cwd_param}")
            if not cwd_path.is_dir():
                raise InvalidParamsError(f"cwd is not a directory: {cwd_param}")
        elif parent_cwd is not None:
            # Inherit cwd from parent if not specified
            cwd_path = parent_cwd

        # SECURITY: Validate cwd is within parent's allowed paths AND parent's cwd
        if cwd_path is not None and parent_permissions is not None:
            parent_allowed = parent_permissions.effective_policy.allowed_paths
            if parent_allowed is not None:
                try:
                    # Use validate_path for consistent containment check
                    validate_path(cwd_path, allowed_paths=parent_allowed)
                except PathSecurityError as e:
                    raise InvalidParamsError(
                        f"cwd '{cwd_path}' is outside parent's allowed paths"
                    ) from e

            # For TRUSTED parents (allowed_paths=None), still validate against parent's cwd
            # This ensures subagent can only operate within parent's working directory
            if parent_cwd is not None and isinstance(parent_cwd, Path):
                try:
                    cwd_path.resolve().relative_to(parent_cwd.resolve())
                except ValueError:
                    raise InvalidParamsError(
                        f"cwd '{cwd_path}' is outside parent's cwd '{parent_cwd}'"
                    )

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
                # Resolve relative paths against agent's effective cwd
                wp_path = Path(wp)
                if not wp_path.is_absolute():
                    base = cwd_path if cwd_path is not None else Path.cwd()
                    wp_path = base / wp_path
                write_paths.append(wp_path.resolve())

        # SECURITY: Validate write paths are within cwd (sandbox root)
        # Applies to ALL sandboxed/worker agents, not just subagents
        effective_preset = preset or "sandboxed"
        if effective_preset in ("sandboxed", "worker") and write_paths:
            sandbox_root = cwd_path if cwd_path is not None else Path.cwd()
            for wp in write_paths:
                try:
                    wp.relative_to(sandbox_root)
                except ValueError as e:
                    raise InvalidParamsError(
                        f"allowed_write_path '{wp}' is outside sandbox root '{sandbox_root}'"
                    ) from e

        # SECURITY: For subagents, validate write paths are within parent's cwd
        # This prevents a parent from granting child write access outside parent's scope
        if write_paths and parent_cwd is not None and isinstance(parent_cwd, Path):
            parent_cwd_resolved = parent_cwd.resolve()
            for wp in write_paths:
                try:
                    wp.relative_to(parent_cwd_resolved)
                except ValueError:
                    raise InvalidParamsError(
                        f"allowed_write_path '{wp}' is outside parent's cwd '{parent_cwd}'"
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
        # Note: effective_preset already defined above during write_paths validation

        # All tools that can modify the filesystem
        WRITE_FILE_TOOLS = ("write_file", "edit_file", "append_file", "regex_replace", "mkdir")
        MIXED_FILE_TOOLS = ("copy_file", "rename")  # Read source, write destination

        if effective_preset in ("sandboxed", "worker"):
            tool_overrides: dict[str, ToolPermission] = {}

            if write_paths is not None and write_paths:
                # Enable write tools with explicit allowed paths
                for tool_name in WRITE_FILE_TOOLS:
                    tool_overrides[tool_name] = ToolPermission(
                        enabled=True,
                        allowed_paths=write_paths,
                    )
                # Mixed tools: also restrict to write paths
                for tool_name in MIXED_FILE_TOOLS:
                    tool_overrides[tool_name] = ToolPermission(
                        enabled=True,
                        allowed_paths=write_paths,
                    )
            else:
                # No write paths = disable all write-capable tools
                for tool_name in WRITE_FILE_TOOLS + MIXED_FILE_TOOLS:
                    tool_overrides[tool_name] = ToolPermission(enabled=False)

            delta_kwargs["tool_overrides"] = tool_overrides
        elif write_paths is not None:
            # For non-sandboxed presets, only apply if explicitly provided
            tool_overrides = {}
            for tool_name in WRITE_FILE_TOOLS:
                tool_overrides[tool_name] = ToolPermission(
                    enabled=True,
                    allowed_paths=write_paths,
                )
            for tool_name in MIXED_FILE_TOOLS:
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

        logger.info(
            "Agent created: %s (preset=%s, cwd=%s, model=%s)",
            agent.agent_id,
            preset or "default",
            cwd_path or ".",
            model or "default",
        )

        result: dict[str, Any] = {
            "agent_id": agent.agent_id,
            "url": f"/agent/{agent.agent_id}",
        }

        # Handle initial_message if provided
        if initial_message is not None:
            wait_for_initial_response = params.get("wait_for_initial_response", False)
            if not isinstance(wait_for_initial_response, bool):
                raise InvalidParamsError("wait_for_initial_response must be boolean")

            request_id = str(uuid.uuid4())
            from nexus3.rpc.types import Request as RpcRequest

            send_request = RpcRequest(
                jsonrpc="2.0",
                method="send",
                params={"content": initial_message, "request_id": request_id},
                id="initial_message",
            )

            result["initial_request_id"] = request_id

            if wait_for_initial_response:
                try:
                    response = await agent.dispatcher.dispatch(send_request)
                    if response and response.result:
                        result["response"] = response.result
                    elif response and response.error:
                        result["response"] = {"error": response.error}
                except Exception as e:
                    logger.error(f"Initial message failed for {agent.agent_id}: {e}")
                    result["response"] = {"error": {"message": str(e)}}
            else:
                task = asyncio.create_task(
                    self._send_initial_background(agent, send_request, request_id)
                )

                def done_callback(t: asyncio.Task[None]) -> None:
                    try:
                        if t.exception():
                            logger.error(
                                f"Bg initial FAILED {agent.agent_id}/{request_id}: {t.exception()}"
                            )
                    except Exception:
                        pass

                task.add_done_callback(done_callback)
                result["initial_status"] = "queued"

        return result

    async def _handle_destroy_agent(self, params: dict[str, Any]) -> dict[str, Any]:
        """Destroy an agent.

        Removes an agent from the pool and cleans up its resources.
        Any in-progress requests for this agent will be cancelled.

        Authorization Rules:
        - Self-destruction is allowed (agent destroys itself)
        - Parent can destroy its children
        - External clients (requester_id=None) are treated as admin

        Args:
            params: Required parameters:
                - agent_id: str - ID of the agent to destroy

        Returns:
            Dict containing:
                - success: bool - True if agent was destroyed
                - agent_id: str - The ID of the destroyed agent

        Raises:
            InvalidParamsError: If agent_id is missing, invalid, or requester
                               is not authorized to destroy the agent.
        """
        agent_id = params.get("agent_id")

        # Validate required parameter
        if agent_id is None:
            raise InvalidParamsError("Missing required parameter: agent_id")
        if not isinstance(agent_id, str):
            raise InvalidParamsError(
                f"agent_id must be string, got: {type(agent_id).__name__}"
            )

        # Destroy the agent through the pool (with authorization check)
        try:
            success = await self._pool.destroy(
                agent_id,
                requester_id=self._current_requester_id,
            )
        except AuthorizationError as e:
            raise InvalidParamsError(str(e)) from e

        if success:
            logger.info("Agent destroyed: %s (by %s)", agent_id, self._current_requester_id or "external")
        else:
            logger.warning("Agent destroy failed: %s not found", agent_id)

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
        logger.info("Server shutdown requested")
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


    async def _send_initial_background(self, agent: "Agent", send_request: "Request", request_id: str) -> None:
        """Fire-and-forget initial message dispatch."""
        try:
            await agent.dispatcher.dispatch(send_request)
            logger.info(f"Background initial_message completed for {agent.agent_id}")
        except Exception as e:
            logger.error(f"Background initial_message FAILED for {agent.agent_id}/{request_id}: {e}")
