# GPT Reviewer Handover - Terminal Unification

This document preserves context from the previous GPT reviewer session for continuity.

---

## 1. Project Context

**NEXUS3** is an AI-powered CLI agent framework. Key features:
- Multi-agent server with JSON-RPC + SSE
- Permission system (yolo/trusted/sandboxed/worker presets)
- MCP integration, context compaction
- Rich REPL with Live displays, tool progress, confirmations

**Multi-client sync** (Phases 1-7, now complete):
- Multiple REPL terminals can connect to the same agent
- Real-time visibility of each other's turns via SSE
- Shared confirmation system (first response wins)
- Foreign turn rendering via `SyncFeed` class

---

## 2. The Decision: Option A (Host Becomes Client)

### Key Insight
The "unified mode" vs "synced mode" distinction is **technical debt from incremental development**, not a deliberate security boundary.

**Reasoning:**
1. Server only listens on `127.0.0.1`
2. Connection requires auth token from local file
3. Any terminal that can connect has already proven it's a local user with token access
4. Therefore, there's no security benefit to restricting what authenticated terminals can do

### Conclusion
For local-only servers, the "host-only" category shrinks to essentially nothing. Every terminal with the token should have full capabilities.

**Option A is the cleanest unification path:** Make the host REPL behave like any other client - use RPC+SSE for everything, eliminating the special-case architecture.

---

## 3. Architecture Plan

### Target State
- **One REPL implementation** for all terminals
- Every terminal (including host) connects via `NexusClient`
- No in-process Session/EventHub/ConfirmationManager calls from REPL
- Host-only = starting the server; everything else is client behavior

### What Changes
| Current Unified (Host) | Current Synced (Client) | Target (All) |
|------------------------|-------------------------|--------------|
| In-process dispatcher | RPC `send` | RPC `send` |
| In-process EventHub | SSE stream | SSE stream |
| Direct pool access | Limited | RPC methods |
| Direct SessionManager | None | RPC methods |

---

## 4. Key Files and Roles

### Server-side
- `nexus3/rpc/global_dispatcher.py` - Handles root-scoped RPC (create/destroy agents, sessions)
- `nexus3/rpc/dispatcher.py` - Handles agent-scoped RPC (send/cancel/confirm/get_*)
- `nexus3/rpc/pool.py` - AgentPool manages agent lifecycle
- `nexus3/rpc/event_hub.py` - SSE event pub/sub
- `nexus3/rpc/confirmations.py` - Multi-client confirmation manager
- `nexus3/session/session.py` - Core agent session logic
- `nexus3/session/session_manager.py` - Session persistence

### Client-side
- `nexus3/cli/repl.py` - Main REPL (1600+ lines, needs refactoring)
- `nexus3/cli/sync_feed.py` - Foreign turn renderer
- `nexus3/cli/sse_router.py` - SSE event routing
- `nexus3/client.py` - NexusClient for RPC calls

---

## 5. RPC Methods to Add

### Global (Root-Scoped) - Must Have
| Method | Purpose |
|--------|---------|
| `list_sessions` | Session discovery for lobby |
| `load_session` | Restore saved session into agent |
| `save_session` | Save active agent as named session |
| `clone_session` | Clone a session |
| `rename_session` | Rename a session |
| `delete_session` | Delete a session |

### Agent-Scoped - Must Have
| Method | Purpose |
|--------|---------|
| `set_cwd` | Change agent working directory |
| `get_permissions` | Get current permission state |
| `set_permissions` | Change permission preset |
| `get_system_prompt` | Get current system prompt |
| `set_system_prompt` | Update system prompt |

### Nice-to-Have
| Method | Purpose |
|--------|---------|
| `get_agent_summaries` | Status for all agents |
| `get_model` / `set_model` | Model switching |
| MCP methods | MCP server management |

Full JSON schemas in `RPC-SCHEMA.md`.

---

## 6. Implementation Milestones

| Milestone | Description | Effort |
|-----------|-------------|--------|
| **1** | Host becomes client for agent interaction (send/cancel/confirm/events) | **M** |
| **2** | Command parity for common commands (/list, /create, /destroy, etc.) | **M** |
| **3** | Session persistence parity (new RPC methods) | **L** |
| **4** | Agent configuration parity (cwd/permissions/prompt) | **L-XL** |
| **5** | MCP parity (optional) | **XL** |

**Minimum viable:** After Milestone 1, all terminals use the same send/cancel/confirm/event pipeline. Core UX is identical.

---

## 7. Gotchas and Risks

### UI Regressions
- prompt_toolkit + Rich Live + background printing is tricky
- Need consistent `_current_live` context across modes
- Buffered foreign printing during Live displays (already implemented)

### RPC Surface Creep
- Token file must be `0600` permissions
- Log all admin operations
- Keep dangerous state changes explicit

### Session Persistence
- Server-local disk operations
- Under local-trust model, RPC exposure is fine
- Start minimal: save/load/list, defer clone/rename/delete

### repl.py Complexity
- 1600+ lines, needs refactoring
- Extract `run_repl_client_core()` as shared function
- Create `CommandRouter` for unified command handling

---

## 8. Recommendations

1. **No backwards compatibility needed** - pre-release, single user (developer)
2. **Be aggressive** - just do the clean thing, no migration shims
3. **Milestone 1 is the big win** - identical agent interaction UX
4. **Parallel work possible** - server RPC additions and client refactoring can proceed simultaneously
5. **Test incrementally** - each milestone should be testable independently

### Implementation Order Suggestion
1. Create `run_repl_client_core()` extracted from synced mode
2. Make unified mode call it with local NexusClient
3. Add root-scoped client for global commands
4. Implement session RPC methods
5. Implement agent config RPC methods
6. Remove leftover in-process special code

---

## 9. Important Context

- **Branch:** `feat/multi-client-sync`
- **Phases 1-7:** Complete (SSE, events, sync, confirmations)
- **Phase 8:** Terminal unification (planning complete, implementation not started)
- **Docs location:** `docs/terminal-unification/`

The planning documents (`README.md`, `RPC-SCHEMA.md`, `REFACTOR-PLAN.md`, `COMMAND-PARITY.md`) contain full details. Read them to get complete context.
