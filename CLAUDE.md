# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NEXUS3 is a clean-slate rewrite of NEXUS2, an AI-powered CLI agent framework. The goal is a simpler, more maintainable, end-to-end tested agent with clear architecture.

**Status:** Phase 3 complete. Phase 4 in progress.

---

## Current Phase: Phase 4 - Full Productivity Skills

**Goal**: Git, search, editing, agent control skills.

### What's Working (Phases 0-3 Complete)

| Phase | Features |
|-------|----------|
| **0 - Core** | Message/ToolCall/ToolResult types, Config loader (Pydantic), AsyncProvider + OpenRouter, UTF-8 everywhere |
| **1 - Display** | Rich.Live streaming, ESC cancellation, Activity phases (WAITING→RESPONDING→THINKING), Slash commands, Status bar |
| **1.5 - Logging** | SQLite + Markdown logs, `--verbose`, `--raw-log`, `--log-dir`, Subagent nesting |
| **2 - Context** | Multi-turn conversations, Token tracking (tiktoken), Truncation strategies, System prompt loading (personal + project), HTTP JSON-RPC (`--serve`), RPC: send/shutdown/get_tokens/get_context/cancel |
| **3 - Skills** | Skill system with DI (ServiceContainer, SkillRegistry), Built-in: read_file/write_file/sleep, Streaming tool detection, Tool execution loop (sequential/parallel), 8 session callbacks, Thinking duration tracking, Cross-platform paths |

### Known Limitations
- No compaction workflow yet (summarizing old messages)
- No animation during input (prompt_toolkit limitation)

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
├── cli/            # REPL (repl.py), HTTP server (serve.py), commands, keys
├── rpc/            # JSON-RPC protocol, Dispatcher, HTTP server
└── client.py       # NexusClient for agent-to-agent communication (planned)
```

Each module has a `README.md` with detailed documentation.

---

## Development Phases

### Completed ✅

| Phase | Goal | Key Deliverables |
|-------|------|------------------|
| 0 | MVP Chat | Core types, config, provider, session, CLI |
| 1 | Display Foundation | Rich.Live, ESC cancel, status bar, callbacks |
| 1.5 | Logging | SQLite + MD logs, verbose/raw streams |
| 2 | Context + IPC | Multi-turn, tokens, truncation, HTTP JSON-RPC |
| 3 | Core Skills | read_file, write_file, sleep, tool loop |

### Phase 4: Full Productivity Skills (Current)
- [ ] `edit_file`, `glob`, `grep`, `git_status`, `git_diff`, `git_log`
- [ ] File operations: `delete_file`, `copy_path`, `move_path`, `make_dir`
- [ ] **NexusClient + agent control skills** (see plan below)

### Phase 5+: Subagents
- SubagentPool, spawn_agent skill, process management
- 3-level permissions: YOLO > TRUSTED > SANDBOXED
- Nested subagents, workflow coordination

---

## NexusClient + Agent Control Skills (Phase 4)

**Goal**: Enable Nexus agents (and Claude Code) to control other Nexus agents via JSON-RPC.

### Layer 1: Protocol Extensions (`nexus3/rpc/protocol.py`)

Add client-side helpers (~15 lines):
```python
def serialize_request(request: Request) -> str: ...
def parse_response(line: str) -> Response: ...
```

### Layer 2: NexusClient (`nexus3/client.py`)

Async HTTP client for JSON-RPC (~80 lines):
```python
class NexusClient:
    def __init__(self, url: str = "http://127.0.0.1:8765", timeout: float = 60.0): ...

    async def __aenter__(self) -> "NexusClient": ...
    async def __aexit__(self, *args) -> None: ...

    async def send(self, content: str, request_id: str | None = None) -> dict: ...
    async def cancel(self, request_id: str) -> dict: ...
    async def get_tokens(self) -> dict: ...
    async def get_context(self) -> dict: ...
    async def shutdown(self) -> dict: ...
```

Uses httpx (already a dependency), context manager pattern, connection pooling.

### Layer 3: Agent Control Skills

| Skill | Description | Parameters |
|-------|-------------|------------|
| `nexus_send` | Send message to agent | `url`, `content`, `request_id?` |
| `nexus_cancel` | Cancel in-progress request | `url`, `request_id` |
| `nexus_status` | Get tokens + context info | `url` |
| `nexus_shutdown` | Request graceful shutdown | `url` |

Skills wrap NexusClient, return ToolResult with JSON output.

### Implementation Order

1. Add `serialize_request`, `parse_response` to protocol.py
2. Create `nexus3/client.py` with NexusClient
3. Create skills in `nexus3/skill/builtin/nexus_*.py`
4. Update registration.py
5. Tests

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

### SOP 1: Type Everything
No `Optional[Any]`. No duck-typing with `hasattr()`. Use Protocols for interfaces.

### SOP 2: Fail Fast
Errors surface immediately. No `pass`. No swallowed exceptions.

### SOP 3: One Way to Do Each Thing
No script proliferation. Features go in skills or CLI flags.

### SOP 4: Explicit Encoding
Always `encoding='utf-8', errors='replace'` for files and subprocesses.

### SOP 5: Test End-to-End
Every feature gets an integration test. Manual testing before merge.

### SOP 6: Document Architecture
Each phase updates this file and relevant module READMEs.

### SOP 7: No Dead Code
Delete unused code immediately. Run `ruff check --select F401`.

### SOP 8: Module Documentation
Each module has README.md with: Purpose, Key Types, Interfaces, Data Flow, Dependencies, Examples.

---

## Key Interfaces

```python
# Skill Protocol (nexus3/skill/base.py)
class Skill(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def description(self) -> str: ...
    @property
    def parameters(self) -> dict[str, Any]: ...
    async def execute(self, **kwargs: Any) -> ToolResult: ...

# AsyncProvider Protocol (nexus3/core/interfaces.py)
class AsyncProvider(Protocol):
    async def stream(self, messages, tools) -> AsyncIterator[StreamEvent]: ...
```

---

## Permission System (Phase 5+)

```
YOLO (dangerous) > TRUSTED (default interactive) > SANDBOXED (restricted)
```

| Level | Capabilities |
|-------|--------------|
| YOLO | All skills without approval, human-only |
| TRUSTED | Read/write anywhere, asks before commands, can spawn SANDBOXED |
| SANDBOXED | Read/write in working_dir only, no commands, no spawning |

---

## Configuration

```
~/.nexus3/
├── config.json      # Global config
└── NEXUS.md         # Personal system prompt

./NEXUS.md           # Project system prompt (overrides personal)
.nexus3/logs/        # Session logs (gitignored)
```

Config is JSON only. System prompts are Markdown.

---

## CLI Commands

```bash
python -m nexus3                    # Interactive REPL
python -m nexus3 --serve [PORT]     # HTTP JSON-RPC server (default 8765)
python -m nexus3 --verbose          # Enable thinking traces, timing
python -m nexus3 --raw-log          # Enable raw API logging
python -m nexus3 --log-dir PATH     # Custom log directory
python -m nexus3 --reload           # Auto-reload on code changes (serve mode)
```

Slash commands: `/quit`, `/exit`, `/q`

---

## Testing

```bash
source .venv/bin/activate
pytest tests/ -v                              # All tests
pytest tests/integration/ -v                  # Integration only
pytest tests/ --cov=nexus3 --cov-report=term  # With coverage
ruff check nexus3/                            # Linting
mypy nexus3/                                  # Type checking
```

Uses **uv** for package management:
```bash
uv venv --python 3.11 .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

---

## Dependencies

**Core:** httpx, rich, prompt-toolkit, pydantic, tiktoken
**Dev:** pytest, pytest-asyncio, pytest-cov, ruff, mypy

---

## What We're NOT Carrying from NEXUS2

| Removed | Reason |
|---------|--------|
| 4-level permissions | Simplified to 3 levels |
| Tag-based approval | Profile-only system |
| 20+ scripts | Skills or CLI flags |
| Swarm orchestration | Never finished |
| hasattr/getattr patterns | Proper Protocols |
| Thread-based spinners | Async Rich.Live |
| Separate agent venv | Use parent's Python |

---

## Display Architecture

**Key insight**: prompt_toolkit and Rich.Live can't both control terminal. Solution: clean handoff.

- **During input**: prompt_toolkit owns terminal, bottom toolbar shows status
- **During streaming**: Rich.Live owns terminal, shows spinner + response + status

**Gumballs** (status indicators):
```
● cyan   = active     ● green  = ready/complete
● red    = error      ● yellow = cancelled
○ dim    = pending    ■ dim    = placeholder
```

Key files: `display/streaming.py` (StreamingDisplay), `cli/repl.py` (handoff logic)

---

## HTTP JSON-RPC Server

**Usage:** `nexus3 --serve [PORT]` (default 8765, localhost only)

**Methods:**
| Method | Params | Returns |
|--------|--------|---------|
| `send` | `{content, request_id?}` | `{content, request_id}` or `{cancelled, request_id}` |
| `cancel` | `{request_id}` | `{cancelled, request_id, reason?}` |
| `get_tokens` | none | Token usage dict |
| `get_context` | none | `{message_count, system_prompt}` |
| `shutdown` | none | `{success: true}` |

See `nexus3/rpc/README.md` for full protocol documentation.

---

## Development Note: Subagent Usage

Use subagents liberally for implementation tasks to manage context window:
- Writing new modules
- Writing tests
- Code modifications
- Research tasks

Main conversation focuses on planning, decisions, and coordination.
