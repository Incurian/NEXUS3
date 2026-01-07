"""Configuration loading with fail-fast behavior."""

import json
from pathlib import Path

from pydantic import ValidationError

from nexus3.config.schema import Config
from nexus3.core.errors import ConfigError


def load_config(path: Path | None = None) -> Config:
    """Load configuration from file with fail-fast behavior.

    Args:
        path: Explicit config file path. If None, searches standard locations.

    Returns:
        Validated Config object.

    Raises:
        ConfigError: If config file exists but contains invalid JSON or fails validation.

    Search order (when path is None):
        1. .nexus3/config.json (project-local)
        2. ~/.nexus3/config.json (global)
        3. Return default Config() if no file found
    """
    if path is not None:
        return _load_from_path(path)

    # Search standard locations
    search_paths = [
        Path.cwd() / ".nexus3" / "config.json",  # Project-local
        Path.home() / ".nexus3" / "config.json",  # Global
    ]

    for config_path in search_paths:
        if config_path.exists():
            return _load_from_path(config_path)

    # No config file found, return defaults
    return Config()


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
