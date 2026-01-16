"""Object graph bootstrap for NEXUS3 server components.

This module provides a single entry point for creating and wiring the core
server components. It handles the circular dependency between AgentPool and
GlobalDispatcher through explicit phased initialization.

Usage:
    pool, global_dispatcher, shared = await bootstrap_server_components(
        config=config,
        base_log_dir=Path(".nexus3/logs"),
        log_streams=LogStream.CONTEXT | LogStream.VERBOSE,
        is_repl=True,
    )
"""

from __future__ import annotations

import logging
from pathlib import Path

from nexus3.config.schema import Config
from nexus3.context.loader import ContextLoader
from nexus3.core.permissions import load_custom_presets_from_config
from nexus3.provider import ProviderRegistry
from nexus3.rpc.global_dispatcher import GlobalDispatcher
from nexus3.rpc.pool import AgentPool, SharedComponents
from nexus3.session import LogStream

logger = logging.getLogger(__name__)


async def bootstrap_server_components(
    config: Config,
    base_log_dir: Path,
    log_streams: LogStream,
    is_repl: bool = False,
) -> tuple[AgentPool, GlobalDispatcher, SharedComponents]:
    """Bootstrap the complete server object graph.

    Handles the circular dependency between AgentPool and GlobalDispatcher
    through explicit phased initialization:

    1. Create provider registry (lazy provider instantiation)
    2. Load context from NEXUS.md files
    3. Load custom permission presets from config
    4. Create SharedComponents (immutable config bundle)
    5. Create AgentPool (without dispatcher initially)
    6. Create GlobalDispatcher (requires pool)
    7. Wire circular dependency (pool -> dispatcher)
    8. Validate wiring succeeded

    Args:
        config: Loaded NEXUS3 configuration.
        base_log_dir: Base directory for agent logs. Each agent gets a subdirectory.
        log_streams: Which log streams to enable (CONTEXT, VERBOSE, RAW).
        is_repl: Whether running in REPL mode. Affects context loading behavior
            (REPL mode may load different prompts than headless mode).

    Returns:
        Tuple of (pool, global_dispatcher, shared):
        - pool: AgentPool for creating/managing agents
        - global_dispatcher: GlobalDispatcher for agent lifecycle RPC methods
        - shared: SharedComponents for access to config, providers, etc.

    Raises:
        RuntimeError: If wiring the circular dependency fails.

    Example:
        config = load_config()
        pool, dispatcher, shared = await bootstrap_server_components(
            config=config,
            base_log_dir=Path(".nexus3/logs"),
            log_streams=LogStream.CONTEXT | LogStream.VERBOSE,
            is_repl=True,
        )

        # Create an agent
        agent = await pool.create(agent_id="worker-1")

        # Handle RPC requests
        response = await dispatcher.dispatch(request)
    """
    # Phase 1: Create provider registry (lazy-creates providers on first use)
    provider_registry = ProviderRegistry(config)

    # Phase 2: Load context (NEXUS.md files from global/ancestor/local dirs)
    context_loader = ContextLoader(context_config=config.context)
    base_context = context_loader.load(is_repl=is_repl)

    # Phase 3: Load custom permission presets from config
    custom_presets = load_custom_presets_from_config(
        {k: v.model_dump() for k, v in config.permissions.presets.items()}
    )

    # Phase 4: Create SharedComponents (immutable config bundle for all agents)
    shared = SharedComponents(
        config=config,
        provider_registry=provider_registry,
        base_log_dir=base_log_dir,
        base_context=base_context,
        context_loader=context_loader,
        log_streams=log_streams,
        custom_presets=custom_presets,
    )

    # Phase 5: Create AgentPool (without dispatcher initially)
    pool = AgentPool(shared)

    # Phase 6: Create GlobalDispatcher (requires pool for agent operations)
    global_dispatcher = GlobalDispatcher(pool)

    # Phase 7: Wire circular dependency (pool needs dispatcher for in-process AgentAPI)
    pool.set_global_dispatcher(global_dispatcher)

    # Phase 8: Validate wiring succeeded
    if pool._global_dispatcher is None:
        raise RuntimeError("Failed to wire GlobalDispatcher to AgentPool")

    logger.debug("Server components bootstrapped successfully")

    return pool, global_dispatcher, shared
