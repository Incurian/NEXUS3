"""Async REPL with prompt-toolkit for NEXUS3."""

import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from rich.live import Live

from nexus3.cli.commands import CommandResult, handle_command, parse_command
from nexus3.cli.keys import KeyMonitor
from nexus3.config.loader import load_config
from nexus3.context import ContextConfig, ContextManager, PromptLoader
from nexus3.core.encoding import configure_stdio
from nexus3.core.errors import NexusError
from nexus3.display import Activity, StreamingDisplay, get_console
from nexus3.display.streaming import ToolState
from nexus3.display.theme import load_theme
from nexus3.provider.openrouter import OpenRouterProvider
from nexus3.session import LogConfig, LogStream, Session, SessionLogger
from nexus3.skill import ServiceContainer, SkillRegistry
from nexus3.skill.builtin import register_builtin_skills

# Configure UTF-8 at module load
configure_stdio()

# Load .env file if present
load_dotenv()


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="nexus3",
        description="AI-powered CLI agent framework",
    )

    # Add subparsers for client commands
    subparsers = parser.add_subparsers(dest="command")

    # send command
    send_parser = subparsers.add_parser("send", help="Send message to a Nexus agent")
    send_parser.add_argument("url", help="Agent URL (e.g., http://localhost:8765)")
    send_parser.add_argument("content", help="Message to send")
    send_parser.add_argument(
        "--request-id", dest="request_id", help="Optional request ID for tracking"
    )

    # cancel command
    cancel_parser = subparsers.add_parser("cancel", help="Cancel an in-progress request")
    cancel_parser.add_argument("url", help="Agent URL")
    cancel_parser.add_argument("request_id", help="Request ID to cancel")

    # status command
    status_parser = subparsers.add_parser("status", help="Get agent status (tokens + context)")
    status_parser.add_argument("url", help="Agent URL")

    # shutdown command
    shutdown_parser = subparsers.add_parser("shutdown", help="Request graceful agent shutdown")
    shutdown_parser.add_argument("url", help="Agent URL")

    # Main mode flags (only apply when no subcommand)
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
    return parser.parse_args()


async def run_repl(
    verbose: bool = False,
    raw_log: bool = False,
    log_dir: Path | None = None,
) -> None:
    """Run the async REPL loop.

    Loads configuration, creates provider and session, then enters an
    interactive loop reading user input and streaming responses.

    Args:
        verbose: Enable verbose logging stream.
        raw_log: Enable raw API logging stream.
        log_dir: Directory for session logs.
    """
    console = get_console()
    theme = load_theme()

    # Load configuration
    try:
        config = load_config()
    except NexusError as e:
        console.print(f"[red]Error:[/] {e.message}")
        return

    # Create provider
    try:
        provider = OpenRouterProvider(config.provider)
    except NexusError as e:
        console.print(f"[red]Error:[/] {e.message}")
        return

    # Configure logging streams - all on by default for debugging
    streams = LogStream.ALL

    # Create session logger
    log_config = LogConfig(
        base_dir=log_dir or Path(".nexus3/logs"),
        streams=streams,
    )
    logger = SessionLogger(log_config)

    # Wire up raw logging callback if enabled
    raw_callback = logger.get_raw_log_callback()
    if raw_callback is not None:
        provider.set_raw_log_callback(raw_callback)

    # Load system prompt
    prompt_loader = PromptLoader()
    loaded_prompt = prompt_loader.load()
    system_prompt = loaded_prompt.content

    # Create context manager
    context = ContextManager(
        config=ContextConfig(),
        logger=logger,
    )
    context.set_system_prompt(system_prompt)

    # Create skill registry with services
    services = ServiceContainer()
    registry = SkillRegistry(services)
    register_builtin_skills(registry)

    # Inject tool definitions into context
    context.set_tool_definitions(registry.get_definitions())

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
            # Extract path from arguments if available
            path = tc.arguments.get("path", "") or tc.arguments.get("file", "")
            tools.append((tc.name, tc.id, path))
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

            # Tool name with path
            if tool.path:
                console.print(f"  {gumball} {tool.name}: {tool.path}{suffix}")
            else:
                console.print(f"  {gumball} {tool.name}{suffix}")

            # Error message on next line (first 70 chars)
            if tool.state == ToolState.ERROR and tool.error:
                error_preview = tool.error[:70] + ("..." if len(tool.error) > 70 else "")
                console.print(f"      [red dim]{error_preview}[/]")
        display.clear_tools()

    # Create session with context and tool callbacks
    session = Session(
        provider,
        context=context,
        logger=logger,
        registry=registry,
        on_tool_call=on_tool_call,
        on_reasoning=on_reasoning,
        on_batch_start=on_batch_start,
        on_tool_active=on_tool_active,
        on_batch_progress=on_batch_progress,
        on_batch_halt=on_batch_halt,
        on_batch_complete=on_batch_complete,
    )

    # Print welcome message
    console.print("[bold]NEXUS3 v0.1.0[/bold]")
    console.print(f"Session: {logger.session_dir}", style="dim")
    if loaded_prompt.personal_path:
        console.print(f"Personal: {loaded_prompt.personal_path}", style="dim")
    if loaded_prompt.project_path:
        console.print(f"Project: {loaded_prompt.project_path}", style="dim")
    console.print("Commands: /quit | ESC to cancel", style="dim")
    console.print("")

    # Toolbar state - tracks ready/active and whether there were errors
    toolbar_has_errors = False

    def get_toolbar() -> HTML:
        """Return the bottom toolbar based on current state."""
        square = '<style fg="ansibrightblack">■</style>'
        if toolbar_has_errors:
            return HTML(f'{square} <style fg="ansiyellow">● ready (some tasks incomplete)</style>')
        else:
            return HTML(f'{square} <style fg="ansigreen">● ready</style>')

    # Style to remove default toolbar highlight
    prompt_style = Style.from_dict({
        "bottom-toolbar": "noreverse",
    })

    # Create prompt session with bottom toolbar
    prompt_session: PromptSession[str] = PromptSession(
        bottom_toolbar=get_toolbar,
        style=prompt_style,
    )

    # Main REPL loop
    while True:
        try:
            # Get user input
            user_input = await prompt_session.prompt_async("> ")

            # Handle empty input
            if not user_input.strip():
                continue

            # Handle slash commands
            command = parse_command(user_input)
            if command is not None:
                result = handle_command(command)
                if result == CommandResult.QUIT:
                    console.print("Goodbye!", style="dim")
                    break
                elif result == CommandResult.UNKNOWN:
                    console.print(f"Unknown command: /{command.name}", style="dim")
                    console.print("Available: /quit, /exit, /q", style="dim")
                continue

            # Overwrite prompt_toolkit's plain input with highlighted version
            # Move cursor up one line and overwrite
            console.print("\033[A\033[K", end="")  # Up one line, clear to end
            console.print(f"[reverse] > {user_input} [/reverse]")
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
            ) -> None:
                async for chunk in session.send(inp):
                    if d.activity == Activity.WAITING:
                        d.set_activity(Activity.RESPONDING)
                    d.add_chunk(chunk)

            # Use Live ONLY during streaming (animation works here)
            with Live(display, console=console, refresh_per_second=10, transient=True) as live:
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
                    session.add_cancelled_tools(cancelled_tools)

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

        except KeyboardInterrupt:
            console.print("")
            console.print("Use /quit to exit.", style="dim")
            continue

        except EOFError:
            console.print("")
            console.print("Goodbye!", style="dim")
            break

    # Clean up logger
    logger.close()


def main() -> None:
    """Entry point for the NEXUS3 CLI."""
    args = parse_args()
    try:
        # Handle client subcommands
        if args.command is not None:
            from nexus3.cli.client_commands import (
                cmd_cancel,
                cmd_send,
                cmd_shutdown,
                cmd_status,
            )

            if args.command == "send":
                exit_code = asyncio.run(
                    cmd_send(args.url, args.content, args.request_id)
                )
            elif args.command == "cancel":
                exit_code = asyncio.run(cmd_cancel(args.url, args.request_id))
            elif args.command == "status":
                exit_code = asyncio.run(cmd_status(args.url))
            elif args.command == "shutdown":
                exit_code = asyncio.run(cmd_shutdown(args.url))
            else:
                print(f"Unknown command: {args.command}")
                exit_code = 1
            raise SystemExit(exit_code)

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
