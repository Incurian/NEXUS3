# nexus3.session Module

Comprehensive chat session management, structured logging, persistence, and tool coordination for NEXUS3 AI agents.

## Overview

The session module is the heart of NEXUS3's conversation management. It coordinates:

- **Session lifecycle**: Multi-turn conversations with streaming LLM responses
- **Tool execution**: Permission-gated skill execution with parallel/sequential modes
- **Event streaming**: Typed event system for real-time UI updates
- **Persistence**: SQLite storage with JSON serialization for save/load/resume
- **Logging**: Multi-stream logging (SQLite, Markdown, JSONL) with subagent nesting

## Module Structure

```
nexus3/session/
├── __init__.py          # Public exports
├── session.py           # Session class - main coordinator
├── session_manager.py   # Disk persistence (save/load/list sessions)
├── events.py            # Typed SessionEvent hierarchy
├── types.py             # LogConfig, LogStream, SessionInfo
├── logging.py           # SessionLogger - multi-stream logging
├── storage.py           # SessionStorage - SQLite operations
├── persistence.py       # SavedSession, message serialization
├── markdown.py          # MarkdownWriter, RawWriter
├── dispatcher.py        # ToolDispatcher - skill resolution
├── enforcer.py          # PermissionEnforcer - security checks
├── confirmation.py      # ConfirmationController - user prompts
├── path_semantics.py    # Tool path semantics for confirmation
└── http_logging.py      # HTTP debug logging to verbose.md
```

---

## Session Class

The `Session` class is the main coordinator between the CLI/REPL and the LLM provider. It manages multi-turn conversations, tool execution loops, and context compaction.

### Callback Type Aliases (from `session.py`)

```python
ConfirmationCallback = Callable[[ToolCall, Path | None, Path], Awaitable[ConfirmationResult]]
ToolCallCallback = Callable[[str, str], None]           # (tool_name, tool_id)
ToolCompleteCallback = Callable[[str, str, bool], None] # (tool_name, tool_id, success)
ReasoningCallback = Callable[[bool], None]              # True=start, False=end
BatchStartCallback = Callable[[tuple[ToolCall, ...]], None]
ToolActiveCallback = Callable[[str, str], None]         # (name, id)
BatchProgressCallback = Callable[[str, str, bool, str, str], None]  # (name, id, success, error, output)
BatchHaltCallback = Callable[[], None]
BatchCompleteCallback = Callable[[], None]
```

### Constructor

```python
Session(
    provider: AsyncProvider,                          # LLM provider for completions
    context: ContextManager | None = None,            # Conversation history (None = single-turn)
    logger: SessionLogger | None = None,              # Session logging
    registry: SkillRegistry | None = None,            # Tool registry
    on_tool_call: ToolCallCallback | None = None,     # Tool detection callback
    on_tool_complete: ToolCompleteCallback | None = None,
    on_reasoning: ReasoningCallback | None = None,    # Extended thinking notifications
    on_batch_start: BatchStartCallback | None = None,
    on_tool_active: ToolActiveCallback | None = None,
    on_batch_progress: BatchProgressCallback | None = None,
    on_batch_halt: BatchHaltCallback | None = None,
    on_batch_complete: BatchCompleteCallback | None = None,
    max_tool_iterations: int = 10,                    # Prevent infinite loops
    skill_timeout: float = 30.0,                      # Per-tool timeout
    max_concurrent_tools: int = 10,                   # Parallel execution limit
    services: ServiceContainer | None = None,         # Shared services (permissions, etc.)
    on_confirm: ConfirmationCallback | None = None,   # User confirmation for destructive actions
    config: Config | None = None,                     # Compaction settings
    context_loader: ContextLoader | None = None,      # System prompt reloading
    is_repl: bool = False,                            # REPL mode affects context loading
)
```

### Key Methods

#### `send()` - Callback-based streaming

```python
async def send(
    user_input: str,
    use_tools: bool = False,
    cancel_token: CancellationToken | None = None,
    user_meta: dict[str, Any] | None = None,
) -> AsyncIterator[str]:
    """Stream response text, invoking callbacks for tool events."""
```

This is the traditional callback-based API. Tool events are dispatched via callback functions. Internally wraps `_execute_tool_loop_events()` and converts events back to callbacks for backward compatibility.

#### `run_turn()` - Event-based streaming

```python
async def run_turn(
    user_input: str,
    use_tools: bool = False,
    cancel_token: CancellationToken | None = None,
    user_meta: dict[str, Any] | None = None,
) -> AsyncIterator[SessionEvent]:
    """Stream typed events for all session activity."""
```

The newer event-based API yields `SessionEvent` objects, enabling cleaner UI decoupling. Requires a context manager (raises `RuntimeError` if `self.context` is None).

#### `compact()` - Context compaction

```python
async def compact(force: bool = False) -> CompactionResult | None:
    """Summarize old messages to reclaim context space."""
```

Compaction uses a separate LLM call to summarize conversation history when token usage exceeds the configured threshold.

#### `add_cancelled_tools()` - Track cancelled tool calls

```python
def add_cancelled_tools(tools: list[tuple[str, str]]) -> None:
    """Store cancelled tool calls to report on next send()."""
```

Takes a list of `(tool_id, tool_name)` tuples. These are flushed as cancelled `ToolResult` messages into the context on the next `send()` or `run_turn()` call.

### Session Lifecycle

1. **Initialization**: Create Session with provider, context, and services
2. **User message**: Call `send()` or `run_turn()` with user input
3. **LLM streaming**: Provider streams content chunks
4. **Tool detection**: Tool calls parsed from stream trigger events
5. **Permission check**: PermissionEnforcer validates tool access
6. **Confirmation**: If needed, ConfirmationController prompts user
7. **Execution**: ToolDispatcher resolves and executes skill
8. **Loop**: Repeat until no tool calls or max iterations
9. **Compaction**: Auto-compact if threshold exceeded

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `halted_at_iteration_limit` | `bool` | Last send hit max iterations |
| `last_iteration_count` | `int` | Iterations in last send |
| `last_action_at` | `datetime | None` | Timestamp of last agent action |

---

## Session Events

The `events.py` module defines a typed event hierarchy for session lifecycle events. All events inherit from `SessionEvent`.

### Content Events

| Event | Attributes | Description |
|-------|------------|-------------|
| `ContentChunk` | `text: str` | LLM text content chunk |
| `ReasoningStarted` | - | Extended thinking block started |
| `ReasoningEnded` | - | Extended thinking block ended |

### Tool Events

| Event | Attributes | Description |
|-------|------------|-------------|
| `ToolDetected` | `name`, `tool_id` | Tool call parsed from stream |
| `ToolBatchStarted` | `tool_calls`, `parallel`, `timestamp` | Batch about to execute |
| `ToolStarted` | `name`, `tool_id`, `timestamp` | Individual tool starting |
| `ToolCompleted` | `name`, `tool_id`, `success`, `error`, `output`, `timestamp` | Tool finished |
| `ToolBatchHalted` | `timestamp` | Sequential batch stopped on error |
| `ToolBatchCompleted` | `timestamp` | All tools in batch finished |

### Session Events

| Event | Attributes | Description |
|-------|------------|-------------|
| `IterationCompleted` | `iteration`, `will_continue` | Tool loop iteration done |
| `SessionCompleted` | `halted_at_limit` | Turn finished |
| `SessionCancelled` | - | Turn cancelled via token |

### Event Flow Example

```
ContentChunk("Let me read that file...")
ToolDetected(name="read_file", tool_id="call_123")
ToolBatchStarted(tool_calls=[...], parallel=False)
ToolStarted(name="read_file", tool_id="call_123")
ToolCompleted(name="read_file", tool_id="call_123", success=True, output="...")
ToolBatchCompleted()
IterationCompleted(iteration=1, will_continue=True)
ContentChunk("The file contains...")
SessionCompleted(halted_at_limit=False)
```

---

## SessionManager

Handles disk persistence of sessions in `~/.nexus3/sessions/`.

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `list_sessions()` | `list[SessionSummary]` | List all saved sessions (sorted newest first) |
| `save_session(saved)` | `Path` | Save `SavedSession` to disk, returns file path |
| `load_session(name)` | `SavedSession` | Load session by name |
| `delete_session(name)` | `bool` | Delete a saved session (True if deleted, False if not found) |
| `session_exists(name)` | `bool` | Check if session exists |
| `rename_session(old, new)` | `Path` | Rename session file, returns new path |
| `clone_session(src, dest)` | `Path` | Duplicate a session, returns new path |
| `save_last_session(saved, name)` | `None` | Save for `--resume` (both data and name) |
| `load_last_session()` | `tuple[SavedSession, str] \| None` | Load last session and name |
| `get_last_session_name()` | `str \| None` | Get name without loading |
| `clear_last_session()` | `None` | Remove last session data |

### File Locations

```
~/.nexus3/
├── sessions/
│   └── {name}.json      # Named sessions (saved via /save)
├── last-session.json    # Auto-saved on exit (for --resume)
└── last-session-name    # Name of last session
```

### Exceptions

| Exception | Description |
|-----------|-------------|
| `SessionManagerError` | Base error for session manager operations |
| `SessionNotFoundError` | Raised when a session does not exist |

### Security

- Session names are validated via `validate_agent_id()` to prevent path traversal
- Files written with secure permissions (0o600) using `O_NOFOLLOW` to reject symlinks
- Directories created with 0o700 permissions
- Windows compatibility: explicit symlink check when `O_NOFOLLOW` unavailable

---

## Persistence

The `persistence.py` module handles serialization of session state.

### Constants

- `SESSION_SCHEMA_VERSION = 1`

### Exceptions

| Exception | Description |
|-----------|-------------|
| `SessionPersistenceError` | Raised when session serialization/deserialization fails (e.g., malformed JSON) |

### SavedSession

```python
@dataclass
class SavedSession:
    agent_id: str
    created_at: datetime
    modified_at: datetime
    messages: list[dict[str, Any]]
    system_prompt: str
    system_prompt_path: str | None
    working_directory: str
    permission_level: str
    token_usage: dict[str, int]
    provenance: str
    permission_preset: str | None
    disabled_tools: list[str]
    session_allowances: dict[str, Any]
    model_alias: str | None          # Model alias used (e.g., "haiku", "gpt")
    clipboard_agent_entries: list[dict[str, Any]]  # Agent-scope clipboard entries
    schema_version: int
```

Methods:

| Method | Returns | Description |
|--------|---------|-------------|
| `to_json()` | `str` | Serialize to JSON string |
| `to_dict()` | `dict[str, Any]` | Convert to dictionary for JSON serialization |
| `from_json(json_str)` | `SavedSession` | Class method: deserialize from JSON string |
| `from_dict(data)` | `SavedSession` | Class method: create from dictionary |

### SessionSummary

```python
@dataclass
class SessionSummary:
    name: str
    modified_at: datetime
    message_count: int
    agent_id: str
```

### Serialization Functions

```python
# Message serialization
serialize_message(msg: Message) -> dict[str, Any]
deserialize_message(data: dict) -> Message
serialize_messages(messages: list[Message]) -> list[dict]
deserialize_messages(data: list[dict]) -> list[Message]

# Tool call serialization
serialize_tool_call(tc: ToolCall) -> dict[str, Any]
deserialize_tool_call(data: dict) -> ToolCall

# Clipboard serialization
serialize_clipboard_entries(entries: dict[str, ClipboardEntry]) -> list[dict[str, Any]]
deserialize_clipboard_entries(data: list[dict[str, Any]]) -> dict[str, ClipboardEntry]

# Full session serialization
serialize_session(...) -> SavedSession
```

---

## SessionLogger

Multi-stream logging coordinator that writes to SQLite, Markdown, and JSONL.

### Log Streams

```python
class LogStream(Flag):
    NONE = 0
    CONTEXT = auto()   # Messages, tool calls (always on)
    VERBOSE = auto()   # Thinking, timing, metadata
    RAW = auto()       # Raw API JSON
    ALL = CONTEXT | VERBOSE | RAW
```

### Configuration

```python
@dataclass
class LogConfig:
    base_dir: Path = Path(".nexus3/logs")
    streams: LogStream = LogStream.ALL
    parent_session: str | None = None
    mode: str = "repl"  # "repl" or "serve"
    session_type: str = "temp"  # 'saved' | 'temp' | 'subagent'
```

### SessionInfo

```python
@dataclass
class SessionInfo:
    session_id: str      # Format: YYYY-MM-DD_HHMMSS_MODE_xxxxxx
    session_dir: Path
    parent_id: str | None
    created_at: datetime

    @classmethod
    def create(cls, base_dir: Path, parent_id: str | None = None, mode: str = "repl") -> SessionInfo:
        """Create new session with generated ID. Subagent dirs nest under parent."""
```

### Output Files

```
.nexus3/logs/{session_id}/
├── session.db      # SQLite database (always)
├── context.md      # Human-readable conversation log
├── verbose.md      # Timing, thinking, events (if VERBOSE)
└── raw.jsonl       # Raw API JSON (if RAW)
```

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `session_dir` | `Path` | Session directory path |
| `session_id` | `str` | Session ID string |

### Key Methods

| Method | Stream | Description |
|--------|--------|-------------|
| `log_system(content)` | CONTEXT | Log system prompt. Returns message ID. |
| `log_user(content, meta)` | CONTEXT | Log user message with optional metadata. Returns message ID. |
| `log_assistant(content, tool_calls, thinking, tokens)` | CONTEXT | Log assistant response (thinking logged to VERBOSE if provided). Returns message ID. |
| `log_tool_result(tool_call_id, name, result)` | CONTEXT | Log tool execution result. Returns message ID. |
| `log_session_event(event)` | SQLite always, VERBOSE conditionally | Log SessionEvent to DB and optionally verbose.md |
| `log_thinking(content, message_id)` | VERBOSE | Log thinking trace |
| `log_timing(operation, duration_ms, metadata)` | VERBOSE | Log timing info |
| `log_token_count(prompt, completion, total)` | VERBOSE | Log token usage |
| `log_http_debug(logger_name, message)` | VERBOSE | Log HTTP debug info |
| `log_raw_request(endpoint, payload)` | RAW | Log API request |
| `log_raw_response(status, body)` | RAW | Log API response |
| `log_raw_chunk(chunk)` | RAW | Log streaming chunk |

### Context Management

```python
logger.get_context_messages() -> list[Message]   # Get messages in context window
logger.get_token_count() -> int                  # Total tokens in current context
logger.mark_compacted(message_ids, summary_id)   # Mark messages as replaced by summary
```

### Subagent Support

```python
child_logger = logger.create_child_logger(name=None)
# Creates nested session in parent's directory
```

### Raw Log Callback

```python
raw_callback = logger.get_raw_log_callback()
# Returns RawLogCallbackAdapter implementing RawLogCallback protocol, or None if RAW stream disabled
```

### Session Markers

```python
logger.update_session_status(status)  # 'active' | 'destroyed' | 'orphaned'
logger.mark_session_destroyed()
logger.mark_session_saved()           # Sets session_type to 'saved'
```

### Lifecycle

```python
logger.close()  # Close logger and release resources (closes SQLite connection)
```

---

## SessionStorage

SQLite operations for session data. Schema version 3.

### Tables

| Table | Purpose |
|-------|---------|
| `schema_version` | Migration tracking |
| `messages` | Core message storage |
| `metadata` | Key-value session metadata |
| `session_markers` | Cleanup tracking (type, status, parent) |
| `events` | Verbose logging events |

### Message Fields

```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    meta TEXT,              -- JSON metadata (source attribution)
    name TEXT,              -- Tool name for tool results
    tool_call_id TEXT,
    tool_calls TEXT,        -- JSON array
    tokens INTEGER,
    timestamp REAL NOT NULL,
    in_context INTEGER,     -- 1 if in current context window
    summary_of TEXT         -- Comma-separated IDs of summarized messages
);
```

### Data Classes

```python
@dataclass
class MessageRow:
    id: int
    role: str
    content: str
    meta: dict[str, Any] | None
    name: str | None
    tool_call_id: str | None
    tool_calls: list[dict[str, Any]] | None
    tokens: int | None
    timestamp: float
    in_context: bool
    summary_of: list[int] | None

@dataclass
class EventRow:
    id: int
    message_id: int | None
    event_type: str
    data: dict[str, Any] | None
    timestamp: float

@dataclass
class SessionMarkers:
    session_type: str    # 'saved' | 'temp' | 'subagent'
    session_status: str  # 'active' | 'destroyed' | 'orphaned'
    parent_agent_id: str | None
    created_at: float
    updated_at: float
```

All three data classes have a `from_row(row: sqlite3.Row)` class method for construction from database rows.

### Public Methods

#### Message Operations

| Method | Returns | Description |
|--------|---------|-------------|
| `insert_message(role, content, *, meta, name, tool_call_id, tool_calls, tokens, timestamp)` | `int` | Insert message, returns ID |
| `get_messages(in_context_only=True)` | `list[MessageRow]` | Get messages, optionally filtered to context window |
| `get_message(message_id)` | `MessageRow \| None` | Get single message by ID |
| `update_context_status(message_ids, in_context)` | `None` | Batch update in_context flag |
| `mark_as_summary(summary_id, replaced_ids)` | `None` | Mark message as summary of others, marks replaced as out-of-context |
| `get_token_count()` | `int` | Total tokens in current context |

#### Metadata Operations

| Method | Returns | Description |
|--------|---------|-------------|
| `get_metadata(key)` | `str \| None` | Get a metadata value |
| `set_metadata(key, value)` | `None` | Set a metadata value (upsert) |
| `get_all_metadata()` | `dict[str, str]` | Get all metadata as dictionary |

#### Event Operations

| Method | Returns | Description |
|--------|---------|-------------|
| `insert_event(event_type, data, message_id, timestamp)` | `int` | Insert event, returns ID |
| `get_events(event_type, message_id)` | `list[EventRow]` | Get events with optional filters |

#### Session Marker Operations

| Method | Returns | Description |
|--------|---------|-------------|
| `init_session_markers(session_type, parent_agent_id)` | `None` | Initialize markers for new session |
| `get_session_markers()` | `SessionMarkers \| None` | Get current session markers |
| `update_session_metadata(session_type, session_status, parent_agent_id)` | `None` | Update marker fields (only provided fields) |
| `mark_session_destroyed()` | `None` | Mark session as destroyed |
| `get_orphaned_sessions(older_than_days=7)` | `list[SessionMarkers]` | Get orphaned sessions older than N days |

#### Lifecycle

| Method | Description |
|--------|-------------|
| `close()` | Close database connection |

### Constants

- `SCHEMA_VERSION = 3`
- `MAX_JSON_FIELD_SIZE = 10 * 1024 * 1024` (10MB)

### Schema Migrations

The storage automatically handles migrations between schema versions:
- **1 -> 2**: Added `session_markers` table for cleanup tracking
- **2 -> 3**: Added `meta` column to messages table for source attribution

---

## Tool Execution Components

### ToolDispatcher

Resolves tool calls to skill implementations.

```python
class ToolDispatcher:
    def __init__(self, registry: SkillRegistry | None = None, services: ServiceContainer | None = None):
        ...

    def find_skill(tool_call: ToolCall) -> tuple[Skill | None, str | None]:
        """Returns (skill, mcp_server_name) or (None, None)."""
```

Resolution order:
1. Built-in skills via SkillRegistry
2. MCP tools (for `mcp_*` prefixed names) via `MCPServerRegistry.find_skill()`

### PermissionEnforcer

Enforces security policies for tool execution.

```python
class PermissionEnforcer:
    def check_all(tool_call, permissions) -> ToolResult | None:
        """Run all permission checks. Returns error or None."""

    def requires_confirmation(tool_call, permissions) -> bool:
        """Check if user confirmation needed (checks ALL write paths)."""

    def get_confirmation_context(tool_call) -> tuple[Path | None, list[Path]]:
        """Get display path and write paths for confirmation UI."""

    def get_effective_timeout(tool_name, permissions, default) -> float:
        """Get per-tool timeout override."""

    def extract_target_paths(tool_call) -> list[Path]:
        """Extract ALL target paths from tool call (source + destination)."""

    def extract_target_path(tool_call) -> Path | None:
        """Extract first target path (legacy, prefer extract_target_paths)."""

    def extract_exec_cwd(tool_call) -> Path | None:
        """Extract execution cwd if applicable."""
```

#### Module Constants

```python
EXEC_TOOLS = frozenset({"bash", "bash_safe", "shell_UNSAFE", "run_python", "git"})
AGENT_TARGET_TOOLS = frozenset({"nexus_send", "nexus_status", "nexus_cancel", "nexus_destroy"})
PATH_TOOLS = frozenset({
    "read_file", "write_file", "edit_file", "append_file", "tail",
    "file_info", "list_directory", "mkdir", "copy_file", "rename",
    "regex_replace", "glob", "grep",
})
```

Permission checks (in order):
1. Tool enabled (not disabled by policy)
2. Action allowed (by permission level; explicit `enabled=True` in tool_permissions bypasses policy-level restrictions)
3. **Target allowed** (for nexus_* tools with `allowed_targets` restriction)
4. Path allowed (sandbox, per-tool, blocked paths) -- checks ALL paths in tool call

Uses `PathDecisionEngine` for consistent path validation across all checks.

### Target Validation

For inter-agent communication tools (`nexus_send`, `nexus_status`, `nexus_cancel`, `nexus_destroy`), the enforcer validates that the target `agent_id` is permitted by the tool's `allowed_targets` setting:

```python
# Tools checked for target restrictions
AGENT_TARGET_TOOLS = frozenset({
    "nexus_send", "nexus_status", "nexus_cancel", "nexus_destroy"
})
```

The `_check_target_allowed()` method resolves relationship-based restrictions:
- `"parent"`: Compares against `permissions.parent_agent_id`
- `"children"`: Checks `services.get_child_agent_ids()`
- `"family"`: Allows either parent or children
- `list[str]`: Explicit allowlist comparison

This enables sandboxed agents to report results back to their parent while being isolated from all other agents.

### ConfirmationController

Handles user confirmation flow for destructive actions. Returns `DENY` if no callback is provided.

```python
class ConfirmationController:
    async def request(tool_call, target_path, agent_cwd, callback) -> ConfirmationResult:
        """Request user confirmation. Returns DENY if callback is None."""

    @staticmethod
    def apply_result(permissions, result, tool_call, target_path, exec_cwd):
        """Apply confirmation result to session allowances."""

    @staticmethod
    def apply_mcp_result(permissions, result, tool_name, server_name):
        """Apply MCP-specific allowances."""

    @staticmethod
    def apply_gitlab_result(permissions, result, skill_name, instance_host):
        """Apply GitLab-specific allowances."""
```

Confirmation results:
- `DENY` - Cancel action
- `ALLOW_ONCE` - Allow this once, no persistent allowance
- `ALLOW_FILE` - Allow writes to this file (for MCP: allow specific tool; for GitLab: allow skill@instance)
- `ALLOW_WRITE_DIRECTORY` - Allow writes to parent directory
- `ALLOW_EXEC_CWD` - Allow exec tool in this directory
- `ALLOW_EXEC_GLOBAL` - Allow exec tool everywhere (for MCP: allow all tools from server)

### Path Semantics

The `path_semantics.py` module defines read vs write path semantics for each tool.

```python
@dataclass(frozen=True)
class ToolPathSemantics:
    read_keys: tuple[str, ...] = ()    # Arguments that are read paths
    write_keys: tuple[str, ...] = ()   # Arguments that are write paths
    display_key: str | None = None     # Path to show in confirmation UI
```

The `TOOL_PATH_SEMANTICS` dict maps tool names to their semantics. Tools not in the registry get a default of `read_keys=("path",), write_keys=("path",), display_key="path"`.

Functions:
```python
get_semantics(tool_name: str) -> ToolPathSemantics
extract_write_paths(tool_name: str, args: dict) -> list[Path]
extract_display_path(tool_name: str, args: dict) -> Path | None
```

Registered semantics:

| Tool | Read Keys | Write Keys | Display Key |
|------|-----------|------------|-------------|
| `write_file` | - | `path` | `path` |
| `mkdir` | - | `path` | `path` |
| `edit_file` | `path` | `path` | `path` |
| `append_file` | `path` | `path` | `path` |
| `regex_replace` | `path` | `path` | `path` |
| `copy_file` | `source` | `destination` | `destination` |
| `rename` | `source` | `destination` | `destination` |
| `read_file` | `path` | - | - |
| `tail` | `path` | - | - |
| `file_info` | `path` | - | - |
| `list_directory` | `path` | - | - |
| `glob` | `path` | - | - |
| `grep` | `path` | - | - |

---

## HTTP Logging

The `http_logging.py` module routes httpx/httpcore debug output to verbose.md.

### Functions

```python
set_current_logger(logger: SessionLogger) -> None
clear_current_logger() -> None
configure_http_logging() -> None    # Call once at startup
unconfigure_http_logging() -> None  # Cleanup on shutdown
```

### Usage

```python
from nexus3.session.http_logging import set_current_logger, clear_current_logger

set_current_logger(session_logger)
try:
    # ... make HTTP calls ...
finally:
    clear_current_logger()
```

The `VerboseMdHandler` class is automatically attached to httpx/httpcore loggers when `configure_http_logging()` is called.

---

## Markdown Writers

### MarkdownWriter

Human-readable conversation logs in `context.md` and `verbose.md`.

```python
MarkdownWriter(session_dir: Path, verbose_enabled: bool = False)
```

Methods:
- `write_system(content)` - System prompt
- `write_user(content, meta)` - User message with source attribution
- `write_assistant(content, tool_calls)` - Assistant response
- `write_tool_result(name, result, error)` - Tool execution result
- `write_separator()` - Horizontal rule
- `write_thinking(content, timestamp)` - Thinking trace (verbose)
- `write_timing(operation, duration_ms, metadata)` - Timing info (verbose)
- `write_token_count(prompt, completion, total)` - Token usage (verbose)
- `write_event(event_type, data)` - Generic event (verbose)
- `write_http_debug(logger_name, message)` - HTTP debug entry (verbose)

### RawWriter

JSONL logging of raw API traffic in `raw.jsonl`.

```python
RawWriter(session_dir: Path)
```

Methods:
- `write_request(endpoint, payload, timestamp)` - API request
- `write_response(status, body, timestamp)` - API response
- `write_stream_chunk(chunk, timestamp)` - SSE chunk

---

## Tool Execution Flow

1. **Stream parsing**: LLM response streamed, tool calls detected
2. **Batch formation**: All tool calls in response form a batch
3. **Permission check**: Each tool checked against permissions
   - Tool enabled?
   - Action allowed by level?
   - Target allowed (for nexus_* tools)?
   - Path allowed (sandbox, blocked)?
4. **Confirmation**: If TRUSTED level, prompt for destructive actions
5. **Skill resolution**: ToolDispatcher finds implementing skill
6. **MCP/GitLab permissions**: Additional permission checks for MCP and GitLab tools
7. **Malformed JSON check**: Reject truncated/malformed tool call arguments
8. **Argument validation**: Validate against skill parameter schema
9. **Execution**: Run skill with timeout
   - Parallel: All tools run concurrently (semaphore limited)
   - Sequential: One at a time, halt on error or cancellation
10. **Result handling**: Add tool results to context (including error sanitization)
11. **Loop**: Continue until no tool calls or max iterations

### Parallel vs Sequential

- **Default**: Sequential (safe for dependent operations)
- **Parallel**: If any tool call has `"_parallel": true` in arguments
- Parallel execution limited by `max_concurrent_tools` semaphore (default 10)

---

## Context Compaction

Session supports automatic context compaction when token usage exceeds threshold.

### Configuration

```python
@dataclass
class CompactionConfig:
    enabled: bool = True
    model: str | None = None           # Separate model for summarization
    summary_budget_ratio: float = 0.25 # Max tokens for summary
    recent_preserve_ratio: float = 0.25 # Recent messages to keep
    trigger_threshold: float = 0.9     # Trigger at 90% capacity
```

### Process

1. **Trigger**: When `used_tokens > threshold * available_tokens`
2. **Selection**: Split messages into "to summarize" and "to preserve"
3. **Summarization**: LLM generates summary of old messages
4. **System prompt reload**: Fresh NEXUS.md read (picks up changes)
5. **Apply**: Replace old messages with summary message

### Compaction Provider

If `compaction.model` is configured, a separate provider is used for summarization (e.g., claude-haiku for speed/cost).

---

## Security Features

### Path Security
- **PathDecisionEngine**: Consistent path validation with blocked_paths enforcement
- **Symlink rejection**: `O_NOFOLLOW` flag prevents symlink attacks
- **Path traversal prevention**: Session names validated to reject `../` patterns

### File Permissions
- **Session directories**: 0o700 (owner read/write/execute)
- **Session files**: 0o600 (owner read/write only)
- **Atomic creation**: Files created with permissions set at open time

### Tool Execution
- **Permission levels**: YOLO, TRUSTED, SANDBOXED with escalating restrictions
- **Per-tool configuration**: Enable/disable, allowed paths, timeouts
- **Confirmation flow**: TRUSTED mode prompts for destructive actions
- **Timeout enforcement**: Prevents runaway tool execution
- **Error sanitization**: Internal paths redacted from agent-visible errors

### JSON Safety
- **Size limits**: 10MB max for JSON fields (prevents memory exhaustion)
- **Malformed handling**: Skip and log malformed JSON, don't crash

---

## Dependencies

| Module | Dependency |
|--------|------------|
| `session.py` | `core.types`, `core.errors`, `core.interfaces`, `core.permissions`, `core.validation`, `context.compaction`, `session.events`, `session.dispatcher`, `session.enforcer`, `session.confirmation`, `session.http_logging` |
| `logging.py` | `core.types`, `core.secure_io`, `session.storage`, `session.markdown`, `session.events`, `session.types` |
| `storage.py` | `core.secure_io` (sqlite3 stdlib) |
| `persistence.py` | `core.types`, `core.errors`, `clipboard.types` |
| `session_manager.py` | `core.constants`, `core.errors`, `core.secure_io`, `core.validation`, `session.persistence` |
| `enforcer.py` | `core.path_decision`, `core.presets`, `core.types`, `session.path_semantics` |
| `confirmation.py` | `core.permissions` |
| `dispatcher.py` | `skill.registry`, `mcp.registry` (TYPE_CHECKING only) |
| `http_logging.py` | `session.logging` (TYPE_CHECKING only) |
| `markdown.py` | `core.secure_io` |
| `path_semantics.py` | (no external dependencies) |
| `events.py` | `core.types` (TYPE_CHECKING only) |
| `types.py` | (no external dependencies) |

---

## Related Modules

- **nexus3/context/**: ContextManager for conversation history
- **nexus3/skill/**: SkillRegistry and skill implementations
- **nexus3/core/**: Types, errors, permissions, path validation
- **nexus3/provider/**: AsyncProvider implementations
- **nexus3/mcp/**: MCP server integration
- **nexus3/clipboard/**: Clipboard system for agent-scope persistence

---

Updated: 2026-02-10
