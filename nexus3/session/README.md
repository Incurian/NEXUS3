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
| `Session` | `session.py` | Coordinates CLI, provider, context, skill execution, and permissions |
| `SessionLogger` | `logging.py` | Central logging interface, manages all log streams |
| `SessionStorage` | `storage.py` | SQLite operations for message and event persistence |
| `SessionManager` | `session_manager.py` | Disk operations for saving/loading/listing sessions |
| `MarkdownWriter` | `markdown.py` | Generates human-readable `context.md` and `verbose.md` |
| `RawWriter` | `markdown.py` | Writes raw API JSON to `raw.jsonl` |
| `LogStream` | `types.py` | Flag enum for log stream selection (CONTEXT, VERBOSE, RAW) |
| `LogConfig` | `types.py` | Configuration dataclass for logging behavior |
| `SessionInfo` | `types.py` | Session metadata (ID, directory, parent, timestamp) |
| `SavedSession` | `persistence.py` | Serialized session state for disk storage |
| `SessionSummary` | `persistence.py` | Brief summary of a saved session for listing |
| `SessionMarkers` | `storage.py` | Cleanup tracking metadata (type, status, parent) |
| `MessageRow` | `storage.py` | Typed representation of a database message row |
| `EventRow` | `storage.py` | Typed representation of a database event row |
| `RawLogCallbackAdapter` | `logging.py` | Bridges SessionLogger to provider's RawLogCallback protocol |
| `ConfirmationCallback` | `session.py` | Async callback for user confirmation on destructive actions |

### Callback Types (session.py)

| Type | Signature | Description |
|------|-----------|-------------|
| `ToolCallCallback` | `(str, str) -> None` | `(tool_name, tool_id)` - Tool detected in stream |
| `ToolCompleteCallback` | `(str, str, bool) -> None` | `(tool_name, tool_id, success)` - Tool finished (deprecated) |
| `ReasoningCallback` | `(bool) -> None` | Reasoning state change (True=start, False=end) |
| `BatchStartCallback` | `(tuple[ToolCall, ...]) -> None` | All tools in batch about to execute |
| `ToolActiveCallback` | `(str, str) -> None` | `(name, id)` - Tool starting execution |
| `BatchProgressCallback` | `(str, str, bool, str) -> None` | `(name, id, success, error_msg)` - Tool completed |
| `BatchHaltCallback` | `() -> None` | Sequential batch halted due to error |
| `BatchCompleteCallback` | `() -> None` | All tools in batch finished |
| `ConfirmationCallback` | `(ToolCall) -> Awaitable[bool]` | Request user confirmation for destructive action |

## Session Coordinator

`Session` coordinates the CLI, LLM provider, context management, skill execution, and permission enforcement:

```python
class Session:
    def __init__(
        self,
        provider: AsyncProvider,
        context: "ContextManager | None" = None,
        logger: "SessionLogger | None" = None,
        registry: "SkillRegistry | None" = None,
        on_tool_call: ToolCallCallback | None = None,
        on_tool_complete: ToolCompleteCallback | None = None,
        on_reasoning: ReasoningCallback | None = None,
        on_batch_start: BatchStartCallback | None = None,
        on_tool_active: ToolActiveCallback | None = None,
        on_batch_progress: BatchProgressCallback | None = None,
        on_batch_halt: BatchHaltCallback | None = None,
        on_batch_complete: BatchCompleteCallback | None = None,
        max_tool_iterations: int = 10,
        skill_timeout: float = 30.0,
        max_concurrent_tools: int = 10,
        services: "ServiceContainer | None" = None,
        on_confirm: ConfirmationCallback | None = None,
    ) -> None: ...

    async def send(
        self, user_input: str, use_tools: bool = False,
        cancel_token: CancellationToken | None = None
    ) -> AsyncIterator[str]: ...

    def add_cancelled_tools(
        self, tools: list[tuple[str, str]]
    ) -> None: ...
```

**Three modes of operation:**

1. **Multi-turn streaming (with ContextManager, no tools)** - Messages streamed, history persists
2. **Multi-turn with tools (with ContextManager + SkillRegistry)** - Streaming tool execution loop
3. **Single-turn (no ContextManager)** - Each `send()` is independent, backwards compatible

### Permission Enforcement

Session integrates with the permission system via `ServiceContainer`:

```python
# Get permissions from services
permissions: AgentPermissions | None = None
if self._services:
    permissions = self._services.get("permissions")

if permissions:
    # Check if tool is enabled
    tool_perm = permissions.tool_permissions.get(tool_call.name)
    if tool_perm and not tool_perm.enabled:
        return ToolResult(error=f"Tool '{tool_call.name}' is disabled by permissions")

    # Check if confirmation required (TRUSTED mode)
    if permissions.effective_policy.requires_confirmation(tool_call.name):
        confirmed = await self._request_confirmation(tool_call)
        if not confirmed:
            return ToolResult(error="Action cancelled by user")

    # Get per-tool timeout
    if tool_perm and tool_perm.timeout is not None:
        effective_timeout = tool_perm.timeout
```

### Argument Validation

Session validates tool arguments against skill JSON schemas before execution:

```python
from nexus3.core.validation import ValidationError, validate_tool_arguments

try:
    args = validate_tool_arguments(
        tool_call.arguments,
        skill.parameters,
        logger=self.logger,
    )
except ValidationError as e:
    return ToolResult(error=f"Invalid arguments for {tool_call.name}: {e.message}")
```

### Cancellation Support

The `send()` method accepts an optional `CancellationToken` parameter for cooperative cancellation. When the token is cancelled (e.g., user presses ESC), the streaming loop exits gracefully.

```python
from nexus3.core.cancel import CancellationToken

token = CancellationToken()

# In UI code, when ESC pressed:
token.cancel()

# Streaming will exit at next checkpoint
async for chunk in session.send("Hello", cancel_token=token):
    print(chunk)
```

### Cancelled Tool Handling

When tool execution is cancelled (e.g., user presses ESC), use `add_cancelled_tools()` to queue cancellation results. On the next `send()`, these are automatically flushed to context with error messages.

```python
# After cancellation
session.add_cancelled_tools([("tool_call_123", "read_file")])

# Next send() flushes cancelled tool results to context
async for chunk in session.send("Continue..."):
    print(chunk)
```

### Tool Execution Loop (Streaming)

When a `SkillRegistry` is provided (or `use_tools=True`), Session runs a streaming tool execution loop via `_execute_tool_loop_streaming()`:

```python
# Internal method: _execute_tool_loop_streaming()
for _ in range(max_tool_iterations):  # default: 10
    async for event in provider.stream(messages, tools):
        if isinstance(event, ReasoningDelta):
            on_reasoning(True)  # Notify reasoning started
        elif isinstance(event, ContentDelta):
            on_reasoning(False)  # End reasoning if active
            yield event.text  # Stream content immediately
        elif isinstance(event, ToolCallStarted):
            on_tool_call(event.name, event.id)  # Notify display
        elif isinstance(event, StreamComplete):
            final_message = event.message

    if final_message.tool_calls:
        on_batch_start(tool_calls)  # Notify batch starting

        # Execute tools (sequential or parallel)
        for tool_call in final_message.tool_calls:
            on_tool_active(name, id)  # Mark tool as active
            result = await _execute_single_tool(tool_call)  # With permission checks
            context.add_tool_result(tool_call.id, tool_call.name, result)
            on_batch_progress(name, id, success, error)  # Report progress

            # Sequential mode: halt on error
            if not result.success:
                on_batch_halt()
                # Add halted results for remaining tools
                break

        on_batch_complete()  # Batch finished
    else:
        # Final response - return (already streamed)
        return
```

**Stream event types** (from `core.types`):
- `ReasoningDelta` - Reasoning/thinking content chunk
- `ContentDelta` - Text chunk to display immediately
- `ToolCallStarted` - Tool call detected (name, id)
- `StreamComplete` - Final `Message` with accumulated content and tool_calls

**Execution modes:**
- **Sequential (default)** - Tools execute one at a time, halts on first error
- **Parallel** - If any tool call has `"_parallel": true` in arguments, all tools in that batch execute concurrently via `asyncio.gather()`

**Safety features:**
- Max iterations (configurable, default 10) to prevent infinite loops
- Skill timeout (configurable, default 30s) with `asyncio.wait_for()`
- Concurrency limit (configurable, default 10) via semaphore for parallel execution
- Permission checks before tool execution
- Confirmation prompts for destructive actions (TRUSTED mode)
- Argument validation against JSON schema
- Unknown skills return error ToolResult
- Exceptions caught and converted to error ToolResult
- Internal arguments (prefixed with `_`) stripped before skill execution
- Sequential mode halts on error, adds "halted" results for remaining tools

## Session Persistence

The `persistence.py` module handles serialization/deserialization of session state:

### SavedSession

```python
@dataclass
class SavedSession:
    agent_id: str
    created_at: datetime
    modified_at: datetime
    messages: list[dict[str, Any]]  # Serialized Message objects
    system_prompt: str
    system_prompt_path: str | None
    working_directory: str
    permission_level: str           # "yolo" | "trusted" | "sandboxed"
    token_usage: dict[str, int]
    provenance: str                 # "user" or parent agent_id
    permission_preset: str | None   # Preset name
    disabled_tools: list[str]       # Tools disabled for this agent
    schema_version: int             # For migrations

    def to_json(self) -> str: ...
    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_json(cls, json_str: str) -> "SavedSession": ...
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SavedSession": ...
```

### Serialization Functions

```python
# Message serialization
def serialize_message(msg: Message) -> dict[str, Any]: ...
def deserialize_message(data: dict[str, Any]) -> Message: ...
def serialize_messages(messages: list[Message]) -> list[dict[str, Any]]: ...
def deserialize_messages(data: list[dict[str, Any]]) -> list[Message]: ...

# ToolCall serialization
def serialize_tool_call(tc: ToolCall) -> dict[str, Any]: ...
def deserialize_tool_call(data: dict[str, Any]) -> ToolCall: ...

# Full session serialization
def serialize_session(
    agent_id: str,
    messages: list[Message],
    system_prompt: str,
    system_prompt_path: str | None,
    working_directory: str | Path,
    permission_level: str,
    token_usage: dict[str, int],
    provenance: str = "user",
    created_at: datetime | None = None,
    permission_preset: str | None = None,
    disabled_tools: list[str] | None = None,
) -> SavedSession: ...
```

## Session Manager

The `session_manager.py` module handles disk operations:

```python
class SessionManager:
    """Manages session persistence to disk.

    Sessions are stored as JSON files:
    - Named sessions: ~/.nexus3/sessions/{name}.json
    - Last session: ~/.nexus3/last-session.json
    - Last session name: ~/.nexus3/last-session-name
    """

    def __init__(self, nexus_dir: Path | None = None) -> None: ...

    # Listing
    def list_sessions(self) -> list[SessionSummary]: ...
    def session_exists(self, name: str) -> bool: ...

    # Save/Load
    def save_session(self, saved: SavedSession) -> Path: ...
    def load_session(self, name: str) -> SavedSession: ...
    def delete_session(self, name: str) -> bool: ...

    # Last session (for resume)
    def save_last_session(self, saved: SavedSession, name: str) -> None: ...
    def load_last_session(self) -> tuple[SavedSession, str] | None: ...
    def get_last_session_name(self) -> str | None: ...
    def clear_last_session(self) -> None: ...

    # Utilities
    def rename_session(self, old_name: str, new_name: str) -> Path: ...
    def clone_session(self, src_name: str, dest_name: str) -> Path: ...
```

**Security features:**
- Path traversal prevention via `validate_agent_id()` on session names
- Secure file permissions (0o600 - owner read/write only)
- TOCTOU race prevention (catch FileNotFoundError instead of exists() checks)

## Multi-Agent Architecture

The Session module is a key component of NEXUS3's multi-agent architecture. In multi-agent scenarios, each agent gets its own independent Session and SessionLogger.

### Integration with AgentPool

The `AgentPool` (in `nexus3/rpc/pool.py`) manages multiple agent instances. When creating an agent, the pool:

1. Creates a new `SessionLogger` with its own log directory under `base_log_dir/agent_id`
2. Creates a new `ContextManager` with fresh conversation history
3. Creates a new `Session` with the shared provider but isolated context and registry
4. Creates a `Dispatcher` for JSON-RPC request handling

```python
# From AgentPool.create():
log_config = LogConfig(
    base_dir=agent_log_dir,
    streams=LogStream.ALL,
    mode="agent",
)
logger = SessionLogger(log_config)

context = ContextManager(
    config=ContextConfig(),
    logger=logger,
)
context.set_system_prompt(system_prompt)

session = Session(
    provider,  # Shared provider (connection pooling)
    context=context,  # Agent's own context
    logger=logger,  # Agent's own logger
    registry=registry,  # Agent's own skill registry
    services=services,  # For permissions
    skill_timeout=skill_timeout,
    max_concurrent_tools=max_concurrent,
)
```

### Agent Structure

Each `Agent` instance contains:

| Component | Description |
|-----------|-------------|
| `agent_id` | Unique identifier for the agent |
| `logger` | `SessionLogger` - writes to agent's own log directory |
| `context` | `ContextManager` - agent's isolated conversation history |
| `services` | `ServiceContainer` - dependency injection for skills and permissions |
| `registry` | `SkillRegistry` - agent's available tools |
| `session` | `Session` - coordinator for LLM interactions |
| `dispatcher` | `Dispatcher` - handles JSON-RPC requests |

### Shared vs. Isolated Resources

| Resource | Shared/Isolated | Reason |
|----------|-----------------|--------|
| `AsyncProvider` | Shared | Connection pooling, expensive to create |
| `PromptLoader` | Shared | Reads same config files |
| `Session` | Isolated | Each agent needs independent state |
| `ContextManager` | Isolated | Each agent has own conversation |
| `SessionLogger` | Isolated | Each agent has own logs |
| `SkillRegistry` | Isolated | Agents may have different tools |
| `AgentPermissions` | Isolated | Each agent has own permission config |

### Subagent Logging

The `SessionLogger.create_child_logger()` method creates nested loggers for subagent sessions:

```python
# Parent logger
parent_logger = SessionLogger(LogConfig())

# Create child for subagent
child_logger = parent_logger.create_child_logger()

# Child session folder is nested under parent:
# parent_session_dir/subagent_xxxxxx/
```

For multi-agent pools managed by `AgentPool`, each agent gets a top-level log directory under `base_log_dir/agent_id` rather than nested subdirectories.

## Logging System

### Log Streams

Three independent, non-exclusive streams controlled by `LogStream` flags:

| Stream | File | Enabled By | Contains |
|--------|------|------------|----------|
| CONTEXT | `session.db` + `context.md` | Always on | Messages, tool calls, tool results |
| VERBOSE | `verbose.md` + events table | `--verbose` | Thinking traces, timing, token counts |
| RAW | `raw.jsonl` | `--raw-log` | Raw API request/response bodies |

### Directory Structure

```
.nexus3/logs/
└── 2024-01-07_143052_repl_a1b2c3/    # Session folder (timestamp + mode + 6-char hex)
    ├── session.db                     # SQLite source of truth
    ├── context.md                     # Human-readable conversation
    ├── verbose.md                     # Thinking/timing (if --verbose)
    ├── raw.jsonl                      # Raw API JSON (if --raw-log)
    └── subagent_d4e5f6/               # Nested subagent session
        ├── session.db
        ├── context.md
        └── ...
```

Session ID format: `YYYY-MM-DD_HHMMSS_MODE_xxxxxx` where MODE is `repl`, `serve`, or `agent`.

### SQLite Schema (Version 2)

```sql
-- Schema version tracking
CREATE TABLE schema_version (version INTEGER PRIMARY KEY);

-- Core message storage
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,           -- system, user, assistant, tool
    content TEXT NOT NULL,
    name TEXT,                    -- tool name (for tool role)
    tool_call_id TEXT,            -- links tool result to call
    tool_calls TEXT,              -- JSON array of tool calls
    tokens INTEGER,
    timestamp REAL NOT NULL,
    in_context INTEGER DEFAULT 1, -- still in active context?
    summary_of TEXT               -- comma-separated IDs if summary
);

-- Key-value metadata
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);

-- Session markers for cleanup (Phase 6)
CREATE TABLE session_markers (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- Singleton row
    session_type TEXT NOT NULL DEFAULT 'temp',  -- 'saved' | 'temp' | 'subagent'
    session_status TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'destroyed' | 'orphaned'
    parent_agent_id TEXT,  -- Who spawned this agent (nullable)
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

-- Events for verbose logging
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER,
    event_type TEXT NOT NULL,     -- thinking, timing, token_usage
    data TEXT,                    -- JSON payload
    timestamp REAL NOT NULL,
    FOREIGN KEY (message_id) REFERENCES messages(id)
);

-- Indexes
CREATE INDEX idx_messages_in_context ON messages(in_context);
CREATE INDEX idx_messages_role ON messages(role);
CREATE INDEX idx_events_type ON events(event_type);
CREATE INDEX idx_events_message ON events(message_id);
CREATE INDEX idx_session_markers_status ON session_markers(session_status);
CREATE INDEX idx_session_markers_type ON session_markers(session_type);
```

### SessionLogger Interface

```python
# Properties
logger.session_dir -> Path
logger.session_id -> str

# Message logging (always goes to context)
logger.log_system(content: str) -> int
logger.log_user(content: str) -> int
logger.log_assistant(content, tool_calls?, thinking?, tokens?) -> int
logger.log_tool_result(tool_call_id, name, result) -> int

# Verbose stream (requires --verbose)
logger.log_thinking(content, message_id?)
logger.log_timing(operation, duration_ms, metadata?)
logger.log_token_count(prompt, completion, total)

# Raw stream (requires --raw-log)
logger.log_raw_request(endpoint, payload)
logger.log_raw_response(status, body)
logger.log_raw_chunk(chunk)

# Context management
logger.get_context_messages() -> list[Message]
logger.get_token_count() -> int
logger.mark_compacted(message_ids, summary_id)

# Session markers
logger.update_session_status(status: str)  # 'active' | 'destroyed' | 'orphaned'
logger.mark_session_destroyed()
logger.mark_session_saved()

# Subagent support
logger.create_child_logger(name?) -> SessionLogger

# Raw log callback
logger.get_raw_log_callback() -> RawLogCallback | None

# Lifecycle
logger.close()
```

### Markdown Output

Files are created with secure permissions (0o600 - owner read/write only).

**context.md format:**
```markdown
# Session Log

Started: 2024-01-07 14:30:52

---

## System

[system prompt content]

---

## User [14:30:55]

[user message]

## Assistant [14:30:58]

[assistant response]

### Tool Calls

**read_file**
```json
{"path": "/path/to/file"}
```

### Tool Result: read_file (success)

```
[file contents]
```
```

**verbose.md format:**
```markdown
# Verbose Log

Started: 2024-01-07 14:30:52

---

### Thinking [14:30:57]

[reasoning content]

**Tokens** [14:30:58]: prompt=1234, completion=567, total=1801

**stream_response** [14:30:58]: 2345.6ms
```

## Data Flow

### Streaming Mode (No Tools)

```
User Input
    |
    v
+---------+    add_user_message()    +----------------+
| Session | -----------------------> | ContextManager |
+----+----+                          +-------+--------+
     |                                       |
     | build_messages()                      | log_user()
     |<--------------------------------------+
     |                                       |
     v                                       v
+----------+                         +---------------+
| Provider |                         | SessionLogger |
+----+-----+                         +-------+-------+
     |                                       |
     | stream()                              |
     v                                       v
 Response --------------------------> +---------------+
 Chunks                               | SessionStorage| (SQLite)
                                      +---------------+
                                      |MarkdownWriter| (context.md)
                                      +---------------+
                                      |  RawWriter   | (raw.jsonl)
                                      +---------------+
```

### Tool Execution Mode (Streaming)

```
User Input
    |
    v
+--------------------------------------------------------------+
|              Session._execute_tool_loop_streaming()           |
|                                                               |
|  +-----------------------------------------------------+     |
|  | Loop (max_tool_iterations):                          |     |
|  |                                                      |     |
|  |  1. context.build_messages() -> messages             |     |
|  |  2. provider.stream(messages, tools)                 |     |
|  |     +-- ReasoningDelta -> on_reasoning(True)         |     |
|  |     +-- ContentDelta -> yield text (immediate)       |     |
|  |     +-- ToolCallStarted -> on_tool_call(name, id)    |     |
|  |     +-- StreamComplete -> final_message              |     |
|  |                                                      |     |
|  |  if final_message.tool_calls:                        |     |
|  |    on_batch_start(tool_calls)                        |     |
|  |    +---------------------------------------------+   |     |
|  |    | _execute_single_tool():                     |   |     |
|  |    |   1. Check permissions (enabled, confirm)   |   |     |
|  |    |   2. Validate arguments against schema      |   |     |
|  |    |   3. Execute with timeout                   |   |     |
|  |    |                                             |   |     |
|  |    | Sequential (default):                       |   |     |
|  |    |   for each tool_call:                       |   |     |
|  |    |     on_tool_active(name, id)                |   |     |
|  |    |     _execute_single_tool() -> result        |   |     |
|  |    |     context.add_tool_result()               |   |     |
|  |    |     on_batch_progress(name, id, ok, err)    |   |     |
|  |    |     if error: on_batch_halt(); break        |   |     |
|  |    |                                             |   |     |
|  |    | Parallel (if _parallel: true):              |   |     |
|  |    |   on_tool_active() for all tools            |   |     |
|  |    |   asyncio.gather() with semaphore           |   |     |
|  |    |   for each result:                          |   |     |
|  |    |     context.add_tool_result()               |   |     |
|  |    |     on_batch_progress()                     |   |     |
|  |    +---------------------------------------------+   |     |
|  |    on_batch_complete()                               |     |
|  |                                                      |     |
|  |  else: return (content already streamed)             |     |
|  +-----------------------------------------------------+     |
|                                                               |
+--------------------------------------------------------------+
                          |
                          v
                   Streaming Complete
```

## Dependencies

**Internal (nexus3):**
- `core.types` - Message, Role, ToolCall, ToolResult, ContentDelta, ReasoningDelta, ToolCallStarted, StreamComplete
- `core.interfaces` - AsyncProvider, RawLogCallback protocols
- `core.cancel` - CancellationToken for cooperative cancellation
- `core.permissions` - AgentPermissions for permission checks
- `core.validation` - validate_tool_arguments, validate_agent_id, ValidationError
- `context.manager` - ContextManager (optional, TYPE_CHECKING only)
- `skill.registry` - SkillRegistry (optional, TYPE_CHECKING only)
- `skill.services` - ServiceContainer (optional, TYPE_CHECKING only)

**External:**
- `sqlite3` - Database storage
- `json` - Serialization for tool_calls, events, raw logs, sessions
- `pathlib` - File path handling
- `datetime`, `time` - Timestamps
- `secrets` - Session ID generation (token_hex)
- `asyncio` - Parallel tool execution, timeouts
- `os`, `stat` - Secure file permissions

## Usage Examples

### Basic Session (Single-Turn)

```python
from nexus3.provider import OpenRouterProvider
from nexus3.session import Session, SessionLogger, LogConfig

# Create logger
logger = SessionLogger(LogConfig())

# Create session
provider = OpenRouterProvider(config)
session = Session(provider, logger=logger)

# Send message
async for chunk in session.send("Hello!"):
    print(chunk, end="", flush=True)
```

### Multi-Turn with Context

```python
from nexus3.context import ContextManager, ContextConfig
from nexus3.session import Session, SessionLogger, LogConfig

# Create logger and context
logger = SessionLogger(LogConfig())
context = ContextManager(ContextConfig(), logger)

# Create session with context
session = Session(provider, context=context)

# Conversation persists across calls
async for chunk in session.send("What is Python?"):
    print(chunk, end="")

async for chunk in session.send("Give me an example"):
    print(chunk, end="")  # Has context of previous exchange
```

### Multi-Turn with Tool Execution and Callbacks

```python
from nexus3.context import ContextManager, ContextConfig
from nexus3.session import Session, SessionLogger, LogConfig
from nexus3.skill import SkillRegistry

# Create components
logger = SessionLogger(LogConfig())
context = ContextManager(ContextConfig(), logger)
registry = SkillRegistry()

# Register skills
registry.register(read_file_skill)
registry.register(write_file_skill)

# Callbacks for UI updates
def on_batch_start(tool_calls):
    print(f"[Executing {len(tool_calls)} tools]")

def on_tool_active(name, tool_id):
    print(f"  Running: {name}")

def on_batch_progress(name, tool_id, success, error):
    status = "done" if success else f"error: {error}"
    print(f"  {name}: {status}")

def on_reasoning(is_reasoning):
    if is_reasoning:
        print("[Thinking...]")

# Create session with all callbacks
session = Session(
    provider,
    context=context,
    registry=registry,
    on_batch_start=on_batch_start,
    on_tool_active=on_tool_active,
    on_batch_progress=on_batch_progress,
    on_reasoning=on_reasoning,
    skill_timeout=30.0,
    max_concurrent_tools=10,
)

# Content streams immediately, even when tools will be called
async for chunk in session.send("Read the contents of README.md"):
    print(chunk, end="")  # Streams content in real-time
```

### Session with Permission Enforcement

```python
from nexus3.skill.services import ServiceContainer
from nexus3.core.permissions import AgentPermissions, get_builtin_preset

# Create service container with permissions
services = ServiceContainer()
permissions = AgentPermissions.from_preset(get_builtin_preset("trusted"))
services.register("permissions", permissions)

# Confirmation callback for destructive actions
async def confirm_action(tool_call):
    response = input(f"Allow {tool_call.name}? [y/N] ")
    return response.lower() == "y"

# Create session with permissions
session = Session(
    provider,
    context=context,
    registry=registry,
    services=services,
    on_confirm=confirm_action,
)

# Destructive actions will prompt for confirmation
async for chunk in session.send("Delete the temp files"):
    print(chunk, end="")
```

### Enabling Verbose and Raw Logging

```python
from nexus3.session import LogConfig, LogStream

config = LogConfig(
    base_dir=Path(".nexus3/logs"),
    streams=LogStream.CONTEXT | LogStream.VERBOSE | LogStream.RAW,
    mode="repl",  # or "serve" or "agent"
    session_type="temp",  # or "saved" or "subagent"
)
logger = SessionLogger(config)

# Now writes to:
# - session.db (always)
# - context.md (always)
# - verbose.md (thinking, timing)
# - raw.jsonl (API payloads)
```

### Creating Subagent Logger

```python
# Parent logger
parent_logger = SessionLogger(LogConfig())

# Create child for subagent
child_logger = parent_logger.create_child_logger()

# Child session folder is nested under parent:
# parent_session_dir/subagent_xxxxxx/
```

### Raw API Logging via Callback

```python
# Get callback adapter for provider
raw_callback = logger.get_raw_log_callback()

if raw_callback:
    # Provider can call:
    raw_callback.on_request(endpoint, payload)
    raw_callback.on_chunk(chunk)
    raw_callback.on_response(status, body)
```

### Handling Cancelled Tools

```python
# When user cancels during tool execution
cancelled_tools = [("tc_001", "read_file"), ("tc_002", "write_file")]
session.add_cancelled_tools(cancelled_tools)

# On next send(), cancelled results are flushed to context
async for chunk in session.send("What happened?"):
    print(chunk)
# The LLM sees: "Cancelled by user: tool execution was interrupted"
```

### Using Cancellation Token

```python
from nexus3.core.cancel import CancellationToken

token = CancellationToken()

# Start streaming in background task
async def stream_response():
    async for chunk in session.send("Write a long essay", cancel_token=token):
        print(chunk, end="")

# When user presses ESC:
token.cancel()  # Stream will exit at next checkpoint
```

### Saving and Loading Sessions

```python
from nexus3.session import SessionManager, serialize_session

# Create manager
manager = SessionManager()  # Uses ~/.nexus3/sessions/

# List existing sessions
for summary in manager.list_sessions():
    print(f"{summary.name}: {summary.message_count} messages")

# Save current session
saved = serialize_session(
    agent_id="my-project",
    messages=context.get_messages(),
    system_prompt=context.get_system_prompt(),
    system_prompt_path=None,
    working_directory=Path.cwd(),
    permission_level="trusted",
    token_usage={"prompt": 1000, "completion": 500},
    permission_preset="trusted",
    disabled_tools=["nexus_shutdown"],
)
manager.save_session(saved)

# Load session
loaded = manager.load_session("my-project")
messages = deserialize_messages(loaded.messages)

# Save as last session (for resume)
manager.save_last_session(saved, "my-project")

# Load last session on startup
result = manager.load_last_session()
if result:
    session_data, name = result
    print(f"Resuming {name}")
```

### Session Markers for Cleanup

```python
# Mark session as saved (won't be auto-cleaned)
logger.mark_session_saved()

# Mark session as destroyed
logger.mark_session_destroyed()

# Update session status
logger.update_session_status("orphaned")

# Get markers from storage
markers = logger.storage.get_session_markers()
if markers:
    print(f"Type: {markers.session_type}")
    print(f"Status: {markers.session_status}")
    print(f"Parent: {markers.parent_agent_id}")
```

## Module Exports

From `__init__.py`:

```python
__all__ = [
    "Session",
    "ConfirmationCallback",
    "SessionLogger",
    "SessionStorage",
    "SessionMarkers",
    "LogConfig",
    "LogStream",
    "SessionInfo",
    "RawLogCallbackAdapter",
    # Persistence
    "SavedSession",
    "SessionSummary",
    "serialize_message",
    "deserialize_message",
    "serialize_messages",
    "deserialize_messages",
    "serialize_session",
    # Session Manager
    "SessionManager",
    "SessionManagerError",
    "SessionNotFoundError",
]
```
