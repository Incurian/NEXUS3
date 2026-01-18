# nexus3.session Module

Comprehensive chat session management, structured logging, persistence, and tool coordination for NEXUS3 AI agents.

## Purpose

Powers conversation lifecycles:
- **Session** coordination: LLM streaming, tool loops (seq/par, configurable max iterations), permissions, compaction, cancellation.
- **Logging**: SQLite + Markdown/JSONL (`context.md`, `verbose.md`, `raw.jsonl`), subagent nesting.
- **Storage**: SQLite v2 (messages/events/metadata/markers).
- **Persistence**: JSON save/load/rename/clone in `~/.nexus3/sessions/`.

Supports multi-turn, tools, perms (YOLO/TRUSTED/SANDBOXED), MCP, auto-compaction.

## Key Exports

From `__init__.py`:

```
Session, ConfirmationCallback, ConfirmationController
ToolDispatcher, PermissionEnforcer, SessionLogger
SessionStorage, SessionMarkers, LogConfig, LogStream, SessionInfo
RawLogCallbackAdapter
SavedSession, SessionSummary, serialize_session, deserialize_messages
SessionManager, SessionManagerError, SessionNotFoundError

# Session Events (typed event stream)
SessionEvent, ContentChunk, ReasoningStarted, ReasoningEnded
ToolDetected, ToolBatchStarted, ToolStarted, ToolCompleted
ToolBatchHalted, ToolBatchCompleted, IterationCompleted
SessionCompleted, SessionCancelled
```

**Core Classes**:
- `Session`: LLM + tools (perms/confirm/dispatch/exec). Methods: `send()`, `run_turn()`.
- `SessionLogger`: Logs to SQLite/MD/JSONL.
- `SessionManager`: Disk ops (`save_session`, `load_session`).
- `PermissionEnforcer`: Tool/path checks, multi-path (Fix 1.2).
- `ConfirmationController`: User confirm + allowances.
- `ToolDispatcher`: Skill/MCP resolution.

**Session Events** (typed event stream for UI decoupling):
- `ContentChunk`: Text content from LLM.
- `ReasoningStarted/Ended`: Extended thinking blocks.
- `ToolDetected`: Tool call parsed from stream.
- `ToolBatchStarted/Completed`: Batch lifecycle.
- `ToolStarted/Completed`: Individual tool execution.
- `IterationCompleted`: Tool loop iteration finished.
- `SessionCompleted/Cancelled`: Terminal events.

## Usage Examples

### 1. Basic Session + Logging
```python
from nexus3.session import Session, LogConfig
from nexus3.session.logging import SessionLogger

config = LogConfig(streams=LogStream.ALL)
logger = SessionLogger(config)
session = Session(provider, context, logger=logger, registry=registry)

async for chunk in session.send("Hello!", use_tools=True):
    print(chunk, end="")
```

### 2. Save/Load Session
```python
from nexus3.session import SessionManager
from nexus3.session.persistence import serialize_session

mgr = SessionManager()
saved = serialize_session(agent_id="proj", messages=context.messages, ...)
mgr.save_session(saved)
loaded = mgr.load_session("proj")
```

### 3. Permissions (TRUSTED)
```python
async def on_confirm(tc, path, cwd):
    # UI prompt
    return ConfirmationResult.ALLOW_FILE  # or ALLOW_EXEC_GLOBAL, etc.

session = Session(..., on_confirm=on_confirm)
```

### 4. Raw Logging
```python
raw_cb = logger.get_raw_log_callback()
provider = create_provider(..., raw_callback=raw_cb)
```

### 5. Subagents
```python
child_logger = logger.create_child_logger()
child_session = Session(..., logger=child_logger)
```

## Architecture Highlights
- **Tool Flow**: Stream → check perms/confirm → validate → exec (sem=10, to=30s) → results.
- **Parallel**: `"_parallel": true` in args.
- **Logging Dirs**: `.nexus3/logs/{id}/` (0o600 secure).
- **Compaction**: Auto on threshold; LLM summary preserves recent.

**Security**: O_NOFOLLOW writes, PathDecisionEngine (Arch A2), timeouts, sanitized errors.

Updated: 2026-01-17