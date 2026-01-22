"""NEXUS3 display system.

Provides a simple spinner display and inline printing with gumballs.
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
from nexus3.display.spinner import Spinner
from nexus3.display.streaming import StreamingDisplay
from nexus3.display.summary import SummaryBar
from nexus3.display.theme import Activity, Status, Theme, load_theme

__all__ = [
    # Console
    "get_console",
    "set_console",
    # Spinner (new simplified display)
    "Spinner",
    # Manager (deprecated - use Spinner instead)
    "DisplayManager",
    # Printer
    "InlinePrinter",
    # Streaming (deprecated - use Spinner instead)
    "StreamingDisplay",
    # Segments (deprecated)
    "ActivitySegment",
    "CancelHintSegment",
    "SummarySegment",
    "TaskCountSegment",
    # Summary bar (deprecated - use Spinner instead)
    "SummaryBar",
    # Theme
    "Activity",
    "Status",
    "Theme",
    "load_theme",
]
