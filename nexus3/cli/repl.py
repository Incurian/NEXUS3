"""Async REPL with prompt-toolkit for NEXUS3.

This module provides the main interactive REPL for NEXUS3. It supports:

1. Unified mode (default): Starts an embedded HTTP server with the REPL.
   The REPL calls Session directly for rich streaming, while external clients
   can connect via HTTP.

2. Client mode (--connect): Connects to an existing NEXUS3 server.

3. Server mode (--serve): Headless HTTP server without REPL (in serve.py).

Architecture in unified mode:
    nexus3 (no flags)
    +-- detect_server(8765)
    |   +-- NEXUS_SERVER --> Error: use --connect
    |   +-- NO_SERVER --> Unified mode:
    |       +-- Create SharedComponents
    |       +-- Create AgentPool with "main" agent
    |       +-- Generate API key --> save to ~/.nexus3/server.key
    |       +-- Start HTTP server as background task
    |       +-- REPL loop calling main agent's Session directly
"""

import argparse
import asyncio
from contextvars import ContextVar
from pathlib import Path

from dotenv import load_dotenv
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from rich.live import Live

# Context variable to store the current Live display for pausing during confirmation
_current_live: ContextVar[Live | None] = ContextVar("_current_live", default=None)

from nexus3.cli import repl_commands
from nexus3.cli.keys import KeyMonitor, pause_key_monitor, resume_key_monitor
from nexus3.cli.lobby import LobbyChoice, show_lobby
from nexus3.cli.whisper import WhisperMode
from nexus3.commands import core as unified_cmd
from nexus3.commands.protocol import CommandContext, CommandOutput
from nexus3.core.permissions import ConfirmationResult
from nexus3.commands.protocol import CommandResult as CmdResult
from nexus3.config.loader import load_config
from nexus3.context import PromptLoader
from nexus3.core.encoding import configure_stdio
from nexus3.core.errors import NexusError
from nexus3.core.types import ToolCall
from nexus3.display import Activity, StreamingDisplay, get_console
from nexus3.display.streaming import ToolState
from nexus3.display.theme import load_theme
from nexus3.core.permissions import load_custom_presets_from_config
from nexus3.provider.openrouter import OpenRouterProvider
from nexus3.rpc.auth import ServerKeyManager
from nexus3.rpc.detection import DetectionResult, detect_server
from nexus3.rpc.global_dispatcher import GlobalDispatcher
from nexus3.rpc.http import DEFAULT_PORT, run_http_server
from nexus3.rpc.pool import AgentConfig, AgentPool, SharedComponents, generate_temp_id
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


def format_tool_params(arguments: dict, max_length: int = 70) -> str:
    """Format tool arguments as a truncated string for display.

    Prioritizes path/file arguments (shown first, not truncated individually).
    Other arguments are truncated if needed.

    Args:
        arguments: Tool call arguments dictionary.
        max_length: Maximum length of output string (default 70).

    Returns:
        Formatted string like 'path=/foo/bar, content="hello..."' truncated to max_length.
    """
    if not arguments:
        return ""

    # Priority keys shown first and not individually truncated
    priority_keys = ("path", "file", "file_path", "directory", "dir", "cwd", "agent_id")
    parts = []

    # Add priority arguments first (full value)
    for key in priority_keys:
        if key in arguments and arguments[key]:
            value = str(arguments[key])
            parts.append(f"{key}={value}")

    # Add remaining arguments (truncated if needed)
    for key, value in arguments.items():
        if key in priority_keys or value is None:
            continue
        str_val = str(value)
        # Truncate long non-priority values
        if len(str_val) > 30:
            str_val = str_val[:27] + "..."
        # Quote strings that contain spaces
        if isinstance(value, str) and " " in str_val:
            str_val = f'"{str_val}"'
        parts.append(f"{key}={str_val}")

    result = ", ".join(parts)

    # Truncate overall result (but this should rarely happen with priority keys first)
    if len(result) > max_length:
        result = result[: max_length - 3] + "..."

    return result


async def confirm_tool_action(tool_call: ToolCall, target_path: Path | None) -> ConfirmationResult:
    """Prompt user for confirmation of destructive action with allow once/always options.

    This callback is invoked by Session when a tool requires user confirmation
    (based on permission level). It shows different options based on tool type:

    For write operations (write_file, edit_file):
        [1] Allow once
        [2] Allow always for this file
        [3] Allow always in this directory
        [4] Deny

    For execution operations (bash, run_python):
        [1] Allow once
        [2] Allow always in current directory
        [3] Allow always (global)
        [4] Deny

    Args:
        tool_call: The tool call requiring confirmation.
        target_path: The path being accessed (for write ops) or None.

    Returns:
        ConfirmationResult indicating user's decision.
    """
    console = get_console()
    tool_name = tool_call.name

    # Determine tool type for appropriate prompting
    is_exec_tool = tool_name in ("bash", "run_python")
    is_nexus_tool = tool_name.startswith("nexus_")
    is_mcp_tool = tool_name.startswith("mcp_")

    # Pause the Live display during confirmation to prevent visual conflicts
    live = _current_live.get()
    if live is not None:
        live.stop()

    # Pause KeyMonitor so it stops consuming stdin and restores terminal mode
    pause_key_monitor()
    # Give KeyMonitor time to pause and restore terminal
    await asyncio.sleep(0.15)

    try:
        # Build description based on tool type
        if is_mcp_tool:
            # Extract server name from mcp_{server}_{tool} format
            parts = tool_name.split("_", 2)
            server_name = parts[1] if len(parts) > 1 else "unknown"
            args_preview = str(tool_call.arguments)[:60]
            if len(str(tool_call.arguments)) > 60:
                args_preview += "..."
            console.print(f"\n[yellow]Allow MCP tool '{tool_name}'?[/]")
            console.print(f"  [dim]Server:[/] {server_name}")
            console.print(f"  [dim]Arguments:[/] {args_preview}")
        elif is_exec_tool:
            cwd = tool_call.arguments.get("cwd", str(Path.cwd()))
            command = tool_call.arguments.get("command", tool_call.arguments.get("code", ""))
            preview = command[:50] + "..." if len(command) > 50 else command
            console.print(f"\n[yellow]Execute {tool_name}?[/]")
            console.print(f"  [dim]Command:[/] {preview}")
            console.print(f"  [dim]Directory:[/] {cwd}")
        elif is_nexus_tool:
            # Nexus tools use agent_id instead of path
            agent_id = tool_call.arguments.get("agent_id", "unknown")
            console.print(f"\n[yellow]Allow {tool_name}?[/]")
            console.print(f"  [dim]Agent:[/] {agent_id}")
        else:
            path_str = str(target_path) if target_path else tool_call.arguments.get("path", "unknown")
            console.print(f"\n[yellow]Allow {tool_name}?[/]")
            console.print(f"  [dim]Path:[/] {path_str}")

        # Show options based on tool type
        console.print()
        if is_mcp_tool:
            console.print("  [cyan][1][/] Allow once")
            console.print("  [cyan][2][/] Allow this tool always (this session)")
            console.print("  [cyan][3][/] Allow all tools from this server (this session)")
            console.print("  [cyan][4][/] Deny")
        elif is_exec_tool:
            console.print("  [cyan][1][/] Allow once")
            console.print("  [cyan][2][/] Allow always in this directory")
            console.print("  [cyan][3][/] Allow always (global)")
            console.print("  [cyan][4][/] Deny")
        else:
            console.print("  [cyan][1][/] Allow once")
            console.print("  [cyan][2][/] Allow always for this file")
            console.print("  [cyan][3][/] Allow always in this directory")
            console.print("  [cyan][4][/] Deny")

        # Use asyncio.to_thread for blocking input to allow event loop to continue
        def get_input() -> str:
            try:
                return console.input("\n[dim]Choice [1-4]:[/] ").strip()
            except (EOFError, KeyboardInterrupt):
                return ""

        response = await asyncio.to_thread(get_input)

        if response == "1":
            return ConfirmationResult.ALLOW_ONCE
        elif response == "2":
            if is_mcp_tool:
                # "Allow this tool always" - we use ALLOW_FILE to signal tool-level
                return ConfirmationResult.ALLOW_FILE
            elif is_exec_tool:
                return ConfirmationResult.ALLOW_EXEC_CWD
            else:
                return ConfirmationResult.ALLOW_FILE
        elif response == "3":
            if is_mcp_tool:
                # "Allow all tools from this server"
                return ConfirmationResult.ALLOW_EXEC_GLOBAL
            elif is_exec_tool:
                return ConfirmationResult.ALLOW_EXEC_GLOBAL
            else:
                return ConfirmationResult.ALLOW_WRITE_DIRECTORY
        else:
            return ConfirmationResult.DENY

    finally:
        # Resume KeyMonitor (restores cbreak mode)
        resume_key_monitor()

        # Resume Live display after confirmation
        if live is not None:
            live.start()


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="nexus3",
        description="AI-powered CLI agent framework",
    )

    # Add subparsers for commands
    subparsers = parser.add_subparsers(dest="command")

    # ==========================================================================
    # RPC subcommand group - all programmatic operations
    # ==========================================================================
    rpc_parser = subparsers.add_parser(
        "rpc",
        help="JSON-RPC commands for programmatic access",
        description="Commands for programmatic interaction with NEXUS3 servers.",
    )
    rpc_subparsers = rpc_parser.add_subparsers(dest="rpc_command")

    # Common argument helpers
    def add_api_key_arg(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--api-key",
            dest="api_key",
            help="API key for authentication (auto-discovers from env/files if not provided)",
        )

    def add_port_arg(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--port", "-p",
            type=int,
            default=8765,
            help="Server port (default: 8765)",
        )

    # rpc detect - Check if server is running
    detect_parser = rpc_subparsers.add_parser(
        "detect",
        help="Check if a NEXUS3 server is running",
    )
    add_port_arg(detect_parser)

    # rpc list - List agents (auto-starts server)
    list_parser = rpc_subparsers.add_parser(
        "list",
        help="List all agents (auto-starts server)",
    )
    add_port_arg(list_parser)
    add_api_key_arg(list_parser)

    # rpc create - Create agent (auto-starts server)
    create_parser = rpc_subparsers.add_parser(
        "create",
        help="Create an agent (auto-starts server)",
    )
    create_parser.add_argument("agent_id", help="ID for the new agent")
    create_parser.add_argument(
        "--preset",
        choices=["trusted", "sandboxed", "worker"],
        default="sandboxed",
        help="Permission preset (default: sandboxed)"
    )
    create_parser.add_argument(
        "--cwd",
        help="Working directory / sandbox root for the agent"
    )
    create_parser.add_argument(
        "--write-path",
        action="append",
        dest="allowed_write_paths",
        metavar="PATH",
        help="Path where writes are allowed (can be repeated)"
    )
    create_parser.add_argument(
        "--model", "-m",
        metavar="NAME",
        help="Model name/alias to use (from config.models or full model ID)"
    )
    add_port_arg(create_parser)
    add_api_key_arg(create_parser)

    # rpc destroy - Destroy agent
    destroy_parser = rpc_subparsers.add_parser(
        "destroy",
        help="Destroy an agent",
    )
    destroy_parser.add_argument("agent_id", help="ID of agent to destroy")
    add_port_arg(destroy_parser)
    add_api_key_arg(destroy_parser)

    # rpc send - Send message to agent
    send_parser = rpc_subparsers.add_parser(
        "send",
        help="Send message to an agent",
    )
    send_parser.add_argument("agent_id", help="Agent ID to send to")
    send_parser.add_argument("content", help="Message to send")
    send_parser.add_argument(
        "--timeout", "-t",
        type=float,
        default=120.0,
        help="Request timeout in seconds (default: 120)",
    )
    add_port_arg(send_parser)
    add_api_key_arg(send_parser)

    # rpc cancel - Cancel request
    cancel_parser = rpc_subparsers.add_parser(
        "cancel",
        help="Cancel an in-progress request",
    )
    cancel_parser.add_argument("agent_id", help="Agent ID")
    cancel_parser.add_argument("request_id", help="Request ID to cancel")
    add_port_arg(cancel_parser)
    add_api_key_arg(cancel_parser)

    # rpc status - Get agent status
    status_parser = rpc_subparsers.add_parser(
        "status",
        help="Get agent status (tokens + context)",
    )
    status_parser.add_argument("agent_id", help="Agent ID")
    add_port_arg(status_parser)
    add_api_key_arg(status_parser)

    # rpc shutdown - Shutdown server
    shutdown_parser = rpc_subparsers.add_parser(
        "shutdown",
        help="Shutdown the server",
    )
    add_port_arg(shutdown_parser)
    add_api_key_arg(shutdown_parser)

    # ==========================================================================
    # Main mode flags (only apply when no subcommand)
    # ==========================================================================
    parser.add_argument(
        "--serve",
        nargs="?",
        const=8765,
        type=int,
        metavar="PORT",
        help="Run HTTP JSON-RPC server (default port: 8765)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging (thinking traces, timing)",
    )
    parser.add_argument(
        "--raw-log",
        action="store_true",
        help="Enable raw API JSON logging",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path(".nexus3/logs"),
        help="Directory for session logs (default: .nexus3/logs)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Auto-reload on code changes (requires watchfiles, serve mode only)",
    )
    # Session startup flags (skip lobby)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume last session automatically (skip lobby)",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Start fresh temp session (skip lobby)",
    )
    parser.add_argument(
        "--session",
        metavar="NAME",
        help="Load specific saved session by name (skip lobby)",
    )
    parser.add_argument(
        "--template",
        metavar="PATH",
        type=Path,
        help="Custom system prompt file for fresh sessions (used with --fresh)",
    )
    parser.add_argument(
        "--model", "-m",
        metavar="NAME",
        help="Model name/alias to use (from config.models or full model ID)",
    )
    parser.add_argument(
        "--connect",
        metavar="URL",
        nargs="?",
        const="http://localhost:8765",
        help="Connect to a Nexus server as client (default: http://localhost:8765)",
    )
    parser.add_argument(
        "--agent",
        default="main",
        help="Agent ID to connect to (default: main, requires --connect)",
    )
    return parser.parse_args()


async def run_repl(
    verbose: bool = False,
    raw_log: bool = False,
    log_dir: Path | None = None,
    port: int = DEFAULT_PORT,
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
        verbose: Enable verbose logging stream.
        raw_log: Enable raw API logging stream.
        log_dir: Directory for session logs.
        port: Port for embedded HTTP server (default: 8765).
        resume: Resume last session automatically (skip lobby).
        fresh: Start fresh temp session (skip lobby).
        session_name: Load specific saved session by name (skip lobby).
        template: Custom system prompt file for fresh sessions.
        model: Model name/alias to use (from config.models or full model ID).
    """
    console = get_console()
    theme = load_theme()

    # Check for existing server on the port
    detection_result = await detect_server(port)
    if detection_result == DetectionResult.NEXUS_SERVER:
        # Server already running - auto-connect to it
        console.print(f"[dim]Server already running on port {port}, connecting...[/]")
        try:
            await run_repl_client(f"http://localhost:{port}", "main")
        except Exception as e:
            console.print(f"\n[yellow]Tip:[/] If connection failed, try killing the old server:")
            console.print(f"  [dim]lsof -i :{port} | awk 'NR>1 {{print $2}}' | xargs kill[/]")
            console.print(f"  [dim]Then run 'nexus' again.[/]")
        return
    elif detection_result == DetectionResult.OTHER_SERVICE:
        console.print(f"[red]Error:[/] Port {port} is already in use by another service")
        return

    # Load configuration
    try:
        config = load_config()
    except NexusError as e:
        console.print(f"[red]Error:[/] {e.message}")
        return

    # Create provider (shared across all agents)
    # Resolve model alias to actual model ID before creating provider
    try:
        from nexus3.config.schema import ProviderConfig
        resolved = config.resolve_model()
        provider_config = ProviderConfig(
            type=config.provider.type,
            api_key_env=config.provider.api_key_env,
            model=resolved.model_id,  # Use resolved ID, not alias
            base_url=config.provider.base_url,
            context_window=resolved.context_window,
            reasoning=resolved.reasoning,
        )
        provider = OpenRouterProvider(provider_config)
    except NexusError as e:
        console.print(f"[red]Error:[/] {e.message}")
        return

    # Configure logging streams based on CLI flags
    streams = LogStream.CONTEXT  # Always on for basic functionality
    if verbose:
        streams |= LogStream.VERBOSE
    if raw_log:
        streams |= LogStream.RAW

    # Base log directory
    base_log_dir = log_dir or Path(".nexus3/logs")

    # Create prompt loader (shared)
    prompt_loader = PromptLoader()
    loaded_prompt = prompt_loader.load()

    # Load custom presets from config
    custom_presets = load_custom_presets_from_config(
        {k: v.model_dump() for k, v in config.permissions.presets.items()}
    )

    # Create shared components for the AgentPool
    shared = SharedComponents(
        config=config,
        provider=provider,
        prompt_loader=prompt_loader,
        base_log_dir=base_log_dir,
        log_streams=streams,
        custom_presets=custom_presets,
    )

    # Create agent pool
    pool = AgentPool(shared)

    # Create global dispatcher for agent management
    global_dispatcher = GlobalDispatcher(pool)

    # Generate and save API key
    key_manager = ServerKeyManager(port=port)
    api_key = key_manager.generate_and_save()

    # Create session manager for auto-restore of saved sessions
    session_manager = SessionManager()

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
            key_manager.delete()
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
            key_manager.delete()
            return
    else:
        # Show lobby
        lobby_result = await show_lobby(session_manager, console)
        if lobby_result.choice == LobbyChoice.QUIT:
            key_manager.delete()
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
        # Create with model if specified
        agent_config = AgentConfig(model=model) if model else None
        main_agent = await pool.create(agent_id=agent_name, config=agent_config)
        if template:
            # Load custom prompt from template
            try:
                content = template.read_text(encoding="utf-8")
                main_agent.context.set_system_prompt(content)
            except OSError as e:
                console.print(f"[red]Error loading template: {e}[/]")
                key_manager.delete()
                await pool.destroy(agent_name)
                return

    # Wire up confirmation callback for main agent
    main_agent.session.on_confirm = confirm_tool_action

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
        """Get the system prompt path from the prompt loader."""
        # Prefer project path (more specific) over personal path
        path = shared.prompt_loader.project_path or shared.prompt_loader.personal_path
        return str(path) if path else None

    # Update last-session immediately after startup (so resume works after quit)
    try:
        perm_level, perm_preset, disabled_tools = get_permission_data(main_agent)
        startup_saved = serialize_session(
            agent_id=agent_name,
            messages=main_agent.context.messages,
            system_prompt=main_agent.context.system_prompt or "",
            system_prompt_path=get_system_prompt_path(),
            working_directory=os.getcwd(),
            permission_level=perm_level,
            token_usage=main_agent.context.get_token_usage(),
            provenance="user",
            created_at=main_agent.created_at,
            permission_preset=perm_preset,
            disabled_tools=disabled_tools,
        )
        session_manager.save_last_session(startup_saved, agent_name)
    except Exception:
        pass  # Don't fail on save errors

    # Phase 6: Agent management state
    current_agent_id = agent_name
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
                    working_directory=os.getcwd(),
                    permission_level=perm_level,
                    token_usage=agent.context.get_token_usage(),
                    provenance="user",
                    created_at=agent.created_at,
                    permission_preset=perm_preset,
                    disabled_tools=disabled_tools,
                )
                session_manager.save_last_session(saved, agent_id)
        except Exception:
            pass  # Don't fail on save errors

    # Start HTTP server as a background task
    http_task = asyncio.create_task(
        run_http_server(
            pool, global_dispatcher, port, api_key=api_key,
            session_manager=session_manager
        ),
        name="http_server",
    )

    # Get the session from the main agent for direct REPL access
    session = main_agent.session
    logger = main_agent.logger

    # Display for streaming phases (created before session for callback)
    display = StreamingDisplay(theme)

    # Callback when tool call is detected in stream (updates live display)
    def on_tool_call(name: str, tool_id: str) -> None:
        display.add_tool_call(name, tool_id)

    # Track if we've printed thinking for this turn
    thinking_printed = False

    def print_thinking_if_needed() -> None:
        """Print accumulated thinking time once (if any)."""
        nonlocal thinking_printed
        if thinking_printed:
            return
        duration = display.get_total_thinking_duration()
        if duration > 0:
            thinking_printed = True
            # Always show "for Ns", minimum 1s
            display_duration = max(1, int(duration))
            console.print(f"  [dim cyan]●[/] [dim]Thought for {display_duration}s[/]")

    # Callback when reasoning state changes
    def on_reasoning(is_reasoning: bool) -> None:
        if is_reasoning:
            display.start_thinking()
        else:
            # Just end thinking, accumulate time - don't print yet
            display.end_thinking()

    # Batch callbacks for tool execution
    def on_batch_start(tool_calls: tuple) -> None:
        """Initialize display with all tools as pending."""
        # Print any accumulated thinking BEFORE tool calls
        print_thinking_if_needed()

        tools = []
        for tc in tool_calls:
            # Format all parameters (path/file prioritized, others truncated)
            params = format_tool_params(tc.arguments)
            tools.append((tc.name, tc.id, params))
        display.start_batch(tools)

    def on_tool_active(name: str, tool_id: str) -> None:
        """Mark tool as actively executing in display."""
        display.set_tool_active(tool_id)

    def on_batch_progress(name: str, tool_id: str, success: bool, error: str) -> None:
        """Update display as each tool completes."""
        display.set_tool_complete(tool_id, success, error)

    def on_batch_halt() -> None:
        """Mark remaining tools as halted when sequence stops on error."""
        display.halt_remaining_tools()

    def on_batch_complete() -> None:
        """Print all results to scrollback when batch finishes."""
        for tool in display.get_batch_results():
            if tool.state == ToolState.SUCCESS:
                gumball = "[green]●[/]"
                suffix = ""
            elif tool.state == ToolState.HALTED:
                gumball = "[dark_orange]●[/]"
                suffix = " [dark_orange](halted)[/]"
            elif tool.state == ToolState.CANCELLED:
                gumball = "[bright_yellow]●[/]"
                suffix = " [bright_yellow](cancelled)[/]"
            else:  # ERROR
                gumball = "[red]●[/]"
                suffix = " [red](error)[/]"

            # Tool name with params
            if tool.params:
                console.print(f"  {gumball} {tool.name}: {tool.params}{suffix}")
            else:
                console.print(f"  {gumball} {tool.name}{suffix}")

            # Error message on next line (first 70 chars)
            if tool.state == ToolState.ERROR and tool.error:
                error_preview = tool.error[:70] + ("..." if len(tool.error) > 70 else "")
                console.print(f"      [red dim]{error_preview}[/]")
        display.clear_tools()

    # Set callbacks on the session for REPL streaming
    # (Session is created by AgentPool without callbacks, so we set them here)
    session.on_tool_call = on_tool_call
    session.on_reasoning = on_reasoning
    session.on_batch_start = on_batch_start
    session.on_tool_active = on_tool_active
    session.on_batch_progress = on_batch_progress
    session.on_batch_halt = on_batch_halt
    session.on_batch_complete = on_batch_complete

    # Print welcome message
    console.print("[bold]NEXUS3 v0.1.0[/bold]")
    console.print(f"Agent: {current_agent_id}", style="dim")
    console.print(f"Session: {logger.session_dir}", style="dim")
    console.print(f"Server: http://localhost:{port}", style="dim")
    if loaded_prompt.personal_path:
        console.print(f"Personal: {loaded_prompt.personal_path}", style="dim")
    if loaded_prompt.project_path:
        console.print(f"Project: {loaded_prompt.project_path}", style="dim")
    console.print("Commands: /help | ESC to cancel", style="dim")
    console.print("")

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

    # Style to remove default toolbar highlight
    prompt_style = Style.from_dict({
        "bottom-toolbar": "noreverse",
    })

    # Create prompt session with bottom toolbar
    prompt_session: PromptSession[str] = PromptSession(
        bottom_toolbar=get_toolbar,
        style=prompt_style,
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

        ctx = make_ctx()

        # REPL-only commands
        if cmd_name in ("quit", "exit", "q"):
            return await repl_commands.cmd_quit(ctx)
        elif cmd_name == "help":
            return await repl_commands.cmd_help(ctx)
        elif cmd_name == "clear":
            return await repl_commands.cmd_clear(ctx)
        elif cmd_name == "agent":
            return await repl_commands.cmd_agent(ctx, cmd_args or None)
        elif cmd_name == "whisper":
            if not cmd_args:
                return CommandOutput.error("Usage: /whisper <agent>")
            return await repl_commands.cmd_whisper(ctx, whisper, cmd_args)
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

        # Unified commands (work in both CLI and REPL)
        elif cmd_name == "list":
            return await unified_cmd.cmd_list(ctx)
        elif cmd_name == "create":
            if not cmd_args:
                return CommandOutput.error("Usage: /create <name> [--perm]")
            create_parts = cmd_args.split()
            name = create_parts[0]
            perm = "trusted"
            for p in create_parts[1:]:
                if p.lower() in ("--yolo", "-y"):
                    perm = "yolo"
                elif p.lower() in ("--trusted", "-t"):
                    perm = "trusted"
                elif p.lower() in ("--sandboxed", "-s"):
                    perm = "sandboxed"
                elif p.lower() in ("--worker", "-w"):
                    perm = "worker"
            return await unified_cmd.cmd_create(ctx, name, perm)
        elif cmd_name == "destroy":
            if not cmd_args:
                return CommandOutput.error("Usage: /destroy <name>")
            return await unified_cmd.cmd_destroy(ctx, cmd_args)
        elif cmd_name == "send":
            send_parts = cmd_args.split(None, 1)
            if len(send_parts) < 2:
                return CommandOutput.error("Usage: /send <agent> <message>")
            return await unified_cmd.cmd_send(ctx, send_parts[0], send_parts[1])
        elif cmd_name == "status":
            return await unified_cmd.cmd_status(ctx, cmd_args or None)
        elif cmd_name == "cancel":
            cancel_parts = cmd_args.split() if cmd_args else []
            agent_id_arg = cancel_parts[0] if cancel_parts else None
            req_id = cancel_parts[1] if len(cancel_parts) > 1 else None
            return await unified_cmd.cmd_cancel(ctx, agent_id_arg, req_id)
        elif cmd_name == "save":
            return await unified_cmd.cmd_save(ctx, cmd_args or None)
        elif cmd_name == "clone":
            clone_parts = cmd_args.split()
            if len(clone_parts) != 2:
                return CommandOutput.error("Usage: /clone <src> <dest>")
            return await unified_cmd.cmd_clone(ctx, clone_parts[0], clone_parts[1])
        elif cmd_name == "rename":
            rename_parts = cmd_args.split()
            if len(rename_parts) != 2:
                return CommandOutput.error("Usage: /rename <old> <new>")
            return await unified_cmd.cmd_rename(ctx, rename_parts[0], rename_parts[1])
        elif cmd_name == "delete":
            if not cmd_args:
                return CommandOutput.error("Usage: /delete <name>")
            return await unified_cmd.cmd_delete(ctx, cmd_args)
        elif cmd_name == "shutdown":
            return await unified_cmd.cmd_shutdown(ctx)

        # Unknown command
        return CommandOutput.error(
            f"Unknown command: /{cmd_name}. Use /help for available commands."
        )

    # Main REPL loop
    while True:
        try:
            # Dynamic prompt based on whisper mode
            if whisper.is_active():
                prompt_text = f"{whisper.target_agent_id}> "
            else:
                prompt_text = "> "
            user_input = await prompt_session.prompt_async(prompt_text)

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
                            current_agent_id = new_id
                            session = new_agent.session
                            logger = new_agent.logger
                            # Re-attach callbacks
                            session.on_tool_call = on_tool_call
                            session.on_reasoning = on_reasoning
                            session.on_batch_start = on_batch_start
                            session.on_tool_active = on_tool_active
                            session.on_batch_progress = on_batch_progress
                            session.on_batch_halt = on_batch_halt
                            session.on_batch_complete = on_batch_complete
                            session.on_confirm = confirm_tool_action
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
                                        new_agent.session.on_confirm = confirm_tool_action
                                        restored_msgs = deserialize_messages(saved.messages)
                                        for msg in restored_msgs:
                                            new_agent.context._messages.append(msg)
                                        console.print(
                                            f"Restored session: {agent_name_to_restore} "
                                            f"({len(restored_msgs)} messages)",
                                            style="dim green",
                                        )
                                        # Switch to restored agent
                                        current_agent_id = agent_name_to_restore
                                        session = new_agent.session
                                        logger = new_agent.logger
                                        session.on_tool_call = on_tool_call
                                        session.on_reasoning = on_reasoning
                                        session.on_batch_start = on_batch_start
                                        session.on_tool_active = on_tool_active
                                        session.on_batch_progress = on_batch_progress
                                        session.on_batch_halt = on_batch_halt
                                        session.on_batch_complete = on_batch_complete
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
                                try:
                                    # Create agent with permission preset
                                    agent_config = AgentConfig(preset=permission_to_use)
                                    new_agent = await pool.create(
                                        agent_id=agent_name_to_create,
                                        config=agent_config,
                                    )
                                    # Wire up confirmation callback
                                    new_agent.session.on_confirm = confirm_tool_action
                                    console.print(
                                        f"Created agent: {agent_name_to_create}",
                                        style="dim green",
                                    )

                                    if action == "prompt_create":
                                        # Switch to the new agent
                                        current_agent_id = agent_name_to_create
                                        session = new_agent.session
                                        logger = new_agent.logger
                                        session.on_tool_call = on_tool_call
                                        session.on_reasoning = on_reasoning
                                        session.on_batch_start = on_batch_start
                                        session.on_tool_active = on_tool_active
                                        session.on_batch_progress = on_batch_progress
                                        session.on_batch_halt = on_batch_halt
                                        session.on_batch_complete = on_batch_complete
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

            # Overwrite prompt_toolkit's plain input with highlighted version
            # Move cursor up one line and overwrite
            console.print("\033[A\033[K", end="")  # Up one line, clear to end
            console.print(f"[reverse] {prompt_text}{user_input} [/reverse]")
            console.print("")  # Blank line after for visual separation

            # Reset display for new response and clear error/thinking state
            display.reset()
            display.clear_error_state()
            display.clear_thinking_duration()
            thinking_printed = False
            toolbar_has_errors = False
            display.set_activity(Activity.WAITING)
            display.start_activity_timer()

            # Streaming task that can be cancelled
            stream_task: asyncio.Task[None] | None = None
            was_cancelled = False

            def on_cancel(
                d: StreamingDisplay = display,
                get_task: object = lambda: stream_task,
            ) -> None:
                nonlocal was_cancelled
                was_cancelled = True
                d.cancel_all_tools()
                task = get_task()  # type: ignore[operator]
                if task is not None:
                    task.cancel()

            async def do_stream(
                d: StreamingDisplay = display,
                inp: str = user_input,
                target_sess: object = active_session,
            ) -> None:
                async for chunk in target_sess.send(inp):  # type: ignore[union-attr]
                    if d.activity == Activity.WAITING:
                        d.set_activity(Activity.RESPONDING)
                    d.add_chunk(chunk)

            # Use Live ONLY during streaming (animation works here)
            with Live(display, console=console, refresh_per_second=10, transient=True) as live:
                # Store live reference for confirmation callback to pause/resume
                token = _current_live.set(live)
                try:
                    async with KeyMonitor(on_escape=on_cancel):
                        stream_task = asyncio.create_task(do_stream())
                        # Refresh loop while streaming
                        while not stream_task.done():
                            live.refresh()
                            await asyncio.sleep(0.1)
                        # Get any exception from the task
                        try:
                            stream_task.result()
                        except asyncio.CancelledError:
                            pass  # Cancelled by ESC

                except NexusError as e:
                    console.print(f"[red]Error:[/] {e.message}")
                    console.print("")  # Visual separation after error
                    display.mark_error()
                finally:
                    # Clear live reference when exiting Live context
                    _current_live.reset(token)

            # Update toolbar error state
            if display.had_errors:
                toolbar_has_errors = True

            # Print cancelled tools to scrollback and queue for next send
            if was_cancelled and display.get_batch_results():
                # Collect cancelled tools for next send
                cancelled_tools = [
                    (tool.tool_id, tool.name)
                    for tool in display.get_batch_results()
                    if tool.state == ToolState.CANCELLED
                ]
                if cancelled_tools:
                    active_session.add_cancelled_tools(cancelled_tools)

                on_batch_complete()

            # Print accumulated thinking time (once, before response)
            print_thinking_if_needed()

            # After Live exits, print the final response
            if display.response:
                console.print("")  # Visual separation before response
                console.print(display.response)
                console.print("")  # Visual separation after response

            # Show completion status
            if was_cancelled:
                console.print("[bright_yellow]● Cancelled by User[/]")
                console.print("")  # Visual separation after cancel

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
                        working_directory=os.getcwd(),
                        permission_level=perm_level,
                        token_usage=save_agent.context.get_token_usage(),
                        provenance="user",
                        created_at=save_agent.created_at,
                        permission_preset=perm_preset,
                        disabled_tools=disabled_tools,
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
    except asyncio.CancelledError:
        pass

    # 3. Delete the API key file
    key_manager.delete()

    # 4. Destroy all agents (cleans up loggers)
    for agent_info in pool.list():
        await pool.destroy(agent_info["agent_id"])


async def run_repl_client(url: str, agent_id: str) -> None:
    """Run REPL as client to a remote Nexus server.

    Args:
        url: Base URL of the server (e.g., http://localhost:8765)
        agent_id: ID of the agent to connect to
    """
    from nexus3.client import ClientError, NexusClient

    console = get_console()

    # Build agent URL
    agent_url = f"{url.rstrip('/')}/agent/{agent_id}"

    console.print("[bold]NEXUS3 Client[/]")
    console.print(f"Connecting to {agent_url}...")

    # Simple prompt session (no bottom toolbar for simplicity)
    prompt_session: PromptSession[str] = PromptSession()

    async with NexusClient.with_auto_auth(agent_url, timeout=300.0) as client:
        # Test connection
        try:
            status = await client.get_tokens()
            console.print(f"Connected. Tokens: {status.get('total', 0)}/{status.get('budget', 0)}")
        except ClientError as e:
            console.print(f"[red]Connection failed:[/] {e}")
            return

        console.print("Commands: /quit | /status")
        console.print("")

        while True:
            try:
                user_input = await prompt_session.prompt_async("> ")

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


def main() -> None:
    """Entry point for the NEXUS3 CLI."""
    args = parse_args()
    try:
        # Handle rpc subcommand group
        if args.command == "rpc":
            from nexus3.cli.client_commands import (
                cmd_cancel,
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
                print("Commands: detect, list, create, destroy, send, cancel, status, shutdown")
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
            elif rpc_cmd == "shutdown":
                exit_code = asyncio.run(cmd_shutdown(args.port, args.api_key))
            else:
                print(f"Unknown rpc command: {rpc_cmd}")
                exit_code = 1
            raise SystemExit(exit_code)

        # Handle connect mode (REPL as client)
        if args.connect is not None:
            asyncio.run(run_repl_client(args.connect, args.agent))
            return

        # Handle serve mode
        if args.serve is not None:
            if args.reload:
                # Use watchfiles for auto-reload
                _run_with_reload(args)
            else:
                from nexus3.cli.serve import run_serve

                asyncio.run(run_serve(
                    port=args.serve,
                    verbose=args.verbose,
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
