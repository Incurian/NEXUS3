"""NEXUS3 display system.

Provides inline printing with gumballs and a configurable summary bar.
"""

from nexus3.display.console import get_console, set_console
from nexus3.display.manager import DisplayManager
from nexus3.display.printer import InlinePrinter
from nexus3.display.segments import (
    ActivitySegment,
    CancelHintSegment,
    SummarySegment,
    TaskCountSegment,
)
from nexus3.display.summary import SummaryBar
from nexus3.display.theme import Activity, Status, Theme, load_theme

__all__ = [
    # Console
    "get_console",
    "set_console",
    # Manager
    "DisplayManager",
    # Printer
    "InlinePrinter",
    # Segments
    "ActivitySegment",
    "CancelHintSegment",
    "SummarySegment",
    "TaskCountSegment",
    # Summary bar
    "SummaryBar",
    # Theme
    "Activity",
    "Status",
    "Theme",
    "load_theme",
]
