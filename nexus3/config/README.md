# nexus3/config

Configuration loading and validation module for NEXUS3.

## Purpose

Robust, fail-fast configuration loading with Pydantic validation. Supports **layered merging**:

**Load Order (base → override):**
1. Shipped defaults (`&lt;install_dir&gt;/defaults/config.json`)
2. Global user (`~/.nexus3/config.json`)
3. Ancestor directories (up to `context.ancestor_depth`)
4. Project local (`CWD/.nexus3/config.json`)

**Merge**: Recursive dicts (later overrides), list concat, scalar overwrite. Validates post-merge.

## Key Exports (`from nexus3.config import *`)

- **Functions**:
  - `load_config(path=None, cwd=None) → Config`: Main entrypoint. Layers if `path=None`.
  - `load_json_file(path, error_context="") → dict`: JSON loader with error handling.

- **Constants**:
  - `DEFAULTS_DIR`, `DEFAULT_CONFIG`

- **Models**:
  - `Config`: Root. Methods: `resolve_model(alias=None)`, `find_model(alias)`, `list_models()`, `list_providers()`.
  - `ProviderConfig`: LLM providers (openrouter/openai/azure/anthropic/ollama/vllm).
  - `ModelConfig`: Per-model (`id`, `context_window`, `reasoning`).
  - `PermissionsConfig`, `PermissionPresetConfig`, `ToolPermissionConfig`: Permissions.
  - `MCPServerConfig`: External MCP servers.
  - `ContextConfig`, `CompactionConfig`, `ServerConfig`.

- **Enums**: `AuthMethod` (bearer/api-key/x-api-key/none), `ProviderType`.

## Usage Examples

### Loading
```python
from nexus3.config import load_config

config = load_config()  # Layered merge → validated Config
config = load_config(Path("myconfig.json"))  # Single file
```

### Models
```python
resolved = config.resolve_model()  # default_model
resolved = config.resolve_model("haiku")
resolved = config.resolve_model("openrouter/haiku")
print(resolved.model_id, resolved.context_window)  # e.g., "anthropic/claude-haiku-4.5" 200000
print(config.list_models())  # ["haiku", "sonnet"]
```

### Permissions/MCP
```python
print(config.permissions.default_preset)  # "trusted"
for server in config.mcp_servers:
    print(server.name, server.command)
```

## Full Schema Example
See existing README for detailed JSON example (providers, permissions, context, etc.).

## Files
- `__init__.py`: Exports.
- `load_utils.py`: `load_json_file`.
- `loader.py`: `load_config`, merging logic.
- `schema.py`: Pydantic models, `ResolvedModel`, validation.