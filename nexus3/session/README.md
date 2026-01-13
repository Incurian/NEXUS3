# Session Module

Chat session coordination, structured logging, persistence, and management for NEXUS3.

## Purpose

This module provides four core capabilities:

1. **Session Coordination** - Ties together the LLM provider, context management, skill execution, and permission enforcement to handle conversation flow
2. **Session Logging** - Structured persistence of all session data via SQLite, with human-readable Markdown exports
3. **Session Persistence** - JSON serialization/deserialization of session state for save/load functionality
4. **Session Management** - Disk operations for named sessions, last-session tracking, and session lifecycle

## Key Types/Classes

| Class | File | Description |
|-------|------|-------------|
| `Session` | `session.py` | Coordinates provider, context, skills, permissions, compaction |
| `SessionLogger` | `logging.py` | Manages SQLite storage, Markdown, raw JSONL streams |
| `SessionStorage` | `storage.py` | SQLite DB operations (messages, events, markers) |
| `SessionManager` | `session_manager.py` | Save/load/list named sessions (~/.nexus3/sessions/) |
| `MarkdownWriter` | `markdown.py` | `context.md` / `verbose.md` generation (0o600 perms) |
| `RawWriter` | `markdown.py` | `raw.jsonl` for API traces |
| `LogStream` | `types.py` | Enum flags: CONTEXT (always), VERBOSE, RAW |
| `LogConfig` | `types.py` | Logging config (dir, streams, mode, type) |
| `SessionInfo` | `types.py` | Session ID/dir/parent/timestamp |
| `SavedSession` | `persistence.py` | JSON-serialized state (v1 schema) |
| `SessionSummary` | `persistence.py` | Listing summary (name, msgs, mod time) |
| `SessionMarkers` | `storage.py` | Cleanup tracking ('temp'/'saved'/'subagent', active/destroyed/orphaned) |
| `RawLogCallbackAdapter` | `logging.py` | Provider -> logger bridge |

### Callbacks (session.py)

| Callback | Signature | Purpose |
|----------|-----------|---------|
| `ConfirmationCallback` | `(ToolCall, Path\|None) -> Awaitable[ConfirmationResult]` | Destructive action confirm (DENY/ALLOW_ONCE/ALLOW_FILE/etc.) |
| `ToolCallCallback` | `(str, str) -> None` | Tool detected |
| `BatchStartCallback` | `(tuple[ToolCall,...]) -> None` | Batch start |
| `ToolActiveCallback` | `(str, str) -> None` | Tool executing |
| `BatchProgressCallback` | `(str, str, bool, str) -> None` | Tool complete |
| `BatchHaltCallback` / `BatchCompleteCallback` | `() -> None` | Batch status |

## Session Class (session.py)

Core coordinator with tool loop, permissions, compaction, MCP fallback.

### Key Features

- **Modes**: Single-turn, multi-turn, tools (seq/par), compaction
- **Tool Loop**: Streams content/reasoning immediately; executes tools post-final msg
  - Seq (default): Halt on error, "halted" results for rest
  - Par (`"_parallel":true`): `asyncio.gather()` w/ semaphore (default max=10)
- **Permissions**: Via `ServiceContainer`; per-tool enabled/timeout/path; TRUSTED confirms; SANDBOXED restricts
- **MCP Fallback**: `mcp_*` tools via `MCPServerRegistry` (TRUSTED/YOLO only)
- **Compaction**: Auto when >threshold; summarizes old msgs; reloads system prompt
- **Cancellation**: `CancellationToken`; `add_cancelled_tools()` queues errors
- **Safety**: Schema validation, timeouts, max iters (10), exception→ToolResult

```python
session = Session(
    provider, context, logger, registry, services,
    max_tool_iterations=10, skill_timeout=30.0, max_concurrent_tools=10,
    config=None, prompt_loader=None,  # For compaction
    callbacks..., on_confirm=...
)

async for chunk in session.send("msg", use_tools=True, cancel_token=token):
    yield chunk

session.compact(force=False)  # Returns CompactionResult | None
```

## Persistence (persistence.py)

`SavedSession` (schema v1) + ser/deser for Message/ToolCall.

New: `session_allowances` (dynamic TRUSTED grants).

`serialize_session(..., session_allowances=dict | None=None)`

## SessionManager (session_manager.py)

Disk ops (~/.nexus3/sessions/{id}.json, last-session.json).

Methods: list/save/load/delete/rename/clone/exists; last-session helpers.

Security: `validate_agent_id()`, 0o600 perms, no TOCTOU.

## Logging (logging.py, storage.py, markdown.py)

### Structure

```
.nexus3/logs/YYYY-MM-DD_HHMMSS_{repl/serve/agent}_xxxxxx/
├── session.db (SQLite v2: messages/events/metadata/markers)
├── context.md
├── verbose.md (opt)
└── raw.jsonl (opt)
└── subagent_xxxxxx/ ... (nested)
```

### SessionLogger API

```python
logger = SessionLogger(LogConfig(base_dir, streams=LogStream.ALL, mode="agent"))
logger.log_user/content → id
logger.log_tool_result(id, name, result)
logger.log_thinking/timing/token_count (VERBOSE)
logger.log_raw_* (RAW)
logger.get_context_messages() → list[Message]
logger.create_child_logger() → nested subagent logger
logger.mark_session_destroyed/saved()
logger.close()
```

Markers: Track type/status/parent for cleanup (Phase 6).

Exports: Matches `__init__.py` __all__.

## Multi-Agent Integration

Each agent: isolated Session/Context/Logger/Registry; shared Provider/PromptLoader.
`AgentPool` creates per-agent log dirs under `base_log_dir/agent_id`.

