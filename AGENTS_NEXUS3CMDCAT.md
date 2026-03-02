# AGENTS_NEXUS3CMDCAT.md

Full command catalog for NEXUS3.

Derived from `CLAUDE.md` user-reference sections, adapted for Codex usage.

## CLI Modes

```bash
# Unified REPL (auto-starts embedded server with 30-min idle timeout)
nexus3                    # Default: lobby mode for session selection
nexus3 --fresh            # Skip lobby, start new temp session
nexus3 --resume           # Resume last session (from ~/.nexus3/last-session.json)
nexus3 --session NAME     # Load specific saved session (from ~/.nexus3/sessions/)
nexus3 --template PATH    # Use custom system prompt (with --fresh)
nexus3 --model NAME       # Use specific model alias or ID

# HTTP server (headless, dev-only - requires NEXUS_DEV=1)
NEXUS_DEV=1 nexus3 --serve [PORT]

# Client mode (connect to existing server)
nexus3 --connect [URL] --agent [ID]
nexus3 --connect --scan 9000-9050  # Scan additional ports for servers

# RPC commands (require server to be running - no auto-start)
nexus3 rpc detect                 # Check if server is running
nexus3 rpc list                   # List all agents
nexus3 rpc create NAME [flags]    # Create agent
nexus3 rpc destroy NAME           # Remove agent
nexus3 rpc send NAME "message"    # Send message
nexus3 rpc status NAME            # Get agent tokens/context
nexus3 rpc compact NAME           # Force context compaction
nexus3 rpc cancel NAME REQ_ID     # Cancel request
nexus3 rpc shutdown               # Shutdown server

# Initialization
nexus3 --init-global              # Create ~/.nexus3/ with defaults
nexus3 --init-global-force        # Overwrite existing global config
```

## CLI Flag Reference

| Flag | Description |
|------|-------------|
| `--fresh` | Start fresh temp session (skip lobby) |
| `--resume` | Resume last session automatically |
| `--session NAME` | Load specific saved session |
| `--template PATH` | Custom system prompt file (with --fresh) |
| `--model NAME` | Model name/alias to use |
| `--serve [PORT]` | Run headless HTTP server (requires NEXUS_DEV=1) |
| `--connect [URL]` | Connect to existing server (URL optional) |
| `--agent ID` | Agent ID to connect to (with --connect) |
| `--scan PORTS` | Additional ports to scan (e.g., "9000" or "8765,9000-9050") |
| `--api-key KEY` | Explicit API key (auto-discovered by default) |
| `-v, --verbose` | Show debug output in terminal |
| `-V, --log-verbose` | Write debug output to verbose.md log |
| `--raw-log` | Enable raw API JSON logging |
| `--log-dir PATH` | Directory for session logs |
| `--reload` | Auto-reload on code changes (serve mode, requires watchfiles) |

## Session Management

Sessions persist conversation history, model choice, permissions, and working directory to disk.

### Startup Flow

1. Lobby (default): interactive menu showing:
   - resume last session (if exists)
   - start fresh session
   - choose from saved sessions
2. Direct flags skip the lobby:
   - `--fresh`: new temp session (`.1`, `.2`, etc.)
   - `--resume`: load `~/.nexus3/last-session.json`
   - `--session NAME`: load `~/.nexus3/sessions/{NAME}.json`

Session command references are below (`/save`, `/clone`, `/rename`, `/delete`).

### Session File Format

Sessions are JSON files with schema version 1:

```json
{
  "schema_version": 1,
  "agent_id": "my-project",
  "created_at": "2026-01-22T10:30:00",
  "modified_at": "2026-01-22T14:45:00",
  "messages": [...],
  "system_prompt": "...",
  "system_prompt_path": "/path/to/NEXUS.md",
  "working_directory": "/home/user/project",
  "permission_level": "trusted",
  "permission_preset": "trusted",
  "disabled_tools": [],
  "session_allowances": {},
  "model_alias": "sonnet",
  "token_usage": {"total": 12500, "available": 195000},
  "provenance": "user"
}
```

### File Locations

```text
~/.nexus3/
├── sessions/           # Named sessions
│   └── {name}.json     # Saved via /save
├── last-session.json   # Auto-saved on exit (for --resume)
└── last-session-name   # Name of last session
```

### Key Behaviors

- Auto-save on exit: current session saved to `last-session.json` for `--resume`
- Temp sessions: named `.1`, `.2`, etc.; require explicit name on `/save`
- Model persistence: model alias is saved and restored
- Permission restoration: preset and disabled tools restored from session
- CWD restoration: working directory restored from session

### Session Restoration Flow

1. Load JSON from disk
2. Deserialize messages to `Message` objects
3. Resolve model alias via config (`config.resolve_model(saved.model_alias)`)
4. Recreate permissions from preset and disabled tools
5. Rebuild agent with context, skill registry, and provider

## REPL Commands Reference

### Agent Management

| Command | Description |
|---------|-------------|
| `/agent` | Show current agent status (model, tokens, permissions) |
| `/agent <name>` | Switch to agent (prompts to create if absent) |
| `/agent <name> --yolo\|--trusted\|--sandboxed` | Create agent with preset and switch |
| `/agent <name> --model <alias>` | Create agent with specific model |
| `/list` | List active agents |
| `/create <name> [--yolo\|--trusted\|--sandboxed] [--model]` | Create agent without switching |
| `/destroy <name>` | Remove active agent |
| `/send <agent> <msg>` | One-shot message to another agent |
| `/status [agent] [--tools] [--tokens] [-a]` | Get status (`-a`: all details) |
| `/cancel [agent]` | Cancel in-progress request |
| `/shutdown` | Shutdown server (stops all agents) |

### Session Management

| Command | Description |
|---------|-------------|
| `/save [name]` | Save current session (prompts for name if temp) |
| `/clone <src> <dest>` | Clone agent or saved session |
| `/rename <old> <new>` | Rename agent or saved session |
| `/delete <name>` | Delete saved session from disk |

### Whisper Mode

| Command | Description |
|---------|-------------|
| `/whisper <agent>` | Redirect all input to target agent |
| `/over` | Exit whisper mode |

### Configuration

| Command | Description |
|---------|-------------|
| `/cwd [path]` | Show or change working directory |
| `/model` | Show current model |
| `/model <name>` | Switch model (alias or full ID) |
| `/permissions` | Show current permissions |
| `/permissions <preset>` | Change preset (`yolo`/`trusted`/`sandboxed`) |
| `/permissions --disable <tool>` | Disable a tool |
| `/permissions --enable <tool>` | Re-enable a tool |
| `/permissions --list-tools` | List enabled/disabled tools |
| `/prompt [file]` | Show or set system prompt |
| `/compact` | Force context compaction/summarization |
| `/gitlab` | Show GitLab status and configured instances |
| `/gitlab on\|off` | Enable/disable GitLab tools for session |

### MCP (External Tools)

| Command | Description |
|---------|-------------|
| `/mcp` | List configured and connected MCP servers |
| `/mcp connect <name>` | Connect to configured MCP server |
| `/mcp connect <name> --allow-all --shared` | Connect without prompts, share with all agents |
| `/mcp disconnect <name>` | Disconnect MCP server |
| `/mcp tools [server]` | List MCP tools |
| `/mcp resources [server]` | List MCP resources |
| `/mcp prompts [server]` | List MCP prompts |
| `/mcp retry <name>` | Retry tool-listing for a server |

Key MCP behaviors:
- Servers connect even if initial tool listing fails (graceful degradation)
- Dead connections auto-reconnect when tools are needed (lazy reconnection)
- Use `/mcp retry <server>` after fixing configuration issues

### Initialization

| Command | Description |
|---------|-------------|
| `/init [FILENAME]` | Create `.nexus3/` with `AGENTS.md` (default) or specified `.md` |
| `/init --force` | Overwrite existing config |
| `/init --global` | Initialize `~/.nexus3/` instead |

### REPL Control

| Command | Description |
|---------|-------------|
| `/help` | Show help |
| `/clear` | Clear display (preserve context) |
| `/quit`, `/exit`, `/q` | Exit REPL |

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `ESC` | Cancel in-progress request |
| `Ctrl+C` | Interrupt current input |
| `Ctrl+D` | Exit REPL |
| `p` | View full tool details during confirmation |

## Codex Operation Notes

When running from Codex tooling in this repo, prefer explicit module invocation:

```bash
.venv/bin/python -m nexus3 ...
```

This avoids shell alias and interpreter ambiguity.
