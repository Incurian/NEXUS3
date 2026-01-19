# Phase 3: Synced REPL Client

**Status:** Complete
**Complexity:** L
**Dependencies:** Phase 2

## Delivers

- "Connect" mode gains full rich UI (spinner, gumballs, tool phases)
- Multiple terminals can drive turns with visual feedback
- Streamed responses instead of waiting for complete response

## User-Visible Behavior

When connecting to an existing server:
```
$ nexus3
Discovered servers:
  1) http://127.0.0.1:8765 (2 agents)

Select: 1

Available agents:
  1) main (125 msgs)
  2) worker-1 (50 msgs)

Select: 1

NEXUS3 v0.1.0 (synced)
Agent: main
Commands: /help | ESC to cancel
>
```

User sees same spinner/gumballs as unified mode during their turns.

## Architecture: Single SSE Stream + Request Router

**Key insight:** Per-turn SSE subscriptions risk missing early events. Instead:

1. Open **one long-lived SSE stream** when connecting
2. Route events to per-turn consumers by `request_id`
3. Subscribe to request queue **before** calling `send()` to avoid races

## Files to Create/Modify

### New: `nexus3/cli/sse_router.py`

EventRouter for single SSE stream + per-request routing:

```python
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, AsyncIterator


TERMINAL_EVENTS = {"turn_completed", "turn_cancelled"}


class EventRouter:
    """Route events from ONE long-lived SSE stream into per-request queues.

    Usage:
        router = EventRouter()
        pump_task = asyncio.create_task(router.pump(client.iter_events()))

        q = await router.subscribe(request_id)
        ... consume q until terminal ...
        await router.unsubscribe(request_id, q)

        pump_task.cancel(); await pump_task
    """

    def __init__(self, *, max_queue_size: int = 200) -> None:
        self._subs: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._max_queue_size = max_queue_size
        self._closed = False
        self._close_exc: Exception | None = None
        self._lock = asyncio.Lock()

    async def subscribe(self, request_id: str) -> asyncio.Queue[dict[str, Any]]:
        """Subscribe to events for a specific request_id."""
        if not request_id:
            raise ValueError("request_id is required")

        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._max_queue_size)
        async with self._lock:
            if self._closed:
                q.put_nowait(
                    {"type": "stream_error", "error": str(self._close_exc or "closed")}
                )
                return q
            self._subs[request_id].add(q)
        return q

    async def unsubscribe(self, request_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        """Unsubscribe a queue; safe to call multiple times."""
        async with self._lock:
            subs = self._subs.get(request_id)
            if not subs:
                return
            subs.discard(q)
            if not subs:
                self._subs.pop(request_id, None)

    async def publish(self, event: dict[str, Any]) -> None:
        """Publish one event to subscribers (called by pump())."""
        rid = event.get("request_id")
        if not rid:
            return  # ignore ping + non-request-scoped events

        async with self._lock:
            queues = list(self._subs.get(rid, ()))
        if not queues:
            return

        for q in queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # Drop for slow consumer

    async def close(self, exc: Exception | None = None) -> None:
        """Close router and wake any subscribers."""
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            self._close_exc = exc
            subs_snapshot = {rid: list(qs) for rid, qs in self._subs.items()}
            self._subs.clear()

        wake = {"type": "stream_error", "error": str(exc or "SSE stream closed")}
        for qs in subs_snapshot.values():
            for q in qs:
                try:
                    q.put_nowait(wake)
                except asyncio.QueueFull:
                    pass

    async def pump(self, events: AsyncIterator[dict[str, Any]]) -> None:
        """Consume events forever and route them. Call in a background task."""
        try:
            async for ev in events:
                await self.publish(ev)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self.close(e)
            raise
        else:
            await self.close(None)
```

### Modify: `nexus3/client.py` — SSE event iterator

Add `iter_events()` that works with agent-scoped URLs (current model):

```python
async def iter_events(
    self,
    request_id: str | None = None,
    *,
    agent_id: str | None = None,
) -> AsyncIterator[dict]:
    """Iterate SSE events from the server.

    Args:
        request_id: Optional filter for a specific turn.
        agent_id: If provided, treat self._url as server root and subscribe to
                 /agent/{agent_id}/events. If omitted, require that self._url
                 already points to /agent/{id} and subscribe to {self._url}/events.
    Yields:
        Parsed event dicts (including "type", "agent_id", and optional "request_id").
    """
```

Key implementation notes:
- If `agent_id` is None, append `/events` to existing URL (agent-scoped)
- If `agent_id` is provided, build `/agent/{agent_id}/events` from origin (root-scoped)
- Use `timeout=None` for long-lived SSE stream
- Parse `event:` and `data:` fields; handle multi-line data; ignore unknown fields
- Include auth header only if `self._api_key` is set

### Modify: `nexus3/cli/repl.py` — Synced client REPL

Replace `run_repl_client()` with synced version:

```python
async def run_repl_client_synced(
    server_url: str,
    agent_id: str,
    api_key: str | None,
    console: Console,
    theme: Theme,
) -> None:
    """Run REPL client with SSE sync for rich UI."""
    agent_url = f"{server_url.rstrip('/')}/agent/{agent_id}"
    async with NexusClient(agent_url, api_key=api_key, timeout=300.0) as client:

        # Start a single SSE stream for the whole session
        router = EventRouter()
        pump_task = asyncio.create_task(router.pump(client.iter_events()))

        display = StreamingDisplay(theme)
        # ... prompt session setup ...

        try:
            while True:
                user_input = await prompt_session.prompt_async("> ")
                if user_input.startswith("/"):
                    # Handle slash commands
                    ...
                    continue

                request_id = secrets.token_hex(8)  # Match server style

                # Subscribe FIRST to avoid missing early events
                q = await router.subscribe(request_id)

                send_task = asyncio.create_task(
                    client.send(user_input, request_id=request_id)
                )

                # Consume events and update display
                # ...

                await router.unsubscribe(request_id, q)

        finally:
            pump_task.cancel()
            try:
                await pump_task
            except asyncio.CancelledError:
                pass
```

### Modify: `nexus3/cli/connect_lobby.py` — Capability detection

Probe `/agent/{id}/events` to detect SSE capability:

- **When:** After agent selection (keep lobby snappy)
- **How:** Open streamed GET, verify `200` + `Content-Type: text/event-stream`, then immediately close
- **401/403:** Auth problem (not "SSE unsupported")
- **404/405:** Fall back to legacy `run_repl_client()` mode
- **Success:** Show banner `NEXUS3 v0.1.0 (synced)`

## Event Handling (Phase 2 Contract)

The turn consumer should handle these SSE event types:

| Event Type | Action |
|------------|--------|
| `content_chunk` | `display.add_chunk(text)` |
| `thinking_started` | `display.start_thinking()` |
| `thinking_ended` | `display.end_thinking()` |
| `tool_detected` | Optional: early tool call UI |
| `batch_started` | `display.start_batch([(name, id, params), ...])` |
| `tool_started` | `display.set_tool_active(tool_id)` |
| `tool_completed` | `display.set_tool_complete(tool_id, success, error)` |
| `batch_halted` | `display.halt_remaining_tools()` |
| `batch_completed` | Print gumballs to scrollback; `display.clear_tools()` |
| `turn_completed` | Return final content |
| `turn_cancelled` | Return "[cancelled]" |
| `stream_error` | Fallback to send result; show error |

## Slash Commands (Phase 3 Scope)

### Local Commands
| Command | Action |
|---------|--------|
| `/help` | Print connect-mode help |
| `/quit`, `/q`, `/exit` | Disconnect |
| `/clear` | Clear console |

### Agent-Scoped RPC Commands
| Command | RPC Method |
|---------|------------|
| `/status` | `get_tokens` + `get_context` |
| `/cancel` | Cancel current request |
| `/cancel <id>` | Cancel specific request |
| `/compact` | `compact(force=True)` |

### Deferred to Later Phases
- `/agents`, `/list`, `/use`, `/create`, `/destroy` — require root-scoped client
- `/whisper`, `/over` — REPL-local routing
- `/permissions`, `/cwd`, `/model` — need RPC methods

## Implementation Order

1. **`NexusClient.iter_events()`** — SSE iterator with agent-scoped URL support
2. **`EventRouter`** — Create `nexus3/cli/sse_router.py`
3. **SSE capability detection** — Add to connect_lobby.py
4. **`run_repl_client_synced()`** — Main synced REPL loop
5. **Slash commands** — Implement scoped subset
6. **Manual testing** — Multi-terminal scenarios

## Progress

- [x] Add `iter_events()` to NexusClient
- [x] Create EventRouter in `nexus3/cli/sse_router.py`
- [x] Add SSE capability detection in connect_lobby
- [x] Implement synced client REPL loop (MVP - no rich UI)
- [x] Security fix: token exfiltration protection
- [x] Wire StreamingDisplay to SSE events
- [x] Add ESC cancellation support
- [x] Implement slash commands (/help, /clear, /status, /compact, /quit, /cancel)
- [x] Fix event loop timeout (0.1s polling for responsive UI)
- [x] Fix batch_started tool id field (Phase 2 uses "id" not "tool_id")
- [x] Fix pump-death detection and fallback wiring
- [x] Fix cancellation output semantics (partial response + marker)
- [x] GPT final review approved (2026-01-19)

## Review Checklist

- [x] Display updates match unified mode
- [x] ESC cancellation works
- [x] Slash commands work
- [x] Fallback to old client mode works
- [x] No missed early events (subscribe before send)
- [x] GPT review approved (2026-01-19)

## Implementation Notes

- **No reconnect/resume ordering yet** — Phase 6 will add `seq` and replay
- **One SSE connection per session** — Avoids race conditions
- **Slash commands scoped** — Only commands that map cleanly to RPC
- Client generates `request_id` and passes to both `send()` and event filter
- **ESC cancellation:** call `client.cancel()`, keep consuming until `turn_cancelled`, then call `display.cancel_all_tools()` to clear pending gumballs
- **`iter_events()` must use `self._client.stream()`** inside the async context so SSE + RPC calls can run concurrently
- **Event loop polling:** Use 0.1s timeout on `q.get()` to keep spinner animating during long tool runs
- **Pump-death detection:** Check `pump_task.done()` and `router.is_closed` pre-turn and mid-turn; return to fallback on failure

## Remaining Work (Full Rich UI)

After MVP infrastructure complete, implement:

1. **StreamingDisplay + Live wiring**: Use same patterns as unified mode
2. **0.1s polling loop**: Replace 300s timeout with short polling + `live.refresh()`
3. **ESC cancellation**: Use `KeyMonitor` with `on_escape` callback that calls `client.cancel(request_id)`
4. **Pump-death fallback**: Return from `run_repl_client_synced()` so wrapper can run legacy mode
5. **Slash commands**: `/help`, `/clear`, `/cancel`, `/cancel <id>`

### SSE → Display Mapping (same as Phase 2 contract)

```
thinking_started  → display.start_thinking()
thinking_ended    → display.end_thinking()
content_chunk     → display.add_chunk(text)
tool_detected     → display.add_tool_call(name, tool_id)
batch_started     → print_thinking_if_needed(); display.start_batch(tools)
tool_started      → display.set_tool_active(tool_id)
tool_completed    → display.set_tool_complete(tool_id, success, error)
batch_halted      → display.halt_remaining_tools()
batch_completed   → print_batch_results_to_scrollback(); display.clear_tools()
turn_completed    → exit loop, print final content
turn_cancelled    → display.cancel_all_tools(); print "[cancelled]"
```

### ESC Cancellation Flow

1. User presses ESC → `on_escape()` callback fires
2. Set `cancel_requested = True`
3. Call `display.cancel_all_tools()` for immediate UI feedback
4. Start `cancel_task = asyncio.create_task(client.cancel(request_id))`
5. Do NOT cancel `send_task` - let server-side cancellation drive termination
6. Keep consuming events until `turn_cancelled` arrives
