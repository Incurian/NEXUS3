# NEXUS3 CLI Module

**Purpose**: Command-line interface for NEXUS3 AI agents. Supports unified REPL (with embedded HTTP server), headless JSON-RPC server (`--serve`), client mode (`--connect`), RPC commands (`nexus rpc`), session persistence, whisper mode, MCP tools, permissions, and model switching.

**Key Files**:
- `__init__.py`: Entry point (`main()`).
- `client_commands.py`: RPC CLI (`nexus rpc detect/list/create/send/etc.`; auto-starts server).
- `commands.py`: Legacy slash parsing.
- `init_commands.py`: Config init (`--init-global`, `/init`).
- `keys.py`: `KeyMonitor` (ESC cancel).
- `lobby.py`: Session lobby UI (`LobbyResult`, `show_lobby`).
- `repl.py`: Core REPL (`run_repl`, arg parsing, streaming callbacks, toolbar).
- `repl_commands.py`: Slash handlers (`cmd_agent`, `cmd_whisper`, `cmd_permissions`, `cmd_mcp`, etc.).
- `serve.py`: Headless server (`run_serve`, `AgentPool` setup).
- `whisper.py`: `WhisperMode` (agent redirection).

**Main Classes/Functions**:
- `WhisperMode`: Whisper state (enter/exit/is_active).
- `KeyMonitor`: Async stdin ESC monitor.
- `run_repl()` / `run_serve()`: Mode entries.
- RPC: `cmd_create/send/status/shutdown` (JSON output).
- Slash: `/agent` (switch/create), `/whisper`/`/over`, `/permissions <preset>`, `/model <name>`, `/mcp connect`, `/compact`.

**Usage**: `nexus` (REPL+lobby), `nexus --serve [port]`, `nexus rpc create ID --preset sandboxed`.