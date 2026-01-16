"""Unified JSON loading utility for config and context files.

This module provides a consistent way to load JSON files with proper error
handling that integrates with the NEXUS3 error hierarchy.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nexus3.core.errors import LoadError


def load_json_file(path: Path, error_context: str = "") -> dict[str, Any]:
    """Load and parse a JSON file with consistent error handling.

    Args:
        path: Path to the JSON file to load.
        error_context: Optional context string for error messages (e.g., "config", "mcp").

    Returns:
        Parsed JSON as a dict. Returns empty dict if file is empty.

    Raises:
        LoadError: If the file doesn't exist, can't be read, contains invalid JSON,
            or contains non-dict JSON (e.g., array or scalar).
    """
    context_prefix = f"{error_context}: " if error_context else ""

    if not path.exists():
        raise LoadError(f"{context_prefix}File not found: {path}")

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        raise LoadError(f"{context_prefix}Failed to read file {path}: {e}") from e

    # Empty file is valid - return empty dict
    content = content.strip()
    if not content:
        return {}

    try:
        result = json.loads(content)
    except json.JSONDecodeError as e:
        raise LoadError(f"{context_prefix}Invalid JSON in {path}: {e}") from e

    if not isinstance(result, dict):
        raise LoadError(
            f"{context_prefix}Expected object in {path}, got {type(result).__name__}"
        )

    return result
