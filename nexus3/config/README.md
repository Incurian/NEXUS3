# nexus3/config

Configuration loading and validation module for NEXUS3.

## Purpose

This module provides robust, fail-fast configuration loading with Pydantic validation. It supports **layered configuration merging**:

**Load Order (base → override):**
1. Shipped defaults (`&lt;install_dir&gt;/defaults/config.json`)
2. Global user (`~/.nexus3/config.json`)
3. Ancestor directories (up to `context.ancestor_depth` levels above CWD)
4. Project local (`CWD/.nexus3/config.json`)

**Merge behavior** (via `deep_merge`):
- Dicts: Recursive merge (later overrides earlier)
- Lists: Concatenation
- Scalars: Overwrite

Validation occurs post-merge. Invalid JSON or schema errors raise `ConfigError`.

## Key Modules & Exports

### `__init__.py`
Exports all key symbols for `from nexus3.config import *`.

### `loader.py`
- `DEFAULTS_DIR`: Path to shipped defaults.
- `DEFAULT_CONFIG`: `DEFAULTS_DIR / "config.json"`.
- `load_config(path: Path | None = None, cwd: Path | None = None) -> Config`: Main entrypoint.

### `schema.py`
Pydantic models (partial list):

| Model | Description |
|-------|-------------|
| `Config` | Root config. Key methods: `resolve_model()`, `find_model()`, `list_models()`. |
| `ProviderConfig` | LLM providers (openrouter/openai/azure/anthropic/ollama/vllm). |
| `ModelConfig` | Per-model aliases (`id`, `context_window`, `reasoning`). |
| `PermissionsConfig` / `PermissionPresetConfig` / `ToolPermissionConfig` | Fine-grained tool/path permissions. |
| `MCPServerConfig` | External MCP tool servers. |
| `ContextConfig` / `CompactionConfig` / `ServerConfig` | Context, compaction, server settings. |

**AuthMethod enum**: `bearer`, `api-key`, `x-api-key`, `none`.

**ProviderType**: `"openrouter" \| "openai" \| "azure" \| "anthropic" \| "ollama" \| "vllm"`.

## Dependencies

- **External**: `pydantic`
- **Internal**: `nexus3.core.{constants, errors, utils}`
- **Stdlib**: `json`, `pathlib`, `typing`, `os`, `warnings`, `enum`

## Architecture Summary

```
load_config()
├── path provided? ── YES ──> _load_from_path(path) ──> Config()
└── NO ──> Merge layers:
    ├── 1. DEFAULT_CONFIG (shipped)
    ├── 2. ~/.nexus3/config.json (global)
    ├── 3. Ancestors (find_ancestor_config_dirs(cwd, depth))
    └── 4. cwd/.nexus3/config.json (local)
    └── deep_merge(all) ──> Config.model_validate()
```

**Model Resolution**:
```
alias ("haiku" or "openrouter/haiku")
├── "/" ? ──> provider/alias lookup
└── Search providers.models ──> ResolvedModel(model_id, context_window, ...)
```

**Permissions**:
- Presets: `yolo`/`trusted`/`sandboxed` (built-in, extendable).
- `allowed_paths`: `None`=inherit/unrestricted, `[]`=deny-all, `["/dir"]`=restrict.
- Paths normalized to absolute (with warnings).

## Usage Examples

### Basic Loading
```python
from pathlib import Path
from nexus3.config import load_config, Config

# Layered load (recommended)
config = load_config()  # Merges all layers → validated Config

# Explicit file
config = load_config(Path("myconfig.json"))

# No files → pydantic defaults
config = load_config()  # Config(default_model="haiku", ...)
```

### Model Resolution
```python
# Default model
resolved = config.resolve_model()  # Uses config.default_model

# Alias
resolved = config.resolve_model("haiku")

# Provider/alias
resolved = config.resolve_model("openrouter/haiku")

print(resolved.model_id)  # e.g., "anthropic/claude-haiku-4.5"
print(resolved.context_window)  # e.g., 200000
```

### List Models/Providers
```python
print(config.list_models())  # ["haiku", "sonnet"]
print(config.list_providers())  # ["openrouter", "anthropic"]
```

### Permissions & MCP
```python
print(config.permissions.default_preset)  # "trusted"

for server in config.mcp_servers:
    print(f"{server.name}: {' '.join(server.command or [])}")
```

### Error Handling
```python
from nexus3.core.errors import ConfigError

try:
    config = load_config()
except ConfigError as e:
    print(f"Config failed: {e}")
```

## Full Config Schema Example

```json
{
  "default_model": "haiku",
  "providers": {
    "openrouter": {
      "type": "openrouter",
      "api_key_env": "OPENROUTER_API_KEY",
      "base_url": "https://openrouter.ai/api/v1",
      "auth_method": "bearer",
      "models": {
        "haiku": {
          "id": "anthropic/claude-haiku-4.5",
          "context_window": 200000,
          "reasoning": false
        }
      }
    }
  },
  "permissions": {
    "default_preset": "trusted",
    "presets": {
      "project": {
        "extends": "trusted",
        "description": "Project-only access",
        "allowed_paths": ["/home/user/project"],
        "tool_permissions": {
          "write_file": {"enabled": false}
        }
      }
    }
  },
  "context": {
    "ancestor_depth": 2,
    "include_readme": true
  },
  "mcp_servers": [
    {
      "name": "github",
      "command": ["npx", "-y", "@anthropic/mcp-server-github"],
      "env_passthrough": ["GITHUB_TOKEN"]
    }
  ],
  "server": {
    "host": "127.0.0.1",
    "port": 8765
  }
}
```

## Security Notes

- **Paths**: Normalized to absolute; non-existent dirs warned.
- **MCP Servers**: Safe env vars only (PATH, HOME, etc.). Use `env`/`env_passthrough` explicitly.
- **Destructive Tools**: `write_file`, `bash_safe`, etc. require confirmation (configurable).
- **Validation**: Ensures unique model aliases, valid default_model.

See `nexus3/core/permissions.py` for built-in presets.
