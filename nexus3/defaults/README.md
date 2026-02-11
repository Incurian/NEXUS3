# NEXUS3 Defaults Module

## Overview

The `nexus3/defaults/` directory contains the **shipped default configuration and system prompts** that NEXUS3 uses. These files serve as:

1. **System documentation** (`NEXUS-DEFAULT.md`) - Always loaded, provides tool docs, permissions, limits
2. **User prompt template** (`NEXUS.md`) - Copied to `~/.nexus3/` on init, user can customize
3. **Default configuration** (`config.json`) - Fallback when no user config exists
4. **Reference implementation** showing all available configuration options

## Files

| File | Purpose |
|------|---------|
| `__init__.py` | Package marker (docstring only, no exports) |
| `NEXUS-DEFAULT.md` | System defaults prompt (tools, permissions, limits) - always loaded |
| `NEXUS.md` | User prompt template - copied to ~/.nexus3/ on init |
| `config.json` | Default LLM providers, models, and settings |

## Split Context Design

NEXUS3 uses a two-file prompt system to separate auto-updating system documentation from user customizations:

| File | Location | Purpose | Updates |
|------|----------|---------|---------|
| `NEXUS-DEFAULT.md` | Package only | Tool docs, permissions, limits | Auto-updates with package upgrades |
| `NEXUS.md` | User's ~/.nexus3/ | Custom instructions | Preserved across upgrades |

This ensures:
- Users get new tool documentation automatically when NEXUS3 is upgraded
- User customizations in `~/.nexus3/NEXUS.md` are never overwritten
- The system prompt is always complete (system defaults + user additions)

## Configuration Loading Hierarchy

Prompts and config use different loading strategies:

**Prompts** (`NEXUS-DEFAULT.md` and `NEXUS.md`):
```
LAYER 1a: System Defaults (NEXUS-DEFAULT.md in package) <- ALWAYS LOADED
    |
LAYER 1b: Global (~/.nexus3/NEXUS.md) OR package NEXUS.md template (fallback)
    |
LAYER 2: Ancestors (up to N levels above CWD)
    |
LAYER 3: Local (CWD/.nexus3/) <- HIGHEST PRIORITY
```

All prompt layers are **concatenated** with labeled section headers.

**Config** (`config.json`):
```
LAYER 1: Global (~/.nexus3/config.json) OR shipped defaults (MUTUALLY EXCLUSIVE)
    |
LAYER 2: Ancestors (up to N levels above CWD)
    |
LAYER 3: Local (CWD/.nexus3/config.json) <- HIGHEST PRIORITY
```

Config layers **deep-merge** into earlier layers:
- Scalar values (strings, numbers, booleans) are replaced
- Objects are recursively merged
- Unspecified keys inherit from earlier layers

**Important:** For config, defaults are a **fallback**, not a base layer. If `~/.nexus3/config.json` exists, `nexus3/defaults/config.json` is NOT loaded or merged. This means a user's global config must include any settings they want to keep from the defaults.

### Loading Logic

The `ContextLoader` in `nexus3/context/loader.py` handles prompts with a two-stage approach:

```python
def _load_global_layer(self) -> list[ContextLayer]:
    """Load the global layer with both system defaults and user customization.

    System defaults (NEXUS-DEFAULT.md) always come from the package.
    User customization (NEXUS.md) comes from ~/.nexus3/ if it exists,
    otherwise falls back to package template.

    Returns:
        List of layers: [system-defaults layer, user/global layer]
    """
    layers: list[ContextLayer] = []
    global_dir = self._get_global_dir()  # ~/.nexus3/
    defaults_dir = self._get_defaults_dir()  # nexus3/defaults/

    # 1. Always load NEXUS-DEFAULT.md from package (system docs/tools)
    pkg_default = defaults_dir / "NEXUS-DEFAULT.md"
    if pkg_default.is_file():
        layer = ContextLayer(name="system-defaults", path=defaults_dir)
        layer.prompt = pkg_default.read_text(encoding="utf-8-sig")
        layers.append(layer)

    # 2. Load user's global config (config.json, mcp.json always from global dir)
    global_config = load_json_file_optional(global_dir / "config.json")
    global_mcp = load_json_file_optional(global_dir / "mcp.json")

    # 3. Load user's NEXUS.md from global dir, or fall back to package template
    user_nexus = global_dir / "NEXUS.md"
    if user_nexus.is_file():
        layer = ContextLayer(name="global", path=global_dir)
        layer.prompt = user_nexus.read_text(encoding="utf-8-sig")
        layer.config = global_config
        layer.mcp = global_mcp
        layers.append(layer)
    else:
        # Fall back to package NEXUS.md template for prompt,
        # but still use global config/mcp if they exist
        pkg_nexus = defaults_dir / "NEXUS.md"
        if pkg_nexus.is_file() or global_config or global_mcp:
            # Use global_dir as path if we have config/mcp there, otherwise defaults_dir
            layer_path = global_dir if (global_config or global_mcp) else defaults_dir
            layer = ContextLayer(name="global", path=layer_path)
            if pkg_nexus.is_file():
                layer.prompt = pkg_nexus.read_text(encoding="utf-8-sig")
            layer.config = global_config
            layer.mcp = global_mcp
            layers.append(layer)

    return layers
```

The config loader in `nexus3/config/loader.py` uses defaults as a fallback only:

```python
# Layer 1: Global user config OR defaults (mutually exclusive)
# If global config exists, use it. Otherwise fall back to defaults.
global_dir = get_nexus_dir()
global_config = global_dir / "config.json"
global_data = load_json_file_optional(global_config)

if global_data:
    # Global config exists - use it as base (NO defaults)
    merged = deep_merge(merged, global_data)
else:
    # No global config - fall back to shipped defaults
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
| `prompt_caching` | `bool` | `true` | Enable prompt caching (reduces cost ~90% on cached tokens) |
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

Controls instruction file loading:

```json
{
  "context": {
    "instruction_files": ["NEXUS.md", "AGENTS.md", "CLAUDE.md", "README.md"]
  }
}
```

| Field | Type | Default | Description |
|------|------|---------|-------------|
| `ancestor_depth` | `int` | `2` | Directory levels above CWD to search (0-10) |
| `instruction_files` | `list[str]` | `["NEXUS.md", "AGENTS.md", "CLAUDE.md", "README.md"]` | Ordered priority list of instruction filenames to search |

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
| `command` | `string \| list[string]?` | `null` | Command for stdio transport (list or string with `args`) |
| `args` | `list[string]?` | `null` | Arguments when `command` is a string (official MCP format) |
| `url` | `string?` | `null` | URL for HTTP transport |
| `env` | `object?` | `null` | Explicit environment variables for subprocess |
| `env_passthrough` | `list[string]?` | `null` | Host env vars to pass through (e.g., `["GITHUB_TOKEN"]`) |
| `cwd` | `string?` | `null` | Working directory for the server subprocess |
| `enabled` | `bool` | `true` | Whether server is enabled |

---

## Prompt Files

### NEXUS-DEFAULT.md (System Defaults)

The `NEXUS-DEFAULT.md` file is **always loaded** and provides system-level documentation:

| Section | Content |
|---------|---------|
| Introduction | Agent identity and capabilities |
| Principles | Behavioral guidelines (be direct, use tools, respect boundaries) |
| Permission System | YOLO/TRUSTED/SANDBOXED levels, ceiling enforcement, RPC defaults |
| Available Tools | Complete tool reference with parameters (file, exec, agent, clipboard, utility) |
| Clipboard System | Scopes, permissions, usage patterns |
| GitLab Integration | Skill categories and configuration reference |
| MCP Integration | External tool protocol, connection commands |
| Execution Modes | Sequential vs parallel (`_parallel: true`) tool execution |
| Working with Subagents | When/how to create, manage lifecycle, communication patterns |
| If You Are a Subagent | Guidelines for agents operating as subagents |
| REPL Commands | Agent management, session, configuration commands |
| Session Management | Persistence, startup modes, CLI flags |
| Configuration | config.json, NEXUS.md, mcp.json structure and layering |
| Tool Limits | File size limits (10MB), output limits (1MB), timeouts |
| Context & Compaction | Automatic summarization, manual compaction |
| System Prompt Architecture | Split design (NEXUS-DEFAULT.md + NEXUS.md) |
| Logs | Server logging, session logs, SQLite schema, searching logs |
| Path Formats | WSL path conversion (Windows/Linux interop) |
| Troubleshooting | Common issues table, debug flags |
| Self-Knowledge | Tips for NEXUS3 agents working on NEXUS3 codebase |

This file auto-updates when NEXUS3 is upgraded, ensuring agents always have current tool documentation.

### NEXUS.md (User Template)

The `NEXUS.md` file is a minimal template that gets copied to `~/.nexus3/NEXUS.md` during initialization:

```markdown
# Agent Instructions

You are NEXUS3, an AI-powered CLI agent.

<!-- Add your custom instructions below -->
```

Users can edit their copy to add:
- Project-specific guidelines
- Personal preferences (response style, etc.)
- Team conventions
- Domain-specific knowledge

This file is **never overwritten** by upgrades, preserving user customizations.

---

## How Defaults Are Used

### Initialization Commands

When running `nexus3 --init-global`:

```python
# nexus3/cli/init_commands.py
defaults_dir = get_defaults_dir()  # nexus3/defaults/

# Copy NEXUS.md (using _safe_write_text to prevent symlink attacks)
default_nexus = defaults_dir / "NEXUS.md"
if default_nexus.exists():
    _safe_write_text(
        global_dir / "NEXUS.md",
        default_nexus.read_text(encoding="utf-8"),
    )

# Copy config.json
default_config = defaults_dir / "config.json"
if default_config.exists():
    _safe_write_text(
        global_dir / "config.json",
        default_config.read_text(encoding="utf-8"),
    )
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
| `nexus3.config.loader` | Loads `config.json` as fallback when no global config exists |
| `nexus3.context.loader` | Always loads `NEXUS-DEFAULT.md`; loads `NEXUS.md` as fallback when no global prompt exists |
| `nexus3.cli.init_commands` | Copies defaults to `~/.nexus3/` via `_safe_write_text()` |
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

1. **No secrets in defaults** - API keys come from environment variables via `api_key_env`
2. **Sandboxed RPC default** - `default_permission_level` is `trusted` for REPL only; RPC agents default to `sandboxed`
3. **Safe MCP defaults** - Test MCP servers only, real servers configured per-user
4. **README safety** - README.md is last in instruction_files priority list and wrapped with documentation boundaries
5. **SSL verification enabled by default** - On-prem examples show how to configure custom CAs securely
6. **Split prompt design** - System docs auto-update, user customizations preserved

---

Updated: 2026-02-10
