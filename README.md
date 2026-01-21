# NEXUS3

**A secure, multi-agent CLI framework for AI-powered software engineering.**

NEXUS3 provides a streaming REPL with an embedded JSON-RPC server for orchestrating multiple AI agents. Each agent runs in isolation with configurable permissions, enabling safe automation of development tasks through 24 built-in skills (file operations, git, shell execution, inter-agent communication).

## Key Design Principles

- **One Server, Many Agents**: Run a single NEXUS3 server per project/family. Create multiple agents within it for parallel research, code review, implementation—all coordinated through `nexus_send`. This is more efficient than multiple servers and enables direct inter-agent communication.
- **Async-First**: Built on asyncio throughout—no threading, predictable concurrency
- **Fail-Fast**: Errors surface immediately with clear messages—no silent failures
- **Security by Default**: Sandboxed by default for RPC agents, permission ceilings prevent escalation
- **Minimal Core**: Zero external dependencies in `nexus3/core` (stdlib + jsonschema only)

## Quick Start

### Installation

```bash
# Create virtual environment (Python 3.11+ required)
uv venv --python 3.11
source .venv/bin/activate

# Install with dev dependencies
uv pip install -e ".[dev]"

# Set API key (OpenRouter recommended, or use ANTHROPIC_API_KEY, OPENAI_API_KEY)
export OPENROUTER_API_KEY="sk-or-..."
```

### Interactive REPL (Recommended)

```bash
nexus3                    # Launch lobby to select/create session
nexus3 --fresh            # Skip lobby, start new temporary session
nexus3 --resume           # Resume last session
nexus3 --session myproj   # Load or create named session
```

**REPL Features:**
- `/help` - List all slash commands
- `/agent list|create|switch` - Manage agents within the session
- `/whisper` - Send message without tool execution
- `/permissions` - View/change permission level
- `/mcp` - List connected MCP servers
- `ESC` - Cancel current streaming response
- Logs saved to `.nexus3/logs/{session-id}/`

### Multi-Agent Workflows

The REPL includes an embedded RPC server. Create subagents for parallel work:

```bash
# In REPL, create a research agent
/agent create researcher

# Or via CLI (same server)
nexus3 rpc create reviewer --preset trusted
nexus3 rpc send reviewer "Review the changes in src/auth.py for security issues"
nexus3 rpc status reviewer
```

**Agents can communicate directly:**
```python
# From within an agent's session, send to another agent
nexus_send(agent_id="reviewer", content="What security issues did you find?")
```

### Headless Server Mode

For automation, CI/CD, or external tooling:

```bash
# Start headless server (requires NEXUS_DEV=1 for security)
NEXUS_DEV=1 nexus3 --serve 8765

# In another terminal, manage agents via RPC
nexus3 rpc create worker --preset sandboxed --cwd /path/to/project
nexus3 rpc send worker "Analyze the test coverage in tests/"
nexus3 rpc list
nexus3 rpc destroy worker
nexus3 rpc shutdown
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              NEXUS3 Server                              │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                         AgentPool                                │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │   │
│  │  │ Agent: main │  │ Agent: sub  │  │ Agent: rev  │  ...         │   │
│  │  │ (REPL)      │  │ (sandboxed) │  │ (trusted)   │              │   │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘              │   │
│  │         │                │                │                      │   │
│  │         └────────────────┼────────────────┘                      │   │
│  │                          │ nexus_send()                          │   │
│  │                          ▼                                       │   │
│  │  ┌─────────────────────────────────────────────────────────┐    │   │
│  │  │              SharedComponents                            │    │   │
│  │  │  • ProviderRegistry (LLM connections)                   │    │   │
│  │  │  • Config (layered settings)                            │    │   │
│  │  │  • PromptLoader (NEXUS.md templates)                    │    │   │
│  │  └─────────────────────────────────────────────────────────┘    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌─────────────────────┐    ┌─────────────────────────────────────┐   │
│  │    HTTP Server      │    │         GlobalDispatcher            │   │
│  │  (localhost:8765)   │───▶│  create_agent / destroy_agent       │   │
│  │  Token auth (nxk_)  │    │  list_agents / shutdown_server      │   │
│  └─────────────────────┘    └─────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

**Data Flow:**
1. User message → Session → Provider (streaming LLM response)
2. Tool calls detected → SkillRegistry → Permission check → Execute
3. Tool results → Back to LLM → Continue until done
4. Response displayed → Logged to SQLite + Markdown

## Features

### Multi-Agent System
- **Agent Isolation**: Each agent has its own context, permissions, and conversation history
- **Permission Ceilings**: Child agents cannot exceed parent's permissions
- **Direct Communication**: `nexus_send()` for synchronous inter-agent messaging
- **Session Persistence**: Save/load agent states, auto-restore on reconnect

### Security & Permissions

| Preset | Level | Description |
|--------|-------|-------------|
| `yolo` | YOLO | Full access, no confirmations (REPL-only, not available via RPC) |
| `trusted` | TRUSTED | Full access, confirms destructive operations |
| `sandboxed` | SANDBOXED | Read-only in CWD, no network, no agent management (**RPC default**) |
| `worker` | SANDBOXED | Minimal: read-only, no writes, no agent management |

**Security Features:**
- Path sandboxing with symlink attack prevention
- URL validation with SSRF protection (blocks private IPs, DNS rebinding)
- Localhost-only RPC binding with token authentication
- Secret redaction in logs and error messages
- Process group kills on timeout (no orphaned subprocesses)

### Built-in Skills (24 total)

| Category | Skills |
|----------|--------|
| **File Read** | `read_file`, `tail`, `file_info`, `list_directory`, `glob`, `grep` |
| **File Write** | `write_file`, `edit_file`, `append_file`, `regex_replace`, `copy_file`, `mkdir`, `rename` |
| **Execution** | `bash_safe` (no shell operators), `shell_UNSAFE` (full shell), `run_python` |
| **Version Control** | `git` (permission-filtered commands) |
| **Agent Management** | `nexus_create`, `nexus_destroy`, `nexus_send`, `nexus_status`, `nexus_cancel`, `nexus_shutdown` |
| **Utility** | `sleep` |

### LLM Providers

Supports multiple providers with automatic retry and streaming:

| Provider | Configuration |
|----------|---------------|
| OpenRouter | `OPENROUTER_API_KEY` (default, access to all models) |
| Anthropic | `ANTHROPIC_API_KEY` (native Claude API) |
| OpenAI | `OPENAI_API_KEY` |
| Azure OpenAI | `AZURE_OPENAI_KEY` + deployment config |
| Ollama | Local models via `http://localhost:11434` |
| vLLM | Self-hosted OpenAI-compatible endpoint |

### Context Management
- **Layered Prompts**: NEXUS.md loaded from defaults → global → ancestors → local
- **Token Budgets**: Automatic tracking with tiktoken
- **Compaction**: LLM-powered summarization when context gets full
- **Temporal Awareness**: Agents always know current date/time and session start

### MCP Integration
Connect external tools via Model Context Protocol:

```json
// .nexus3/mcp.json
{
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-filesystem", "/path/to/allow"]
    }
  }
}
```

Tools appear as `mcp_filesystem_*` skills with appropriate permission checks.

## Module Reference

| Module | Lines | Purpose |
|--------|-------|---------|
| [core](nexus3/core/README.md) | ~800 | Types (`Message`, `StreamEvent`), `AsyncProvider` protocol, permission system, path/URL security, validation utilities |
| [config](nexus3/config/README.md) | ~470 | Layered configuration loading, Pydantic schemas for all settings |
| [provider](nexus3/provider/README.md) | ~680 | LLM provider implementations, `ProviderRegistry` for multi-provider setups |
| [context](nexus3/context/README.md) | ~650 | `ContextManager` for conversation state, token counting, compaction |
| [session](nexus3/session/README.md) | ~690 | `Session` coordinator, event system, `SessionLogger`, persistence |
| [skill](nexus3/skill/README.md) | ~950 | `SkillRegistry`, base classes (`FileSkill`, `ExecutionSkill`), all built-in skills |
| [display](nexus3/display/README.md) | ~650 | `StreamingDisplay` with Rich Live, tool gumballs, summary bar |
| [cli](nexus3/cli/README.md) | ~580 | REPL implementation, argument parsing, lobby, confirmation UI |
| [rpc](nexus3/rpc/README.md) | ~880 | JSON-RPC 2.0 server, `AgentPool`, `GlobalDispatcher`, authentication |
| [mcp](nexus3/mcp/README.md) | ~650 | MCP client, transport implementations, skill adapters |
| [commands](nexus3/commands/README.md) | ~630 | Unified command infrastructure for CLI and REPL |
| [defaults](nexus3/defaults/README.md) | ~360 | Default configuration and system prompt templates |

## Configuration

Configuration is layered (later overrides earlier):
1. **Shipped defaults**: `nexus3/defaults/config.json`
2. **Global**: `~/.nexus3/config.json`
3. **Ancestors**: Parent directories' `.nexus3/config.json`
4. **Local**: `./.nexus3/config.json`

Example multi-provider setup:

```json
{
  "providers": {
    "openrouter": {
      "type": "openrouter",
      "api_key_env": "OPENROUTER_API_KEY"
    },
    "anthropic": {
      "type": "anthropic",
      "api_key_env": "ANTHROPIC_API_KEY"
    }
  },
  "default_provider": "openrouter",
  "models": {
    "fast": {"id": "anthropic/claude-haiku", "context_window": 200000},
    "smart": {"id": "anthropic/claude-sonnet-4", "context_window": 200000},
    "native": {"id": "claude-sonnet-4-20250514", "provider": "anthropic"}
  },
  "default_model": "smart"
}
```

## Development

```bash
# Run tests (2300+ tests)
.venv/bin/pytest tests/ -v

# Type checking
.venv/bin/mypy nexus3/

# Linting
.venv/bin/ruff check nexus3/

# Run specific test categories
.venv/bin/pytest tests/unit/ -v
.venv/bin/pytest tests/integration/ -v
.venv/bin/pytest tests/security/ -v
```

### Creating Custom Skills

```python
from nexus3.skill import BaseSkill, ToolResult

class MySkill(BaseSkill):
    @property
    def name(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "Does something useful"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "The input"}
            },
            "required": ["input"]
        }

    async def execute(self, input: str = "", **kwargs) -> ToolResult:
        result = do_something(input)
        return ToolResult(output=result)

# Register with factory
def my_skill_factory(container):
    return MySkill()
```

## Known Issues

**Duplicate gumballs on fast-failing tools**: When a tool fails very quickly, users may see a stale blue (ACTIVE) gumball artifact above the correct red (ERROR) gumball. This is a Rich `Live` with `transient=True` timing issue and is cosmetic only.

## License

MIT

---

**Updated**: 2026-01-21
