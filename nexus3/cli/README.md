# NEXUS3 CLI Module

The command-line interface for NEXUS3, providing interactive REPL, HTTP server, and RPC client capabilities.

## Overview

The CLI module implements three primary modes of operation:

1. **Unified REPL Mode** (default): Interactive REPL with an embedded HTTP server for external access
2. **Client Mode** (`--connect`): Connect to an existing NEXUS3 server as a thin client
3. **Server Mode** (`--serve`): Headless HTTP JSON-RPC server (development only, requires `NEXUS_DEV=1`)

### Architecture

```
nexus3 (no flags)
├── discover_servers(candidate_ports)
│   ├── NEXUS_SERVER found → Show connect lobby
│   │   ├── Connect to existing server
│   │   └── Or start new embedded server
│   └── NO_SERVER → Start embedded server directly:
│       ├── Create SharedComponents
│       ├── Create AgentPool with "main" agent
│       ├── Generate API key in memory
│       ├── Start HTTP server with started_event
│       ├── Save API key only after bind succeeds
│       └── REPL loop calling main agent's Session directly
```

The unified REPL calls `Session` directly (not through HTTP) to preserve streaming callbacks for rich terminal display, while external clients connect via the embedded HTTP server on the same port.

---

## Module Structure

```
nexus3/cli/
├── __init__.py          # Package entry point, exports main()
├── repl.py              # Main REPL implementation (~1900 lines)
├── serve.py             # Headless HTTP server mode
├── arg_parser.py        # CLI argument parsing with subparsers
├── client_commands.py   # RPC CLI command handlers
├── repl_commands.py     # REPL slash command handlers (~2800 lines)
├── lobby.py             # Session selection lobby UI
├── connect_lobby.py     # Server/agent connection UI
├── confirmation_ui.py   # Tool action confirmation dialogs
├── keys.py              # Keyboard input handling (ESC detection)
├── whisper.py           # Whisper mode state management
├── live_state.py        # Shared Rich Live context
└── init_commands.py     # Configuration initialization
```

---

## Module Reference

### `__init__.py` - Package Entry Point

```python
from nexus3.cli import main
```

Exports only `main()` from `repl.py`.

---

### `repl.py` - Main REPL Implementation

The heart of the CLI, implementing the unified REPL architecture.

#### Key Functions

| Function | Description |
|----------|-------------|
| `run_repl()` | Main REPL loop with embedded server |
| `run_repl_client()` | Client mode connecting to existing server |
| `main()` | Entry point parsing args and dispatching to modes |

#### `run_repl()` Parameters

```python
async def run_repl(
    verbose: bool = False,      # DEBUG output to console (-v)
    log_verbose: bool = False,  # Verbose logging to file (-V)
    raw_log: bool = False,      # Raw API JSON logging
    log_dir: Path | None = None,  # Session log directory
    port: int | None = None,    # HTTP server port
    resume: bool = False,       # Resume last session
    fresh: bool = False,        # Fresh temp session
    session_name: str | None = None,  # Load specific session
    template: Path | None = None,     # Custom system prompt
    model: str | None = None,   # Model name/alias
) -> None
```

#### Startup Flow

1. Load configuration and determine effective port
2. Discover existing servers on candidate ports
3. Show connect lobby if servers found
4. Bootstrap server components (`AgentPool`, `GlobalDispatcher`, `SharedComponents`)
5. Generate API key and start embedded HTTP server
6. Show session lobby (resume last, fresh, select from saved)
7. Create/restore main agent with trusted preset
8. Enter main input loop

#### Key Features

- **Session Callbacks**: Attaches streaming callbacks to Session for rich display
- **Callback Leak Prevention**: `_set_display_session()` detaches callbacks when switching agents
- **Incoming Turn Notifications**: RPC messages interrupt prompt and show spinner
- **Token Toolbar**: Bottom toolbar shows token usage and ready/error state
- **Auto-Save**: Saves session after each interaction for resume capability

---

### `serve.py` - Headless HTTP Server

Development-only headless server mode.

```python
async def run_serve(
    port: int | None = None,
    verbose: bool = False,
    log_verbose: bool = False,
    raw_log: bool = False,
    log_dir: Path | None = None,
) -> None
```

**Security**: Requires `NEXUS_DEV=1` environment variable.

**Startup sequence:**
1. Load configuration
2. Check for existing server on port
3. Bootstrap server components
4. Generate API key (write to disk only after bind succeeds)
5. Run until shutdown requested

---

### `arg_parser.py` - Argument Parsing

Defines CLI arguments using argparse with subparsers for `rpc` commands.

#### Helper Functions

| Function | Description |
|----------|-------------|
| `add_api_key_arg()` | Add `--api-key` argument |
| `add_port_arg()` | Add `--port/-p` argument |
| `add_verbose_arg()` | Add `-v/--verbose` argument |
| `add_log_verbose_arg()` | Add `-V/--log-verbose` argument |
| `parse_args()` | Parse all CLI arguments |

#### Main Mode Flags

| Flag | Description |
|------|-------------|
| `--serve [PORT]` | Run HTTP JSON-RPC server (requires `NEXUS_DEV=1`) |
| `--connect [URL]` | Connect to server (no URL = discover mode) |
| `--agent ID` | Agent to connect to (default: main) |
| `--scan PORTSPEC` | Additional ports to scan |
| `-v, --verbose` | DEBUG output to console |
| `-V, --log-verbose` | Verbose logging to file |
| `--raw-log` | Raw API JSON logging |
| `--log-dir PATH` | Session log directory |
| `--reload` | Auto-reload on code changes (serve mode only) |

#### Session Startup Flags

| Flag | Description |
|------|-------------|
| `--resume` | Resume last session (skip lobby) |
| `--fresh` | Start fresh temp session (skip lobby) |
| `--session NAME` | Load specific saved session (skip lobby) |
| `--template PATH` | Custom system prompt file (with `--fresh`) |
| `--model NAME` | Model name/alias to use |

#### RPC Subcommands

```
nexus3 rpc detect [--port]
nexus3 rpc list [--port] [--api-key]
nexus3 rpc create ID [--preset] [--cwd] [--write-path] [--model] [--message] [--timeout]
nexus3 rpc destroy ID [--port] [--api-key]
nexus3 rpc send AGENT MSG [--timeout] [--port] [--api-key]
nexus3 rpc cancel AGENT REQUEST_ID [--port] [--api-key]
nexus3 rpc status AGENT [--port] [--api-key]
nexus3 rpc compact AGENT [--port] [--api-key]
nexus3 rpc shutdown [--port] [--api-key]
```

---

### `client_commands.py` - RPC CLI Commands

Thin wrappers around `NexusClient` for CLI access. All commands print JSON to stdout and return exit codes.

| Function | Description |
|----------|-------------|
| `cmd_detect(port)` | Check if server is running |
| `cmd_list(port, api_key)` | List all agents |
| `cmd_create(agent_id, port, api_key, preset, cwd, ...)` | Create agent |
| `cmd_destroy(agent_id, port, api_key)` | Remove agent |
| `cmd_send(agent_id, content, port, api_key, timeout)` | Send message |
| `cmd_cancel(agent_id, request_id, port, api_key)` | Cancel request |
| `cmd_status(agent_id, port, api_key)` | Get agent status |
| `cmd_compact(agent_id, port, api_key)` | Force compaction |
| `cmd_shutdown(port, api_key)` | Shutdown server |

**Security**: Commands do NOT auto-start servers.

---

### `repl_commands.py` - REPL Slash Commands

Slash command implementations for the interactive REPL.

#### Agent Management

| Command | Description |
|---------|-------------|
| `/agent` | Show current agent status |
| `/agent <name>` | Switch to agent (prompts to create if missing) |
| `/agent <name> --yolo\|--trusted\|--sandboxed` | Create with preset and switch |
| `/agent <name> --model <alias>` | Create with specific model |
| `/whisper <agent>` | Enter whisper mode |
| `/over` | Exit whisper mode |
| `/list` | List all active agents |
| `/create <name> [--preset] [--model]` | Create without switching |
| `/destroy <name>` | Remove agent from pool |
| `/send <agent> <msg>` | One-shot message to another agent |
| `/status [agent] [--tools] [--tokens] [-a]` | Get status |
| `/cancel [agent]` | Cancel in-progress request |

#### Session Management

| Command | Description |
|---------|-------------|
| `/save [name]` | Save current session |
| `/clone <src> <dest>` | Clone agent or session |
| `/rename <old> <new>` | Rename agent or session |
| `/delete <name>` | Delete saved session |

#### Configuration

| Command | Description |
|---------|-------------|
| `/cwd [path]` | Show or change working directory |
| `/model [name]` | Show or switch model |
| `/permissions [preset]` | Show or set permissions |
| `/permissions --disable <tool>` | Disable a tool |
| `/permissions --enable <tool>` | Re-enable a tool |
| `/permissions --list-tools` | List tool status |
| `/prompt [file]` | Show or set system prompt |
| `/compact` | Force context compaction |

#### MCP (External Tools)

| Command | Description |
|---------|-------------|
| `/mcp` | List servers |
| `/mcp connect <name> [--allow-all] [--shared]` | Connect to server |
| `/mcp disconnect <name>` | Disconnect from server |
| `/mcp tools [server]` | List available tools |
| `/mcp resources [server]` | List available resources |
| `/mcp prompts [server]` | List available prompts |
| `/mcp retry <name>` | Retry listing tools |

#### GitLab

| Command | Description |
|---------|-------------|
| `/gitlab` | List configured instances |
| `/gitlab test [name]` | Test connection |

#### Initialization

| Command | Description |
|---------|-------------|
| `/init` | Create `.nexus3/` in current directory |
| `/init --force` | Overwrite existing config |
| `/init --global` | Initialize `~/.nexus3/` instead |

#### REPL Control

| Command | Description |
|---------|-------------|
| `/help [command]` | Show help (detailed with command name) |
| `/clear` | Clear display (preserves context) |
| `/quit`, `/exit`, `/q` | Exit REPL |

#### Exports

| Export | Description |
|--------|-------------|
| `HELP_TEXT` | Full help text string |
| `COMMAND_HELP` | Dict of per-command detailed help |
| `get_command_help(cmd)` | Get help for specific command |
| `print_yolo_warning(console)` | Display YOLO mode warning |

---

### `lobby.py` - Session Selection Lobby

Interactive session selection on REPL startup.

```
NEXUS3 REPL

  1) Resume: my-project (2h ago, 45 messages)
  2) Fresh session
  3) Choose from saved...

[1/2/3/q]:
```

#### Data Types

```python
class LobbyChoice(Enum):
    RESUME = auto()   # Resume last session
    FRESH = auto()    # Create fresh temp session
    SELECT = auto()   # User selected from saved list
    QUIT = auto()     # Exit

@dataclass
class LobbyResult:
    choice: LobbyChoice
    session_name: str | None = None
    template_path: Path | None = None
```

#### Functions

| Function | Description |
|----------|-------------|
| `show_lobby(session_manager, console)` | Display lobby menu |
| `show_session_list(session_manager, console)` | Show saved sessions picker |
| `format_time_ago(dt)` | Format datetime as relative time |

---

### `connect_lobby.py` - Server/Agent Connection

Interactive UI for connecting to discovered servers.

```
NEXUS3 Connect

Discovered servers:
  1) http://127.0.0.1:8765 [ready]  2 agents

Options:
  n) Start embedded server (port 8765)
  p) Start embedded server on different port...
  s) Scan additional ports...
  u) Connect to URL manually...
  q) Quit
```

#### Data Types

```python
class ConnectAction(Enum):
    CONNECT = "connect"              # Connect to server+agent
    START_NEW_SERVER = "start_new"   # Start embedded server
    START_DIFFERENT_PORT = "start_different_port"
    SHUTDOWN_AND_REPLACE = "shutdown"
    RESCAN = "rescan"                # Scan more ports
    MANUAL_URL = "manual_url"        # User entered URL
    QUIT = "quit"

@dataclass
class ConnectResult:
    action: ConnectAction
    server_url: str | None = None
    agent_id: str | None = None
    port: int | None = None
    api_key: str | None = None
    scan_spec: str | None = None
    create_agent: bool = False
```

#### Functions

| Function | Description |
|----------|-------------|
| `show_connect_lobby(console, servers, default_port, ...)` | Main connect UI |
| `show_agent_picker(console, server)` | Agent selection menu |
| `prompt_for_port(console, default)` | Port number prompt |
| `prompt_for_port_spec(console)` | Port range specification |
| `prompt_for_api_key(console)` | API key prompt (uses getpass) |
| `prompt_for_url(console)` | URL and agent ID prompt |
| `prompt_for_agent_id(console)` | Agent ID prompt |

---

### `confirmation_ui.py` - Tool Action Confirmation

Interactive confirmation prompts for destructive actions (TRUSTED mode).

```python
async def confirm_tool_action(
    tool_call: ToolCall,
    target_path: Path | None,
    agent_cwd: Path,
    pause_event: asyncio.Event,
    pause_ack_event: asyncio.Event,
) -> ConfirmationResult
```

#### Confirmation Menus by Tool Type

**Write operations** (write_file, edit_file):
```
Allow write_file?
  Path: /path/to/file.py

  [1] Allow once
  [2] Allow always for this file
  [3] Allow always in this directory
  [4] Deny
  [p] View full details
```

**Execution operations** (bash_safe, run_python):
```
Execute bash_safe?
  Command: ls -la
  Directory: /home/user

  [1] Allow once
  [2] Allow always in this directory
  [3] Deny
  [p] View full details
```

**shell_UNSAFE** (always requires per-use approval):
```
Execute shell_UNSAFE?
  Command: rm -rf temp/

  [1] Allow once
  [2] Deny
  [p] View full details
```

**MCP tools**:
```
Allow MCP tool 'mcp_github_create_issue'?
  Server: github
  Arguments: {"title": "Bug report"...}

  [1] Allow once
  [2] Allow this tool always (this session)
  [3] Allow all tools from this server (this session)
  [4] Deny
  [p] View full details
```

#### Helper Functions

| Function | Description |
|----------|-------------|
| `format_tool_params(arguments, max_length)` | Format args as truncated string |
| `smart_truncate(value, max_length, preserve_ends)` | Smart string truncation |

#### Security Features

- All values escaped with `escape_rich_markup()` to prevent injection
- Pauses Live display and KeyMonitor during prompts
- Uses `asyncio.to_thread()` for blocking input
- External editor popup for full tool details (`[p]` option)

---

### `keys.py` - Keyboard Input Handling

ESC key detection during async operations for cancellation.

```python
class KeyMonitor:
    def __init__(
        self,
        on_escape: Callable[[], None],
        pause_event: asyncio.Event,
        pause_ack_event: asyncio.Event,
    ) -> None

    async def __aenter__(self) -> "KeyMonitor"
    async def __aexit__(self, ...) -> None
```

#### Pause Protocol

1. Caller clears `pause_event` to request pause
2. Monitor sets `pause_ack_event` when paused (terminal restored)
3. Caller waits for `pause_ack_event` before taking input
4. Caller sets `pause_event` to signal resume
5. Monitor clears `pause_ack_event` and resumes monitoring

#### Platform Support

| Platform | Implementation | Details |
|----------|----------------|---------|
| Unix/Linux/macOS | `termios` + `tty` + `select` | Sets terminal to cbreak mode |
| Windows | `msvcrt` | Uses `kbhit()` and `getwch()` |
| Fallback | Sleep loop | No keyboard detection, respects pause protocol |

#### Exports

| Export | Description |
|--------|-------------|
| `ESC` | ESC key code (`"\x1b"`) |
| `KeyMonitor` | Context manager class |
| `monitor_for_escape()` | Low-level monitor function |

---

### `whisper.py` - Whisper Mode State

Manages persistent message redirection to another agent.

```python
@dataclass
class WhisperMode:
    active: bool = False
    target_agent_id: str | None = None
    original_agent_id: str | None = None

    def enter(self, target: str, current: str) -> None
    def exit(self) -> str | None
    def is_active(self) -> bool
    def get_target(self) -> str | None
    def get_prompt_prefix(self) -> str
```

**Usage in REPL:**
```
> /whisper worker-1
+-- whisper mode: worker-1 -- /over to return --+
worker-1> What is 2+2?
(response from worker-1)
worker-1> /over
+-- returned to main ----------------+
>
```

---

### `live_state.py` - Shared Live Context

Shared ContextVar for Rich Live display coordination.

```python
_current_live: ContextVar[Live | None] = ContextVar("_current_live", default=None)
```

Exists to prevent circular imports and ensure `repl.py` and `confirmation_ui.py` share the same ContextVar instance for pausing/resuming the Live display.

---

### `init_commands.py` - Configuration Initialization

Initialize configuration directories with security protections.

```python
def init_global(force: bool = False) -> tuple[bool, str]
def init_local(cwd: Path | None = None, force: bool = False) -> tuple[bool, str]
```

#### Global Init (`~/.nexus3/`)

- Copies `NEXUS.md` from defaults
- Copies `config.json` from defaults
- Creates empty `mcp.json`
- Creates `sessions/` directory

#### Local Init (`./.nexus3/`)

- Creates `NEXUS.md` template
- Creates `config.json` template
- Creates empty `mcp.json`

#### Security

Uses `_safe_write_text()` which refuses to follow symlinks, raising `InitSymlinkError` if detected.

---

## Dependencies

### Internal Dependencies

| Module | Imports From |
|--------|--------------|
| `nexus3.commands` | Unified command infrastructure |
| `nexus3.config` | Configuration loading and schema |
| `nexus3.core` | Types, errors, encoding, permissions, validation, paths, text_safety |
| `nexus3.display` | Spinner, Activity, console, theme |
| `nexus3.rpc` | Auth, bootstrap, detection, discovery, HTTP, pool |
| `nexus3.session` | Session, LogStream, SessionManager, persistence |
| `nexus3.client` | NexusClient for RPC communication |
| `nexus3.mcp` | MCP registry and permissions |

### External Dependencies

| Package | Usage |
|---------|-------|
| `prompt_toolkit` | Interactive prompt with async support, styling, HTML formatting |
| `rich` | Live display, console output, formatting |
| `python-dotenv` | Load `.env` files |

### Platform-Specific Dependencies

| Module | Platform | Usage |
|--------|----------|-------|
| `termios`, `tty`, `select` | Unix/Linux/macOS | Terminal mode control for ESC detection |
| `msvcrt` | Windows | Native keyboard input handling |

---

## Usage Examples

### Interactive REPL

```bash
# Default: lobby mode for session selection
nexus3

# Skip lobby - resume last session
nexus3 --resume

# Skip lobby - fresh temp session with specific model
nexus3 --fresh --model gpt-4o

# Skip lobby - load specific saved session
nexus3 --session my-project

# Connect to existing server
nexus3 --connect http://localhost:8765 --agent worker-1

# Connect with server discovery
nexus3 --connect

# Scan additional ports
nexus3 --connect --scan 9000-9050
```

### REPL Commands

```
# Agent management
> /agent                    # Show current agent status
> /agent analyzer --trusted # Create and switch to new agent
> /whisper worker-1         # Enter whisper mode
worker-1> do some work
worker-1> /over            # Return to original agent

# Configuration
> /permissions sandboxed
> /permissions --disable write_file
> /model claude-3-5-sonnet
> /cwd /path/to/project
> /compact

# MCP
> /mcp                      # List servers
> /mcp connect github --allow-all --shared
> /mcp tools github
> /mcp disconnect github

# Session
> /save my-session
> /clone my-session backup
> /delete old-session

# Help
> /help                     # Overview of all commands
> /help save                # Detailed help for /save
> /save --help              # Same as /help save
```

### Headless Server

```bash
# Start development server (requires NEXUS_DEV=1)
NEXUS_DEV=1 nexus3 --serve 8765

# With auto-reload on code changes
NEXUS_DEV=1 nexus3 --serve 8765 --reload --verbose
```

### RPC Client

```bash
# Check server status
nexus3 rpc detect

# List agents
nexus3 rpc list

# Create agent with initial message
nexus3 rpc create worker --preset sandboxed --cwd /path --message "Start task" --timeout 300

# Send message to agent
nexus3 rpc send worker "Continue working" --timeout 600

# Get agent status
nexus3 rpc status worker

# Force compaction (recover stuck agent)
nexus3 rpc compact worker

# Shutdown server
nexus3 rpc shutdown
```

### Configuration Init

```bash
# Initialize global config (~/.nexus3/)
nexus3 --init-global
nexus3 --init-global-force  # Overwrite existing

# Initialize project config (from REPL)
> /init
> /init --force
> /init --global
```

---

## Security Considerations

1. **Server Mode Protection**: `--serve` requires `NEXUS_DEV=1` to prevent scripts from spinning up unattended servers

2. **RPC Commands Don't Auto-Start**: All `nexus3 rpc` commands require a running server - they will not automatically start one

3. **Token Lifecycle**: API keys are only written to disk after successful server bind, and deleted on shutdown

4. **Symlink Attack Prevention**: Init commands use `_safe_write_text()` which refuses to follow symlinks

5. **Rich Markup Escaping**: All user-controlled values in confirmation prompts are escaped with `escape_rich_markup()`

6. **Idle Timeout**: Embedded server auto-shuts down after 30 minutes of no RPC activity (WSL-safe monotonic clock)

7. **Input Validation**: Agent IDs validated via `validate_agent_id()` to prevent path traversal

---

*Updated: 2026-02-01*
