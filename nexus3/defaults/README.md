# NEXUS3 Defaults Module

## Overview

The `nexus3/defaults/` directory contains the **shipped default configuration and system prompt** that NEXUS3 uses when no user configuration exists. These files serve as:

1. **Fallback configuration** when no `~/.nexus3/` or `./.nexus3/` exists
2. **Templates** for `nexus3 --init-global` to copy to `~/.nexus3/`
3. **Reference implementation** showing all available configuration options

## Files

| File | Purpose |
|------|---------|
| `__init__.py` | Package marker (docstring only, no exports) |
| `config.json` | Default LLM providers, models, and settings |
| `NEXUS.md` | Default agent system prompt |

## Configuration Loading Hierarchy

Defaults are the **lowest priority** layer in the config loading hierarchy:

```
LAYER 1: Package defaults (this directory) <- LOWEST PRIORITY
    |
LAYER 2: Global (~/.nexus3/)
    |
LAYER 3: Ancestors (up to N levels above CWD)
    |
LAYER 4: Local (CWD/.nexus3/) <- HIGHEST PRIORITY
```

Later layers **deep-merge** into earlier layers, meaning:
- Scalar values (strings, numbers, booleans) are replaced
- Objects are recursively merged
- Unspecified keys inherit from earlier layers

### Loading Logic

The `ContextLoader` in `nexus3/context/loader.py` handles defaults:

```python
def _load_global_layer(self) -> ContextLayer | None:
    """Load the global layer with fallback to defaults."""
    global_dir = self._get_global_dir()  # ~/.nexus3/

    if global_dir.is_dir():
        layer = self._load_layer(global_dir, "global")
        if layer.prompt or layer.config or layer.mcp:
            return layer  # Use global config if it has content

    # Fall back to install defaults
    defaults_dir = self._get_defaults_dir()  # nexus3/defaults/
    if defaults_dir.is_dir():
        return self._load_layer(defaults_dir, "defaults")

    return None
```

The config loader in `nexus3/config/loader.py` similarly starts from defaults:

```python
# Layer 1: Shipped defaults
default_data = load_json_file_optional(DEFAULT_CONFIG)  # nexus3/defaults/config.json
if default_data:
    merged = deep_merge(merged, default_data)
```

---

## config.json Structure

### Top-Level Settings

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `default_model` | `string` | `"fast"` | Default model alias (or `provider/alias` format) |
| `stream_output` | `bool` | `true` | Stream responses token-by-token |
| `max_tool_iterations` | `int` | `100` | Max tool calls per agent response |
| `default_permission_level` | `string` | `"trusted"` | Default preset for REPL mode |
| `skill_timeout` | `float` | `120.0` | Default timeout (seconds) for tool execution |
| `max_concurrent_tools` | `int` | `10` | Max parallel tool executions |

### Providers Configuration

The `providers` object maps provider names to their configurations:

```json
{
  "providers": {
    "openrouter": {
      "type": "openrouter",
      "api_key_env": "OPENROUTER_API_KEY",
      "base_url": "https://openrouter.ai/api/v1",
      "models": { ... }
    },
    "anthropic": {
      "type": "anthropic",
      "api_key_env": "ANTHROPIC_API_KEY",
      "base_url": "https://api.anthropic.com",
      "auth_method": "x-api-key",
      "models": { ... }
    }
  }
}
```

#### Provider Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | `string` | `"openrouter"` | Provider type: `openrouter`, `openai`, `azure`, `anthropic`, `ollama`, `vllm` |
| `api_key_env` | `string` | `"OPENROUTER_API_KEY"` | Environment variable containing API key |
| `base_url` | `string` | `"https://openrouter.ai/api/v1"` | Base URL for API requests |
| `auth_method` | `string` | `"bearer"` | Auth method: `bearer`, `api-key`, `x-api-key`, `none` |
| `extra_headers` | `object` | `{}` | Additional headers for API requests |
| `api_version` | `string?` | `null` | API version (for Azure) |
| `deployment` | `string?` | `null` | Azure deployment name |
| `request_timeout` | `float` | `120.0` | Request timeout in seconds |
| `max_retries` | `int` | `3` | Max retry attempts (0-10) |
| `retry_backoff` | `float` | `1.5` | Exponential backoff multiplier (1.0-5.0) |
| `allow_insecure_http` | `bool` | `false` | Allow non-HTTPS for non-localhost URLs |
| `verify_ssl` | `bool` | `true` | Verify SSL certificates (set `false` for self-signed certs) |
| `ssl_ca_cert` | `string?` | `null` | Path to custom CA certificate file |
| `models` | `object` | `{}` | Model aliases available through this provider |

#### SSL/TLS Configuration

For on-premises or private deployments with non-standard certificates:

```json
{
  "providers": {
    "onprem-selfsigned": {
      "type": "openai",
      "base_url": "https://llm.internal.company.com/v1",
      "api_key_env": "ONPREM_API_KEY",
      "verify_ssl": false,
      "models": { ... }
    },
    "onprem-corporate-ca": {
      "type": "openai",
      "base_url": "https://llm.internal.company.com/v1",
      "api_key_env": "ONPREM_API_KEY",
      "ssl_ca_cert": "/etc/ssl/certs/corporate-ca.crt",
      "models": { ... }
    }
  }
}
```

- **`verify_ssl: false`**: Disables certificate verification entirely. Use only when necessary.
- **`ssl_ca_cert`**: Points to a custom CA certificate file. More secure than disabling verification.

#### Model Configuration

Each model in `providers.*.models`:

```json
{
  "models": {
    "gpt": {
      "id": "openai/gpt-5.2",
      "context_window": 400000,
      "reasoning": false,
      "guidance": "OpenAI GPT-5.2. Good for: deep analysis, validation, complex reasoning."
    }
  }
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | `string` | required | Full model identifier sent to API |
| `context_window` | `int` | `131072` | Context window size in tokens |
| `reasoning` | `bool` | `false` | Enable extended thinking/reasoning |
| `guidance` | `string?` | `null` | Usage guidance (shown in `/models` command) |

### Default Models in config.json

| Alias | Provider | Model ID | Context | Notes |
|-------|----------|----------|---------|-------|
| `gemini` | openrouter | `google/gemini-3-flash-preview` | 1M | Multimodal, large context |
| `gpt` | openrouter | `openai/gpt-5.2` | 400K | Deep analysis, complex reasoning |
| `oss` | openrouter | `openai/gpt-oss-120b` | 131K | Budget/experimental tasks |
| `fast` | openrouter | `x-ai/grok-4.1-fast` | 2M | Default model, huge context |
| `haiku-native` | anthropic | `claude-haiku-4-5` | 200K | Fast Claude (native API) |
| `sonnet-native` | anthropic | `claude-sonnet-4-5` | 200K | Balanced Claude (native API) |
| `opus-native` | anthropic | `claude-opus-4-5` | 200K | Most capable Claude (native API) |

The config also includes two example on-premises provider configurations (`onprem-example-selfsigned`, `onprem-example-corporate-ca`) demonstrating SSL configuration options.

### Compaction Configuration

Context compaction summarizes old messages when context exceeds threshold:

```json
{
  "compaction": {
    "enabled": true,
    "model": "fast",
    "summary_budget_ratio": 0.25,
    "recent_preserve_ratio": 0.25,
    "trigger_threshold": 0.9
  }
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `true` | Enable automatic compaction |
| `model` | `string?` | `"fast"` | Model alias for summarization (`null` = use default) |
| `summary_budget_ratio` | `float` | `0.25` | Max tokens for summary (fraction of available) |
| `recent_preserve_ratio` | `float` | `0.25` | Recent messages to preserve (fraction of available) |
| `trigger_threshold` | `float` | `0.9` | Compact when usage exceeds this ratio |

### Context Configuration

Controls NEXUS.md prompt loading:

```json
{
  "context": {
    "include_readme": false,
    "readme_as_fallback": false
  }
}
```

| Field | Type | Default | Description |
|------|------|---------|-------------|
| `ancestor_depth` | `int` | `2` | Directory levels above CWD to search (0-10) |
| `include_readme` | `bool` | `false` | Always include README.md alongside NEXUS.md |
| `readme_as_fallback` | `bool` | `false` | Use README.md when no NEXUS.md exists |

### MCP Servers Configuration

Example MCP server definitions (for testing):

```json
{
  "mcp_servers": [
    {
      "name": "test",
      "command": ["python3", "-m", "nexus3.mcp.test_server"]
    },
    {
      "name": "http-test",
      "url": "http://127.0.0.1:9000"
    }
  ]
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `string` | required | Server name (used in skill prefixes) |
| `command` | `list[string]?` | `null` | Command for stdio transport |
| `url` | `string?` | `null` | URL for HTTP transport |
| `env` | `object?` | `null` | Explicit environment variables |
| `env_passthrough` | `list[string]?` | `null` | Host env vars to pass through |
| `enabled` | `bool` | `true` | Whether server is enabled |

---

## NEXUS.md System Prompt

The default `NEXUS.md` provides comprehensive agent instructions covering:

### Sections

1. **Introduction** - Agent identity and capabilities
2. **Principles** - Behavioral guidelines (be direct, use tools, respect boundaries)
3. **Permission System** - YOLO/TRUSTED/SANDBOXED levels, ceiling enforcement
4. **Logs** - Server logging, session logs, SQLite schema, finding things
5. **Tool Limits** - File size limits, timeouts, context recovery
6. **Available Tools** - Complete tool reference with parameters
7. **Agent Communication** - Permission defaults for RPC agents
8. **Execution Modes** - Sequential vs parallel tool execution
9. **Response Format** - Output formatting guidelines
10. **Path Formats** - WSL path conversion guidance
11. **Self-Knowledge** - Tips for NEXUS3 agents working on NEXUS3 codebase

### Key Content

The prompt includes:

- **Tool reference table** with all parameters
- **Permission explanations** for YOLO, TRUSTED, SANDBOXED presets
- **RPC security defaults** (sandboxed by default, write tools disabled)
- **Log file locations** and query examples
- **File operation limits** (10MB max, 1MB output, 10K lines)
- **Parallel execution** via `_parallel: true` argument
- **WSL path conversion** rules for Windows/Linux interop

---

## How Defaults Are Used

### Initialization Commands

When running `nexus3 --init-global`:

```python
# nexus3/cli/init_commands.py
defaults_dir = get_defaults_dir()  # nexus3/defaults/

# Copy NEXUS.md
default_nexus = defaults_dir / "NEXUS.md"
if default_nexus.exists():
    shutil.copy(default_nexus, global_dir / "NEXUS.md")

# Copy config.json
default_config = defaults_dir / "config.json"
if default_config.exists():
    shutil.copy(default_config, global_dir / "config.json")
```

### Runtime Loading

```python
# nexus3/core/constants.py
def get_defaults_dir() -> Path:
    """Get package defaults directory (shipped with package)."""
    import nexus3
    return Path(nexus3.__file__).parent / "defaults"
```

The defaults directory is located relative to the installed package, making it work in both development (`python -m nexus3`) and installed (`pip install nexus3`) modes.

---

## Dependencies

| Module | Usage |
|--------|-------|
| `nexus3.core.constants` | `get_defaults_dir()` function |
| `nexus3.config.loader` | Loads `config.json` as first merge layer |
| `nexus3.context.loader` | Loads `NEXUS.md` as fallback when no global config |
| `nexus3.cli.init_commands` | Copies defaults to `~/.nexus3/` |
| `nexus3.config.schema` | Pydantic models that validate `config.json` |

---

## Customization

To override defaults without modifying package files:

### Global Overrides (`~/.nexus3/`)

```bash
nexus3 --init-global  # Creates ~/.nexus3/ with copies of defaults
# Then edit ~/.nexus3/config.json and ~/.nexus3/NEXUS.md
```

### Project Overrides (`.nexus3/`)

```bash
# In REPL:
/init  # Creates ./.nexus3/ with templates

# Or manually:
mkdir -p .nexus3
echo '{"default_model": "gpt"}' > .nexus3/config.json
```

### Partial Overrides

You don't need to copy entire files. Override only what you need:

```json
// .nexus3/config.json - only override the default model
{
  "default_model": "anthropic/sonnet-native"
}
```

All other settings inherit from earlier layers (global, then defaults).

---

## Security Considerations

1. **No secrets in defaults** - API keys come from environment variables
2. **Sandboxed RPC default** - `default_permission_level` is `trusted` for REPL only; RPC agents default to `sandboxed`
3. **Safe MCP defaults** - Test MCP servers only, real servers configured per-user
4. **README opt-in** - `readme_as_fallback: false` prevents untrusted READMEs from injecting prompts
5. **SSL verification enabled by default** - On-prem examples show how to configure custom CAs securely

---

Updated: 2026-01-28
