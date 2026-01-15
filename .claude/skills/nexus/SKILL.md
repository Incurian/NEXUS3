---
name: nexus
description: Start the NEXUS3 interactive REPL or server modes. Use this for interactive agent sessions.
---

# Nexus

Start the NEXUS3 AI agent in various modes.

## Usage

```bash
nexus [OPTIONS]
```

## Modes

### Default (REPL with Embedded Server)

```bash
nexus
```

Starts an interactive REPL with an embedded server. This is the most common mode:
- Auto-detects if a server is already running on port 8765
- If server exists: connects to it as a client
- If no server: starts embedded server + REPL with agent "main"

### Session Management

```bash
nexus                    # Opens lobby to select session
nexus --fresh            # Skip lobby, start new temp session
nexus --resume           # Resume last session (auto-saved)
nexus --session NAME     # Load specific saved session
nexus --template PATH    # Use custom system prompt
```

### Headless Server

```bash
nexus --serve [PORT]
```

Starts a headless HTTP server for multi-agent operations:
- Default port: 8765
- No interactive REPL - just serves RPC requests
- Use `nexus-rpc` commands to interact with it

### Client Mode

```bash
nexus --connect [URL] --agent [ID]
```

Connect to an existing server as a REPL client:
- URL default: `http://127.0.0.1:8765`
- Agent ID default: `main`

## Options

| Option | Description |
|--------|-------------|
| `--serve [PORT]` | Start headless server mode |
| `--connect [URL]` | Connect to existing server |
| `--agent ID` | Agent ID when connecting (default: main) |
| `--fresh` | Skip lobby, start new temp session |
| `--resume` | Resume last session |
| `--session NAME` | Load specific saved session |
| `--template PATH` | Custom system prompt file |
| `--verbose` | Enable verbose logging |
| `--log-dir DIR` | Custom log directory |
| `--init-global` | Initialize global config (~/.nexus3/) |
| `--init-global-force` | Overwrite existing global config |

## Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/clear` | Clear conversation history |
| `/status` | Show token usage and context info |
| `/save [name]` | Save current session |
| `/load <name>` | Load saved session |
| `/compact` | Manually trigger context compaction |
| `/init` | Initialize local config (.nexus3/) |
| `/permissions` | Show/change permission preset |
| `/whisper <agent>` | Switch to whisper mode (talk to subagent) |
| `/quit` or `/exit` | Exit the REPL |

## Permission Presets

Change permissions during session:

```
/permissions              # Show current preset
/permissions trusted      # Switch to trusted (default)
/permissions sandboxed    # Switch to sandboxed (limited)
/permissions yolo         # Switch to yolo (no confirmations)
/permissions --list-tools # List tool status
/permissions --disable write_file  # Disable a tool
```

| Preset | Description |
|--------|-------------|
| `yolo` | Full access, no confirmations |
| `trusted` | Confirmations for destructive actions (default) |
| `sandboxed` | Limited to CWD, no network, nexus tools disabled |
| `worker` | Minimal: sandboxed + no write_file |

## Context Configuration

NEXUS3 loads context from multiple sources (merged in order):

1. **Global** (`~/.nexus3/NEXUS.md`) - Personal defaults
2. **Ancestors** (parent directories) - Organization standards
3. **Local** (`./.nexus3/NEXUS.md`) - Project-specific

Use `/init` to create local config templates.

## Examples

Start interactive session:
```bash
nexus
```

Start fresh session (skip lobby):
```bash
nexus --fresh
```

Resume last session:
```bash
nexus --resume
```

Start headless server on port 9000:
```bash
nexus --serve 9000
```

Connect to existing server:
```bash
nexus --connect http://127.0.0.1:8765 --agent worker-1
```

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| ESC | Cancel running request |
| Ctrl+C | Cancel input / exit |
| Ctrl+D | Exit REPL |

## Notes

- Session logs are saved to `.nexus3/logs/` by default
- Auto-save creates `~/.nexus3/last-session.json` for `--resume`
- Use `nexus-rpc` for programmatic operations (create agents, send messages, etc.)
- Context compaction automatically triggers at 90% token usage
