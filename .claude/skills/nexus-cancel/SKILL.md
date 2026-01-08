---
name: nexus-cancel
description: Cancel an in-progress request on a Nexus agent. Use this to stop long-running operations.
---

# Nexus Cancel

Cancel an in-progress request on a Nexus agent.

## Usage

```bash
python -m nexus3 cancel <url> <request-id>
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `url` | Yes | The agent's HTTP endpoint (e.g., `http://localhost:8765`) |
| `request-id` | Yes | The ID of the request to cancel |

## Output

Returns JSON with:
- `cancelled`: Boolean indicating if cancellation succeeded
- `request_id`: The cancelled request ID
- `reason`: Cancellation reason (if applicable)

## Examples

Cancel a specific request:
```bash
python -m nexus3 cancel http://localhost:8765 analyze-001
```

Cancel on a custom port:
```bash
python -m nexus3 cancel http://localhost:9000 long-task-123
```

## Workflow

1. Start a request with a known ID:
   ```bash
   python -m nexus3 send http://localhost:8765 "Long analysis task" --request-id task-001
   ```

2. If it takes too long, cancel it:
   ```bash
   python -m nexus3 cancel http://localhost:8765 task-001
   ```

## Notes

- Only works for requests that are still in progress
- Cancellation is graceful - the agent stops at the next safe point
- The original `send` command will return with `cancelled: true`
- Request IDs must match exactly (case-sensitive)
