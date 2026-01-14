# NEXUS3

An AI-powered CLI agent framework with multi-agent support. NEXUS3 is a clean-slate rewrite focused on simplicity, maintainability, and end-to-end testability.

## Features

- **Interactive REPL** - Streaming responses with Rich-based terminal UI, ESC cancellation, and animated status indicators
- **HTTP Server Mode** - JSON-RPC 2.0 API for automation, testing, and integration with external tools
- **Multi-Agent Architecture** - Create, manage, and destroy multiple isolated agent instances via API
- **Agent-to-Agent Communication** - Built-in skills for agents to control other agents
- **Tool/Skill System** - Extensible skill framework with dependency injection and parallel execution support
- **Context Management** - Token tracking, automatic truncation, LLM-based compaction, layered system prompts, and dynamic timestamps
- **MCP Support** - Connect to external Model Context Protocol servers (stdio/HTTP) and use their tools as native skills
- **Structured Logging** - SQLite-backed session logs with human-readable Markdown exports
- **Cross-Platform** - UTF-8 everywhere, path normalization for Windows/Unix compatibility

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
- [Session Management](#session-management)
- [Security & Permissions](#security--permissions)
- [Multi-Agent API](#multi-agent-api)
- [Built-in Skills](#built-in-skills)
- [Adding Custom Skills](#adding-custom-skills)
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
nexus                    # Lobby mode - choose/create sessions
nexus --fresh            # Skip lobby, start new temp session
nexus --resume           # Resume last session
nexus --session NAME     # Load specific saved session
```

- Type messages at the prompt to chat with the AI
- Press **ESC** during streaming to cancel a response
- Use `/quit`, `/exit`, or `/q` to exit
- Use `/save NAME` to save your session
- Use `/help` to see all commands

### HTTP Server Mode

Start the JSON-RPC server for programmatic control:

```bash
nexus --serve            # Default port 8765
nexus --serve 9000       # Custom port
nexus --serve --reload   # Auto-reload for development
```

### RPC Commands

Programmatic operations via `nexus-rpc`:

```bash
nexus-rpc detect             # Check if server running
nexus-rpc list               # List agents (auto-starts server)
nexus-rpc create worker-1    # Create agent
nexus-rpc send worker-1 "Hello"  # Send message
nexus-rpc status worker-1    # Get agent status
nexus-rpc destroy worker-1   # Destroy agent
nexus-rpc shutdown           # Stop server
```

### Client Mode

Connect to a running server as a REPL client:

```bash
nexus --connect              # Connect to localhost:8765
nexus --connect http://server:9000 --agent worker-1
```

---

## CLI Reference

### Main Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--serve [PORT]` | 8765 | Run HTTP JSON-RPC server instead of REPL |
| `--connect [URL]` | `http://localhost:8765` | Connect to server as REPL client |
| `--agent ID` | `main` | Agent ID to connect to (requires `--connect`) |
| `--fresh` | off | Skip lobby, start new temp session |
| `--resume` | off | Resume last session |
| `--session NAME` | - | Load specific saved session |
| `--template PATH` | - | Use custom system prompt file |
| `--verbose` | off | Enable verbose logging (thinking traces, timing) |
| `--raw-log` | off | Enable raw API JSON logging |
| `--log-dir PATH` | `.nexus3/logs` | Directory for session logs |
| `--reload` | off | Auto-reload on code changes (serve mode only) |

### REPL Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all available commands |
| `/save NAME` | Save current session |
| `/load NAME` | Load a saved session |
| `/new` | Start a new session |
| `/sessions` | List saved sessions |
| `/agent ID [--preset]` | Create a new agent |
| `/switch ID` | Switch to another agent |
| `/destroy ID` | Destroy an agent |
| `/whisper` | Enter whisper mode (side conversation) |
| `/permissions` | Show/modify permissions |
| `/cwd [PATH]` | Show/change working directory |
| `/status` | Show token usage |
| `/quit` | Exit NEXUS3 |

---

## Session Management

NEXUS3 supports persistent sessions that can be saved, loaded, and resumed.

### Session Types

| Type | Example | Description |
|------|---------|-------------|
| **Temp sessions** | `.1`, `.2` | Auto-generated, not persisted |
| **Saved sessions** | `myproject` | Named, persisted to disk |

### Lobby Mode

When you run `nexus` without flags, you enter lobby mode:
- See list of saved sessions
- Resume a previous session
- Start a new session
- Delete old sessions

### Persistence

Sessions are saved to `~/.nexus3/sessions/` as JSON files containing:
- Conversation history
- Token counts
- Permission settings
- Working directory (planned)

The last session is auto-saved to `~/.nexus3/last-session.json` for quick resume with `nexus --resume`.

### Whisper Mode

Use `/whisper` to start a side conversation that doesn't affect the main session history. Useful for asking clarifying questions or exploring tangents without polluting the main context.

---

## Security & Permissions

NEXUS3 includes a comprehensive security system with API authentication, path sandboxing, and permission presets.

### API Authentication

The HTTP server uses API key authentication:
- Keys are auto-generated on first server start
- Stored in `~/.nexus3/server.key` (or `server-{port}.key` for non-default ports)
- All RPC requests require `Authorization: Bearer <key>` header
- Keys use constant-time comparison to prevent timing attacks

```bash
# API key is auto-discovered by nexus-rpc commands
nexus-rpc send worker-1 "Hello"

# Or specify explicitly
nexus-rpc --api-key nxk_abc123... send worker-1 "Hello"
```

### Permission Presets

Agents can be created with different permission levels:

| Preset | Level | Description |
|--------|-------|-------------|
| `yolo` | YOLO | Full access, no confirmations (**REPL only**) |
| `trusted` | TRUSTED | Confirmations for destructive actions (default) |
| `sandboxed` | SANDBOXED | Limited to CWD, no network, nexus tools disabled |
| `worker` | SANDBOXED | Alias for sandboxed with write_file disabled |

**Note:** `yolo` preset is only available via interactive REPL (`/agent --yolo`), not via RPC or programmatic API. This prevents scripts from accidentally spawning unrestricted agents.

```bash
# Create agent with preset (via RPC - yolo not allowed)
nexus-rpc create worker-1 --preset sandboxed
nexus-rpc create worker-1 --preset sandboxed --cwd /tmp/sandbox --write-path /tmp/sandbox/output

# Via REPL (yolo allowed for interactive use)
/agent worker-1 --sandboxed
/agent worker-1 --yolo
```

### Permission Features

1. **Per-tool configuration**: Enable/disable tools, per-tool paths, per-tool timeouts
2. **Ceiling inheritance**: Subagents cannot exceed parent permissions
3. **Runtime modification**: `/permissions` command to change settings mid-session
4. **Confirmation prompts**: TRUSTED mode prompts before destructive actions

```bash
# View current permissions
/permissions

# Disable a tool
/permissions --disable write_file

# Re-enable (if ceiling allows)
/permissions --enable write_file

# List all tools with status
/permissions --list-tools
```

### Path Sandboxing

File operations (`read_file`, `write_file`) are sandboxed:
- **YOLO/TRUSTED**: Full filesystem access
- **SANDBOXED/WORKER**: Limited to `allowed_paths` (default: CWD)
- Path traversal attempts (`../`) are blocked
- Symlinks outside sandbox are rejected

### URL Validation (SSRF Protection)

All nexus skills validate URLs before making requests:
- Public internet allowed, private IPs blocked (10.x, 172.16-31.x, 192.168.x, link-local)
- Cloud metadata endpoints blocked (169.254.169.254)
- DNS rebinding protection (all resolved IPs checked)
- Localhost allowed by default (`allow_localhost=True`)
- HTTP/HTTPS only, no file:// or other schemes

### Destructive Actions

These tools require confirmation in TRUSTED mode:
- `write_file`
- `nexus_destroy`
- `nexus_shutdown`
- `nexus_create` (spawning agents)

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
# Basic creation
curl -X POST http://localhost:8765 \
    -H "Authorization: Bearer $NEXUS_API_KEY" \
    -d '{"jsonrpc":"2.0","method":"create_agent","params":{"agent_id":"worker-1"},"id":1}'

# With permission preset
curl -X POST http://localhost:8765 \
    -H "Authorization: Bearer $NEXUS_API_KEY" \
    -d '{"jsonrpc":"2.0","method":"create_agent","params":{"agent_id":"worker-1","preset":"sandboxed"},"id":1}'

# With disabled tools
curl -X POST http://localhost:8765 \
    -H "Authorization: Bearer $NEXUS_API_KEY" \
    -d '{"jsonrpc":"2.0","method":"create_agent","params":{"agent_id":"worker-1","preset":"trusted","disable_tools":["write_file"]},"id":1}'
```

Response:
```json
{"jsonrpc":"2.0","id":1,"result":{"agent_id":"worker-1","url":"/agent/worker-1"}}
```

Parameters:
- `agent_id` (optional): Unique identifier. Auto-generated if omitted.
- `preset` (optional): Permission preset (trusted/sandboxed/worker). Default: trusted.
- `cwd` (optional): Working directory / sandbox root. For sandboxed, this is the only readable path.
- `allowed_write_paths` (optional): Paths where write_file/edit_file are allowed (must be within cwd).
- `disable_tools` (optional): List of tools to disable for this agent.
- `model` (optional): Model name/alias to use (from config.models or full model ID).
- `system_prompt` (optional): Override the default system prompt.

#### `list_agents`

List all active agents with their status.

```bash
curl -X POST http://localhost:8765 \
    -H "Authorization: Bearer $NEXUS_API_KEY" \
    -d '{"jsonrpc":"2.0","method":"list_agents","id":2}'
```

Response:
```json
{
  "jsonrpc":"2.0","id":2,
  "result":{
    "agents":[
      {"agent_id":"worker-1","created_at":"2024-01-15T10:30:00","message_count":5,"is_temp":false}
    ]
  }
}
```

#### `destroy_agent`

Destroy an agent and clean up resources. Cancels any in-progress requests.

```bash
curl -X POST http://localhost:8765 \
    -H "Authorization: Bearer $NEXUS_API_KEY" \
    -d '{"jsonrpc":"2.0","method":"destroy_agent","params":{"agent_id":"worker-1"},"id":3}'
```

Response:
```json
{"jsonrpc":"2.0","id":3,"result":{"success":true,"agent_id":"worker-1"}}
```

#### `shutdown_server`

Gracefully shutdown the entire server.

```bash
curl -X POST http://localhost:8765 \
    -H "Authorization: Bearer $NEXUS_API_KEY" \
    -d '{"jsonrpc":"2.0","method":"shutdown_server","id":4}'
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

NEXUS3 includes 24 built-in skills registered automatically:

### File Operations (Read-Only)

| Skill | Description | Parameters |
|-------|-------------|------------|
| `read_file` | Read file contents with optional line range | `path`, `offset`?, `limit`? |
| `tail` | Read last N lines of a file | `path`, `lines`? (default: 10) |
| `file_info` | Get file/directory metadata | `path` |
| `list_directory` | List directory contents | `path` |
| `glob` | Find files matching pattern | `pattern`, `path`?, `exclude`? |
| `grep` | Search file contents with regex | `pattern`, `path`?, `include`?, `context`? |

### File Operations (Destructive)

| Skill | Description | Parameters |
|-------|-------------|------------|
| `write_file` | Write content to file (creates directories) | `path`, `content` |
| `edit_file` | Edit file with search/replace | `path`, `old_string`, `new_string` |
| `append_file` | Append content to a file | `path`, `content`, `newline`? |
| `regex_replace` | Pattern-based find/replace | `path`, `pattern`, `replacement`, `count`?, etc. |
| `copy_file` | Copy a file to a new location | `source`, `destination`, `overwrite`? |
| `mkdir` | Create directory (and parents) | `path` |
| `rename` | Rename or move file/directory | `source`, `destination`, `overwrite`? |

**Note:** Destructive tools include guidance to read files before modifying them for safety.

### Version Control

| Skill | Description | Parameters |
|-------|-------------|------------|
| `git` | Execute git commands (permission-filtered) | `command`, `cwd`? |

### Execution (High-Risk)

| Skill | Description | Parameters |
|-------|-------------|------------|
| `bash` | Execute shell command | `command`, `timeout`? |
| `run_python` | Execute Python code | `code`, `timeout`? |

Features:
- Cross-platform path handling (Windows/Unix)
- Home directory expansion (`~/.config/...`)
- **Path sandboxing**: SANDBOXED/WORKER presets restrict to allowed paths
- **Async I/O**: Non-blocking file operations
- **UTF-8 encoding**: With error replacement for invalid bytes

### Utility

| Skill | Description | Parameters |
|-------|-------------|------------|
| `sleep` | Pause execution | `seconds`, `label`? |

### Agent Control

These skills enable agent-to-agent communication. All use `agent_id` + optional `port` instead of URLs:

| Skill | Description | Parameters |
|-------|-------------|------------|
| `nexus_create` | Create a new agent | `agent_id`, `preset`?, `disable_tools`?, `cwd`?, `model`?, `initial_message`? |
| `nexus_destroy` | Destroy an agent | `agent_id`, `port`? |
| `nexus_send` | Send message to agent | `agent_id`, `content`, `port`? |
| `nexus_status` | Get agent tokens/context | `agent_id`, `port`? |
| `nexus_cancel` | Cancel in-progress request | `agent_id`, `request_id`, `port`? |
| `nexus_shutdown` | Shutdown entire server | `port`? |

*Note: `port` defaults to 8765. API key is auto-discovered. `preset` can be trusted/sandboxed/worker (yolo is REPL-only).*

Security features:
- **URL validation**: SSRF protection blocks private IPs
- **Ceiling inheritance**: Subagents cannot exceed parent permissions
- **Agent ID validation**: Only alphanumeric, dash, underscore, dot allowed

Example: One agent spawning and controlling another:

```python
# Create a sandboxed worker
await nexus_create.execute(agent_id="worker-1", preset="sandboxed")

# Send it a task
await nexus_send.execute(agent_id="worker-1", content="Process this data")

# Check status
await nexus_status.execute(agent_id="worker-1")

# Clean up
await nexus_destroy.execute(agent_id="worker-1")
```

### Parallel Execution

The LLM can request parallel tool execution. Tools in the same batch run concurrently up to `max_concurrent_tools` (default: 10).

### Skill Timeout

All skills have a configurable timeout (default: 30 seconds). Configure via `skill_timeout` in config.

---

## Adding Custom Skills

NEXUS3's skill system is designed for extensibility with specialized base classes that handle common patterns.

### Skill Type Hierarchy

Choose the appropriate base class for your skill:

| Base Class | Use Case | Examples |
|------------|----------|----------|
| `FileSkill` | File I/O with sandbox validation | read_file, write_file, glob |
| `NexusSkill` | Agent control with server communication | nexus_send, nexus_create |
| `ExecutionSkill` | Subprocess execution with timeout | bash, run_python |
| `FilteredCommandSkill` | Permission-filtered CLI tools | git |
| `BaseSkill` | Generic skills without shared infrastructure | sleep |

### Basic Skill Structure

```python
from nexus3.skill.base import BaseSkill
from nexus3.core.types import ToolResult

class MySkill(BaseSkill):
    def __init__(self):
        super().__init__(
            name="my_skill",
            description="Does something useful",
            parameters={
                "type": "object",
                "properties": {
                    "input": {"type": "string", "description": "The input to process"}
                },
                "required": ["input"]
            }
        )

    async def execute(self, input: str = "", **kwargs) -> ToolResult:
        # Your logic here
        return ToolResult(output=f"Processed: {input}")
```

### Using Dependency Injection

Skills can access services via the `ServiceContainer`:

```python
from nexus3.skill.services import ServiceContainer
from pathlib import Path

def my_skill_factory(services: ServiceContainer) -> MySkill:
    """Factory function for DI-based skill creation."""
    allowed_paths = services.get("allowed_paths")  # list[Path] | None
    api_key = services.get("api_key")              # str | None
    permissions = services.get("permissions")       # AgentPermissions | None
    return MySkill(allowed_paths=allowed_paths)
```

### Available Services

| Service | Type | Description |
|---------|------|-------------|
| `allowed_paths` | `list[Path] \| None` | Sandbox paths (None = unrestricted) |
| `api_key` | `str \| None` | Server API key for RPC calls |
| `port` | `int` | Server port (default: 8765) |
| `agent_id` | `str \| None` | Current agent's ID |
| `permissions` | `AgentPermissions \| None` | Current agent's permissions |

### Integrating with Permissions

For skills that need permission checks:

```python
from nexus3.core.paths import validate_sandbox, PathSecurityError
from nexus3.core.url_validator import validate_url, UrlSecurityError

class SecureFileSkill(BaseSkill):
    def __init__(self, allowed_paths: list[Path] | None = None):
        self.allowed_paths = allowed_paths
        # ...

    async def execute(self, path: str = "", **kwargs) -> ToolResult:
        # Validate path if sandboxed
        if self.allowed_paths is not None:
            try:
                validated_path = validate_sandbox(path, self.allowed_paths)
            except PathSecurityError as e:
                return ToolResult(error=str(e))
        else:
            validated_path = Path(path).resolve()

        # Your file operation here
        content = await asyncio.to_thread(validated_path.read_text, encoding="utf-8")
        return ToolResult(output=content)
```

### Marking Skills as Destructive

If your skill modifies state, add it to the destructive tools list in config:

```json
{
  "permissions": {
    "destructive_tools": ["write_file", "my_destructive_skill"]
  }
}
```

This ensures TRUSTED mode prompts for confirmation before execution.

### Registering Skills

Register skills in `skill/builtin/registration.py`:

```python
from nexus3.skill.registry import SkillRegistry

def register_builtin_skills(registry: SkillRegistry) -> None:
    # Simple skill (no DI needed)
    registry.register(MySimpleSkill)

    # Skill with DI factory
    registry.register_factory("my_skill", my_skill_factory)
```

### Best Practices

1. **Always use async I/O**: Wrap blocking operations with `asyncio.to_thread()`
2. **Validate inputs**: Use `validate_sandbox()` for paths, `validate_url()` for URLs
3. **Return errors gracefully**: Use `ToolResult(error=message)` instead of raising
4. **Respect permissions**: Check `allowed_paths` if your skill accesses files
5. **Use UTF-8**: Always specify `encoding="utf-8", errors="replace"` for file ops
6. **Document parameters**: Use JSON Schema with descriptions in `parameters`

---

## Configuration

### Config Files

NEXUS3 looks for configuration in this order:
1. `.nexus3/config.json` (project-local)
2. `~/.nexus3/config.json` (global)

```json
{
  "provider": {
    "type": "openrouter",
    "model": "anthropic/claude-sonnet-4",
    "api_key_env": "OPENROUTER_API_KEY"
  },
  "stream_output": true,
  "skill_timeout": 30.0,
  "max_concurrent_tools": 10,
  "max_tool_iterations": 10,
  "permissions": {
    "default_preset": "trusted",
    "destructive_tools": ["write_file", "nexus_destroy", "nexus_shutdown", "nexus_create"],
    "presets": {
      "dev": {
        "extends": "trusted",
        "allowed_paths": ["/home/user/projects"],
        "tool_permissions": {
          "nexus_shutdown": {"enabled": false}
        }
      }
    }
  }
}
```

### File Locations

```
~/.nexus3/
├── config.json           # Global configuration
├── NEXUS.md              # Personal system prompt
├── server.key            # API key for default port
├── server-9000.key       # API key for port 9000
├── sessions/             # Saved session files
│   ├── myproject.json
│   └── experiment.json
└── last-session.json     # Auto-saved for --resume

./.nexus3/                # Project-local (gitignored)
└── logs/                 # Session logs
    └── session-123/
        ├── session.db    # SQLite log
        ├── context.md    # Human-readable
        └── raw.jsonl     # Raw API (if --raw-log)

./NEXUS.md                # Project system prompt
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

Both layers are combined with environment info appended.

### Provider Types

NEXUS3 supports multiple LLM providers. Set `provider.type` in config:

| Type | Description | API Key Env |
|------|-------------|-------------|
| `openrouter` | OpenRouter.ai (default) | `OPENROUTER_API_KEY` |
| `openai` | Direct OpenAI API | `OPENAI_API_KEY` |
| `azure` | Azure OpenAI Service | `AZURE_OPENAI_KEY` |
| `anthropic` | Anthropic Claude API | `ANTHROPIC_API_KEY` |
| `ollama` | Local Ollama server | (none required) |
| `vllm` | vLLM server | (none required) |

See `nexus3/provider/README.md` for full configuration examples.

### Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | API key for OpenRouter LLM provider (default) |
| `OPENAI_API_KEY` | API key for OpenAI provider |
| `AZURE_OPENAI_KEY` | API key for Azure OpenAI provider |
| `ANTHROPIC_API_KEY` | API key for Anthropic provider |
| `NEXUS_API_KEY` | Override auto-discovered server API key |

---

## Architecture

### Module Overview

```
nexus3/
├── core/           # Types, interfaces, errors, paths, URL validation, permissions
├── config/         # Pydantic schema, permission config, fail-fast loader
├── provider/       # AsyncProvider protocol, multi-provider support (OpenRouter/OpenAI/Azure/Anthropic/Ollama)
├── context/        # ContextManager, PromptLoader, TokenCounter, atomic truncation
├── session/        # Session coordinator, persistence, SessionManager, SQLite logging
├── skill/          # Skill protocol, SkillRegistry, ServiceContainer, builtin skills
├── display/        # DisplayManager, StreamingDisplay, InlinePrinter, SummaryBar, theme
├── cli/            # Unified REPL, lobby, whisper, HTTP server, client commands
├── rpc/            # JSON-RPC protocol, Dispatcher, GlobalDispatcher, AgentPool, auth
└── client.py       # NexusClient for agent-to-agent communication
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
- **Specialized Base Classes** - `FileSkill` (sandbox), `NexusSkill` (server), `ExecutionSkill` (subprocess), `FilteredCommandSkill` (permission-filtered CLI)
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
| Configuration | [nexus3/config/README.md](nexus3/config/README.md) |
| Context management | [nexus3/context/README.md](nexus3/context/README.md) |
| Session and logging | [nexus3/session/README.md](nexus3/session/README.md) |
| Skill system | [nexus3/skill/README.md](nexus3/skill/README.md) |
| Display system | [nexus3/display/README.md](nexus3/display/README.md) |
| CLI interface | [nexus3/cli/README.md](nexus3/cli/README.md) |
| RPC and multi-agent | [nexus3/rpc/README.md](nexus3/rpc/README.md) |
| MCP integration | [nexus3/mcp/README.md](nexus3/mcp/README.md) |
| Provider (LLM APIs) | [nexus3/provider/README.md](nexus3/provider/README.md) |

---

## License

MIT
