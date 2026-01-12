# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NEXUS3 is a clean-slate rewrite of NEXUS2, an AI-powered CLI agent framework. The goal is a simpler, more maintainable, end-to-end tested agent with clear architecture.

**Status:** Phase 8 complete. 966 tests pass. Full permission system with presets, per-tool config, and inheritance.

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
| **5R - Security** | API key auth, server detection, path sandbox (infra), URL validator (infra), JSON injection fix, provider retry |
| **6 - Sessions** | Persistence, lobby mode, whisper mode, unified commands, agent naming, auto-restore, permission types |
| **7 - Integration** | Sandbox → file skills, URL validation → nexus skills, async I/O, skill timeout, concurrency limit, truncation fix |
| **8 - Permissions** | Permission presets (yolo/trusted/sandboxed/worker), per-tool config, deltas, ceiling inheritance, confirmation prompts |

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
{"method": "create_agent", "params": {"agent_id": "worker-1", "preset": "sandboxed"}}
{"method": "create_agent", "params": {"agent_id": "worker-1", "preset": "trusted", "disable_tools": ["write_file"]}}
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
| `nexus_create` | `agent_id`, `preset`?, `disable_tools`?, `port`? | Create a new agent with permissions |
| `nexus_destroy` | `agent_id`, `port`? | Remove an agent (server keeps running) |
| `nexus_send` | `agent_id`, `content`, `port`? | Send message to an agent |
| `nexus_status` | `agent_id`, `port`? | Get agent tokens + context |
| `nexus_cancel` | `agent_id`, `request_id`, `port`? | Cancel in-progress request |
| `nexus_shutdown` | `port`? | Shutdown the entire server |

*Note: `port` defaults to 8765. `preset` can be yolo/trusted/sandboxed/worker. Skills mirror `nexus-rpc` CLI commands.*

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
**Detailed remediation plan:** `/REMEDIATION_PLAN.md` (~600 lines)

### Critical Issues Status

| # | Issue | Status | Notes |
|---|-------|--------|-------|
| 1 | No authentication on HTTP server | ✅ FIXED | `rpc/auth.py`, middleware in `http.py` |
| 2 | Path traversal in file skills | ✅ FIXED | `validate_sandbox()` wired into read/write skills |
| 3 | SSRF in nexus_send | ✅ FIXED | `validate_url()` in all 6 nexus skills |
| 4 | Tool call/result pair truncation | ✅ FIXED | Groups preserved as atomic units |
| 5 | Blocking file I/O in async skills | ✅ FIXED | `asyncio.to_thread()` in file skills |
| 6 | No provider tests | ⚠️ PARTIAL | Provider has retry logic, tests incomplete |
| 7 | Raw log callback race | ❌ TODO | Need log multiplexer with contextvars |
| 8 | Requests not cancelled on destroy | ✅ FIXED | `cancel_all_requests()` in Dispatcher |
| 9 | Messages never GC'd | ❌ TODO | Need pruning after truncation |
| 10 | Missing encoding in file ops | ⚠️ PARTIAL | Skills have it, session logs need check |

---

## Remediation Plan: Phase 5R Status

### Phase 5R.1: Security Hardening - COMPLETE

| Task | Status | Files |
|------|--------|-------|
| API Key Auth | ✅ Done | `rpc/auth.py`, `rpc/http.py` middleware |
| Server Detection | ✅ Done | `rpc/detection.py` |
| Path Sandbox | ✅ Done | `read_file.py`, `write_file.py` use `validate_sandbox()` |
| SSRF Protection | ✅ Done | All 6 nexus skills use `validate_url()` |
| JSON Injection | ✅ Done | All errors use `json.dumps()` |

### Phase 5R.2: Data Integrity - MOSTLY COMPLETE

| Task | Status | Description |
|------|--------|-------------|
| Truncation Fix | ✅ Done | Groups tool_call + results as atomic units |
| Message GC | ❌ TODO | Prune messages after truncation |
| Cancel on Destroy | ✅ Done | `cancel_all_requests()` in Dispatcher |
| Encoding | ⚠️ Partial | Skills have it, session logs need audit |

### Phase 5R.3: Async/Performance - MOSTLY COMPLETE

| Task | Status | Description |
|------|--------|-------------|
| Async File I/O | ✅ Done | `asyncio.to_thread()` in file skills |
| Skill Timeout | ✅ Done | `asyncio.wait_for()` + `skill_timeout` config |
| Concurrency Limit | ✅ Done | Semaphore + `max_concurrent_tools` config |
| Log Multiplexer | ❌ TODO | Use contextvars for multi-agent logging |

### Phase 5R.4: Test Coverage - PARTIAL

Provider has retry logic and tests. Context truncation tests needed. CLI/REPL tests added in Phase 6.

### Phase 5R.5: Minor Fixes - MOSTLY COMPLETE

| Task | Status |
|------|--------|
| Export ReasoningDelta | ✅ Done |
| extra="forbid" Pydantic | ✅ Done |
| Consolidate InvalidParamsError | ✅ Done |
| Remove cli/output.py | ✅ Done |
| verbose/raw_log params | ❌ TODO |
| Provider retry | ✅ Done |
| max_iterations config | ✅ Done |

---

## Phase 6: Agent Management - COMPLETE (834 tests)

All Phase 6 infrastructure and integration complete:
- ✅ Session persistence (`session/persistence.py`, `session/session_manager.py`)
- ✅ Unified commands (`commands/protocol.py`, `commands/core.py`)
- ✅ Agent naming (temp `.1` vs saved `myproject`)
- ✅ REPL commands (`cli/repl_commands.py`, `cli/whisper.py`)
- ✅ Lobby mode (`cli/lobby.py`)
- ✅ Auto-restore saved sessions
- ✅ Permission types (`core/permissions.py`)
- ✅ CLI flags: `--resume`, `--fresh`, `--session`, `--template`
- ✅ Whisper mode for side conversations
- ✅ Auto-save to `last-session.json`

### Deferred Features

| Feature | Status | Notes |
|---------|--------|-------|
| Permission enforcement | Types exist | `core/permissions.py` has types, skills don't check |
| SQLite session markers | Schema exists | Markers not written on create/destroy |
| Working directory persistence | `/cwd` works | Not persisted in session save/restore |
| `/permissions` per-agent | Placeholder | Returns "trusted", doesn't track per-agent |
| `/save` full metadata | Partial | Missing system_prompt_path, working_directory |

### Known Issue: WSL Terminal

WSL bash closes after `nexus` exits. Predates recent changes, likely environmental. To investigate later.

---

## Phase 7: Implementation Complete (2026-01-09)

### Phase 7A: Security Integration - COMPLETE

**Goal:** Wire existing security infrastructure into skills.

#### 7A.1: Path Sandbox → File Skills

**Files:** `skill/builtin/read_file.py`, `skill/builtin/write_file.py`, `rpc/pool.py`

```python
# read_file.py / write_file.py changes:
class ReadFileSkill:
    def __init__(self, allowed_paths: list[Path] | None = None):
        self.allowed_paths = allowed_paths  # None = unrestricted (backwards compat)

    async def execute(self, path: str = "", **kwargs: Any) -> ToolResult:
        if self.allowed_paths is not None:
            from nexus3.core.paths import validate_sandbox
            p = validate_sandbox(path, self.allowed_paths)  # Raises PathSecurityError
        else:
            p = normalize_path(path)
        # ... rest unchanged

def read_file_factory(services: ServiceContainer) -> ReadFileSkill:
    allowed_paths = services.get("allowed_paths")  # From ServiceContainer
    return ReadFileSkill(allowed_paths=allowed_paths)

# rpc/pool.py: Register allowed_paths when creating agent
services.register("allowed_paths", [Path.cwd()])  # Or None for unrestricted
```

**Error handling:** Catch `PathSecurityError`, return `ToolResult(error=e.message)`

#### 7A.2: URL Validation → Nexus Skills

**Files:** All 6 nexus skills (`nexus_send.py`, `nexus_status.py`, `nexus_cancel.py`, `nexus_shutdown.py`, `nexus_create.py`, `nexus_destroy.py`)

```python
# Same pattern for all 6 skills:
from nexus3.core.url_validator import validate_url, UrlSecurityError

async def execute(self, ...):
    url = f"http://127.0.0.1:{actual_port}/..."

    try:
        validated_url = validate_url(url, allow_localhost=True)
    except UrlSecurityError as e:
        return ToolResult(error=f"URL validation failed: {e}")

    async with NexusClient(validated_url, api_key=api_key) as client:
        # ... rest unchanged
```

---

### Phase 7B: Async & Performance - COMPLETE

#### 7B.1: Async File I/O

**Files:** `skill/builtin/read_file.py`, `skill/builtin/write_file.py`

```python
import asyncio

# read_file.py:
content = await asyncio.to_thread(p.read_text, encoding="utf-8")

# write_file.py:
await asyncio.to_thread(p.parent.mkdir, parents=True, exist_ok=True)
await asyncio.to_thread(p.write_text, content, encoding="utf-8")
```

#### 7B.2: Skill Timeout

**Files:** `config/schema.py`, `session/session.py`, `rpc/pool.py`

```python
# config/schema.py:
skill_timeout: float = 30.0  # 0 = no timeout

# session/session.py _execute_single_tool():
try:
    if self.skill_timeout > 0:
        return await asyncio.wait_for(skill.execute(**args), timeout=self.skill_timeout)
    else:
        return await skill.execute(**args)
except asyncio.TimeoutError:
    return ToolResult(error=f"Skill '{tool_call.name}' timed out after {self.skill_timeout}s")
```

#### 7B.3: Parallel Concurrency Limit

**Files:** `config/schema.py`, `session/session.py`

```python
# config/schema.py:
max_concurrent_tools: int = 10

# session/session.py:
self._tool_semaphore = asyncio.Semaphore(max_concurrent_tools)

async def _execute_tools_parallel(self, tool_calls):
    async def execute_one(tc):
        async with self._tool_semaphore:
            return await self._execute_single_tool(tc)
    return await asyncio.gather(*[execute_one(tc) for tc in tool_calls], return_exceptions=True)
```

---

### Phase 7C: Data Integrity - COMPLETE

#### 7C.1: Truncation Fix (Tool Call/Result Pairs)

**Files:** `context/manager.py`

**Problem:** Truncation can separate assistant messages with `tool_calls` from their TOOL result messages, creating invalid sequences.

**Solution:** Group messages into atomic units before truncation.

```python
def _identify_message_groups(self) -> list[list[Message]]:
    """Group messages: standalone OR (assistant+tool_calls + matching results)."""
    groups = []
    i = 0
    while i < len(self._messages):
        msg = self._messages[i]
        if msg.role == Role.ASSISTANT and msg.tool_calls:
            # Collect assistant + all matching TOOL results
            group = [msg]
            expected_ids = {tc.id for tc in msg.tool_calls}
            j = i + 1
            while j < len(self._messages) and self._messages[j].role == Role.TOOL:
                if self._messages[j].tool_call_id in expected_ids:
                    group.append(self._messages[j])
                    j += 1
                else:
                    break
            groups.append(group)
            i = j
        else:
            groups.append([msg])
            i += 1
    return groups

def _truncate_oldest_first(self) -> list[Message]:
    groups = self._identify_message_groups()
    # Build from newest groups backwards, respecting budget
    # Remove oldest complete groups, not individual messages
```

**Also fix:** Use `count_messages([msg])` instead of `count(msg.content) + 4` for accurate token counting.

#### 7C.2: Cancel on Destroy

**Files:** `rpc/dispatcher.py`, `rpc/pool.py`

```python
# dispatcher.py:
async def cancel_all_requests(self) -> dict[str, bool]:
    """Cancel all in-progress requests."""
    cancelled = {}
    for request_id, token in list(self._active_requests.items()):
        token.cancel()
        cancelled[request_id] = True
    return cancelled

# pool.py destroy():
async def destroy(self, agent_id: str) -> bool:
    async with self._lock:
        agent = self._agents.pop(agent_id, None)
        if agent is None:
            return False
        await agent.dispatcher.cancel_all_requests()  # NEW
        agent.logger.close()
        return True
```

---

### Phase 7D: Deferred Items

| Item | Notes |
|------|-------|
| Message GC | Prune messages after truncation (max_messages config) |
| Log multiplexer | contextvars for multi-agent raw log callbacks |
| ~~Permission enforcement~~ | ✅ Done in Phase 8 |
| verbose/raw_log CLI | Wire to LogStream flags |
| More tools | bash, web_fetch, etc. |

---

### Implementation Summary

All Phase 7 items completed 2026-01-09:

| Task | Files Modified |
|------|----------------|
| 7A.1 Sandbox | `read_file.py`, `write_file.py`, `pool.py` |
| 7A.2 URL validation | 6 nexus skills |
| 7B.1 Async I/O | `read_file.py`, `write_file.py` |
| 7B.2 Skill timeout | `config/schema.py`, `session.py`, `pool.py` |
| 7B.3 Concurrency | `config/schema.py`, `session.py` |
| 7C.1 Truncation | `context/manager.py` |
| 7C.2 Cancel | `dispatcher.py`, `pool.py` |

**New config options:**
- `skill_timeout: float = 30.0` (seconds, 0 = no timeout)
- `max_concurrent_tools: int = 10`

---

## Phase 8: Permission System - COMPLETE (2026-01-09)

### Overview

Full permission system with presets, per-tool configuration, and inheritance.

### Core Types (`core/permissions.py`)

| Type | Purpose |
|------|---------|
| `ToolPermission` | Per-tool config: enabled, allowed_paths, timeout |
| `PermissionPreset` | Named config: level, paths, network, tool_permissions |
| `PermissionDelta` | Changes to apply: disable/enable tools, path overrides |
| `AgentPermissions` | Runtime state with `can_grant()` and `apply_delta()` |

### Built-in Presets

| Preset | Level | Description |
|--------|-------|-------------|
| `yolo` | YOLO | Full access, no confirmations |
| `trusted` | TRUSTED | Confirmations for destructive actions (default) |
| `sandboxed` | SANDBOXED | Limited to CWD, no network, nexus tools disabled |
| `worker` | SANDBOXED | Minimal: no write_file, no agent management |

### Key Features

1. **Per-tool configuration**: Enable/disable tools, per-tool paths, per-tool timeouts
2. **Permission presets**: Named configurations loaded from config or built-in
3. **Deltas**: Spawn agents with modifications (e.g., "trusted but disable write_file")
4. **Ceiling inheritance**: Subagents cannot exceed parent permissions
5. **Runtime modification**: `/permissions` command to change settings mid-session
6. **Confirmation prompts**: TRUSTED mode prompts for destructive actions in REPL

### Config Schema (`config/schema.py`)

```json
{
  "permissions": {
    "default_preset": "trusted",
    "presets": {
      "dev": {
        "extends": "trusted",
        "allowed_paths": ["/home/user/projects"],
        "tool_permissions": {"nexus_shutdown": {"enabled": false}}
      }
    },
    "destructive_tools": ["write_file", "nexus_destroy", "nexus_shutdown"]
  }
}
```

### Enforcement Points

1. **Session._execute_single_tool()**: Checks tool enabled, confirmation, per-tool timeout
2. **AgentPool.create()**: Resolves preset, applies delta, enforces ceiling
3. **nexus_create skill**: Validates ceiling before RPC call

### CLI Commands

```bash
/permissions              # Show current permissions
/permissions trusted      # Change preset (within ceiling)
/permissions --disable write_file   # Disable a tool
/permissions --enable write_file    # Re-enable (if ceiling allows)
/permissions --list-tools           # List tool status

/agent worker-1 --sandboxed         # Create with preset
```

### Files Modified

| Category | Files |
|----------|-------|
| Core Types | `core/permissions.py` |
| Config | `config/schema.py` |
| Enforcement | `session/session.py`, `rpc/pool.py` |
| CLI | `cli/repl.py`, `cli/repl_commands.py` |
| Skills | `skill/builtin/nexus_create.py` |
| Persistence | `session/persistence.py` |
| Client | `client.py`, `rpc/global_dispatcher.py` |

### Tests Added

- `test_permission_presets.py` - 74 tests for types and logic
- `test_permission_enforcement.py` - 18 tests for Session enforcement
- `test_permission_inheritance.py` - 32 tests for ceiling logic

---

## Development Note

Use subagents liberally for implementation tasks to manage context window.
