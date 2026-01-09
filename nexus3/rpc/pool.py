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
from nexus3.rpc.dispatcher import Dispatcher
from nexus3.session import LogConfig, LogStream, Session, SessionLogger
from nexus3.skill import ServiceContainer, SkillRegistry

if TYPE_CHECKING:
    from nexus3.config.schema import Config
    from nexus3.context.prompt_loader import PromptLoader
    from nexus3.core.interfaces import AsyncProvider


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
    """

    config: Config
    provider: AsyncProvider
    prompt_loader: PromptLoader
    base_log_dir: Path


@dataclass
class AgentConfig:
    """Configuration options for creating a new agent.

    Allows customization of agent behavior at creation time.
    All fields are optional - defaults are used if not specified.

    Attributes:
        agent_id: Unique identifier for the agent. Auto-generated if None.
        system_prompt: Override the default system prompt. If None, uses
            the prompt_loader to load personal + project prompts.

    Future extensions:
        - permission_level: YOLO | TRUSTED | SANDBOXED
        - working_dir: Restrict file operations to this directory
        - max_tokens: Override context window size
        - tools: Override available tools
    """

    agent_id: str | None = None
    system_prompt: str | None = None


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
                streams=LogStream.ALL,
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

    async def destroy(self, agent_id: str) -> bool:
        """Destroy an agent and clean up its resources.

        This method:
        1. Removes the agent from the pool
        2. Closes the agent's logger (flushes buffers, closes DB)

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
            - created_at: ISO format timestamp of creation
            - message_count: Number of messages in context
            - should_shutdown: Whether the agent's dispatcher wants shutdown
        """
        result: list[dict[str, Any]] = []
        for agent in self._agents.values():
            result.append({
                "agent_id": agent.agent_id,
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
