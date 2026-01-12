# nexus3/config

Configuration loading and validation module for NEXUS3.

## Purpose

This module provides fail-fast configuration loading with Pydantic validation. It supports a hierarchical config search (project-local overrides global) and returns sensible defaults when no config file exists.

## Key Types/Classes

### `ProviderConfig` (schema.py)

LLM provider configuration with defaults:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | `str` | `"openrouter"` | Provider type identifier |
| `api_key_env` | `str` | `"OPENROUTER_API_KEY"` | Environment variable containing API key |
| `model` | `str` | `"x-ai/grok-code-fast-1"` | Model identifier |
| `base_url` | `str` | `"https://openrouter.ai/api/v1"` | API base URL |

### `ToolPermissionConfig` (schema.py)

Per-tool permission configuration for use in config.json presets:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `True` | Whether tool is enabled |
| `allowed_paths` | `list[str] \| None` | `None` | Paths tool can access (None = inherit from preset) |
| `timeout` | `float \| None` | `None` | Tool-specific timeout (None = use global) |
| `requires_confirmation` | `bool \| None` | `None` | Prompt before execution (None = use preset default) |

### `PermissionPresetConfig` (schema.py)

Custom permission preset configuration:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `extends` | `str \| None` | `None` | Base preset to extend (e.g., "trusted") |
| `description` | `str` | `""` | Human-readable description |
| `allowed_paths` | `list[str] \| None` | `None` | Paths accessible to tools |
| `blocked_paths` | `list[str]` | `[]` | Paths explicitly blocked |
| `network_access` | `bool \| None` | `None` | Network access (derived from level for built-ins) |
| `tool_permissions` | `dict[str, ToolPermissionConfig]` | `{}` | Per-tool overrides |
| `default_tool_timeout` | `float \| None` | `None` | Default timeout for tools |

### `PermissionsConfig` (schema.py)

Top-level permissions configuration:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `default_preset` | `str` | `"trusted"` | Default preset for new agents |
| `presets` | `dict[str, PermissionPresetConfig]` | `{}` | Custom preset definitions |
| `destructive_tools` | `list[str]` | `["write_file", "nexus_destroy", "nexus_shutdown"]` | Tools requiring confirmation in TRUSTED mode |

### `Config` (schema.py)

Root configuration model:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `provider` | `ProviderConfig` | `ProviderConfig()` | LLM provider settings |
| `stream_output` | `bool` | `True` | Whether to stream responses |
| `max_tool_iterations` | `int` | `10` | Maximum iterations of the tool execution loop |
| `default_permission_level` | `str` | `"trusted"` | Default permission level (yolo/trusted/sandboxed) |
| `skill_timeout` | `float` | `30.0` | Global skill timeout in seconds (0 = no timeout) |
| `max_concurrent_tools` | `int` | `10` | Maximum parallel tool executions |
| `permissions` | `PermissionsConfig` | `PermissionsConfig()` | Permission system configuration |

### `load_config(path: Path | None = None) -> Config` (loader.py)

Main entry point for loading configuration.

**Parameters:**
- `path`: Optional explicit config file path. If `None`, searches standard locations.

**Returns:** Validated `Config` object.

**Raises:** `ConfigError` if config file exists but is invalid.

### `_load_from_path(path: Path) -> Config` (loader.py)

Internal function that loads and validates config from a specific path.

**Parameters:**
- `path`: Path to config file.

**Returns:** Validated `Config` object.

**Raises:** `ConfigError` if file doesn't exist, contains invalid JSON, or fails validation.

## Configuration Schema

Full configuration with all options:

```json
{
  "provider": {
    "type": "openrouter",
    "api_key_env": "OPENROUTER_API_KEY",
    "model": "x-ai/grok-code-fast-1",
    "base_url": "https://openrouter.ai/api/v1"
  },
  "stream_output": true,
  "max_tool_iterations": 10,
  "default_permission_level": "trusted",
  "skill_timeout": 30.0,
  "max_concurrent_tools": 10,
  "permissions": {
    "default_preset": "trusted",
    "destructive_tools": ["write_file", "nexus_destroy", "nexus_shutdown"],
    "presets": {
      "dev": {
        "extends": "trusted",
        "description": "Development preset with project-scoped access",
        "allowed_paths": ["/home/user/projects"],
        "tool_permissions": {
          "nexus_shutdown": {"enabled": false}
        }
      }
    }
  }
}
```

All fields are optional - missing fields use defaults.

## Loading Logic

### Search Order (when no explicit path provided)

1. `.nexus3/config.json` - Project-local (current working directory)
2. `~/.nexus3/config.json` - Global (user home)
3. Return `Config()` with defaults if no file found

### Fail-Fast Behavior

If a config file is found but invalid, loading **fails immediately** with `ConfigError`:
- File doesn't exist (when explicit path provided)
- File exists but can't be read (OS error)
- Invalid JSON syntax
- Pydantic validation failure (including unknown fields due to `extra="forbid"`)

This prevents silent misconfiguration.

## Data Flow

```
load_config(path)
    |
    +-- path provided? --> _load_from_path(path)
    |                           |
    |                           +-- check file exists
    |                           +-- read file (UTF-8)
    |                           +-- json.loads()
    |                           +-- Config.model_validate()
    |                           +-- return Config or raise ConfigError
    |
    +-- no path --> search .nexus3/config.json, ~/.nexus3/config.json
                        |
                        +-- found? --> _load_from_path(found_path)
                        +-- not found? --> return Config() (defaults)
```

## Dependencies

- **External**: `pydantic` (validation)
- **Internal**: `nexus3.core.errors.ConfigError`

## Usage Examples

```python
from nexus3.config import load_config, Config, ProviderConfig

# Load from standard locations (project-local -> global -> defaults)
config = load_config()

# Load from explicit path
from pathlib import Path
config = load_config(Path("/path/to/config.json"))

# Access provider settings
api_key_env = config.provider.api_key_env
model = config.provider.model
base_url = config.provider.base_url

# Access performance settings
timeout = config.skill_timeout
max_concurrent = config.max_concurrent_tools
max_iterations = config.max_tool_iterations

# Access permission settings
default_preset = config.permissions.default_preset
destructive_tools = config.permissions.destructive_tools

# Create config programmatically (for testing)
config = Config(
    provider=ProviderConfig(model="anthropic/claude-sonnet-4"),
    stream_output=True,
    skill_timeout=60.0,
    max_concurrent_tools=5
)
```

### Error Handling

```python
from nexus3.config import load_config
from nexus3.core.errors import ConfigError

try:
    config = load_config()
except ConfigError as e:
    print(f"Configuration error: {e.message}")
```

### Custom Permission Presets

```python
from nexus3.config import (
    Config,
    PermissionsConfig,
    PermissionPresetConfig,
    ToolPermissionConfig,
)

# Define a custom preset in code
custom_preset = PermissionPresetConfig(
    extends="trusted",
    description="Project-specific preset",
    allowed_paths=["/home/user/myproject"],
    tool_permissions={
        "write_file": ToolPermissionConfig(
            allowed_paths=["/home/user/myproject/output"],
            timeout=10.0
        ),
        "nexus_shutdown": ToolPermissionConfig(enabled=False)
    }
)

config = Config(
    permissions=PermissionsConfig(
        default_preset="custom",
        presets={"custom": custom_preset}
    )
)
```

## Module Exports

The `__init__.py` exports:
- `Config` - Root configuration model
- `ProviderConfig` - Provider configuration model
- `ToolPermissionConfig` - Per-tool permission config
- `PermissionPresetConfig` - Custom preset config
- `PermissionsConfig` - Top-level permissions config
- `load_config` - Configuration loader function

## Built-in Permission Presets

The config schema defines settings for custom presets. Built-in presets are defined in `core/permissions.py`:

| Preset | Level | Description |
|--------|-------|-------------|
| `yolo` | YOLO | Full access, no confirmations |
| `trusted` | TRUSTED | Default. Confirmations for destructive actions |
| `sandboxed` | SANDBOXED | Limited to CWD, no network, nexus tools disabled |
| `worker` | SANDBOXED | Minimal: no write_file, no agent management |

Custom presets can extend built-ins using the `extends` field.
