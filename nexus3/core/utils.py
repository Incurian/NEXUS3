"""Shared utility functions for NEXUS3.

These are common operations used across multiple modules that don't
fit into more specific categories.
"""

from pathlib import Path
from typing import Any

from nexus3.core.constants import NEXUS_DIR_NAME


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge dicts. Override values take precedence.

    - Dicts are recursively merged
    - Lists are extended (not replaced)
    - Other values are overwritten

    Args:
        base: Base dictionary.
        override: Dictionary with values to overlay.

    Returns:
        New merged dictionary (original dicts not modified).
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            result[key] = result[key] + value
        else:
            result[key] = value
    return result


def find_ancestor_config_dirs(cwd: Path, max_depth: int = 2) -> list[Path]:
    """Find .nexus3 directories in ancestor paths.

    Searches up to max_depth parent directories for .nexus3 config directories.

    Args:
        cwd: Starting directory.
        max_depth: Maximum number of ancestor levels to check.

    Returns:
        List of ancestor config directories in order from
        furthest (grandparent) to nearest (parent).
    """
    ancestors = []
    current = cwd.parent

    for _ in range(max_depth):
        if current == current.parent:  # Reached root
            break
        config_dir = current / NEXUS_DIR_NAME
        if config_dir.is_dir():
            ancestors.append(config_dir)
        current = current.parent

    # Return in order: grandparent first, then parent (for correct merge order)
    return list(reversed(ancestors))
