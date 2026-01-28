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

## Module Files

### Core Entry Points

| File | Purpose | Key Exports |
|------|---------|-------------|
| `__init__.py` | Package entry point | `main()` |
| `repl.py` | Main REPL implementation | `run_repl()`, `run_repl_client()`, `main()` |
| `serve.py` | Headless HTTP server mode | `run_serve()` |
| `arg_parser.py` | CLI argument parsing | `parse_args()`, `add_api_key_arg()`, `add_port_arg()`, `add_verbose_arg()`, `add_log_verbose_arg()` |

### Commands and Handlers

| File | Purpose | Key Exports |
|------|---------|-------------|
| `client_commands.py` | RPC CLI commands | `cmd_detect()`, `cmd_list()`, `cmd_create()`, `cmd_destroy()`, `cmd_send()`, `cmd_cancel()`, `cmd_status()`, `cmd_compact()`, `cmd_shutdown()` |
| `repl_commands.py` | REPL slash command handlers | `cmd_agent()`, `cmd_whisper()`, `cmd_over()`, `cmd_cwd()`, `cmd_permissions()`, `cmd_prompt()`, `cmd_compact()`, `cmd_model()`, `cmd_mcp()`, `cmd_init()`, `cmd_help()`, `cmd_clear()`, `cmd_quit()`, `HELP_TEXT` |
| `init_commands.py` | Configuration initialization | `init_global()`, `init_local()` |

### UI Components

| File | Purpose | Key Exports |
|------|---------|-------------|
| `lobby.py` | Session selection lobby | `show_lobby()`, `show_session_list()`, `LobbyChoice`, `LobbyResult`, `format_time_ago()` |
| `connect_lobby.py` | Server/agent connection UI | `show_connect_lobby()`, `show_agent_picker()`, `ConnectAction`, `ConnectResult` |
| `confirmation_ui.py` | Tool action confirmation | `confirm_tool_action()`, `format_tool_params()` |
| `keys.py` | Keyboard input handling | `KeyMonitor`, `monitor_for_escape()`, `ESC` |
| `whisper.py` | Whisper mode state | `WhisperMode` |
| `live_state.py` | Shared Rich Live context | `_current_live` (ContextVar) |

---

## Detailed Component Documentation

### REPL Implementation (`repl.py`)

The main REPL is the heart of the CLI, weighing in at ~1800 lines. It handles:

**Startup Flow:**
1. Load configuration and determine effective port
2. Discover existing servers on candidate ports
3. Show connect lobby if servers found (options: connect, start new, scan more ports)
4. Bootstrap server components (`AgentPool`, `GlobalDispatcher`, `SharedComponents`)
5. Generate API key and start embedded HTTP server
6. Show session lobby (resume last, fresh, select from saved)
7. Create/restore main agent with trusted preset
8. Enter main input loop

**Key Features:**
- **Session Callbacks**: Attaches streaming callbacks to Session for rich display (tool calls, reasoning, batch progress)
- **Callback Leak Prevention**: `_set_display_session()` detaches callbacks from previous session when switching agents
- **Incoming Turn Notifications**: When RPC messages arrive, interrupts prompt and shows spinner
- **Token Toolbar**: Bottom toolbar shows token usage and ready/error state
- **Auto-Save**: Saves session after each interaction for resume capability

**Session Management:**
```python
# Save current agent as last session
save_as_last_session(current_agent_id)

# Serialize session state
serialize_session(
    agent_id=agent_name,
    messages=agent.context.messages,
    system_prompt=agent.context.system_prompt,
    working_directory=str(agent.services.get_cwd()),
    permission_level=perm_level,
    token_usage=agent.context.get_token_usage(),
    # ...
)
```

### Argument Parser (`arg_parser.py`)

Defines all CLI arguments using argparse with subparsers for the `rpc` command group.

**Main Mode Flags:**
- `--serve [PORT]`: Run HTTP JSON-RPC server (requires `NEXUS_DEV=1`)
- `--connect [URL]`: Connect to server (no URL = discover mode)
- `--agent ID`: Agent to connect to (default: main)
- `--verbose`: Enable verbose logging
- `--raw-log`: Enable raw API JSON logging
- `--log-dir PATH`: Session log directory
- `--reload`: Auto-reload on code changes (serve mode only)

**Session Startup Flags (skip lobby):**
- `--resume`: Resume last session
- `--fresh`: Start fresh temp session
- `--session NAME`: Load specific saved session
- `--template PATH`: Custom system prompt file
- `--model NAME`: Model name/alias to use

**RPC Subcommands:**
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

### Lobby System (`lobby.py`)

The lobby provides session selection on REPL startup:

```
NEXUS3 REPL

  1) Resume: my-project (2h ago, 45 messages)
  2) Fresh session
  3) Choose from saved...

[1/2/3/q]:
```

**LobbyChoice Enum:**
- `RESUME`: Resume last session
- `FRESH`: Create fresh temp session
- `SELECT`: User selected from saved list
- `QUIT`: Exit

**LobbyResult Dataclass:**
```python
@dataclass
class LobbyResult:
    choice: LobbyChoice
    session_name: str | None = None
    template_path: Path | None = None
```

### Connect Lobby (`connect_lobby.py`)

When servers are discovered, shows options for connecting:

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

**ConnectAction Enum:**
- `CONNECT`: Connect to selected server+agent
- `START_NEW_SERVER`: Start embedded server
- `START_DIFFERENT_PORT`: Start on user-specified port
- `SHUTDOWN_AND_REPLACE`: Shutdown selected server then start new
- `RESCAN`: Scan more ports
- `MANUAL_URL`: User entered URL manually
- `QUIT`: Exit

**Agent Picker:** After selecting a server, shows agent list with options to connect, create new, or go back.

### Whisper Mode (`whisper.py`)

Whisper mode enables persistent message redirection to another agent:

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

### Key Monitor (`keys.py`)

Provides ESC key detection during async operations for cancellation:

```python
class KeyMonitor:
    """Context manager for monitoring keys during an operation."""

    def __init__(
        self,
        on_escape: Callable[[], None],
        pause_event: asyncio.Event,
        pause_ack_event: asyncio.Event,
    ) -> None

    async def __aenter__(self) -> "KeyMonitor"
    async def __aexit__(self, ...) -> None
```

**Pause Protocol (for confirmation dialogs):**
1. Caller clears `pause_event` to request pause
2. Monitor sets `pause_ack_event` when paused (terminal restored)
3. Caller waits for `pause_ack_event` before taking input
4. Caller sets `pause_event` to signal resume
5. Monitor clears `pause_ack_event` and resumes monitoring

**Platform Support:**
- Unix: Uses `termios`/`tty` for non-blocking input with `select()`
- Windows: Uses `msvcrt.kbhit()` and `msvcrt.getwch()` for native keyboard handling

### Windows ESC Key Support

On Windows, ESC key detection uses `msvcrt.kbhit()` and `msvcrt.getwch()` instead of termios. This provides native Windows keyboard handling without requiring additional dependencies.

**Requirements:**
- Windows Terminal or PowerShell 7+ recommended
- Falls back to sleep-only loop if `msvcrt` unavailable

**Behavior:**
- Polls for keyboard input using `msvcrt.kbhit()`
- Reads key with `msvcrt.getwch()` (wide character support)
- Detects ESC key (character code 27) to trigger cancellation callback

### Confirmation UI (`confirmation_ui.py`)

Provides interactive confirmation prompts for destructive tool actions (TRUSTED mode):

```python
async def confirm_tool_action(
    tool_call: ToolCall,
    target_path: Path | None,
    agent_cwd: Path,
    pause_event: asyncio.Event,
    pause_ack_event: asyncio.Event,
) -> ConfirmationResult
```

**Confirmation Options by Tool Type:**

*Write operations (write_file, edit_file):*
```
Allow write_file?
  Path: /path/to/file.py

  [1] Allow once
  [2] Allow always for this file
  [3] Allow always in this directory
  [4] Deny
```

*Execution operations (bash_safe, run_python):*
```
Execute bash_safe?
  Command: ls -la
  Directory: /home/user

  [1] Allow once
  [2] Allow always in this directory
  [3] Deny
```

*shell_UNSAFE (always requires per-use approval):*
```
Execute shell_UNSAFE?
  Command: rm -rf temp/

  [1] Allow once
  [2] Deny
  (shell_UNSAFE requires approval each time)
```

*MCP tools:*
```
Allow MCP tool 'mcp_github_create_issue'?
  Server: github
  Arguments: {"title": "Bug report"...}

  [1] Allow once
  [2] Allow this tool always (this session)
  [3] Allow all tools from this server (this session)
  [4] Deny
```

**Security Features:**
- All values escaped with `escape_rich_markup()` to prevent injection
- Pauses Live display and KeyMonitor during prompts
- Uses `asyncio.to_thread()` for blocking input

### HTTP Server Mode (`serve.py`)

Headless HTTP server for development and automation:

```python
async def run_serve(
    port: int | None = None,
    verbose: bool = False,
    raw_log: bool = False,
    log_dir: Path | None = None,
) -> None
```

**Startup:**
1. Load configuration
2. Check for existing server on port
3. Bootstrap server components
4. Generate API key and write to token file after bind succeeds
5. Run until shutdown requested

**Security:** Requires `NEXUS_DEV=1` environment variable to prevent unattended servers.

### Client Commands (`client_commands.py`)

Thin wrappers around `NexusClient` for CLI access:

```python
async def cmd_detect(port: int) -> int
async def cmd_list(port: int, api_key: str | None) -> int
async def cmd_create(agent_id: str, port: int, api_key: str | None, preset: str, ...) -> int
async def cmd_destroy(agent_id: str, port: int, api_key: str | None) -> int
async def cmd_send(agent_id: str, content: str, port: int, api_key: str | None, timeout: float) -> int
async def cmd_cancel(agent_id: str, request_id: str, port: int, api_key: str | None) -> int
async def cmd_status(agent_id: str, port: int, api_key: str | None) -> int
async def cmd_compact(agent_id: str, port: int, api_key: str | None) -> int
async def cmd_shutdown(port: int, api_key: str | None) -> int
```

All commands:
- Print JSON to stdout for parsing
- Print errors to stderr
- Return exit code (0 = success, 1 = error)
- Do NOT auto-start servers (security measure)

### REPL Commands (`repl_commands.py`)

Slash command handlers for the interactive REPL:

**Agent Management:**
- `/agent` - Show current agent status
- `/agent <name>` - Switch to agent (prompts to create/restore if missing)
- `/agent <name> --yolo|--trusted|--sandboxed` - Create with preset and switch
- `/whisper <agent>` - Enter whisper mode
- `/over` - Exit whisper mode

**Configuration:**
- `/cwd [path]` - Show or change working directory
- `/permissions [preset|--disable TOOL|--enable TOOL|--list-tools]` - Permission management
- `/prompt [file]` - Show or set system prompt
- `/model [name]` - Show or switch model
- `/compact` - Force context compaction

**MCP:**
- `/mcp` - List servers
- `/mcp connect <name> [--allow-all|--per-tool] [--shared|--private]` - Connect to server
- `/mcp disconnect <name>` - Disconnect from server
- `/mcp tools [server]` - List available tools

**Session:**
- `/save [name]` - Save current session
- `/clone <src> <dest>` - Clone session
- `/rename <old> <new>` - Rename session
- `/delete <name>` - Delete saved session

**REPL Control:**
- `/help` - Display help
- `/clear` - Clear display
- `/quit`, `/exit`, `/q` - Exit REPL

### Init Commands (`init_commands.py`)

Configuration directory initialization with symlink attack protection:

```python
def init_global(force: bool = False) -> tuple[bool, str]
def init_local(cwd: Path | None = None, force: bool = False) -> tuple[bool, str]
```

**Global Init (`~/.nexus3/`):**
- Copies NEXUS.md from defaults
- Copies config.json from defaults
- Creates empty mcp.json
- Creates sessions/ directory

**Local Init (`./.nexus3/`):**
- Creates NEXUS.md template
- Creates config.json template
- Creates empty mcp.json

**Security:** Uses `_safe_write_text()` which refuses to follow symlinks.

### Live State (`live_state.py`)

Shared ContextVar for Rich Live display coordination:

```python
_current_live: ContextVar[Live | None] = ContextVar("_current_live", default=None)
```

This exists to prevent circular imports and ensure `repl.py` and `confirmation_ui.py` share the same ContextVar instance for pausing/resuming the Live display during confirmation prompts.

---

## Dependencies

### Internal Dependencies

| Module | Imports From |
|--------|--------------|
| `nexus3.commands` | Unified command infrastructure |
| `nexus3.config` | Configuration loading and schema |
| `nexus3.core` | Types, errors, encoding, permissions, validation, paths |
| `nexus3.display` | StreamingDisplay, Activity, console, theme |
| `nexus3.rpc` | Auth, bootstrap, detection, discovery, HTTP, pool |
| `nexus3.session` | Session, LogStream, SessionManager, persistence |
| `nexus3.client` | NexusClient for RPC communication |
| `nexus3.mcp` | MCP registry and permissions |

### External Dependencies

| Package | Usage |
|---------|-------|
| `prompt_toolkit` | Interactive prompt with async support, styling |
| `rich` | Live display, console output, formatting |
| `python-dotenv` | Load .env files |

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

---

*Updated: 2026-01-21*
