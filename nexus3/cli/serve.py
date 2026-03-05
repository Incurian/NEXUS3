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

import asyncio
from pathlib import Path

from dotenv import load_dotenv

from nexus3.config.loader import load_config
from nexus3.core.encoding import configure_stdio
from nexus3.core.errors import NexusError
from nexus3.display import get_console
from nexus3.display.safe_sink import SafeSink
from nexus3.rpc.auth import ServerTokenManager, generate_api_key
from nexus3.rpc.bootstrap import bootstrap_server_components, configure_server_logging
from nexus3.rpc.detection import DetectionResult, detect_server
from nexus3.rpc.http import run_http_server
from nexus3.session import LogStream, SessionManager

# Configure UTF-8 at module load
configure_stdio()

# Load .env file if present
load_dotenv()


def _sanitize_serve_text(safe_sink: SafeSink, value: object) -> str:
    """Sanitize dynamic serve output text before Rich interpolation."""
    return safe_sink.sanitize_print_content(str(value))


def _format_serve_config_error_line(safe_sink: SafeSink, message: str) -> str:
    """Format config-error line while preserving trusted text wrapper."""
    safe_message = _sanitize_serve_text(safe_sink, message)
    return f"Configuration error: {safe_message}"


def _format_serve_existing_server_line(safe_sink: SafeSink, port: int) -> str:
    """Format existing-server detection line while preserving trusted text wrapper."""
    safe_port = _sanitize_serve_text(safe_sink, port)
    return f"Error: NEXUS3 server already running on port {safe_port}"


def _format_serve_connect_hint_line(safe_sink: SafeSink, port: int) -> str:
    """Format connect-hint line while preserving trusted text wrapper."""
    safe_port = _sanitize_serve_text(safe_sink, port)
    return f"Use 'nexus3 --connect http://localhost:{safe_port}' to connect to it"


def _format_serve_other_service_line(safe_sink: SafeSink, port: int) -> str:
    """Format occupied-port line while preserving trusted text wrapper."""
    safe_port = _sanitize_serve_text(safe_sink, port)
    return f"Error: Port {safe_port} is already in use by another service"


def _format_serve_url_line(safe_sink: SafeSink, port: int) -> str:
    """Format server-url startup line while preserving trusted text wrapper."""
    safe_port = _sanitize_serve_text(safe_sink, port)
    return f"Server: http://127.0.0.1:{safe_port}"


def _format_serve_token_file_line(safe_sink: SafeSink, token_path: Path) -> str:
    """Format token-file startup line while preserving trusted text wrapper."""
    safe_token_path = _sanitize_serve_text(safe_sink, token_path)
    return f"Token file: {safe_token_path}"


def _format_serve_server_log_line(safe_sink: SafeSink, server_log_file: Path) -> str:
    """Format server-log startup line while preserving trusted text wrapper."""
    safe_server_log_file = _sanitize_serve_text(safe_sink, server_log_file)
    return f"Server log: {safe_server_log_file}"


def _format_serve_session_logs_line(safe_sink: SafeSink, base_log_dir: Path) -> str:
    """Format session-logs startup line while preserving trusted text wrapper."""
    safe_base_log_dir = _sanitize_serve_text(safe_sink, base_log_dir)
    return f"Session logs: {safe_base_log_dir}"


async def run_serve(
    port: int | None = None,
    verbose: bool = False,
    log_verbose: bool = False,
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
        verbose: Enable DEBUG output to console (-v).
        log_verbose: Enable verbose logging to file (-V).
        raw_log: Enable raw API logging stream.
        log_dir: Directory for session logs.
    """
    console = get_console()
    safe_sink = SafeSink(console)

    # Load configuration first to get default port
    try:
        config = load_config()
    except NexusError as e:
        console.print(_format_serve_config_error_line(safe_sink, e.message))
        return

    # Use config port if not specified
    effective_port = port if port is not None else config.server.port

    # Check for existing server on the port
    detection_result = await detect_server(effective_port)
    if detection_result == DetectionResult.NEXUS_SERVER:
        console.print(_format_serve_existing_server_line(safe_sink, effective_port))
        console.print(_format_serve_connect_hint_line(safe_sink, effective_port))
        return
    elif detection_result == DetectionResult.OTHER_SERVICE:
        console.print(_format_serve_other_service_line(safe_sink, effective_port))
        return

    # Base log directory
    base_log_dir = log_dir or Path(".nexus3/logs")

    # Configure server logging to file (INFO to file, WARNING to console)
    # More verbose if --verbose flag is set
    import logging
    console_level = logging.DEBUG if verbose else logging.WARNING
    server_log_file = configure_server_logging(
        base_log_dir,
        level=logging.INFO,
        console_level=console_level,
    )

    # Configure logging streams based on CLI flags
    log_streams = LogStream.CONTEXT  # Always on for basic functionality
    if log_verbose:
        log_streams |= LogStream.VERBOSE
        # Configure HTTP debug logging to verbose.md
        from nexus3.session import configure_http_logging
        configure_http_logging()
    if raw_log:
        log_streams |= LogStream.RAW

    # Bootstrap server components (D5: unified bootstrap)
    pool, global_dispatcher, shared = await bootstrap_server_components(
        config=config,
        base_log_dir=base_log_dir,
        log_streams=log_streams,
        is_repl=False,
    )

    # Generate token in memory (do NOT write file yet - wait for bind success)
    # This prevents token clobbering if bind fails
    api_key = generate_api_key()
    token_manager = ServerTokenManager(port=effective_port)

    # Delete any stale token file (we've confirmed no server is running)
    token_manager.delete()

    # Create session manager for auto-restore of saved sessions
    session_manager = SessionManager()

    # Create event to signal when server has bound successfully
    started_event = asyncio.Event()

    # Start server as a task so we can wait for bind success
    server_task = asyncio.create_task(
        run_http_server(
            pool, global_dispatcher, effective_port, api_key=api_key,  # type: ignore[arg-type]
            session_manager=session_manager,
            idle_timeout=None,  # No auto-shutdown in headless dev mode
            started_event=started_event,
        )
    )

    try:
        # Wait for server to bind (with timeout)
        try:
            await asyncio.wait_for(started_event.wait(), timeout=5.0)
        except TimeoutError:
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass
            console.print("Server failed to start (bind timeout)")
            return

        # Server bound successfully - now write token file
        token_manager.save(api_key)

        # Print startup info
        console.print("NEXUS3 Multi-Agent HTTP Server")
        console.print(_format_serve_url_line(safe_sink, effective_port))
        console.print(_format_serve_token_file_line(safe_sink, token_manager.token_path))
        console.print(_format_serve_server_log_line(safe_sink, server_log_file))
        console.print(_format_serve_session_logs_line(safe_sink, base_log_dir))
        console.print("Press Ctrl+C to stop")
        console.print("")

        # Wait for server to finish (runs until shutdown)
        await server_task

    except asyncio.CancelledError:
        # Handle Ctrl+C gracefully
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass
        raise

    finally:
        # Clean up token file
        token_manager.delete()

        # Cleanup all agents
        for agent_info in pool.list():
            await pool.destroy(agent_info["agent_id"])

        # G1: Close provider HTTP clients
        if shared and shared.provider_registry:
            await shared.provider_registry.aclose()
