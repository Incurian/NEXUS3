# Terminal Unification (Phase 8)

**Goal:** Make every terminal connected to an agent work identically - no "primary/secondary" distinction.

**Status:** Milestones 1-4 complete. Host REPL now uses same client loop as connect mode.

**Branch:** `feat/multi-client-sync` (continues from Phase 7)

## Progress (2026-01-20)

**Completed:**
- ✅ All session RPC methods (list/load/save/clone/rename/delete)
- ✅ All agent config RPC methods (set_cwd, get/set_permissions, get/set_system_prompt, get/set_model)
- ✅ Pool service registrations (system_prompt_path, provider_registry)
- ✅ Session allowances restoration on load
- ✅ allow_exec_cwd decision type for exec tools
- ✅ NexusClient wrappers for all new methods
- ✅ Last-Event-ID support for SSE reconnect with auto-retry
- ✅ Extracted `run_repl_client_core()` shared function from synced mode
- ✅ Wired unified mode to use `run_repl_client_core()` via local NexusClient
- ✅ Full command parity: /list, /create, /destroy, /save, /sessions, /clone, /rename, /delete, /cwd, /permissions, /prompt, /model
- ✅ Agent switching via `/agent <id>` with proper cleanup (recursive call, validates agent exists)
- ✅ MCP error message for connected terminals (explains that MCP tools work, management is host-only)

**Result:** The host REPL is now "just another client" - it starts the embedded server, then connects via NexusClient and uses the same client loop as `--connect` mode. All terminals now have identical capabilities.

**Remaining:**
- MCP RPC methods (deferred - MCP management from any terminal)

---

## Background

The current "unified mode" vs "synced mode" distinction is **technical debt from incremental development**, not a deliberate security boundary:

1. Server only listens on `127.0.0.1`
2. Connection requires auth token from local file (`~/.nexus3/rpc.token`)
3. Any terminal that can connect has already proven it's a local user with token access
4. Therefore, there's no security benefit to restricting what authenticated terminals can do

**Conclusion:** For local-only servers, the "host-only" category should shrink to essentially nothing. Every terminal with the token should have full capabilities.

---

## Architecture: Option A (Host Becomes Client)

**Target:** One REPL implementation for all terminals.

- Server always runs HTTP JSON-RPC + SSE
- **Every terminal** (including host) connects via `NexusClient`
- No in-process Session/EventHub/ConfirmationManager calls from REPL
- Host-only = starting the server; everything else is client behavior

This eliminates "primary/secondary" by construction, not by duplicating code.

---

## Current State vs Target

| Aspect | Current Unified (Host) | Current Synced (Client) | Target (All) |
|--------|------------------------|-------------------------|--------------|
| Send messages | In-process dispatcher | RPC `send` | RPC `send` |
| Cancel | In-process | RPC `cancel` | RPC `cancel` |
| Confirmations | In-process ConfirmationManager | RPC `confirm` | RPC `confirm` |
| Events | In-process EventHub | SSE stream | SSE stream |
| Agent switching | Direct pool access | Limited | RPC methods |
| Session management | Direct SessionManager | None | RPC methods |
| Rich UI | Full | Partial | Full |

---

## Documents

- [RPC-SCHEMA.md](./RPC-SCHEMA.md) - New RPC methods needed
- [REFACTOR-PLAN.md](./REFACTOR-PLAN.md) - Step-by-step implementation plan
- [COMMAND-PARITY.md](./COMMAND-PARITY.md) - Slash command analysis

---

## Milestones

| Milestone | Description | Effort | Status |
|-----------|-------------|--------|--------|
| **1** | Host becomes client for agent interaction | **M** | **Complete** ✅ |
| **2** | Command parity for common commands | **M** | **Complete** ✅ |
| **3** | Session persistence parity | **L** | **Complete** ✅ |
| **4** | Agent configuration parity | **L-XL** | **Complete** ✅ |
| **5** | MCP parity (optional) | **XL** | Deferred |

**"Identical terminals" achieved:** All terminals now use the same `run_repl_client_core()` function for send/cancel/confirm/event rendering. The host REPL creates a local NexusClient after starting the embedded server and delegates to the shared client loop.

**Implementation notes:**
- Extracted `run_repl_client_core()` from synced mode (~600 lines)
- Unified mode now calls `run_repl_client_core()` with local NexusClient
- Removed ~680 lines of duplicated REPL code
- File went from 2493 to 1813 lines

---

## UX Features to Preserve

- Rich streaming Live display (spinners, gumballs, tool phases)
- SyncFeed foreign turns (content/tool/confirmation alerts)
- Confirmation UI (Option B: prompt when idle)
- History display (single-line preview)
- Status bar / ready indicator (prompt_toolkit bottom toolbar)
- Keybindings (ESC cancel, Ctrl+C)

---

## Files to Change

### Server-side
- `nexus3/rpc/global_dispatcher.py` - Add session RPC methods
- `nexus3/rpc/dispatcher.py` - Add agent config methods
- `nexus3/session/session_manager.py` - Expose operations for RPC

### Client-side
- `nexus3/cli/repl.py` - Refactor unified mode to use same client loop as synced
- `nexus3/cli/command_router.py` - New shared command routing
- `nexus3/client.py` - Add wrappers for new RPC methods

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| UI regressions (prompt_toolkit + Live) | Buffered foreign printing, consistent `_current_live`, integration tests |
| RPC surface creep | Token file `0600`, log admin ops, explicit dangerous operations |
| Session RPC complexity | Start minimal (save/load/list), defer clone/rename/delete |
