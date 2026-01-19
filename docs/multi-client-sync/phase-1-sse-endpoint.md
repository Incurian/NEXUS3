# Phase 1: SSE Endpoint + EventHub

**Status:** Complete
**Complexity:** M
**Dependencies:** Phase 0

## Delivers

- Embedded server exposes `GET /agent/{agent_id}/events` (SSE)
- Per-agent pub/sub EventHub for broadcasting events
- A "watcher" client can subscribe and see live events

## User-Visible Behavior

```bash
# Subscribe to agent events (curl example)
curl -N -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8765/agent/test-agent/events

# Output (SSE format):
event: ping
data: {"type":"ping","agent_id":"test-agent"}

event: turn_started
data: {"type":"turn_started","agent_id":"test-agent","request_id":"abc123"}

event: content_chunk
data: {"type":"content_chunk","agent_id":"test-agent","request_id":"abc123","text":"Hello"}
```

## SSE Event JSON Envelope (canonical format)

All events use a flat JSON envelope in the `data:` field:

```json
{
  "type": "event_type",
  "agent_id": "agent-name",
  "request_id": "abc123",
  "seq": 0,
  ...event-specific fields...
}
```

**Phase 1 notes:**
- `seq` is **optional until Phase 6** (omit for now)
- `request_id` only present for turn-scoped events (omit for ping)
- `agent_id` should always be present
- Phase 1 only emits `ping` events: `{"type":"ping","agent_id":"test-agent"}`

## Files to Create/Modify

### New: `nexus3/rpc/event_hub.py`

```python
import asyncio
from collections import defaultdict

class EventHub:
    """Per-agent pub/sub for SSE events."""

    def __init__(self, max_queue_size: int = 100):
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._max_queue_size = max_queue_size

    def subscribe(self, agent_id: str) -> asyncio.Queue:
        """Create a subscription queue for an agent."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue_size)
        self._subscribers[agent_id].add(queue)
        return queue

    def unsubscribe(self, agent_id: str, queue: asyncio.Queue) -> None:
        """Remove a subscription and cleanup empty agent keys."""
        self._subscribers[agent_id].discard(queue)
        # Cleanup: remove agent key if no subscribers remain
        if not self._subscribers[agent_id]:
            del self._subscribers[agent_id]

    async def publish(self, agent_id: str, event: dict) -> None:
        """Publish event to all subscribers for an agent."""
        # Use .get() to avoid creating empty keys in defaultdict
        subs = self._subscribers.get(agent_id)
        if not subs:
            return
        for queue in list(subs):  # Copy to avoid mutation during iteration
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop event for slow clients (backpressure)
                pass

    def has_subscribers(self, agent_id: str) -> bool:
        """Check if agent has any active subscribers."""
        return bool(self._subscribers.get(agent_id))

    def subscriber_count(self, agent_id: str) -> int:
        """Count subscribers for an agent."""
        return len(self._subscribers.get(agent_id, set()))

    def total_subscriber_count(self) -> int:
        """Count total subscribers across all agents (for idle timeout)."""
        return sum(len(subs) for subs in self._subscribers.values())
```

### Modify: `nexus3/rpc/http.py`

#### CRITICAL: Semaphore bypass for SSE

The current `run_http_server` wraps ALL connections in `async with semaphore`. SSE connections are long-lived and MUST NOT hold the semaphore.

**DoS consideration:** We need to detect SSE requests without parsing the full body (which could be up to 1MB). Solution: create a header-only parse function that reads request line + headers but NOT body.

Change `client_handler`:

```python
# BEFORE (current code):
async def client_handler(reader, writer) -> None:
    nonlocal last_activity
    last_activity = time.monotonic()
    async with semaphore:
        await handle_connection(reader, writer, pool, global_dispatcher, api_key, session_manager)

# AFTER (with SSE bypass + two-stage parsing):
async def client_handler(reader, writer) -> None:
    nonlocal last_activity
    last_activity = time.monotonic()

    # Stage 1: Read ONLY request line + headers (no body) to detect SSE
    # This is safe outside semaphore since headers are bounded by MAX_TOTAL_HEADERS_SIZE
    try:
        method, path, headers = await read_http_request_headers(reader)
    except HttpParseError as e:
        error_response = make_error_response(None, PARSE_ERROR, str(e))
        await send_http_response(writer, 400, serialize_response(error_response))
        writer.close()
        await writer.wait_closed()
        return

    # Check if SSE request BEFORE acquiring semaphore
    if _is_sse_request_from_headers(method, path):
        # SSE: authenticate then handle without semaphore
        # Build minimal HttpRequest for auth (no body needed)
        http_request = HttpRequest(method=method, path=path, headers=headers, body="")
        auth_error, auth_status = _authenticate_request(http_request, api_key)
        if auth_error is not None:
            await send_http_response(writer, auth_status, serialize_response(auth_error))
            writer.close()
            await writer.wait_closed()
            return
        await handle_sse_subscription(writer, path, event_hub)
        return

    # Regular JSON-RPC: acquire semaphore, then read body
    async with semaphore:
        # Stage 2: Read body under semaphore protection
        try:
            body = await read_http_body(reader, headers)
        except HttpParseError as e:
            error_response = make_error_response(None, PARSE_ERROR, str(e))
            await send_http_response(writer, 400, serialize_response(error_response))
            return
        http_request = HttpRequest(method=method, path=path, headers=headers, body=body)
        await handle_connection_with_parsed_request(
            http_request, writer, pool, global_dispatcher, api_key, session_manager
        )
```

#### New helper: read_http_request_headers (header-only parse)

```python
async def read_http_request_headers(
    reader: asyncio.StreamReader,
) -> tuple[str, str, dict[str, str]]:
    """Read only request line and headers (not body).

    Returns: (method, path, headers)
    Raises: HttpParseError

    This is safe to call outside the semaphore since headers are bounded.
    """
    # Read request line (existing logic from read_http_request)
    request_line = await asyncio.wait_for(reader.readline(), timeout=30.0)
    # ... parse method, path, version ...

    # Read headers (existing logic from read_http_request)
    headers = {}
    # ... header parsing loop ...

    return method, path, headers

async def read_http_body(
    reader: asyncio.StreamReader,
    headers: dict[str, str],
) -> str:
    """Read request body based on Content-Length header.

    Call this UNDER semaphore protection for non-SSE requests.
    """
    content_length = int(headers.get("content-length", "0"))
    if content_length > MAX_BODY_SIZE:
        raise HttpParseError(f"Body too large: {content_length}")
    if content_length > 0:
        body_bytes = await asyncio.wait_for(
            reader.readexactly(content_length),
            timeout=30.0,
        )
        return body_bytes.decode("utf-8")
    return ""
```

#### New helper: handle_connection_with_parsed_request

```python
async def handle_connection_with_parsed_request(
    http_request: HttpRequest,
    writer: asyncio.StreamWriter,
    pool: AgentPool,
    global_dispatcher: GlobalDispatcher,
    api_key: str | None,
    session_manager: SessionManager | None,
) -> None:
    """Handle connection with already-parsed HttpRequest.

    This is the existing handle_connection logic, but:
    - Does NOT call read_http_request (already parsed)
    - Starts at Layer 2 (method validation)
    """
    # Layer 2: Validate HTTP method (POST only for JSON-RPC)
    if http_request.method != "POST":
        error_response = make_error_response(None, INVALID_REQUEST, "Method not allowed. Use POST.")
        await send_http_response(writer, 405, serialize_response(error_response))
        return

    # Layer 3-8: Continue with existing handle_connection logic...
    # (auth, routing, parsing, dispatch, response)
```

#### Helper to detect SSE requests

```python
def _is_sse_request_from_headers(method: str, path: str) -> bool:
    """Check if request is for SSE event stream (from parsed headers)."""
    if method != "GET":
        return False
    # Pattern: /agent/{agent_id}/events
    if path.startswith("/agent/") and path.endswith("/events"):
        return True
    return False

def _extract_agent_id_from_events_path(path: str) -> str | None:
    """Extract agent_id from /agent/{agent_id}/events path."""
    # /agent/foo/events -> foo
    if path.startswith("/agent/") and path.endswith("/events"):
        middle = path[7:-7]  # Remove "/agent/" and "/events"
        if middle and is_valid_agent_id(middle):
            return middle
    return None
```

#### SSE handler implementation

```python
async def handle_sse_subscription(
    writer: asyncio.StreamWriter,
    path: str,
    event_hub: EventHub,
) -> None:
    """Handle SSE subscription for agent events."""
    agent_id = _extract_agent_id_from_events_path(path)
    if agent_id is None:
        error_response = make_error_response(None, INVALID_PARAMS, "Invalid agent ID in path")
        await send_http_response(writer, 400, serialize_response(error_response))
        return

    # Send SSE headers
    headers = [
        "HTTP/1.1 200 OK",
        "Content-Type: text/event-stream; charset=utf-8",
        "Cache-Control: no-cache",
        "Connection: keep-alive",
        "X-Accel-Buffering: no",  # Disable proxy buffering
        "",
        "",
    ]
    writer.write("\r\n".join(headers).encode())
    await writer.drain()

    # Subscribe to events
    queue = event_hub.subscribe(agent_id)
    try:
        while True:
            try:
                # Wait for event with timeout (for heartbeat)
                event = await asyncio.wait_for(queue.get(), timeout=15.0)
                await write_sse_event(writer, event)
            except asyncio.TimeoutError:
                # Send heartbeat (include agent_id for consistency)
                await write_sse_event(writer, {"type": "ping", "agent_id": agent_id})
    except (ConnectionResetError, BrokenPipeError, OSError):
        pass  # Client disconnected
    finally:
        event_hub.unsubscribe(agent_id, queue)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

async def write_sse_event(writer: asyncio.StreamWriter, event: dict) -> None:
    """Write a single SSE event."""
    event_type = event.get("type", "message")
    data = json.dumps(event)
    message = f"event: {event_type}\ndata: {data}\n\n"
    writer.write(message.encode())
    await writer.drain()
```

#### Update idle timeout logic

```python
# In run_http_server main loop:
while not pool.should_shutdown and not global_dispatcher.shutdown_requested:
    # Check idle timeout
    if idle_timeout is not None:
        # Don't idle-timeout if we have active SSE subscribers
        if event_hub.total_subscriber_count() > 0:
            last_activity = time.monotonic()
        else:
            idle_duration = time.monotonic() - last_activity
            if idle_duration > idle_timeout:
                logger.info(
                    "Idle timeout reached (%.0fs without RPC activity), shutting down",
                    idle_duration,
                )
                break

    await asyncio.sleep(0.1)
```

### Modify: `nexus3/rpc/pool.py` (SharedComponents)

Add EventHub to SharedComponents:

```python
@dataclass
class SharedComponents:
    config: Config
    provider_registry: ProviderRegistry
    base_log_dir: Path
    base_context: LoadedContext
    context_loader: ContextLoader
    log_streams: LogStream
    custom_presets: dict[str, PermissionPreset]
    event_hub: EventHub  # NEW
```

### Modify: `nexus3/rpc/bootstrap.py`

Create EventHub during bootstrap:

```python
from nexus3.rpc.event_hub import EventHub

async def bootstrap_server_components(...):
    # ... existing code ...

    # Phase 4: Create EventHub for SSE
    event_hub = EventHub()

    # Phase 5: Create SharedComponents (add event_hub)
    shared = SharedComponents(
        config=config,
        provider_registry=provider_registry,
        base_log_dir=base_log_dir,
        base_context=base_context,
        context_loader=context_loader,
        log_streams=log_streams,
        custom_presets=custom_presets,
        event_hub=event_hub,  # NEW
    )
    # ... rest of bootstrap ...
```

### Modify: `run_http_server` signature

Pass EventHub to the server:

```python
async def run_http_server(
    pool: AgentPool,
    global_dispatcher: GlobalDispatcher,
    port: int = DEFAULT_PORT,
    host: str = BIND_HOST,
    api_key: str | None = None,
    session_manager: SessionManager | None = None,
    max_concurrent: int = 32,
    idle_timeout: float | None = None,
    started_event: asyncio.Event | None = None,
    event_hub: EventHub | None = None,  # NEW
) -> None:
```

## Implementation Notes

- SSE format: `event: {type}\ndata: {json}\n\n`
- Heartbeat every 15s to detect dead connections
- Bounded queues (100 events) with drop policy for slow clients
- Auth: Same Bearer token as JSON-RPC, enforced via `_authenticate_request()` BEFORE streaming starts
- SSE connections bypass the connection semaphore to avoid blocking

## Progress

- [x] Create `event_hub.py` with EventHub class
- [x] Add `_is_sse_request_from_headers()` and `_extract_agent_id_from_events_path()` helpers
- [x] Add SSE branch in `client_handler` BEFORE semaphore acquisition
- [x] Implement `handle_sse_subscription()` with proper headers
- [x] Implement `write_sse_event()` helper (with event_type sanitization)
- [x] Add heartbeat mechanism (15s timeout)
- [x] Update idle timeout to check `total_subscriber_count()`
- [x] Add EventHub to SharedComponents
- [x] Create EventHub in bootstrap
- [x] Pass EventHub to `run_http_server`
- [x] Test with curl
- [x] Fix connection leak in client_handler (GPT review)
- [x] Sanitize event_type in write_sse_event (GPT review)

## Claude Code Ready Checklist

- [x] `http.py` handles `GET /agent/{id}/events` with auth
- [x] SSE handler does **not** hold connection semaphore
- [x] SSE handler streams heartbeat every 15s and exits cleanly on disconnect
- [x] `EventHub` supports subscribe/unsubscribe with bounded queues
- [x] `EventHub.total_subscriber_count()` exists for idle timeout
- [x] Idle timeout doesn't shut down while any SSE subscriber exists

## Review Checklist

- [x] SSE format correct (event/data/newlines)
- [x] Auth enforced on SSE endpoint (via `_authenticate_request`)
- [x] Heartbeat working
- [x] Slow client doesn't block others (queue drops)
- [x] Idle timeout doesn't kill server with subscribers
- [x] GPT review approved (2026-01-19)
