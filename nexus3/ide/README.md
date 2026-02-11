# nexus3/ide

IDE integration for NEXUS3 agents via WebSocket MCP (Model Context Protocol).

**Updated: 2026-02-11**

## Overview

The `nexus3.ide` module provides a bridge between NEXUS3 agents and IDE features exposed through a WebSocket-based MCP server (e.g., a VS Code extension). It enables agents to interact with IDE capabilities: viewing diffs for file-write confirmations, reading LSP diagnostics, seeing open editor tabs, and injecting IDE context into agent system prompts.

### Key Capabilities

- **IDE discovery:** Automatic lock file scanning with PID validation and workspace matching
- **WebSocket MCP transport:** Persistent connection with ping/pong keepalive
- **Diff-based confirmations:** Route file-write confirmations through IDE diff viewer (blocks until accept/reject)
- **LSP diagnostics:** Read error/warning diagnostics from the IDE's language servers
- **Editor awareness:** Query open tabs, selections, workspace folders, dirty state
- **Context injection:** Format IDE state for system prompt injection (open tabs, diagnostics)
- **Automatic reconnection:** Reconnects on dead connections with workspace rediscovery

---

## Architecture

```
IDEBridge (one per REPL session)
    |
    +-- discover_ides(cwd)         -> list[IDEInfo]
    |       scans ~/.nexus3/ide/*.lock
    |       validates PIDs, matches workspace
    |
    +-- IDEConnection
            +-- MCPClient
            |       +-- WebSocketTransport -> ws://127.0.0.1:{port}
            |
            +-- open_diff()        -> DiffOutcome (blocks until user decides)
            +-- get_diagnostics()  -> list[Diagnostic]
            +-- get_open_editors() -> list[EditorInfo]
            +-- ...11 methods total
```

### Data Flow

1. **Discovery:** Scan `~/.nexus3/ide/*.lock` for running IDE instances
2. **Matching:** Filter by workspace folder overlap with agent's CWD, sort by longest prefix
3. **Connection:** WebSocket connect with auth token from lock file, MCP handshake
4. **Usage:** Agents call typed wrapper methods (open_diff, get_diagnostics, etc.)
5. **Context:** IDE state formatted and injected into system prompt between git and clipboard sections
6. **Reconnection:** Dead connections detected and re-established via workspace rediscovery

---

## Module Structure

```
nexus3/ide/
+-- __init__.py       # Public API exports
+-- bridge.py         # IDEBridge lifecycle manager
+-- connection.py     # IDEConnection (typed async MCP tool wrappers) + result types
+-- context.py        # format_ide_context() for system prompt injection
+-- discovery.py      # Lock file scanning + PID validation
+-- transport.py      # WebSocketTransport (MCPTransport subclass)
```

---

## Public Exports

```python
from nexus3.ide import (
    # Bridge
    IDEBridge,              # Lifecycle manager (discovery, connect, reconnect)

    # Connection
    IDEConnection,          # Typed async wrappers around MCPClient.call_tool()

    # Result types
    DiffOutcome,            # Enum: FILE_SAVED, DIFF_REJECTED
    Diagnostic,             # LSP diagnostic (file_path, line, message, severity, source)
    Selection,              # Editor text selection (file_path, text, line/char ranges)
    EditorInfo,             # Open editor tab (file_path, is_active, is_dirty, language_id)

    # Discovery
    IDEInfo,                # Lock file data (pid, workspace_folders, ide_name, port, auth_token)
    discover_ides,          # Scan lock files, validate PIDs, match workspace

    # Transport
    WebSocketTransport,     # WebSocket MCPTransport subclass

    # Context
    format_ide_context,     # Format IDE state for system prompt injection
)
```

---

## Constants

| Constant | Value | Location | Description |
|----------|-------|----------|-------------|
| `_MAX_IDE_CONTEXT_LENGTH` | 800 | `context.py` | Max characters for system prompt injection |
| Ping interval | 30s | `transport.py` | WebSocket ping/pong interval |
| Ping timeout | 10s | `transport.py` | WebSocket ping/pong timeout |
| Connect timeout | 10s | `bridge.py` | MCPClient connection timeout |
| Max open tabs shown | 10 | `context.py` | Truncated in context injection |
| Max diagnostics shown | 50 | `context.py` | Default cap for error details |

---

## Components

### IDEBridge (`bridge.py`)

Manages IDE discovery and connection lifecycle. Created once per SharedComponents (one per REPL session). Not connected until `auto_connect()` or `connect()` is called.

```python
from nexus3.ide import IDEBridge

bridge = IDEBridge(config=ide_config)

# Auto-discover and connect to best-matching IDE
connection = await bridge.auto_connect(cwd=Path("/home/user/project"))

# Or connect to a specific IDE
connection = await bridge.connect(ide_info)

# Check connection status
if bridge.is_connected:
    conn = bridge.connection  # IDEConnection | None

# Reconnect after connection loss
reconnected = await bridge.reconnect_if_dead(cwd=Path("/home/user/project"))

# Disconnect
await bridge.disconnect()
```

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `connection` | `IDEConnection \| None` | Current connection (None if disconnected) |
| `is_connected` | `bool` | Whether transport is alive |

**Methods:**

| Method | Description |
|--------|-------------|
| `auto_connect(cwd)` | Discover and connect to best-matching IDE for CWD |
| `connect(ide_info)` | Connect to a specific IDE instance |
| `disconnect()` | Disconnect from current IDE |
| `reconnect_if_dead(cwd?)` | Reconnect if dead, returns True if connected |

**Internal state:**
- `_diff_lock` (`asyncio.Lock`): Serializes `openDiff` requests to prevent concurrent diff tabs
- `_last_cwd` (`Path | None`): Remembered for reconnection rediscovery

### IDEConnection (`connection.py`)

Typed async wrappers around `MCPClient.call_tool()`. Each method maps to a specific MCP tool exposed by the IDE extension.

```python
# Show diff and block until user accepts or rejects
outcome = await connection.open_diff(
    old_file_path="/path/to/file.py",
    new_file_path="/path/to/file.py",
    new_file_contents="new content here",
    tab_name="NEXUS3: file.py",
)
if outcome == DiffOutcome.FILE_SAVED:
    # User accepted the change
    pass

# Read LSP diagnostics
diagnostics = await connection.get_diagnostics()
errors = [d for d in diagnostics if d.severity == "error"]

# Query open editors
editors = await connection.get_open_editors()
active = [e for e in editors if e.is_active]
```

**Methods (11 total):**

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `open_diff` | `old_file_path, new_file_path, new_file_contents, tab_name` | `DiffOutcome` | Show diff, blocks until accept/reject |
| `open_file` | `file_path, preview?` | `None` | Open file in editor |
| `get_diagnostics` | `uri?` | `list[Diagnostic]` | LSP diagnostics (all or per-file) |
| `get_current_selection` | -- | `Selection \| None` | Active editor selection (requires focus) |
| `get_latest_selection` | -- | `Selection \| None` | Latest selection (persists across focus changes) |
| `get_open_editors` | -- | `list[EditorInfo]` | Open tabs |
| `get_workspace_folders` | -- | `list[str]` | Workspace folder paths |
| `check_document_dirty` | `file_path` | `bool` | Unsaved changes check |
| `save_document` | `file_path` | `None` | Save document |
| `close_tab` | `tab_name` | `None` | Close specific tab |
| `close_all_diff_tabs` | -- | `None` | Close all NEXUS3 diff tabs |

**Properties:**
- `is_connected` -- Whether the underlying WebSocket transport is alive
- `ide_info` -- The `IDEInfo` for this connection

### Result Types (`connection.py`)

**DiffOutcome:** Enum result of an `openDiff` operation
```python
class DiffOutcome(Enum):
    FILE_SAVED = "FILE_SAVED"       # User accepted the diff
    DIFF_REJECTED = "DIFF_REJECTED" # User rejected the diff
```

**Diagnostic:** LSP diagnostic from IDE
```python
@dataclass
class Diagnostic:
    file_path: str              # Absolute file path
    line: int                   # Line number
    message: str                # Diagnostic message
    severity: str               # "error", "warning", "info", "hint"
    source: str | None = None   # Language server source (e.g., "pylance")
```

**Selection:** Editor text selection
```python
@dataclass
class Selection:
    file_path: str              # File containing selection
    text: str                   # Selected text content
    start_line: int             # Start line number
    start_character: int        # Start character offset
    end_line: int               # End line number
    end_character: int          # End character offset
```

**EditorInfo:** Open editor tab info
```python
@dataclass
class EditorInfo:
    file_path: str              # File path
    is_active: bool = False     # Whether tab is active
    is_dirty: bool = False      # Whether file has unsaved changes
    language_id: str | None = None  # VS Code language ID (e.g., "python")
```

### WebSocketTransport (`transport.py`)

Subclass of `MCPTransport` (from `nexus3.mcp.transport`) for WebSocket communication with IDE MCP servers. Uses the `websockets` library (v13+).

```python
from nexus3.ide import WebSocketTransport

transport = WebSocketTransport(
    url="ws://127.0.0.1:12345",
    auth_token="random-session-token",
)
await transport.connect()
await transport.send({"jsonrpc": "2.0", "method": "...", "id": 1})
response = await transport.receive()
await transport.close()
```

**Key design decisions:**
- **Background listener task:** Reads all WebSocket frames and queues them. All messages including notifications are queued because `MCPClient._call()` has its own notification-discarding loop that expects to see everything via `receive()`.
- **Auth via header:** Token sent as `x-nexus3-ide-authorization` HTTP header during WebSocket handshake.
- **Keepalive:** 30-second ping interval, 10-second pong timeout.
- **Lifecycle:** Uses `await websockets.connect()` directly (not `async with`) since lifecycle is managed by explicit `connect()`/`close()` calls.

**Properties:**
- `is_connected` -- Checks three conditions: WebSocket exists, protocol exists, and listener task is alive (not done)

### Discovery (`discovery.py`)

Lock file scanning and PID validation for IDE discovery.

```python
from nexus3.ide import discover_ides, IDEInfo

# Find IDEs whose workspace contains the given CWD
ides = discover_ides(cwd=Path("/home/user/project"))
if ides:
    best_match = ides[0]  # Sorted by longest prefix match
    print(f"Found {best_match.ide_name} on port {best_match.port}")
```

**IDEInfo:** Lock file data
```python
@dataclass
class IDEInfo:
    pid: int                        # IDE process ID
    workspace_folders: list[str]    # Workspace folder paths
    ide_name: str                   # IDE name (e.g., "VS Code")
    transport: str                  # Transport type (e.g., "ws")
    auth_token: str                 # Authentication token
    port: int                       # WebSocket port number
    lock_path: Path                 # Path to the lock file
```

**Lock file format:** `~/.nexus3/ide/{port}.lock`
```json
{
    "pid": 12345,
    "workspaceFolders": ["/home/user/project"],
    "ideName": "VS Code",
    "transport": "ws",
    "authToken": "random-token-here"
}
```

**Discovery behavior:**
1. Scans `~/.nexus3/ide/*.lock` (port number from filename stem)
2. Validates PID is alive via `os.kill(pid, 0)`
3. Cleans up stale lock files (dead PIDs)
4. Filters by workspace match (CWD must be within a workspace folder)
5. Sorts by longest prefix match (best match first)

### Context Formatting (`context.py`)

Formats IDE state for injection into the agent system prompt.

```python
from nexus3.ide import format_ide_context

context = format_ide_context(
    ide_name="VS Code",
    open_editors=editors,
    diagnostics=diagnostics,
    inject_diagnostics=True,
    inject_open_editors=True,
    max_diagnostics=50,
)
# Returns str | None (None if nothing to inject)
```

**Output example:**
```
IDE connected: VS Code
  Open tabs: main.py, utils.py, test_main.py
  Diagnostics: 2 errors, 3 warnings
    main.py:42: Undefined variable 'foo'
    utils.py:17: Missing return type annotation
```

**Behavior:**
- Returns `None` if no open editors and no diagnostics to show
- Truncates to 800 characters max (with `...` suffix)
- Shows at most 10 open tab names (filename only, not full path)
- Groups diagnostics into error/warning counts, then lists error details
- Injected between git context and clipboard context in system prompt

---

## Integration Points

The IDE module integrates with several other NEXUS3 components:

| Component | Location | Integration |
|-----------|----------|-------------|
| **SharedComponents** | `rpc/pool.py` | `ide_bridge` field, registered in ServiceContainer |
| **Bootstrap** | `rpc/bootstrap.py` | Created in REPL mode when `config.ide.enabled` |
| **ContextManager** | `context/manager.py` | `_ide_context` field, injected into system prompt |
| **Session** | `session/session.py` | IDE context refreshed after tool batch completion |
| **REPL** | `cli/repl.py` | `confirm_with_ide_or_terminal` routes file-write confirmations through IDE diff viewer with terminal fallback; reconnection attempted on dead connections |

---

## Configuration

IDE behavior is controlled by `IDEConfig` in `config/schema.py`:

```json
{
    "ide": {
        "enabled": true,
        "auto_connect": true,
        "inject_diagnostics": true,
        "inject_open_editors": true,
        "use_ide_diffs": true
    }
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `true` | Enable IDE bridge creation at startup |
| `auto_connect` | `bool` | `true` | Auto-discover and connect to running IDEs |
| `inject_diagnostics` | `bool` | `true` | Inject LSP diagnostics into system prompt context |
| `inject_open_editors` | `bool` | `true` | Inject open editor tabs into system prompt context |
| `use_ide_diffs` | `bool` | `true` | Route file-write confirmations through IDE diff viewer |

---

## Security Considerations

| Protection | Description |
|------------|-------------|
| Localhost only | WebSocket connects to `127.0.0.1` only |
| Auth token | Per-session random token stored in lock file, sent via `x-nexus3-ide-authorization` HTTP header |
| PID validation | Dead processes detected via `os.kill(pid, 0)`, stale lock files cleaned up |
| Lock file permissions | Created by VS Code extension with standard file permissions |
| Diff serialization | `asyncio.Lock` prevents concurrent diff tabs that could confuse the user |

---

## Dependencies

### Internal Dependencies

| Module | Usage |
|--------|-------|
| `nexus3.mcp.client` | `MCPClient` for MCP protocol communication |
| `nexus3.mcp.transport` | `MCPTransport` base class for WebSocketTransport |
| `nexus3.config.schema` | `IDEConfig` (TYPE_CHECKING only) |

### External Dependencies

| Package | Required For | Install |
|---------|--------------|---------|
| `websockets` (v13+) | `WebSocketTransport` | `pip install websockets` |

**Note:** `websockets` is imported unconditionally in `transport.py`, so it is required whenever the `nexus3.ide` module's transport is used.

---

*Updated: 2026-02-11*
