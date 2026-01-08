---
name: nexus-send
description: Send messages to a Nexus agent. Use this to communicate with subagents or other Nexus instances running HTTP JSON-RPC servers.
---

# Nexus Send

Send a message to a Nexus agent running an HTTP JSON-RPC server.

## Usage

```bash
python -m nexus3 send <url> <content> [--request-id ID]
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `url` | Yes | The agent's HTTP endpoint (e.g., `http://localhost:8765`) |
| `content` | Yes | The message to send to the agent |
| `--request-id` | No | Optional ID to track/cancel this request later |

## Output

Returns JSON with:
- `content`: The agent's response
- `request_id`: The request ID (generated if not provided)

If cancelled:
- `cancelled`: true
- `request_id`: The cancelled request ID
- `reason`: Cancellation reason (if any)

## Examples

Send a simple message:
```bash
python -m nexus3 send http://localhost:8765 "What files are in the current directory?"
```

Send with a request ID for tracking:
```bash
python -m nexus3 send http://localhost:8765 "Analyze this codebase" --request-id analyze-001
```

Send to a custom port:
```bash
python -m nexus3 send http://localhost:9000 "Run the test suite"
```

## Notes

- The agent must be running with `python -m nexus3 --serve [PORT]`
- Default port is 8765 if not specified when starting the agent
- Long-running requests can be cancelled with `nexus-cancel`
- Use `nexus-status` to check agent health before sending
