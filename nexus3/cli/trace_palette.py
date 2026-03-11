"""Shared color palette for trace-style REPL and trace output."""

from __future__ import annotations

TRACE_HEADER_STYLES: dict[str, str] = {
    "user": "bold bright_blue",
    "assistant": "bold bright_magenta",
    "tool_call": "bold bright_cyan",
    "tool_result": "bold bright_green",
}

TRACE_BODY_STYLES: dict[str, str] = {
    "user": "blue",
    "assistant": "magenta",
    "tool_call": "cyan",
    "tool_result": "#2c7a4b",
}


def trace_header_style(kind: str) -> str:
    """Return the canonical trace header style for an entry kind."""
    return TRACE_HEADER_STYLES.get(kind, "bold")


def trace_body_style(kind: str) -> str | None:
    """Return the canonical trace body style for an entry kind."""
    return TRACE_BODY_STYLES.get(kind)
