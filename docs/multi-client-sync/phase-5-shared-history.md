# Phase 5: Shared History + Background Updates

**Status:** Not started
**Complexity:** M→L
**Dependencies:** Phase 4

## Delivers

- Messages from other agents (via nexus_send) appear in active REPL
- While idle at prompt, see other terminals' turns completing
- New terminals can "attach" and see recent transcript

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

Add transcript RPC method:

```python
async def _handle_get_messages(self, request: Request) -> Response:
    """Get recent message history for transcript sync."""
    limit = request.params.get("limit", 20)
    offset = request.params.get("offset", 0)

    messages = self._context.messages[offset:offset + limit]
    serialized = [
        {
            "role": msg.role,
            "content": msg.content,
            "timestamp": msg.timestamp.isoformat() if hasattr(msg, "timestamp") else None,
            "source": getattr(msg, "source", None),  # For nexus_send attribution
        }
        for msg in messages
    ]

    return make_success_response(request.id, {
        "messages": serialized,
        "total": len(self._context.messages),
    })
```

### Modify: `nexus3/cli/repl.py` (both modes)

1. **Fetch transcript on connect/start**:
   ```python
   # On connect or attach
   messages = await client.get_messages(agent_id, limit=10)
   console.print("--- Recent history ---")
   for msg in messages:
       print_message_summary(msg)
   console.print("---")
   ```

2. **Background event consumer**:
   ```python
   async def background_event_watcher(event_queue: asyncio.Queue) -> None:
       """Watch for events while idle at prompt."""
       while True:
           try:
               event = await event_queue.get()
               # Skip events for our own requests
               if event.get("request_id") == current_request_id:
                   continue

               event_type = event.get("type")

               if event_type == "turn_started":
                   # Show who's talking
                   source = event.get("source", "another terminal")
                   print_in_terminal(f"[{source} started turn...]")

               elif event_type == "turn_completed":
                   # Show brief summary
                   content = event.get("content", "")[:50]
                   print_in_terminal(f"[turn completed: {content}...]")

           except asyncio.CancelledError:
               break
   ```

3. **Prompt-toolkit safe printing**:
   ```python
   from prompt_toolkit.patch_stdout import patch_stdout

   # Use patch_stdout context or run_in_terminal for background prints
   with patch_stdout():
       console.print(f"[{source}]: {message}")
   ```

### Modify: `nexus3/client.py`

Add `get_messages()` method:

```python
async def get_messages(
    self,
    agent_id: str,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """Get recent message history."""
    response = await self._call(
        f"/agent/{agent_id}",
        "get_messages",
        {"limit": limit, "offset": offset},
    )
    return response.get("messages", [])
```

### Modify: `nexus3/session/events.py` or context

Add source attribution to messages:

```python
# When nexus_send delivers a message, tag it
message.source = f"{sender_agent_id} → {receiver_agent_id}"
```

## Implementation Notes

- Use `patch_stdout()` to avoid corrupting prompt during background prints
- Limit background verbosity (show turn start/end, not every chunk)
- Transcript fetch uses existing message storage (no new persistence)

## Progress

- [ ] Add `get_messages` RPC method
- [ ] Add `get_messages` to NexusClient
- [ ] Implement transcript fetch on connect
- [ ] Implement background event watcher
- [ ] Add prompt-toolkit safe printing
- [ ] Add source attribution to nexus_send messages
- [ ] Test multi-terminal history sync

## Review Checklist

- [ ] Transcript paging works
- [ ] Background updates don't corrupt prompt
- [ ] nexus_send messages attributed correctly
- [ ] Not too verbose (summarized updates)
- [ ] GPT review approved
