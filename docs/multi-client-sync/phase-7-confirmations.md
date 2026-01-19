# Phase 7: Multi-Client Confirmations

**Status:** Not started (Optional/Later)
**Complexity:** XL
**Dependencies:** Phase 6

## Delivers

- Confirmation prompts work from any connected terminal
- All terminals see "waiting for confirmation" state
- Any authorized terminal can approve/deny

## User-Visible Behavior

Terminal A initiates a turn that needs confirmation:

```
# Terminal A
> Delete the temp files
  ● shell_UNSAFE: rm -rf /tmp/test/*
    [AWAITING CONFIRMATION]
    Press Y to confirm, N to deny...
```

Terminal B (also connected) sees:

```
# Terminal B
> _
[Terminal A awaiting confirmation]
  ● shell_UNSAFE: rm -rf /tmp/test/*
    [AWAITING CONFIRMATION - respond in any terminal]
```

Either terminal can respond.

## Architecture Considerations

This is complex because:
1. Confirmation currently uses local callback (`session.on_confirm`)
2. Need to pause turn execution server-side
3. Need to broadcast confirmation request to all clients
4. Need to accept response from any client
5. Need to prevent duplicate responses

## Files to Modify

### New: `nexus3/rpc/confirmations.py`

```python
@dataclass
class PendingConfirmation:
    request_id: str
    agent_id: str
    tool_name: str
    tool_args: dict
    created_at: datetime
    response_event: asyncio.Event
    response: bool | None = None

class ConfirmationManager:
    """Track pending confirmations across clients."""

    _pending: dict[str, PendingConfirmation]

    async def request_confirmation(
        self,
        request_id: str,
        agent_id: str,
        tool_name: str,
        tool_args: dict,
    ) -> bool:
        """Request confirmation, wait for any client to respond."""
        confirmation = PendingConfirmation(
            request_id=request_id,
            agent_id=agent_id,
            tool_name=tool_name,
            tool_args=tool_args,
            created_at=datetime.now(),
            response_event=asyncio.Event(),
        )
        self._pending[request_id] = confirmation

        # Publish confirmation request event
        await self._event_hub.publish(agent_id, {
            "type": "confirmation_requested",
            "request_id": request_id,
            "tool_name": tool_name,
            "tool_args": tool_args,
        })

        # Wait for response
        await confirmation.response_event.wait()
        return confirmation.response

    def submit_response(self, request_id: str, approved: bool) -> bool:
        """Submit confirmation response (from any client)."""
        if request_id not in self._pending:
            return False

        confirmation = self._pending.pop(request_id)
        confirmation.response = approved
        confirmation.response_event.set()

        # Publish response event
        # ...

        return True
```

### New RPC Methods

```python
# In dispatcher or global dispatcher:

async def _handle_confirm(self, request: Request) -> Response:
    """Submit confirmation response."""
    request_id = request.params.get("request_id")
    approved = request.params.get("approved", False)

    success = confirmation_manager.submit_response(request_id, approved)
    return make_success_response(request.id, {"success": success})
```

### Modify: `nexus3/session/session.py`

Replace local `on_confirm` callback with confirmation manager:

```python
async def _execute_tool_with_confirmation(self, tool_call: ToolCall) -> ToolResult:
    if self._needs_confirmation(tool_call):
        approved = await self._confirmation_manager.request_confirmation(
            request_id=self._current_request_id,
            agent_id=self._agent_id,
            tool_name=tool_call.name,
            tool_args=tool_call.arguments,
        )
        if not approved:
            return ToolResult(success=False, output="User denied")

    return await self._execute_tool(tool_call)
```

### Modify: REPL clients

Handle confirmation events:

```python
elif event_type == "confirmation_requested":
    # Show confirmation UI
    tool_name = event["tool_name"]
    console.print(f"  ● {tool_name}: [AWAITING CONFIRMATION]")
    console.print("    Press Y to confirm, N to deny...")

    # Wait for key press
    key = await wait_for_key("yn")
    approved = key == "y"

    # Submit response
    await client.confirm(event["request_id"], approved)
```

## Implementation Notes

- Only one response accepted (first wins)
- Timeout for confirmations (auto-deny after N seconds)
- Consider: should any terminal be able to confirm, or only the initiator?

## Progress

- [ ] Design confirmation flow (which terminal can respond?)
- [ ] Create ConfirmationManager
- [ ] Add confirmation RPC methods
- [ ] Modify Session to use manager
- [ ] Add confirmation UI to REPL clients
- [ ] Handle timeout/auto-deny
- [ ] Test cross-terminal confirmation

## Review Checklist

- [ ] Only one response accepted
- [ ] All terminals see confirmation state
- [ ] Timeout handled gracefully
- [ ] Security: who can confirm?
- [ ] GPT review approved

## Open Questions

1. **Who can confirm?** Options:
   - Only the terminal that initiated the turn
   - Any terminal connected to the agent
   - Any terminal with TRUSTED permission level

2. **What if initiator disconnects?**
   - Auto-deny after timeout?
   - Allow other terminals to respond?

3. **WebSocket vs SSE for this?**
   - SSE + RPC works but is more round-trips
   - WebSocket would be cleaner for bidirectional
