---
name: nexus-rpc
description: Programmatic RPC commands for NEXUS3 multi-agent operations. Create agents, send messages, check status, and manage the server.
---

# Nexus RPC

Programmatic commands for NEXUS3 multi-agent operations.

## Usage

```bash
nexus-rpc <command> [arguments] [--port PORT]
```

## Commands

### detect

Check if a NEXUS3 server is running.

```bash
nexus-rpc detect [--port PORT]
```

Returns JSON with server status:
```json
{"status": "nexus_server", "port": 8765}
{"status": "no_server", "port": 8765}
```

### list

List all agents on the server. **Auto-starts server if needed.**

```bash
nexus-rpc list [--port PORT]
```

Returns JSON array of agent info:
```json
[{"id": "main", "created_at": "2024-01-09T10:30:00"}]
```

### create

Create a new agent. **Auto-starts server if needed.**

```bash
nexus-rpc create <agent_id> [--port PORT]
```

Returns JSON with agent info:
```json
{"id": "worker-1", "created_at": "2024-01-09T10:30:00"}
```

### destroy

Destroy an agent (server keeps running).

```bash
nexus-rpc destroy <agent_id> [--port PORT]
```

Returns JSON confirmation:
```json
{"destroyed": "worker-1"}
```

### send

Send a message to an agent and get the response.

```bash
nexus-rpc send <agent_id> <content> [--port PORT]
```

Returns JSON with response:
```json
{"content": "The response from the agent", "request_id": "abc123"}
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

Returns JSON confirmation:
```json
{"cancelled": true, "request_id": "abc123"}
```

### shutdown

Gracefully shutdown the entire server.

```bash
nexus-rpc shutdown [--port PORT]
```

Returns JSON confirmation:
```json
{"success": true, "message": "Server shutting down"}
```

## Parameters

| Parameter | Description |
|-----------|-------------|
| `--port` | Server port (default: 8765) |

## Auto-Start Behavior

- `list` and `create` will auto-start a server if none is running
- `send`, `status`, `destroy`, `cancel`, `shutdown` require server to be running

## Workflow Example

```bash
# Check if server running
nexus-rpc detect

# Create an agent (auto-starts server)
nexus-rpc create worker-1

# Send work to the agent
nexus-rpc send worker-1 "Analyze the file main.py"

# Check agent status
nexus-rpc status worker-1

# Destroy the agent when done
nexus-rpc destroy worker-1

# Shutdown the server
nexus-rpc shutdown
```

## destroy vs shutdown

| Command | Effect |
|---------|--------|
| `nexus-rpc destroy <id>` | Removes ONE agent, server keeps running |
| `nexus-rpc shutdown` | Stops the entire server and all agents |

## Notes

- All commands return JSON for easy parsing
- API key authentication is handled automatically
- Default port is 8765
