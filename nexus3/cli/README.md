# NEXUS3 CLI Module

## Purpose

The `nexus3.cli` module provides the complete command-line interface (CLI) for the NEXUS3 AI agent framework. It enables:

- **Interactive REPL**: Rich, streaming UI with prompt-toolkit, Rich live displays, bottom toolbar (tokens/ready state), ESC cancel, session persistence/lobby, whisper mode for multi-agent switching, slash commands for agent/model/permissions/MCP management.
- **Multi-Agent Support**: Create/switch/destroy agents, whisper mode (`/whisper &lt;id&gt;` → `/over`), session save/restore/clone.
- **Headless JSON-RPC Server**: `--serve` for programmatic HTTP access (requires `NEXUS_DEV=1`).
- **RPC Client**: `nexus3 rpc` subcommands (detect/list/create/send/status/cancel/shutdown) with JSON output.
- **Configuration**: `--init-global`/local for `~/.nexus3/` or `./.nexus3/`, model switching, permission presets (yolo/trusted/sandboxed), MCP tool integration.
- **Security**: No auto-start servers in RPC, confirmation prompts for tools, path sandboxing, idle timeouts.

Default port: 8765. Unified REPL auto-starts embedded server if none running.

## Dependencies

**Runtime** (from imports):
- `asyncio`, `rich`, `prompt-toolkit`, `pathlib`, `dotenv`.
- NEXUS3 core: `nexus3.config`, `nexus3.context`, `nexus3.provider`, `nexus3.rpc`, `nexus3.session`, `nexus3.commands`.
- Optional: `watchfiles` (`--reload`).

**Python**: 3.11+ (async/typing).

## Key Modules & Classes/Functions

| Module              | Purpose                          | Key Exports |
|---------------------|----------------------------------|-------------|
| `__init__.py`       | Entry point                      | `main()` |
| `arg_parser.py`     | CLI argument parsing             | `parse_args()` |
| `client_commands.py`| RPC CLI (`nexus3 rpc`)           | `cmd_detect()`, `cmd_list()`, `cmd_create()`, etc. |
| `confirmation_ui.py`| Tool confirmation UI             | `confirm_tool_action()`, `format_tool_params()` |
| `init_commands.py`  | Config init                      | `init_global()`, `init_local()` |
| `keys.py`           | ESC key monitoring               | `KeyMonitor` |
| `live_state.py`     | Shared Live display state        | `_current_live` ContextVar |
| `lobby.py`          | Session lobby UI                 | `show_lobby()` → `LobbyResult` |
| `repl.py`           | Core REPL (~55K LoC)             | `run_repl()`, `main()`; streaming callbacks, toolbar, slash routing |
| `repl_commands.py`  | REPL slash handlers              | `/agent`, `/whisper`/`/over`, `/permissions`, `/model`, `/mcp`, etc. |
| `serve.py`          | Headless HTTP JSON-RPC server    | `run_serve()` |
| `whisper.py`        | Whisper mode state               | `WhisperMode` |

**Core Classes**:
- `WhisperMode`: Manages whisper state (target/original agent).
- `KeyMonitor`: Async stdin ESC monitor (pausable for prompts).
- `LobbyResult`: Session selection result.

**Slash Commands** (in REPL):
- Agent: `/agent [id|--preset]`, `/list`, `/create`, `/destroy`, `/send`.
- Config: `/permissions [preset|--disable TOOL]`, `/model [name]`, `/cwd [path]`, `/prompt [file]`.
- MCP: `/mcp [connect/disconnect/tools] &lt;server&gt; [--allow-all|--shared]`.
- Session: `/save [name]`, `/resume` (CLI), `/clone/rename/delete`.
- UI: `/help`, `/clear`, `/quit`.

## Usage Examples

### Interactive REPL (Default)
```bash
nexus3  # or python -m nexus3.cli
# Lobby: Resume last/fresh/choose saved → REPL with embedded server at :8765
```

CLI flags:
```bash
nexus3 --resume          # Skip lobby, resume last
nexus3 --fresh --model gpt-4o-mini  # Fresh temp session
nexus3 --session my-project  # Load saved
nexus3 --connect http://localhost:8765 --agent worker-1  # Client mode
```

### Headless Server (Dev Only)
```bash
NEXUS_DEV=1 nexus3 --serve 8765 --verbose
nexus3 --serve 8765 --reload  # Auto-reload (watchfiles)
```

### RPC Client (JSON)
```bash
nexus3 rpc detect
nexus3 rpc list
nexus3 rpc create worker-1 --preset sandboxed --message "Hi"
nexus3 rpc send worker-1 "Analyze code" --timeout 600
nexus3 rpc status worker-1
nexus3 rpc shutdown
```

### REPL Slash Examples
```
/agent analyzer --trusted
/whisper analyzer  # analyzer&gt;
/over
/permissions sandboxed --disable write_file
/model claude-3-5-sonnet-200k
/mcp connect github --allow-all --shared
/help
```

## Architecture (Unified REPL+Server)
```
nexus3
├── detect_server(8765) → if running: --connect else: unified
│   ├── SharedComponents (config/providers/context)
│   ├── AgentPool("main"/resume) + GlobalDispatcher
│   ├── token_manager → ~/.nexus3/server.key
│   ├── HTTP server task (idle=30min)
│   └── REPL: prompt → Session.send() → streaming (Live display, ESC/KeyMonitor)
│       ├── /slash → repl_commands → pool ops
│       ├── whisper: redirect Session
│       └── confirm_tool_action(): Rich prompts (pause Live/KeyMonitor)
└── Cleanup: shutdown → cancel HTTP → delete token → pool.destroy_all()
```

- **Unified**: REPL uses direct Session (zero-latency streaming); RPC via HTTP.
- **Sessions**: Auto-save last; lobby for resume.
- **Permissions**: Per-agent, presets+overrides+ceiling.
- **MCP**: Dynamic tools; connect/share/allow per-session.
- **Streaming**: Batched tools, thinking timer, cancel re-queues.

## Development
- Working dir: `/home/inc/repos/NEXUS3/nexus3/cli`.
- Config: `~/.nexus3/config.json`, `./.nexus3/`.
- Logs: `.nexus3/logs/&lt;agent&gt;/&lt;timestamp&gt;/`.
- Extend: Slash handlers in `repl_commands.py`; RPC in `client_commands.py`.

See NEXUS3 core docs for agents/session/tools.

---
*Updated: 2026-01-17*
