"""Rich-based output utilities for NEXUS3 CLI."""

from collections.abc import AsyncIterator

from rich.console import Console

# Shared console instance
console = Console()


async def print_streaming(chunks: AsyncIterator[str]) -> None:
    """Print streamed chunks in real-time.

    Args:
        chunks: Async iterator of string chunks to print.
    """
    async for chunk in chunks:
        console.print(chunk, end="", highlight=False)
    # Print newline after stream completes
    console.print()


def print_error(message: str) -> None:
    """Print an error message in red.

    Args:
        message: The error message to display.
    """
    console.print(f"[bold red]Error:[/bold red] {message}")


def print_info(message: str) -> None:
    """Print an informational message.

    Args:
        message: The info message to display.
    """
    console.print(f"[dim]{message}[/dim]")
