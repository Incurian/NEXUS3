"""Shared helpers for normalizing tool-call argument edge cases.

These helpers are intentionally narrow. They exist to centralize recurring
boundary normalization for callers that serialize omitted optional string
arguments as empty strings.
"""

from __future__ import annotations


def normalize_empty_optional_string(value: str | None) -> str | None:
    """Treat an empty-string optional value as omitted."""
    if value == "":
        return None
    return value


def is_omitted_optional_string(value: object) -> bool:
    """Return True when an optional string value is effectively omitted."""
    return value is None or value == ""
