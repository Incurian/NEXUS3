# nexus3/config

Configuration loading and Pydantic validation module for NEXUS3.

## Overview

This module provides robust, fail-fast configuration loading with comprehensive validation using Pydantic models. It supports **layered merging** where configurations from multiple sources are deep-merged together, allowing project-level overrides of global settings.

### Load Order (base to override)

1. **Global user** (`~/.nexus3/config.json`) OR **Shipped defaults** (`<install_dir>/defaults/config.json`) if no global config exists
2. **Ancestor directories** (up to `context.ancestor_depth` levels above CWD, default 2)
3. **Project local** (`CWD/.nexus3/config.json`)

**Important:** Defaults are ONLY used as a fallback when no home config exists. If `~/.nexus3/config.json` exists, defaults are NOT merged.

Later layers override earlier layers using deep merge. Validation occurs after all layers are merged.

## Module Files

| File | Purpose |
|------|---------|
| `__init__.py` | Public exports |
| `schema.py` | Pydantic models for all configuration sections |
| `loader.py` | Layered configuration loading and merging |
| `load_utils.py` | Safe JSON file loading utility |

## Public Exports

```python
from nexus3.config import (
    # Functions
    load_config,              # Load and merge configuration from multiple layers
    load_json_file,           # Safe JSON file loader with error handling
    load_json_file_optional,  # Optional JSON loader (returns None if missing)

    # Constants
    DEFAULTS_DIR,     # Path to shipped defaults directory
    DEFAULT_CONFIG,   # Path to default config.json

    # Root config model
    Config,           # Root configuration with all settings

    # Provider models
    ProviderConfig,   # LLM provider configuration
    AuthMethod,       # Authentication method enum

    # Permission models
    PermissionsConfig,        # Top-level permissions configuration
    PermissionPresetConfig,   # Custom permission preset configuration
    ToolPermissionConfig,     # Per-tool permission configuration

    # MCP models
    MCPServerConfig,  # MCP server configuration
)
```

**Note:** `ModelConfig`, `ResolvedModel`, `ProviderType`, `ClipboardConfig`, `ContextConfig`, `CompactionConfig`, `ServerConfig`, `GitLabConfig`, and `GitLabInstanceConfig` are defined in `schema.py` but not exported from the package. Import them directly from `nexus3.config.schema` if needed.

---

## Functions

### `load_config(path: Path | None = None, cwd: Path | None = None) -> Config`

Load configuration with layered merging.

**Parameters:**
- `path`: Explicit config file path. If provided, skips layered loading and loads only from this file.
- `cwd`: Working directory for ancestor/local lookup. Defaults to `Path.cwd()`.

**Returns:** Validated `Config` object.

**Raises:** `ConfigError` if any config file contains invalid JSON or merged config fails validation.

**Example:**
```python
from nexus3.config import load_config
from pathlib import Path

# Layered load (default behavior)
config = load_config()

# Load from explicit path
config = load_config(Path("/path/to/config.json"))

# Layered load with custom working directory
config = load_config(cwd=Path("/path/to/project"))
```

### `load_json_file(path: Path, error_context: str = "") -> dict[str, Any]`

Load and parse a JSON file with consistent error handling.

**Parameters:**
- `path`: Path to the JSON file to load.
- `error_context`: Optional context string for error messages (e.g., "config", "mcp").

**Returns:** Parsed JSON as a dict. Returns empty dict if file is empty.

**Raises:** `LoadError` if the file doesn't exist, can't be read, contains invalid JSON, or contains non-dict JSON.

**Note:** Uses `utf-8-sig` encoding to automatically handle Windows UTF-8 BOM (Byte Order Mark). See [Windows Compatibility](#windows-compatibility) section.

**Example:**
```python
from nexus3.config import load_json_file
from pathlib import Path

data = load_json_file(Path("settings.json"), error_context="settings")
```

### `load_json_file_optional(path: Path, error_context: str = "") -> dict[str, Any] | None`

Load JSON file if it exists, returning None for missing files.

Use this for optional config layers (global, ancestor, local) where the file may or may not exist.

**Parameters:**
- `path`: Path to the JSON file to load.
- `error_context`: Optional context string for error messages.

**Returns:** Parsed JSON as dict, empty dict for empty files, or None if file missing.

**Raises:** `LoadError` if file exists but can't be read or contains invalid JSON.

**Note:** Uses `Path.resolve()` for Windows/Git Bash compatibility where paths may have different formats (e.g., `/c/Users/...`).

**Example:**
```python
from nexus3.config import load_json_file_optional
from pathlib import Path

# Returns None if file doesn't exist
data = load_json_file_optional(Path("~/.nexus3/config.json"))
if data is not None:
    # Process config
    pass
```

---

## Configuration Schema

### `Config` (Root Model)

The root configuration model containing all NEXUS3 settings.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `default_model` | `str` | `"haiku"` | Default model alias (or `provider/alias` format) |
| `providers` | `dict[str, ProviderConfig]` | `{}` | Provider configurations with their models |
| `stream_output` | `bool` | `True` | Enable streaming output |
| `max_tool_iterations` | `int` | `10` | Maximum tool iterations per turn |
| `default_permission_level` | `str` | `"trusted"` | Default permission level |
| `skill_timeout` | `float` | `30.0` | Default skill timeout in seconds |
| `max_concurrent_tools` | `int` | `10` | Maximum concurrent tool executions |
| `permissions` | `PermissionsConfig` | `PermissionsConfig()` | Permission system configuration |
| `compaction` | `CompactionConfig` | `CompactionConfig()` | Context compaction settings |
| `clipboard` | `ClipboardConfig` | `ClipboardConfig()` | Clipboard system configuration |
| `context` | `ContextConfig` | `ContextConfig()` | Context loading settings |
| `mcp_servers` | `list[MCPServerConfig]` | `[]` | MCP server configurations |
| `server` | `ServerConfig` | `ServerConfig()` | HTTP server configuration |
| `gitlab` | `GitLabConfig` | `GitLabConfig()` | GitLab integration configuration |

**Key Methods:**

```python
# Resolve a model alias to full settings
resolved = config.resolve_model()  # Uses default_model
resolved = config.resolve_model("haiku")
resolved = config.resolve_model("openrouter/haiku")  # Explicit provider/alias

# List available models and providers
aliases = config.list_models()  # ["haiku", "sonnet", "gpt"]
providers = config.list_providers()  # ["openrouter", "anthropic"]

# Get provider configuration
provider = config.get_provider_config("openrouter")

# Find which provider owns an alias
provider_name, model_config = config.find_model("haiku")

# Get model guidance table for prompt injection
# Returns: [(alias, context_window, guidance), ...]
models = config.get_model_guidance_table()
```

**Validation:**
- Ensures model aliases are globally unique across all providers
- Validates that `default_model` references a valid alias

---

### `ProviderConfig`

Configuration for an LLM provider.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | `ProviderType` | `"openrouter"` | Provider type |
| `api_key_env` | `str` | `"OPENROUTER_API_KEY"` | Environment variable containing API key |
| `base_url` | `str` | `"https://openrouter.ai/api/v1"` | Base URL for API requests |
| `auth_method` | `AuthMethod` | `BEARER` | How to send the API key |
| `extra_headers` | `dict[str, str]` | `{}` | Additional headers for API requests |
| `api_version` | `str \| None` | `None` | API version string (for Azure) |
| `deployment` | `str \| None` | `None` | Azure deployment name |
| `request_timeout` | `float` | `120.0` | Request timeout in seconds |
| `max_retries` | `int` | `3` | Max retry attempts (0-10) |
| `retry_backoff` | `float` | `1.5` | Exponential backoff multiplier (1.0-5.0) |
| `allow_insecure_http` | `bool` | `False` | Allow HTTP for non-localhost URLs |
| `prompt_caching` | `bool` | `True` | Enable prompt caching (~90% savings on cached tokens) |
| `verify_ssl` | `bool` | `True` | Verify SSL certificates (false for self-signed) |
| `ssl_ca_cert` | `str \| None` | `None` | Path to CA certificate for SSL verification |
| `models` | `dict[str, ModelConfig]` | `{}` | Model aliases for this provider |

**Supported Provider Types:**
- `openrouter` - OpenRouter.ai
- `openai` - Direct OpenAI API
- `azure` - Azure OpenAI Service
- `anthropic` - Anthropic Claude API
- `ollama` - Local Ollama server
- `vllm` - vLLM OpenAI-compatible server

### `AuthMethod` (Enum)

Authentication method for API requests.

| Value | Header Format | Use Case |
|-------|---------------|----------|
| `BEARER` | `Authorization: Bearer <key>` | OpenRouter, OpenAI, most APIs |
| `API_KEY` | `api-key: <key>` | Azure OpenAI |
| `X_API_KEY` | `x-api-key: <key>` | Anthropic |
| `NONE` | No auth header | Local Ollama |

### `ModelConfig`

Configuration for a model under a provider.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | `str` | (required) | Full model identifier sent to API |
| `context_window` | `int` | `131072` | Context window size in tokens |
| `reasoning` | `bool` | `False` | Enable extended thinking/reasoning |
| `guidance` | `str \| None` | `None` | Usage guidance for the model |

### `ResolvedModel`

Result of resolving a model alias (not a Pydantic model).

| Attribute | Type | Description |
|-----------|------|-------------|
| `model_id` | `str` | Full model identifier |
| `context_window` | `int` | Context window size |
| `reasoning` | `bool` | Whether reasoning is enabled |
| `alias` | `str` | The alias that was resolved |
| `provider_name` | `str` | Name of the provider |
| `guidance` | `str \| None` | Usage guidance |

---

### `PermissionsConfig`

Top-level permissions configuration.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `default_preset` | `str` | `"sandboxed"` | Default permission preset |
| `presets` | `dict[str, PermissionPresetConfig]` | `{}` | Custom permission presets |
| `destructive_tools` | `list[str]` | See below | Tools that require confirmation |

**Default Destructive Tools:**
- `write_file`, `edit_file`, `bash_safe`, `shell_UNSAFE`, `run_python`, `nexus_destroy`, `nexus_shutdown`

### `PermissionPresetConfig`

Custom permission preset configuration.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `extends` | `str \| None` | `None` | Base preset to extend |
| `description` | `str` | `""` | Human-readable description |
| `allowed_paths` | `list[str] \| None` | `None` | Path restrictions (`None` = unrestricted, `[]` = deny all) |
| `blocked_paths` | `list[str]` | `[]` | Always blocked paths |
| `network_access` | `bool \| None` | `None` | Network access (derived from level) |
| `tool_permissions` | `dict[str, ToolPermissionConfig]` | `{}` | Per-tool configuration |
| `default_tool_timeout` | `float \| None` | `None` | Default timeout for tools |

**Path Normalization:**
- `~` is expanded to home directory
- Paths are converted to absolute paths
- Warnings are issued for non-existent or non-directory paths

### `ToolPermissionConfig`

Per-tool permission configuration.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `True` | Whether the tool is enabled |
| `allowed_paths` | `list[str] \| None` | `None` | Tool-specific path restrictions |
| `timeout` | `float \| None` | `None` | Tool-specific timeout |
| `requires_confirmation` | `bool \| None` | `None` | Override confirmation requirement |

---

### `CompactionConfig`

Configuration for context compaction/summarization.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `True` | Enable automatic compaction |
| `model` | `str \| None` | `None` | Model alias for summarization (`None` = use default) |
| `summary_budget_ratio` | `float` | `0.25` | Ratio of available budget for summary |
| `recent_preserve_ratio` | `float` | `0.25` | Ratio to preserve as recent messages |
| `trigger_threshold` | `float` | `0.9` | Compact when context exceeds this ratio |
| `redact_secrets` | `bool` | `True` | Redact secrets before summarization |

### `ClipboardConfig`

Configuration for the clipboard system.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `True` | Enable clipboard tools |
| `inject_into_context` | `bool` | `True` | Auto-inject clipboard index into system prompt |
| `max_injected_entries` | `int` | `10` | Maximum entries to show per scope in context injection (0-50) |
| `show_source_in_injection` | `bool` | `True` | Show source path/lines in context injection |
| `max_entry_bytes` | `int` | `1048576` | Maximum size of a single clipboard entry (1KB-10MB) |
| `warn_entry_bytes` | `int` | `102400` | Size threshold for warning on large entries |
| `default_ttl_seconds` | `int \| None` | `None` | Default TTL for new entries (None = permanent) |

### `ContextConfig`

Configuration for context loading.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `ancestor_depth` | `int` | `2` | Directory levels above CWD to search (0-10) |
| `include_readme` | `bool` | `False` | Always include README.md |
| `readme_as_fallback` | `bool` | `False` | Use README when no NEXUS.md exists (opt-in for security) |

### `ServerConfig`

Configuration for the HTTP server.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | `str` | `"127.0.0.1"` | Host address to bind to |
| `port` | `int` | `8765` | Port number (1-65535) |
| `log_level` | `Literal` | `"INFO"` | Logging level (DEBUG/INFO/WARNING/ERROR) |

### `MCPServerConfig`

Configuration for an MCP (Model Context Protocol) server.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | (required) | Friendly name for the server |
| `command` | `str \| list[str] \| None` | `None` | Command for stdio transport (see formats below) |
| `args` | `list[str] \| None` | `None` | Arguments when command is a string (official format) |
| `url` | `str \| None` | `None` | URL for HTTP transport |
| `env` | `dict[str, str] \| None` | `None` | Explicit environment variables |
| `env_passthrough` | `list[str] \| None` | `None` | Host env vars to pass through |
| `cwd` | `str \| None` | `None` | Working directory for server subprocess |
| `enabled` | `bool` | `True` | Whether server is enabled |

**Command formats:** Two formats are supported for the `command` field:

1. **NEXUS3 format:** Command as a list
   ```json
   {"command": ["npx", "-y", "@anthropic/mcp-server-github"]}
   ```

2. **Official MCP format:** Command as string with separate `args` array
   ```json
   {"command": "npx", "args": ["-y", "@anthropic/mcp-server-github"]}
   ```

**Method:** `get_command_list() -> list[str]` - Returns the command as a list regardless of which format was used.

**Validation:** Exactly one of `command` or `url` must be set.

**Security:** MCP servers receive only safe environment variables by default (PATH, HOME, USER, etc.). Use `env` for explicit values or `env_passthrough` to copy from host.

### `GitLabConfig`

Top-level GitLab configuration supporting multiple instances.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `instances` | `dict[str, GitLabInstanceConfig]` | `{}` | Named GitLab instance configurations |
| `default_instance` | `str \| None` | `None` | Name of the default instance to use when not specified |

**Validation:** If `default_instance` is set, it must reference an existing instance in `instances`.

### `GitLabInstanceConfig`

Configuration for a single GitLab instance.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | `str` | `"https://gitlab.com"` | Base URL for the GitLab instance |
| `token_env` | `str \| None` | `None` | Environment variable containing the GitLab API token |
| `token` | `str \| None` | `None` | Direct token value (NOT RECOMMENDED - use `token_env`) |

**Validation:** At least one of `token` or `token_env` must be specified. If both are set, `token` takes precedence.

**Security:** Store GitLab tokens in environment variables (via `token_env`), not directly in config files.

---

## Usage Examples

### Multi-Provider Configuration

```json
{
  "default_model": "haiku",
  "providers": {
    "openrouter": {
      "type": "openrouter",
      "api_key_env": "OPENROUTER_API_KEY",
      "models": {
        "haiku": {
          "id": "anthropic/claude-haiku-4.5",
          "context_window": 200000,
          "guidance": "Fast and cheap. Good for research tasks."
        },
        "sonnet": {
          "id": "anthropic/claude-sonnet-4",
          "context_window": 200000,
          "guidance": "Balanced. Good for most tasks."
        }
      }
    },
    "anthropic": {
      "type": "anthropic",
      "api_key_env": "ANTHROPIC_API_KEY",
      "auth_method": "x-api-key",
      "base_url": "https://api.anthropic.com/v1",
      "models": {
        "haiku-native": {
          "id": "claude-haiku-4-5",
          "context_window": 200000
        }
      }
    },
    "local": {
      "type": "ollama",
      "base_url": "http://localhost:11434/v1",
      "auth_method": "none",
      "models": {
        "llama": {
          "id": "llama3.2",
          "context_window": 128000
        }
      }
    }
  }
}
```

### Custom Permission Preset

```json
{
  "permissions": {
    "default_preset": "sandboxed",
    "presets": {
      "researcher": {
        "extends": "sandboxed",
        "description": "Read-only research agent",
        "allowed_paths": ["~/projects"],
        "tool_permissions": {
          "write_file": {"enabled": false},
          "edit_file": {"enabled": false},
          "bash_safe": {"timeout": 10}
        }
      }
    }
  }
}
```

### MCP Server Configuration

```json
{
  "mcp_servers": [
    {
      "name": "github",
      "command": ["npx", "-y", "@anthropic/mcp-server-github"],
      "env_passthrough": ["GITHUB_TOKEN"]
    },
    {
      "name": "postgres",
      "command": ["npx", "-y", "@anthropic/mcp-server-postgres"],
      "env": {"DATABASE_URL": "postgresql://localhost/mydb"}
    }
  ]
}
```

### GitLab Configuration

```json
{
  "gitlab": {
    "instances": {
      "default": {
        "url": "https://gitlab.com",
        "token_env": "GITLAB_TOKEN"
      },
      "work": {
        "url": "https://gitlab.company.com",
        "token_env": "WORK_GITLAB_TOKEN"
      }
    },
    "default_instance": "default"
  }
}
```

### Clipboard Configuration

```json
{
  "clipboard": {
    "enabled": true,
    "inject_into_context": true,
    "max_injected_entries": 10,
    "default_ttl_seconds": 3600
  }
}
```

### Resolving Models

```python
from nexus3.config import load_config

config = load_config()

# Use default model
resolved = config.resolve_model()
print(f"Model: {resolved.model_id}")
print(f"Provider: {resolved.provider_name}")
print(f"Context: {resolved.context_window}")

# Resolve specific alias
resolved = config.resolve_model("sonnet")

# Explicit provider/alias format
resolved = config.resolve_model("anthropic/haiku-native")

# List all available models
for alias in config.list_models():
    resolved = config.resolve_model(alias)
    print(f"{alias}: {resolved.model_id} ({resolved.provider_name})")
```

---

## Dependencies

### Internal Dependencies

- `nexus3.core.constants` - `get_defaults_dir()`, `get_nexus_dir()`
- `nexus3.core.errors` - `ConfigError`, `LoadError`
- `nexus3.core.utils` - `deep_merge()`, `find_ancestor_config_dirs()`

### External Dependencies

- `pydantic` - Model validation and serialization

---

## Error Handling

The module uses two error types from `nexus3.core.errors`:

- **`ConfigError`**: Raised by `load_config()` for configuration-specific errors (invalid JSON, validation failures, missing files when path is explicit).
- **`LoadError`**: Raised by `load_json_file()` for general file loading errors.

Both errors inherit from `NexusError` and are designed for fail-fast behavior.

---

## Windows Compatibility

### BOM Handling

All JSON file loading in this module uses `utf-8-sig` encoding to automatically handle Windows UTF-8 BOM (Byte Order Mark).

**Background:** Windows applications (notably Notepad and PowerShell) often add a UTF-8 BOM (the bytes `EF BB BF`) to the beginning of text files. Standard `utf-8` encoding treats these bytes as content, causing JSON parsing to fail with errors like:

```
Invalid JSON: Unexpected UTF-8 BOM (decode using utf-8-sig)
```

**Solution:** The `utf-8-sig` codec automatically strips the BOM if present, and works identically to `utf-8` for files without a BOM. This ensures cross-platform compatibility without requiring users to manually fix their config files.

**Affected functions:**
- `load_json_file()` in `load_utils.py`
- `load_json_file_optional()` in `load_utils.py`

---

## Related Modules

- `nexus3/context/` - Uses `ContextConfig` for loading NEXUS.md prompts
- `nexus3/provider/` - Uses `ProviderConfig` to instantiate LLM providers
- `nexus3/session/` - Uses `PermissionsConfig` for permission enforcement
- `nexus3/rpc/` - Uses `ServerConfig` for HTTP server settings
- `nexus3/mcp/` - Uses `MCPServerConfig` to launch MCP servers
- `nexus3/clipboard/` - Uses `ClipboardConfig` for clipboard system settings
- `nexus3/skill/builtins/gitlab/` - Uses `GitLabConfig` for GitLab API integration

---

Last updated: 2026-02-10
