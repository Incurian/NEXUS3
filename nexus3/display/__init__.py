"""NEXUS3 display system.

Exports the active Spinner-based REPL display path. Legacy display-stack
modules remain importable from their direct module paths during cleanup, but
they are no longer re-exported from this package root.
"""

from nexus3.display.console import get_console, set_console
from nexus3.display.printer import InlinePrinter
from nexus3.display.spinner import Spinner
from nexus3.display.theme import Activity, Status, Theme, load_theme

__all__ = [
    # Console
    "get_console",
    "set_console",
    # Canonical REPL display path
    "Spinner",
    # Supporting helpers
    "InlinePrinter",
    # Theme
    "Activity",
    "Status",
    "Theme",
    "load_theme",
]
