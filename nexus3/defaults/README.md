# NEXUS3 Defaults Module

## Purpose
The `nexus3.defaults` module provides default configuration files and prompts for the NEXUS3 AI-powered CLI agent. It serves as the foundational setup for NEXUS3 instances, including model providers, tool configurations, and agent behavior guidelines.

This directory contains:
- Default `config.json` for LLM providers (OpenRouter, Anthropic), models, streaming, compaction, MCP servers, and context settings.
- `NEXUS.md`: Core system prompt defining the agent's principles, tools, execution modes, and response formats.
- `__init__.py`: Package initializer with docstring indicating its role.

## Key Files/Modules
- **`__init__.py`**: Minimal package file. Docstring: `"Default configuration and prompts for NEXUS3."`
- **`config.json`**: JSON configuration with:
  - Default model: `"fast"` (x-ai/grok-4.1-fast).
  - Providers: OpenRouter (haiku, sonnet, opus, gemini, gpt, oss, fast) and Anthropic (native models).
  - Features: Streaming output, tool limits, permission levels, context compaction, MCP test servers.
- **`NEXUS.md`**: System prompt for NEXUS3 agents, covering:
  - Principles (Be Direct, Use Tools Effectively, etc.).
  - Available tools (file ops, agent comms).
  - Execution modes (Sequential/Parallel).
  - Response formats.

No additional Python classes or functions beyond package init.

## Dependencies
- External APIs: OpenRouter, Anthropic (via API keys: `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`).
- Python runtime (inferred from MCP server commands).
- No explicit Python package dependencies in source (runtime uses these defaults).

## Usage Examples
1. **Loading Defaults in NEXUS3**:
   NEXUS3 automatically loads `config.json` for provider setup and `NEXUS.md` as system prompt.

2. **Customizing Config**:
   Copy `config.json` and modify:
   ```json
   {
     "default_model": "sonnet",
     "providers": { ... }
   }
   ```

3. **MCP Server Integration**:
   Defaults include test MCP servers:
   ```bash
   python3 -m nexus3.mcp.test_server  # Local test server
   ```

## Architecture Summary
- **Flat Structure**: Simple directory treated as a Python package.
- **Configuration-Driven**: `config.json` centralizes LLM/model settings.
- **Prompt-Centric**: `NEXUS.md` embeds agent behavior and tool docs.
- **Extensible**: Easy to override or extend for custom NEXUS3 deployments.
- **No Runtime Code**: Purely declarative (configs/prompts); logic in core NEXUS3.

## Directory Contents
```
.
├── __init__.py     (52B)
├── config.json     (2.0K)
└── NEXUS.md        (3.1K)
```

For full NEXUS3 documentation, see the main repository.
