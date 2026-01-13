# CLI Module

The command-line interface for NEXUS3, providing interactive REPL, HTTP server, client, and RPC modes.

## Purpose

Primary user-facing interface handling:
- **Unified REPL** (default): Interactive session with embedded HTTP server for multi-client access
- **HTTP Server Mode** (`--serve`): Headless multi-agent JSON-RPC server
- **Client Mode** (`--connect`): REPL connected to remote server
- **RPC Commands** (`nexus rpc`): Programmatic control of remote agents

Key features:
- `prompt-toolkit` REPL with bottom toolbar (status, tokens)
- Rich streaming display with spinners, tool progress, ESC cancellation (Unix)
- Lobby mode for session selection on startup
- Whisper mode for side conversations with agents
- MCP (external tool servers) integration with consent prompts
- Session persistence/auto-save (`~/.nexus3/sessions/`)
- Permission system with presets, tool enable/disable, confirmations
- Model switching with context checks
- Auto-reload in dev (`--reload --serve`)

## Files

| File | Description |
|------|-------------|
| `__init__.py` | Exports `main()` from `repl.py` |
| `client_commands.py` | RPC CLI wrappers (`nexus rpc ...`): `detect`, `list`, `create`, `destroy`, `send`, `cancel`, `status`, `shutdown` |
| `commands.py` | Legacy basic slash parsing (`/quit` only, superseded) |
| `keys.py` | `KeyMonitor`: ESC detection during streaming (Unix `termios/select`) |
| `lobby.py` | Lobby UI: resume/fresh/select saved sessions |
| `repl.py` | Main entry: arg parsing, unified REPL, client REPL, callbacks, slash routing |
| `repl_commands.py` | REPL slash handlers: `/agent`, `/whisper`, `/over`, `/cwd`, `/permissions`, `/prompt`, `/help`, `/clear`, `/quit`, `/compact`, `/model`, `/mcp` |
| `serve.py` | Headless server: `SharedComponents`, `AgentPool`, dispatchers |
| `whisper.py` | `WhisperMode`: state for side-agent conversations |

## CLI Modes

### 1. Unified REPL (default: `nexus`)

Embedded HTTP server + direct `Session` calls for rich display.

```bash
nexus                    # Lobby → resume/fresh/select
nexus --fresh            # Fresh temp session (skip lobby)
nexus --resume           # Resume last session
nexus --session myproj   # Load saved session
nexus --template FILE    # Custom prompt (--fresh)
nexus --model alias      # Startup model
```

- Auto-connects if server on port (suggests kill/restart).
- Toolbar: `■ ● ready | 1,234 / 128,000`
- ESC: Cancel stream/tools (Unix).
- Auto-save after each turn.
- If server running: connects as client.

### 2. HTTP Server (`--serve`)

Headless JSON-RPC 2.0 multi-agent server.

```bash
nexus --serve            # Port 8765
nexus --serve 9000       # Custom port
nexus --serve --reload   # Dev auto-reload (watchfiles)
```

Endpoints:
- `POST /` or `/rpc`: Global (`create_agent`, `destroy_agent`, `list_agents`, `shutdown_server`)
- `POST /agent/{id}`: Agent ops (`send`, `cancel`, `get_tokens`, `get_context`)
- `Authorization: Bearer nxk_...` (auto-generated `~/.nexus3/server.{port}.key`)

### 3. Client REPL (`--connect`)

Interactive client to remote server.

```bash
nexus --connect                  # localhost:8765/agent/main
nexus --connect http://host:9000 --agent worker-1
```

Commands: `/status`, `/quit`.

### 4. RPC Commands (`nexus rpc` or `nexus-rpc`)

JSON stdout, exit codes. Some auto-start server.

```bash
nexus rpc detect [--port 9000]
nexus rpc list [--port] [--api-key]
nexus rpc create ID [--preset sandboxed] [--cwd PATH] [--write-path PATH...] [--model NAME] [--port] [--api-key]
nexus rpc destroy ID [--port] [--api-key]
nexus rpc send ID "msg" [--timeout 120] [--port] [--api-key]
nexus rpc cancel ID REQ_ID [--port] [--api-key]
nexus rpc status ID [--port] [--api-key]
nexus rpc shutdown [--port] [--api-key]
```

## CLI Flags

| Flag | Description |
|------|-------------|
| `--serve [PORT]` | Headless server (8765) |
| `--connect [URL]` | Client REPL (http://localhost:8765) |
| `--agent ID` | Target agent (--connect, default: main) |
| `--verbose` | Thinking traces/timing |
| `--raw-log` | Raw API JSON logs |
| `--log-dir PATH` | Logs dir (.nexus3/logs) |
| `--reload` | Auto-reload (--serve dev) |
| `--resume` | Skip lobby: last session |
| `--fresh` | Skip lobby: temp session |
| `--session NAME` | Skip lobby: load session |
| `--template PATH` | Custom prompt (--fresh) |
| `--model NAME` | Model alias/ID |

**RPC flags**: `--port`, `--api-key` (auto-discover).

## Lobby Mode

Startup screen (unless `--resume`/`--fresh`/`--session`):

```
NEXUS3 REPL

  1) Resume: my-project (2h ago, 45 messages)
  2) Fresh session
  3) Choose from saved...

[1/2/3/q]:
```

- Select → detailed list.
- `q`: Quit.

## Slash Commands (Unified REPL/Client)

### Agent Mgmt
```
/agent                 # Status
/agent <name> [--yolo|--trusted|--sandboxed]  # Switch/create
/whisper <agent>       # Side convo (/over to return)
/over                  # Exit whisper
/list                  # Agents
/create <name>         # Create
/destroy <name>        # Destroy
/send <agent> <msg>    # One-shot
/status [<agent>]      # Tokens/context
/cancel [<agent>] [<id>]  # Cancel req
/shutdown              # Stop server
```

### Sessions
```
/save [<name>]         # Save (prompt if temp)
/clone <src> <dest>    # Clone agent/session
/rename <old> <new>    # Rename
/delete <name>         # Delete saved
```

### Config
```
/cwd [<path>]          # Show/set dir
/permissions           # Show
/permissions <preset>  # Change preset
/permissions --list-tools  # Tool status
/permissions --disable|--enable <tool>  # Toggle tool
/prompt [<file>]       # Show/set prompt
/model                 # Show model
/model <alias>         # Switch (checks context size)
/compact               # Summarize old msgs
```

### MCP (External Tools)
```
/mcp                          # List servers
/mcp connect <name> [--allow-all|--per-tool] [--shared|--private]  # Connect+prompts
/mcp disconnect <name>        # Disconnect (owner only)
/mcp tools [<server>]         # List tools
```

- Prompts: allow-all/per-tool, share/private.
- YOLO: auto-allow/private.
- Shared: visible to all agents (they approve tools).

### REPL
```
/help    # This list
/clear   # Clear screen (keep context)
/quit /q # Exit
```

**Keyboard**: ESC (cancel, Unix), Ctrl+C (input), Ctrl+D (quit).

## Whisper Mode

Persistent redirection:
```
/whisper worker-1
worker-1> hello
[stream...]
worker-1> /over
→ main>
```

- Prompt shows target.
- State preserved across turns.

## Confirmation Prompts

Destructive tools (TRUSTED/YOLO):

**Write** (`write_file/edit_file`):
```
Allow write_file?
Path: /foo/bar.txt
[1] Allow once [2] Allow file [3] Allow dir [4] Deny
```

**Exec** (`bash/run_python`):
```
Execute bash?
Command: ls -la
Directory: /cwd
[1] once [2] dir [3] global [4] Deny
```

**MCP/Nexus**: Similar, tailored.

## Data Flow: Unified REPL

```
Startup → detect_server()
  → NO_SERVER: SharedComponents + AgentPool("main") + HTTP task + API key
  → Lobby/CLI flags → create/restore agent → wire callbacks → REPL loop

Loop:
  input → slash? → handle → switch/whisper/save/etc.
  → else: target_session.send(input)
    → Live(StreamingDisplay) + KeyMonitor(ESC)
    → chunks → add_chunk() + tool callbacks (reasoning/batch)
    → final → print + auto-save
```

## Usage Examples

### REPL
```bash
nexus --fresh --model claude-3.5-sonnet
/whisper worker-1
/mcp connect my-server --allow-all --shared
```

### Server + RPC
```bash
nexus --serve 9000  # PID, key file printed
nexus rpc --port 9000 create worker-1 --preset sandboxed --cwd /proj
nexus rpc --port 9000 send worker-1 "Hello"
```

### Curl
```bash
curl -H "Authorization: Bearer $(cat ~/.nexus3/server.8765.key)" \
  -d '{"jsonrpc":"2.0","method":"create_agent","params":{"agent_id":"foo"},"id":1}' \
  http://localhost:8765
```

## Dependencies

**Internal**: `nexus3.client`, `commands.*`, `config`, `context`, `core.*`, `display.*`, `provider.openrouter`, `rpc.*`, `session.*`.

**External**: `prompt_toolkit`, `rich`, `dotenv`, `watchfiles` (dev).

Version: Compatible with NEXUS3 v0.1.0+