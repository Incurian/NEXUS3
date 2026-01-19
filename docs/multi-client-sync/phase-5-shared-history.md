# Phase 5: Shared History + Background Updates

**Status:** Complete (5a + 5b)
**Complexity:** M→L
**Dependencies:** Phase 4

## Delivers

- Messages from other agents (via nexus_send) appear in active REPL
- While idle at prompt, see other terminals' turns completing
- New terminals can "attach" and see recent transcript

## GPT Architecture Review (2026-01-19)

### Implementation Order
Split into two sub-phases:
1. **Phase 5a (Core)**: get_messages RPC, transcript fetch, background watcher
2. **Phase 5b (Attribution)**: Message.meta support, nexus_send source tracking

### Key Architecture Decisions
- **Background safe printing**: Use `prompt_session.app.run_in_terminal()` (not `patch_stdout`)
- **Event types to show**: Only terminal events (`turn_completed`, `turn_cancelled`)
- **Request filtering**: Track `active_request_id` to avoid showing own turns twice
- **Unified vs synced**: Same filtering rules, different event sources (EventHub vs SSE)
- **Source attribution (Phase 5b)**: Add `Message.meta: dict[str, Any]` field, update persistence

## User-Visible Behavior

Terminal A is idle at prompt. Terminal B sends a message:

```
# Terminal A (idle)
> _
[worker-1 → main]: Task completed successfully
[main responding...]
  ● read_file: results.json
  ● Thought for 3s
The analysis shows...
>
```

New terminal connecting:

```
$ nexus3 --connect
...
NEXUS3 v0.1.0 (synced)
Agent: main

--- Recent history (last 5 turns) ---
[user]: Analyze the data
[assistant]: I'll read the file...
[worker-1 → main]: Task completed
[assistant]: The analysis shows...
---

>
```

## Files to Modify

### Modify: `nexus3/rpc/dispatcher.py`

Add transcript RPC method with validation:

```python
# in __init__:
self._handlers["get_messages"] = self._handle_get_messages

async def _handle_get_messages(self, request: Request) -> Response:
    """Get recent message history for transcript sync."""
    params = request.params or {}
    offset = params.get("offset", 0)
    limit = params.get("limit", 200)

    if not isinstance(offset, int) or offset < 0:
        raise InvalidParamsError("offset must be a non-negative integer")
    if not isinstance(limit, int) or limit <= 0 or limit > 2000:
        raise InvalidParamsError("limit must be an integer between 1 and 2000")

    msgs = self._context.messages
    total = len(msgs)
    slice_ = msgs[offset : offset + limit]

    def serialize_message(msg: Message, idx: int) -> dict[str, Any]:
        out = {
            "index": idx,
            "role": msg.role.value,
            "content": msg.content,
            "tool_call_id": msg.tool_call_id,
        }
        # Phase 5b: include meta if present
        meta = getattr(msg, "meta", None)
        if meta:
            out["meta"] = meta
        return out

    serialized = [serialize_message(m, offset + i) for i, m in enumerate(slice_)]

    return make_success_response(request.id, {
        "agent_id": self._agent_id,
        "total": total,
        "offset": offset,
        "limit": limit,
        "messages": serialized,
    })
```

### Modify: `nexus3/cli/repl.py` (both modes)

1. **Transcript fetch on connect** (synced mode):
   ```python
   # After "Connected" but before prompt loop
   try:
       result = await client.get_messages(offset=0, limit=20)
       if result.get("messages"):
           console.print("--- Recent history ---")
           for msg in result["messages"]:
               role = msg.get("role", "?")
               content = (msg.get("content") or "")[:100]
               console.print(f"[{role}]: {content}...")
           console.print("---")
   except Exception:
       pass  # Older server may not support get_messages
   ```

2. **Safe printing helper**:
   ```python
   async def safe_print(prompt_session: PromptSession, text: str) -> None:
       """Print to terminal without corrupting prompt."""
       def _print() -> None:
           console.print(text)
       await prompt_session.app.run_in_terminal(_print)
   ```

3. **Background event watcher (unified mode)**:
   ```python
   async def background_watch_unified(
       agent_id: str,
       prompt_session: PromptSession,
       console: Console,
       active_request_id_getter: Callable[[], str | None],
   ) -> None:
       """Watch for events while idle at prompt."""
       q = shared.event_hub.subscribe(agent_id)
       try:
           while True:
               ev = await q.get()
               if ev.get("type") not in ("turn_completed", "turn_cancelled"):
                   continue
               if ev.get("request_id") == active_request_id_getter():
                   continue
               # Safe print in terminal
               await prompt_session.app.run_in_terminal(
                   lambda: console.print(f"[dim cyan]●[/] [{agent_id}] turn {ev['type']}")
               )
       finally:
           shared.event_hub.unsubscribe(agent_id, q)
   ```

4. **Background event watcher (synced mode)**:
   ```python
   # Reuse existing SSE pump + add global queue for background events
   # Don't open a second SSE connection - publish all events to a global queue
   async def background_watch_synced(
       global_queue: asyncio.Queue,
       prompt_session: PromptSession,
       console: Console,
       active_request_id_getter: Callable[[], str | None],
   ) -> None:
       """Watch SSE events while idle at prompt."""
       while True:
           ev = await global_queue.get()
           if ev.get("type") not in ("turn_completed", "turn_cancelled"):
               continue
           if ev.get("request_id") == active_request_id_getter():
               continue
           await prompt_session.app.run_in_terminal(
               lambda: console.print(f"[dim cyan]●[/] turn {ev['type']}")
           )
   ```

### Modify: `nexus3/client.py`

Add `get_messages()` method:

```python
async def get_messages(
    self,
    offset: int = 0,
    limit: int = 200,
) -> dict[str, Any]:
    """Get recent message history."""
    response = await self._call("get_messages", {"offset": offset, "limit": limit})
    return cast(dict[str, Any], self._check(response))
```

### Phase 5b: Source Attribution

**GPT Architecture Review (2026-01-19)**

Goal: Messages from nexus_send display with source attribution:
```
[worker-1 → main]: Task completed
```

#### Implementation Order

**Parallel Track A+B:**
- (A) Add `Message.meta` + persistence changes
- (B) Add `user_meta` to Session.run_turn() and ContextManager.add_user_message()

**Sequential (depends on A+B):**
- (C) Dispatcher: accept optional params for meta and pass into Session.run_turn(user_meta=...)
- (D) DirectAgentAPI: allow passing source params through `send()`
- (E) `nexus_send` skill: read caller agent id from ServiceContainer and pass source info

#### File Changes

**1. `nexus3/core/types.py` - Add meta to Message**
```python
@dataclass(frozen=True)
class Message:
    role: Role
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)  # NEW
```

**2. `nexus3/context/manager.py` - Allow meta on user messages**
```python
def add_user_message(self, content: str, meta: dict[str, Any] | None = None) -> None:
    msg = Message(role=Role.USER, content=content, meta=meta or {})
    self._messages.append(msg)
```

**3. `nexus3/session/session.py` - Add user_meta param**
```python
async def run_turn(
    self,
    user_input: str,
    use_tools: bool = False,
    cancel_token: CancellationToken | None = None,
    user_meta: dict[str, Any] | None = None,   # NEW
) -> AsyncIterator[SessionEvent]:
    # ...
    self.context.add_user_message(user_input, meta=user_meta)
```

**4. `nexus3/session/persistence.py` - Serialize/deserialize meta**
```python
def serialize_message(msg: Message) -> dict[str, Any]:
    data = {"role": msg.role.value, "content": msg.content}
    # ...
    if msg.meta:
        data["meta"] = msg.meta
    return data

def deserialize_message(data: dict[str, Any]) -> Message:
    meta = data.get("meta", {}) or {}
    return Message(role=role, content=content, ..., meta=meta)
```

**5. `nexus3/rpc/dispatcher.py` - Accept source params in _handle_send**
```python
source = params.get("source")
source_agent_id = params.get("source_agent_id")

user_meta = None
if source or source_agent_id:
    user_meta = {"source": source, "source_agent_id": source_agent_id}

async for ev in self._session.run_turn(content, cancel_token=token, user_meta=user_meta):
    # ...
```

**6. `nexus3/rpc/agent_api.py` - DirectAgentAPI.send() with source params**
```python
async def send(
    self,
    content: str,
    request_id: str | int | None = None,
    *,
    source: str | None = None,
    source_agent_id: str | None = None,
) -> dict[str, Any]:
    params = {"content": content}
    if source is not None: params["source"] = source
    if source_agent_id is not None: params["source_agent_id"] = source_agent_id
    # ...
```

**7. `nexus3/skill/builtin/nexus_send.py` - Include caller agent_id**
```python
sender_id = self._services.get("agent_id")  # registered in pool.py

async def send_and_format(client: Any) -> dict[str, Any]:
    return await client.send(
        content,
        source="nexus_send",
        source_agent_id=sender_id,
    )
```

**8. Display formatting (repl.py transcript)**
```python
meta = msg.get("meta", {})
if meta.get("source") == "nexus_send" and meta.get("source_agent_id"):
    prefix = f"[{meta['source_agent_id']} → {agent_id}] "
```

#### Edge Cases
- **Meta dict must be JSON-serializable** (no datetimes, Paths)
- **Saved sessions**: adding meta requires persistence updates (backward compat: missing meta = {})
- **Spoofing**: remote HTTP clients could set source_agent_id (acceptable for Phase 5b; harden later)

#### Tests
1. Message serialization round-trip with meta preserved
2. Dispatcher passes meta into context via send RPC
3. nexus_send skill calls send() with source="nexus_send" and source_agent_id

## Implementation Notes

- Use `prompt_session.app.run_in_terminal()` for background prints (not `patch_stdout`)
- Show only terminal events (`turn_completed`, `turn_cancelled`) in background
- Track `active_request_id` to avoid showing own turns twice
- Synced mode: don't open second SSE connection - use global queue from pump
- Unified mode: subscribe to EventHub directly

## Progress

### Phase 5a (Core) - Complete
- [x] Add `get_messages` RPC method in dispatcher.py
- [x] Add `get_messages` to NexusClient
- [x] Implement transcript fetch on connect (synced mode) - fetches last 20 messages
- [x] Implement background event watcher (unified mode)
- [x] Implement background event watcher (synced mode)
- [x] Add global_queue to EventRouter for synced mode background watching
- [x] Fix transcript fetch to get last 20 (not first 20)
- [x] Add exception handling to synced mode run_in_terminal
- [x] GPT review approved (2026-01-19)

### Phase 5b (Attribution) - Complete
- [x] Add Message.meta field (types.py)
- [x] Update persistence serialize/deserialize (persistence.py)
- [x] Add meta param to ContextManager.add_user_message (manager.py)
- [x] Add user_meta param to Session.run_turn (session.py)
- [x] Accept source params in dispatcher._handle_send (dispatcher.py)
- [x] Add source params to DirectAgentAPI.send (agent_api.py)
- [x] Update NexusClient.send with source params (client.py)
- [x] Update nexus_send skill with source attribution (nexus_send.py)
- [x] Display attribution in transcript (repl.py)
- [x] GPT review approved (2026-01-19)

## Review Checklist

- [x] Transcript paging works (offset/limit)
- [x] Background updates don't corrupt prompt (run_in_terminal)
- [x] Own turns not shown twice (request_id filtering)
- [x] Only terminal events shown in background
- [x] GPT review approved (2026-01-19)
