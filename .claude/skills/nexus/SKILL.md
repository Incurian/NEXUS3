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
| `--verbose` | Enable verbose logging |
| `--log-dir DIR` | Custom log directory |

## Examples

Start interactive session:
```bash
nexus
```

Start headless server on port 9000:
```bash
nexus --serve 9000
```

Connect to existing server:
```bash
nexus --connect http://127.0.0.1:8765 --agent worker-1
```

## Notes

- The REPL supports slash commands: `/help`, `/clear`, `/status`, `/quit`
- Press ESC to cancel a running request
- Session logs are saved to `.nexus3/logs/` by default
- Use `nexus-rpc` for programmatic operations (create agents, send messages, etc.)
