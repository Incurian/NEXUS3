---
name: nexus-rpc
description: Programmatic RPC commands for NEXUS3 multi-agent operations. Create agents, send messages, check status, and manage the server.
---

# Nexus RPC

Programmatic commands for NEXUS3 multi-agent operations. Use this for creating agent swarms, parallel task execution, and programmatic control.

## Usage

```bash
nexus-rpc <command> [arguments] [options]
```

## Commands

### detect

Check if a NEXUS3 server is running.

```bash
nexus-rpc detect [--port PORT]
```

Returns JSON with server status:
```json
{"running": true, "result": "nexus_server", "port": 8765}
{"running": false, "result": "no_server", "port": 8765}
```

### list

List all agents on the server. **Auto-starts server if needed.**

```bash
nexus-rpc list [--port PORT]
```

Returns JSON with agent details:
```json
{
  "agents": [
    {"agent_id": "main", "message_count": 5, "created_at": "2026-01-14T10:30:00"}
  ]
}
```

### create

Create a new agent. **Auto-starts server if needed.**

```bash
nexus-rpc create <agent_id> [options]
```

**Options:**
| Option | Description |
|--------|-------------|
| `-M, --message TEXT` | Send initial message after creation (agent starts working immediately) |
| `-p, --preset NAME` | Permission preset: trusted (default), sandboxed, worker |
| `--disable-tools TOOLS` | Comma-separated tools to disable |
| `--write-path PATH` | Additional path for write_file/edit_file (use with sandboxed/worker) |
| `--cwd PATH` | Working directory for the agent |
| `--model NAME` | Model override (e.g., anthropic/claude-haiku) |
| `--port PORT` | Server port (default: 8765) |

**Examples:**
```bash
# Basic agent
nexus-rpc create worker-1

# Agent with initial task (starts immediately)
nexus-rpc create researcher -M "Search for all TODO comments in nexus3/"

# Sandboxed agent with write access to specific path
nexus-rpc create writer --preset sandboxed --write-path /tmp/output

# Worker preset (minimal permissions, no agent management)
nexus-rpc create minion --preset worker --write-path ./results
```

### destroy

Destroy an agent (server keeps running).

```bash
nexus-rpc destroy <agent_id> [--port PORT]
```

### send

Send a message to an agent and wait for response.

```bash
nexus-rpc send <agent_id> <content> [--port PORT]
```

Returns JSON with response:
```json
{"content": "The agent's response", "request_id": "abc123"}
```

### status

Get agent token usage and context info.

```bash
nexus-rpc status <agent_id> [--port PORT]
```

Returns JSON with status:
```json
{
  "tokens": {"system": 612, "tools": 593, "messages": 20, "total": 1225},
  "context": {"message_count": 2, "system_prompt": true}
}
```

### cancel

Cancel an in-progress request on an agent.

```bash
nexus-rpc cancel <agent_id> <request_id> [--port PORT]
```

### shutdown

Gracefully shutdown the entire server and all agents.

```bash
nexus-rpc shutdown [--port PORT]
```

## Permission Presets

| Preset | Description |
|--------|-------------|
| `trusted` | Full access with confirmation for destructive actions (default) |
| `sandboxed` | Limited to CWD, no network, nexus tools disabled |
| `worker` | Minimal: sandboxed + no write_file, no agent management |

**Note:** `yolo` preset is only available in interactive REPL, not via RPC.

## Workflow Patterns

### Single Agent Task

```bash
nexus-rpc create analyzer -M "Analyze nexus3/core/ for security issues"
# Wait for completion, then:
nexus-rpc destroy analyzer
```

### Parallel Agent Swarm

Create multiple agents working on different tasks:

```bash
# Start server if needed
nexus-rpc detect || nexus --serve &

# Create swarm with initial tasks
nexus-rpc create rev-core -M "Review nexus3/core/ for clean architecture"
nexus-rpc create rev-rpc -M "Review nexus3/rpc/ for security"
nexus-rpc create rev-skill -M "Review nexus3/skill/ for code quality"

# Monitor progress
nexus-rpc list

# Clean up when done
nexus-rpc destroy rev-core
nexus-rpc destroy rev-rpc
nexus-rpc destroy rev-skill
```

### Worker Pool Pattern

Create constrained workers for specific tasks:

```bash
# Workers can only write to designated output directory
nexus-rpc create worker-1 --preset worker --write-path ./output -M "Task 1"
nexus-rpc create worker-2 --preset worker --write-path ./output -M "Task 2"
```

## Auto-Start Behavior

| Command | Auto-starts server? |
|---------|---------------------|
| `detect` | No |
| `list` | Yes |
| `create` | Yes |
| `send`, `status`, `destroy`, `cancel`, `shutdown` | No (requires server) |

## destroy vs shutdown

| Command | Effect |
|---------|--------|
| `nexus-rpc destroy <id>` | Removes ONE agent, server keeps running |
| `nexus-rpc shutdown` | Stops the entire server and all agents |

## Notes

- All commands return JSON for easy parsing
- API key authentication is handled automatically (stored in ~/.nexus3/rpc.token)
- Default port is 8765
- Use `--port` to work with multiple servers
