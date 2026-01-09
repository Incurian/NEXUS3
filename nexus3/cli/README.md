# CLI Module

The command-line interface for NEXUS3, providing interactive REPL, HTTP server, and client modes.

## Purpose

This module is the primary user-facing interface for NEXUS3. It handles:

- **Standalone REPL** - Interactive sessions with streaming response display
- **HTTP Server Mode** - Multi-agent JSON-RPC server for automation and programmatic control
- **Client Mode** - REPL connected to a remote Nexus server
- **CLI Commands** - Standalone commands for controlling remote agents

Key features:
- User input processing and slash commands
- ESC key cancellation during streaming operations
- Session initialization and lifecycle management
- Skill registration and tool definitions injection
- Auto-reload during development (server mode)

## Files

### `repl.py` - Main Entry Point and Interactive REPL

The primary CLI entry point that routes to different modes based on arguments.

| Function | Description |
|----------|-------------|
| `main()` | Entry point for CLI, routes to REPL, server, client, or subcommand |
| `parse_args()` | Argument parser for all CLI flags and subcommands |
| `run_repl()` | Async REPL loop with prompt-toolkit input and Rich.Live streaming |
| `run_repl_client()` | Async REPL as client to remote Nexus server |
| `_run_with_reload()` | Runs server with watchfiles auto-reload on code changes |

Key responsibilities:
- Loads configuration via `load_config()`
- Creates `OpenRouterProvider` for LLM access
- Initializes `SessionLogger` with all log streams enabled by default
- Wires raw logging callback to provider for API request/response capture
- Loads system prompt via `PromptLoader` (layered personal + project prompts)
- Creates `ContextManager` for conversation history and token tracking
- Registers built-in skills via `SkillRegistry` and injects tool definitions
- Manages the interactive prompt-toolkit session with bottom toolbar
- Coordinates `Rich.Live` display during streaming with `KeyMonitor` for ESC cancellation
- Handles tool execution callbacks (batch start, tool active, progress, halt, complete)
- Tracks thinking duration and displays it before tool calls or response
- Manages cancelled tool state for next send

### `serve.py` - HTTP JSON-RPC Multi-Agent Server

Runs NEXUS3 as an HTTP server with multi-agent support via AgentPool.

| Function | Description |
|----------|-------------|
| `run_serve(port, verbose, raw_log, log_dir)` | Async function that starts multi-agent HTTP server |

Architecture:
- **SharedComponents** - Immutable resources shared across all agents (config, provider, prompt_loader)
- **AgentPool** - Manages agent lifecycle (create, destroy, list, get)
- **GlobalDispatcher** - Handles agent management RPC methods (create_agent, destroy_agent, list_agents)
- **Per-agent Dispatcher** - Handles agent-specific RPC methods (send, cancel, get_tokens, etc.)

Key responsibilities:
- Creates `SharedComponents` with config, provider, prompt loader
- Creates `AgentPool` for managing multiple agent instances
- Creates `GlobalDispatcher` for agent lifecycle management
- Runs `run_http_server()` with path-based routing
- Cleans up all agents on shutdown

Protocol:
- `POST /` or `POST /rpc` - Routes to GlobalDispatcher (agent management)
- `POST /agent/{agent_id}` - Routes to agent's Dispatcher (agent operations)

### `client_commands.py` - CLI Commands for Remote Agents

Thin wrappers around `NexusClient` for command-line use. Each function prints JSON to stdout and returns an exit code.

| Function | Description |
|----------|-------------|
| `cmd_send(url, content, request_id)` | Send a message to an agent |
| `cmd_cancel(url, request_id)` | Cancel an in-progress request |
| `cmd_status(url)` | Get tokens and context info from agent |
| `cmd_shutdown(url)` | Request graceful agent shutdown |

### `commands.py` - Slash Command Handling

Parses and handles slash commands (input starting with `/`).

| Type | Description |
|------|-------------|
| `Command` | Dataclass with `name: str` and `args: str` fields |
| `CommandResult` | Enum: `QUIT`, `HANDLED`, `UNKNOWN` |
| `parse_command(user_input)` | Returns `Command` if input starts with `/`, else `None` |
| `handle_command(command)` | Executes command and returns `CommandResult` |

Currently supported commands:
- `/quit`, `/exit`, `/q` - Exit the REPL

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

### `output.py` - Legacy Output Utilities

Simple Rich-based output utilities. Largely superseded by `display` module.

| Function | Description |
|----------|-------------|
| `console` | Shared `rich.console.Console` instance |
| `print_streaming(chunks)` | Streams async chunks to console (legacy) |
| `print_error(message)` | Prints error in red bold |
| `print_info(message)` | Prints message in dim style |

Note: The REPL now uses `StreamingDisplay` from `nexus3.display` instead of these functions.

### `__init__.py` - Module Exports

Exports only `main` from `repl.py`.

## CLI Modes

### 1. Standalone REPL (default)

Interactive mode for direct conversation with the AI.

```bash
python -m nexus3
```

Features:
- prompt-toolkit input with persistent bottom toolbar showing status
- Rich.Live display during streaming with animated spinner
- ESC key cancellation of in-progress responses
- Gumball status indicators (ready/error states)
- Tool execution progress with visual feedback

### 2. HTTP Server Mode

Multi-agent server accepting JSON-RPC 2.0 requests.

```bash
python -m nexus3 --serve         # Default port 8765
python -m nexus3 --serve 9000    # Custom port
```

Use cases:
- Automated testing
- External tool integration (e.g., Claude Code)
- Multi-agent coordination
- Subagent communication

### 3. Client Mode (REPL to Remote Server)

Connect to a running Nexus server as a REPL client.

```bash
python -m nexus3 --connect                           # Default http://localhost:8765
python -m nexus3 --connect http://server:9000        # Custom server
python -m nexus3 --connect --agent worker-1          # Specific agent
```

Features:
- Interactive input/output to remote agent
- `/status` command for token/context info
- `/quit` to disconnect

### 4. CLI Subcommands

One-shot commands for controlling remote agents.

```bash
# Send a message
python -m nexus3 send http://localhost:8765/agent/main "Hello"

# Cancel in-progress request
python -m nexus3 cancel http://localhost:8765/agent/main 42

# Get agent status
python -m nexus3 status http://localhost:8765/agent/main

# Request shutdown
python -m nexus3 shutdown http://localhost:8765/agent/main
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

### Subcommands

| Command | Arguments | Description |
|---------|-----------|-------------|
| `send` | `URL CONTENT [--request-id ID]` | Send message to agent |
| `cancel` | `URL REQUEST_ID` | Cancel in-progress request |
| `status` | `URL` | Get tokens and context info |
| `shutdown` | `URL` | Request graceful shutdown |

## Data Flow

### Interactive REPL

```
User Input
    |
parse_command()
    +-- Slash command --> handle_command() --> QUIT/HANDLED/UNKNOWN
    |
    +-- Regular message:
            |
        StreamingDisplay.reset() / clear_error_state() / clear_thinking_duration()
        StreamingDisplay.set_activity(WAITING)
        StreamingDisplay.start_activity_timer()
            |
        KeyMonitor context (background ESC detection)
            |
        Session.send(user_input) --> async stream chunks
            |
        Each chunk:
          - Activity changes WAITING --> RESPONDING on first chunk
          - StreamingDisplay.add_chunk()
          - Rich.Live refreshes (animated spinner + response text)
            |
        Tool calls detected:
          - on_reasoning() callback tracks thinking start/end
          - on_batch_start() initializes tool display (all tools pending)
          - on_tool_active() marks each tool as running
          - on_batch_progress() updates completion status per tool
          - on_batch_halt() marks remaining tools halted on error
          - on_batch_complete() prints results to scrollback
            |
        Stream complete:
          - Live context exits
          - Thinking duration printed (if any)
          - Final response printed to console
          - Cancelled status if ESC was pressed
          - Cancelled tools queued for next send
```

### HTTP Server Mode (Multi-Agent)

```
HTTP POST
    |
    +-- Path: / or /rpc
    |       |
    |       v
    |   GlobalDispatcher.dispatch()
    |       +-- "create_agent" --> AgentPool.create() --> new agent
    |       +-- "destroy_agent" --> AgentPool.destroy()
    |       +-- "list_agents" --> AgentPool.list()
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
| `nexus3.config.loader` | `load_config()` for configuration |
| `nexus3.context` | `ContextConfig`, `ContextManager`, `PromptLoader` |
| `nexus3.core.encoding` | `configure_stdio()` for UTF-8 |
| `nexus3.core.errors` | `NexusError` exception handling |
| `nexus3.display` | `Activity`, `StreamingDisplay`, `get_console()` |
| `nexus3.display.streaming` | `ToolState` enum for tool result display |
| `nexus3.display.theme` | `load_theme()` |
| `nexus3.provider.openrouter` | `OpenRouterProvider` |
| `nexus3.rpc` | `Dispatcher`, `GlobalDispatcher` |
| `nexus3.rpc.http` | `run_http_server()`, `DEFAULT_PORT` |
| `nexus3.rpc.pool` | `AgentPool`, `SharedComponents` |
| `nexus3.session` | `Session`, `SessionLogger`, `LogConfig`, `LogStream` |
| `nexus3.skill` | `ServiceContainer`, `SkillRegistry` |
| `nexus3.skill.builtin` | `register_builtin_skills()` |

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
# Start REPL
python -m nexus3

# With verbose logging (thinking traces, timing)
python -m nexus3 --verbose

# With raw API logging
python -m nexus3 --raw-log

# Custom log directory
python -m nexus3 --log-dir ./my-logs

# Combine options
python -m nexus3 --verbose --raw-log --log-dir ./debug-logs
```

### HTTP Server

```bash
# Start the server
python -m nexus3 --serve

# Start with auto-reload for development
python -m nexus3 --serve --reload

# Custom port
python -m nexus3 --serve 9000
```

#### Agent Management (GlobalDispatcher)

```bash
# Create an agent
curl -X POST http://localhost:8765 \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","method":"create_agent","params":{},"id":1}'

# Response: {"jsonrpc":"2.0","result":{"agent_id":"a1b2c3d4","url":"/agent/a1b2c3d4"},"id":1}

# Create agent with specific ID
curl -X POST http://localhost:8765 \
    -d '{"jsonrpc":"2.0","method":"create_agent","params":{"agent_id":"main"},"id":2}'

# List all agents
curl -X POST http://localhost:8765 \
    -d '{"jsonrpc":"2.0","method":"list_agents","id":3}'

# Destroy an agent
curl -X POST http://localhost:8765 \
    -d '{"jsonrpc":"2.0","method":"destroy_agent","params":{"agent_id":"main"},"id":4}'
```

#### Agent Operations (Per-Agent Dispatcher)

```bash
# Send a message to an agent
curl -X POST http://localhost:8765/agent/main \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","method":"send","params":{"content":"Hello"},"id":1}'

# Multi-turn conversation (server maintains context)
curl -X POST http://localhost:8765/agent/main \
    -d '{"jsonrpc":"2.0","method":"send","params":{"content":"My name is Alice"},"id":1}'
curl -X POST http://localhost:8765/agent/main \
    -d '{"jsonrpc":"2.0","method":"send","params":{"content":"What is my name?"},"id":2}'

# Check token usage
curl -X POST http://localhost:8765/agent/main \
    -d '{"jsonrpc":"2.0","method":"get_tokens","id":3}'

# Get context info
curl -X POST http://localhost:8765/agent/main \
    -d '{"jsonrpc":"2.0","method":"get_context","id":4}'

# Request agent shutdown
curl -X POST http://localhost:8765/agent/main \
    -d '{"jsonrpc":"2.0","method":"shutdown","id":5}'
```

### Client Mode

```bash
# Connect to default server
python -m nexus3 --connect

# Connect to custom server
python -m nexus3 --connect http://server:9000

# Connect to specific agent
python -m nexus3 --connect --agent worker-1

# Inside client REPL:
> Hello!                # Send message to agent
> /status               # Show tokens and context
> /quit                 # Disconnect
```

### CLI Subcommands

```bash
# Send message and get JSON response
python -m nexus3 send http://localhost:8765/agent/main "What is 2+2?"

# With request ID for tracking
python -m nexus3 send http://localhost:8765/agent/main "Hello" --request-id 42

# Cancel a request
python -m nexus3 cancel http://localhost:8765/agent/main 42

# Get agent status (tokens + context)
python -m nexus3 status http://localhost:8765/agent/main

# Shutdown agent gracefully
python -m nexus3 shutdown http://localhost:8765/agent/main
```

### Slash Commands (REPL)

```
> /quit          # Exit the REPL
> /q             # Same as /quit
> /exit          # Same as /quit
> /unknown       # Shows "Unknown command" error
> Hello world    # Sent to the model
```

### ESC Cancellation

During a streaming response, press ESC to:

1. Cancel the HTTP request to the provider
2. Stop the streaming display
3. Show "Cancelled" status with yellow gumball
4. Mark pending tools as cancelled
5. Return to the input prompt immediately

Note: ESC cancellation only works on Unix systems. Windows falls back to completing the request normally.

## Architecture Notes

### Server Architecture

The HTTP server uses a two-tier dispatcher architecture:

1. **GlobalDispatcher** - Handles requests to `/` or `/rpc`
   - `create_agent`: Create new agent in pool
   - `destroy_agent`: Remove agent from pool
   - `list_agents`: List all agents with status

2. **Per-Agent Dispatchers** - Handle requests to `/agent/{agent_id}`
   - `send`: Send message and get response
   - `cancel`: Cancel in-progress request
   - `get_tokens`: Get token usage
   - `get_context`: Get context info
   - `shutdown`: Request graceful shutdown

### SharedComponents

Resources shared across all agents:
- **config**: Global NEXUS3 configuration
- **provider**: LLM provider (shared for connection pooling)
- **prompt_loader**: System prompt loader
- **base_log_dir**: Base directory for logs (agents get subdirectories)

### AgentPool

Manages agent lifecycle:
- Thread-safe with asyncio.Lock
- Each agent gets isolated context, logger, skills, session
- Agents share the provider for efficiency
- Tracks shutdown state across all agents

### NexusClient

Python client for JSON-RPC:
- Context manager pattern (`async with`)
- Connection pooling via httpx
- Automatic request ID generation
- Error handling with `ClientError`
