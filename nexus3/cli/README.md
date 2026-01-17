# NEXUS3 CLI Module

## Purpose

NEXUS3 CLI is the command-line interface for the NEXUS3 AI agent framework. It provides:
- **Interactive REPL**: Streaming UI with Rich live display, bottom toolbar (tokens/state), ESC cancel, session lobby/persistence, whisper mode, slash commands.
- **Multi-Agent**: Create/switch/destroy agents, `/whisper <id>` → `/over`, session save/restore/clone.
- **HTTP JSON-RPC Server**: `--serve` (dev-only, `NEXUS_DEV=1`), port 8765.
- **RPC Client**: `nexus3 rpc` subcommands (detect/list/create/send/status/cancel/compact/shutdown) → JSON stdout.
- **Config**: `--init-global/local`, `/init`, model/permission/MCP management, sandboxing.

Unified REPL auto-starts embedded server (direct Session calls for zero-latency).

## Key Modules & Exports

| Module | Purpose | Key Exports |
|--------|---------|-------------|
| `__init__.py` | Entry | `main()` |
| `arg_parser.py` | Arg parsing | `parse_args()` |
| `client_commands.py` | RPC CLI | `cmd_list()`, `cmd_create()`, etc. |
| `confirmation_ui.py` | Tool confirm UI | `confirm_tool_action()` |
| `init_commands.py` | Config init | `init_global()`, `init_local()` |
| `keys.py` | ESC monitor | `KeyMonitor` |
| `live_state.py` | Live state | `_current_live` |
| `lobby.py` | Session lobby | `show_lobby()` → `LobbyResult` |
| `repl.py` | Core REPL (55K) | `run_repl()`, `main()` |
| `repl_commands.py` | Slash handlers | `/agent`, `/whisper`, `/model`, `/mcp`, `/init` |
| `serve.py` | Headless server | `run_serve()` |
| `whisper.py` | Whisper state | `WhisperMode` |

**Key Classes**: `WhisperMode`, `KeyMonitor`, `LobbyResult`.

**Slash Commands**:
- Agent: `/agent [id|--preset]`, `/list`, `/create`, `/destroy`, `/send`.
- Config: `/permissions [preset|--disable TOOL]`, `/model`, `/cwd`, `/prompt`, `/compact`, `/init`.
- MCP: `/mcp [connect/disconnect/tools] <server> [--allow-all|--shared]`.
- Session: `/save`, `/clone/rename/delete`.
- UI: `/help`, `/clear`, `/quit`.

## Usage Examples

### REPL (Default)
```bash
nexus3  # Lobby → REPL + embedded server (:8765)
nexus3 --resume  # Skip lobby
nexus3 --fresh -m gpt-4o-mini
nexus3 --session proj
nexus3 --connect http://localhost:8765 --agent worker
```
REPL:
```
/agent analyzer --trusted
/whisper analyzer  # analyzer> ...
/over
/permissions sandboxed --disable write_file
/model claude-3-5-sonnet-200k
/mcp connect github --allow-all --shared
/help
```

### Headless Server
```bash
NEXUS_DEV=1 nexus3 --serve 8765 --verbose --reload
```

### RPC Client
```bash
nexus3 rpc detect
nexus3 rpc list
nexus3 rpc create worker --sandboxed --message "Hi"
nexus3 rpc send worker "Task" -t 600
nexus3 rpc status worker
nexus3 rpc shutdown
```

### Init
```bash
nexus3 --init-global-force  # ~/.nexus3/
nexus3 --init-global        # Skip if exists
/init  # ./.nexus3/ (REPL)
```

---
*Updated: 2026-01-17*
