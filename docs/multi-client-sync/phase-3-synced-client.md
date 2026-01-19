# Phase 3: Synced REPL Client

**Status:** Not started
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

## Files to Modify

### Modify: `nexus3/client.py`

Add SSE subscription helper:

```python
async def iter_events(
    self,
    agent_id: str,
    request_id: str | None = None,
) -> AsyncIterator[dict]:
    """Subscribe to SSE events for an agent.

    Args:
        agent_id: Agent to subscribe to
        request_id: Optional filter for specific request

    Yields:
        Event dicts as they arrive
    """
    url = f"{self.base_url}agent/{agent_id}/events"
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "GET",
            url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=None,  # SSE is long-lived
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    if request_id is None or data.get("request_id") == request_id:
                        yield data
```

### Modify: `nexus3/cli/repl.py` (client path)

Replace `run_repl_client()` with synced version:

```python
async def run_repl_client_synced(
    server_url: str,
    agent_id: str,
    api_key: str,
    console: Console,
    theme: Theme,
) -> None:
    """Run REPL client with SSE sync for rich UI."""
    client = NexusClient(server_url, api_key)
    display = StreamingDisplay(theme)

    # Event handler that updates display
    async def handle_events(request_id: str) -> str:
        """Consume events and update display, return final content."""
        content_parts = []
        async for event in client.iter_events(agent_id, request_id):
            event_type = event.get("type")

            if event_type == "content_chunk":
                content_parts.append(event["text"])
                display.add_chunk(event["text"])

            elif event_type == "thinking_started":
                display.start_thinking()

            elif event_type == "thinking_ended":
                display.end_thinking()

            elif event_type == "batch_started":
                tools = [(t["name"], t["id"], t.get("params", ""))
                         for t in event["tools"]]
                display.start_batch(tools)

            elif event_type == "tool_started":
                display.set_tool_active(event["tool_id"])

            elif event_type == "tool_completed":
                display.set_tool_complete(
                    event["tool_id"],
                    event.get("success", True),
                    event.get("error"),
                )

            elif event_type == "batch_completed":
                # Print batch results
                for tool in display.get_batch_results():
                    # ... same gumball printing as unified mode
                display.clear_tools()

            elif event_type == "turn_completed":
                return event.get("content", "".join(content_parts))

            elif event_type == "turn_cancelled":
                return "[cancelled]"

        return "".join(content_parts)

    # Main loop
    while True:
        user_input = await prompt_async("> ")

        if user_input.startswith("/"):
            # Handle slash commands locally (expanded set)
            result = handle_client_slash_command(user_input, client, agent_id)
            if result == "quit":
                break
            continue

        # Generate request_id client-side
        request_id = generate_request_id()

        # Start send in background
        send_task = asyncio.create_task(
            client.send(agent_id, user_input, request_id=request_id)
        )

        # Consume events with Live display
        display.reset()
        display.set_activity(Activity.WAITING)

        with Live(display, console=console, refresh_per_second=10, transient=True):
            try:
                content = await handle_events(request_id)
            except asyncio.CancelledError:
                await client.cancel(agent_id, request_id)
                content = "[cancelled]"

        # Print final response
        console.print(Markdown(content))

        # Ensure send task completes
        await send_task
```

### Modify: `nexus3/cli/connect_lobby.py`

- Add logic to try SSE endpoint; if 404/405, fall back to old client mode
- Update banner to show "(synced)" when SSE available

## Implementation Notes

- Client generates `request_id` and passes to both `send()` and event filter
- ESC cancellation: cancel the event consumer, then call `client.cancel()`
- Slash commands: expand from just `/quit`/`/status` to full set (they all work via RPC)

## Progress

- [ ] Add `iter_events()` to NexusClient
- [ ] Implement synced client REPL loop
- [ ] Wire StreamingDisplay to SSE events
- [ ] Add ESC cancellation support
- [ ] Expand slash command handling
- [ ] Add SSE capability detection/fallback
- [ ] Test multi-terminal scenario

## Review Checklist

- [ ] Display updates match unified mode
- [ ] ESC cancellation works
- [ ] Slash commands work
- [ ] Fallback to old client mode works
- [ ] GPT review approved
