# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NEXUS3 is a clean-slate rewrite of NEXUS2, an AI-powered CLI agent framework. The goal is a simpler, more maintainable, end-to-end tested agent with clear architecture.

**Status:** Phase 6 integration complete (812 tests pass). Known bugs to fix post-compaction.

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
# Standalone REPL (auto-starts embedded server)
nexus

# HTTP server (headless multi-agent)
nexus --serve [PORT]

# Client mode (connect to existing server)
nexus --connect [URL] --agent [ID]

# RPC commands (see "NEXUS3 Command Aliases" below for full list)
nexus-rpc create worker-1
nexus-rpc send worker-1 "Hello"
nexus-rpc shutdown
```

---

## Built-in Skills

| Skill | Parameters | Description |
|-------|------------|-------------|
| `read_file` | `path` | Read file contents |
| `write_file` | `path`, `content` | Write/create files |
| `sleep` | `seconds` | Pause execution (for testing) |
| `nexus_create` | `agent_id`, `port`? | Create a new agent |
| `nexus_destroy` | `agent_id`, `port`? | Remove an agent (server keeps running) |
| `nexus_send` | `agent_id`, `content`, `port`? | Send message to an agent |
| `nexus_status` | `agent_id`, `port`? | Get agent tokens + context |
| `nexus_cancel` | `agent_id`, `request_id`, `port`? | Cancel in-progress request |
| `nexus_shutdown` | `port`? | Shutdown the entire server |

*Note: `port` defaults to 8765. Skills mirror `nexus-rpc` CLI commands exactly.*

---

## Design Principles

1. **Async-first** - asyncio throughout, not threading
2. **Fail-fast** - No silent exception swallowing
3. **Single source of truth** - One way to do each thing
4. **Minimal viable interfaces** - Small, well-typed protocols
5. **End-to-end tested** - Integration tests, not just unit tests
6. **Document as you go** - Update this file and module READMEs
7. **Unified invocation patterns** - CLI commands, NEXUS3 skills, and NexusClient methods should mirror each other. Users, Claude, and NEXUS3 agents should all use the same interface patterns (e.g., `agent_id` not URLs). This reduces cognitive load and ensures changes propagate consistently.

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
pytest tests/ -v                              # All tests
pytest tests/integration/ -v                  # Integration only
ruff check nexus3/                            # Linting
mypy nexus3/                                  # Type checking
```

---

## NEXUS3 Command Aliases

**IMPORTANT:** When testing or demonstrating NEXUS3, always use the shell aliases, never raw `python -m nexus3` or `.venv/bin/python` invocations. The user prefers clean, natural commands.

Two aliases are installed in `~/.local/bin/`:

```bash
# Interactive modes
nexus                        # REPL with embedded server (default)
nexus --serve [PORT]         # Headless server mode
nexus --connect [URL]        # Connect to existing server

# Programmatic RPC operations
nexus-rpc detect             # Check if server is running
nexus-rpc list               # List agents (auto-starts server)
nexus-rpc create ID          # Create agent (auto-starts server)
nexus-rpc destroy ID         # Destroy agent
nexus-rpc send AGENT MSG     # Send message to agent
nexus-rpc status AGENT       # Get agent status
nexus-rpc shutdown           # Stop server (graceful)
nexus-rpc cancel AGENT ID    # Cancel in-progress request
```

**Key behaviors:**
- `nexus-rpc list` and `nexus-rpc create` auto-start a server if none running
- `nexus-rpc send/status/destroy/shutdown` require server to be running
- All commands use `--port N` to specify non-default port (default: 8765)

**User preference:** Commands should be simple and clean. Avoid:
- Sourcing virtualenvs manually
- Using `python -m nexus3` directly
- Using full paths to scripts
- Any invocation that isn't `nexus` or `nexus-rpc`

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

### Phase 5R.1: Security Hardening + REPL Unification

**Goal:** Make HTTP server production-safe AND unify REPL to use server internally.

#### 5R.1.0: REPL Unification (Prerequisite)

Unify standalone REPL to use AgentPool internally, with server collision detection.

**New CLI Behavior:**
```bash
nexus3              # Check for server → connect if exists, else start embedded + REPL
nexus3 --serve      # Check for server → error if exists, else start headless
nexus3 --connect    # Check for server → error if not exists, else connect
```

**Server Collision Detection:**
```python
# nexus3/rpc/detection.py
async def detect_server(port: int) -> DetectionResult:
    """Probe port with list_agents RPC to identify NEXUS3 servers."""
    # Returns: NO_SERVER, NEXUS_SERVER, OTHER_SERVICE, TIMEOUT, ERROR
```

**Unified REPL Architecture:**
```
nexus3 (no flags)
├── detect_server(8765)
│   ├── NEXUS_SERVER → connect as client (read key from ~/.nexus3/server.key)
│   └── NO_SERVER → start embedded server + REPL
│       ├── Create SharedComponents
│       ├── Create AgentPool with "main" agent
│       ├── Generate API key → write to ~/.nexus3/server.key
│       ├── Start HTTP server as background task
│       └── Run REPL calling session directly (preserves streaming UX)
```

**Key Insight:** REPL calls Session directly (not via HTTP) to preserve streaming callbacks.
External clients use HTTP. This tests the full agent lifecycle without HTTP overhead locally.

**Files:**
- NEW: `nexus3/rpc/detection.py` - Server detection
- NEW: `nexus3/rpc/auth.py` - Key generation/validation
- MODIFY: `nexus3/cli/repl.py` - Unified startup logic
- MODIFY: `nexus3/cli/serve.py` - Collision detection

#### 5R.1.1: API Key Authentication

**Key Format:** `nxk_` + 32 bytes URL-safe Base64 (e.g., `nxk_7Ks9XmN2pLqR4Tv8...`)

**Key Storage:**
```
~/.nexus3/
├── server.key          # Default (port 8765)
└── server-{port}.key   # Port-specific
```

**Key Discovery Order (Client):**
1. `--api-key` CLI flag
2. `NEXUS3_API_KEY` environment variable
3. `~/.nexus3/server-{port}.key`
4. `~/.nexus3/server.key`

**Server Startup:**
```
$ nexus3 --serve
NEXUS3 server on http://127.0.0.1:8765
API key: nxk_7Ks9XmN2pLqR4Tv8YbHc1WzJ5AfD6GiE0MnO3PuQ9
Key file: ~/.nexus3/server.key
```

**Files:**
- NEW: `nexus3/rpc/auth.py` - `generate_api_key()`, `validate_api_key()`, `ServerKeyManager`
- MODIFY: `nexus3/rpc/http.py` - Add auth middleware (401/403 responses)
- MODIFY: `nexus3/client.py` - Add `api_key` param with auto-discovery
- MODIFY: `nexus3/cli/client_commands.py` - Add `--api-key` flag
- MODIFY: `nexus3/skill/builtin/nexus_*.py` - Use key from ServiceContainer

#### 5R.1.2: Path Sandboxing

**Default:** CWD only. **Configurable:** `allowed_paths` in config.

**Implementation:**
```python
# Extend nexus3/core/paths.py
def validate_sandbox(path: str, allowed: list[Path]) -> Path:
    """Validate path is within sandbox. Raises PathSecurityError if not."""
    resolved = Path(path).resolve()
    # Block symlink attacks
    if resolved.is_symlink():
        raise PathSecurityError(path, "Symlinks not allowed")
    # Check allowed paths
    for allowed_path in allowed:
        if resolved.is_relative_to(allowed_path):
            return resolved
    raise PathSecurityError(path, "Path outside sandbox")
```

**Files:**
- MODIFY: `nexus3/core/paths.py` - Add `validate_sandbox()`, `PathSecurityError`
- MODIFY: `nexus3/config/schema.py` - Add `allowed_paths: list[str] = ["."]`
- MODIFY: `nexus3/skill/builtin/read_file.py` - Use sandbox validation
- MODIFY: `nexus3/skill/builtin/write_file.py` - Use sandbox validation

#### 5R.1.3: SSRF Protection

**Default:** Localhost only (`127.0.0.1`, `localhost`). Always block cloud metadata IPs.

**Files:**
- NEW: `nexus3/core/url_validator.py` - `validate_url()`, `UrlSecurityError`
- MODIFY: `nexus3/skill/builtin/nexus_send.py` - Validate URL before request
- MODIFY: `nexus3/skill/builtin/nexus_cancel.py` - Same
- MODIFY: `nexus3/skill/builtin/nexus_status.py` - Same
- MODIFY: `nexus3/skill/builtin/nexus_shutdown.py` - Same

#### 5R.1.4: JSON Injection Fix

Replace f-string JSON with `json.dumps()` in error responses.

**Files:**
- MODIFY: `nexus3/rpc/http.py` - Use `json.dumps({"error": str(e)})`

---

#### Phase 5R.1 Implementation Order

1. **5R.1.4** - JSON injection (5 min, low risk)
2. **5R.1.1** - Auth system (`rpc/auth.py`, key generation)
3. **5R.1.0** - Server detection (`rpc/detection.py`)
4. **5R.1.0** - REPL unification (modify `cli/repl.py`)
5. **5R.1.1** - HTTP auth middleware + client changes
6. **5R.1.2** - Path sandboxing (extend `core/paths.py`)
7. **5R.1.3** - SSRF protection (`core/url_validator.py`)
8. **Tests** - Auth, sandbox, SSRF, collision detection

#### New Files Summary

| File | Purpose |
|------|---------|
| `nexus3/rpc/auth.py` | Key generation, validation, ServerKeyManager |
| `nexus3/rpc/detection.py` | Server collision detection |
| `nexus3/core/url_validator.py` | SSRF protection |
| `tests/unit/test_auth.py` | Auth tests |
| `tests/unit/test_detection.py` | Collision detection tests |
| `tests/unit/test_sandbox.py` | Path sandbox tests |
| `tests/unit/test_url_validator.py` | SSRF tests |

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

## Current Phase: Phase 6 - Agent Management System

### Implementation Status

**Infrastructure Complete (834 tests pass):**

| Subphase | Status | Files Created |
|----------|--------|---------------|
| 6.1 Session Persistence | ✅ Done | `session/persistence.py`, `session/session_manager.py` |
| 6.2 Unified Commands | ✅ Done | `commands/protocol.py`, `commands/core.py` |
| 6.3 Agent Naming | ✅ Done | Modified `rpc/pool.py` (is_temp, generate_temp_id) |
| 6.4 REPL Commands | ✅ Done | `cli/whisper.py`, `cli/repl_commands.py` |
| 6.5 Lobby Mode | ✅ Done | `cli/lobby.py` |
| 6.6 Auto-Restore | ✅ Done | Modified `rpc/pool.py`, `rpc/http.py` |
| 6.7 Permissions | ✅ Done | `core/permissions.py` |

**Integration Complete (2026-01-09):**

All Phase 6 features wired into `repl.py`:
- ✅ CLI flags: `--resume`, `--fresh`, `--session NAME`, `--template PATH`
- ✅ Lobby on startup with CLI flag bypass
- ✅ Slash command routing to 20+ commands
- ✅ Whisper mode with dynamic prompts and message routing
- ✅ Agent switching with callback re-attachment
- ✅ Auto-save to `last-session.json` after each interaction

### Known Bugs

| Bug | Status | Location | Issue |
|-----|--------|----------|-------|
| `/send` broken | **FIXED** | `commands/core.py:174` | Now uses async generator properly |
| `/agent foo` (nonexistent) | **FIXED** | `repl.py:718-774` | Handles y/n prompt and creates agent |
| `/whisper foo` (nonexistent) | **FIXED** | `repl.py:718-774` | Handles y/n prompt and enters whisper |
| `get_token_summary` typo | **FIXED** | Multiple files | Changed to `get_token_usage()` |
| `/agent foo` (saved) | **FIXED** | `repl_commands.py:122-137` | Now offers to restore saved sessions |
| Last session not updating | **FIXED** | `repl.py:415-430, 734` | Updates on startup and agent switch |
| WSL terminal closes on exit | **INVESTIGATING** | Unknown | See "WSL Terminal Issue" below |
| `/permissions` placeholder | Deferred | `repl_commands.py:315` | Returns "trusted" but doesn't track per-agent |
| `/save` metadata incomplete | Deferred | `commands/core.py:328-330` | Missing `system_prompt_path`, `working_directory`, `permission_level` |

### WSL Terminal Issue

**Symptom:** After `nexus` exits (via `/quit` or lobby `q`), the WSL bash session closes and returns to PowerShell instead of staying in WSL.

**Environment:** PowerShell 7.5.4 → Windows Terminal → `wsl` command → bash → `nexus`

**Debugging performed:**
- Added DEBUG output: Python exits cleanly, all debug messages print
- Tried `os._exit(0)` to bypass Python cleanup: Still crashes
- Tried `stty sane` terminal reset: No effect
- Tried various Rich Console options: No effect
- Tested with `git stash` (pre-today's changes): Still crashes
- **Conclusion:** Issue predates today's changes, may be environmental or in earlier commits

**Not caused by:**
- Today's session management changes
- Rich `legacy_windows` option
- Python atexit handlers (os._exit tested)

**To investigate later:**
- Check older git commits
- Test on fresh WSL instance
- Check for WSL/Windows Terminal updates
- Try minimal Rich/prompt_toolkit reproduction

### Partially Implemented

| Feature | Status | Notes |
|---------|--------|-------|
| Permission levels | Defined, not enforced | `core/permissions.py` has types but skills don't check them |
| SQLite session markers | Schema exists | Markers not written on session create/destroy |
| Working directory tracking | `/cwd` works | But not persisted in session save/restore |

**New Test Files (234 new tests):**
- `tests/unit/test_persistence.py` (39)
- `tests/unit/test_agent_naming.py` (28)
- `tests/unit/test_session_markers.py` (29)
- `tests/unit/test_commands.py` (51)
- `tests/unit/test_permissions.py` (61)
- `tests/unit/test_whisper.py` (30)
- `tests/unit/test_repl_commands.py` (45)
- `tests/unit/test_lobby.py` (36)
- `tests/unit/test_auto_restore.py` (11)

**Key New Modules:**
- `nexus3/commands/` - Unified command infrastructure
- `nexus3/session/persistence.py` - SavedSession, serialize/deserialize
- `nexus3/session/session_manager.py` - SessionManager for disk storage
- `nexus3/cli/lobby.py` - show_lobby(), LobbyChoice, LobbyResult
- `nexus3/cli/whisper.py` - WhisperMode class
- `nexus3/cli/repl_commands.py` - cmd_agent, cmd_whisper, cmd_over, etc.
- `nexus3/core/permissions.py` - PermissionLevel, PermissionPolicy

### Overview

A comprehensive agent management system with:
- Flat agent hierarchy (no special "main" agent)
- Session persistence (save/restore agents)
- Unified CLI and REPL commands
- Whisper mode for side conversations
- Permission levels per agent

### Startup Flow (Lobby Mode)

```
$ nexus

NEXUS3 REPL

  1) Resume: my-project (2h ago, 45 messages)
  2) Fresh session
  3) Choose from saved...

[1/2/3]:
```

**CLI Overrides:**
- `nexus --resume` → restore last session
- `nexus --fresh` → create temp agent `.1`
- `nexus --fresh --template path/to/prompt.md` → fresh with custom prompt
- `nexus --session my-project` → load specific session

### Agent Naming & Persistence

| Type | Format | Examples | In saved list? | Restorable after shutdown? |
|------|--------|----------|----------------|---------------------------|
| Named (saved) | alphanumeric | `worker-1`, `my-project` | Yes | Yes |
| Temp (drone) | `.prefix` | `.1`, `.2`, `.quick-test` | No | No (except last session) |

**Note:** Both temp and saved sessions write to SQLite logs (for debugging/history).
The difference is whether they appear in `sessions/` directory and the "Choose from saved" list.

**Fresh session = temp session**: Lobby option "Fresh session" creates `.1` (temp).
Use `/save myname` to promote to a saved session.

### Unified Command Set

Commands work identically as `nexus-rpc <cmd>` (CLI) and `/<cmd>` (REPL slash command).
Both use the same underlying code.

| Command | Args | Purpose |
|---------|------|---------|
| `list` | | List all agents (interactive in REPL) |
| `create` | `<name> [--sandboxed\|--trusted\|--yolo]` | Create agent without switching |
| `destroy` | `<name>` | Remove active agent from pool |
| `send` | `<agent> <message>` | One-shot message to another agent |
| `status` | `[agent]` | Agent status (default: current) |
| `cancel` | `[agent] [request_id]` | Cancel in-progress request |
| `shutdown` | | Stop server |
| `save` | `[name]` | Save session (prompts for name if temp) |
| `clone` | `<src> <dest>` | Clone agent (active→active, saved→saved) |
| `rename` | `<old> <new>` | Rename agent |
| `delete` | `<name>` | Delete saved session from disk |

### REPL-Only Commands

| Command | Args | Purpose |
|---------|------|---------|
| `/agent` | `[name] [--perm]` | View current / switch / create+switch |
| `/whisper` | `<agent>` | Enter persistent send mode |
| `/over` | | Exit whisper mode |
| `/cwd` | `[path]` | Show/set working directory |
| `/permissions` | `[level]` | Show/set permission level |
| `/prompt` | `[file]` | Show/set system prompt |
| `/help` | | Help |
| `/clear` | | Clear conversation display |
| `/quit` | | Exit REPL |

### Whisper Mode

Persistent send mode for extended conversations with another agent:

```
You: Hello main agent

A: Hello! How can I help?

You: /whisper worker-1
┌── whisper mode: worker-1 ── /over to return ──┐

worker-1> What is 2+2?

worker-1: 2+2 equals 4.

worker-1> /over
└── returned to main ──────────────────────────┘

You: As I was saying...
```

**Behavior:**
- Prompt changes to `<agent>>`
- Visual indicators show whisper mode active
- `/whisper <nonexistent>` prompts "Create? y/n"

### Side Conversation Context

| Location | Included? | Reasoning |
|----------|-----------|-----------|
| Target agent history | **Yes** | They experienced it |
| Current agent history | **No** | Side channel, user can copy if needed |

### `/agent` vs `/create` Behavior

| Command | Action |
|---------|--------|
| `/create foo` | Create foo, stay on current agent |
| `/agent foo` | Switch to foo (prompts to create if doesn't exist) |
| `/agent` | Show current agent's detailed status |

### Cross-Session Auto-Restore

When external request targets a saved (inactive) agent:
```
$ nexus-rpc send archived-helper "Wake up"
[auto-restoring archived-helper from saved session]
{"content": "Hello! I'm back.", ...}
```

### Permission Levels

| Level | Description |
|-------|-------------|
| `--yolo` | Full access, no confirmations |
| `--trusted` | Confirmations for destructive actions |
| `--sandboxed` | Limited paths, restricted network |

### Session Storage

```
~/.nexus3/
├── sessions/
│   ├── my-project.json    # Named saved sessions
│   └── analyzer.json
├── last-session.json      # Last user session (temp OR saved) - always restorable
├── last-session-name      # What the last session was called (".1" or "myproject")
├── config.json
└── server.key
```

**What gets saved in session JSON:**
- Conversation history (messages)
- System prompt (path or content)
- Working directory
- Permission level
- Token usage stats
- Created/modified timestamps
- Provenance (creator: user or parent agent ID)

**Last session behavior:**
- Every user-connected session auto-persists to `last-session.json` as you work
- "Resume" in lobby always works, even if last session was temp `.1`
- Subagent sessions do NOT overwrite `last-session.json` (only direct user connection)
- "Choose from saved" only shows `sessions/` directory contents

### SQLite Log Markers (for cleanup)

All sessions log to SQLite for debugging. Add metadata to identify orphaned logs:

| Column | Values | Purpose |
|--------|--------|---------|
| `session_type` | `'saved'` \| `'temp'` \| `'subagent'` | What kind of session |
| `session_status` | `'active'` \| `'destroyed'` \| `'orphaned'` | Current state |
| `parent_agent_id` | agent ID or `null` | Who spawned this (for subagents) |

This enables queries like: "find all temp/destroyed sessions older than 30 days" for optional cleanup.

### Agent Lifecycle

```
┌─────────────────────────────────────────────────────────────────┐
│                         SAVED SESSIONS                          │
│                    (~/.nexus3/sessions/*.json)                  │
│                                                                 │
│   ┌─────────┐    /save name    ┌─────────┐                     │
│   │ Active  │ ────────────────▶│  Saved  │                     │
│   │ (named) │ ◀────────────────│  (disk) │                     │
│   └─────────┘   /agent name    └─────────┘                     │
│        │                            │                           │
│        │ /destroy                   │ /delete                   │
│        ▼                            ▼                           │
│   [removed from pool]          [removed from disk]              │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                         TEMP SESSIONS                           │
│                       (not in sessions/)                        │
│                                                                 │
│   ┌─────────┐                  ┌──────────────┐                 │
│   │ Active  │ ────────────────▶│ last-session │ (auto-save)    │
│   │ (temp)  │   user-connected │    .json     │                 │
│   └─────────┘                  └──────────────┘                 │
│        │                                                        │
│        │ /save myname ──────────▶ PROMOTED TO SAVED             │
│        │                                                        │
│        │ /destroy or shutdown                                   │
│        ▼                                                        │
│   [gone, but last-session.json survives for resume]             │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase 6 Completion Status (2026-01-09)

**Completed:**
- ✅ `/send` bug fixed - uses async generator properly
- ✅ y/n prompts handled for `/agent foo` and `/whisper foo`
- ✅ `get_token_summary` → `get_token_usage` (4 locations)
- ✅ `/agent foo` restores saved sessions from disk
- ✅ Last-session updates on startup and agent switch
- ✅ "Choose from saved" properly updates resume target
- ✅ RPC live tests pass: detect, list, create, status, destroy, shutdown

**Live Testing Results:**
- ✅ Lobby displays correctly with Resume/Fresh/Saved options
- ✅ `/save myname` creates `~/.nexus3/sessions/myname.json`
- ✅ `/agent myname` restores saved session with prompt
- ✅ Switching agents updates `last-session.json`
- ✅ `--resume` correctly loads last session
- ✅ Whisper mode works with message routing
- ⚠️ WSL terminal closes on exit (investigating, predates today)

**Deferred to Next Phase (permissions/cwd tracking):**
- `/permissions` tracking per-agent
- `/save` metadata: system_prompt_path, working_directory, permission_level
- SQLite session markers
- Working directory persistence

---

## Development Note

Use subagents liberally for implementation tasks to manage context window:
- Writing new modules
- Writing tests
- Code modifications
- Research tasks

Main conversation focuses on planning, decisions, and coordination.
