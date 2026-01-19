# Phase 6: Hardening

**Status:** Complete
**Complexity:** M
**Dependencies:** Phase 5

## Delivers

- Stable event ordering with sequence numbers
- Reconnect support with `Last-Event-ID`
- Slow client handling (backpressure/disconnect)
- Idle timeout correctly handles SSE subscribers

## User-Visible Behavior

- Reconnecting client catches up on missed events
- Slow network doesn't affect other clients or server
- Server doesn't shut down while clients are connected

## GPT Architecture Review (2026-01-19)

### Implementation Order

**Parallel Track A (EventHub changes):**
- Per-agent sequence counters
- Ring buffer for replay (100 events)
- `get_events_since(agent_id, since_seq)` method
- Slow client detection (track drops, disconnect after 10)

**Parallel Track B (HTTP changes):**
- Parse `Last-Event-ID` header on SSE connect
- Include `id: {seq}` in SSE output
- Replay missed events before live stream

**Integration:**
- Wire slow client disconnection to SSE handler
- Ensure idle timeout respects subscriber count

### Key Data Structures

```python
@dataclass
class SubscriberState:
    queue: asyncio.Queue[dict]
    consecutive_drops: int = 0

class EventHub:
    _subs: dict[str, dict[asyncio.Queue, SubscriberState]]  # agent_id -> queue -> state
    _seq: dict[str, int]  # Per-agent sequence counter
    _history: dict[str, deque[dict]]  # Ring buffer per agent
```

### Edge Cases
- **Replay truncation**: If client reconnects with Last-Event-ID older than buffer, return what we have
- **Duplicate delivery**: Clients should dedupe by seq if subscribe-then-replay causes overlap
- **Slow client detection**: Reset drop count on successful enqueue; disconnect after 10 consecutive drops
- **Invalid Last-Event-ID**: Treat as 0 (no replay)

## Files to Modify

### Modify: `nexus3/rpc/event_hub.py`

1. **Add sequence numbers**:
   ```python
   @dataclass
   class EventHub:
       _seq_counters: dict[str, int]  # Per-agent sequence
       _ring_buffers: dict[str, deque]  # For replay

       def __init__(self, buffer_size: int = 100):
           self._seq_counters = defaultdict(int)
           self._ring_buffers = defaultdict(lambda: deque(maxlen=buffer_size))

       async def publish(self, agent_id: str, event: dict) -> None:
           # Add sequence number
           seq = self._seq_counters[agent_id]
           self._seq_counters[agent_id] += 1
           event["seq"] = seq

           # Store in ring buffer for replay
           self._ring_buffers[agent_id].append(event)

           # Publish to subscribers
           for queue in self._subscribers[agent_id]:
               try:
                   queue.put_nowait(event)
               except asyncio.QueueFull:
                   # Mark client as slow, will be disconnected
                   pass

       def get_events_since(self, agent_id: str, since_seq: int) -> list[dict]:
           """Get events from ring buffer since sequence number."""
           buffer = self._ring_buffers[agent_id]
           return [e for e in buffer if e.get("seq", 0) > since_seq]
   ```

2. **Slow client detection**:
   ```python
   @dataclass
   class Subscription:
       queue: asyncio.Queue
       slow_count: int = 0
       MAX_SLOW_COUNT: int = 10

       def mark_slow(self) -> bool:
           """Mark as slow, return True if should disconnect."""
           self.slow_count += 1
           return self.slow_count >= self.MAX_SLOW_COUNT
   ```

### Modify: `nexus3/rpc/http.py`

1. **Support `Last-Event-ID` header**:
   ```python
   async def handle_sse_subscription(...):
       # Check for reconnect
       last_event_id = headers.get("last-event-id")
       if last_event_id:
           since_seq = int(last_event_id)
           # Replay missed events
           for event in event_hub.get_events_since(agent_id, since_seq):
               await write_sse_event(writer, event)

       # Continue with live events
       queue = event_hub.subscribe(agent_id)
       ...
   ```

2. **Include `id` in SSE events**:
   ```python
   async def write_sse_event(writer: StreamWriter, event: dict) -> None:
       seq = event.get("seq", 0)
       event_type = event.get("type", "message")
       data = json.dumps(event)
       message = f"id: {seq}\nevent: {event_type}\ndata: {data}\n\n"
       writer.write(message.encode())
       await writer.drain()
   ```

3. **Update idle timeout**:
   ```python
   # In run_http_server:
   while not pool.should_shutdown and not global_dispatcher.shutdown_requested:
       # Check idle timeout
       if idle_timeout is not None:
           # Don't idle-timeout if we have active subscribers
           if event_hub.total_subscriber_count() > 0:
               last_activity = time.monotonic()
           else:
               idle_duration = time.monotonic() - last_activity
               if idle_duration > idle_timeout:
                   logger.info("Idle timeout reached...")
                   break
   ```

4. **Disconnect slow clients**:
   ```python
   # In EventHub.publish or SSE handler
   if subscription.mark_slow():
       # Close the connection
       subscription.queue.put_nowait({"type": "_disconnect", "reason": "slow"})
   ```

## Implementation Notes

- Ring buffer size 100 events = ~few seconds of history for replay
- SSE `id` field enables automatic browser/client reconnect
- Slow client threshold: 10 consecutive drops → disconnect

## Progress

- [x] Add sequence numbers to events (EventHub._seq)
- [x] Add ring buffer for replay (EventHub._history with deque maxlen=100)
- [x] Implement `Last-Event-ID` reconnect (http.py parses header + replays)
- [x] Add `id` field to SSE output (write_sse_event includes id: seq)
- [x] Implement slow client detection/disconnect (consecutive_drops tracking + is_subscribed check)
- [x] Fix idle timeout for SSE subscribers (already implemented)
- [x] Fix replay-before-subscribe race (subscribe first, drain duplicates)
- [x] GPT review approved (2026-01-19)

## Review Checklist

- [x] Sequence numbers monotonic per-agent
- [x] Reconnect replays correct events (with gap fix)
- [x] Slow client doesn't block others (removed after 10 drops)
- [x] Slow client connection actually closes (is_subscribed check on timeout)
- [x] Idle timeout respects subscribers
- [x] GPT review approved (2026-01-19)
