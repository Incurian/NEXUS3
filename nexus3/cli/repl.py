"""Async REPL with prompt-toolkit for NEXUS3."""

import asyncio

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from rich.live import Live

from nexus3.cli.commands import CommandResult, handle_command, parse_command
from nexus3.cli.keys import KeyMonitor
from nexus3.config.loader import load_config
from nexus3.core.encoding import configure_stdio
from nexus3.core.errors import NexusError
from nexus3.display import Activity, StreamingDisplay, get_console
from nexus3.display.theme import load_theme
from nexus3.provider.openrouter import OpenRouterProvider
from nexus3.session.session import Session

# Configure UTF-8 at module load
configure_stdio()


async def run_repl() -> None:
    """Run the async REPL loop.

    Loads configuration, creates provider and session, then enters an
    interactive loop reading user input and streaming responses.
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

    # Create session
    session = Session(provider)

    # Print welcome message
    console.print("[bold]NEXUS3 v0.1.0[/bold]")
    console.print("Commands: /quit | ESC to cancel", style="dim")
    console.print("")

    # Display for streaming phases
    display = StreamingDisplay(theme)

    # Toolbar state
    toolbar_status = "ready"

    def get_toolbar() -> HTML:
        """Return the bottom toolbar based on current state."""
        square = '<style fg="ansibrightblack">■</style>'
        if toolbar_status == "ready":
            return HTML(f'{square} <style fg="ansigreen">● ready</style>')
        elif toolbar_status == "error":
            return HTML(f'{square} <style fg="ansired">● error</style>')
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
            # Get user input (toolbar shows "ready" state)
            toolbar_status = "ready"
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

            # Reset display for new response
            display.reset()
            display.set_activity(Activity.WAITING)

            # Streaming task that can be cancelled
            stream_task: asyncio.Task[None] | None = None

            def on_cancel(
                d: StreamingDisplay = display,
                get_task: object = lambda: stream_task,
            ) -> None:
                d.cancel()
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

            # After Live exits, print the final response
            if display.response:
                console.print("")  # Visual separation before response
                console.print(display.response)
                console.print("")  # Visual separation after response

            # Show completion status
            if display.is_cancelled:
                console.print("[yellow]● Cancelled[/]")
                console.print("")  # Visual separation after cancel

        except KeyboardInterrupt:
            console.print("")
            console.print("Use /quit to exit.", style="dim")
            continue

        except EOFError:
            console.print("")
            console.print("Goodbye!", style="dim")
            break


def main() -> None:
    """Entry point for the NEXUS3 CLI."""
    try:
        asyncio.run(run_repl())
    except KeyboardInterrupt:
        # Handle Ctrl+C during startup
        pass


if __name__ == "__main__":
    main()
