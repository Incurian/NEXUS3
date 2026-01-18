# NEXUS3 Defaults Module

## Purpose
Provides default configuration and system prompts for NEXUS3, an AI-powered CLI agent for software engineering tasks (file ops, commands, git, subagents).

## Key Components
No Python classes/functions. Contains declarative files:

- **`__init__.py`**: Package init. Docstring: `"Default configuration and prompts for NEXUS3."`

- **`config.json`**: LLM providers (OpenRouter, Anthropic), models (haiku, sonnet, opus, gemini, gpt, oss, fast; default: "fast"), settings (streaming, compaction, MCP servers).

- **`NEXUS.md`**: Agent system prompt (principles, permissions, tools, logs, execution modes).

## Usage

These files are loaded automatically via the config layer system:
1. **Package defaults** (this directory) → lowest priority
2. **Global config** (`~/.nexus3/`) → user overrides
3. **Local config** (`./.nexus3/`) → project-specific

To customize, create `~/.nexus3/config.json` or `./.nexus3/config.json` with overrides.
Use `nexus3 --init-global` to initialize the global config directory.

## Files
- `__init__.py`: Package init (no exports)
- `config.json`: Default providers, models, settings
- `NEXUS.md`: Default agent system prompt

Updated: 2026-01-17