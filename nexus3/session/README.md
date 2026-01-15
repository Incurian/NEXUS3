# nexus3.session Module

Comprehensive chat session management, structured logging, persistence, and coordination for NEXUS3 AI agents.

## Purpose

The `nexus3.session` module orchestrates the core conversation lifecycle for NEXUS3 agents:

1. **Session Coordination** (`Session`): Manages LLM provider interactions, tool execution loops (sequential/parallel), permission checks, context compaction, and cancellation.
2. **Structured Logging** (`SessionLogger`): SQLite-backed storage with Markdown exports (`context.md`, `verbose.md`) and raw JSONL traces. Supports subagents.
3. **Persistence** (`SavedSession`, `SessionManager`): JSON serialization for save/load/rename/clone sessions in `~/.nexus3/sessions/`.
4. **Storage** (`SessionStorage`): SQLite schema v2 for messages/events/metadata/markers (cleanup tracking).

Enables multi-turn conversations, tool use, permissions (YOLO/TRUSTED/SANDBOXED), MCP tools, and auto-compaction.

## Dependencies

### Python Standard Library
- `asyncio`, `dataclasses`, `datetime`, `enum`, `json`, `logging`, `os`, `pathlib`, `secrets`, `sqlite3`, `stat`, `time`, `typing`

### Internal NEXUS3 Modules
- `nexus3.core.*` (types, permissions, validation, interfaces)
- `nexus3.context.*` (compaction, manager, loader)
- `nexus3.config.schema` (Config, models)
- `nexus3.skill.*` (registry, services)
- `nexus3.provider.*` (AsyncProvider)
- `nexus3.mcp.*` (permissions, registry; optional)

No external packages required.

## Key Classes & Modules

| Module/File | Key Exports | Role |
|-------------|-------------|------|
| `__init__.py` | All public API | Package exports |
| `session.py` | `Session`, `ConfirmationCallback` | Core coordinator + tool loop |
| `logging.py` | `SessionLogger`, `RawLogCallbackAdapter` | Multi-stream logging hub |
| `storage.py` | `SessionStorage`, `SessionMarkers` | SQLite ops (v2 schema) |
| `session_manager.py` | `SessionManager`, `SessionNotFoundError` | Disk persistence |
| `persistence.py` | `SavedSession`, `serialize_session(...)` | JSON ser/de |
| `markdown.py` | `MarkdownWriter`, `RawWriter` | Human/raw log writers |
| `types.py` | `LogConfig`, `LogStream`, `SessionInfo` | Config & types |

**Exported API** (from `__init__.py`): Matches table above.

## Architecture Overview

### Logging Structure
```
.nexus3/logs/YYYY-MM-DD_HHMMSS_{repl/serve/agent}_xxxxxx/  # SessionInfo.session_dir
├── session.db                          # SQLite: messages/events/metadata/session_markers
├── context.md                          # Core chat (always)
├── verbose.md                          # Thinking/timing/tokens (--verbose)
├── raw.jsonl                           # API traces (--raw-log)
└── subagent_xxxxxx/                    # Nested child loggers
    └── ...
```
- **Permissions**: Files created 0o600 (owner r/w only).
- **Markers**: Track `session_type` ('temp'/'saved'/'subagent'), `status` ('active'/'destroyed'/'orphaned'), parent for cleanup.

### Session Flow (`Session.send()`)
```
user_input → add_user_message()
↓ (if tools)
while tool_calls and < max_iters (10):
  compact? → summarize old msgs
  stream(provider) → yield ContentDelta/ReasoningDelta
  if tool_calls:
    permissions → confirm? → validate args → exec seq/par (semaphore=10)
    add_tool_results()
final content → add_assistant_message() → compact?
```

- **Tool Execution**: Seq (halt on error), Par (`_parallel: true`). Timeouts (30s default).
- **Permissions**: Per-tool enabled/timeout/path; TRUSTED confirms destructive ops; SANDBOXED restricts.
- **Compaction**: Auto > threshold; LLM summary; preserves recent msgs/system prompt reload.
- **Callbacks**: Batch-aware progress, reasoning start/end, tool events.

### Persistence
- **SavedSession** (JSON schema v1): agent_id, messages, prompt, perms, allowances, token_usage.
- **SessionManager**: `~/.nexus3/sessions/{agent_id}.json` + last-session helpers.
- Security: `validate_agent_id()`, atomic 0o600 writes, TOCTOU-safe.

## Usage Examples

### 1. Basic Session
```python
from nexus3.session import Session, LogConfig, LogStream
from nexus3.session.logging import SessionLogger

config = LogConfig(streams=LogStream.ALL)
logger = SessionLogger(config)
session = Session(provider, context, logger=logger, registry=registry, services=services)

async for chunk in session.send("Hello!", use_tools=True):
    print(chunk, end="", flush=True)
```

### 2. Save/Load Session
```python
from nexus3.session import SessionManager
from nexus3.session.persistence import serialize_session

manager = SessionManager()
saved = serialize_session(agent_id="my-agent", messages=context.messages, 
                          system_prompt=prompt, working_directory=cwd,
                          permission_level="trusted", ...)
path = manager.save_session(saved)
loaded = manager.load_session("my-agent")
```

### 3. Subagent Logging
```python
child_logger = logger.create_child_logger()  # Nests under parent session_dir
child_session = Session(..., logger=child_logger)
```

### 4. Raw Logging (Provider Integration)
```python
raw_callback = logger.get_raw_log_callback()  # If LogStream.RAW enabled
provider = create_provider(config, model="gpt-4o", raw_callback=raw_callback)
```

### 5. Custom Confirmation (TRUSTED Mode)
```python
async def confirm(tool_call: ToolCall, path: Path | None, cwd: Path) -> ConfirmationResult:
    # UI prompt: \"Allow {tool_call.name} on {path}?\"
    return ConfirmationResult.ALLOW_FILE  # or DENY/ALLOW_ONCE/etc.

session = Session(..., on_confirm=confirm)
```

## Multi-Agent Support
- **AgentPool**: Per-agent `Session`/`Context`/`Logger`; shared `Provider`/`PromptLoader`.
- **Subagents**: Nested dirs, parent_id tracking, child destruction skip-confirm.
- **Cleanup**: Markers enable orphaned temp/subagent pruning (Phase 6).

## Security Features
- Tool arg JSON schema validation.
- Permission levels w/ confirmations/allowances.
- Secure file perms (0o600), path traversal validation.
- Timeouts, max iters, exception→ToolResult.

Exports match `__init__.py` __all__. See source for full API docs.