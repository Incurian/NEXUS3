# Plan: Double Spinner Fix

## Overview

**Bug:** When two external RPC `send` requests arrive at an agent with an active REPL connection, two spinners and two "Waiting..." lines appear simultaneously. ESC cannot stop them — user is trapped.

**Discovered:** 2026-02-12 during AgentBridge AGENTS.md testing.

## Root Cause Analysis

Four contributing root causes identified:

### 1. Missing "ended" notification on non-CancelledError exceptions

In `dispatcher.py:_handle_send()` (line ~119-256), only `asyncio.CancelledError` is caught in the inner try/except (line 241). If `Session.send()` raises any other exception (provider errors, network errors, NexusError), the "ended" notification is **never sent**. The spinner stays running and `_incoming_turn_active` remains `True` forever, trapping the REPL in `while _incoming_turn_active: await asyncio.sleep(0.05)`.

### 2. Overwritten state variables without cleanup of prior spinner

In `repl.py`, the `_on_incoming_turn` "started" handler (lines 927-951) overwrites `_incoming_turn_done` and `_incoming_spinner_task` without first cancelling the prior spinner task. Since `_run_incoming_spinner` reads `_incoming_turn_done` from the enclosing scope, an orphaned spinner task reads the **new** Event object and keeps looping alongside the new spinner — creating two simultaneous `Rich.Live` instances.

### 3. No ESC handling during incoming turn wait

When the REPL waits for an incoming RPC turn (line 1324: `while _incoming_turn_active`), there is no `KeyMonitor` active. The user cannot press ESC to cancel.

### 4. Outer CancelledError handler misses "ended" notification

The outer `except asyncio.CancelledError` at line 253 (outside `_turn_lock`) catches task-level cancellation but does NOT send the "ended" notification.

### Trigger Sequence

1. Request 1 arrives, acquires `_turn_lock`, sends "started", spinner starts
2. `Session.send()` raises a non-CancelledError (e.g., provider API 404)
3. Exception bypasses inner `except asyncio.CancelledError`, propagates past lock release
4. "ended" never sent; spinner 1 orphaned; `_incoming_turn_active` stays `True`
5. Request 2 arrives, acquires lock, sends "started"
6. "started" handler overwrites `_incoming_turn_done` and `_incoming_spinner_task`
7. Spinner 1 (orphaned) reads new `_incoming_turn_done` Event, keeps running
8. Spinner 2 starts — both spinners active simultaneously
9. REPL stuck in `while _incoming_turn_active` with no ESC handler — **trapped**

## Design Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| Where to add "ended" guarantee? | `try/finally` in `_handle_send` | Guarantees notification regardless of exception type |
| How to handle orphaned spinners? | Cancel old spinner task before starting new one | Defensive; prevents state accumulation |
| How to enable ESC during incoming turns? | Add KeyMonitor during incoming turn wait loop | Consistent with existing REPL ESC pattern |
| Add request queuing for incoming turns? | No — defer | `_turn_lock` already serializes; fix the cleanup gaps |
| Replace module-level variables with class? | Yes — `_IncomingTurnState` | Reduces variable mismatch risk, makes cleanup atomic |

## Implementation Details

### Change 1: Guarantee "ended" notification (dispatcher.py)

Wrap "started"/"ended" lifecycle in `try/finally`:

```python
async with self._turn_lock:
    started_incoming = False
    if source != "repl":
        await self._notify_incoming({"phase": "started", ...})
        started_incoming = True

    try:
        async for chunk in self._session.send(...):
            ...
        if started_incoming:
            await self._notify_incoming({"phase": "ended", "ok": True, ...})
            started_incoming = False
        return {content, ...}
    except asyncio.CancelledError:
        if started_incoming:
            await self._notify_incoming({"phase": "ended", "cancelled": True, ...})
            started_incoming = False
        return {"cancelled": True, ...}
    finally:
        if started_incoming:
            try:
                await self._notify_incoming({
                    "phase": "ended", "request_id": request_id,
                    "ok": False, "error": True,
                })
            except Exception:
                pass  # Best effort
```

Also move outer `except asyncio.CancelledError` (line 253) into lock scope.

### Change 2: Encapsulate incoming turn state (repl.py)

Replace 5 module-level nonlocal variables with:

```python
class _IncomingTurnState:
    def __init__(self, console, theme):
        self.active = False
        self._done_event = None
        self._spinner_task = None
        self._end_payload = None

    async def start(self):
        await self._cleanup_spinner()
        self.active = True
        self._done_event = asyncio.Event()
        self._spinner_task = asyncio.create_task(self._run_spinner())

    async def end(self, payload):
        self._end_payload = payload
        if self._done_event: self._done_event.set()
        if self._spinner_task:
            try: await self._spinner_task
            except: pass
            self._spinner_task = None

    async def cancel(self):
        await self.end({"ok": False, "cancelled": True})

    async def _cleanup_spinner(self):
        if self._spinner_task is not None:
            if self._done_event: self._done_event.set()
            self._spinner_task.cancel()
            try: await self._spinner_task
            except: pass
            self._spinner_task = None
```

### Change 3: ESC support during incoming turn wait (repl.py)

Replace busy-wait with KeyMonitor-enabled wait:

```python
if user_input is _INCOMING_TURN_SENTINEL:
    incoming_cancelled = False
    def on_incoming_cancel():
        nonlocal incoming_cancelled
        incoming_cancelled = True

    async with KeyMonitor(on_escape=on_incoming_cancel, ...):
        while incoming_state.active and not incoming_cancelled:
            await asyncio.sleep(0.05)

    if incoming_cancelled:
        agent.dispatcher.cancel_all_active()
        await incoming_state.cancel()
    continue
```

## Files to Modify

| File | Change |
|------|--------|
| `nexus3/rpc/dispatcher.py` | try/finally for "ended" guarantee; handle outer CancelledError |
| `nexus3/cli/repl.py` | _IncomingTurnState class; defensive cleanup; ESC support |

## Testing Strategy

### Unit Tests (new: `tests/unit/test_incoming_turn.py`)

1. `test_ended_sent_on_session_error` — Session.send() raises RuntimeError; verify "ended" sent
2. `test_ended_sent_on_success` — normal flow; verify "ended" with ok=True
3. `test_send_exception_returns_error_response` — generic Exception; verify no hang
4. `test_concurrent_sends_serialized` — two sends; verify started/ended/started/ended
5. `test_start_cleans_up_orphaned_spinner` — start() twice without end(); verify cleanup

### Integration Tests (new: `tests/integration/test_incoming_turn_lifecycle.py`)

6. `test_rapid_rpc_sends_single_spinner` — two rapid sends; one spinner at a time
7. `test_rpc_send_error_cleans_up` — failing session; REPL recovers

### Live Testing

```bash
nexus3 --fresh
# In separate terminal:
nexus3 rpc send main "first message" &
nexus3 rpc send main "second message" &
# Verify: one spinner at a time, ESC works
```

## Implementation Checklist

### Phase 1: Fix dispatcher "ended" guarantee (Required First)

- [ ] **P1.1** Add `started_incoming` flag and `try/finally` in `_handle_send` (`dispatcher.py`)
- [ ] **P1.2** Move outer `except asyncio.CancelledError` into lock scope with "ended" notification
- [ ] **P1.3** Unit test: `test_ended_sent_on_session_error`
- [ ] **P1.4** Unit test: `test_ended_sent_on_success`
- [ ] **P1.5** Unit test: `test_send_exception_returns_error_response`

### Phase 2: Encapsulate incoming turn state + defensive cleanup (After Phase 1)

- [ ] **P2.1** Create `_IncomingTurnState` class in `repl.py`
- [ ] **P2.2** Update `_on_incoming_turn` callback to use state class
- [ ] **P2.3** Update REPL main loop to check `incoming_state.active`
- [ ] **P2.4** Add "error" display case in spinner end notification
- [ ] **P2.5** Unit test: `test_start_cleans_up_orphaned_spinner`

### Phase 3: ESC cancellation for incoming turns (After Phase 2)

- [ ] **P3.1** Replace busy-wait with `KeyMonitor`-enabled wait loop
- [ ] **P3.2** On ESC, cancel active request + call `incoming_state.cancel()`
- [ ] **P3.3** Unit test: ESC sets cancelled state

### Phase 4: Integration tests + live testing (After Phase 3)

- [ ] **P4.1** Integration test: rapid sends → serialized spinners
- [ ] **P4.2** Integration test: failing session → spinner cleanup
- [ ] **P4.3** Live test: two rapid external `rpc send` commands
- [ ] **P4.4** Live test: ESC during incoming turn

### Phase 5: Documentation (After Phase 4)

- [ ] **P5.1** Update `CLAUDE.md` keyboard shortcuts table for ESC on incoming turns
- [ ] **P5.2** Inline code comments for `try/finally` guarantee in `dispatcher.py`

## Quick Reference

| Component | File | Lines |
|-----------|------|-------|
| Dispatcher._handle_send | `nexus3/rpc/dispatcher.py` | ~119-256 |
| Dispatcher._notify_incoming | `nexus3/rpc/dispatcher.py` | ~105-117 |
| REPL incoming turn state | `nexus3/cli/repl.py` | ~883-965 |
| REPL main loop sentinel | `nexus3/cli/repl.py` | ~1321-1326 |
| KeyMonitor | `nexus3/cli/keys.py` | ~117-163 |
| Spinner | `nexus3/display/spinner.py` | |
| CancellationToken | `nexus3/core/cancel.py` | |
| Existing dispatcher tests | `tests/unit/test_rpc_dispatcher.py` | |

## Effort Estimate

| Phase | LOC (approx) |
|-------|------|
| 1: Dispatcher fix | ~30 |
| 2: State class | ~100 |
| 3: ESC support | ~30 |
| 4: Tests | ~200 |
| 5: Docs | ~10 |
| **Total** | **~370** |
