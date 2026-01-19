# Multi-Client REPL Sync

Real-time synchronization for multiple REPL terminals connected to the same agent.

## Goal

Enable multiple REPL terminals to:
1. Connect to the same agent with full rich UI (spinner, gumballs, tool phases)
2. See each other's turns in real-time
3. Receive messages from other agents (via nexus_send) in the chat history
4. Share unified conversation history

## Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Transport | SSE (Server-Sent Events) | Simpler than WebSocket; one-way push sufficient for UI sync |
| EventHub location | Pool/SharedComponents | Clean ownership, testable, fits existing architecture |
| Event source | `Session.run_turn()` | Already exists with rich SessionEvent types |
| Client mode selection | Try SSE, fallback | Lowest friction, backward compatible |
| History snapshot | RPC `get_messages` | Paging support, better testability |

## Phases

| Phase | Description | Complexity | Status |
|-------|-------------|------------|--------|
| [Phase 0](phase-0-event-contract.md) | Event schema/contract | S | Not started |
| [Phase 1](phase-1-sse-endpoint.md) | SSE endpoint + EventHub | M | Not started |
| [Phase 2](phase-2-publish-events.md) | Publish turn/tool events from dispatcher | M→L | Not started |
| [Phase 3](phase-3-synced-client.md) | Synced REPL client with rich UI | L | Not started |
| [Phase 4](phase-4-unified-events.md) | Host REPL also event-driven | L | Not started |
| [Phase 5](phase-5-shared-history.md) | Shared history + background updates | M→L | Not started |
| [Phase 6](phase-6-hardening.md) | Ordering, reconnect, backpressure | M | Not started |
| [Phase 7](phase-7-confirmations.md) | Multi-client confirmations | XL | Optional/Later |

## Key Complexity Traps

1. **Long-lived SSE + semaphore**: SSE connections must not hold the connection semaphore forever
2. **Idle timeout + SSE**: SSE connections must count as activity
3. **Turn concurrency**: Must serialize per-agent turns to avoid context corruption
4. **Prompt redraw**: Background events require prompt-toolkit-safe output

## Branch

`feat/multi-client-sync`
