# Phase 2: Publish Events from Dispatcher

**Status:** Complete
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
data: {"type": "turn_started", "request_id": "abc", "agent_id": "test"}

event: thinking_started
data: {"type": "thinking_started", "request_id": "abc", "agent_id": "test"}

event: thinking_ended
data: {"type": "thinking_ended", "request_id": "abc", "agent_id": "test", "duration_ms": 2500}

event: content_chunk
data: {"type": "content_chunk", "request_id": "abc", "agent_id": "test", "text": "Let me "}

event: tool_detected
data: {"type": "tool_detected", "request_id": "abc", "agent_id": "test", "name": "read_file", "tool_id": "t1"}

event: batch_started
data: {"type": "batch_started", "request_id": "abc", "agent_id": "test", "tools": [{"name": "read_file", "id": "t1", "params": "path.txt"}]}

event: tool_started
data: {"type": "tool_started", "request_id": "abc", "agent_id": "test", "tool_id": "t1"}

event: tool_completed
data: {"type": "tool_completed", "request_id": "abc", "agent_id": "test", "tool_id": "t1", "success": true}

event: batch_completed
data: {"type": "batch_completed", "request_id": "abc", "agent_id": "test"}

event: turn_completed
data: {"type": "turn_completed", "request_id": "abc", "agent_id": "test", "content": "Done!", "halted": false}
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

- [x] Add turn lock to Dispatcher
- [x] Switch `_handle_send` to use `run_turn()`
- [x] Implement SessionEvent → SSE event mapping
- [x] Wire EventHub into Dispatcher
- [x] Test event publishing with curl
- [ ] Optional: Add `nexus3 rpc watch` command

## Review Checklist

- [x] All SessionEvent types mapped correctly
- [x] Turn lock prevents concurrent sends
- [x] Existing JSON-RPC API unchanged
- [x] Events include request_id for correlation
- [x] GPT review approved (2026-01-19)

## GPT Review Fixes (2026-01-19)

Based on GPT review findings:

1. **agent_id enforcement**: Changed `event.setdefault()` to `event[...] = ...` to guarantee canonical agent_id
2. **Cancellation semantics**: Check cancellation BEFORE emitting turn_started (avoids confusing turn_started→turn_cancelled sequence)
3. **Tool params whitespace**: Normalize newlines/tabs to spaces in `_format_tool_params` for single-line UI rendering
4. **Docs consistency**: Added `type` field to all example JSON payloads
5. **Terminal event guarantee (queued-cancel)**: Emit `turn_cancelled` even for requests cancelled while queued (before turn started)
6. **Terminal event guarantee (errors)**: Added broad Exception handler that emits `turn_cancelled` before re-raising
