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
from nexus3.core.encoding import configure_stdio
from nexus3.core.errors import NexusError
from nexus3.rpc.auth import ServerTokenManager
from nexus3.rpc.bootstrap import bootstrap_server_components
from nexus3.rpc.detection import DetectionResult, detect_server
from nexus3.rpc.http import run_http_server
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

    # Base log directory
    base_log_dir = log_dir or Path(".nexus3/logs")

    # Configure logging streams based on CLI flags
    log_streams = LogStream.CONTEXT  # Always on for basic functionality
    if verbose:
        log_streams |= LogStream.VERBOSE
    if raw_log:
        log_streams |= LogStream.RAW

    # Bootstrap server components (D5: unified bootstrap)
    pool, global_dispatcher, shared = await bootstrap_server_components(
        config=config,
        base_log_dir=base_log_dir,
        log_streams=log_streams,
        is_repl=False,
    )

    # Generate fresh token (we've confirmed no server is running, so any existing token is stale)
    token_manager = ServerTokenManager(port=effective_port)
    api_key = token_manager.generate_fresh()

    # Create session manager for auto-restore of saved sessions
    session_manager = SessionManager()

    # Print startup info
    print("NEXUS3 Multi-Agent HTTP Server")
    print(f"Logs: {base_log_dir}")
    print(f"Listening on http://localhost:{effective_port}")
    print(f"Token file: {token_manager.token_path}")
    print("Press Ctrl+C to stop")
    print("")

    # Run the HTTP server
    # Note: Headless mode (--serve) requires NEXUS_DEV=1 and has no idle timeout.
    # This is intentional - dev mode servers run until explicitly stopped.
    try:
        await run_http_server(
            pool, global_dispatcher, effective_port, api_key=api_key,
            session_manager=session_manager,
            idle_timeout=None,  # No auto-shutdown in headless dev mode
        )
    finally:
        # Clean up token file
        token_manager.delete()

        # Cleanup all agents
        for agent_info in pool.list():
            await pool.destroy(agent_info["agent_id"])
