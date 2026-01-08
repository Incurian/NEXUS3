---
name: nexus-status
description: Get status information from a Nexus agent. Shows token usage, context size, and system health.
---

# Nexus Status

Get status and health information from a Nexus agent.

## Usage

```bash
python -m nexus3 status <url>
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `url` | Yes | The agent's HTTP endpoint (e.g., `http://localhost:8765`) |

## Output

Returns JSON with token usage and context information:

```json
{
  "tokens": {
    "prompt_tokens": 1234,
    "completion_tokens": 567,
    "total_tokens": 1801
  },
  "context": {
    "message_count": 10,
    "system_prompt": "You are a helpful assistant..."
  }
}
```

## Examples

Check agent status:
```bash
python -m nexus3 status http://localhost:8765
```

Check status on custom port:
```bash
python -m nexus3 status http://localhost:9000
```

## Use Cases

- **Health check**: Verify an agent is responding before sending work
- **Token monitoring**: Track token usage to avoid limits
- **Context inspection**: See how many messages are in the conversation
- **Debugging**: Verify system prompt is loaded correctly

## Notes

- This is a lightweight operation that does not affect the agent's state
- Use this before `nexus-send` to verify the agent is ready
- Token counts reflect the current session's usage
- Message count includes both user and assistant messages
