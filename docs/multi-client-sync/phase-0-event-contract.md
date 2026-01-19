# Phase 0: Event Contract

**Status:** Not started
**Complexity:** S
**Dependencies:** None

## Delivers

- Documented, versioned event schema for server-to-client communication
- No behavior change yet, but prevents later churn

## User-Visible Behavior

None (internal foundation).

## Files to Create/Modify

### New: `nexus3/rpc/events_protocol.py`

Event types to define:

```python
from dataclasses import dataclass
from typing import Literal

# Event envelope
@dataclass
class ServerEvent:
    type: str
    agent_id: str
    seq: int  # For ordering/reconnect
    data: dict

# Event types
EventType = Literal[
    # Turn lifecycle
    "turn_started",
    "turn_completed",
    "turn_cancelled",

    # Content streaming
    "content_chunk",

    # Tool lifecycle
    "tool_detected",
    "batch_started",
    "tool_started",
    "tool_completed",
    "batch_halted",
    "batch_completed",

    # Reasoning
    "thinking_started",
    "thinking_ended",

    # Heartbeat
    "ping",
]
```

### Documentation

Add event schema docs to this file or a separate `events.md`.

## Implementation Notes

- Keep schema simple and flat for SSE serialization
- Include `request_id` in turn events for client correlation
- Include timestamps for debugging

## Progress

- [ ] Create `events_protocol.py` with dataclasses
- [ ] Add JSON encoder helpers
- [ ] Document event types

## Review Checklist

- [ ] All existing SessionEvent types mapped
- [ ] Schema supports future extensibility
- [ ] GPT review approved
