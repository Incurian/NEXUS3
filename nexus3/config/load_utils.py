"""Unified JSON loading utility for config and context files.

This module provides a consistent way to load JSON files with proper error
handling that integrates with the NEXUS3 error hierarchy.

Use:
- load_json_file() for required files (raises LoadError if not found)
- load_json_file_optional() for optional config layers (returns None if not found)

Both functions use Path.resolve() for Windows/Git Bash compatibility where
Path.home() may return Unix-style paths like /c/Users/... that fail exists() checks.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from nexus3.core.errors import LoadError

logger = logging.getLogger(__name__)


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

    # Use resolve() for Windows compatibility (Git Bash path format)
    resolved = path.resolve()

    if not resolved.exists():
        raise LoadError(f"{context_prefix}File not found: {path}")

    try:
        content = resolved.read_text(encoding="utf-8-sig")
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


def load_json_file_optional(path: Path, error_context: str = "") -> dict[str, Any] | None:
    """Load JSON file if it exists, returning None for missing files.

    Use this for optional config layers (global, ancestor, local) where the
    file may or may not exist.

    Args:
        path: Path to the JSON file to load.
        error_context: Optional context string for error messages.

    Returns:
        Parsed JSON as dict, empty dict for empty files, or None if file missing.

    Raises:
        LoadError: If file exists but can't be read or contains invalid JSON.
    """
    # Use resolve() for Windows compatibility (Git Bash path format)
    resolved = path.resolve()

    if not resolved.is_file():
        logger.debug("Config file not found: %s (resolved: %s)", path, resolved)
        return None

    logger.debug("Loading config file: %s", resolved)
    return load_json_file(resolved, error_context)
