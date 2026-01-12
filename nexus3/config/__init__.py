"""Configuration loading and validation."""

from nexus3.config.loader import DEFAULT_CONFIG, DEFAULTS_DIR, load_config
from nexus3.config.schema import (
    Config,
    MCPServerConfig,
    PermissionPresetConfig,
    PermissionsConfig,
    ProviderConfig,
    ToolPermissionConfig,
)

__all__ = [
    "Config",
    "DEFAULT_CONFIG",
    "DEFAULTS_DIR",
    "MCPServerConfig",
    "PermissionPresetConfig",
    "PermissionsConfig",
    "ProviderConfig",
    "ToolPermissionConfig",
    "load_config",
]
