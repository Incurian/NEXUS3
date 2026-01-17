# NEXUS3 Defaults Module

## Purpose
Provides default configuration and system prompts for NEXUS3, an AI-powered CLI agent for software engineering tasks (file ops, commands, git, subagents).

## Key Components
No Python classes/functions. Contains declarative files:

- **`__init__.py`**: Package init. Docstring: `"Default configuration and prompts for NEXUS3."`

- **`config.json`**: LLM providers (OpenRouter, Anthropic), models (haiku, sonnet, opus, gemini, gpt, oss, fast; default: "fast"), settings (streaming, compaction, MCP servers).

- **`NEXUS.md`**: Agent system prompt (principles, permissions, tools, logs, execution modes).

## Usage Examples
1. **NEXUS3 Auto-Loads**:
   ```
   nexus3 repl  # Uses defaults/config.json and defaults/NEXUS.md
   ```

2. **Custom Config**:
   ```
   cp defaults/config.json myconfig.json
   # Edit, e.g., "default_model": "sonnet"
   nexus3 --config myconfig.json
   ```

3. **MCP Test Server** (from config.json):
   ```
   python3 -m nexus3.mcp.test_server
   ```

## Files (ls -l)
```
-rw-r--r--       52B  2026-01-08 16:33  __init__.py
-rw-r--r--      2.9K  2026-01-17 09:38  config.json
-rw-r--r--      8.4K  2026-01-17 05:57  NEXUS.md
-rw-r--r--      1.2K  2026-01-17 05:57  README.md
```

Updated: 2026-01-17