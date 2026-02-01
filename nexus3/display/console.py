"""Shared Rich Console instance for NEXUS3."""

from __future__ import annotations

import sys

from rich.console import Console


_console: Console | None = None


def get_console() -> Console:
    """Get the shared Console instance.

    Creates the console on first access with shell-appropriate settings.
    On Windows, detects shell capabilities and configures Rich accordingly.
    """
    global _console
    if _console is None:
        if sys.platform == "win32":
            # Import here to avoid circular imports
            from nexus3.core.shell_detection import supports_ansi

            ansi_ok = supports_ansi()
            _console = Console(
                highlight=False,
                markup=True,
                force_terminal=ansi_ok,      # Only force if shell supports it
                legacy_windows=not ansi_ok,  # Use legacy mode for CMD.exe
                no_color=not ansi_ok,        # Disable color if no ANSI
            )
        else:
            # Unix: keep current behavior
            _console = Console(
                highlight=False,
                markup=True,
                force_terminal=True,
                legacy_windows=False,
            )
    return _console


def set_console(console: Console) -> None:
    """Set a custom Console instance.

    Useful for testing or custom configurations.
    """
    global _console
    _console = console
