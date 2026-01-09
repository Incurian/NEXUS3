# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NEXUS3 is a clean-slate rewrite of NEXUS2, an AI-powered CLI agent framework. The goal is a simpler, more maintainable, end-to-end tested agent with clear architecture.

**Status:** Phase 4 complete. Code review complete. Remediation planned.

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

## Code Review Issues (2026-01-08)

Full review in `/code-review/SUMMARY.md`. 21 files analyzed.
**Detailed remediation plan:** `/REMEDIATION_PLAN.md` (~600 lines, 40-50 hrs estimated)

### Overall Grades

| Category | Grade | Notes |
|----------|-------|-------|
| Architecture | A- | Clean separation, Protocol-based design |
| Code Quality | B+ | Consistent patterns, some duplication |
| Security | C+ | Critical gaps for production |
| Test Coverage | B- | Good foundation, missing critical paths |
| Documentation | A | Excellent READMEs |

### Critical Issues (Must Fix)

| # | Issue | Module | Type |
|---|-------|--------|------|
| 1 | No authentication on HTTP server | rpc/http | Security |
| 2 | Path traversal in file skills | skill/builtin | Security |
| 3 | SSRF in nexus_send | skill/builtin | Security |
| 4 | Tool call/result pair corruption in truncation | context/manager | Data Integrity |
| 5 | Blocking file I/O in async skills | skill/builtin | Performance |
| 6 | No provider tests | provider | Reliability |
| 7 | Raw log callback race in multi-agent | rpc/pool | Logging |
| 8 | In-progress requests not cancelled on destroy | rpc/pool | Resource Leak |
| 9 | Messages never garbage collected | context/manager | Memory Leak |
| 10 | Missing encoding in file operations | session/markdown | Cross-platform |

---

## Remediation Plan: Phase 5R (Review Fixes)

### Phase 5R.1: Security Hardening (Critical)

**Goal:** Make HTTP server production-safe.

| Task | Description | Files |
|------|-------------|-------|
| 5R.1.1 | Add API key authentication to HTTP server | `rpc/http.py` |
| 5R.1.2 | Implement path sandboxing for file skills | `skill/builtin/read_file.py`, `write_file.py` |
| 5R.1.3 | Add URL allowlist for nexus_send (SSRF protection) | `skill/builtin/nexus_send.py` |
| 5R.1.4 | Fix JSON injection in error responses | `rpc/http.py` |

**Implementation:**
```python
# 5R.1.1: API Key Auth
# - Generate random API key on server start
# - Require Authorization: Bearer <key> header
# - Print key to console on startup

# 5R.1.2: Path Sandboxing
# - Add allowed_paths config option
# - Validate resolved paths stay within allowed directories
# - Block symlink attacks with realpath check

# 5R.1.3: SSRF Protection
# - Restrict to localhost URLs by default
# - Add allowed_hosts config for external access
```

### Phase 5R.2: Data Integrity Fixes

**Goal:** Fix data corruption and memory leaks.

| Task | Description | Files |
|------|-------------|-------|
| 5R.2.1 | Fix truncation to preserve tool call/result pairs | `context/manager.py` |
| 5R.2.2 | Add message garbage collection | `context/manager.py` |
| 5R.2.3 | Cancel in-progress requests on agent destroy | `rpc/pool.py` |
| 5R.2.4 | Add explicit encoding to all file operations | `session/*.py`, `config/loader.py` |

**Implementation:**
```python
# 5R.2.1: Truncation Fix
# - Track tool_call_id associations
# - Always keep tool call + result together
# - Truncate as pairs, not individual messages

# 5R.2.2: GC for Messages
# - Add max_messages config (default 1000)
# - Prune oldest messages beyond limit
# - Respect tool pair integrity during pruning
```

### Phase 5R.3: Async/Performance Fixes

**Goal:** Proper async patterns throughout.

| Task | Description | Files |
|------|-------------|-------|
| 5R.3.1 | Convert blocking file I/O to async | `skill/builtin/*.py` |
| 5R.3.2 | Add skill execution timeout | `session/session.py` |
| 5R.3.3 | Add concurrency limit for parallel tools | `session/session.py` |
| 5R.3.4 | Fix raw log callback race condition | `rpc/pool.py` |

**Implementation:**
```python
# 5R.3.1: Async File I/O
# - Use asyncio.to_thread() for file operations
# - Or use aiofiles library

# 5R.3.2: Skill Timeout
async def _execute_single_tool(self, tc):
    return await asyncio.wait_for(
        skill.execute(**args),
        timeout=self._skill_timeout  # Default 300s
    )

# 5R.3.3: Parallel Concurrency Limit
MAX_CONCURRENT_TOOLS = 5
semaphore = asyncio.Semaphore(MAX_CONCURRENT_TOOLS)
```

### Phase 5R.4: Test Coverage Expansion

**Goal:** Cover critical untested paths.

| Task | Description | Priority |
|------|-------------|----------|
| 5R.4.1 | Add provider unit tests (mock HTTP) | High |
| 5R.4.2 | Add context manager truncation tests | High |
| 5R.4.3 | Add file skill security tests | High |
| 5R.4.4 | Add CLI/REPL tests | Medium |
| 5R.4.5 | Add HTTP server tests | Medium |

### Phase 5R.5: Minor Fixes

| Task | Description | Files |
|------|-------------|-------|
| 5R.5.1 | Export ReasoningDelta from core | `core/__init__.py` |
| 5R.5.2 | Add `extra="forbid"` to Pydantic models | `config/schema.py` |
| 5R.5.3 | Consolidate duplicate InvalidParamsError | `rpc/errors.py` |
| 5R.5.4 | Remove dead code (cli/output.py) | `cli/output.py` |
| 5R.5.5 | Fix unused verbose/raw_log params | `cli/repl.py` |
| 5R.5.6 | Add provider retry logic | `provider/openrouter.py` |
| 5R.5.7 | Make max_iterations configurable | `session/session.py` |

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
