# NEXUS3

An AI-powered CLI agent framework with multi-agent support. NEXUS3 is a clean-slate rewrite focused on simplicity, maintainability, and end-to-end testability.

## Features

- **Interactive REPL** - Streaming responses with Rich-based terminal UI, ESC cancellation, and animated status indicators
- **HTTP Server Mode** - JSON-RPC 2.0 API for automation, testing, and integration with external tools
- **Multi-Agent Architecture** - Create, manage, and destroy multiple isolated agent instances via API
- **Agent-to-Agent Communication** - Built-in skills for agents to control other agents
- **Tool/Skill System** - Extensible skill framework with dependency injection and parallel execution support
- **Context Management** - Token tracking, automatic truncation, and layered system prompts
- **Structured Logging** - SQLite-backed session logs with human-readable Markdown exports
- **Cross-Platform** - UTF-8 everywhere, path normalization for Windows/Unix compatibility

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
- [Multi-Agent API](#multi-agent-api)
- [Built-in Skills](#built-in-skills)
- [Configuration](#configuration)
- [Architecture](#architecture)
- [Development](#development)
- [License](#license)

---

## Installation

NEXUS3 uses [uv](https://github.com/astral-sh/uv) for Python version management and package installation.

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment with Python 3.11
uv python install 3.11
uv venv --python 3.11 .venv

# Activate virtual environment
source .venv/bin/activate  # Linux/macOS
# or: .venv\Scripts\activate  # Windows

# Install package with development dependencies
uv pip install -e ".[dev]"
```

### Dependencies

**Core:** httpx, rich, prompt-toolkit, pydantic, tiktoken

**Dev:** pytest, pytest-asyncio, pytest-cov, ruff, mypy, watchfiles

---

## Quick Start

### Set API Key

```bash
export OPENROUTER_API_KEY="your-key-here"
```

### Interactive REPL

Start an interactive session with streaming responses:

```bash
python -m nexus3
```

- Type messages at the prompt to chat with the AI
- Press **ESC** during streaming to cancel a response
- Use `/quit`, `/exit`, or `/q` to exit

### HTTP Server Mode

Start the JSON-RPC server for programmatic control:

```bash
# Default port 8765
python -m nexus3 --serve

# Custom port
python -m nexus3 --serve 9000

# With auto-reload for development
python -m nexus3 --serve --reload
```

Send a message via curl:

```bash
# Create an agent
curl -X POST http://localhost:8765 \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","method":"create_agent","params":{"agent_id":"main"},"id":1}'

# Send a message
curl -X POST http://localhost:8765/agent/main \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","method":"send","params":{"content":"Hello!"},"id":2}'
```

### Client Mode (Connect to Remote Server)

Connect to a running NEXUS3 server as a REPL client:

```bash
# Connect to default server (localhost:8765)
python -m nexus3 --connect

# Connect to custom server
python -m nexus3 --connect http://server:9000

# Connect to a specific agent
python -m nexus3 --connect --agent worker-1
```

Inside the client REPL:
- Type messages to send to the remote agent
- `/status` - Show token usage and context info
- `/quit` - Disconnect

### CLI Subcommands

One-shot commands for controlling remote agents:

```bash
# Send a message
python -m nexus3 send http://localhost:8765/agent/main "What is 2+2?"

# Send with request ID for tracking
python -m nexus3 send http://localhost:8765/agent/main "Hello" --request-id 42

# Cancel an in-progress request
python -m nexus3 cancel http://localhost:8765/agent/main 42

# Get agent status (tokens + context)
python -m nexus3 status http://localhost:8765/agent/main

# Request graceful shutdown
python -m nexus3 shutdown http://localhost:8765/agent/main
```

---

## CLI Reference

### Main Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--serve [PORT]` | 8765 | Run HTTP JSON-RPC server instead of REPL |
| `--connect [URL]` | `http://localhost:8765` | Connect to server as REPL client |
| `--agent ID` | `main` | Agent ID to connect to (requires `--connect`) |
| `--verbose` | off | Enable verbose logging (thinking traces, timing) |
| `--raw-log` | off | Enable raw API JSON logging |
| `--log-dir PATH` | `.nexus3/logs` | Directory for session logs |
| `--reload` | off | Auto-reload on code changes (serve mode only) |

### Subcommands

| Command | Arguments | Description |
|---------|-----------|-------------|
| `send` | `URL CONTENT [--request-id ID]` | Send message to agent |
| `cancel` | `URL REQUEST_ID` | Cancel in-progress request |
| `status` | `URL` | Get tokens and context info |
| `shutdown` | `URL` | Request graceful shutdown |

---

## Multi-Agent API

The HTTP server supports a multi-agent architecture where you can create, manage, and destroy multiple isolated agent instances.

### Path-Based Routing

| Path | Handler | Description |
|------|---------|-------------|
| `POST /` or `POST /rpc` | GlobalDispatcher | Agent lifecycle management |
| `POST /agent/{agent_id}` | Agent's Dispatcher | Agent-specific operations |

### Agent Lifecycle Methods

These methods are sent to `/` or `/rpc`:

#### `create_agent`

Create a new agent instance with isolated context and state.

```bash
curl -X POST http://localhost:8765 \
    -d '{"jsonrpc":"2.0","method":"create_agent","params":{"agent_id":"worker-1"},"id":1}'
```

Response:
```json
{"jsonrpc":"2.0","id":1,"result":{"agent_id":"worker-1","url":"/agent/worker-1"}}
```

Parameters:
- `agent_id` (optional): Unique identifier. Auto-generated if omitted.
- `system_prompt` (optional): Override the default system prompt.

#### `list_agents`

List all active agents with their status.

```bash
curl -X POST http://localhost:8765 \
    -d '{"jsonrpc":"2.0","method":"list_agents","id":2}'
```

Response:
```json
{
  "jsonrpc":"2.0","id":2,
  "result":{
    "agents":[
      {"agent_id":"worker-1","created_at":"2024-01-15T10:30:00","message_count":5,"should_shutdown":false}
    ]
  }
}
```

#### `destroy_agent`

Destroy an agent and clean up resources.

```bash
curl -X POST http://localhost:8765 \
    -d '{"jsonrpc":"2.0","method":"destroy_agent","params":{"agent_id":"worker-1"},"id":3}'
```

Response:
```json
{"jsonrpc":"2.0","id":3,"result":{"success":true,"agent_id":"worker-1"}}
```

### Agent Operation Methods

These methods are sent to `/agent/{agent_id}`:

#### `send`

Send a message and get a response.

```bash
curl -X POST http://localhost:8765/agent/worker-1 \
    -d '{"jsonrpc":"2.0","method":"send","params":{"content":"Hello!"},"id":1}'
```

Response:
```json
{"jsonrpc":"2.0","id":1,"result":{"content":"Hello! How can I help?","request_id":"a1b2c3d4"}}
```

Parameters:
- `content` (required): Message text
- `request_id` (optional): ID for tracking/cancellation

#### `cancel`

Cancel an in-progress request.

```bash
curl -X POST http://localhost:8765/agent/worker-1 \
    -d '{"jsonrpc":"2.0","method":"cancel","params":{"request_id":"a1b2c3d4"},"id":2}'
```

Response:
```json
{"jsonrpc":"2.0","id":2,"result":{"cancelled":true,"request_id":"a1b2c3d4"}}
```

#### `get_tokens`

Get token usage breakdown.

```bash
curl -X POST http://localhost:8765/agent/worker-1 \
    -d '{"jsonrpc":"2.0","method":"get_tokens","id":3}'
```

Response:
```json
{"jsonrpc":"2.0","id":3,"result":{"system":150,"tools":0,"messages":42,"total":192,"budget":8000,"available":6000}}
```

#### `get_context`

Get context information.

```bash
curl -X POST http://localhost:8765/agent/worker-1 \
    -d '{"jsonrpc":"2.0","method":"get_context","id":4}'
```

#### `shutdown`

Request graceful shutdown of the agent.

```bash
curl -X POST http://localhost:8765/agent/worker-1 \
    -d '{"jsonrpc":"2.0","method":"shutdown","id":5}'
```

### Multi-Turn Conversation Example

```bash
# Create agent
curl -X POST http://localhost:8765 \
    -d '{"jsonrpc":"2.0","method":"create_agent","params":{"agent_id":"chat"},"id":1}'

# First message
curl -X POST http://localhost:8765/agent/chat \
    -d '{"jsonrpc":"2.0","method":"send","params":{"content":"My name is Alice"},"id":2}'

# Second message (agent remembers context)
curl -X POST http://localhost:8765/agent/chat \
    -d '{"jsonrpc":"2.0","method":"send","params":{"content":"What is my name?"},"id":3}'
# Response: "Your name is Alice."

# Clean up
curl -X POST http://localhost:8765 \
    -d '{"jsonrpc":"2.0","method":"destroy_agent","params":{"agent_id":"chat"},"id":4}'
```

### Python Client

For Python applications, use `NexusClient`:

```python
from nexus3.client import NexusClient, ClientError

async with NexusClient("http://localhost:8765") as client:
    # Send message
    result = await client.send("Hello!")
    print(result["content"])

    # Get token usage
    tokens = await client.get_tokens()

    # Cancel request
    await client.cancel(request_id="123")

    # Shutdown
    await client.shutdown()
```

---

## Built-in Skills

NEXUS3 includes 7 built-in skills registered automatically:

### File Operations

| Skill | Description | Parameters |
|-------|-------------|------------|
| `read_file` | Read file contents as UTF-8 text | `path` (required) |
| `write_file` | Write content to file (creates directories) | `path`, `content` (required) |

Cross-platform path handling:
- Windows backslashes (`C:\Users\...`) converted to forward slashes
- Home directory expansion (`~/.config/...`)
- Relative paths resolved to absolute

### Testing

| Skill | Description | Parameters |
|-------|-------------|------------|
| `sleep` | Sleep for specified duration | `seconds` (required), `label` (optional) |

### Agent Control

These skills enable agent-to-agent communication via HTTP JSON-RPC:

| Skill | Description | Parameters |
|-------|-------------|------------|
| `nexus_send` | Send message to a Nexus agent | `url`, `content` (required), `request_id` (optional) |
| `nexus_cancel` | Cancel in-progress request | `url`, `request_id` (required) |
| `nexus_status` | Get token/context info from agent | `url` (required) |
| `nexus_shutdown` | Request graceful agent shutdown | `url` (required) |

Example: One agent controlling another:

```python
# Agent A can send messages to Agent B
await nexus_send.execute(url="http://localhost:8765/agent/worker-b", content="Process this data")

# Check status
await nexus_status.execute(url="http://localhost:8765/agent/worker-b")
```

### Parallel Execution

Add `"_parallel": true` to any tool call's arguments to run all tools in the batch concurrently:

```json
{"name": "read_file", "arguments": {"path": "file1.py", "_parallel": true}}
{"name": "read_file", "arguments": {"path": "file2.py", "_parallel": true}}
```

---

## Configuration

### Config Files

NEXUS3 looks for configuration in this order:
1. `.nexus3/config.json` (project-local)
2. `~/.nexus3/config.json` (global)

```json
{
  "provider": {
    "model": "anthropic/claude-sonnet-4",
    "api_key_env": "OPENROUTER_API_KEY"
  },
  "stream_output": true
}
```

### System Prompts

System prompts are loaded from `NEXUS.md` files with a layered approach:

```
Personal Layer (first match wins):
  1. ~/.nexus3/NEXUS.md          # User defaults
  2. <package>/defaults/NEXUS.md  # Package defaults

Project Layer (optional):
  ./NEXUS.md                      # Project-specific (in cwd)
```

Both layers are combined with headers:

```markdown
# Personal Configuration
[personal prompt content]

# Project Configuration
[project prompt content]

# Environment
Working directory: /path/to/project
Operating system: Linux (WSL2 on Windows)
Terminal: vscode (xterm-256color)
Mode: Interactive REPL
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | API key for OpenRouter LLM provider |

---

## Architecture

### Module Overview

```
nexus3/
├── core/           # Foundational types, protocols, errors
├── config/         # Pydantic schema, fail-fast loader
├── provider/       # LLM provider implementations
├── context/        # Message history, token tracking, truncation
├── session/        # Session coordinator, logging
├── skill/          # Skill system with dependency injection
├── display/        # Terminal UI with Rich
├── cli/            # REPL and HTTP server entry points
├── rpc/            # JSON-RPC 2.0 protocol and multi-agent pool
└── client.py       # Async HTTP client for agent communication
```

### Core Module (`nexus3/core`)

Foundational types with zero internal dependencies:

| Type | Description |
|------|-------------|
| `Message` | Immutable message with role, content, optional tool_calls |
| `Role` | Enum: SYSTEM, USER, ASSISTANT, TOOL |
| `ToolCall` | Request to execute a tool (id, name, arguments) |
| `ToolResult` | Execution result (output/error, success property) |
| `StreamEvent` | Base class for streaming events |
| `ContentDelta` | Text chunk for immediate display |
| `ToolCallStarted` | Tool call detected in stream |
| `StreamComplete` | Final message with accumulated content |
| `AsyncProvider` | Protocol for LLM providers |
| `CancellationToken` | Cooperative cancellation support |

### Context Module (`nexus3/context`)

Manages conversation state and token budgets:

- **ContextManager** - Tracks system prompt, messages, tool definitions
- **PromptLoader** - Layered system prompt loading with environment info
- **TokenCounter** - Pluggable counting (tiktoken or simple estimation)
- **Truncation** - Automatic oldest-first or middle-out strategies

Token budget calculation:
```
max_tokens (8000 default)
  - reserve_tokens (2000)  <- Reserved for response
  = available (6000)       <- Budget for context
```

### Session Module (`nexus3/session`)

Coordinates LLM interactions and logging:

- **Session** - Ties together provider, context, and skill execution
- **SessionLogger** - SQLite + Markdown logging with configurable streams
- **Tool Execution Loop** - Sequential or parallel skill execution with callbacks

Log streams:
| Stream | Files | Enabled By |
|--------|-------|------------|
| CONTEXT | `session.db` + `context.md` | Always |
| VERBOSE | `verbose.md` | `--verbose` |
| RAW | `raw.jsonl` | `--raw-log` |

### Skill Module (`nexus3/skill`)

Extensible tool system:

- **Skill Protocol** - Interface for all skills (name, description, parameters, execute)
- **BaseSkill** - Convenience base class
- **SkillRegistry** - Factory-based registration with lazy instantiation
- **ServiceContainer** - Simple dependency injection

Creating a custom skill:
```python
class MySkill(BaseSkill):
    def __init__(self):
        super().__init__(
            name="my_skill",
            description="Does something useful",
            parameters={
                "type": "object",
                "properties": {"input": {"type": "string"}},
                "required": ["input"]
            }
        )

    async def execute(self, input: str = "", **kwargs) -> ToolResult:
        return ToolResult(output=f"Result: {input}")
```

### RPC Module (`nexus3/rpc`)

JSON-RPC 2.0 implementation for HTTP server:

- **AgentPool** - Manages multiple agent instances with isolated state
- **SharedComponents** - Resources shared across agents (provider, config)
- **GlobalDispatcher** - Handles create/destroy/list agent methods
- **Dispatcher** - Per-agent request handling (send/cancel/get_tokens)
- **HTTP Server** - Pure asyncio implementation, localhost-only binding

### Multi-Agent Design

```
+------------------+
|  SharedComponents |  <- Shared: provider, config, prompt_loader
+------------------+
         |
         v
+------------------+
|    AgentPool     |  <- Manages agent lifecycle
+------------------+
         |
    +----+----+
    |         |
    v         v
+-------+  +-------+
| Agent |  | Agent |  <- Isolated: context, logger, registry, session
+-------+  +-------+
```

Each agent has:
- Own `ContextManager` (independent conversation history)
- Own `SessionLogger` (writes to agent's log directory)
- Own `SkillRegistry` (with per-agent service container)
- Own `Session` (uses shared provider but isolated state)
- Own `Dispatcher` (handles RPC requests)

---

## Development

### Running Tests

```bash
# Activate virtual environment
source .venv/bin/activate

# Run all tests
pytest tests/ -v

# Integration tests only
pytest tests/integration/ -v

# With coverage report
pytest tests/ --cov=nexus3 --cov-report=term-missing
```

### Linting and Type Checking

```bash
# Lint with ruff
ruff check nexus3/

# Type check with mypy
mypy nexus3/
```

### Project Guidelines

Key development principles:

1. **Async-first** - asyncio throughout, not threading
2. **Fail-fast** - No silent exception swallowing
3. **Type everything** - No `Optional[Any]`, use Protocols for interfaces
4. **Single source of truth** - One way to do each thing
5. **End-to-end tested** - Integration tests for every feature

See [CLAUDE.md](CLAUDE.md) for detailed development guidelines and implementation status.

### Module Documentation

Each module has its own README with detailed documentation:

| Module | README |
|--------|--------|
| Core types and protocols | [nexus3/core/README.md](nexus3/core/README.md) |
| Context management | [nexus3/context/README.md](nexus3/context/README.md) |
| Session and logging | [nexus3/session/README.md](nexus3/session/README.md) |
| Skill system | [nexus3/skill/README.md](nexus3/skill/README.md) |
| CLI interface | [nexus3/cli/README.md](nexus3/cli/README.md) |
| RPC and multi-agent | [nexus3/rpc/README.md](nexus3/rpc/README.md) |

---

## License

MIT
