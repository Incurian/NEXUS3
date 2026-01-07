"""Shared Rich Console instance for NEXUS3."""

from rich.console import Console

# Shared console instance - all display components should use this
# This ensures consistent output and proper coordination with Rich.Live
_console: Console | None = None


def get_console() -> Console:
    """Get the shared Console instance.

    Creates the console on first access. All display components
    should use this rather than creating their own Console.
    """
    global _console
    if _console is None:
        _console = Console(
            highlight=False,  # Don't auto-highlight, we control styling
            markup=True,      # Enable Rich markup like [cyan]text[/]
        )
    return _console


def set_console(console: Console) -> None:
    """Set a custom Console instance.

    Useful for testing or custom configurations.
    """
    global _console
    _console = console
