# nexus3/config

Configuration loading and validation module for NEXUS3.

## Purpose

This module provides fail-fast configuration loading with Pydantic validation. It supports layered configuration with deep merging:

**Load Order (earlier layers are base, later override):**
1. **Shipped defaults** (`nexus3/defaults/config.json`)
2. **Global user** (`~/.nexus3/config.json`)
3. **Ancestor directories** (up to N levels above CWD, configurable)
4. **Project local** (`CWD/.nexus3/config.json`)

**Merge behavior:**
- Dicts are recursively merged (local keys override, global preserved)
- Lists are concatenated (not replaced)
- Other values are overwritten by later layers

## Key Types/Classes

### `ModelAliasConfig` (schema.py)

Model aliases for friendly names.

| Field            | Type     | Default | Description |
|------------------|----------|---------|-------------|
| `id`             | `str`    | -       | Full model identifier (e.g., `x-ai/grok-code-fast-1`) |
| `context_window` | `int \| None` | `None` | Context window size (uses provider default if None) |
| `reasoning`      | `bool \| None` | `None` | Enable extended thinking (uses provider default if None) |

### `ProviderConfig` (schema.py)

LLM provider configuration. Supports multiple provider types with configurable authentication.

| Field            | Type            | Default                  | Description |
|------------------|-----------------|--------------------------|-------------|
| `type`           | `str`           | `openrouter`             | Provider type: openrouter, openai, azure, anthropic, ollama, vllm |
| `api_key_env`    | `str`           | `OPENROUTER_API_KEY`     | Env var for API key |
| `model`          | `str`           | `x-ai/grok-code-fast-1`  | Default model ID or alias |
| `base_url`       | `str`           | `https://openrouter.ai/api/v1` | API base URL |
| `context_window` | `int`           | `131072`                 | Default context window |
| `reasoning`      | `bool`          | `False`                  | Default reasoning mode |
| `auth_method`    | `AuthMethod`    | `bearer`                 | How to send API key: bearer, api-key, x-api-key, none |
| `extra_headers`  | `dict[str,str]` | `{}`                     | Additional HTTP headers |
| `api_version`    | `str \| None`   | `None`                   | API version (for Azure) |
| `deployment`     | `str \| None`   | `None`                   | Deployment name (for Azure) |

**AuthMethod enum:** `bearer` (Authorization: Bearer), `api-key` (api-key header), `x-api-key` (x-api-key header), `none` (no auth)

### `ToolPermissionConfig` (schema.py)

Per-tool permissions.

| Field                  | Type              | Default | Description |
|------------------------|-------------------|---------|-------------|
| `enabled`              | `bool`            | `True`  | Enable tool |
| `allowed_paths`        | `list[str] \| None` | `None` | Paths tool can access (`None`=inherit, `[]`=deny all) |
| `timeout`              | `float \| None`   | `None`  | Tool timeout (inherits preset/global) |
| `requires_confirmation`| `bool \| None`    | `None`  | Override confirmation prompt |

**`allowed_paths` semantics:** `None`/omitted=inherit, `[]`=deny all, `["path", ...]`=restrict to these dirs.

### `PermissionPresetConfig` (schema.py)

Custom permission presets.

| Field                  | Type              | Default | Description |
|------------------------|-------------------|---------|-------------|
| `extends`              | `str \| None`     | `None`  | Base preset to extend |
| `description`          | `str`             | `""`    | Description |
| `allowed_paths`        | `list[str] \| None` | `None` | Allowed paths (`None`=unrestricted, `[]`=deny all) |
| `blocked_paths`        | `list[str]`       | `[]`    | Explicitly blocked paths |
| `network_access`       | `bool \| None`    | `None`  | Network access (derived from level) |
| `tool_permissions`     | `dict[str, ToolPermissionConfig]` | `{}` | Per-tool overrides |
| `default_tool_timeout` | `float \| None`   | `None`  | Preset default timeout |

### `PermissionsConfig` (schema.py)

Top-level permissions.

| Field             | Type                            | Default                                                                 | Description |
|-------------------|---------------------------------|-------------------------------------------------------------------------|-------------|
| `default_preset`  | `str`                           | `trusted`                                                               | Default for new agents |
| `presets`         | `dict[str, PermissionPresetConfig]` | `{}`                                                                    | Custom presets |
| `destructive_tools` | `list[str]`                  | `["write_file", "edit_file", "bash", "run_python", "nexus_destroy", "nexus_shutdown"]` | Tools needing confirmation |

### `CompactionConfig` (schema.py)

Context compaction settings.

| Field                  | Type     | Default | Description |
|------------------------|----------|---------|-------------|
| `enabled`              | `bool`   | `True`  | Enable auto-compaction |
| `model`                | `str \| None` | `None` | Compaction model (uses provider.model if None) |
| `summary_budget_ratio` | `float`  | `0.25`  | Budget ratio for summary |
| `recent_preserve_ratio`| `float`  | `0.25`  | Ratio of recent messages to preserve |
| `trigger_threshold`    | `float`  | `0.9`   | Compact when context > this budget ratio |

### `ContextConfig` (schema.py)

Context loading settings.

| Field                  | Type     | Default | Description |
|------------------------|----------|---------|-------------|
| `ancestor_depth`       | `int`    | `2`     | How many parent dirs to check for .nexus3/ (0-10) |
| `include_readme`       | `bool`   | `False` | Always include README.md in context |
| `readme_as_fallback`   | `bool`   | `True`  | Use README.md when no NEXUS.md exists |

### `MCPServerConfig` (schema.py)

MCP (Model Context Protocol) server configs for external tools.

**SECURITY:** MCP servers receive only safe environment variables by default (PATH, HOME, USER, LANG, etc.). This prevents accidental API key leakage. To pass additional vars:
- Use `env` for explicit key-value pairs (e.g., secrets from config)
- Use `env_passthrough` to copy specific vars from host environment

| Field           | Type              | Default | Description |
|-----------------|-------------------|---------|-------------|
| `name`          | `str`             | -       | Server name (skill prefix) |
| `command`       | `list[str] \| None` | `None` | Stdio command |
| `url`           | `str \| None`     | `None`  | HTTP URL (future) |
| `env`           | `dict[str, str] \| None` | `None` | Explicit env vars (highest priority) |
| `env_passthrough` | `list[str] \| None` | `None` | Host env vars to pass through |
| `enabled`       | `bool`            | `True`  | Enabled |

### `Config` (schema.py)

Root config.

| Field                  | Type                            | Default             | Description |
|------------------------|---------------------------------|---------------------|-------------|
| `provider`             | `ProviderConfig`                | `ProviderConfig()`  | LLM provider |
| `models`               | `dict[str, ModelAliasConfig]`   | `{}`                | Model aliases |
| `stream_output`        | `bool`                          | `True`              | Stream responses |
| `max_tool_iterations`  | `int`                           | `10`                | Max tool loop iterations |
| `default_permission_level` | `str`                      | `trusted`           | Default level (yolo/trusted/sandboxed) |
| `skill_timeout`        | `float`                         | `30.0`              | Global timeout (0=no) |
| `max_concurrent_tools` | `int`                           | `10`                | Max parallel tools |
| `permissions`          | `PermissionsConfig`             | `PermissionsConfig()` | Permissions |
| `compaction`           | `CompactionConfig`              | `CompactionConfig()` | Compaction |
| `mcp_servers`          | `list[MCPServerConfig]`         | `[]`                | MCP servers |

**Key methods:**
- `resolve_model(name_or_id: str | None) -> ResolvedModel`: Resolve alias or use defaults.
- `list_models() -> list[str]`: List aliases.

### `load_config(path: Path | None = None) -> Config` (loader.py)

Load config with search fallback.

**Search order (path=None):**
1. `.nexus3/config.json` (project-local)
2. `~/.nexus3/config.json` (user global)
3. `<install>/defaults/config.json` (shipped)

**Raises:** `ConfigError` on invalid file.

## Full Schema Example

```json
{
  "provider": {
    "type": "openrouter",
    "model": "x-ai/grok-code-fast-1",
    "context_window": 131072,
    "reasoning": false
  },
  "models": {
    "fast": { "id": "x-ai/grok-code-fast-1", "context_window": 131072 },
    "smart": { "id": "anthropic/claude-sonnet-4", "context_window": 200000, "reasoning": true }
  },
  "stream_output": true,
  "max_tool_iterations": 10,
  "default_permission_level": "trusted",
  "skill_timeout": 30.0,
  "max_concurrent_tools": 10,
  "permissions": {
    "default_preset": "trusted",
    "presets": {
      "dev": {
        "extends": "trusted",
        "description": "Project access",
        "allowed_paths": ["/home/user/project"],
        "tool_permissions": { "nexus_shutdown": { "enabled": false } }
      }
    }
  },
  "compaction": {
    "enabled": true,
    "model": "fast",
    "summary_budget_ratio": 0.25
  },
  "mcp_servers": [
    {
      "name": "postgres",
      "command": ["npx", "-y", "@anthropic/mcp-server-postgres"],
      "env": { "DATABASE_URL": "postgresql://localhost/db" }
    },
    {
      "name": "github",
      "command": ["npx", "-y", "@anthropic/mcp-server-github"],
      "env_passthrough": ["GITHUB_TOKEN"]
    }
  ]
}
```

## Loading Logic

```
load_config(path)
    |
    +-- path? --> _load_from_path(path)
    |
    +-- search: .nexus3/config.json → ~/.nexus3/config.json → defaults/config.json
                        |
                        +-- found & valid --> return Config
                        +-- invalid --> raise ConfigError
                        +-- none found --> Config() defaults
```

## Usage Examples

```python
from nexus3.config import load_config, Config

# Load (project → global → defaults → pydantic defaults)
config = load_config()

# Explicit path
config = load_config(Path("myconfig.json"))

# Model resolution
resolved = config.resolve_model("fast")  # Uses models['fast']
print(resolved.model_id, resolved.context_window)

# List aliases
print(config.list_models())  # ['fast', 'smart']

# Provider access
print(config.provider.model)

# Compaction
print(config.compaction.enabled)

# MCP servers
for server in config.mcp_servers:
    print(server.name)
```

### Error Handling

```python
from nexus3.core.errors import ConfigError

try:
    config = load_config()
except ConfigError as e:
    print(f"Config error: {e}")
```

## Module Exports (`__init__.py`)

- `Config`, `ProviderConfig`, `ToolPermissionConfig`, `PermissionPresetConfig`, `PermissionsConfig`, `MCPServerConfig`
- `load_config`
- `DEFAULT_CONFIG`, `DEFAULTS_DIR`

## Built-in Presets (defined in `core/permissions.py`)

| Preset     | Level     | Access |
|------------|-----------|--------|
| `yolo`     | YOLO      | Full, no confirms |
| `trusted`  | TRUSTED   | CWD auto-allowed, prompts others |
| `sandboxed`| SANDBOXED | Read-only CWD, no exec/network |

Custom presets extend via `extends`.

## `allowed_paths` Semantics

| JSON     | Python     | Meaning |
|----------|------------|---------|
| `null`/omit | `None` | Unrestricted (preset) / inherit (tool) |
| `[]`     | `[]`     | Deny all |
| `["/dir"]` | `["/dir"]` | Restrict to dir(s) |

Applies to presets/tools.
