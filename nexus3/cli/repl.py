"""Async REPL with prompt-toolkit for NEXUS3."""

import asyncio

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout

from nexus3.cli.output import console, print_error, print_info, print_streaming
from nexus3.config.loader import load_config
from nexus3.core.encoding import configure_stdio
from nexus3.core.errors import NexusError
from nexus3.provider.openrouter import OpenRouterProvider
from nexus3.session.session import Session

# Configure UTF-8 at module load
configure_stdio()


async def run_repl() -> None:
    """Run the async REPL loop.

    Loads configuration, creates provider and session, then enters an
    interactive loop reading user input and streaming responses.
    """
    # Load configuration
    try:
        config = load_config()
    except NexusError as e:
        print_error(e.message)
        return

    # Create provider
    try:
        provider = OpenRouterProvider(config.provider)
    except NexusError as e:
        print_error(e.message)
        return

    # Create session
    session = Session(provider)

    # Print welcome message
    console.print("[bold]NEXUS3 v0.1.0[/bold]")
    print_info("Type /quit to exit.")
    console.print()

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
                print_info("Goodbye!")
                break

            # Send to session and stream response
            try:
                await print_streaming(session.send(user_input))
            except NexusError as e:
                print_error(e.message)

        except KeyboardInterrupt:
            # Handle Ctrl+C gracefully
            console.print()
            print_info("Use /quit to exit.")
            continue

        except EOFError:
            # Handle Ctrl+D
            console.print()
            print_info("Goodbye!")
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
