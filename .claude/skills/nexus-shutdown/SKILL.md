---
name: nexus-shutdown
description: Request graceful shutdown of a Nexus agent. Use this to cleanly stop an agent server.
---

# Nexus Shutdown

Request a graceful shutdown of a Nexus agent server.

## Usage

```bash
python -m nexus3 shutdown <url>
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `url` | Yes | The agent's HTTP endpoint (e.g., `http://localhost:8765`) |

## Output

Returns JSON with:
```json
{
  "success": true
}
```

## Examples

Shutdown an agent:
```bash
python -m nexus3 shutdown http://localhost:8765
```

Shutdown on custom port:
```bash
python -m nexus3 shutdown http://localhost:9000
```

## Behavior

1. The agent receives the shutdown request
2. Any in-progress requests are cancelled gracefully
3. The HTTP server stops accepting new connections
4. Session logs are finalized
5. The process exits cleanly

## Notes

- This is a graceful shutdown - the agent will finish cleanup before exiting
- Any pending requests will be cancelled with a shutdown reason
- The agent's logs will be properly closed
- Use this instead of killing the process directly
- After shutdown, the agent must be restarted manually if needed
