"""Command-line interface."""

from nexus3.cli.repl import main
from nexus3.cli.sse_router import EventRouter, TERMINAL_EVENTS

__all__ = ["main", "EventRouter", "TERMINAL_EVENTS"]
