# Phase 4: Host REPL Uses Events

**Status:** Not started
**Complexity:** L
**Dependencies:** Phase 3

## Delivers

- Host REPL (embedded server) also becomes event-driven
- All terminals see all turns (host and connected clients)
- Eliminates "callbacks belong to one terminal" as a class of problems

## User-Visible Behavior

- No visible change for single-terminal use
- Multi-terminal: host terminal sees turns from connected clients in real-time

## Files to Modify

### Modify: `nexus3/cli/repl.py` (unified mode)

Change streaming section to route through dispatcher:

```python
# Before (current):
async for chunk in active_session.send(user_input):
    display.add_chunk(chunk)

# After (event-driven):
request_id = generate_request_id()

# Subscribe to events in-process (not via SSE)
event_queue = event_hub.subscribe(current_agent_id)

try:
    # Start send through dispatcher (in-process call)
    send_task = asyncio.create_task(
        main_agent.dispatcher.dispatch(Request(
            method="send",
            params={"content": user_input, "request_id": request_id},
            id=request_id,
        ))
    )

    # Consume events from queue
    while True:
        try:
            event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
            # Filter to our request_id
            if event.get("request_id") != request_id:
                continue

            event_type = event.get("type")

            if event_type == "content_chunk":
                display.add_chunk(event["text"])
            elif event_type == "thinking_started":
                display.start_thinking()
            # ... same handling as synced client

            elif event_type in ("turn_completed", "turn_cancelled"):
                break

        except asyncio.TimeoutError:
            # Check if send task failed
            if send_task.done():
                break
            # Otherwise refresh display
            continue

    await send_task

finally:
    event_hub.unsubscribe(current_agent_id, event_queue)
```

### Modify: `nexus3/rpc/event_hub.py`

Ensure in-process subscribe works the same as SSE:

```python
def subscribe(self, agent_id: str) -> asyncio.Queue:
    """Create a subscription queue for an agent.

    Works for both:
    - In-process consumers (host REPL)
    - SSE handlers (connected clients)
    """
    # Same implementation, just used differently
```

### Remove callback wiring

Once event-driven, remove direct callback assignments:

```python
# Remove these:
session.on_tool_call = on_tool_call
session.on_reasoning = on_reasoning
# ... etc

# Callbacks are now implicit via event publishing
```

## Implementation Notes

- Host REPL becomes "just another subscriber" to the event stream
- Dispatcher is the single source of events (no dual paths)
- In-process queue subscription avoids HTTP overhead for host

## Progress

- [ ] Add in-process event consumption to unified REPL
- [ ] Remove direct callback wiring
- [ ] Test host sees own turns via events
- [ ] Test host sees connected client turns
- [ ] Verify ESC cancellation still works

## Review Checklist

- [ ] Single-terminal behavior unchanged
- [ ] Multi-terminal: all see all turns
- [ ] No callback/event duplication
- [ ] Performance acceptable (in-process queue)
- [ ] GPT review approved
