"""Shared Live display state for REPL confirmation UI.

This module exists to avoid circular imports and ContextVar duplication.

Sprint 5 fix: repl.py and confirmation_ui.py previously defined separate
ContextVar instances named _current_live, causing confirmation prompts to
hang because the confirmation UI could not stop the active Live display.

Both modules must import the SAME ContextVar instance.
"""

from __future__ import annotations

from contextvars import ContextVar

from rich.live import Live

# Context variable to store the current Live display for pausing during confirmation
_current_live: ContextVar[Live | None] = ContextVar("_current_live", default=None)
