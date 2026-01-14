"""HTTP server mode for NEXUS3.

This module provides the HTTP server entry point, which runs NEXUS3 as a
multi-agent JSON-RPC 2.0 server over HTTP. This enables programmatic control
for automation, integration with external tools, and multi-client access.

Architecture:
    - AgentPool: Manages multiple agent instances with shared components
    - GlobalDispatcher: Handles agent lifecycle (create/destroy/list)
    - Per-agent Dispatchers: Handle agent-specific requests (send/cancel/etc)

Protocol:
    - POST / or /rpc with JSON-RPC 2.0 request body → GlobalDispatcher
    - POST /agent/{agent_id} with JSON-RPC 2.0 request body → Agent's Dispatcher

Example:
    python -m nexus3 --serve

    # Create an agent
    curl -X POST http://localhost:8765 \\
        -H "Content-Type: application/json" \\
        -H "Authorization: Bearer nxk_..." \\
        -d '{"jsonrpc":"2.0","method":"create_agent","params":{},"id":1}'

    # Send a message to the agent
    curl -X POST http://localhost:8765/agent/{agent_id} \\
        -H "Content-Type: application/json" \\
        -H "Authorization: Bearer nxk_..." \\
        -d '{"jsonrpc":"2.0","method":"send","params":{"content":"Hi"},"id":2}'
"""

from pathlib import Path

from dotenv import load_dotenv

from nexus3.config.loader import load_config
from nexus3.context import ContextLoader
from nexus3.core.encoding import configure_stdio
from nexus3.core.errors import NexusError
from nexus3.core.permissions import load_custom_presets_from_config
from nexus3.provider import ProviderRegistry
from nexus3.rpc.auth import ServerKeyManager
from nexus3.rpc.detection import DetectionResult, detect_server
from nexus3.rpc.global_dispatcher import GlobalDispatcher
from nexus3.rpc.http import run_http_server
from nexus3.rpc.pool import AgentPool, SharedComponents
from nexus3.session import LogStream, SessionManager

# Configure UTF-8 at module load
configure_stdio()

# Load .env file if present
load_dotenv()


async def run_serve(
    port: int | None = None,
    verbose: bool = False,
    raw_log: bool = False,
    log_dir: Path | None = None,
) -> None:
    """Run NEXUS3 as a multi-agent HTTP server.

    Starts an HTTP server that accepts JSON-RPC 2.0 requests with
    path-based routing to multiple agents. Agent lifecycle is managed
    via the GlobalDispatcher at / or /rpc, while agent-specific
    requests go to /agent/{agent_id}.

    Before starting, detects if a server is already running on the port.
    If so, exits with an error message.

    Args:
        port: Port to listen on. If None, uses config.server.port.
        verbose: Enable verbose logging stream.
        raw_log: Enable raw API logging stream.
        log_dir: Directory for session logs.
    """
    # Load configuration first to get default port
    try:
        config = load_config()
    except NexusError as e:
        print(f"Configuration error: {e.message}")
        return

    # Use config port if not specified
    effective_port = port if port is not None else config.server.port

    # Check for existing server on the port
    detection_result = await detect_server(effective_port)
    if detection_result == DetectionResult.NEXUS_SERVER:
        print(f"Error: NEXUS3 server already running on port {effective_port}")
        print(f"Use 'nexus --connect http://localhost:{effective_port}' to connect to it")
        return
    elif detection_result == DetectionResult.OTHER_SERVICE:
        print(f"Error: Port {effective_port} is already in use by another service")
        return

    # Create provider registry (lazy-creates providers on first use)
    provider_registry = ProviderRegistry(config)

    # Base log directory
    base_log_dir = log_dir or Path(".nexus3/logs")

    # Configure logging streams based on CLI flags
    log_streams = LogStream.CONTEXT  # Always on for basic functionality
    if verbose:
        log_streams |= LogStream.VERBOSE
    if raw_log:
        log_streams |= LogStream.RAW

    # Load custom presets from config
    custom_presets = load_custom_presets_from_config(
        {k: v.model_dump() for k, v in config.permissions.presets.items()}
    )

    # Load base context for subagent inheritance
    context_loader = ContextLoader(context_config=config.context)
    base_context = context_loader.load(is_repl=False)

    # Create shared components
    shared = SharedComponents(
        config=config,
        provider_registry=provider_registry,
        base_log_dir=base_log_dir,
        base_context=base_context,
        context_loader=context_loader,
        log_streams=log_streams,
        custom_presets=custom_presets,
    )

    # Create agent pool
    pool = AgentPool(shared)

    # Create global dispatcher for agent management
    global_dispatcher = GlobalDispatcher(pool)

    # Load existing API key or generate new one (persistence prevents auth mismatches)
    key_manager = ServerKeyManager(port=effective_port)
    api_key = key_manager.load_or_generate()

    # Create session manager for auto-restore of saved sessions
    session_manager = SessionManager()

    # Print startup info
    print("NEXUS3 Multi-Agent HTTP Server")
    print(f"Logs: {base_log_dir}")
    print(f"Listening on http://localhost:{effective_port}")
    print(f"Key file: {key_manager.key_path}")
    print("Press Ctrl+C to stop")
    print("")

    # Run the HTTP server
    try:
        await run_http_server(
            pool, global_dispatcher, effective_port, api_key=api_key,
            session_manager=session_manager
        )
    finally:
        # Clean up API key file
        key_manager.delete()

        # Cleanup all agents
        for agent_info in pool.list():
            await pool.destroy(agent_info["agent_id"])
