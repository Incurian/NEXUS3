"""Configuration loading with fail-fast behavior and layered merging.

This module provides configuration loading that merges configs from multiple
layers (defaults → global → ancestors → local), allowing project-level
overrides of global settings.
"""

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from nexus3.config.schema import Config
from nexus3.core.errors import ConfigError

# Path to shipped defaults in the install directory
DEFAULTS_DIR = Path(__file__).parent.parent / "defaults"
DEFAULT_CONFIG = DEFAULTS_DIR / "config.json"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge dicts. Override values take precedence.

    - Dicts are recursively merged
    - Lists are extended (not replaced)
    - Other values are overwritten

    Args:
        base: Base dictionary.
        override: Dictionary with values to overlay.

    Returns:
        New merged dictionary.
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            result[key] = result[key] + value  # Extend lists
        else:
            result[key] = value
    return result


def _load_json_file(path: Path) -> dict[str, Any] | None:
    """Load a JSON config file if it exists.

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed JSON as dict, or None if file doesn't exist.

    Raises:
        ConfigError: If file exists but contains invalid JSON.
    """
    if not path.exists():
        return None

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"Failed to read config file {path}: {e}") from e

    if not content.strip():
        return {}  # Empty file = empty config

    try:
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ConfigError(f"Expected object in {path}, got {type(data).__name__}")
        return data
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in config file {path}: {e}") from e


def _find_ancestor_config_dirs(cwd: Path, max_depth: int = 2) -> list[Path]:
    """Find .nexus3 directories in ancestor paths.

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
        config_dir = current / ".nexus3"
        if config_dir.is_dir():
            ancestors.append(config_dir)
        current = current.parent

    # Return in order: grandparent first, then parent (for correct merge order)
    return list(reversed(ancestors))


def load_config(path: Path | None = None, cwd: Path | None = None) -> Config:
    """Load configuration from file with layered merging.

    When path is None, merges config from multiple layers:
    1. Shipped defaults (install_dir/defaults/config.json)
    2. Global user (~/.nexus3/config.json)
    3. Ancestor directories (up to 2 levels above cwd)
    4. Project local (cwd/.nexus3/config.json)

    Later layers override earlier layers using deep merge.

    Args:
        path: Explicit config file path. If provided, skips layered loading.
        cwd: Working directory for ancestor/local lookup. Defaults to Path.cwd().

    Returns:
        Validated Config object.

    Raises:
        ConfigError: If any config file contains invalid JSON or merged config
            fails validation.
    """
    if path is not None:
        return _load_from_path(path)

    effective_cwd = cwd or Path.cwd()
    merged: dict[str, Any] = {}
    loaded_from: list[Path] = []

    # Layer 1: Shipped defaults
    default_data = _load_json_file(DEFAULT_CONFIG)
    if default_data:
        merged = _deep_merge(merged, default_data)
        loaded_from.append(DEFAULT_CONFIG)

    # Layer 2: Global user config
    global_config = Path.home() / ".nexus3" / "config.json"
    global_data = _load_json_file(global_config)
    if global_data:
        merged = _deep_merge(merged, global_data)
        loaded_from.append(global_config)

    # Layer 3: Ancestor directories
    # Determine ancestor_depth by checking all layers (local takes precedence)
    # Check local first, then global, then merged defaults - use first found
    local_config = effective_cwd / ".nexus3" / "config.json"
    local_depth = None
    if local_config.exists():
        local_data_peek = _load_json_file(local_config)
        if local_data_peek:
            local_depth = local_data_peek.get("context", {}).get("ancestor_depth")
    ancestor_depth = (
        local_depth
        if local_depth is not None
        else merged.get("context", {}).get("ancestor_depth", 2)
    )
    ancestor_dirs = _find_ancestor_config_dirs(effective_cwd, ancestor_depth)

    for ancestor_dir in ancestor_dirs:
        ancestor_config = ancestor_dir / "config.json"
        ancestor_data = _load_json_file(ancestor_config)
        if ancestor_data:
            merged = _deep_merge(merged, ancestor_data)
            loaded_from.append(ancestor_config)

    # Layer 4: Project local config
    local_config = effective_cwd / ".nexus3" / "config.json"
    local_data = _load_json_file(local_config)
    if local_data:
        merged = _deep_merge(merged, local_data)
        loaded_from.append(local_config)

    # Validate merged config
    if not merged:
        # No config files found - use Pydantic defaults
        return Config()

    try:
        return Config.model_validate(merged)
    except ValidationError as e:
        sources = ", ".join(str(p) for p in loaded_from)
        raise ConfigError(f"Config validation failed (merged from {sources}): {e}") from e


def _load_from_path(path: Path) -> Config:
    """Load and validate config from a specific path.

    Args:
        path: Path to config file.

    Returns:
        Validated Config object.

    Raises:
        ConfigError: If file doesn't exist, contains invalid JSON, or fails validation.
    """
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"Failed to read config file {path}: {e}") from e

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in config file {path}: {e}") from e

    try:
        return Config.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"Config validation failed for {path}: {e}") from e
