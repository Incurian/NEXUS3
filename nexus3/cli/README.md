# CLI Module

The command-line interface for NEXUS3, providing both interactive REPL and HTTP server modes.

## Purpose

This module is the primary user-facing interface for NEXUS3. It handles:

- Interactive REPL sessions with streaming response display
- HTTP JSON-RPC server mode for automation and programmatic control
- User input processing and slash commands
- ESC key cancellation during streaming operations
- Session initialization and lifecycle management
- Skill registration and tool definitions injection
- Auto-reload during development (server mode)

## Files

### `repl.py` - Main Entry Point and Interactive REPL

The primary CLI entry point that handles both REPL and server mode routing.

| Function | Description |
|----------|-------------|
| `main()` | Entry point for CLI, routes to REPL or HTTP server based on `--serve` flag |
| `run_repl()` | Async REPL loop with prompt-toolkit input and Rich.Live streaming display |
| `parse_args()` | Argument parser for `--serve`, `--verbose`, `--raw-log`, `--log-dir`, `--reload` |
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

### `serve.py` - HTTP JSON-RPC Server

Runs NEXUS3 as an HTTP server accepting JSON-RPC 2.0 requests.

| Function | Description |
|----------|-------------|
| `run_serve(port, verbose, raw_log, log_dir)` | Async function that starts HTTP JSON-RPC server |

Key responsibilities:
- Same initialization as REPL (config, provider, logger, context, skills)
- Uses `mode="serve"` in `LogConfig` to differentiate from REPL sessions
- Loads system prompt with `is_repl=False` for server-appropriate prompt
- Creates `Dispatcher` for JSON-RPC method routing
- Runs `run_http_server()` from `nexus3.rpc.http`
- Maintains session context across multiple requests (multi-turn conversations)

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

The code includes placeholder comments for future commands (`/help`, `/clear`).

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

## Entry Points

### Interactive REPL (default)

```bash
python -m nexus3
```

Features:
- prompt-toolkit input with persistent bottom toolbar showing status
- Rich.Live display during streaming with animated spinner
- ESC key cancellation of in-progress responses
- Gumball status indicators (ready/error states)

### HTTP Server Mode

```bash
python -m nexus3 --serve         # Default port 8765
python -m nexus3 --serve 9000    # Custom port
```

Accepts JSON-RPC 2.0 POST requests. Use cases:
- Automated testing
- External tool integration (e.g., Claude Code)
- Subagent communication
- Multi-turn programmatic conversations (server maintains session context)

## CLI Arguments

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--serve [PORT]` | int | 8765 | Run HTTP JSON-RPC server instead of REPL |
| `--verbose` | flag | off | Enable verbose logging (thinking traces, timing) |
| `--raw-log` | flag | off | Enable raw API request/response logging |
| `--log-dir PATH` | Path | `.nexus3/logs` | Directory for session logs |
| `--reload` | flag | off | Auto-reload on code changes (serve mode only, requires watchfiles) |

## Data Flow

### Interactive REPL

```
User Input
    ↓
parse_command()
    ├── Slash command → handle_command() → QUIT/HANDLED/UNKNOWN
    │
    └── Regular message:
            ↓
        StreamingDisplay.reset() / clear_error_state() / clear_thinking_duration()
        StreamingDisplay.set_activity(WAITING)
        StreamingDisplay.start_activity_timer()
            ↓
        KeyMonitor context (background ESC detection)
            ↓
        Session.send(user_input) → async stream chunks
            ↓
        Each chunk:
          - Activity changes WAITING → RESPONDING on first chunk
          - StreamingDisplay.add_chunk()
          - Rich.Live refreshes (animated spinner + response text)
            ↓
        Tool calls detected:
          - on_reasoning() callback tracks thinking start/end
          - on_batch_start() initializes tool display (all tools pending)
          - on_tool_active() marks each tool as running
          - on_batch_progress() updates completion status per tool
          - on_batch_halt() marks remaining tools halted on error
          - on_batch_complete() prints results to scrollback
            ↓
        Stream complete:
          - Live context exits
          - Thinking duration printed (if any)
          - Final response printed to console
          - Cancelled status if ESC was pressed
          - Cancelled tools queued for next send
```

### HTTP Server Mode

```
HTTP POST (JSON-RPC request body)
    ↓
run_http_server() receives connection
    ↓
parse_request() → Request object
    ↓
Dispatcher.dispatch()
    ├── "send" → Session.send_complete() → full response
    ├── "get_tokens" → context.get_token_usage()
    ├── "get_context" → context.get_messages()
    ├── "compact" → context.compact()
    └── "shutdown" → server stops
    ↓
Response object → JSON
    ↓
HTTP response to client
```

## Dependencies

### Internal (nexus3 modules)

| Module | Used For |
|--------|----------|
| `nexus3.config.loader` | `load_config()` for configuration |
| `nexus3.context` | `ContextConfig`, `ContextManager`, `PromptLoader` |
| `nexus3.core.encoding` | `configure_stdio()` for UTF-8 |
| `nexus3.core.errors` | `NexusError` exception handling |
| `nexus3.display` | `Activity`, `StreamingDisplay`, `get_console()` |
| `nexus3.display.streaming` | `ToolState` enum for tool result display |
| `nexus3.display.theme` | `load_theme()` |
| `nexus3.provider.openrouter` | `OpenRouterProvider` |
| `nexus3.session` | `Session`, `SessionLogger`, `LogConfig`, `LogStream` |
| `nexus3.skill` | `ServiceContainer`, `SkillRegistry` |
| `nexus3.skill.builtin` | `register_builtin_skills()` |
| `nexus3.rpc` | `Dispatcher` (HTTP server mode) |
| `nexus3.rpc.http` | `run_http_server()`, `DEFAULT_PORT` (HTTP server mode) |

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

# Send a message
curl -X POST http://localhost:8765 \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","method":"send","params":{"content":"Hello"},"id":1}'

# Multi-turn conversation (server maintains context)
curl -X POST http://localhost:8765 \
    -d '{"jsonrpc":"2.0","method":"send","params":{"content":"My name is Alice"},"id":1}'
curl -X POST http://localhost:8765 \
    -d '{"jsonrpc":"2.0","method":"send","params":{"content":"What is my name?"},"id":2}'

# Check token usage
curl -X POST http://localhost:8765 \
    -d '{"jsonrpc":"2.0","method":"get_tokens","id":3}'

# Shutdown the server gracefully
curl -X POST http://localhost:8765 \
    -d '{"jsonrpc":"2.0","method":"shutdown","id":4}'
```

### Slash Commands

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
4. Return to the input prompt immediately

Note: ESC cancellation only works on Unix systems. Windows falls back to completing the request normally.