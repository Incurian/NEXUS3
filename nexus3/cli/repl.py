"""Async REPL with prompt-toolkit for NEXUS3."""

import asyncio

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout

from nexus3.cli.keys import KeyMonitor
from nexus3.config.loader import load_config
from nexus3.core.encoding import configure_stdio
from nexus3.core.errors import NexusError
from nexus3.display import Activity, DisplayManager
from nexus3.provider.openrouter import OpenRouterProvider
from nexus3.session.session import Session

# Configure UTF-8 at module load
configure_stdio()


async def run_repl() -> None:
    """Run the async REPL loop.

    Loads configuration, creates provider and session, then enters an
    interactive loop reading user input and streaming responses.
    """
    # Create display manager
    display = DisplayManager()

    # Load configuration
    try:
        config = load_config()
    except NexusError as e:
        display.print_error(e.message)
        return

    # Create provider
    try:
        provider = OpenRouterProvider(config.provider)
    except NexusError as e:
        display.print_error(e.message)
        return

    # Create session
    session = Session(provider)

    # Print welcome message
    display.print("[bold]NEXUS3 v0.1.0[/bold]")
    display.print("Type /quit to exit.", style="dim")
    display.print("")

    # Create prompt session for async input
    prompt_session: PromptSession[str] = PromptSession()

    # Main REPL loop
    while True:
        try:
            # Get user input with patch_stdout to handle async output properly
            with patch_stdout():
                user_input = await prompt_session.prompt_async("> ")

            # Handle empty input
            if not user_input.strip():
                continue

            # Handle /quit command
            if user_input.strip().lower() == "/quit":
                display.print("Goodbye!", style="dim")
                break

            # Send to session and stream response
            try:
                async with display.live_session():
                    # Monitor for ESC key to cancel
                    async with KeyMonitor(on_escape=display.cancel):
                        display.set_activity(Activity.THINKING)

                        first_chunk = True
                        async for chunk in session.send(user_input):
                            # Check for cancellation
                            if display.is_cancelled:
                                display.print_cancelled()
                                break

                            # Switch to responding after first chunk
                            if first_chunk:
                                display.set_activity(Activity.RESPONDING)
                                first_chunk = False

                            display.print_streaming(chunk)

                        # Finish the response line
                        if not display.is_cancelled:
                            display.finish_streaming()

                        display.set_activity(Activity.IDLE)

            except NexusError as e:
                display.print_error(e.message)

            # Add spacing after response
            display.print("")

        except KeyboardInterrupt:
            # Handle Ctrl+C gracefully
            display.print("")
            display.print("Use /quit to exit.", style="dim")
            continue

        except EOFError:
            # Handle Ctrl+D
            display.print("")
            display.print("Goodbye!", style="dim")
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
