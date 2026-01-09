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
        provider=provider,
        prompt_loader=prompt_loader,
        base_log_dir=Path(".nexus3/logs"),
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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from nexus3.context import ContextConfig, ContextManager
from nexus3.core.permissions import (
    AgentPermissions,
    PermissionDelta,
    resolve_preset,
)
from nexus3.rpc.dispatcher import Dispatcher
from nexus3.session import LogConfig, LogStream, Session, SessionLogger
from nexus3.session.persistence import SavedSession, deserialize_messages
from nexus3.skill import ServiceContainer, SkillRegistry

if TYPE_CHECKING:
    from nexus3.config.schema import Config
    from nexus3.context.prompt_loader import PromptLoader
    from nexus3.core.interfaces import AsyncProvider


# === Agent Naming Helpers ===


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
    but shares expensive/singleton resources like the provider.

    Attributes:
        config: The global NEXUS3 configuration.
        provider: The LLM provider (shared for connection pooling).
        prompt_loader: Loader for system prompts (personal + project).
        base_log_dir: Base directory for agent logs. Each agent gets a subdirectory.
        log_streams: Log streams to enable (defaults to ALL for backwards compatibility).
    """

    config: Config
    provider: AsyncProvider
    prompt_loader: PromptLoader
    base_log_dir: Path
    log_streams: LogStream = LogStream.ALL


@dataclass
class AgentConfig:
    """Configuration options for creating a new agent.

    Allows customization of agent behavior at creation time.
    All fields are optional - defaults are used if not specified.

    Attributes:
        agent_id: Unique identifier for the agent. Auto-generated if None.
        system_prompt: Override the default system prompt. If None, uses
            the prompt_loader to load personal + project prompts.
        preset: Permission preset name (e.g., "yolo", "trusted", "sandboxed").
            If None, uses default_preset from config.
        delta: Permission delta to apply to the base preset.
        parent_permissions: Parent agent's permissions for ceiling enforcement.
            Used when an agent spawns a subagent.

    Future extensions:
        - working_dir: Restrict file operations to this directory
        - max_tokens: Override context window size
        - tools: Override available tools
    """

    agent_id: str | None = None
    system_prompt: str | None = None
    preset: str | None = None
    delta: PermissionDelta | None = None
    parent_permissions: AgentPermissions | None = None


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
            # Resolve agent_id from config or parameter
            effective_config = config or AgentConfig()
            effective_id = effective_config.agent_id or agent_id or uuid4().hex[:8]

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

            # Wire up raw logging callback to provider if supported
            # Note: AsyncProvider protocol doesn't require set_raw_log_callback,
            # but concrete implementations like OpenRouterProvider support it.
            raw_callback = logger.get_raw_log_callback()
            if raw_callback is not None:
                provider = self._shared.provider
                if hasattr(provider, "set_raw_log_callback"):
                    provider.set_raw_log_callback(raw_callback)

            # Determine system prompt
            if effective_config.system_prompt is not None:
                system_prompt = effective_config.system_prompt
            else:
                # Load from prompt_loader
                loaded_prompt = self._shared.prompt_loader.load(is_repl=False)
                system_prompt = loaded_prompt.content

            # Create context manager
            context = ContextManager(
                config=ContextConfig(),
                logger=logger,
            )
            context.set_system_prompt(system_prompt)

            # Create skill registry with services
            # Import here to avoid circular import (skills -> client -> rpc -> pool)
            from nexus3.skill.builtin import register_builtin_skills

            services = ServiceContainer()

            # Resolve permissions from preset
            preset_name = effective_config.preset or self._shared.config.permissions.default_preset
            try:
                permissions = resolve_preset(preset_name)
            except ValueError:
                # Fall back to trusted if preset not found
                permissions = resolve_preset("trusted")

            # Apply delta if provided
            if effective_config.delta:
                permissions = permissions.apply_delta(effective_config.delta)

            # Enforce ceiling if spawned by another agent
            if effective_config.parent_permissions is not None:
                if not effective_config.parent_permissions.can_grant(permissions):
                    raise PermissionError(
                        f"Requested permissions '{preset_name}' exceed parent ceiling"
                    )
                permissions.ceiling = effective_config.parent_permissions
                permissions.parent_agent_id = effective_config.parent_permissions.base_preset

            # Register permissions and allowed_paths
            services.register("permissions", permissions)
            services.register("allowed_paths", permissions.effective_policy.allowed_paths)

            registry = SkillRegistry(services)
            register_builtin_skills(registry)

            # Inject tool definitions into context
            context.set_tool_definitions(registry.get_definitions())

            # Create session with context
            session = Session(
                self._shared.provider,
                context=context,
                logger=logger,
                registry=registry,
                skill_timeout=self._shared.config.skill_timeout,
                max_concurrent_tools=self._shared.config.max_concurrent_tools,
            )

            # Create dispatcher with context for token info
            dispatcher = Dispatcher(session, context=context)

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
        # Generate temp ID (needs lock to avoid race)
        async with self._lock:
            temp_id = generate_temp_id(set(self._agents.keys()))

        # Create agent with the temp ID
        effective_config = config or AgentConfig()
        # Override any agent_id in config with the temp ID
        effective_config = AgentConfig(
            agent_id=temp_id,
            system_prompt=effective_config.system_prompt,
            preset=effective_config.preset,
            delta=effective_config.delta,
            parent_permissions=effective_config.parent_permissions,
        )
        return await self.create(config=effective_config)

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

    async def restore_from_saved(self, saved: SavedSession) -> Agent:
        """Restore an agent from a saved session.

        Creates a new agent with the saved session's state, including
        conversation history, system prompt, and other configuration.
        This is used for cross-session auto-restore when external requests
        target inactive saved sessions.

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
            agent_id = saved.agent_id

            # Check for duplicate
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

            # Wire up raw logging callback to provider if supported
            raw_callback = logger.get_raw_log_callback()
            if raw_callback is not None:
                provider = self._shared.provider
                if hasattr(provider, "set_raw_log_callback"):
                    provider.set_raw_log_callback(raw_callback)

            # Use system prompt from saved session
            system_prompt = saved.system_prompt

            # Create context manager
            context = ContextManager(
                config=ContextConfig(),
                logger=logger,
            )
            context.set_system_prompt(system_prompt)

            # Restore conversation history from saved session
            messages = deserialize_messages(saved.messages)
            for msg in messages:
                context._messages.append(msg)

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
                permissions = resolve_preset(preset_name)
            except ValueError:
                # Fall back to trusted if preset not found
                permissions = resolve_preset("trusted")

            # Apply disabled_tools from saved session
            if saved.disabled_tools:
                delta = PermissionDelta(disable_tools=saved.disabled_tools)
                permissions = permissions.apply_delta(delta)

            # Register permissions and allowed_paths
            services.register("permissions", permissions)
            services.register("allowed_paths", permissions.effective_policy.allowed_paths)

            registry = SkillRegistry(services)
            register_builtin_skills(registry)

            # Inject tool definitions into context
            context.set_tool_definitions(registry.get_definitions())

            # Create session with context
            session = Session(
                self._shared.provider,
                context=context,
                logger=logger,
                registry=registry,
                skill_timeout=self._shared.config.skill_timeout,
                max_concurrent_tools=self._shared.config.max_concurrent_tools,
            )

            # Create dispatcher with context for token info
            dispatcher = Dispatcher(session, context=context)

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

    async def destroy(self, agent_id: str) -> bool:
        """Destroy an agent and clean up its resources.

        This method:
        1. Removes the agent from the pool
        2. Cancels all in-progress requests
        3. Closes the agent's logger (flushes buffers, closes DB)

        The agent's log directory is preserved for debugging/auditing.

        Args:
            agent_id: The ID of the agent to destroy.

        Returns:
            True if the agent was found and destroyed, False if not found.
        """
        async with self._lock:
            agent = self._agents.pop(agent_id, None)
            if agent is None:
                return False

            # Cancel all in-progress requests before cleanup
            await agent.dispatcher.cancel_all_requests()

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
        """
        result: list[dict[str, Any]] = []
        for agent in self._agents.values():
            result.append({
                "agent_id": agent.agent_id,
                "is_temp": is_temp_agent(agent.agent_id),
                "created_at": agent.created_at.isoformat(),
                "message_count": len(agent.context.messages),
                "should_shutdown": agent.dispatcher.should_shutdown,
            })
        return result

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
