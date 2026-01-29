"""Shared utility functions for NEXUS3.

These are common operations used across multiple modules that don't
fit into more specific categories.
"""

from pathlib import Path
from typing import Any

from nexus3.core.constants import NEXUS_DIR_NAME


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge dicts. Override values take precedence.

    P2.14 SECURITY: Lists are now REPLACED, not extended. This is critical for
    security-related keys like `blocked_paths` and `disabled_tools`. For example:
    - Global: `blocked_paths: ["/etc"]`
    - Local:  `blocked_paths: []`
    - Result: `[]` (local replaces global)

    If lists were extended, local config couldn't override/clear global lists,
    which breaks the principle that more specific config takes precedence.

    Merge rules:
    - Dicts are recursively merged
    - Lists are REPLACED (override wins completely)
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
        else:
            # P2.14 FIX: Lists (and all other types) are replaced, not extended
            # This ensures local config can override security-related lists
            result[key] = value
    return result


def find_ancestor_config_dirs(
    cwd: Path,
    max_depth: int = 2,
    exclude_paths: list[Path] | None = None,
) -> list[Path]:
    """Find .nexus3 directories in ancestor paths.

    Searches up to max_depth parent directories for .nexus3 config directories.

    Args:
        cwd: Starting directory.
        max_depth: Maximum number of ancestor levels to check.
        exclude_paths: Paths to exclude (e.g., global dir). Uses resolve() for comparison.

    Returns:
        List of ancestor config directories in order from
        furthest (grandparent) to nearest (parent).
    """
    ancestors = []
    # Use resolve() for consistent cross-platform comparison
    current = cwd.resolve().parent

    # Normalize exclude paths for comparison
    excluded_resolved: set[Path] = set()
    if exclude_paths:
        excluded_resolved = {p.resolve() for p in exclude_paths}

    for _ in range(max_depth):
        if current == current.parent:  # Reached root
            break
        config_dir = current / NEXUS_DIR_NAME
        if config_dir.is_dir():
            # Skip if this matches an excluded path (e.g., global dir)
            if config_dir.resolve() not in excluded_resolved:
                ancestors.append(config_dir)
        current = current.parent

    # Return in order: grandparent first, then parent (for correct merge order)
    return list(reversed(ancestors))
