# NEXUS3 CLI Module

## Purpose

The `nexus3.cli` module provides the complete command-line interface (CLI) for the NEXUS3 AI agent framework. It enables:

- **Interactive REPL**: Rich, streaming UI with prompt-toolkit, Rich live displays, bottom toolbar (tokens/ready state), ESC cancel, session persistence/lobby, whisper mode for multi-agent switching, slash commands for agent/model/permissions/MCP management.
- **Multi-Agent Support**: Create/switch/destroy agents, whisper mode (`/whisper <id>` → `/over`), session save/restore/clone.
- **Headless JSON-RPC Server**: `--serve` for programmatic HTTP access (requires `NEXUS_DEV=1`).
- **RPC Client**: `nexus3 rpc` subcommands (detect/list/create/send/status/cancel/shutdown) with JSON output.
- **Configuration**: `--init-global`/local for `~/.nexus3/` or `./.nexus3/`, model switching, permission presets (yolo/trusted/sandboxed/worker), MCP tool integration.
- **Security**: No auto-start servers in RPC, confirmation prompts for tools, path sandboxing, idle timeouts.

Default port: 8765. Unified REPL auto-starts embedded server if none running.

## Dependencies

**Runtime** (inferred from imports):
- `asyncio`, `rich`, `prompt-toolkit`, `pathlib`, `dotenv`.
- NEXUS3 core: `nexus3.config`, `nexus3.context`, `nexus3.provider`, `nexus3.rpc`, `nexus3.session`, `nexus3.commands`.
- Optional: `watchfiles` (`--reload`), `select/termios/tty` (Unix ESC monitor).

**Python**: 3.11+ (async/typing).

## Key Modules & Classes/Functions

| Module | Purpose | Key Exports |
|--------|---------|-------------|
| `__init__.py` | Entry point | `main()` |
| `client_commands.py` | RPC CLI (`nexus3 rpc`) | `cmd_detect()`, `cmd_list()`, `cmd_create()`, `cmd_send()`, `cmd_status()`, etc. (JSON stdout) |
| `commands.py` | Legacy slash parsing | `parse_command()`, `handle_command()` (minimal, superseded) |
| `init_commands.py` | Config init | `init_global()`, `init_local()` (creates `NEXUS.md`, `config.json`, `mcp.json`) |
| `keys.py` | ESC monitoring | `KeyMonitor` (async context mgr), `monitor_for_escape()` |
| `lobby.py` | Session lobby UI | `show_lobby()` → `LobbyResult` (resume/fresh/select) |
| `repl.py` | Core REPL (70K+ LoC) | `run_repl()`, `parse_args()`, `confirm_tool_action()`, `main()`; streaming callbacks, toolbar, slash routing |
| `repl_commands.py` | REPL slash handlers | `/agent`, `/whisper`/`/over`, `/permissions`, `/model`, `/mcp`, `/cwd`, `/prompt`, `/compact`, `/help`, `/quit`, etc. |
| `serve.py` | Headless server | `run_serve()` (AgentPool + HTTP, no idle timeout in dev) |
| `whisper.py` | Agent redirection | `WhisperMode` (enter/exit/is_active/get_prompt_prefix) |

**Core Classes**:
- `WhisperMode`: Manages whisper state (target/original agent).
- `KeyMonitor`: Async stdin ESC during ops (pausable for prompts).
- `StreamingDisplay`: Live UI for thinking/tools/response (tool batching, gumballs).

**Slash Commands** (in REPL):
- Agent: `/agent [id|--preset]`, `/list`, `/create`, `/destroy`, `/send`.
- Config: `/permissions [preset|--disable TOOL]`, `/model [name]`, `/cwd [path]`, `/prompt [file]`, `/compact`.
- MCP: `/mcp [connect/disconnect/tools] <server> [--allow-all|--shared]`.
- Session: `/save [name]`, `/resume`, `/clone/rename/delete`.
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
nexus3 --fresh --model gpt-4o-mini  # Fresh temp session, specific model
nexus3 --session my-project  # Load saved
nexus3 --connect http://localhost:8765 --agent worker-1  # Client mode
```

### Headless Server (Dev Only)
```bash
NEXUS_DEV=1 nexus3 --serve 8765 --verbose  # Runs until Ctrl+C
nexus3 --serve 8765 --reload  # Auto-reload on .py changes (watchfiles)
```

### RPC Client (JSON Output)
```bash
nexus3 rpc detect                    # {"running": true}
nexus3 rpc list                      # {"agents": [...]}
nexus3 rpc create worker-1 --preset sandboxed --message "Hi"
nexus3 rpc send worker-1 "Analyze code" --timeout 600
nexus3 rpc status worker-1
nexus3 rpc shutdown
```

### REPL Slash Examples
```
/agent analyzer --trusted     # Switch/create
/whisper analyzer             # Redirect input → analyzer> 
/over                         # Return
/permissions sandboxed --disable write_file
/model claude-3-5-sonnet-200k
/mcp connect github --allow-all --shared
/help
```

## Architecture Summary

```
nexus3 (no args)
├── detect_server(8765)
│   ├── NEXUS_SERVER → --connect mode (or shutdown+restart)
│   └── NO_SERVER → Unified:
│       ├── SharedComponents (config/providers/context)
│       ├── AgentPool("main" or resume) + GlobalDispatcher
│       ├── token_manager.generate() → ~/.nexus3/server.key
│       ├── asyncio.create_task(run_http_server(idle=30min))
│       └── REPL loop: prompt → Session.send() → streaming callbacks
│           ├── Live(StreamingDisplay): thinking ●→ tools batch → response
│           ├── /slash → repl_commands → pool ops
│           ├── whisper: redirect to target Session
│           └── confirm_tool_action(): Rich prompts (pause Live/KeyMonitor)
└── Cleanup: shutdown → cancel HTTP → delete token → pool.destroy_all()
```

- **Unified REPL+Server**: REPL bypasses HTTP (direct Session) for zero-latency streaming; RPC clients use HTTP.
- **Sessions**: Auto-save last after each turn/startup (serialize context/permissions). Lobby for resume.
- **Permissions**: Per-agent, presets+overrides+ceiling (parent), tool enable/disable, path sandbox.
- **MCP**: Dynamic tools (`mcp_server_tool`), connect/share/allow (per-session allowances).
- **Streaming**: Batched tools (parallel/sequential), thinking timer, cancel re-queues cancelled tools.

## Development

- Working dir: `/home/inc/repos/NEXUS3/nexus3/cli`.
- Config: `~/.nexus3/config.json` (models/providers/permissions), `./.nexus3/` (project-local).
- Logs: `.nexus3/logs/<agent>/<timestamp>/` (context/verbose/raw).
- Extend: Add slash handlers in `repl_commands.py`; RPC in `client_commands.py`.

See NEXUS3 core docs for agents/session/tools.

---
*Generated: 2026-01-15*
