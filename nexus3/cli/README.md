# CLI Module

The command-line interface for NEXUS3, providing interactive REPL, HTTP server, and client modes.

## Purpose

This module is the primary user-facing interface for NEXUS3. It handles:

- **Unified REPL** - Interactive sessions with embedded HTTP server for multi-client access
- **HTTP Server Mode** - Headless multi-agent JSON-RPC server for automation
- **Client Mode** - REPL connected to a remote Nexus server
- **RPC Commands** - Programmatic commands for controlling remote agents

Key features:
- User input processing with comprehensive slash command system
- ESC key cancellation during streaming operations
- Lobby mode for session selection on startup
- Whisper mode for side conversations with other agents
- Session persistence and auto-save
- Permission system integration with confirmation prompts
- Auto-reload during development (server mode)

## Files

### `repl.py` - Main Entry Point and Interactive REPL

The primary CLI entry point that routes to different modes based on arguments.

| Function | Description |
|----------|-------------|
| `main()` | Entry point for CLI, routes to REPL, server, client, or RPC commands |
| `parse_args()` | Argument parser for all CLI flags and subcommands |
| `run_repl()` | Async REPL loop with unified mode (embedded HTTP server) |
| `run_repl_client()` | Async REPL as client to remote Nexus server |
| `confirm_tool_action()` | Confirmation callback for destructive actions |
| `_run_with_reload()` | Runs server with watchfiles auto-reload on code changes |

Key responsibilities:
- Detects if a server is already running on the port before starting
- Loads configuration via `load_config()` and custom permission presets
- Creates `OpenRouterProvider` for LLM access
- Creates `SharedComponents` and `AgentPool` for agent management
- Generates and manages API keys via `ServerKeyManager`
- Shows lobby mode for session selection (resume/fresh/choose)
- Supports CLI flags to skip lobby: `--resume`, `--fresh`, `--session NAME`
- Creates/restores agents based on startup mode
- Wires session callbacks for streaming display, tool execution, and confirmation prompts
- Starts HTTP server as background task for external client access
- Auto-saves current session after each interaction
- Handles comprehensive slash commands via `handle_slash_command()`
- Manages whisper mode state for side conversations
- Coordinates `Rich.Live` display during streaming with `KeyMonitor` for ESC cancellation

### `serve.py` - HTTP JSON-RPC Multi-Agent Server

Runs NEXUS3 as a headless HTTP server with multi-agent support via AgentPool.

| Function | Description |
|----------|-------------|
| `run_serve(port, verbose, raw_log, log_dir)` | Async function that starts multi-agent HTTP server |

Architecture:
- **SharedComponents** - Immutable resources shared across all agents (config, provider, prompt_loader, custom_presets)
- **AgentPool** - Manages agent lifecycle (create, destroy, list, get, restore)
- **GlobalDispatcher** - Handles agent management RPC methods (create_agent, destroy_agent, list_agents, shutdown_server)
- **Per-agent Dispatcher** - Handles agent-specific RPC methods (send, cancel, get_tokens, etc.)
- **SessionManager** - Manages saved session files for persistence

Key responsibilities:
- Detects if a server is already running before starting
- Creates `SharedComponents` with config, provider, prompt loader, and custom presets
- Creates `AgentPool` for managing multiple agent instances
- Creates `GlobalDispatcher` for agent lifecycle management
- Generates and saves API key for authentication
- Runs `run_http_server()` with path-based routing
- Cleans up API key and all agents on shutdown

Protocol:
- `POST /` or `POST /rpc` - Routes to GlobalDispatcher (agent management)
- `POST /agent/{agent_id}` - Routes to agent's Dispatcher (agent operations)
- All requests require `Authorization: Bearer <api_key>` header

### `repl_commands.py` - REPL-Specific Command Handlers

Slash command implementations that only work in REPL mode.

| Command | Description |
|---------|-------------|
| `/agent [name] [--perm]` | Show current agent status, switch, or create+switch with permission |
| `/whisper <agent>` | Enter whisper mode (redirect input to target agent) |
| `/over` | Exit whisper mode, return to original agent |
| `/cwd [path]` | Show or set working directory for current agent |
| `/permissions [args]` | Show/modify permissions (preset, --disable, --enable, --list-tools) |
| `/prompt [file]` | Show or set system prompt from file |
| `/help` | Display comprehensive help text |
| `/clear` | Clear the display (preserves context) |
| `/quit`, `/exit`, `/q` | Exit REPL |

The module also exports `HELP_TEXT` constant with full command reference.

### `client_commands.py` - RPC CLI Commands

Thin wrappers around `NexusClient` for command-line use. Each function prints JSON to stdout and returns an exit code.

| Command | Description | Auto-starts Server |
|---------|-------------|-------------------|
| `cmd_detect(port)` | Check if server is running | No |
| `cmd_list(port, api_key)` | List all agents | Yes |
| `cmd_create(agent_id, port, api_key)` | Create agent | Yes |
| `cmd_destroy(agent_id, port, api_key)` | Destroy agent | No |
| `cmd_send(agent_id, content, port, api_key)` | Send message | No |
| `cmd_cancel(agent_id, request_id, port, api_key)` | Cancel request | No |
| `cmd_status(agent_id, port, api_key)` | Get tokens + context | No |
| `cmd_shutdown(port, api_key)` | Shutdown server | No |

Commands that require a running server will error if none exists. Commands that auto-start will spawn a detached server process and wait for it to be ready.

### `commands.py` - Legacy Slash Command Parsing

Basic slash command parsing (mostly superseded by `repl_commands.py`).

| Type | Description |
|------|-------------|
| `Command` | Dataclass with `name: str` and `args: str` fields |
| `CommandResult` | Enum: `QUIT`, `HANDLED`, `UNKNOWN` |
| `parse_command(user_input)` | Returns `Command` if input starts with `/`, else `None` |
| `handle_command(command)` | Executes basic commands and returns `CommandResult` |

Currently only handles `/quit`, `/exit`, `/q`. Other commands routed through `repl_commands.py`.

### `lobby.py` - Session Selection UI

Interactive session selection screen shown when starting NEXUS3 without flags.

| Type/Function | Description |
|---------------|-------------|
| `LobbyChoice` | Enum: `RESUME`, `FRESH`, `SELECT`, `QUIT` |
| `LobbyResult` | Dataclass with choice, session_name, template_path |
| `format_time_ago(dt)` | Format datetime as relative time (e.g., "2h ago") |
| `show_lobby(session_manager, console)` | Display lobby menu and get user choice |
| `show_session_list(session_manager, console)` | Display saved sessions for selection |

Example lobby display:
```
NEXUS3 REPL

  1) Resume: my-project (2h ago, 45 messages)
  2) Fresh session
  3) Choose from saved...

[1/2/3/q]:
```

### `whisper.py` - Whisper Mode State Management

Manages whisper mode state for side conversations with other agents.

| Type | Description |
|------|-------------|
| `WhisperMode` | Dataclass managing whisper state |

Methods:
- `enter(target, current)` - Enter whisper mode targeting another agent
- `exit()` - Exit whisper mode, returns original agent ID
- `is_active()` - Check if in whisper mode
- `get_target()` - Get current whisper target
- `get_prompt_prefix()` - Get prompt prefix for display

Example flow:
```
> /whisper worker-1
worker-1> What is 2+2?
(response from worker-1)
worker-1> /over
(returns to original agent)
```

### `keys.py` - ESC Key Handling

Provides ESC key detection during async operations for cancellation.

| Type | Description |
|------|-------------|
| `ESC` | Constant `"\x1b"` - the ESC key code |
| `monitor_for_escape(on_escape, check_interval)` | Background task that monitors stdin for ESC |
| `KeyMonitor` | Async context manager wrapping `monitor_for_escape()` |

Implementation details:
- **Unix**: Uses `termios.tcgetattr()` / `tty.setcbreak()` for raw terminal mode
- **Unix**: Uses `select.select()` for non-blocking input polling
- **Windows**: Falls back to no-op (ESC detection not currently supported)
- Restores terminal settings on exit via try/finally

### `__init__.py` - Module Exports

Exports only `main` from `repl.py`.

## CLI Modes

### 1. Unified REPL (default)

Interactive mode with embedded HTTP server for external client access.

```bash
nexus                    # Start with lobby
nexus --fresh            # Skip lobby, fresh temp session
nexus --resume           # Skip lobby, resume last session
nexus --session myproj   # Skip lobby, load specific session
nexus --template FILE    # Use custom prompt (with --fresh)
```

Features:
- Lobby mode for session selection
- prompt-toolkit input with persistent bottom toolbar showing status
- Rich.Live display during streaming with animated spinner
- ESC key cancellation of in-progress responses
- Comprehensive slash command system
- Whisper mode for side conversations
- Auto-save after each interaction
- Embedded HTTP server on port 8765 (external clients can connect)
- Tool execution progress with visual feedback
- Confirmation prompts for destructive actions (TRUSTED mode)

### 2. HTTP Server Mode

Headless multi-agent server accepting JSON-RPC 2.0 requests.

```bash
nexus --serve            # Default port 8765
nexus --serve 9000       # Custom port
nexus --serve --reload   # Auto-reload on code changes (dev)
```

Use cases:
- Automated testing
- External tool integration
- Multi-agent coordination
- Subagent communication

### 3. Client Mode

Connect to a running Nexus server as a REPL client.

```bash
nexus --connect                            # Default http://localhost:8765
nexus --connect http://server:9000         # Custom server
nexus --connect --agent worker-1           # Specific agent
```

Features:
- Interactive input/output to remote agent
- `/status` command for token/context info
- `/quit` to disconnect

### 4. RPC Commands

Programmatic commands for controlling remote agents.

```bash
# All commands accessed via `nexus rpc <command>` or `nexus-rpc <command>` alias

nexus-rpc detect                 # Check if server is running
nexus-rpc list                   # List agents (auto-starts server)
nexus-rpc create worker-1        # Create agent (auto-starts server)
nexus-rpc destroy worker-1       # Destroy agent
nexus-rpc send worker-1 "Hello"  # Send message
nexus-rpc status worker-1        # Get tokens + context
nexus-rpc cancel worker-1 42     # Cancel request
nexus-rpc shutdown               # Stop server

# Optional flags
--port 9000                      # Non-default port
--api-key nxk_...                # Explicit API key (auto-discovers if not set)
```

## CLI Arguments

### Main Flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--serve [PORT]` | int | 8765 | Run HTTP JSON-RPC server instead of REPL |
| `--connect [URL]` | str | `http://localhost:8765` | Connect to server as REPL client |
| `--agent ID` | str | `main` | Agent ID to connect to (requires `--connect`) |
| `--verbose` | flag | off | Enable verbose logging (thinking traces, timing) |
| `--raw-log` | flag | off | Enable raw API JSON logging |
| `--log-dir PATH` | Path | `.nexus3/logs` | Directory for session logs |
| `--reload` | flag | off | Auto-reload on code changes (serve mode only) |
| `--resume` | flag | off | Resume last session (skip lobby) |
| `--fresh` | flag | off | Start fresh temp session (skip lobby) |
| `--session NAME` | str | - | Load specific saved session (skip lobby) |
| `--template PATH` | Path | - | Custom system prompt file (used with --fresh) |

### RPC Subcommands

All accessed via `nexus rpc <command>`:

| Command | Arguments | Description |
|---------|-----------|-------------|
| `detect` | `[--port N]` | Check if server is running |
| `list` | `[--port N] [--api-key KEY]` | List all agents |
| `create` | `ID [--port N] [--api-key KEY]` | Create agent |
| `destroy` | `ID [--port N] [--api-key KEY]` | Destroy agent |
| `send` | `ID MSG [--port N] [--api-key KEY]` | Send message to agent |
| `status` | `ID [--port N] [--api-key KEY]` | Get tokens and context |
| `cancel` | `AGENT REQUEST_ID [--port N] [--api-key KEY]` | Cancel request |
| `shutdown` | `[--port N] [--api-key KEY]` | Shutdown server |

## Slash Commands (REPL)

### Agent Management
```
/agent              Show current agent detailed status
/agent <name>       Switch to agent (prompts to create if doesn't exist)
/agent <name> --yolo|--trusted|--sandboxed|--worker
                    Create agent with permission level and switch

/whisper <agent>    Enter whisper mode - redirect input to target
/over               Exit whisper mode, return to original agent

/list               List all active agents
/create <name>      Create agent without switching
/destroy <name>     Remove active agent from pool
/send <agent> <msg> One-shot message to another agent
/status [agent]     Get agent status (default: current)
/cancel [agent]     Cancel in-progress request
```

### Session Management
```
/save [name]        Save current session (prompts for name if temp)
/clone <src> <dest> Clone agent or saved session
/rename <old> <new> Rename agent or saved session
/delete <name>      Delete saved session from disk
```

### Configuration
```
/cwd [path]         Show or change working directory
/permissions        Show current permissions
/permissions <preset>           Change to preset
/permissions --disable <tool>   Disable a tool
/permissions --enable <tool>    Re-enable a tool
/permissions --list-tools       List tool status
/prompt [file]      Show or set system prompt
```

### REPL Control
```
/help               Show help message
/clear              Clear display (preserves context)
/quit, /exit, /q    Exit REPL
```

### Keyboard Shortcuts
```
ESC                 Cancel in-progress request
Ctrl+C              Interrupt current input
Ctrl+D              Exit REPL
```

## Data Flow

### Unified REPL (with embedded server)

```
nexus (startup)
    |
detect_server(8765)
    +-- NEXUS_SERVER --> Error: use --connect
    +-- OTHER_SERVICE --> Error: port in use
    +-- NO_SERVER:
        |
        Create SharedComponents + AgentPool
        Generate API key --> ~/.nexus3/server.key
        |
        show_lobby() --> Resume / Fresh / Select saved
        |
        Create/restore main agent
        Start HTTP server as background task
        |
        REPL loop:
            |
            prompt_session.prompt_async()
                |
                +-- Slash command --> handle_slash_command()
                |       |
                |       +-- QUIT --> cleanup + exit
                |       +-- SWITCH_AGENT --> update session/logger
                |       +-- ENTER_WHISPER --> update whisper state
                |       +-- SUCCESS/ERROR --> display message
                |
                +-- Regular message:
                        |
                    Check whisper mode --> get target session
                        |
                    StreamingDisplay.reset()
                    KeyMonitor context (ESC detection)
                        |
                    Session.send(user_input) --> async stream
                        |
                    Each chunk --> display.add_chunk()
                    Tool calls --> on_batch_start/progress/complete
                        |
                    Print final response
                    Auto-save current session
```

### HTTP Server Mode (Multi-Agent)

```
HTTP POST
    |
    +-- Missing/Invalid Authorization --> 401
    |
    +-- Path: / or /rpc
    |       |
    |       v
    |   GlobalDispatcher.dispatch()
    |       +-- "create_agent" --> AgentPool.create(preset, delta)
    |       +-- "destroy_agent" --> AgentPool.destroy()
    |       +-- "list_agents" --> AgentPool.list()
    |       +-- "shutdown_server" --> signal shutdown
    |       |
    |       v
    |   Response --> JSON --> HTTP response
    |
    +-- Path: /agent/{agent_id}
            |
            v
        AgentPool.get(agent_id)
            |
            v
        Agent.dispatcher.dispatch()
            +-- "send" --> Session.send_complete() --> full response
            +-- "cancel" --> cancel in-progress request
            +-- "get_tokens" --> context.get_token_usage()
            +-- "get_context" --> context info
            +-- "shutdown" --> mark agent for shutdown
            |
            v
        Response --> JSON --> HTTP response
```

### Client Mode

```
User Input
    |
parse local commands (/quit, /status)
    |
    +-- /quit --> disconnect
    +-- /status --> client.get_tokens() + client.get_context()
    +-- message --> client.send(content)
            |
            v
        NexusClient.send() --> HTTP POST to /agent/{agent_id}
            |
            v
        Print response content
```

## Dependencies

### Internal (nexus3 modules)

| Module | Used For |
|--------|----------|
| `nexus3.client` | `NexusClient`, `ClientError` for client/subcommands |
| `nexus3.commands.core` | Unified commands (list, create, destroy, send, etc.) |
| `nexus3.commands.protocol` | `CommandContext`, `CommandOutput`, `CommandResult` |
| `nexus3.config.loader` | `load_config()` for configuration |
| `nexus3.context` | `PromptLoader` |
| `nexus3.core.encoding` | `configure_stdio()` for UTF-8 |
| `nexus3.core.errors` | `NexusError` exception handling |
| `nexus3.core.permissions` | Permission loading and preset resolution |
| `nexus3.core.types` | `ToolCall` for confirmation callbacks |
| `nexus3.display` | `Activity`, `StreamingDisplay`, `get_console()` |
| `nexus3.display.streaming` | `ToolState` enum for tool result display |
| `nexus3.display.theme` | `load_theme()` |
| `nexus3.provider.openrouter` | `OpenRouterProvider` |
| `nexus3.rpc.auth` | `ServerKeyManager`, `discover_api_key` |
| `nexus3.rpc.detection` | `detect_server`, `DetectionResult`, `wait_for_server` |
| `nexus3.rpc.global_dispatcher` | `GlobalDispatcher` |
| `nexus3.rpc.http` | `run_http_server()`, `DEFAULT_PORT` |
| `nexus3.rpc.pool` | `AgentPool`, `SharedComponents`, `AgentConfig`, `generate_temp_id` |
| `nexus3.session` | `LogStream`, `SessionManager` |
| `nexus3.session.persistence` | `SavedSession`, serialization functions |

### External

| Package | Used For |
|---------|----------|
| `prompt_toolkit` | `PromptSession` for interactive input with toolbar, `HTML` for formatting, `Style` |
| `rich` | `Console`, `Live` display, styling |
| `dotenv` | `.env` file loading via `load_dotenv()` |
| `watchfiles` | Auto-reload on code changes (optional, for `--reload` flag) |

## Usage Examples

### Interactive Session

```bash
# Start REPL (shows lobby)
nexus

# Skip lobby, resume last session
nexus --resume

# Skip lobby, start fresh
nexus --fresh

# Skip lobby, load specific session
nexus --session my-project

# Fresh session with custom prompt
nexus --fresh --template ./custom-prompt.md

# With verbose logging
nexus --verbose

# With raw API logging
nexus --raw-log

# Custom log directory
nexus --log-dir ./my-logs
```

### HTTP Server

```bash
# Start headless server
nexus --serve

# Custom port
nexus --serve 9000

# With auto-reload for development
nexus --serve --reload
```

#### Agent Management (GlobalDispatcher)

```bash
# Create an agent
curl -X POST http://localhost:8765 \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer nxk_..." \
    -d '{"jsonrpc":"2.0","method":"create_agent","params":{},"id":1}'

# Create agent with permission preset
curl -X POST http://localhost:8765 \
    -H "Authorization: Bearer nxk_..." \
    -d '{"jsonrpc":"2.0","method":"create_agent","params":{"agent_id":"worker-1","preset":"sandboxed"},"id":2}'

# List all agents
curl -X POST http://localhost:8765 \
    -H "Authorization: Bearer nxk_..." \
    -d '{"jsonrpc":"2.0","method":"list_agents","id":3}'

# Destroy an agent
curl -X POST http://localhost:8765 \
    -H "Authorization: Bearer nxk_..." \
    -d '{"jsonrpc":"2.0","method":"destroy_agent","params":{"agent_id":"main"},"id":4}'

# Shutdown server
curl -X POST http://localhost:8765 \
    -H "Authorization: Bearer nxk_..." \
    -d '{"jsonrpc":"2.0","method":"shutdown_server","id":5}'
```

#### Agent Operations (Per-Agent Dispatcher)

```bash
# Send a message
curl -X POST http://localhost:8765/agent/main \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer nxk_..." \
    -d '{"jsonrpc":"2.0","method":"send","params":{"content":"Hello"},"id":1}'

# Check token usage
curl -X POST http://localhost:8765/agent/main \
    -H "Authorization: Bearer nxk_..." \
    -d '{"jsonrpc":"2.0","method":"get_tokens","id":3}'

# Get context info
curl -X POST http://localhost:8765/agent/main \
    -H "Authorization: Bearer nxk_..." \
    -d '{"jsonrpc":"2.0","method":"get_context","id":4}'
```

### Client Mode

```bash
# Connect to default server
nexus --connect

# Connect to custom server
nexus --connect http://server:9000

# Connect to specific agent
nexus --connect --agent worker-1

# Inside client REPL:
> Hello!                # Send message to agent
> /status               # Show tokens and context
> /quit                 # Disconnect
```

### RPC Commands

```bash
# Check if server is running
nexus-rpc detect

# List agents (auto-starts server if needed)
nexus-rpc list

# Create an agent
nexus-rpc create worker-1

# Send message
nexus-rpc send worker-1 "What is 2+2?"

# Get agent status
nexus-rpc status worker-1

# Cancel a request
nexus-rpc cancel worker-1 42

# Shutdown server
nexus-rpc shutdown

# With custom port
nexus-rpc --port 9000 list
```

### ESC Cancellation

During a streaming response, press ESC to:

1. Cancel the HTTP request to the provider
2. Stop the streaming display
3. Show "Cancelled by User" status
4. Mark pending tools as cancelled
5. Return to the input prompt immediately

Note: ESC cancellation only works on Unix systems. Windows falls back to completing the request normally.

## Architecture Notes

### Unified Mode

The default REPL mode (no `--serve` or `--connect` flags) runs in "unified mode":

1. Detects if a server is already running on the port
2. If running: Errors with suggestion to use `--connect`
3. If not: Starts embedded HTTP server as background task
4. REPL calls Session directly for rich streaming display
5. External clients can connect via HTTP on the same port
6. API key is generated and saved to `~/.nexus3/server.key`

This allows both interactive use and programmatic access to the same agent pool.

### Server Architecture

The HTTP server uses a two-tier dispatcher architecture:

1. **GlobalDispatcher** - Handles requests to `/` or `/rpc`
   - `create_agent`: Create new agent in pool (with preset/delta)
   - `destroy_agent`: Remove agent from pool
   - `list_agents`: List all agents with status
   - `shutdown_server`: Graceful server shutdown

2. **Per-Agent Dispatchers** - Handle requests to `/agent/{agent_id}`
   - `send`: Send message and get response
   - `cancel`: Cancel in-progress request
   - `get_tokens`: Get token usage
   - `get_context`: Get context info
   - `shutdown`: Request agent shutdown

### SharedComponents

Resources shared across all agents:
- **config**: Global NEXUS3 configuration
- **provider**: LLM provider (shared for connection pooling)
- **prompt_loader**: System prompt loader
- **base_log_dir**: Base directory for logs (agents get subdirectories)
- **log_streams**: Active logging streams (CONTEXT, VERBOSE, RAW)
- **custom_presets**: User-defined permission presets from config

### AgentPool

Manages agent lifecycle:
- Thread-safe with asyncio.Lock
- Each agent gets isolated context, logger, skills, session, services
- Agents share the provider for efficiency
- Tracks shutdown state across all agents
- Supports permission presets and deltas on creation
- Can restore agents from saved sessions

### Session Manager

Manages session persistence:
- `~/.nexus3/sessions/` directory for saved sessions
- `last-session.json` tracks most recent session for resume
- Sessions include messages, system prompt, permissions, token usage
- Auto-save after each REPL interaction

### Permission Integration

The CLI integrates with the permission system:
- `confirm_tool_action()` callback prompts for destructive actions (TRUSTED mode)
- `/permissions` command shows and modifies agent permissions
- `/agent <name> --sandboxed` creates agents with specific presets
- Permissions are saved/restored with sessions
