# nexus3/config

Configuration loading and validation module for NEXUS3.

## Purpose

Robust, fail-fast configuration loading with Pydantic validation. Supports **layered merging**:

**Load Order (base → override):**
1. Shipped defaults (`&lt;install_dir&gt;/defaults/config.json`)
2. Global user (`~/.nexus3/config.json`)
3. Ancestor directories (up to `context.ancestor_depth`, default 2)
4. Project local (`CWD/.nexus3/config.json`)

Deep merge (later overrides earlier). Validates post-merge.

## Key Exports

`from nexus3.config import *`

**Functions:**
- `load_config(path=None, cwd=None) → Config`: Layered load or single file.
- `load_json_file(path: Path, error_context="") → dict`: Safe JSON loader.

**Constants:**
- `DEFAULTS_DIR: Path`
- `DEFAULT_CONFIG: Path`

**Models & Enums:**
- `Config`: Root. Key methods: `resolve_model(alias=None) → ResolvedModel`, `list_models()`, `list_providers()`.
- `ProviderConfig`: LLM providers (openrouter, openai, azure, anthropic, ollama, vllm).
- `PermissionsConfig`, `PermissionPresetConfig`, `ToolPermissionConfig`: Permissions.
- `MCPServerConfig`: MCP servers.
- `AuthMethod`: Auth types (bearer, api-key, x-api-key, none).

## Usage Examples

### Loading
```python
from nexus3.config import load_config

config = load_config()  # Layered → Config
config = load_config(Path("myconfig.json"))
```

### Models
```python
resolved = config.resolve_model()  # default_model
resolved = config.resolve_model("haiku")  # alias
print(resolved.model_id)  # e.g., "anthropic/claude-haiku-4.5"
print(config.list_models())  # ["haiku", "sonnet"]
```

### Permissions/MCP
```python
print(config.permissions.default_preset)  # "trusted"
for server in config.mcp_servers:
    print(server.name, server.command or server.url)
```

## Files
- `__init__.py`: Exports.
- `load_utils.py`: `load_json_file`.
- `loader.py`: `load_config`, merging.
- `schema.py`: Models, validation.