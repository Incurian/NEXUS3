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
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from nexus3.core.secure_io import secure_mkdir

from nexus3.config.schema import Config
from nexus3.context.loader import ContextLoader
from nexus3.core.permissions import load_custom_presets_from_config
from nexus3.provider import ProviderRegistry
from nexus3.rpc.global_dispatcher import GlobalDispatcher
from nexus3.rpc.pool import AgentPool, SharedComponents
from nexus3.session import LogStream

logger = logging.getLogger(__name__)

# Dedicated logger for server lifecycle events (separate from main nexus3 logger)
# This allows REPL to add file logging without affecting console output
SERVER_LOGGER_NAME = "nexus3.server"


def configure_server_file_logging(
    log_dir: Path,
    level: int = logging.INFO,
) -> Path:
    """Configure file-based logging for server lifecycle events (non-destructive).

    Unlike configure_server_logging(), this function:
    - Does NOT clear existing handlers
    - Does NOT alter console logging
    - Only adds a file handler if one doesn't already exist

    This makes it safe to call from REPL mode without disrupting the CLI's
    existing logging setup.

    Logs are written to `{log_dir}/server.log` with automatic rotation
    (max 5MB per file, 3 backup files).

    Server lifecycle events (agent create/destroy, bind, shutdown) should use
    the nexus3.server logger to ensure they're captured in this file.

    Args:
        log_dir: Directory for server.log file. Created if doesn't exist.
        level: Logging level for file output (default INFO).

    Returns:
        Path to the server.log file.

    Example:
        log_file = configure_server_file_logging(Path(".nexus3/logs"))
        server_logger = logging.getLogger("nexus3.server")
        server_logger.info("Server started on port 8765")
    """
    # Ensure log directory exists with secure permissions
    secure_mkdir(log_dir)

    log_file = log_dir / "server.log"
    log_file_resolved = log_file.resolve()

    # Get or create the dedicated server logger
    server_logger = logging.getLogger(SERVER_LOGGER_NAME)
    server_logger.setLevel(level)

    # Check if we already have a file handler for this file
    # (prevents duplicate handlers if called multiple times)
    # Use resolved paths for comparison to handle relative vs absolute paths
    for handler in server_logger.handlers:
        if isinstance(handler, RotatingFileHandler):
            if hasattr(handler, 'baseFilename') and Path(handler.baseFilename).resolve() == log_file_resolved:
                # Already configured
                return log_file

    # Create rotating file handler
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    # Add handler (non-destructively)
    server_logger.addHandler(file_handler)

    # Propagate to parent (nexus3) so messages go to both console and file
    server_logger.propagate = True

    server_logger.info("Server logging configured: %s", log_file)
    return log_file


def configure_server_logging(
    log_dir: Path,
    level: int = logging.INFO,
    console_level: int = logging.WARNING,
) -> Path:
    """Configure file-based logging for server lifecycle events.

    Sets up a rotating file handler for the nexus3 namespace that captures:
    - Agent create/destroy operations
    - Client connections
    - Token operations
    - Errors and warnings

    Logs are written to `{log_dir}/server.log` with automatic rotation
    (max 5MB per file, 3 backup files).

    Args:
        log_dir: Directory for server.log file. Created if doesn't exist.
        level: Logging level for file output (default INFO).
        console_level: Logging level for console output (default WARNING).

    Returns:
        Path to the server.log file.

    Example:
        log_file = configure_server_logging(Path(".nexus3/logs"))
        # Now INFO+ logs from nexus3.* go to .nexus3/logs/server.log
    """
    # Ensure log directory exists with secure permissions
    secure_mkdir(log_dir)

    log_file = log_dir / "server.log"

    # Create rotating file handler
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    # Create console handler (less verbose)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))

    # Configure the nexus3 namespace logger
    nexus_logger = logging.getLogger("nexus3")
    nexus_logger.setLevel(min(level, console_level))

    # Remove any existing handlers to avoid duplicates on reconfigure
    nexus_logger.handlers.clear()

    # Add handlers
    nexus_logger.addHandler(file_handler)
    nexus_logger.addHandler(console_handler)

    # Don't propagate to root logger
    nexus_logger.propagate = False

    logger.info("Server logging configured: %s", log_file)
    return log_file


def _format_model_guidance_section(config: Config) -> str | None:
    """Format model guidance table for system prompt injection.

    Args:
        config: The loaded NEXUS3 configuration.

    Returns:
        Formatted markdown section, or None if no models have guidance.
    """
    models = config.get_model_guidance_table()
    if not models:
        return None

    def format_context(tokens: int) -> str:
        """Format token count as human-readable string."""
        if tokens >= 1_000_000:
            return f"{tokens / 1_000_000:.0f}M"
        elif tokens >= 1000:
            return f"{tokens / 1000:.0f}K"
        return str(tokens)

    lines = [
        "",
        "## Available Models",
        "",
        "When creating subagents, choose an appropriate model:",
        "",
        "| Alias | Context | Guidance |",
        "|-------|---------|----------|",
    ]

    for alias, context_window, guidance in models:
        ctx = format_context(context_window)
        lines.append(f"| {alias} | {ctx} | {guidance} |")

    lines.append("")
    lines.append('Example: `nexus_create(agent_id="researcher", model="fast")`')

    return "\n".join(lines)


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

    # Phase 2.5: Inject model guidance into system prompt
    model_guidance = _format_model_guidance_section(config)
    if model_guidance:
        # Import here to access the dataclass for replacement
        from dataclasses import replace
        base_context = replace(
            base_context,
            system_prompt=base_context.system_prompt + model_guidance,
        )

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
