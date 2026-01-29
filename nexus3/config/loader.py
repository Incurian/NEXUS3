"""Configuration loading with fail-fast behavior and layered merging.

This module provides configuration loading that merges configs from multiple
layers (defaults → global → ancestors → local), allowing project-level
overrides of global settings.
"""

import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from nexus3.config.load_utils import load_json_file, load_json_file_optional
from nexus3.config.schema import Config
from nexus3.core.constants import get_defaults_dir, get_nexus_dir
from nexus3.core.errors import ConfigError, LoadError
from nexus3.core.utils import deep_merge, find_ancestor_config_dirs

logger = logging.getLogger(__name__)

# Path to shipped defaults in the install directory
DEFAULTS_DIR = get_defaults_dir()
DEFAULT_CONFIG = DEFAULTS_DIR / "config.json"


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
    try:
        default_data = load_json_file_optional(DEFAULT_CONFIG)
    except LoadError as e:
        raise ConfigError(e.message) from e
    if default_data:
        merged = deep_merge(merged, default_data)
        loaded_from.append(DEFAULT_CONFIG)

    # Layer 2: Global user config
    global_dir = get_nexus_dir()
    global_config = global_dir / "config.json"
    try:
        global_data = load_json_file_optional(global_config)
    except LoadError as e:
        raise ConfigError(e.message) from e
    if global_data:
        merged = deep_merge(merged, global_data)
        loaded_from.append(global_config)
    else:
        logger.debug("No global config at: %s", global_config)

    # Layer 3: Ancestor directories
    # Determine ancestor_depth by checking all layers (local takes precedence)
    # Check local first, then global, then merged defaults - use first found
    local_config = effective_cwd / ".nexus3" / "config.json"
    local_depth = None
    try:
        local_data_peek = load_json_file_optional(local_config)
    except LoadError as e:
        raise ConfigError(e.message) from e
    if local_data_peek:
        local_depth = local_data_peek.get("context", {}).get("ancestor_depth")
    ancestor_depth = (
        local_depth
        if local_depth is not None
        else merged.get("context", {}).get("ancestor_depth", 2)
    )

    # BUGFIX: Exclude global dir to avoid loading it twice (when CWD is inside home)
    ancestor_dirs = find_ancestor_config_dirs(
        effective_cwd, ancestor_depth, exclude_paths=[global_dir]
    )

    for ancestor_dir in ancestor_dirs:
        ancestor_config = ancestor_dir / "config.json"
        try:
            ancestor_data = load_json_file_optional(ancestor_config)
        except LoadError as e:
            raise ConfigError(e.message) from e
        if ancestor_data:
            merged = deep_merge(merged, ancestor_data)
            loaded_from.append(ancestor_config)

    # Layer 4: Project local config
    local_config = effective_cwd / ".nexus3" / "config.json"
    try:
        local_data = load_json_file_optional(local_config)
    except LoadError as e:
        raise ConfigError(e.message) from e
    if local_data:
        merged = deep_merge(merged, local_data)
        loaded_from.append(local_config)

    # Log final sources for debugging
    if loaded_from:
        logger.info("Config loaded from: %s", [str(p) for p in loaded_from])
    else:
        logger.debug("No config files found, using defaults")

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
    try:
        data = load_json_file(path, error_context="config")
    except LoadError as e:
        raise ConfigError(e.message) from e

    try:
        return Config.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"Config validation failed for {path}: {e}") from e
