"""Multi-agent pool management for NEXUS3.

This module provides the AgentPool class for managing multiple agent instances,
each with their own context, skills, and logging. This enables multi-agent
scenarios where a coordinator can spawn and control multiple agents.

Architecture:
    - SharedComponents: Immutable config shared across all agents
    - AgentConfig: Per-agent creation options
    - Agent: A single agent instance with all its components
    - AgentPool: Manager for creating, destroying, and accessing agents

Example:
    from nexus3.rpc.pool import AgentPool, SharedComponents

    shared = SharedComponents(
        config=config,
        provider_registry=provider_registry,
        base_log_dir=Path(".nexus3/logs"),
        base_context=base_context,
        context_loader=context_loader,
    )
    pool = AgentPool(shared)

    # Create an agent
    agent = await pool.create(agent_id="worker-1")

    # Dispatch requests to it
    response = await agent.dispatcher.dispatch(request)

    # Clean up
    await pool.destroy("worker-1")
"""

from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from nexus3.clipboard import CLIPBOARD_PRESETS, ClipboardManager
from nexus3.context import ContextConfig, ContextLoader, ContextManager, LoadedContext
from nexus3.core.permissions import (
    AgentPermissions,
    PermissionDelta,
    PermissionLevel,
    PermissionPreset,
    ToolPermission,
    resolve_preset,
)
from nexus3.mcp.registry import MCPServerRegistry
from nexus3.rpc.dispatcher import Dispatcher
from nexus3.rpc.log_multiplexer import LogMultiplexer
from nexus3.session import LogConfig, LogStream, Session, SessionLogger
from nexus3.session.persistence import (
    SavedSession,
    deserialize_clipboard_entries,
    deserialize_messages,
)
from nexus3.skill import ServiceContainer, SkillRegistry
from nexus3.skill.vcs import register_vcs_skills
from nexus3.skill.vcs.config import GitLabConfig as VCSGitLabConfig
from nexus3.skill.vcs.config import GitLabInstance

if TYPE_CHECKING:
    from nexus3.config.schema import Config
    from nexus3.provider.registry import ProviderRegistry
    from nexus3.rpc.global_dispatcher import GlobalDispatcher
    from nexus3.session.session_manager import SessionManager


# Maximum nesting depth for agent creation
# 0 = root, 1 = child, 2 = grandchild, etc.
MAX_AGENT_DEPTH = 5


def _convert_gitlab_config(config: Config) -> VCSGitLabConfig | None:
    """Convert schema GitLabConfig to VCS GitLabConfig.

    Returns None if no GitLab instances are configured or if gitlab
    is not properly configured (e.g., mock in tests).
    """
    try:
        schema_config = config.gitlab
        # Guard against mocks or missing instances attribute
        if not hasattr(schema_config, "instances") or not isinstance(schema_config.instances, dict):
            return None
        if not schema_config.instances:
            return None

        # Convert each instance
        instances: dict[str, GitLabInstance] = {}
        for name, inst in schema_config.instances.items():
            instances[name] = GitLabInstance(
                url=inst.url,
                token=inst.token,
                token_env=inst.token_env,
                username=inst.username,
                email=inst.email,
                user_id=inst.user_id,
            )

        return VCSGitLabConfig(
            instances=instances,
            default_instance=schema_config.default_instance,
        )
    except (AttributeError, TypeError, ValueError):
        # Handle any conversion errors gracefully (e.g., mocked config in tests)
        return None


class AuthorizationError(Exception):
    """Raised when an operation is not authorized.

    Used for pool-level authorization checks, such as verifying that
    an agent has permission to destroy another agent.
    """

    pass


# === Agent Naming Helpers ===


# Path traversal patterns to reject in agent IDs (security)
_FORBIDDEN_AGENT_ID_PATTERNS: frozenset[str] = frozenset({
    "/",      # Unix path separator
    "\\",     # Windows path separator
    "..",     # Parent directory traversal
    "%2f",    # URL-encoded /
    "%2F",    # URL-encoded / (uppercase)
    "%5c",    # URL-encoded \
    "%5C",    # URL-encoded \ (uppercase)
})

# Maximum allowed agent ID length
_MAX_AGENT_ID_LENGTH = 128


def validate_agent_id(agent_id: str) -> None:
    """Validate agent ID for security (path traversal prevention).

    Rejects agent IDs that could be used for path traversal attacks when
    used to create log directories (base_log_dir / agent_id).

    Valid examples: "worker-1", ".temp", "a1b2c3d4", "my-agent_v2"
    Invalid examples: "../etc", "/root", "foo/bar", "%2f..%2f"

    Args:
        agent_id: The agent identifier to validate.

    Raises:
        ValueError: If the agent_id is empty, too long, or contains
            path traversal patterns.
    """
    # Empty or too long
    if not agent_id:
        raise ValueError("Agent ID cannot be empty")
    if len(agent_id) > _MAX_AGENT_ID_LENGTH:
        raise ValueError(
            f"Agent ID too long: {len(agent_id)} chars "
            f"(max {_MAX_AGENT_ID_LENGTH})"
        )

    # Check for forbidden patterns (case-insensitive for encoded variants)
    agent_id_lower = agent_id.lower()
    for pattern in _FORBIDDEN_AGENT_ID_PATTERNS:
        if pattern in agent_id or pattern in agent_id_lower:
            raise ValueError(
                f"Invalid agent ID '{agent_id}': contains forbidden pattern '{pattern}'"
            )

    # Reject absolute paths and explicit relative traversal
    if agent_id.startswith(("/", "\\", "./")):
        raise ValueError(
            f"Invalid agent ID '{agent_id}': looks like a path"
        )


def is_temp_agent(agent_id: str) -> bool:
    """Return True if agent_id starts with '.' (temp/drone).

    Temp agents:
    - Don't appear in "saved sessions" list
    - Use format like .1, .2, .quick-test
    - Can be promoted to named via /save command

    Named agents:
    - Appear in saved sessions list
    - Use alphanumeric format like worker-1, my-project
    - Restorable after shutdown

    Args:
        agent_id: The agent identifier to check.

    Returns:
        True if the agent_id indicates a temp agent, False otherwise.
    """
    return agent_id.startswith(".")


def generate_temp_id(existing_ids: set[str]) -> str:
    """Generate next temp agent ID like .1, .2, etc.

    Finds the lowest available numeric temp ID that is not
    already in use.

    Args:
        existing_ids: Set of agent IDs already in use.

    Returns:
        A temp agent ID string like ".1", ".2", etc.
    """
    i = 1
    while f".{i}" in existing_ids:
        i += 1
    return f".{i}"


@dataclass(frozen=True)
class SharedComponents:
    """Components shared across all agents in a pool.

    These are immutable resources that all agents can reference but not modify.
    Each agent gets its own copies of mutable state (context, logger, etc.)
    but shares expensive/singleton resources like the provider registry.

    Attributes:
        config: The global NEXUS3 configuration.
        provider_registry: Registry for managing multiple LLM providers.
        base_log_dir: Base directory for agent logs. Each agent gets a subdirectory.
        base_context: The loaded context from server startup (for subagent inheritance).
        context_loader: Loader for reloading context during compaction.
        log_streams: Log streams to enable (defaults to ALL for backwards compatibility).
        custom_presets: Custom permission presets loaded from config.
        mcp_registry: MCP server registry for external tool integration.
        is_repl: Whether running in REPL mode (affects context loading during compaction).
    """

    config: Config
    provider_registry: ProviderRegistry
    base_log_dir: Path
    base_context: LoadedContext
    context_loader: ContextLoader
    log_streams: LogStream = LogStream.ALL
    custom_presets: dict[str, PermissionPreset] = field(default_factory=dict)
    mcp_registry: MCPServerRegistry = field(default_factory=MCPServerRegistry)
    is_repl: bool = False


@dataclass
class AgentConfig:
    """Configuration options for creating a new agent.

    Allows customization of agent behavior at creation time.
    All fields are optional - defaults are used if not specified.

    Attributes:
        agent_id: Unique identifier for the agent. Auto-generated if None.
        system_prompt: Override the default system prompt. If None, uses
            the base_context.system_prompt from SharedComponents.
        preset: Permission preset name (e.g., "yolo", "trusted", "sandboxed").
            If None, uses default_preset from config.
        cwd: Working directory / sandbox root. For SANDBOXED preset, this is
            the only path the agent can access. Must be within parent's allowed
            paths if parent_permissions is set.
        delta: Permission delta to apply to the base preset.
        parent_permissions: Parent agent's permissions for ceiling enforcement.
            Used when an agent spawns a subagent.
        parent_agent_id: ID of the parent agent that created this agent.
            Used for tracking agent lineage in permission inheritance.
        model: Model name/alias to use. If None, uses provider default.
            Can be an alias defined in config.models or a full model ID.
    """

    agent_id: str | None = None
    system_prompt: str | None = None
    preset: str | None = None
    cwd: Path | None = None
    delta: PermissionDelta | None = None
    parent_permissions: AgentPermissions | None = None
    parent_agent_id: str | None = None
    model: str | None = None


@dataclass
class Agent:
    """A single agent instance with all its components.

    Each agent has its own isolated state:
    - ContextManager with conversation history
    - SessionLogger with its own log directory
    - SkillRegistry with access to shared services
    - Session for LLM interactions
    - Dispatcher for JSON-RPC request handling

    The agent shares the provider (for connection pooling) but has
    independent state for everything else.

    Attributes:
        agent_id: Unique identifier for this agent.
        logger: Session logger writing to agent's log directory.
        context: Context manager with agent's conversation history.
        services: Service container for dependency injection.
        registry: Skill registry with registered tools.
        session: Session coordinator for LLM interactions.
        dispatcher: JSON-RPC dispatcher for handling requests.
        created_at: Timestamp when the agent was created.
    """

    agent_id: str
    logger: SessionLogger
    context: ContextManager
    services: ServiceContainer
    registry: SkillRegistry
    session: Session
    dispatcher: Dispatcher
    created_at: datetime = field(default_factory=datetime.now)
    repl_connected: bool = False


class AgentPool:
    """Manages multiple agent instances.

    The AgentPool handles agent lifecycle:
    - Creating agents with proper initialization
    - Destroying agents and cleaning up resources
    - Looking up agents by ID
    - Tracking shutdown state across all agents

    Thread-safe: Uses asyncio.Lock for agent creation/destruction.

    Example:
        pool = AgentPool(shared_components)

        # Create agents
        agent1 = await pool.create()  # Auto-generated ID
        agent2 = await pool.create(agent_id="worker-2")

        # Access agents
        agent = pool.get("worker-2")
        if agent:
            response = await agent.dispatcher.dispatch(request)

        # List all agents
        for info in pool.list():
            print(f"{info['agent_id']}: {info['message_count']} messages")

        # Clean up
        await pool.destroy("worker-2")

    Attributes:
        _shared: Shared components available to all agents.
        _agents: Dictionary mapping agent_id to Agent instance.
        _lock: Asyncio lock for thread-safe operations.
    """

    def __init__(self, shared: SharedComponents) -> None:
        """Initialize the agent pool.

        Args:
            shared: Shared components available to all agents.
        """
        self._shared = shared
        self._agents: dict[str, Agent] = {}
        self._lock = asyncio.Lock()

        # Create log multiplexer for multi-agent raw log routing
        # This routes raw API logs to the correct agent based on async context
        self._log_multiplexer = LogMultiplexer()

        # Set the multiplexer on the provider registry
        # This will be applied to all providers as they are created
        self._shared.provider_registry.set_raw_log_callback(self._log_multiplexer)

        # Global dispatcher reference for in-process AgentAPI
        # Set via set_global_dispatcher() after GlobalDispatcher is created
        self._global_dispatcher: GlobalDispatcher | None = None

    def set_global_dispatcher(self, dispatcher: GlobalDispatcher) -> None:
        """Set the global dispatcher for in-process AgentAPI.

        This enables skills to use DirectAgentAPI instead of HTTP for
        same-process agent communication. Must be called after creating
        the GlobalDispatcher.

        Args:
            dispatcher: The GlobalDispatcher instance.
        """
        self._global_dispatcher = dispatcher

    @property
    def log_multiplexer(self) -> LogMultiplexer:
        """Get the log multiplexer for setting agent context in dispatchers."""
        return self._log_multiplexer

    @property
    def system_prompt_path(self) -> str | None:
        """Get the system prompt path from the loaded context.

        Returns the most specific prompt source path (local > ancestor > global).
        Returns None if no sources are set.
        """
        sources = self._shared.base_context.sources.prompt_sources
        if not sources:
            return None
        # Return the last (most specific) source path
        return str(sources[-1].path)

    async def create(
        self,
        agent_id: str | None = None,
        config: AgentConfig | None = None,
    ) -> Agent:
        """Create a new agent instance.

        The agent is initialized with:
        - Its own log directory under base_log_dir/agent_id
        - Its own context manager with fresh conversation history
        - Its own skill registry (with access to shared services)
        - A session connected to the shared provider
        - A dispatcher for handling JSON-RPC requests

        Args:
            agent_id: Unique identifier for the agent. If None, generates
                a random 8-character hex ID (uuid4().hex[:8]).
            config: Additional configuration options. Overrides agent_id
                if both are provided.

        Returns:
            The newly created Agent instance.

        Raises:
            ValueError: If an agent with the given ID already exists.
        """
        async with self._lock:
            return await self._create_unlocked(agent_id=agent_id, config=config)

    async def _create_unlocked(
        self,
        agent_id: str | None = None,
        config: AgentConfig | None = None,
    ) -> Agent:
        """Internal agent creation - caller MUST hold self._lock.

        This is the actual agent creation logic, factored out to allow
        create_temp() to hold the lock while generating the temp ID AND
        creating the agent (P1.9 race condition fix).
        """
        # Resolve agent_id from config or parameter
        effective_config = config or AgentConfig()
        effective_id = effective_config.agent_id or agent_id or uuid4().hex[:8]

        # Validate agent ID for path traversal attacks (P0.5 security fix)
        validate_agent_id(effective_id)

        # Check for duplicate
        if effective_id in self._agents:
            raise ValueError(f"Agent already exists: {effective_id}")

        # Create agent log directory
        agent_log_dir = self._shared.base_log_dir / effective_id

        # Create session logger
        log_config = LogConfig(
            base_dir=agent_log_dir,
            streams=self._shared.log_streams,
            mode="agent",
        )
        logger = SessionLogger(log_config)

        # Register raw logging callback with the multiplexer
        # The multiplexer routes logs to correct agent based on async context
        raw_callback = logger.get_raw_log_callback()
        if raw_callback is not None:
            self._log_multiplexer.register(effective_id, raw_callback)

        # Determine system prompt
        if effective_config.system_prompt is not None:
            system_prompt = effective_config.system_prompt
        elif effective_config.cwd is not None:
            # Subagent with custom cwd - use ContextLoader for per-directory context
            context_loader = ContextLoader(
                cwd=effective_config.cwd,
                context_config=self._shared.config.context,
            )
            system_prompt = context_loader.load_for_subagent(
                parent_context=self._shared.base_context,
            )
        else:
            # Use the base context system prompt (default server context)
            system_prompt = self._shared.base_context.system_prompt

        # Resolve model name/alias to full settings
        resolved_model = self._shared.config.resolve_model(effective_config.model)

        # Create skill registry with services
        # Import here to avoid circular import (skills -> client -> rpc -> pool)
        from nexus3.skill.builtin import register_builtin_skills

        services = ServiceContainer()

        # Resolve permissions from preset (using custom presets from config if available)
        preset_name = effective_config.preset or self._shared.config.permissions.default_preset
        try:
            permissions = resolve_preset(
                preset_name,
                self._shared.custom_presets,
                cwd=effective_config.cwd,
            )
        except ValueError:
            # Fall back to sandboxed if preset not found
            permissions = resolve_preset(
                "sandboxed",
                self._shared.custom_presets,
                cwd=effective_config.cwd,
            )

        # SECURITY: Check ceiling BEFORE applying delta
        # This ensures the base preset is allowed, then we check the delta result
        if effective_config.parent_permissions is not None:
            # Check recursion depth limit
            if effective_config.parent_permissions.depth >= MAX_AGENT_DEPTH:
                raise PermissionError(
                    f"Cannot create agent: max nesting depth ({MAX_AGENT_DEPTH}) exceeded"
                )
            # First check: base preset must be allowed
            if not effective_config.parent_permissions.can_grant(permissions):
                raise PermissionError(
                    f"Requested preset '{preset_name}' exceeds parent ceiling"
                )

        # Apply delta if provided
        if effective_config.delta:
            permissions = permissions.apply_delta(effective_config.delta)
            # Second check: delta result must also be allowed
            if effective_config.parent_permissions is not None:
                if not effective_config.parent_permissions.can_grant(permissions):
                    raise PermissionError(
                        "Permission delta would exceed parent ceiling"
                    )

        # Set ceiling reference and depth after all checks pass
        # SECURITY FIX: Use deepcopy to prevent shared references
        # If parent permissions are mutated later, child's ceiling shouldn't change
        if effective_config.parent_permissions is not None:
            permissions.ceiling = copy.deepcopy(effective_config.parent_permissions)
            # SECURITY FIX: Store actual parent agent ID, not preset name
            permissions.parent_agent_id = effective_config.parent_agent_id
            permissions.depth = effective_config.parent_permissions.depth + 1

        # Register agent_id, permissions, allowed_paths, model, cwd, and MCP registry
        services.register("agent_id", effective_id)
        services.register("permissions", permissions)
        services.register("allowed_paths", permissions.effective_policy.allowed_paths)
        services.register("model", resolved_model)  # ResolvedModel for model hotswapping
        services.register("mcp_registry", self._shared.mcp_registry)
        # Per-agent cwd for isolation (avoids global os.chdir)
        agent_cwd = effective_config.cwd or Path.cwd()
        services.register("cwd", agent_cwd)

        # Create ClipboardManager based on permission level
        permission_level = permissions.effective_policy.level
        if permission_level == PermissionLevel.YOLO:
            clipboard_perms = CLIPBOARD_PRESETS["yolo"]
        elif permission_level == PermissionLevel.TRUSTED:
            clipboard_perms = CLIPBOARD_PRESETS["trusted"]
        else:  # SANDBOXED or unknown - fail safe
            clipboard_perms = CLIPBOARD_PRESETS["sandboxed"]

        clipboard_manager = ClipboardManager(
            agent_id=effective_id,
            cwd=agent_cwd,
            permissions=clipboard_perms,
        )
        services.register("clipboard_manager", clipboard_manager)

        # Create context manager with model's context window
        context_config = ContextConfig(
            max_tokens=resolved_model.context_window,
        )
        context = ContextManager(
            config=context_config,
            logger=logger,
            agent_id=effective_id,
            clipboard_manager=clipboard_manager,
            clipboard_config=self._shared.config.clipboard,
        )
        context.set_system_prompt(system_prompt)

        # Add session start message with agent metadata
        write_paths: list[str] | None = None
        write_file_perm = permissions.tool_permissions.get("write_file")
        if write_file_perm and write_file_perm.allowed_paths is not None:
            write_paths = [str(p) for p in write_file_perm.allowed_paths]
        context.add_session_start_message(
            agent_id=effective_id,
            preset=preset_name,
            cwd=str(agent_cwd),
            write_paths=write_paths,
        )

        # Initialize git repository context
        context.refresh_git_context(agent_cwd)

        # Register GitLab config for VCS skills
        gitlab_config = _convert_gitlab_config(self._shared.config)
        if gitlab_config:
            services.register("gitlab_config", gitlab_config)

        # Register AgentAPI for in-process communication (bypasses HTTP)
        # Pass effective_id as requester_id for authorization checks (H5 fix)
        if self._global_dispatcher is not None:
            from nexus3.rpc.agent_api import DirectAgentAPI
            agent_api = DirectAgentAPI(self, self._global_dispatcher, requester_id=effective_id)
            services.register("agent_api", agent_api)

        registry = SkillRegistry(services)
        register_builtin_skills(registry)

        # Register VCS skills (GitLab, GitHub) if configured
        register_vcs_skills(registry, services, permissions)

        # Default gitlab skills to disabled (user enables via /gitlab on)
        # Guard: skip tools already in tool_permissions (e.g. restored sessions)
        for skill_name in list(registry._specs):
            if skill_name.startswith("gitlab_") and skill_name not in permissions.tool_permissions:
                permissions.tool_permissions[skill_name] = ToolPermission(enabled=False)

        # SECURITY FIX: Inject only enabled tool definitions into context
        # Disabled tools should not be visible to the LLM at all
        tool_defs = registry.get_definitions_for_permissions(permissions)

        # Add MCP tools if agent has MCP permission (TRUSTED/YOLO only)
        # Only include tools from MCP servers visible to this agent
        from nexus3.mcp.permissions import can_use_mcp
        if can_use_mcp(permissions):
            for mcp_skill in await self._shared.mcp_registry.get_all_skills(agent_id=effective_id):
                # Check if MCP tool is disabled in permissions
                tool_perm = permissions.tool_permissions.get(mcp_skill.name)
                if tool_perm is not None and not tool_perm.enabled:
                    continue
                tool_defs.append({
                    "type": "function",
                    "function": {
                        "name": mcp_skill.name,
                        "description": mcp_skill.description,
                        "parameters": mcp_skill.parameters,
                    },
                })

        context.set_tool_definitions(tool_defs)

        # Get the provider for this model from the registry
        provider = self._shared.provider_registry.get(
            resolved_model.provider_name,
            resolved_model.model_id,
            resolved_model.reasoning,
        )

        # Create session with context and services for permission enforcement
        session = Session(
            provider,
            context=context,
            logger=logger,
            registry=registry,
            skill_timeout=self._shared.config.skill_timeout,
            max_tool_iterations=self._shared.config.max_tool_iterations,
            max_concurrent_tools=self._shared.config.max_concurrent_tools,
            services=services,
            config=self._shared.config,
            context_loader=self._shared.context_loader,
            is_repl=self._shared.is_repl,
        )

        # Create dispatcher with context for token info and log multiplexer
        dispatcher = Dispatcher(
            session,
            context=context,
            agent_id=effective_id,
            log_multiplexer=self._log_multiplexer,
            pool=self,
        )

        # Create agent instance
        agent = Agent(
            agent_id=effective_id,
            logger=logger,
            context=context,
            services=services,
            registry=registry,
            session=session,
            dispatcher=dispatcher,
        )

        # Store in pool
        self._agents[effective_id] = agent

        # Track child in parent agent's services (for permission-free destroy)
        if effective_config.parent_agent_id is not None:
            parent = self._agents.get(effective_config.parent_agent_id)
            if parent:
                child_ids: set[str] = parent.services.get("child_agent_ids") or set()
                child_ids.add(effective_id)
                parent.services.register("child_agent_ids", child_ids)

        return agent

    async def create_temp(self, config: AgentConfig | None = None) -> Agent:
        """Create a new temp agent with auto-generated ID.

        Temp agents use IDs starting with '.' (e.g., .1, .2, .3).
        This method finds the next available numeric temp ID and creates
        an agent with that ID.

        Temp agents:
        - Don't appear in "saved sessions" list
        - Can be promoted to named via /save command
        - Are useful for one-off tasks and quick experiments

        Args:
            config: Additional configuration options. The agent_id field
                is ignored (auto-generated).

        Returns:
            The newly created Agent instance with a temp ID.

        Example:
            agent = await pool.create_temp()
            print(agent.agent_id)  # ".1"

            agent2 = await pool.create_temp()
            print(agent2.agent_id)  # ".2"
        """
        # P1.9 SECURITY FIX: Hold lock for entire operation to prevent race condition
        # Previously, lock was released between generate_temp_id() and create(), allowing
        # concurrent calls to generate the same ID before either stored it
        async with self._lock:
            temp_id = generate_temp_id(set(self._agents.keys()))

            # Create agent with the temp ID
            effective_config = config or AgentConfig()
            # Override any agent_id in config with the temp ID
            effective_config = AgentConfig(
                agent_id=temp_id,
                system_prompt=effective_config.system_prompt,
                preset=effective_config.preset,
                cwd=effective_config.cwd,
                model=effective_config.model,
                delta=effective_config.delta,
                parent_permissions=effective_config.parent_permissions,
                parent_agent_id=effective_config.parent_agent_id,
            )
            # Use _create_unlocked since we already hold the lock
            return await self._create_unlocked(config=effective_config)

    def is_temp(self, agent_id: str) -> bool:
        """Check if an agent ID represents a temp agent.

        This is a convenience method on the pool that delegates to
        the module-level is_temp_agent() function.

        Args:
            agent_id: The agent ID to check.

        Returns:
            True if the agent_id starts with '.', False otherwise.
        """
        return is_temp_agent(agent_id)

    async def get_or_restore(
        self,
        agent_id: str,
        session_manager: SessionManager | None = None,
    ) -> Agent | None:
        """Get agent, restoring from saved session if needed.

        This is atomic - concurrent calls for the same agent_id are safe.
        The lock is held throughout the check-and-restore operation to prevent
        TOCTOU race conditions where multiple requests could try to restore
        the same saved session simultaneously.

        Args:
            agent_id: The ID of the agent to get or restore.
            session_manager: Optional session manager for loading saved sessions.
                           If None, only returns active agents.

        Returns:
            The Agent instance if found or restored, None if not found and
            cannot be restored.

        Example:
            # Safe for concurrent requests
            agent = await pool.get_or_restore("worker-1", session_manager)
            if agent:
                response = await agent.dispatcher.dispatch(request)
        """
        async with self._lock:
            # Check 1: Already active?
            if agent_id in self._agents:
                return self._agents[agent_id]

            # Check 2: Can restore?
            if session_manager is not None and session_manager.session_exists(agent_id):
                saved = session_manager.load_session(agent_id)
                return await self._restore_unlocked(saved)

            return None

    async def _restore_unlocked(self, saved: SavedSession) -> Agent:
        """Internal restore logic - caller MUST hold self._lock.

        This is the actual restoration logic, factored out to allow
        get_or_restore() to hold the lock while both checking for existing
        agents AND restoring from saved session (TOCTOU race condition fix).

        Args:
            saved: The SavedSession containing the agent's persisted state.

        Returns:
            The restored Agent instance with full conversation history.

        Raises:
            ValueError: If an agent with the saved session's ID already exists.
        """
        agent_id = saved.agent_id

        # Validate agent ID for path traversal attacks (P0.5 security fix)
        validate_agent_id(agent_id)

        # Check for duplicate (caller should have checked, but defense-in-depth)
        if agent_id in self._agents:
            raise ValueError(f"Agent already exists: {agent_id}")

        # Create agent log directory
        agent_log_dir = self._shared.base_log_dir / agent_id

        # Create session logger
        log_config = LogConfig(
            base_dir=agent_log_dir,
            streams=self._shared.log_streams,
            mode="agent",
        )
        logger = SessionLogger(log_config)

        # Register raw logging callback with the multiplexer
        raw_callback = logger.get_raw_log_callback()
        if raw_callback is not None:
            self._log_multiplexer.register(agent_id, raw_callback)

        # Use system prompt from saved session
        system_prompt = saved.system_prompt

        # Resolve model for context window
        resolved_model = self._shared.config.resolve_model(saved.model_alias)

        # Create skill registry with services
        from nexus3.skill.builtin import register_builtin_skills

        services = ServiceContainer()

        # Resolve permissions from saved session or fall back to default
        preset_name = (
            saved.permission_preset
            if saved.permission_preset
            else self._shared.config.permissions.default_preset
        )
        try:
            permissions = resolve_preset(preset_name, self._shared.custom_presets)
        except ValueError:
            # Fall back to sandboxed if preset not found
            permissions = resolve_preset("sandboxed", self._shared.custom_presets)

        # Apply disabled_tools from saved session
        if saved.disabled_tools:
            delta = PermissionDelta(disable_tools=saved.disabled_tools)
            permissions = permissions.apply_delta(delta)

        # Register agent_id, permissions, allowed_paths, cwd, model and MCP registry
        services.register("agent_id", agent_id)
        services.register("permissions", permissions)
        services.register("allowed_paths", permissions.effective_policy.allowed_paths)
        services.register("mcp_registry", self._shared.mcp_registry)
        services.register("model", resolved_model)  # ResolvedModel for /model command
        # Per-agent cwd for isolation (restored from saved session)
        agent_cwd = Path(saved.working_directory) if saved.working_directory else Path.cwd()
        services.register("cwd", agent_cwd)

        # Create ClipboardManager based on permission level
        permission_level = permissions.effective_policy.level
        if permission_level == PermissionLevel.YOLO:
            clipboard_perms = CLIPBOARD_PRESETS["yolo"]
        elif permission_level == PermissionLevel.TRUSTED:
            clipboard_perms = CLIPBOARD_PRESETS["trusted"]
        else:  # SANDBOXED or unknown - fail safe
            clipboard_perms = CLIPBOARD_PRESETS["sandboxed"]

        clipboard_manager = ClipboardManager(
            agent_id=agent_id,
            cwd=agent_cwd,
            permissions=clipboard_perms,
        )
        services.register("clipboard_manager", clipboard_manager)

        # Restore agent-scope clipboard entries if present
        if saved.clipboard_agent_entries:
            entries = deserialize_clipboard_entries(saved.clipboard_agent_entries)
            clipboard_manager.restore_agent_entries(entries)

        # Create context manager with saved model's context window
        context_config = ContextConfig(
            max_tokens=resolved_model.context_window,
        )
        context = ContextManager(
            config=context_config,
            logger=logger,
            agent_id=agent_id,
            clipboard_manager=clipboard_manager,
            clipboard_config=self._shared.config.clipboard,
        )
        context.set_system_prompt(system_prompt)

        # Restore conversation history from saved session
        messages = deserialize_messages(saved.messages)
        for msg in messages:
            context._messages.append(msg)

        # Refresh git repository context
        context.refresh_git_context(agent_cwd)

        # Register GitLab config for VCS skills
        gitlab_config = _convert_gitlab_config(self._shared.config)
        if gitlab_config:
            services.register("gitlab_config", gitlab_config)

        # Register AgentAPI for in-process communication (bypasses HTTP)
        # Pass agent_id as requester_id for authorization checks (H5 fix)
        if self._global_dispatcher is not None:
            from nexus3.rpc.agent_api import DirectAgentAPI
            agent_api = DirectAgentAPI(self, self._global_dispatcher, requester_id=agent_id)
            services.register("agent_api", agent_api)

        registry = SkillRegistry(services)
        register_builtin_skills(registry)

        # Register VCS skills (GitLab, GitHub) if configured
        register_vcs_skills(registry, services, permissions)

        # Default gitlab skills to disabled (user enables via /gitlab on)
        # Guard: skip tools already in tool_permissions (e.g. restored sessions)
        for skill_name in list(registry._specs):
            if skill_name.startswith("gitlab_") and skill_name not in permissions.tool_permissions:
                permissions.tool_permissions[skill_name] = ToolPermission(enabled=False)

        # SECURITY FIX: Inject only enabled tool definitions into context
        # Disabled tools should not be visible to the LLM at all
        tool_defs = registry.get_definitions_for_permissions(permissions)

        # Add MCP tools if agent has MCP permission (TRUSTED/YOLO only)
        # Only include tools from MCP servers visible to this agent
        from nexus3.mcp.permissions import can_use_mcp
        if can_use_mcp(permissions):
            for mcp_skill in await self._shared.mcp_registry.get_all_skills(agent_id=agent_id):
                # Check if MCP tool is disabled in permissions
                tool_perm = permissions.tool_permissions.get(mcp_skill.name)
                if tool_perm is not None and not tool_perm.enabled:
                    continue
                tool_defs.append({
                    "type": "function",
                    "function": {
                        "name": mcp_skill.name,
                        "description": mcp_skill.description,
                        "parameters": mcp_skill.parameters,
                    },
                })

        context.set_tool_definitions(tool_defs)

        # Get the provider from the registry for restored sessions
        # Model alias is now persisted in SavedSession and restored here
        provider = self._shared.provider_registry.get(
            resolved_model.provider_name,
            resolved_model.model_id,
            resolved_model.reasoning,
        )

        # Create session with context and services for permission enforcement
        session = Session(
            provider,
            context=context,
            logger=logger,
            registry=registry,
            skill_timeout=self._shared.config.skill_timeout,
            max_concurrent_tools=self._shared.config.max_concurrent_tools,
            services=services,
            config=self._shared.config,
            context_loader=self._shared.context_loader,
            is_repl=self._shared.is_repl,
        )

        # Create dispatcher with context for token info and log multiplexer
        dispatcher = Dispatcher(
            session,
            context=context,
            agent_id=agent_id,
            log_multiplexer=self._log_multiplexer,
            pool=self,
        )

        # Create agent instance with saved creation time if available
        agent = Agent(
            agent_id=agent_id,
            logger=logger,
            context=context,
            services=services,
            registry=registry,
            session=session,
            dispatcher=dispatcher,
            created_at=saved.created_at,
        )

        # Store in pool
        self._agents[agent_id] = agent

        return agent

    async def restore_from_saved(self, saved: SavedSession) -> Agent:
        """Restore an agent from a saved session.

        Creates a new agent with the saved session's state, including
        conversation history, system prompt, and other configuration.
        This is used for cross-session auto-restore when external requests
        target inactive saved sessions.

        Note: For atomic get-or-restore operations, prefer get_or_restore()
        which handles the TOCTOU race condition properly.

        Args:
            saved: The SavedSession containing the agent's persisted state.

        Returns:
            The restored Agent instance with full conversation history.

        Raises:
            ValueError: If an agent with the saved session's ID already exists.

        Example:
            saved = session_manager.load_session("archived-helper")
            agent = await pool.restore_from_saved(saved)
            # Agent now has its full conversation history restored
        """
        async with self._lock:
            return await self._restore_unlocked(saved)

    async def destroy(
        self,
        agent_id: str,
        requester_id: str | None = None,
        *,
        admin_override: bool = False,
    ) -> bool:
        """Destroy an agent and clean up its resources.

        This method:
        1. Checks authorization (unless admin_override)
        2. Removes the agent from the pool
        3. Cancels all in-progress requests
        4. Closes the agent's logger (flushes buffers, closes DB)
        5. Removes from parent's child tracking (if applicable)

        The agent's log directory is preserved for debugging/auditing.

        Authorization Rules:
        - Self-destruction is always allowed (agent destroys itself)
        - Parent can destroy its children
        - External clients (requester_id=None) are treated as admin
        - admin_override=True bypasses all checks (for shutdown, etc.)

        Args:
            agent_id: The ID of the agent to destroy.
            requester_id: ID of the requesting agent (None for external clients).
            admin_override: If True, skip authorization checks (for server shutdown).

        Returns:
            True if the agent was found and destroyed, False if not found.

        Raises:
            AuthorizationError: If requester is not authorized to destroy the agent.
        """
        async with self._lock:
            if agent_id not in self._agents:
                return False

            agent = self._agents[agent_id]

            # Authorization check (unless admin override or external client)
            if not admin_override and requester_id is not None:
                # Get the target agent's permissions to check parent_agent_id
                target_permissions: AgentPermissions | None = agent.services.get("permissions")

                # Self-destruction is allowed
                if requester_id == agent_id:
                    pass  # Allowed
                # Parent can destroy children
                elif (
                    target_permissions is not None
                    and target_permissions.parent_agent_id == requester_id
                ):
                    pass  # Allowed
                else:
                    raise AuthorizationError(
                        f"Agent '{requester_id}' is not authorized to destroy '{agent_id}'"
                    )

            # Remove from pool
            self._agents.pop(agent_id)

            # Remove from parent's child tracking
            permissions: AgentPermissions | None = agent.services.get("permissions")
            if permissions and permissions.parent_agent_id:
                parent = self._agents.get(permissions.parent_agent_id)
                if parent:
                    child_ids: set[str] | None = parent.services.get("child_agent_ids")
                    if child_ids and agent_id in child_ids:
                        child_ids.discard(agent_id)

            # Cancel all in-progress requests before cleanup
            await agent.dispatcher.cancel_all_requests()

            # Unregister from log multiplexer
            self._log_multiplexer.unregister(agent_id)

            # Clean up clipboard manager (closes DB connections)
            clipboard_manager: ClipboardManager | None = agent.services.get("clipboard_manager")
            if clipboard_manager:
                clipboard_manager.close()

            # Clean up logger (closes DB connection, flushes files)
            agent.logger.close()

            return True

    def get(self, agent_id: str) -> Agent | None:
        """Get an agent by ID.

        Args:
            agent_id: The ID of the agent to retrieve.

        Returns:
            The Agent instance, or None if no agent with that ID exists.
        """
        return self._agents.get(agent_id)

    def get_children(self, agent_id: str) -> list[str]:
        """Get IDs of all child agents of a given agent.

        Args:
            agent_id: The ID of the parent agent.

        Returns:
            List of child agent IDs (may be empty).
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            return []
        child_ids: set[str] | None = agent.services.get("child_agent_ids")
        return list(child_ids) if child_ids else []

    def list(self) -> list[dict[str, Any]]:
        """List all agents with basic info.

        Returns a lightweight summary of each agent without exposing
        the full Agent objects. Useful for status displays and
        agent selection.

        Returns:
            List of dicts with keys:
            - agent_id: The agent's unique identifier
            - is_temp: True if this is a temp agent (starts with '.')
            - created_at: ISO format timestamp of creation
            - message_count: Number of messages in context
            - should_shutdown: Whether the agent's dispatcher wants shutdown
            - parent_agent_id: ID of parent agent (None if root)
            - child_count: Number of active child agents
            - halted_at_iteration_limit: Whether agent hit max tool iterations
            - model: Model alias being used
            - last_action_at: ISO timestamp of last agent action (None if no actions yet)
            - permission_level: Permission level (YOLO, TRUSTED, SANDBOXED)
            - cwd: Working directory path
            - write_paths: List of allowed write paths (None = unrestricted)
        """
        from nexus3.config.schema import ResolvedModel

        result: list[dict[str, Any]] = []
        for agent in self._agents.values():
            permissions: AgentPermissions | None = agent.services.get("permissions")
            child_ids: set[str] | None = agent.services.get("child_agent_ids")
            resolved_model: ResolvedModel | None = agent.services.get("model")
            cwd: Path | None = agent.services.get("cwd")

            # Get write paths from permissions (check write_file tool permission)
            write_paths: list[str] | None = None
            if permissions:
                write_file_perm = permissions.tool_permissions.get("write_file")
                if write_file_perm and write_file_perm.allowed_paths is not None:
                    write_paths = [str(p) for p in write_file_perm.allowed_paths]

            result.append({
                "agent_id": agent.agent_id,
                "is_temp": is_temp_agent(agent.agent_id),
                "created_at": agent.created_at.isoformat(),
                "message_count": len(agent.context.messages),
                "should_shutdown": agent.dispatcher.should_shutdown,
                "parent_agent_id": permissions.parent_agent_id if permissions else None,
                "child_count": len(child_ids) if child_ids else 0,
                "halted_at_iteration_limit": agent.session.halted_at_iteration_limit,
                "model": resolved_model.alias if resolved_model else None,
                "last_action_at": (
                    agent.session.last_action_at.isoformat()
                    if agent.session.last_action_at
                    else None
                ),
                "permission_level": (
                    permissions.effective_policy.level.name if permissions else None
                ),
                "cwd": str(cwd) if cwd else None,
                "write_paths": write_paths,
            })
        return result

    def set_repl_connected(self, agent_id: str, connected: bool) -> None:
        """Set REPL connection state for an agent.

        Args:
            agent_id: The agent to update.
            connected: True if REPL is connected, False otherwise.
        """
        agent = self._agents.get(agent_id)
        if agent:
            agent.repl_connected = connected

    def is_repl_connected(self, agent_id: str) -> bool:
        """Check if REPL is connected to an agent.

        Args:
            agent_id: The agent to check.

        Returns:
            True if REPL is connected, False otherwise.
        """
        agent = self._agents.get(agent_id)
        return agent.repl_connected if agent else False

    @property
    def should_shutdown(self) -> bool:
        """Check if all agents want shutdown.

        Returns True if ALL agents in the pool have their dispatcher's
        should_shutdown flag set. This indicates a coordinated shutdown
        where all agents have completed or been explicitly shut down.

        Returns:
            True if all agents want shutdown (or pool is empty), False otherwise.
        """
        if not self._agents:
            return False  # Empty pool doesn't trigger shutdown

        return all(agent.dispatcher.should_shutdown for agent in self._agents.values())

    def __len__(self) -> int:
        """Return the number of agents in the pool."""
        return len(self._agents)

    def __contains__(self, agent_id: str) -> bool:
        """Check if an agent ID exists in the pool."""
        return agent_id in self._agents
