# Phase 2: Publish Events from Dispatcher

**Status:** Not started
**Complexity:** M→L
**Dependencies:** Phase 1

## Delivers

- SSE stream includes full turn/tool/reasoning events
- Same semantics as local REPL callbacks
- Remote terminals can render gumballs + spinner accurately

## User-Visible Behavior

SSE subscribers see real-time events during agent turns:

```
event: turn_started
data: {"request_id": "abc", "agent_id": "test"}

event: thinking_started
data: {"request_id": "abc"}

event: thinking_ended
data: {"request_id": "abc", "duration_ms": 2500}

event: content_chunk
data: {"request_id": "abc", "text": "Let me "}

event: tool_detected
data: {"request_id": "abc", "name": "read_file", "tool_id": "t1"}

event: batch_started
data: {"request_id": "abc", "tools": [{"name": "read_file", "id": "t1", "params": "path.txt"}]}

event: tool_started
data: {"request_id": "abc", "tool_id": "t1"}

event: tool_completed
data: {"request_id": "abc", "tool_id": "t1", "success": true}

event: batch_completed
data: {"request_id": "abc"}

event: turn_completed
data: {"request_id": "abc", "content": "Done!", "halted": false}
```

## Files to Modify

### Modify: `nexus3/rpc/dispatcher.py`

1. **Add per-agent turn lock**:
   ```python
   class Dispatcher:
       def __init__(self, ...):
           self._turn_lock = asyncio.Lock()
   ```

2. **Change `_handle_send` to use `Session.run_turn()`**:
   ```python
   async def _handle_send(self, request: Request) -> Response:
       content_str = request.params.get("content", "")
       request_id = request.params.get("request_id") or generate_request_id()

       async with self._turn_lock:
           # Publish turn_started
           await self._publish_event("turn_started", {"request_id": request_id})

           final_content = []
           try:
               async for event in self._session.run_turn(content_str):
                   # Map SessionEvent to SSE event and publish
                   sse_event = self._map_session_event(event, request_id)
                   if sse_event:
                       await self._publish_event(sse_event["type"], sse_event)

                   # Collect content for final response
                   if isinstance(event, ContentChunk):
                       final_content.append(event.text)

               # Publish turn_completed
               await self._publish_event("turn_completed", {
                   "request_id": request_id,
                   "content": "".join(final_content),
                   "halted": False,
               })
           except asyncio.CancelledError:
               await self._publish_event("turn_cancelled", {"request_id": request_id})
               raise

       return make_success_response(request.id, {
           "content": "".join(final_content),
           "request_id": request_id,
       })
   ```

3. **Add event mapping helper**:
   ```python
   def _map_session_event(self, event: SessionEvent, request_id: str) -> dict | None:
       """Map SessionEvent to SSE event dict."""
       if isinstance(event, ContentChunk):
           return {"type": "content_chunk", "request_id": request_id, "text": event.text}
       elif isinstance(event, ToolDetected):
           return {"type": "tool_detected", ...}
       # ... etc for all SessionEvent types
   ```

4. **Add publish helper**:
   ```python
   async def _publish_event(self, event_type: str, data: dict) -> None:
       if self._event_hub:
           await self._event_hub.publish(self._agent_id, {"type": event_type, **data})
   ```

### Modify: `nexus3/rpc/pool.py`

- Pass EventHub to each Dispatcher on agent creation

### Optional: New CLI command

```bash
nexus3 rpc watch <agent_id>  # Simple event stream viewer
```

## Implementation Notes

- `Session.run_turn()` already yields `SessionEvent` types - use them as source of truth
- Turn lock prevents concurrent sends corrupting context
- Keep existing JSON-RPC response format for backward compatibility

## Progress

- [ ] Add turn lock to Dispatcher
- [ ] Switch `_handle_send` to use `run_turn()`
- [ ] Implement SessionEvent → SSE event mapping
- [ ] Wire EventHub into Dispatcher
- [ ] Test event publishing with curl
- [ ] Optional: Add `nexus3 rpc watch` command

## Review Checklist

- [ ] All SessionEvent types mapped correctly
- [ ] Turn lock prevents concurrent sends
- [ ] Existing JSON-RPC API unchanged
- [ ] Events include request_id for correlation
- [ ] GPT review approved
