# NEXUS3

AI-powered CLI agent framework. Clean-slate rewrite of NEXUS2.

**Status:** Phase 1 (Display System) complete. Next: logging modes.

## Features

- Streaming chat with animated spinner during responses
- ESC to cancel requests mid-stream
- Slash commands (/quit, /exit, /q)
- Persistent status bar (no scrollback pollution)
- Clean visual separation between exchanges

## Installation

```bash
# Requires Python 3.11+
uv venv --python 3.11 .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Configuration

Set your API key:
```bash
export OPENROUTER_API_KEY="your-key-here"
```

Optional: Create `~/.nexus3/config.json`:
```json
{
  "provider": {
    "model": "x-ai/grok-code-fast-1"
  }
}
```

## Usage

```bash
source .venv/bin/activate
python -m nexus3
```

Commands:
- `/quit` or `/exit` - Exit the REPL
- `ESC` - Cancel current request

## Development

```bash
# Run tests
pytest tests/ -v

# Lint and type check
ruff check nexus3/
mypy nexus3/
```

See [CLAUDE.md](CLAUDE.md) for architecture and development guidelines.

## Project Structure

```
nexus3/
├── cli/           # REPL and command handling
├── config/        # Configuration loading
├── core/          # Types, errors, interfaces
├── display/       # Rich-based display system
├── provider/      # LLM provider (OpenRouter)
└── session/       # Chat session coordinator
```
