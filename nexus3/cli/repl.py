"""Async REPL with prompt-toolkit for NEXUS3.

This module provides the main interactive REPL for NEXUS3. It supports:

1. Unified mode (default): Starts an embedded HTTP server with the REPL.
   The REPL calls Session directly for rich streaming, while external clients
   can connect via HTTP.

2. Client mode (--connect): Connects to an existing NEXUS3 server.
   - If --connect without URL: Shows connect lobby to discover servers
   - If --connect URL: Connects directly to specified server

3. Server mode (--serve): Headless HTTP server without REPL (in serve.py).

Architecture in unified mode:
    nexus3 (no flags)
    +-- discover_servers(candidate_ports)
    |   +-- NEXUS_SERVER found --> Show connect lobby
    |       +-- Connect to existing server
    |       +-- Or start new embedded server
    |   +-- NO_SERVER --> Start embedded server directly:
    |       +-- Create SharedComponents
    |       +-- Create AgentPool with "main" agent
    |       +-- Generate API key in memory
    |       +-- Start HTTP server with started_event
    |       +-- Save API key only after bind succeeds
    |       +-- REPL loop calling main agent's Session directly
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from dotenv import load_dotenv
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from prompt_toolkit.lexers import SimpleLexer
from rich.live import Live

from nexus3.cli.arg_parser import parse_args
from nexus3.cli.live_state import _current_live

from nexus3.cli import repl_commands
from nexus3.cli.confirmation_ui import confirm_tool_action, format_tool_params
from nexus3.cli.keys import KeyMonitor
from nexus3.cli.lobby import LobbyChoice, show_lobby
from nexus3.cli.whisper import WhisperMode
from nexus3.commands import core as unified_cmd
from nexus3.commands.protocol import CommandContext, CommandOutput
from nexus3.commands.protocol import CommandResult as CmdResult
from nexus3.config.loader import load_config
from nexus3.core.encoding import configure_stdio
from nexus3.core.errors import NexusError
from nexus3.core.permissions import ConfirmationResult, PermissionLevel
from nexus3.core.validation import ValidationError, validate_agent_id
from nexus3.core.types import ToolCall
from nexus3.display import Activity, Spinner, get_console
from nexus3.display.theme import Status, load_theme
from nexus3.core.text_safety import escape_rich_markup
from nexus3.rpc.auth import ServerTokenManager, generate_api_key
from nexus3.rpc.bootstrap import bootstrap_server_components, configure_server_file_logging, SERVER_LOGGER_NAME
from nexus3.rpc.detection import DetectionResult
from nexus3.rpc.discovery import discover_servers, discover_token_ports, parse_port_spec
from nexus3.rpc.http import run_http_server
from nexus3.cli.connect_lobby import show_connect_lobby, ConnectAction
from nexus3.rpc.pool import Agent, AgentConfig, generate_temp_id
from nexus3.session import LogStream, SessionManager
from nexus3.session.persistence import (
    SavedSession,
    deserialize_messages,
    serialize_session,
)

# Configure UTF-8 at module load
configure_stdio()

# Load .env file if present
load_dotenv()


# NOTE: parse_args() is imported from nexus3.cli.arg_parser


async def run_repl(
    verbose: bool = False,
    log_verbose: bool = False,
    raw_log: bool = False,
    log_dir: Path | None = None,
    port: int | None = None,
    # Phase 6: Session startup flags
    resume: bool = False,
    fresh: bool = False,
    session_name: str | None = None,
    template: Path | None = None,
    model: str | None = None,
) -> None:
    """Run the async REPL loop in unified mode.

    This function implements the unified REPL architecture:
    1. Detect if a NEXUS3 server is already running on the port
    2. If server exists: Error out with message to use --connect
    3. If no server: Start embedded server (AgentPool + HTTP) with REPL

    The REPL calls Session directly to preserve streaming callbacks for
    rich display. External clients can connect via HTTP on the same port.

    Args:
        verbose: Enable DEBUG output to console (-v).
        log_verbose: Enable verbose logging to file (-V).
        raw_log: Enable raw API logging stream.
        log_dir: Directory for session logs.
        port: Port for embedded HTTP server. If None, uses config.server.port.
        resume: Resume last session automatically (skip lobby).
        fresh: Start fresh temp session (skip lobby).
        session_name: Load specific saved session by name (skip lobby).
        template: Custom system prompt file for fresh sessions.
        model: Model name/alias to use (from config.models or full model ID).
    """
    console = get_console()
    theme = load_theme()

    # Load configuration early to get default port
    try:
        config = load_config()
    except NexusError as e:
        console.print(f"[red]Error:[/] {e.message}")
        return

    # Use config port if not specified via CLI
    effective_port = port if port is not None else config.server.port

    # =========================================================================
    # Multi-server discovery and connect lobby
    # =========================================================================
    from nexus3.client import NexusClient

    # Build candidate ports for discovery
    candidate_ports: set[int] = {effective_port, 8765}  # Always include default
    candidate_ports.update(discover_token_ports().keys())

    # Discovery and connect lobby loop
    while True:
        # Discover servers on candidate ports
        servers = await discover_servers(sorted(candidate_ports))
        nexus_servers = [s for s in servers if s.detection == DetectionResult.NEXUS_SERVER]

        if nexus_servers:
            # Check if the default port already has a NEXUS server
            default_port_in_use = any(s.port == effective_port for s in nexus_servers)
            # Show connect lobby
            result = await show_connect_lobby(
                console, nexus_servers, effective_port, default_port_in_use=default_port_in_use
            )

            if result.action == ConnectAction.CONNECT:
                # Create agent first if requested
                if result.create_agent and result.agent_id:
                    try:
                        from nexus3.client import NexusClient
                        server_url = result.server_url or f"http://127.0.0.1:{effective_port}"
                        client = NexusClient.with_auto_auth(
                            f"{server_url}/",
                            api_key=result.api_key,
                        )
                        await client.create_agent(result.agent_id)
                        console.print(f"[dim]Created agent: {result.agent_id}[/]")
                    except Exception as e:
                        console.print(f"[red]Failed to create agent: {e}[/]")
                        continue  # Go back to lobby
                # Connect to selected server+agent
                await run_repl_client(
                    result.server_url or f"http://127.0.0.1:{effective_port}",
                    result.agent_id or "main",
                    api_key=result.api_key,
                )
                return

            elif result.action == ConnectAction.START_NEW_SERVER:
                # Use the port from result if specified
                if result.port:
                    effective_port = result.port
                # Fall through to start embedded server
                break

            elif result.action == ConnectAction.START_DIFFERENT_PORT:
                # User wants to start on a different port (when default is in use)
                if result.port:
                    effective_port = result.port
                # Fall through to start embedded server
                break

            elif result.action == ConnectAction.SHUTDOWN_AND_REPLACE:
                # Shutdown selected server, then start new one
                if result.server_url:
                    console.print(f"[dim]Shutting down server at {result.server_url}...[/]")
                    try:
                        shutdown_token_mgr = ServerTokenManager(port=result.port or effective_port)
                        shutdown_key = shutdown_token_mgr.load()
                        async with NexusClient(
                            result.server_url, api_key=shutdown_key, timeout=5.0
                        ) as shutdown_client:
                            await shutdown_client.shutdown_server()
                        # Wait for server to release the port
                        for _ in range(20):  # Up to 2 seconds
                            await asyncio.sleep(0.1)
                            check_port = result.port or effective_port
                            check_servers = await discover_servers([check_port])
                            still_running = any(
                                s.detection == DetectionResult.NEXUS_SERVER
                                for s in check_servers
                            )
                            if not still_running:
                                break
                        console.print("[dim]Server shutdown complete.[/]")
                    except Exception as e:
                        logger.debug("Server shutdown error: %s: %s", type(e).__name__, e)
                        console.print(f"[yellow]Warning: Server shutdown may have failed: {e}[/]")
                # Use the port from the shutdown server
                if result.port:
                    effective_port = result.port
                # Fall through to start embedded server
                break

            elif result.action == ConnectAction.RESCAN:
                # Add new ports and loop back to discovery
                if result.scan_spec:
                    try:
                        new_ports = parse_port_spec(result.scan_spec)
                        candidate_ports.update(new_ports)
                        console.print(f"[dim]Scanning {len(new_ports)} additional ports...[/]")
                    except ValueError as e:
                        console.print(f"[red]Invalid port specification:[/] {e}")
                # Loop back to discover with expanded ports
                continue

            elif result.action == ConnectAction.MANUAL_URL:
                # Connect to manually entered URL
                if result.server_url:
                    await run_repl_client(
                        result.server_url,
                        result.agent_id or "main",
                        api_key=result.api_key,
                    )
                    return
                # No URL provided, loop back
                continue

            elif result.action == ConnectAction.QUIT:
                return
        else:
            # No servers found - check if our target port is in use by another service
            for server in servers:
                is_target = server.port == effective_port
                is_other_service = server.detection == DetectionResult.OTHER_SERVICE
                if is_target and is_other_service:
                    console.print(
                        f"[red]Error:[/] Port {effective_port} is in use by another service"
                    )
                    return
            # No servers, proceed to start embedded server
            break

    # Config already loaded above for port resolution

    # Configure logging streams based on CLI flags
    log_streams = LogStream.CONTEXT  # Always on for basic functionality
    if log_verbose:
        log_streams |= LogStream.VERBOSE
        # Configure HTTP debug logging to verbose.md
        from nexus3.session import configure_http_logging
        configure_http_logging()
    if raw_log:
        log_streams |= LogStream.RAW

    # Base log directory
    base_log_dir = log_dir or Path(".nexus3/logs")

    # Configure server lifecycle logging (non-destructive, adds file handler only)
    # This ensures embedded HTTP server events are logged to server.log
    server_log_file = configure_server_file_logging(base_log_dir)
    server_logger = logging.getLogger(SERVER_LOGGER_NAME)

    # Bootstrap server components (D5: unified bootstrap)
    pool, global_dispatcher, shared = await bootstrap_server_components(
        config=config,
        base_log_dir=base_log_dir,
        log_streams=log_streams,
        is_repl=True,
    )

    # Generate token in memory - do NOT write to disk yet
    # We'll save it only after the server successfully binds
    api_key = generate_api_key()
    token_manager = ServerTokenManager(port=effective_port)

    # Create session manager for auto-restore of saved sessions
    session_manager = SessionManager()

    # Per-REPL pause events for key monitor (E4: replace global state)
    # pause_event: set = running, cleared = pause requested
    # pause_ack_event: set when monitor has actually paused
    key_monitor_pause = asyncio.Event()
    key_monitor_pause.set()  # Start in "running" state
    key_monitor_pause_ack = asyncio.Event()

    # Closure that captures the per-REPL events for confirmation callbacks
    async def confirm_with_pause(
        tool_call: ToolCall,
        target_path: Path | None,
        agent_cwd: Path,
    ) -> ConfirmationResult:
        return await confirm_tool_action(
            tool_call, target_path, agent_cwd, key_monitor_pause, key_monitor_pause_ack
        )

    # =========================================================================
    # Phase 6: Lobby mode - determine startup mode based on CLI flags
    # =========================================================================
    saved_session: SavedSession | None = None
    startup_mode: str
    agent_name: str

    if resume:
        # Load last session directly
        last = session_manager.load_last_session()
        if last is None:
            console.print("[red]No last session to resume[/]")
            token_manager.delete()
            return
        saved_session, agent_name = last
        startup_mode = "resume"
    elif fresh:
        # Fresh temp session
        agent_name = generate_temp_id(set())  # .1
        startup_mode = "fresh"
    elif session_name:
        # Load specific saved session
        from nexus3.session.session_manager import SessionNotFoundError
        try:
            saved_session = session_manager.load_session(session_name)
            agent_name = session_name
            startup_mode = "session"
        except SessionNotFoundError:
            console.print(f"[red]Session not found: {session_name}[/]")
            token_manager.delete()
            return
    else:
        # Show lobby
        lobby_result = await show_lobby(session_manager, console)
        if lobby_result.choice == LobbyChoice.QUIT:
            token_manager.delete()
            return
        elif lobby_result.choice == LobbyChoice.RESUME:
            last = session_manager.load_last_session()
            if last:
                saved_session, agent_name = last
                startup_mode = "resume"
            else:
                agent_name = generate_temp_id(set())
                startup_mode = "fresh"
        elif lobby_result.choice == LobbyChoice.FRESH:
            agent_name = generate_temp_id(set())
            startup_mode = "fresh"
        elif lobby_result.choice == LobbyChoice.SELECT:
            agent_name = lobby_result.session_name  # type: ignore[assignment]
            saved_session = session_manager.load_session(agent_name)
            startup_mode = "session"
        else:
            # Fallback (shouldn't happen)
            agent_name = generate_temp_id(set())
            startup_mode = "fresh"

    # =========================================================================
    # Create agent based on startup mode
    # =========================================================================
    if startup_mode in ("resume", "session") and saved_session is not None:
        main_agent = await pool.restore_from_saved(saved_session)
        # Note: restored sessions keep their original model, --model flag is ignored
    else:
        # Create with trusted preset for REPL (user is interactive)
        # RPC-created agents default to sandboxed via config.permissions.default_preset
        agent_config = AgentConfig(model=model, preset="trusted")
        main_agent = await pool.create(agent_id=agent_name, config=agent_config)
        if template:
            # Load custom prompt from template
            try:
                content = template.read_text(encoding="utf-8")
                main_agent.context.set_system_prompt(content)
            except OSError as e:
                console.print(f"[red]Error loading template: {e}[/]")
                token_manager.delete()
                await pool.destroy(agent_name)
                return

    # Wire up confirmation callback for main agent
    main_agent.session.on_confirm = confirm_with_pause

    # Helper to get permission data from an agent
    def get_permission_data(agent: object) -> tuple[str, str | None, list[str]]:
        """Extract permission info from agent for serialization.

        Returns:
            Tuple of (permission_level, permission_preset, disabled_tools)
        """
        perms = agent.services.get("permissions")  # type: ignore[union-attr]
        if perms:
            level = perms.effective_policy.level.value
            preset = perms.base_preset
            disabled = [
                name for name, tp in perms.tool_permissions.items()
                if not tp.enabled
            ]
        else:
            level = "trusted"
            preset = None
            disabled = []
        return level, preset, disabled

    def get_system_prompt_path() -> str | None:
        """Get the system prompt path from the loaded context."""
        # Return the most specific prompt source (last in list)
        sources = shared.base_context.sources.prompt_sources
        if not sources:
            return None
        return str(sources[-1].path)

    def get_model_alias(agent: Agent) -> str | None:
        """Get the model alias from an agent's services."""
        try:
            model = agent.services.get("model")
            return model.alias if model else None
        except Exception:
            return None

    # Update last-session immediately after startup (so resume works after quit)
    try:
        perm_level, perm_preset, disabled_tools = get_permission_data(main_agent)
        startup_saved = serialize_session(
            agent_id=agent_name,
            messages=main_agent.context.messages,
            system_prompt=main_agent.context.system_prompt or "",
            system_prompt_path=get_system_prompt_path(),
            working_directory=str(main_agent.services.get_cwd()),
            permission_level=perm_level,
            token_usage=main_agent.context.get_token_usage(),
            provenance="user",
            created_at=main_agent.created_at,
            permission_preset=perm_preset,
            disabled_tools=disabled_tools,
            model_alias=get_model_alias(main_agent),
        )
        session_manager.save_last_session(startup_saved, agent_name)
    except Exception as e:
        logger.debug("Failed to save initial session: %s: %s", type(e).__name__, e)

    # Phase 6: Agent management state
    current_agent_id = agent_name
    pool.set_repl_connected(agent_name, True)
    whisper = WhisperMode()

    # Helper to create command context (captures current state)
    def make_ctx() -> CommandContext:
        return CommandContext(
            pool=pool,
            session_manager=session_manager,
            current_agent_id=current_agent_id,
            is_repl=True,
        )

    # Helper to save current agent as last session
    def save_as_last_session(agent_id: str) -> None:
        """Save the given agent as the last session for resume."""
        try:
            agent = pool.get(agent_id)
            if agent:
                perm_level, perm_preset, disabled_tools = get_permission_data(agent)
                saved = serialize_session(
                    agent_id=agent_id,
                    messages=agent.context.messages,
                    system_prompt=agent.context.system_prompt or "",
                    system_prompt_path=get_system_prompt_path(),
                    working_directory=str(agent.services.get_cwd()),
                    permission_level=perm_level,
                    token_usage=agent.context.get_token_usage(),
                    provenance="user",
                    created_at=agent.created_at,
                    permission_preset=perm_preset,
                    disabled_tools=disabled_tools,
                    model_alias=get_model_alias(agent),
                )
                session_manager.save_last_session(saved, agent_id)
        except Exception as e:
            logger.debug("Failed to auto-save session: %s: %s", type(e).__name__, e)

    # Start HTTP server as a background task with started_event for safe token lifecycle
    # Idle timeout: 30 min (1800s) - server auto-shuts down if no RPC activity
    # This ensures servers don't linger after user walks away
    started_event = asyncio.Event()
    http_task = asyncio.create_task(
        run_http_server(
            pool, global_dispatcher, effective_port, api_key=api_key,
            session_manager=session_manager,
            idle_timeout=1800.0,
            started_event=started_event,
        ),
        name="http_server",
    )

    # Track whether server successfully started (for done-callback use)
    http_server_started = False
    loop = asyncio.get_running_loop()

    # Done-callback for http_task: log exit, cleanup token, warn user
    def _on_http_task_done(task: asyncio.Task) -> None:
        """Handle http_task completion (crash, idle timeout, or cancellation)."""
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            server_logger.info("Embedded HTTP server task cancelled")
            return

        if exc:
            # Pass proper exc_info tuple for traceback logging
            server_logger.error(
                "Embedded HTTP server crashed: %s", exc,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
        else:
            server_logger.info("Embedded HTTP server exited (no exception)")

        # Always delete token on server exit (prevents stale discovery/auth)
        try:
            token_manager.delete()
        except Exception as delete_err:
            server_logger.debug("Failed to delete token on server exit: %s", delete_err)

        # Warn user if server had started (don't warn if it never bound)
        # Guard against loop closure during shutdown
        if http_server_started and not loop.is_closed():
            loop.call_soon_threadsafe(
                lambda: console.print(
                    "[yellow]Warning:[/] Embedded RPC server stopped. "
                    "External `nexus3 rpc ...` will not work until restarted."
                )
            )

    http_task.add_done_callback(_on_http_task_done)

    # Wait for server to bind successfully OR detect early failure
    # Using asyncio.wait() to catch http_task crashing before started_event is set
    started_wait = asyncio.create_task(started_event.wait(), name="http_server_started_wait")
    try:
        done, pending = await asyncio.wait(
            {http_task, started_wait},
            timeout=5.0,
            return_when=asyncio.FIRST_COMPLETED,
        )

        if started_wait in done and started_event.is_set():
            # Server bound successfully - now safe to write token
            http_server_started = True
            token_manager.save(api_key)
            server_logger.info("Embedded RPC server listening: http://127.0.0.1:%s/", effective_port)
            console.print(f"[dim]Embedded RPC listening: http://127.0.0.1:{effective_port}/[/]")
            console.print(f"[dim]Server log: {server_log_file}[/]")
        elif http_task in done:
            # Server task exited before setting started_event - get the real exception
            exc = http_task.exception() if not http_task.cancelled() else None
            error_msg = f"Embedded server exited during startup: {exc!r}" if exc else "Embedded server exited during startup (no exception)"
            server_logger.error(error_msg)
            console.print(f"[red]Error:[/] {error_msg}")
            console.print("[dim]Check server.log for details.[/]")
            await pool.destroy(agent_name)
            if shared and shared.provider_registry:
                await shared.provider_registry.aclose()
            return
        else:
            # Timeout - neither completed in time
            http_task.cancel()
            try:
                await http_task
            except asyncio.CancelledError:
                pass
            server_logger.error("Server failed to start on port %s (timeout)", effective_port)
            console.print(f"[red]Error:[/] Server failed to start on port {effective_port}")
            console.print("[dim]The port may be in use by another process.[/]")
            await pool.destroy(agent_name)
            if shared and shared.provider_registry:
                await shared.provider_registry.aclose()
            return
    finally:
        # Clean up the started_wait task
        started_wait.cancel()
        try:
            await started_wait
        except asyncio.CancelledError:
            pass

    # Get the session from the main agent for direct REPL access
    session = main_agent.session
    logger = main_agent.logger

    # Spinner for streaming phases
    spinner = Spinner(console, theme)

    # =============================================================
    # Turn state tracking
    # =============================================================

    # Tool state tracking for timing and cancellation bookkeeping
    import time as _time
    _tool_start_times: dict[str, float] = {}  # tool_id -> start time
    _active_tools: dict[str, str] = {}  # tool_id -> tool_name (for cancellation)
    _pending_tools: dict[str, tuple[str, str]] = {}  # tool_id -> (name, params) (for halt display)
    _had_errors = False  # Track if any errors occurred in turn
    _stream_line_open = False  # Whether streaming has left the cursor mid-line

    # Thinking state
    _thinking_start: float | None = None
    _thinking_total: float = 0.0
    _thinking_printed = False

    def _reset_turn_state() -> None:
        """Reset all turn state for a new turn."""
        nonlocal _had_errors, _thinking_start, _thinking_total, _thinking_printed, _stream_line_open
        _tool_start_times.clear()
        _active_tools.clear()
        _pending_tools.clear()
        _had_errors = False
        _stream_line_open = False
        _thinking_start = None
        _thinking_total = 0.0
        _thinking_printed = False

    def _print_thinking_if_needed() -> None:
        """Print accumulated thinking time once (if any)."""
        nonlocal _thinking_printed
        if _thinking_printed:
            return
        if _thinking_total > 0:
            _thinking_printed = True
            display_duration = max(1, int(_thinking_total))
            spinner.print(f"  [dim cyan]●[/] [dim]Thought for {display_duration}s[/]")

    # =============================================================
    # Session callbacks - print immediately to scrollback
    # =============================================================

    # Callback when tool call is detected in stream (early detection, no print)
    def on_tool_call(name: str, tool_id: str) -> None:
        # Just track for potential cancellation - no display update needed
        pass

    # Callback when reasoning state changes
    def on_reasoning(is_reasoning: bool) -> None:
        nonlocal _thinking_start, _thinking_total
        if is_reasoning:
            _thinking_start = _time.monotonic()
            spinner.update("Thinking...", Activity.THINKING)
        else:
            if _thinking_start:
                _thinking_total += _time.monotonic() - _thinking_start
                _thinking_start = None
            spinner.update("Responding...", Activity.RESPONDING)

    # Batch callbacks for tool execution
    def on_batch_start(tool_calls: tuple) -> None:
        """Initialize batch - print thinking, then track tools."""
        nonlocal _stream_line_open

        # Flush any buffered streaming text before tool output
        spinner.flush_stream()

        # If we've been streaming assistant text without a trailing newline,
        # make sure tool output starts on a fresh line.
        if _stream_line_open:
            spinner.print("")
            _stream_line_open = False

        # Print any accumulated thinking BEFORE tool calls
        _print_thinking_if_needed()

        # Track all tools in batch as pending (for halt display)
        for tc in tool_calls:
            params = format_tool_params(tc.arguments)
            _pending_tools[tc.id] = (tc.name, params)

        spinner.update("Running tools...", Activity.TOOL_CALLING)

    def on_tool_active(name: str, tool_id: str) -> None:
        """Tool started executing - print call line and track timing."""
        nonlocal _stream_line_open

        # Flush any buffered streaming text before tool output
        spinner.flush_stream()

        if _stream_line_open:
            spinner.print("")
            _stream_line_open = False

        # Get params from pending (if available)
        params = ""
        if tool_id in _pending_tools:
            _, params = _pending_tools[tool_id]

        # Print tool call line
        if params:
            spinner.print(f"  [cyan]●[/] {name}: {params}")
        else:
            spinner.print(f"  [cyan]●[/] {name}")

        # Track start time and active state
        _tool_start_times[tool_id] = _time.monotonic()
        _active_tools[tool_id] = name

        # Remove from pending
        _pending_tools.pop(tool_id, None)

        # Update spinner
        spinner.update(f"Running: {name}", Activity.TOOL_CALLING)

    def on_batch_progress(name: str, tool_id: str, success: bool, error: str, output: str) -> None:
        """Tool completed - print result line with duration."""
        import json as _json
        nonlocal _had_errors

        # Calculate duration
        duration = 0.0
        if tool_id in _tool_start_times:
            duration = _time.monotonic() - _tool_start_times.pop(tool_id)

        # Remove from active tracking
        _active_tools.pop(tool_id, None)
        _pending_tools.pop(tool_id, None)

        # Format duration
        duration_str = f" ({duration:.1f}s)" if duration >= 0.1 else ""

        if success:
            # Success - show result summary
            result_preview = _summarize_tool_output(name, output)
            if result_preview:
                spinner.print(f"      [green]→[/] {result_preview}{duration_str}")
            else:
                spinner.print(f"      [green]→[/] done{duration_str}")

            # Special handling for nexus_send - show response content
            if name == "nexus_send" and output:
                try:
                    parsed = _json.loads(output)
                    content = parsed.get("content", "")
                    if content:
                        preview = " ".join(content.split())[:100]
                        ellipsis = "..." if len(content) > 100 else ""
                        spinner.print(f"      [dim cyan]↳ Response: {preview}{ellipsis}[/]")
                except (_json.JSONDecodeError, KeyError):
                    pass
        else:
            _had_errors = True
            # Error - show error message
            error_preview = escape_rich_markup(error[:70] + ("..." if len(error) > 70 else ""))
            spinner.print(f"      [red]→[/] [red]{error_preview}[/]{duration_str}")

    def on_batch_halt() -> None:
        """Sequential batch halted - print halted for remaining pending tools."""
        for tool_id, (name, params) in list(_pending_tools.items()):
            if params:
                spinner.print(f"  [dark_orange]●[/] {name}: {params} [dark_orange](halted)[/]")
            else:
                spinner.print(f"  [dark_orange]●[/] {name} [dark_orange](halted)[/]")
        _pending_tools.clear()

    def on_batch_complete() -> None:
        """Batch finished - no action needed, tools already printed."""
        pass

    def _summarize_tool_output(name: str, output: str) -> str:
        """Create a brief summary of tool output."""
        if not output:
            return ""
        # For read_file, show line count
        if name == "read_file":
            lines = output.count("\n") + (1 if output and not output.endswith("\n") else 0)
            size_kb = len(output) / 1024
            if size_kb >= 1:
                return f"{lines} lines, {size_kb:.1f}KB"
            return f"{lines} lines"
        # For other tools, first non-empty line (truncated)
        first_line = output.split("\n")[0].strip()[:60]
        if first_line:
            return first_line + ("..." if len(output.split("\n")[0]) > 60 else "")
        return ""

    # =============================================================
    # Session callback attachment (leak-prevention)
    #
    # Problem: If the user switches into another agent, that agent's Session can
    # end up with REPL callbacks attached. Later, when the current agent calls
    # nexus_send(target_agent), the target agent runs in-process and its tool
    # callbacks can render into the current terminal UI ("sleep overwrote send").
    #
    # Fix: Attach REPL streaming callbacks only to the currently displayed agent.
    # On switch, detach callbacks from the previous session.
    # =============================================================

    _callback_session: object | None = None

    def _detach_repl_callbacks(sess: object) -> None:
        """Clear streaming callbacks from a session (NOT on_confirm)."""
        setattr(sess, "on_tool_call", None)
        setattr(sess, "on_reasoning", None)
        setattr(sess, "on_batch_start", None)
        setattr(sess, "on_tool_active", None)
        setattr(sess, "on_batch_progress", None)
        setattr(sess, "on_batch_halt", None)
        setattr(sess, "on_batch_complete", None)

    def _attach_repl_callbacks(sess: object) -> None:
        """Attach streaming callbacks to a session."""
        setattr(sess, "on_tool_call", on_tool_call)
        setattr(sess, "on_reasoning", on_reasoning)
        setattr(sess, "on_batch_start", on_batch_start)
        setattr(sess, "on_tool_active", on_tool_active)
        setattr(sess, "on_batch_progress", on_batch_progress)
        setattr(sess, "on_batch_halt", on_batch_halt)
        setattr(sess, "on_batch_complete", on_batch_complete)

    def _set_display_session(new_sess: object) -> None:
        """Detach callbacks from prior displayed session; attach to new_sess."""
        nonlocal _callback_session
        if _callback_session is not None and _callback_session is not new_sess:
            _detach_repl_callbacks(_callback_session)
        _attach_repl_callbacks(new_sess)
        _callback_session = new_sess

    # Attach callbacks to the initial session
    _set_display_session(session)

    # =============================================================
    # Incoming turn notifications (for RPC messages while at prompt)
    #
    # When another agent or external client sends a message via RPC,
    # notify the user so they know processing is happening.
    # =============================================================

    _current_dispatcher: object | None = None
    _INCOMING_TURN_SENTINEL = object()  # Sentinel to interrupt prompt
    _incoming_turn_active = False  # Flag to track if incoming turn in progress
    _incoming_turn_done: asyncio.Event | None = None  # Signal spinner to stop
    _incoming_spinner_task: asyncio.Task[None] | None = None  # Spinner task
    _incoming_end_payload: dict[str, Any] | None = None  # Store end payload for after spinner

    async def _run_incoming_spinner() -> None:
        """Run the spinner while incoming turn is active."""
        nonlocal _incoming_turn_active, _incoming_end_payload
        # Create a fresh spinner for the incoming turn
        incoming_spinner = Spinner(console, theme)
        incoming_spinner.show("Processing incoming message...", Activity.WAITING)

        try:
            # Wait until turn ends
            while _incoming_turn_done and not _incoming_turn_done.is_set():
                await asyncio.sleep(0.1)
        finally:
            incoming_spinner.hide()

        # After spinner stops, print the end notification
        if _incoming_end_payload:
            ok = _incoming_end_payload.get("ok", False)
            if ok:
                # Strip newlines and collapse whitespace for clean single-line preview
                raw_preview = _incoming_end_payload.get("content_preview", "")
                preview = " ".join(raw_preview.split())[:50]
                ellipsis = "..." if len(raw_preview) > 50 else ""
                console.print(f"[bold green]✓ Response sent:[/] {preview}{ellipsis}")
            elif _incoming_end_payload.get("cancelled"):
                console.print("[bold yellow]✗ Request cancelled[/]")
            _incoming_end_payload = None
        # Only release main loop AFTER notification is printed
        _incoming_turn_active = False

    async def _on_incoming_turn(payload: dict[str, Any]) -> None:
        """Handle incoming turn notifications from dispatcher."""
        nonlocal _incoming_turn_active, _incoming_turn_done, _incoming_spinner_task, _incoming_end_payload
        phase = payload.get("phase")
        source = payload.get("source", "rpc")
        source_agent = payload.get("source_agent_id")

        if phase == "started":
            _incoming_turn_active = True
            # Strip newlines for clean single-line preview
            raw_preview = payload.get("preview", "")
            preview = " ".join(raw_preview.split())[:50]

            # Interrupt the prompt if active - this makes it "agent's turn"
            if prompt_session.app and prompt_session.app.is_running:
                prompt_session.app.exit(result=_INCOMING_TURN_SENTINEL)
                # Yield to let prompt actually exit before we print
                await asyncio.sleep(0)
                # Move up and clear the prompt line (prompt_toolkit adds newline on exit)
                sys.stdout.write("\033[1A\r\033[2K")  # Up one line, start of line, clear
                sys.stdout.flush()

            # Print notification
            if source_agent:
                console.print(f"[bold cyan]▶ INCOMING from {source_agent}:[/] {preview}...")
            else:
                console.print(f"[bold cyan]▶ INCOMING ({source}):[/] {preview}...")
            console.bell()

            # Start spinner task
            _incoming_turn_done = asyncio.Event()
            _incoming_spinner_task = asyncio.create_task(_run_incoming_spinner())

        elif phase == "ended":
            # Store payload and signal spinner to stop
            _incoming_end_payload = payload
            if _incoming_turn_done:
                _incoming_turn_done.set()
            # Wait for spinner task to finish (it prints the end notification)
            if _incoming_spinner_task:
                try:
                    await _incoming_spinner_task
                except Exception:
                    pass
                _incoming_spinner_task = None

    def _set_incoming_hook(dispatcher: object) -> None:
        """Set the incoming turn hook on a dispatcher."""
        nonlocal _current_dispatcher
        # Clear hook on old dispatcher
        if _current_dispatcher is not None and _current_dispatcher is not dispatcher:
            setattr(_current_dispatcher, "on_incoming_turn", None)
        # Set hook on new dispatcher
        setattr(dispatcher, "on_incoming_turn", _on_incoming_turn)
        _current_dispatcher = dispatcher

    # Wire up incoming turn notifications for main agent
    _set_incoming_hook(main_agent.dispatcher)

    # Print welcome message
    console.print("[bold]NEXUS3 v0.1.0[/bold]")
    console.print(f"Agent: {current_agent_id}", style="dim")
    console.print(f"Session: {logger.session_dir}", style="dim")
    console.print(f"Server: http://127.0.0.1:{effective_port}", style="dim")
    # Show prompt sources (from ContextLoader)
    for source in shared.base_context.sources.prompt_sources:
        console.print(f"Context: {source.path} ({source.layer_name})", style="dim")
    console.print("Commands: /help | ESC to cancel", style="dim")
    console.print("")

    # Shell environment detection and warnings (Windows only)
    if sys.platform == "win32":
        from nexus3.core.shell_detection import (
            detect_windows_shell,
            WindowsShell,
            check_console_codepage,
        )

        shell = detect_windows_shell()
        if shell == WindowsShell.CMD:
            console.print(
                "[yellow]Detected CMD.exe[/] - using simplified output mode.",
                style="dim",
            )
            console.print(
                "[dim]For best experience, use Windows Terminal or PowerShell 7+[/]"
            )
        elif shell == WindowsShell.POWERSHELL_5:
            console.print(
                "[yellow]Detected PowerShell 5.1[/] - ANSI colors may not work.",
                style="dim",
            )
            console.print(
                "[dim]For best experience, upgrade to PowerShell 7+[/]"
            )

        # Code page warning
        codepage, is_utf8 = check_console_codepage()
        if not is_utf8 and codepage != 0:
            console.print(
                f"[yellow]Console code page is {codepage}[/], not UTF-8 (65001).",
                style="dim",
            )
            console.print(
                "[dim]Run 'chcp 65001' before NEXUS3 for proper character display.[/]"
            )

    # Toolbar state - tracks ready/active and whether there were errors
    toolbar_has_errors = False

    def get_toolbar() -> HTML:
        """Return the bottom toolbar based on current state."""
        square = '<style fg="ansibrightblack">■</style>'

        # Get token usage from current session's context
        token_info = ""
        if session.context:
            usage = session.context.get_token_usage()
            used = usage["total"]
            budget = usage["budget"]
            token_info = f' | <style fg="ansibrightblack">{used:,} / {budget:,}</style>'

        if toolbar_has_errors:
            return HTML(f'{square} <style fg="ansiyellow">● ready (some tasks incomplete)</style>{token_info}')
        else:
            return HTML(f'{square} <style fg="ansigreen">● ready</style>{token_info}')

    # Native reverse styling: prompt via HTML, input via lexer
    lexer = SimpleLexer('class:input-field')
    style = Style.from_dict({
        'bottom-toolbar': 'noreverse',
        'prompt': 'reverse',
        'input-field': 'reverse',
    })
    prompt_session: PromptSession[str] = PromptSession(
        lexer=lexer,
        bottom_toolbar=get_toolbar,
        style=style,
    )

    # Phase 6: Comprehensive slash command handler
    async def handle_slash_command(cmd_str: str) -> CommandOutput | None:
        """Handle slash commands, return None if not a slash command."""
        nonlocal current_agent_id

        if not cmd_str.startswith("/"):
            return None

        # Parse command and args
        parts = cmd_str[1:].split(None, 1)
        cmd_name = parts[0].lower() if parts else ""
        cmd_args = parts[1] if len(parts) > 1 else ""

        # Check for --help or -h flag - show command help instead of executing
        if cmd_args and ("--help" in cmd_args.split() or "-h" in cmd_args.split()):
            help_text = repl_commands.get_command_help(cmd_name)
            if help_text:
                return CommandOutput.success(message=help_text)
            # Fall through to normal handling if command not found

        ctx = make_ctx()

        # REPL-only commands
        if cmd_name in ("quit", "exit", "q"):
            return await repl_commands.cmd_quit(ctx)
        elif cmd_name == "help":
            return await repl_commands.cmd_help(ctx, cmd_args or None)
        elif cmd_name == "clear":
            return await repl_commands.cmd_clear(ctx)
        elif cmd_name == "agent":
            return await repl_commands.cmd_agent(ctx, cmd_args or None)
        elif cmd_name == "whisper":
            if not cmd_args:
                return CommandOutput.error("Usage: /whisper <agent>")
            try:
                target = validate_agent_id(cmd_args.strip())
            except ValidationError as e:
                return CommandOutput.error(f"Invalid agent name: {e}")
            return await repl_commands.cmd_whisper(ctx, whisper, target)
        elif cmd_name == "over":
            return await repl_commands.cmd_over(ctx, whisper)
        elif cmd_name == "cwd":
            return await repl_commands.cmd_cwd(ctx, cmd_args or None)
        elif cmd_name == "permissions":
            return await repl_commands.cmd_permissions(ctx, cmd_args or None)
        elif cmd_name == "prompt":
            return await repl_commands.cmd_prompt(ctx, cmd_args or None)
        elif cmd_name == "compact":
            return await repl_commands.cmd_compact(ctx)
        elif cmd_name == "model":
            return await repl_commands.cmd_model(ctx, cmd_args or None)
        elif cmd_name == "mcp":
            return await repl_commands.cmd_mcp(ctx, cmd_args or None)
        elif cmd_name == "init":
            return await repl_commands.cmd_init(ctx, cmd_args or None)

        # Unified commands (work in both CLI and REPL)
        elif cmd_name == "list":
            return await unified_cmd.cmd_list(ctx)
        elif cmd_name == "create":
            if not cmd_args:
                return CommandOutput.error(
                    "Usage: /create <name> [--yolo|--trusted|--sandboxed] [--model <alias>]"
                )
            create_parts = cmd_args.split()
            try:
                name = validate_agent_id(create_parts[0])
            except ValidationError as e:
                return CommandOutput.error(f"Invalid agent name: {e}")
            perm = "trusted"
            model: str | None = None
            i = 1
            while i < len(create_parts):
                p = create_parts[i]
                p_lower = p.lower()
                if p_lower in ("--yolo", "-y"):
                    perm = "yolo"
                elif p_lower in ("--trusted", "-t"):
                    perm = "trusted"
                elif p_lower in ("--sandboxed", "-s"):
                    perm = "sandboxed"
                elif p_lower in ("--model", "-m"):
                    if i + 1 >= len(create_parts):
                        return CommandOutput.error(
                            f"Flag {p} requires a value.\n"
                            "Usage: /create <name> --model <alias>"
                        )
                    model = create_parts[i + 1]
                    i += 1
                elif p_lower.startswith("--model="):
                    model = p.split("=", 1)[1]
                    if not model:
                        return CommandOutput.error("Flag --model= requires a value.")
                elif p_lower.startswith("-m="):
                    model = p.split("=", 1)[1]
                    if not model:
                        return CommandOutput.error("Flag -m= requires a value.")
                elif p.startswith("-"):
                    return CommandOutput.error(
                        f"Unknown flag: {p}\n"
                        "Valid flags: --yolo/-y, --trusted/-t, --sandboxed/-s, --model/-m <alias>"
                    )
                else:
                    return CommandOutput.error(
                        f"Unexpected argument: {p}\n"
                        "Usage: /create <name> [--yolo|--trusted|--sandboxed] [--model <alias>]"
                    )
                i += 1
            return await unified_cmd.cmd_create(ctx, name, perm, model)
        elif cmd_name == "destroy":
            if not cmd_args:
                return CommandOutput.error("Usage: /destroy <name>")
            try:
                agent_name = validate_agent_id(cmd_args.strip())
            except ValidationError as e:
                return CommandOutput.error(f"Invalid agent name: {e}")
            return await unified_cmd.cmd_destroy(ctx, agent_name)
        elif cmd_name == "send":
            send_parts = cmd_args.split(None, 1)
            if len(send_parts) < 2:
                return CommandOutput.error("Usage: /send <agent> <message>")
            try:
                agent_name = validate_agent_id(send_parts[0])
            except ValidationError as e:
                return CommandOutput.error(f"Invalid agent name: {e}")
            return await unified_cmd.cmd_send(ctx, agent_name, send_parts[1])
        elif cmd_name == "status":
            # Parse flags: --tools, --tokens, --all/-a, and optional agent_id
            status_args = cmd_args.split() if cmd_args else []
            show_tools = False
            show_tokens = False
            agent_name = None

            for arg in status_args:
                if arg == "--tools":
                    show_tools = True
                elif arg == "--tokens":
                    show_tokens = True
                elif arg in ("--all", "-a"):
                    show_tools = True
                    show_tokens = True
                elif not arg.startswith("-"):
                    # Assume it's an agent ID
                    try:
                        agent_name = validate_agent_id(arg)
                    except ValidationError as e:
                        return CommandOutput.error(f"Invalid agent name: {e}")

            return await unified_cmd.cmd_status(ctx, agent_name, show_tools, show_tokens)
        elif cmd_name == "cancel":
            cancel_parts = cmd_args.split() if cmd_args else []
            agent_id_arg = None
            if cancel_parts:
                try:
                    agent_id_arg = validate_agent_id(cancel_parts[0])
                except ValidationError as e:
                    return CommandOutput.error(f"Invalid agent name: {e}")
            req_id = cancel_parts[1] if len(cancel_parts) > 1 else None
            return await unified_cmd.cmd_cancel(ctx, agent_id_arg, req_id)
        elif cmd_name == "save":
            if cmd_args:
                try:
                    session_name = validate_agent_id(cmd_args.strip())
                except ValidationError as e:
                    return CommandOutput.error(f"Invalid session name: {e}")
                return await unified_cmd.cmd_save(ctx, session_name)
            return await unified_cmd.cmd_save(ctx, None)
        elif cmd_name == "clone":
            clone_parts = cmd_args.split()
            if len(clone_parts) != 2:
                return CommandOutput.error("Usage: /clone <src> <dest>")
            try:
                src_name = validate_agent_id(clone_parts[0])
                dest_name = validate_agent_id(clone_parts[1])
            except ValidationError as e:
                return CommandOutput.error(f"Invalid session name: {e}")
            return await unified_cmd.cmd_clone(ctx, src_name, dest_name)
        elif cmd_name == "rename":
            rename_parts = cmd_args.split()
            if len(rename_parts) != 2:
                return CommandOutput.error("Usage: /rename <old> <new>")
            try:
                old_name = validate_agent_id(rename_parts[0])
                new_name = validate_agent_id(rename_parts[1])
            except ValidationError as e:
                return CommandOutput.error(f"Invalid session name: {e}")
            return await unified_cmd.cmd_rename(ctx, old_name, new_name)
        elif cmd_name == "delete":
            if not cmd_args:
                return CommandOutput.error("Usage: /delete <name>")
            try:
                session_name = validate_agent_id(cmd_args.strip())
            except ValidationError as e:
                return CommandOutput.error(f"Invalid session name: {e}")
            return await unified_cmd.cmd_delete(ctx, session_name)
        elif cmd_name == "shutdown":
            return await unified_cmd.cmd_shutdown(ctx)

        # Unknown command
        return CommandOutput.error(
            f"Unknown command: /{cmd_name}. Use /help for available commands."
        )

    # Main REPL loop
    while True:
        try:
            # YOLO mode warning - show before prompt so user sees it before typing
            agent = pool.get(current_agent_id)
            if agent:
                perms = agent.services.get("permissions")
                if perms and perms.effective_policy.level == PermissionLevel.YOLO:
                    console.print("[bold red]⚠️  YOLO MODE - All actions execute without confirmation[/]")

            # Dynamic prompt based on whisper mode
            if whisper.is_active():
                prompt_text = f"{whisper.target_agent_id}> "
            else:
                prompt_text = "> "
            user_input = await prompt_session.prompt_async(
                HTML(f"<style class='prompt'>{prompt_text}</style>")
            )

            # Check if prompt was interrupted by incoming RPC turn
            if user_input is _INCOMING_TURN_SENTINEL:
                # Wait for incoming turn to complete before showing prompt again
                while _incoming_turn_active:
                    await asyncio.sleep(0.05)
                continue

            # Handle empty input
            if not user_input.strip():
                continue

            # Track whisper state before handling command (for /over visual)
            was_whisper = whisper.is_active()

            # Handle slash commands with new routing
            if user_input.startswith("/"):
                output = await handle_slash_command(user_input)
                if output is not None:
                    # Handle command results
                    if output.result == CmdResult.QUIT:
                        console.print("Goodbye!", style="dim")
                        break
                    elif output.result == CmdResult.SWITCH_AGENT:
                        # Check if exiting whisper mode
                        if was_whisper:
                            console.print(
                                f"[dim]\u2514\u2500\u2500 returned to "
                                f"{output.new_agent_id} "
                                f"\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
                                f"\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
                                f"\u2500\u2500\u2500\u2500\u2500\u2500\u2518[/]"
                            )
                        # Switch to new agent
                        new_id = output.new_agent_id
                        new_agent = pool.get(new_id)
                        if new_agent:
                            pool.set_repl_connected(current_agent_id, False)
                            current_agent_id = new_id
                            pool.set_repl_connected(new_id, True)
                            session = new_agent.session
                            logger = new_agent.logger
                            # Detach callbacks from old session, attach to new
                            _set_display_session(session)
                            _set_incoming_hook(new_agent.dispatcher)
                            session.on_confirm = confirm_with_pause
                            # Update last session on switch
                            save_as_last_session(current_agent_id)
                            if not was_whisper:
                                console.print(
                                    f"Switched to: {current_agent_id}", style="dim cyan"
                                )
                        else:
                            console.print(f"[red]Agent not found: {new_id}[/]")
                    elif output.result == CmdResult.ENTER_WHISPER:
                        console.print(
                            f"[dim]\u250c\u2500\u2500 whisper mode: "
                            f"{output.whisper_target} \u2500\u2500 "
                            f"/over to return \u2500\u2500\u2510[/]"
                        )
                    elif output.result == CmdResult.ERROR:
                        # Check for prompt actions that need user confirmation
                        action = output.data.get("action") if output.data else None

                        if action == "prompt_restore":
                            # Restore saved session
                            if output.message:
                                console.print(f"[yellow]{output.message}[/]")
                            try:
                                confirm = console.input("[y/n]: ").strip().lower()
                            except (EOFError, KeyboardInterrupt):
                                confirm = "n"

                            if confirm == "y":
                                agent_name_to_restore = output.data["agent_name"]
                                permission_to_use = output.data.get("permission")
                                try:
                                    # Load saved session and restore
                                    saved = session_manager.load_session(agent_name_to_restore)
                                    # Create agent with permission preset
                                    agent_config = AgentConfig(preset=permission_to_use)
                                    await pool.create(
                                        agent_id=agent_name_to_restore,
                                        config=agent_config,
                                    )
                                    # Restore messages to context
                                    new_agent = pool.get(agent_name_to_restore)
                                    if new_agent:
                                        # Wire up confirmation callback
                                        new_agent.session.on_confirm = confirm_with_pause
                                        restored_msgs = deserialize_messages(saved.messages)
                                        for msg in restored_msgs:
                                            new_agent.context._messages.append(msg)
                                        console.print(
                                            f"Restored session: {agent_name_to_restore} "
                                            f"({len(restored_msgs)} messages)",
                                            style="dim green",
                                        )
                                        # Switch to restored agent
                                        pool.set_repl_connected(current_agent_id, False)
                                        current_agent_id = agent_name_to_restore
                                        pool.set_repl_connected(agent_name_to_restore, True)
                                        session = new_agent.session
                                        logger = new_agent.logger
                                        # Detach callbacks from old session, attach to new
                                        _set_display_session(session)
                                        _set_incoming_hook(new_agent.dispatcher)
                                        session.on_confirm = confirm_with_pause
                                        # Update last session on restore
                                        save_as_last_session(current_agent_id)
                                        console.print(
                                            f"Switched to: {agent_name_to_restore}",
                                            style="dim cyan",
                                        )
                                except Exception as e:
                                    console.print(f"[red]Failed to restore: {e}[/]")

                        elif action in ("prompt_create", "prompt_create_whisper"):
                            # Create new agent
                            if output.message:
                                console.print(f"[yellow]{output.message}[/]")
                            try:
                                confirm = console.input("[y/n]: ").strip().lower()
                            except (EOFError, KeyboardInterrupt):
                                confirm = "n"

                            if confirm == "y":
                                agent_name_to_create = output.data["agent_name"]
                                permission_to_use = output.data.get("permission")
                                model_to_use = output.data.get("model")
                                try:
                                    # Create agent with permission preset and model
                                    agent_config = AgentConfig(
                                        preset=permission_to_use,
                                        model=model_to_use,
                                    )
                                    new_agent = await pool.create(
                                        agent_id=agent_name_to_create,
                                        config=agent_config,
                                    )
                                    # Wire up confirmation callback
                                    new_agent.session.on_confirm = confirm_with_pause
                                    console.print(
                                        f"Created agent: {agent_name_to_create}",
                                        style="dim green",
                                    )

                                    if action == "prompt_create":
                                        # Switch to the new agent
                                        pool.set_repl_connected(current_agent_id, False)
                                        current_agent_id = agent_name_to_create
                                        pool.set_repl_connected(agent_name_to_create, True)
                                        session = new_agent.session
                                        logger = new_agent.logger
                                        # Detach callbacks from old session, attach to new
                                        _set_display_session(session)
                                        _set_incoming_hook(new_agent.dispatcher)
                                        session.on_confirm = confirm_with_pause
                                        # Update last session on create+switch
                                        save_as_last_session(current_agent_id)
                                        console.print(
                                            f"Switched to: {agent_name_to_create}",
                                            style="dim cyan",
                                        )
                                    else:  # prompt_create_whisper
                                        whisper.enter(
                                            agent_name_to_create, current_agent_id
                                        )
                                        console.print(
                                            f"[dim]\u250c\u2500\u2500 whisper mode: "
                                            f"{agent_name_to_create} \u2500\u2500 "
                                            f"/over to return \u2500\u2500\u2510[/]"
                                        )
                                except Exception as e:
                                    console.print(f"[red]Failed to create agent: {e}[/]")

                        elif output.message:
                            console.print(f"[red]{output.message}[/]")
                    elif output.result == CmdResult.SUCCESS:
                        # Handle special actions
                        if output.data and output.data.get("action") == "clear":
                            console.clear()
                        elif output.message:
                            console.print(output.message)
                continue

            # Determine target session (whisper mode may redirect)
            if whisper.is_active():
                target_id = whisper.target_agent_id
                target_agent = pool.get(target_id)
                if target_agent is None:
                    console.print(f"[red]Whisper target not found: {target_id}[/]")
                    whisper.exit()
                    continue
                active_session = target_agent.session
            else:
                active_session = session

            # Visual separation before response/streaming
            console.print("")

            # Reset turn state
            _reset_turn_state()
            toolbar_has_errors = False
            turn_start_time = _time.monotonic()
            _first_chunk_received = False

            # Streaming task that can be cancelled
            stream_task: asyncio.Task[None] | None = None
            was_cancelled = False
            cancel_reason = ""

            def on_cancel(
                get_task: object = lambda: stream_task,
            ) -> None:
                nonlocal was_cancelled, cancel_reason
                was_cancelled = True
                # Determine what we're cancelling
                if _active_tools:
                    # Cancelling a tool
                    tool_name = list(_active_tools.values())[0]
                    cancel_reason = f"Cancelled: {tool_name}"
                else:
                    cancel_reason = "Cancelled: streaming"
                task = get_task()  # type: ignore[operator]
                if task is not None:
                    task.cancel()

            async def do_stream(
                inp: str = user_input,
                target_sess: object = active_session,
                agent_id: str = current_agent_id,
            ) -> None:
                nonlocal _first_chunk_received, _stream_line_open
                # Wrap in agent_context for correct raw log routing
                with pool.log_multiplexer.agent_context(agent_id):
                    async for chunk in target_sess.send(inp):  # type: ignore[union-attr]
                        if not _first_chunk_received:
                            _first_chunk_received = True
                            spinner.update("Responding...", Activity.RESPONDING)
                        spinner.print_streaming(chunk)
                        if chunk:
                            _stream_line_open = not chunk.endswith("\n")

            # Show spinner during streaming
            spinner.show("Waiting...", Activity.WAITING)

            # Store live reference for confirmation callback to pause/resume
            token = _current_live.set(spinner.live)
            try:
                async with KeyMonitor(
                    on_escape=on_cancel,
                    pause_event=key_monitor_pause,
                    pause_ack_event=key_monitor_pause_ack,
                ):
                    stream_task = asyncio.create_task(do_stream())
                    # Wait for streaming to complete
                    try:
                        await stream_task
                    except asyncio.CancelledError:
                        pass  # Cancelled by ESC

            except NexusError as e:
                # Ensure the error prints on its own line if we were mid-stream.
                if _stream_line_open:
                    spinner.print("")
                    _stream_line_open = False
                spinner.print(f"[red]Error:[/] {e.message}")
                spinner.print("")
                _had_errors = True
            finally:
                # Ensure the streamed response line is terminated before we
                # stop the Live spinner (prevents messy wrapping / cursor state).
                if _stream_line_open:
                    spinner.print("")
                    _stream_line_open = False
                spinner.hide()
                _current_live.reset(token)

            # Update toolbar error state
            if _had_errors:
                toolbar_has_errors = True

            # Print any remaining thinking time
            _print_thinking_if_needed()

            # Collect cancelled tools for Session bookkeeping
            if was_cancelled and _active_tools:
                cancelled_tools = [(tid, name) for tid, name in _active_tools.items()]
                if cancelled_tools:
                    active_session.add_cancelled_tools(cancelled_tools)

            # Newline after streaming content
            console.print("")

            # Show completion status
            turn_duration = _time.monotonic() - turn_start_time
            if was_cancelled:
                console.print(f"[bright_yellow]● {cancel_reason}[/]")
            else:
                console.print(f"[dim]Turn completed in {turn_duration:.1f}s[/]")

            # Auto-save last session after each interaction
            try:
                # Get current agent for saving
                save_agent = pool.get(current_agent_id)
                if save_agent:
                    perm_level, perm_preset, disabled_tools = get_permission_data(
                        save_agent
                    )
                    saved = serialize_session(
                        agent_id=current_agent_id,
                        messages=save_agent.context.messages,
                        system_prompt=save_agent.context.system_prompt or "",
                        system_prompt_path=get_system_prompt_path(),
                        working_directory=str(save_agent.services.get_cwd()),
                        permission_level=perm_level,
                        token_usage=save_agent.context.get_token_usage(),
                        provenance="user",
                        created_at=save_agent.created_at,
                        permission_preset=perm_preset,
                        disabled_tools=disabled_tools,
                        model_alias=get_model_alias(save_agent),
                    )
                    session_manager.save_last_session(saved, current_agent_id)
            except Exception as e:
                # Log but don't fail REPL for auto-save errors
                console.print(f"[dim red]Auto-save failed: {e}[/]")

        except KeyboardInterrupt:
            console.print("")
            console.print("Use /quit to exit.", style="dim")
            continue

        except EOFError:
            console.print("")
            console.print("Goodbye!", style="dim")
            break

    # Clean up resources
    # 1. Signal shutdown to stop the HTTP server
    main_agent.dispatcher.request_shutdown()

    # 2. Cancel the HTTP server task
    http_task.cancel()
    try:
        await http_task
    except (asyncio.CancelledError, OSError):
        # CancelledError: normal cancellation
        # OSError: server failed to start (e.g., port already in use)
        pass

    # 3. Delete the API key file
    token_manager.delete()

    # 4. Clear REPL connection state before destroying agents
    pool.set_repl_connected(current_agent_id, False)

    # 5. Destroy all agents (cleans up loggers)
    for agent_info in pool.list():
        await pool.destroy(agent_info["agent_id"])

    # 6. Close provider HTTP clients
    if shared and shared.provider_registry:
        await shared.provider_registry.aclose()

    # 7. Close MCP connections (prevents unclosed transport warnings on Windows)
    if shared and shared.mcp_registry:
        await shared.mcp_registry.close_all()


async def run_repl_client(url: str, agent_id: str, api_key: str | None = None) -> None:
    """Run REPL as client to a remote Nexus server.

    Args:
        url: Base URL of the server (e.g., http://127.0.0.1:8765)
        agent_id: ID of the agent to connect to
        api_key: Optional API key for authentication. If None, uses auto-discovery.
    """
    from nexus3.client import ClientError, NexusClient

    console = get_console()

    # Build agent URL
    agent_url = f"{url.rstrip('/')}/agent/{agent_id}"

    console.print("[bold]NEXUS3 Client[/]")
    console.print(f"Connecting to {agent_url}...")

    # Simple prompt session with styled input (no bottom toolbar for simplicity)
    lexer = SimpleLexer('class:input-field')
    style = Style.from_dict({
        'prompt': 'reverse',
        'input-field': 'reverse',
    })
    prompt_session: PromptSession[str] = PromptSession(
        lexer=lexer,
        style=style,
    )

    # Use provided API key if given, otherwise auto-discover
    try:
        if api_key:
            client_ctx = NexusClient(agent_url, api_key=api_key, timeout=300.0)
        else:
            client_ctx = NexusClient.with_auto_auth(agent_url, timeout=300.0)
    except ValueError as e:
        console.print(f"[red]Invalid URL:[/] {e}")
        return

    async with client_ctx as client:
        # Test connection
        try:
            status = await client.get_tokens()
            console.print(f"Connected. Tokens: {status.get('total', 0)}/{status.get('available', status.get('budget', 0))}")
        except ClientError as e:
            console.print(f"[red]Connection failed:[/] {e}")
            return

        console.print("Commands: /quit | /status")
        console.print("")

        while True:
            try:
                user_input = await prompt_session.prompt_async(
                    HTML("<style class='prompt'>> </style>")
                )

                if not user_input.strip():
                    continue

                # Handle local commands
                if user_input.strip() in ("/quit", "/q", "/exit"):
                    console.print("Disconnecting.", style="dim")
                    break

                if user_input.strip() == "/status":
                    try:
                        tokens = await client.get_tokens()
                        context = await client.get_context()
                        console.print(f"Tokens: {tokens}")
                        console.print(f"Context: {context}")
                    except ClientError as e:
                        console.print(f"[red]Error:[/] {e}")
                    continue

                # Send message to agent
                console.print("")  # Visual separation
                try:
                    result = await client.send(user_input)
                    if "content" in result:
                        console.print(result["content"])
                    elif "cancelled" in result:
                        console.print("[yellow]Request was cancelled[/]")
                    console.print("")  # Visual separation
                except ClientError as e:
                    console.print(f"[red]Error:[/] {e}")
                    console.print("")

            except KeyboardInterrupt:
                console.print("")
                console.print("Use /quit to exit.", style="dim")
                continue
            except EOFError:
                console.print("")
                console.print("Disconnecting.", style="dim")
                break


async def _run_connect_with_discovery(args: argparse.Namespace) -> None:
    """Run connect mode with server discovery.

    Discovers servers on candidate ports and shows the connect lobby for
    server/agent selection.

    Args:
        args: Parsed command line arguments including scan and api_key.
    """
    from nexus3.config.loader import load_config

    console = get_console()

    # Load config to get default port
    try:
        config = load_config()
        effective_port = config.server.port
    except NexusError:
        effective_port = 8765

    # Build candidate ports
    candidate_ports: set[int] = {effective_port, 8765}
    candidate_ports.update(discover_token_ports().keys())
    if args.scan:
        try:
            candidate_ports.update(parse_port_spec(args.scan))
        except ValueError as e:
            console.print(f"[red]Invalid port specification:[/] {e}")
            return

    # Discovery loop
    while True:
        servers = await discover_servers(sorted(candidate_ports))
        nexus_servers = [s for s in servers if s.detection == DetectionResult.NEXUS_SERVER]

        if not nexus_servers:
            console.print("[dim]No NEXUS3 servers found.[/]")
            console.print(f"[dim]Scanned ports: {sorted(candidate_ports)}[/]")
            return

        # Check if the default port already has a NEXUS server
        default_port_in_use = any(s.port == effective_port for s in nexus_servers)
        result = await show_connect_lobby(
            console, nexus_servers, effective_port, default_port_in_use=default_port_in_use
        )

        if result.action == ConnectAction.CONNECT:
            # Create agent first if requested
            if result.create_agent and result.agent_id:
                try:
                    from nexus3.client import NexusClient
                    server_url = result.server_url or f"http://127.0.0.1:{effective_port}"
                    client = NexusClient.with_auto_auth(
                        f"{server_url}/",
                        api_key=result.api_key or args.api_key,
                    )
                    await client.create_agent(result.agent_id)
                    console.print(f"[dim]Created agent: {result.agent_id}[/]")
                except Exception as e:
                    console.print(f"[red]Failed to create agent: {e}[/]")
                    return  # In connect mode, just exit on failure
            await run_repl_client(
                result.server_url or f"http://127.0.0.1:{effective_port}",
                result.agent_id or "main",
                api_key=result.api_key or args.api_key,
            )
            return

        elif result.action == ConnectAction.RESCAN:
            if result.scan_spec:
                try:
                    new_ports = parse_port_spec(result.scan_spec)
                    candidate_ports.update(new_ports)
                    console.print(f"[dim]Scanning {len(new_ports)} additional ports...[/]")
                except ValueError as e:
                    console.print(f"[red]Invalid port specification:[/] {e}")
            continue

        elif result.action == ConnectAction.MANUAL_URL:
            if result.server_url:
                await run_repl_client(
                    result.server_url,
                    result.agent_id or "main",
                    api_key=result.api_key or args.api_key,
                )
                return
            continue

        elif result.action == ConnectAction.QUIT:
            return

        else:
            # START_NEW_SERVER, SHUTDOWN_AND_REPLACE not applicable in pure connect mode
            console.print("[dim]This option is not available in connect mode.[/]")
            console.print("[dim]Use 'nexus3' without --connect to start a server.[/]")
            continue


def main() -> None:
    """Entry point for the NEXUS3 CLI."""
    import logging

    args = parse_args()

    # Configure logging based on verbosity
    log_level = logging.DEBUG if getattr(args, "verbose", False) else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        # Handle rpc subcommand group
        if args.command == "rpc":
            from nexus3.cli.client_commands import (
                cmd_cancel,
                cmd_compact,
                cmd_create,
                cmd_destroy,
                cmd_detect,
                cmd_list,
                cmd_send,
                cmd_shutdown,
                cmd_status,
            )

            rpc_cmd = args.rpc_command
            if rpc_cmd is None:
                print("Usage: nexus3 rpc <command>")
                print("Commands: detect, list, create, destroy, send, cancel, status, compact, shutdown")
                raise SystemExit(1)

            if rpc_cmd == "detect":
                exit_code = asyncio.run(cmd_detect(args.port))
            elif rpc_cmd == "list":
                exit_code = asyncio.run(cmd_list(args.port, args.api_key))
            elif rpc_cmd == "create":
                exit_code = asyncio.run(cmd_create(
                    args.agent_id,
                    args.port,
                    args.api_key,
                    args.preset,
                    args.cwd,
                    args.allowed_write_paths,
                    args.model,
                    args.message,
                    args.timeout,
                ))
            elif rpc_cmd == "destroy":
                exit_code = asyncio.run(cmd_destroy(args.agent_id, args.port, args.api_key))
            elif rpc_cmd == "send":
                exit_code = asyncio.run(
                    cmd_send(args.agent_id, args.content, args.port, args.api_key, args.timeout)
                )
            elif rpc_cmd == "cancel":
                exit_code = asyncio.run(
                    cmd_cancel(args.agent_id, args.request_id, args.port, args.api_key)
                )
            elif rpc_cmd == "status":
                exit_code = asyncio.run(cmd_status(args.agent_id, args.port, args.api_key))
            elif rpc_cmd == "compact":
                exit_code = asyncio.run(cmd_compact(args.agent_id, args.port, args.api_key))
            elif rpc_cmd == "shutdown":
                exit_code = asyncio.run(cmd_shutdown(args.port, args.api_key))
            else:
                print(f"Unknown rpc command: {rpc_cmd}")
                exit_code = 1
            raise SystemExit(exit_code)

        # Handle init-global command
        if args.init_global or args.init_global_force:
            from nexus3.cli.init_commands import init_global

            force = args.init_global_force
            success, message = init_global(force=force)
            print(message)
            raise SystemExit(0 if success else 1)

        # Handle connect mode (REPL as client)
        if args.connect is not None:
            if args.connect == "DISCOVER":
                # Show connect lobby to discover servers
                asyncio.run(_run_connect_with_discovery(args))
            else:
                # Direct connection to specified URL
                asyncio.run(run_repl_client(args.connect, args.agent, api_key=args.api_key))
            return

        # Handle serve mode
        if args.serve is not None:
            # Security: headless server mode requires NEXUS_DEV=1
            # This prevents scripts/malware from spinning up unattended servers
            if os.environ.get("NEXUS_DEV") != "1":
                print("Error: Headless server mode disabled for security.")
                print("Set NEXUS_DEV=1 to enable (development only).")
                print("For normal use, run 'nexus3' which starts an embedded server.")
                raise SystemExit(1)

            if args.reload:
                # Use watchfiles for auto-reload
                _run_with_reload(args)
            else:
                from nexus3.cli.serve import run_serve

                asyncio.run(run_serve(
                    port=args.serve,
                    verbose=args.verbose,
                    log_verbose=getattr(args, "log_verbose", False),
                    raw_log=args.raw_log,
                    log_dir=args.log_dir,
                ))
        else:
            # Default: interactive REPL
            if args.reload:
                print("--reload only works with --serve mode")
                return
            asyncio.run(run_repl(
                verbose=args.verbose,
                log_verbose=getattr(args, "log_verbose", False),
                raw_log=args.raw_log,
                log_dir=args.log_dir,
                resume=args.resume,
                fresh=args.fresh,
                session_name=args.session,
                template=args.template,
                model=args.model,
            ))
    except KeyboardInterrupt:
        # Handle Ctrl+C during startup
        pass


def _run_with_reload(args: argparse.Namespace) -> None:
    """Run serve mode with auto-reload using watchfiles."""
    try:
        import watchfiles
    except ImportError:
        print("Auto-reload requires watchfiles: pip install watchfiles")
        print("Or install dev dependencies: uv pip install -e '.[dev]'")
        return

    import sys
    from pathlib import Path

    # Find the nexus3 package directory to watch
    import nexus3
    watch_path = Path(nexus3.__file__).parent

    print(f"[reload] Watching {watch_path} for changes...")
    print(f"[reload] Starting server on port {args.serve}")
    print("")

    # Build the command to run
    cmd = [
        sys.executable, "-m", "nexus3",
        "--serve", str(args.serve),
    ]
    if args.verbose:
        cmd.append("--verbose")
    if getattr(args, "log_verbose", False):
        cmd.append("--log-verbose")
    if args.raw_log:
        cmd.append("--raw-log")
    if args.log_dir:
        cmd.extend(["--log-dir", str(args.log_dir)])

    # Run with watchfiles - restarts on any .py file change
    watchfiles.run_process(
        watch_path,
        target=cmd[0],
        args=cmd[1:],
        callback=lambda changes: print(f"[reload] Detected changes: {changes}"),
    )


if __name__ == "__main__":
    main()
