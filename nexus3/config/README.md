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

### `Config` (schema.py)

Root configuration model:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `provider` | `ProviderConfig` | `ProviderConfig()` | LLM provider settings |
| `stream_output` | `bool` | `True` | Whether to stream responses |

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

```json
{
  "provider": {
    "type": "openrouter",
    "api_key_env": "OPENROUTER_API_KEY",
    "model": "x-ai/grok-code-fast-1",
    "base_url": "https://openrouter.ai/api/v1"
  },
  "stream_output": true
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
- Pydantic validation failure

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

# Create config programmatically (for testing)
config = Config(
    provider=ProviderConfig(model="anthropic/claude-sonnet-4"),
    stream_output=True
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

## Module Exports

The `__init__.py` exports:
- `Config` - Root configuration model
- `ProviderConfig` - Provider configuration model
- `load_config` - Configuration loader function
