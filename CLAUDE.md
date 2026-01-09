# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NEXUS3 is a clean-slate rewrite of NEXUS2, an AI-powered CLI agent framework. The goal is a simpler, more maintainable, end-to-end tested agent with clear architecture.

**Status:** Phase 4 complete. Multi-agent server architecture implemented.

---

## Phases Complete

| Phase | Features |
|-------|----------|
| **0 - Core** | Message/ToolCall/ToolResult types, Config loader (Pydantic), AsyncProvider + OpenRouter, UTF-8 everywhere |
| **1 - Display** | Rich.Live streaming, ESC cancellation, Activity phases, Slash commands, Status bar |
| **1.5 - Logging** | SQLite + Markdown logs, `--verbose`, `--raw-log`, `--log-dir`, Subagent nesting |
| **2 - Context** | Multi-turn conversations, Token tracking (tiktoken), Truncation strategies, System prompt loading, HTTP JSON-RPC |
| **3 - Skills** | Skill system with DI, Built-in: read_file/write_file/sleep/nexus_*, Tool execution loop, 8 session callbacks |
| **4 - Multi-Agent** | AgentPool, GlobalDispatcher, path-based routing, `--connect` mode, NexusClient |

---

## Architecture

```
nexus3/
├── core/           # Types (Message, ToolCall, ToolResult), interfaces, errors, encoding
├── config/         # Pydantic schema, fail-fast loader
├── provider/       # AsyncProvider protocol, OpenRouter implementation
├── context/        # ContextManager, PromptLoader, TokenCounter, truncation
├── session/        # Session coordinator, SessionLogger, SQLite storage
├── skill/          # Skill protocol, SkillRegistry, ServiceContainer, builtin skills
├── display/        # StreamingDisplay, theme, console
├── cli/            # REPL, HTTP server, client commands, client mode
├── rpc/            # JSON-RPC protocol, Dispatcher, GlobalDispatcher, AgentPool
└── client.py       # NexusClient for agent-to-agent communication
```

Each module has a `README.md` with detailed documentation.

---

## Multi-Agent Server

### Architecture

```
nexus3 --serve
├── SharedComponents (config, provider, prompt_loader)
├── AgentPool
│   ├── Agent "main" → Session, Context, Dispatcher
│   └── Agent "worker" → Session, Context, Dispatcher
└── HTTP Server
    ├── POST /           → GlobalDispatcher (create/list/destroy)
    └── POST /agent/{id} → Agent's Dispatcher (send/cancel/etc)
```

### API

```bash
# Global methods (POST /)
{"method": "create_agent", "params": {"agent_id": "worker-1"}}
{"method": "list_agents"}
{"method": "destroy_agent", "params": {"agent_id": "worker-1"}}

# Agent methods (POST /agent/{id})
{"method": "send", "params": {"content": "Hello"}}
{"method": "cancel", "params": {"request_id": "..."}}
{"method": "get_tokens"}
{"method": "get_context"}
{"method": "shutdown"}
```

### Component Sharing

| Shared | Per-Agent |
|--------|-----------|
| Config | SessionLogger |
| Provider | ContextManager |
| PromptLoader | ServiceContainer |
| Base log directory | SkillRegistry, Session, Dispatcher |

---

## CLI Modes

```bash
# Standalone REPL (local)
python -m nexus3

# HTTP server (multi-agent)
python -m nexus3 --serve [PORT]

# Client mode (connect to server)
python -m nexus3 --connect [URL] --agent [ID]

# One-shot commands
python -m nexus3 send <url> <content>
python -m nexus3 cancel <url> <id>
python -m nexus3 status <url>
python -m nexus3 shutdown <url>
```

---

## Built-in Skills

| Skill | Description |
|-------|-------------|
| `read_file` | Read file contents with cross-platform path handling |
| `write_file` | Write/create files |
| `sleep` | Pause execution (for testing) |
| `nexus_send` | Send message to another agent |
| `nexus_cancel` | Cancel in-progress request |
| `nexus_status` | Get agent tokens + context |
| `nexus_shutdown` | Request agent shutdown |

---

## Design Principles

1. **Async-first** - asyncio throughout, not threading
2. **Fail-fast** - No silent exception swallowing
3. **Single source of truth** - One way to do each thing
4. **Minimal viable interfaces** - Small, well-typed protocols
5. **End-to-end tested** - Integration tests, not just unit tests
6. **Document as you go** - Update this file and module READMEs

---

## Development SOPs

| SOP | Description |
|-----|-------------|
| Type Everything | No `Optional[Any]`. Use Protocols for interfaces. |
| Fail Fast | Errors surface immediately. No `pass`. No swallowed exceptions. |
| One Way | Features go in skills or CLI flags, not scripts. |
| Explicit Encoding | Always `encoding='utf-8', errors='replace'`. |
| Test E2E | Every feature gets an integration test. |
| Document | Each phase updates this file and module READMEs. |
| No Dead Code | Delete unused code. Run `ruff check --select F401`. |

---

## Key Interfaces

```python
# Skill Protocol
class Skill(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def description(self) -> str: ...
    @property
    def parameters(self) -> dict[str, Any]: ...
    async def execute(self, **kwargs: Any) -> ToolResult: ...

# AsyncProvider Protocol
class AsyncProvider(Protocol):
    def stream(self, messages, tools) -> AsyncIterator[StreamEvent]: ...
```

---

## Testing

```bash
source .venv/bin/activate
pytest tests/ -v                              # All tests (366)
pytest tests/integration/ -v                  # Integration only
ruff check nexus3/                            # Linting
mypy nexus3/                                  # Type checking
```

---

## Configuration

```
~/.nexus3/
├── config.json      # Global config
└── NEXUS.md         # Personal system prompt

./NEXUS.md           # Project system prompt (overrides personal)
.nexus3/logs/        # Session logs (gitignored)
```

---

## Next Phase: Phase 5 - Subagent Spawning

- SubagentPool integration with spawn_agent skill
- Permission levels: YOLO > TRUSTED > SANDBOXED
- Nested subagents with automatic port allocation
- Workflow coordination

---

## Development Note

Use subagents liberally for implementation tasks to manage context window:
- Writing new modules
- Writing tests
- Code modifications
- Research tasks

Main conversation focuses on planning, decisions, and coordination.
