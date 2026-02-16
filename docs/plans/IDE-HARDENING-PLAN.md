# Plan: IDE Integration Hardening

## Overview

Post-implementation hardening of the IDE integration module (`nexus3/ide/`). The IDE integration was implemented across 5 phases (P1-P5) on `feature/ide-integration` and is functionally complete. After merging `master` into the feature branch, a validation swarm of 5 Claude Code explorer agents identified 18 issues across robustness, lifecycle, context injection, and test coverage.

**Current state:**
- IDE module: 6 files (bridge, connection, context, discovery, transport, __init__)
- Tests: 80/80 passing, 85% public API coverage
- All imports resolve, no circular dependencies
- Master merge clean (one CLAUDE.md conflict resolved manually)

**Goal:** Fix all 24 identified issues before merging to master.

---

## Scope

### Included (all 24 issues)

**HIGH severity (5):**
1. Missing IDE bridge cleanup on REPL shutdown
2. TOCTOU race in IDE context refresh
3. Unsafe reconnection during parallel tool execution
4. `assert` instead of explicit check in transport
5. Listener crash doesn't update `is_connected`

**MEDIUM severity (13):**
6. No per-agent IDE bridge scoping
7. Sandboxed agents can see IDE context
8. No timeout on `open_diff`
9. Missing IDE context refresh on agent creation
10. Missing IDE context refresh on REPL commands
11. Missing IDE context refresh during compaction
12. Windows PID checking untested
13. Missing UTF-8 error handling in lock file read
14. No bounds checking on `result.content[0]`
15. Reconnect uses stale CWD
19. `_restore_unlocked()` doesn't register IDE bridge (restored sessions lack IDE access)
20. `/ide` command bypasses permission gating (accesses `_shared` directly)
21. Shutdown `disconnect()` needs timeout to prevent hang on unresponsive IDE

**LOW severity (6):**
16. 4 untested connection methods
17. Unbounded receive queue
18. No logging on lock file parse failures
22. `close()` in transport must reset `_listener_failed` for reconnection
23. Existing `is_connected` tests need `_listener_failed` mock after P1.2
24. Test imports need `_is_windows_pid_alive` added for P4.3

### Deferred to Future
- Per-agent IDE connections (each agent has own WebSocket) — too large for this plan
- macOS-specific testing

### Explicitly Excluded
- VS Code extension changes (separate project in `editors/vscode/`)
- New IDE features or tools

---

## Design Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| Per-agent IDE scoping (#6) | Document as limitation + skip bridge registration for sandboxed agents | Full per-agent connections is a major feature; scoping by permission level is cheap and prevents the security issue (#7) |
| Reconnection locking (#3) | Add `asyncio.Lock` to bridge for reconnection | Serializes reconnect with active IDE operations without blocking event loop |
| `open_diff` timeout (#8) | Add configurable timeout (default 120s) with fallback to terminal | Prevents indefinite hang; 120s is generous for reviewing a diff |
| Context refresh asymmetry (#9-11) | Add `_refresh_ide_context()` helper, call alongside git refresh | Follows existing pattern, minimal code |
| Listener crash detection (#5) | Set `_listener_failed` flag, check in `is_connected`, reset in `close()` | Lightweight, no API change |
| Shutdown disconnect timeout (#21) | Wrap `disconnect()` in `asyncio.wait_for(..., timeout=5.0)` | Prevents hang on unresponsive IDE |
| Restore session IDE bridge (#19) | Add IDE bridge registration to `_restore_unlocked()` with permission gate | Matches `_create_unlocked()` pattern |
| `/ide` command access (#20) | Use `agent.services.get("ide_bridge")` instead of `_shared` | Respects permission gating |
| IDE refresh helper (#9-11) | Extract refresh pattern from session.py:595-613 into `IDEBridge.refresh_context()` method | Avoids 6x duplication, encapsulates `_config` access |

---

## Implementation Details

### Issue 1 & 21: Missing IDE bridge cleanup on REPL shutdown (with timeout)

**File:** `nexus3/cli/repl.py` (shutdown sequence, ~line 1784)

Add after MCP registry close (with timeout to prevent hang on unresponsive IDE):
```python
# Close IDE bridge (with timeout)
if shared and shared.ide_bridge:
    try:
        await asyncio.wait_for(shared.ide_bridge.disconnect(), timeout=5.0)
    except (asyncio.TimeoutError, Exception):
        pass
```

### Issue 2: TOCTOU race in IDE context refresh

**File:** `nexus3/session/session.py` (~line 595-613)

Change from:
```python
if self.context and ide_bridge and ide_bridge.is_connected:
    conn = ide_bridge.connection
    editors = await conn.get_open_editors()
```
To atomic access:
```python
if self.context and ide_bridge:
    conn = ide_bridge.connection  # Single atomic access
    if conn and conn.is_connected:
        editors = await conn.get_open_editors()
```

### Issue 3: Reconnection lock

**File:** `nexus3/ide/bridge.py`

Add `_reconnect_lock: asyncio.Lock` to `__init__`. Wrap `reconnect_if_dead()` body in `async with self._reconnect_lock`. Also check lock in `confirm_with_ide_or_terminal` path.

### Issue 4: Replace assertions in transport

**File:** `nexus3/ide/transport.py` (lines 43, 55)

Replace:
```python
assert self._ws is not None
```
With:
```python
if self._ws is None:
    raise RuntimeError("WebSocket not connected")
```

### Issue 5 & 22: Listener crash detection (with reconnection support)

**File:** `nexus3/ide/transport.py`

Add `_listener_failed: bool = False` field to `__init__` (after line 24). Set to `True` in `_listen()` exception handler. Check in `is_connected` property. Reset to `False` in `close()` method (after line 67) to allow reconnection:
```python
@property
def is_connected(self) -> bool:
    return (
        self._ws is not None
        and self._ws.protocol is not None
        and self._listener_task is not None
        and not self._listener_task.done()
        and not self._listener_failed
    )
```

### Issue 6 & 7: Skip IDE bridge for sandboxed agents

**File:** `nexus3/rpc/pool.py` (~line 586)

`PermissionLevel` is already imported at line 50. Change from unconditional registration to permission-gated (follows clipboard pattern at lines 571-576):
```python
if self._shared.ide_bridge is not None:
    if permissions.effective_policy.level != PermissionLevel.SANDBOXED:
        services.register("ide_bridge", self._shared.ide_bridge)
```

### Issue 8: Timeout on open_diff

**File:** `nexus3/ide/connection.py` (`open_diff` method, lines 71-88)

Add `import asyncio` to file imports (not currently imported). Wrap the MCP call in `asyncio.wait_for()`:
```python
async def open_diff(self, ..., timeout: float = 120.0) -> DiffOutcome:
    try:
        result = await asyncio.wait_for(
            self._client.call_tool("openDiff", {...}),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return DiffOutcome.DIFF_REJECTED  # Timeout = reject, fall back to terminal
```

### Issues 9-11: IDE context refresh parity

Extract IDE refresh logic from `session.py:595-613` into a reusable async helper (e.g., in `nexus3/ide/bridge.py` or a new `nexus3/ide/refresh.py`). Then call it at each location:

**File:** `nexus3/rpc/pool.py` (line 615) — add IDE refresh after `context.refresh_git_context(agent_cwd)` on agent creation. Note: bridge may not be connected yet; handle gracefully.

**File:** `nexus3/cli/repl_commands.py` — add IDE refresh alongside git refresh in 4 commands:
- `/cwd` (`cmd_cwd()`, git refresh at line 1006)
- `/prompt` (`cmd_prompt()`, git refresh at line 1310)
- `/model` (`cmd_model()`, git refresh at line 1574)
- `/gitlab` (`_gitlab_toggle()`, git refresh at line 2398)

**File:** `nexus3/session/session.py` (line 1068) — add IDE refresh after git refresh during compaction

`ContextManager.refresh_ide_context()` already exists at `manager.py:263`. Pattern: wherever `context.refresh_git_context(cwd)` is called, also call IDE refresh if bridge available.

### Issue 12: Windows PID test coverage

**File:** `tests/unit/ide/test_discovery.py`

Add tests for `_is_windows_pid_alive()` with mocked subprocess:
- PowerShell returns process found
- PowerShell returns empty (process dead)
- PowerShell not found (FileNotFoundError → assume alive)
- PowerShell times out

### Issue 13: UTF-8 error handling in lock file read

**File:** `nexus3/ide/discovery.py` (line 186)

Change:
```python
data = json.loads(lock_file.read_text(encoding="utf-8"))
```
To (using `errors="ignore"` for consistency with `/proc/version` line 15 and `/etc/resolv.conf` line 108):
```python
data = json.loads(lock_file.read_text(encoding="utf-8", errors="ignore"))
```

### Issue 14: Bounds checking on result.content

**File:** `nexus3/ide/connection.py` (`_extract_text` helper, ~line 57-61)

Add bounds check:
```python
def _extract_text(result: Any) -> str:
    if not result.content or len(result.content) == 0:
        return ""
    first = result.content[0]
    return first.get("text", "") if isinstance(first, dict) else getattr(first, "text", "")
```

### Issue 15: Reconnect uses stale CWD

**File:** `nexus3/ide/bridge.py` (`reconnect_if_dead`)

Accept optional `cwd` parameter (already exists). Ensure callers pass current CWD. Update `confirm_with_ide_or_terminal` in `repl.py` to pass agent's current CWD.

### Issue 16: Missing connection tests

**File:** `tests/unit/ide/test_connection.py`

Add 4 tests following existing patterns:
- `test_open_file`
- `test_save_document`
- `test_close_tab`
- `test_close_all_diff_tabs`

### Issue 17: Bounded receive queue

**File:** `nexus3/ide/transport.py` (line 23)

Change:
```python
self._receive_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
```
To:
```python
self._receive_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
```

Change `_listen()` to use `put_nowait` with overflow handling (nested inside existing try/except):
```python
try:
    async for data in self._ws:
        msg = json.loads(data)
        try:
            self._receive_queue.put_nowait(msg)
        except asyncio.QueueFull:
            logger.warning("IDE receive queue full, dropping message")
except websockets.exceptions.ConnectionClosed:
    logger.debug("WebSocket connection closed")
except Exception:
    logger.exception("WebSocket listener error")
    self._listener_failed = True
```

### Issue 18: Lock file parse logging

**File:** `nexus3/ide/discovery.py` (~line 186-188)

Add debug logging (note: current code has bare `return`, which is correct for `-> None` function):
```python
except (json.JSONDecodeError, OSError) as e:
    logger.debug("Failed to read lock file %s: %s", lock_file, e)
    return
```

### Issue 19: `_restore_unlocked()` missing IDE bridge registration

**File:** `nexus3/rpc/pool.py` (`_restore_unlocked()`, ~line 914 area)

The restore path registers clipboard, permissions, and GitLab config but NOT the IDE bridge. Add permission-gated registration matching the pattern in `_create_unlocked()`:
```python
# Register IDE bridge if available (not for sandboxed agents)
if self._shared.ide_bridge is not None:
    if permissions.effective_policy.level != PermissionLevel.SANDBOXED:
        services.register("ide_bridge", self._shared.ide_bridge)
```

### Issue 20: `/ide` command bypasses permission gating

**File:** `nexus3/cli/repl_commands.py` (`cmd_ide()`, ~line 2745)

Current code accesses `ctx.pool._shared.ide_bridge` directly (with `noqa: SLF001`). After P5.1 gates sandboxed agents, this bypasses the gate. Change to:
```python
agent = ctx.pool.get(ctx.agent_id) if ctx.pool else None
ide_bridge = agent.services.get("ide_bridge") if agent and agent.services else None
```

### Issue 22: Transport `close()` must reset `_listener_failed`

**File:** `nexus3/ide/transport.py` (`close()` method, after line 67)

Add reset to allow reconnection after listener crash:
```python
async def close(self) -> None:
    if self._listener_task:
        self._listener_task.cancel()
        self._listener_task = None
    if self._ws:
        await self._ws.close()
        self._ws = None
    self._listener_failed = False  # Allow reconnection
```

---

## Testing Strategy

### Unit Tests (new)
- Transport: assertion replacement, listener crash detection, bounded queue, `close()` resets `_listener_failed`
- Discovery: Windows PID checking (5 scenarios), UTF-8 lock file handling
- Connection: 4 missing method tests, bounds checking on result.content, `open_diff` timeout
- Bridge: reconnection lock behavior

### Unit Tests (verify existing pass)
- All 80 existing IDE tests must continue passing

### Integration Tests
- IDE bridge cleanup on shutdown (with timeout)
- Sandboxed agent doesn't get IDE bridge registered (both create and restore paths)
- Context refresh triggers match git refresh triggers
- Restored sessions have IDE bridge available (for non-sandboxed agents)
- `/ide` command respects permission scoping

### Live Testing
```bash
nexus3 --fresh
# 1. Verify IDE auto-connects (check /ide status)
# 2. /cwd to different project → verify IDE context updates
# 3. Create sandboxed subagent → verify no IDE access
# 4. Kill VS Code → verify graceful degradation
# 5. Restart VS Code → verify reconnection works
# 6. /quit → verify clean shutdown (no unclosed transport warnings)
```

---

## Codebase Validation Notes

*Validated by 5 parallel Claude Code explorer agents on 2026-02-13*
*Per-phase validation by 6 parallel agents on 2026-02-13*

| Agent | Scope | Key Findings |
|-------|-------|-------------|
| Imports/Deps | All IDE imports | 18/18 resolve, no circular deps, websockets 16.0 installed |
| Session Integration | session.py, pool.py, bootstrap.py, repl.py | 6 issues: cleanup, TOCTOU, reconnect race, scoping, permissions, timeout |
| Discovery/Transport | discovery.py, transport.py, connection.py, bridge.py | Robust overall; assertions, listener crash, UTF-8, bounds checking |
| Tests | All test_*.py in tests/unit/ide/ | 80/80 passing, 4 untested methods, mocks accurate |
| Context Injection | context.py, manager.py, schema.py, repl_commands.py | Refresh asymmetry with git context at 7 trigger points |

Master merge (378451b — trusted parent creates sandboxed child at any CWD) confirmed non-conflicting but makes shared-bridge scoping issue more likely.

### Per-Phase Validation Corrections

**Phase 1 (Transport):**
- Line numbers confirmed: assert at 43/55, queue at 23, is_connected at 69-76, listener handler at 49-52
- Queue type is `Queue[dict[str, Any]]` NOT `Queue[str]` — plan code samples corrected below
- QueueFull handling needs nested try/except to preserve ConnectionClosed handler

**Phase 2 (Bridge):**
- Bridge already has `_diff_lock` at line 28 (for diffs); `_reconnect_lock` is a NEW separate lock
- REPL shutdown: MCP close at line 1784, IDE cleanup inserts after
- TOCTOU confirmed at exact lines 597 (is_connected check) → 599 (connection access)
- `confirm_with_ide_or_terminal` already has `agent_cwd: Path` param (line 368) — just needs passing to `reconnect_if_dead()` at line 382

**Phase 3 (Connection):**
- `_extract_text()` at lines 57-61 already handles empty list (`if result.content:` is falsy for `[]`)
- Plan's version adds type flexibility (dict vs object) which is a worthwhile improvement
- `asyncio` NOT imported in connection.py — must add `import asyncio`
- `DiffOutcome.DIFF_REJECTED` confirmed at line 21

**Phase 4 (Discovery):**
- Lock file `read_text()` at line 186, confirmed missing `errors=` param
- Existing codebase pattern uses `errors="ignore"` (not "replace") for `/proc/version` (line 15) and `/etc/resolv.conf` (line 108-109) — use `errors="ignore"` for consistency
- Exception handler at lines 185-188 catches `(json.JSONDecodeError, OSError)` — adding `errors="ignore"` prevents UnicodeDecodeError from bypassing the handler
- `_is_windows_pid_alive()` at lines 242-255, 5 test scenarios (adds OSError case)

**Phase 5 (Scoping/Refresh):**
- `PermissionLevel` already imported at pool.py line 50 — no need for local import
- Clipboard permission pattern at pool.py lines 571-576 provides exact model
- Git refresh exact lines: `/cwd`:1006, `/prompt`:1310, `/model`:1574, `/gitlab`:2398
- `/permissions` does NOT call `refresh_git_context` — remove from P5.3
- Compaction git refresh at line 1068 (not ~692)
- `ContextManager.refresh_ide_context()` already exists at manager.py line 263
- Should extract IDE refresh pattern from session.py:595-613 into a helper to avoid 6x duplication

**Phase 6-7 (Tests/Docs):**
- Untested method signatures: `open_file(file_path, preview=False)`, `save_document(file_path)`, `close_tab(tab_name)`, `close_all_diff_tabs()`
- IDE README.md exists (424 lines), needs "Known Limitations" section
- CLAUDE.md IDE refresh triggers table only lists 1 trigger — needs all 6

### Second-Pass Validation Findings (Round 2)

**Phase 1 — NEW:**
- `close()` must reset `_listener_failed = False` for reconnection (Issue #22)
- Existing 6 `is_connected` tests will need `_listener_failed` mock setup after P1.2 (Issue #23)
- No other assertions exist in transport.py besides lines 43 and 55

**Phase 2 — NEW:**
- Shutdown `disconnect()` needs `asyncio.wait_for(..., timeout=5.0)` to prevent hang (Issue #21)
- Only 1 caller of `reconnect_if_dead()` exists (repl.py:382) — simplifies P2.4
- TOCTOU exception handler (`except Exception: pass` at session.py:612-613) mitigates crash risk but fix still worthwhile for correctness
- `_reconnect_lock` doesn't block `is_connected` checks (property accessed before lock)

**Phase 3 — NEW:**
- 10 other methods also call `call_tool()` without timeout — deferred (fast MCP round-trips, not user-blocking)
- Adding `timeout` param to `open_diff` is backward-compatible (default value)

**Phase 4 — NEW:**
- Test imports need `_is_windows_pid_alive` added to import list in test_discovery.py (Issue #24)
- Bare `return` in `_process_lock_file` is correct (function returns `-> None`)
- PowerShell f-string PID interpolation: LOW risk, `pid` from trusted lock files

**Phase 5 — NEW:**
- `_restore_unlocked()` (pool.py ~line 914) doesn't register IDE bridge — restored sessions lack IDE access (Issue #19)
- `/ide` command accesses `ctx.pool._shared.ide_bridge` directly, bypassing permission gate (Issue #20)
- IDE refresh pattern accesses `ide_bridge._config` (private) — extract to `IDEBridge.refresh_context()` method to encapsulate

**Phase 6-7 — NEW:**
- After P1.2, existing `is_connected` tests may fail if they don't mock `_listener_failed` field
- Live test plan is realistic; sandboxed isolation testable via `/agent name --sandboxed`

---

## Implementation Checklist

### Phase 1: Transport Robustness (no external dependencies)
- [ ] **P1.1** Replace `assert` with explicit `RuntimeError` in `transport.py:43,55`
- [ ] **P1.2** Add `_listener_failed: bool = False` field to `__init__` (after line 24), set in `_listen()` exception handler, check in `is_connected` property, reset in `close()` method
- [ ] **P1.3** Change line 23: `asyncio.Queue()` → `asyncio.Queue(maxsize=1000)`, update `_listen()` to use `put_nowait()` with nested `QueueFull` handling
- [ ] **P1.4** Add unit tests for P1.1-P1.3 (including `close()` reset test). Update existing 6 `is_connected` tests to initialize `_listener_failed = False` in mocks.

### Phase 2: Bridge Lifecycle & Safety
- [ ] **P2.1** Add `_reconnect_lock` to `bridge.py` `__init__` and wrap `reconnect_if_dead()` body in `async with self._reconnect_lock`
- [ ] **P2.2** Add IDE bridge `disconnect()` with `asyncio.wait_for(..., timeout=5.0)` in REPL shutdown sequence after MCP close (`repl.py:1784`)
- [ ] **P2.3** Fix TOCTOU in `session.py:597-599` IDE context refresh (atomic connection access: get `conn` first, then check `conn.is_connected`)
- [ ] **P2.4** Pass `agent_cwd` to `reconnect_if_dead(cwd=agent_cwd)` at `repl.py:382` (only caller)
- [ ] **P2.5** Add unit tests for reconnection lock, shutdown cleanup, and CWD passing

### Phase 3: Connection Hardening
- [ ] **P3.1** Add `import asyncio` to `connection.py` and type-flexible bounds checking in `_extract_text()` (dict vs object)
- [ ] **P3.2** Add `asyncio.wait_for()` timeout on `open_diff` (default 120s), return `DIFF_REJECTED` on timeout
- [ ] **P3.3** Add unit tests for P3.1-P3.2 (bounds check, type flexibility, timeout behavior)

### Phase 4: Discovery Hardening
- [ ] **P4.1** Add `errors="ignore"` to lock file `read_text()` call at line 186 (consistency with existing codebase pattern)
- [ ] **P4.2** Add `logger.debug()` for lock file parse failures (add `as e` binding to exception handler)
- [ ] **P4.3** Add `_is_windows_pid_alive` to test imports and add 5 unit tests (process found, process dead, PowerShell not found, timeout, OSError)
- [ ] **P4.4** Add unit test for corrupted UTF-8 lock file (use pytest `caplog` fixture for logging verification)

### Phase 5: Permission Scoping & Context Refresh
- [ ] **P5.1** Gate IDE bridge registration on non-sandboxed permission level in both `_create_unlocked()` (line 586) and `_restore_unlocked()` (~line 914) in `pool.py`
- [ ] **P5.2** Extract IDE refresh pattern from `session.py:595-613` into `IDEBridge.refresh_context(context)` method (encapsulates `_config` access, avoids 6x duplication)
- [ ] **P5.3** Add IDE context refresh on agent creation (`pool.py:615`, skip gracefully if bridge not connected)
- [ ] **P5.4** Add IDE context refresh alongside git refresh in `repl_commands.py` (`/cwd`:1006, `/model`:1574, `/prompt`:1310, `/gitlab`:2398)
- [ ] **P5.5** Add IDE context refresh during compaction (`session.py:1068`)
- [ ] **P5.6** Update `/ide` command (`repl_commands.py:~2745`) to get bridge from `agent.services` instead of `_shared` (respects permission gating)
- [ ] **P5.7** Add unit/integration tests for P5.1-P5.6

### Phase 6: Test Coverage Gaps
- [ ] **P6.1** Add `test_open_file` to `test_connection.py`
- [ ] **P6.2** Add `test_save_document` to `test_connection.py`
- [ ] **P6.3** Add `test_close_tab` to `test_connection.py`
- [ ] **P6.4** Add `test_close_all_diff_tabs` to `test_connection.py`

### Phase 7: Verification & Documentation
- [ ] **P7.1** Run full test suite (existing 80 + all new tests must pass)
- [ ] **P7.2** Run `ruff check nexus3/` — 0 errors
- [ ] **P7.3** Live test: IDE auto-connect, /cwd refresh, sandboxed isolation, reconnection, clean shutdown, session restore
- [ ] **P7.4** Update `nexus3/ide/README.md` with known limitations (single shared bridge, sandboxed exclusion)
- [ ] **P7.5** Update `CLAUDE.md` IDE section: refresh triggers table (6 triggers, not 1), permission scoping note

---

## Quick Reference: File Locations

| Component | File Path |
|-----------|-----------|
| IDE bridge | `nexus3/ide/bridge.py` |
| IDE connection | `nexus3/ide/connection.py` |
| IDE context formatting | `nexus3/ide/context.py` |
| IDE discovery | `nexus3/ide/discovery.py` |
| WebSocket transport | `nexus3/ide/transport.py` |
| REPL shutdown | `nexus3/cli/repl.py` (~line 1755-1784) |
| REPL confirm callback | `nexus3/cli/repl.py` (~line 365-405) |
| Session IDE refresh | `nexus3/session/session.py` (~line 595-613) |
| Agent creation | `nexus3/rpc/pool.py` (~line 580-615) |
| Agent restore | `nexus3/rpc/pool.py` (`_restore_unlocked()`, ~line 821-1036) |
| REPL commands | `nexus3/cli/repl_commands.py` |
| `/ide` command | `nexus3/cli/repl_commands.py` (~line 2740-2800) |
| IDE config schema | `nexus3/config/schema.py` (~line 317-355) |
| Bridge tests | `tests/unit/ide/test_bridge.py` |
| Connection tests | `tests/unit/ide/test_connection.py` |
| Context tests | `tests/unit/ide/test_context.py` |
| Discovery tests | `tests/unit/ide/test_discovery.py` |
| Transport tests | `tests/unit/ide/test_transport.py` |
