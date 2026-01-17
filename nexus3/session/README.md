# nexus3.session Module

Comprehensive chat session management, structured logging, persistence, and tool coordination for NEXUS3 AI agents.

## Purpose

The `nexus3.session` module powers conversation lifecycles:
1. **Session** (`session.py`): LLM coordination, streaming tool loops (sequential/parallel), permissions, compaction, cancellation.
2. **Logging** (`logging.py`): SQLite + Markdown/JSONL exports (`context.md`, `verbose.md`, `raw.jsonl`), subagent nesting.
3. **Storage** (`storage.py`): SQLite v2 schema for messages/events/metadata/markers.
4. **Persistence** (`persistence.py`, `session_manager.py`): JSON save/load/rename/clone in `~/.nexus3/sessions/`.

Supports multi-turn, tools, permissions (YOLO/TRUSTED/SANDBOXED), MCP, auto-compaction.

## Dependencies

**Stdlib**: `asyncio`, `dataclasses`, `datetime`, `json`, `logging`, `os`, `pathlib`, `secrets`, `sqlite3`, `typing`.

**NEXUS3**:
- `nexus3.core.*`: types, permissions, validation.
- `nexus3.context.*`: compaction/manager.
- `nexus3.config.schema`: Config.
- `nexus3.skill.*`: registry/services (tools).
- `nexus3.provider.*`: AsyncProvider.
- `nexus3.mcp.*`: optional.

No external deps.

## Key Classes/Modules

| File | Key Exports | Role |
|------|-------------|------|
| `__init__.py` | All public API | Exports |
| `session.py` | `Session`, `ConfirmationCallback` | Core + tool loop |
| `logging.py` | `SessionLogger`, `RawLogCallbackAdapter` | Logging hub |
| `storage.py` | `SessionStorage`, `SessionMarkers` | SQLite ops |
| `session_manager.py` | `SessionManager`, `SessionNotFoundError` | Disk persistence |
| `persistence.py` | `SavedSession`, `serialize_session()` | JSON ser/de |
| `markdown.py` | `MarkdownWriter`, `RawWriter` | Log writers |
| `confirmation.py` | `ConfirmationController` | User confirmations |
| `dispatcher.py` | `ToolDispatcher` | Skill resolution |
| `enforcer.py` | `PermissionEnforcer` | Permissions |
| `types.py` | `LogConfig`, `LogStream`, `SessionInfo` | Types |

## Architecture

### Logging
```
.nexus3/logs/YYYY-MM-DD_HHMMSS_{repl/serve/agent}_xxxxxx/
├── session.db (SQLite v2)
├── context.md
├── verbose.md (--verbose)
├── raw.jsonl (--raw-log)
└── subagent_xxxxxx/...
```
- Secure 0o600 perms.
- Markers track type/status/parent for cleanup.

### Session Flow (`Session.send()`)
```
user → add_user()
↓ tools?
while tool_calls < max_iters(10):
  compact? → LLM summarize
  stream(provider) → ContentDelta/ToolCallStarted
  tools? → check perms/confirm → validate → exec seq/par (sem=10, to=30s)
  add_tool_results()
final → add_assistant() → compact?
```
- **Parallel**: `_parallel: true`.
- **Perms**: Enabled/timeout/path; confirm destructive; allowances.
- **Compaction**: Auto-threshold; preserves recent/system reload.

### Persistence
- `SavedSession` (JSON v1): msgs/prompt/perms/allowances.
- `SessionManager`: `~/.nexus3/sessions/{agent_id}.json`, last-session.

## Usage Examples

### 1. Basic Session
```python
from nexus3.session import Session, LogConfig, LogStream
from nexus3.session.logging import SessionLogger

config = LogConfig(streams=LogStream.ALL)
logger = SessionLogger(config)
session = Session(provider, context, logger=logger, registry=registry)

async for chunk in session.send("Hello!", use_tools=True):
    print(chunk, end="")
```

### 2. Save/Load
```python
from nexus3.session import SessionManager
from nexus3.session.persistence import serialize_session

mgr = SessionManager()
saved = serialize_session(agent_id="my-agent", messages=..., ...)
mgr.save_session(saved)
loaded = mgr.load_session("my-agent")
```

### 3. Subagents
```python
child_logger = logger.create_child_logger()
child_session = Session(..., logger=child_logger)
```

### 4. Permissions (TRUSTED)
```python
async def confirm(tc, path, cwd):
    # UI: "Allow {tc.name} on {path}?"
    return ConfirmationResult.ALLOW_FILE

session = Session(..., on_confirm=confirm)
```

### 5. Raw Logging
```python
raw_cb = logger.get_raw_log_callback()
provider = create_provider(..., raw_callback=raw_cb)
```

## Security
- JSON schema validation.
- PathDecisionEngine (Arch A2).
- Secure 0o600 writes (O_NOFOLLOW).
- Timeouts, max iters, error→ToolResult.

Updated: 2026-01-17
