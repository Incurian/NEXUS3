# NEXUS3

An AI-powered CLI agent framework. Clean-slate rewrite focused on simplicity, maintainability, and end-to-end testability.

## Installation

NEXUS3 uses [uv](https://github.com/astral-sh/uv) for Python version management and package installation.

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment with Python 3.11
uv python install 3.11
uv venv --python 3.11 .venv

# Activate virtual environment
source .venv/bin/activate

# Install package with development dependencies
uv pip install -e ".[dev]"
```

## Configuration

Set your API key:

```bash
export OPENROUTER_API_KEY="your-key-here"
```

Optionally create a configuration file at `.nexus3/config.json` (project-local) or `~/.nexus3/config.json` (global):

```json
{
  "provider": {
    "model": "anthropic/claude-sonnet-4",
    "api_key_env": "OPENROUTER_API_KEY"
  },
  "stream_output": true
}
```

## Quick Start

### Interactive REPL

```bash
python -m nexus3
```

Type messages at the prompt. Press ESC during streaming to cancel. Use `/quit` to exit.

### HTTP Server Mode (JSON-RPC)

For automation and programmatic control, start the HTTP server:

```bash
# Start server on default port 8765
python -m nexus3 --serve

# Start server on custom port
python -m nexus3 --serve 9000
```

Then send JSON-RPC requests via HTTP:

```bash
curl -X POST http://localhost:8765 \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","method":"send","params":{"content":"Hello"},"id":1}'
```

## CLI Options

| Flag | Description |
|------|-------------|
| `--serve [PORT]` | Run HTTP JSON-RPC server (default port: 8765) |
| `--reload` | Auto-restart on code changes (serve mode only, requires watchfiles) |
| `--verbose` | Enable verbose logging (thinking traces, timing) |
| `--raw-log` | Enable raw API request/response logging |
| `--log-dir PATH` | Custom directory for session logs |

## System Prompt

NEXUS3 loads system prompts from `NEXUS.md` files with a layered approach:

1. **Personal layer** (first found): `~/.nexus3/NEXUS.md` or package defaults
2. **Project layer** (optional): `./NEXUS.md` in current directory

Both layers are combined if present.

## Architecture

```
nexus3/
├── core/       # Foundational types, protocols, errors, streaming events
├── config/     # Configuration loading and validation
├── provider/   # LLM API implementations (OpenRouter) with streaming tool detection
├── session/    # Chat coordination, tool execution loop, SQLite logging
├── context/    # Message history, token tracking, truncation
├── skill/      # Tool system with dependency injection
├── display/    # Rich-based terminal UI with gumballs
├── cli/        # REPL and HTTP server entry points
├── rpc/        # JSON-RPC 2.0 protocol for HTTP server mode
└── client.py   # Async HTTP client for agent-to-agent communication
```

### Module Documentation

| Module | Description |
|--------|-------------|
| [core](nexus3/core/README.md) | Immutable data types (`Message`, `ToolCall`, `ToolResult`), streaming events (`StreamEvent`, `ContentDelta`, `ToolCallStarted`), protocols (`AsyncProvider`), exceptions |
| [config](nexus3/config/README.md) | Pydantic-validated configuration with fail-fast loading |
| [provider](nexus3/provider/README.md) | OpenRouter LLM provider with streaming and real-time tool call detection |
| [session](nexus3/session/README.md) | Session coordinator with streaming tool execution loop and SQLite-backed logging |
| [context](nexus3/context/README.md) | Context window management, token counting, automatic truncation |
| [skill](nexus3/skill/README.md) | Skill system with protocol-based interface, dependency injection, and registry |
| [display](nexus3/display/README.md) | Terminal display with animated spinners and gumball status indicators |
| [cli](nexus3/cli/README.md) | Interactive REPL with ESC cancellation and slash commands |
| [rpc](nexus3/rpc/README.md) | JSON-RPC 2.0 protocol for HTTP server automation |
| client.py | Async HTTP client (`NexusClient`) for programmatic agent communication |

### Built-in Skills

| Skill | Description |
|-------|-------------|
| `read_file` | Read file contents from disk |
| `write_file` | Write content to a file |
| `sleep` | Pause execution for a specified duration |
| `nexus_send` | Send a message to a Nexus agent and get the response |
| `nexus_cancel` | Cancel a running operation on a Nexus agent |
| `nexus_status` | Get the status/token usage of a Nexus agent |
| `nexus_shutdown` | Request graceful shutdown of a Nexus agent |

The `nexus_*` skills enable agent-to-agent communication via HTTP JSON-RPC, allowing one agent to control or query another running in server mode (`--serve`).

## Development

### Running Tests

```bash
# Activate virtual environment
source .venv/bin/activate

# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=nexus3 --cov-report=term-missing
```

### Linting and Type Checking

```bash
# Lint
ruff check nexus3/

# Type check
mypy nexus3/
```

### Project Guidelines

See [CLAUDE.md](CLAUDE.md) for detailed development guidelines, architecture decisions, and implementation status.

## License

MIT
