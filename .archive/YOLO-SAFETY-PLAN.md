# Plan: YOLO Mode Safety Improvements

## Overview

YOLO mode grants full access with no confirmations - it's intentionally dangerous and REPL-only. This plan adds safety guardrails:

1. **Warning banner** - Visible reminder every turn that YOLO is active
2. **Worker preset cleanup** - Remove legacy "worker" preset from valid options
3. **REPL-only enforcement** - Prevent RPC from sending messages to YOLO agents

## Current State

- YOLO agents can be created only via REPL (blocked in `global_dispatcher.py:179-184`)
- However, RPC CAN send messages to existing YOLO agents - security gap
- "worker" preset is legacy but still listed as valid in several places
- No visual warning when operating in YOLO mode

## Goal

Make YOLO mode's danger more visible and close the RPC loophole.

---

## Phase 1: Intent (Complete)

### YOLO Warning Banner
- Display warning at start of **every** user turn when in YOLO mode
- Red bold with ⚠️ emoji: `[bold red]⚠️ YOLO MODE - All actions execute without confirmation[/]`
- Intentionally annoying - no short version, no suppression option
- Only in REPL (where YOLO exists)

### Worker Preset Cleanup
- Remove "worker" completely - no backward compatibility
- Remove from valid preset lists AND legacy mappings
- Update documentation

### YOLO-Requires-REPL (Nuanced)
- Block RPC `send` to YOLO agents **only when REPL is not connected**
- If REPL is actively connected (user can see what happens), allow RPC send
- Return clear error when blocked: "Cannot send to YOLO agent - no REPL connected"
- Requires tracking REPL connection state per agent

---

## Phase 2: Exploration (Complete)

### Warning Banner Location

**Insert point**: `nexus3/cli/repl.py` around line 1217, after empty input check in main loop

```python
# After empty input handling, before processing:
agent = pool.get(current_agent_id)
if agent:
    perms = agent.services.get("permissions")
    if perms and perms.effective_policy.level == PermissionLevel.YOLO:
        console.print("[bold red]⚠️  YOLO MODE - All actions execute without confirmation[/]")
```

**Display patterns**: Rich console with markup (`console.print("[bold red]...[/]")`)

**Permission check**: `agent.services.get("permissions").effective_policy.level == PermissionLevel.YOLO`

### Worker Preset - Files to Clean Up (REMOVE ALL)

- `nexus3/core/presets.py:177` - worker → sandboxed mapping
- `nexus3/core/permissions.py:312-314` - worker → sandboxed mapping
- `nexus3/cli/repl_commands.py` - worker → sandboxed mapping
- `nexus3/rpc/global_dispatcher.py:180` - `valid_presets = {"trusted", "sandboxed", "worker"}`
- `nexus3/cli/arg_parser.py:128` - CLI choices include "worker"
- `nexus3/commands/core.py` - `valid_permissions` includes "worker"
- `CLAUDE.md` - mentions worker in presets documentation

**Not in `get_builtin_presets()`**: Only yolo, trusted, sandboxed are first-class (correct)

### RPC-to-YOLO Flow

**Current behavior**:
1. RPC `send` arrives at `dispatcher.py:_handle_send()`
2. No permission level check - message is processed
3. REPL shows "▶ INCOMING" notification but no YOLO warning
4. Agent executes with full YOLO permissions even if user isn't watching

**Desired behavior**:
- If YOLO agent AND no REPL connected → block with error
- If YOLO agent AND REPL connected → allow (user can see it)
- Non-YOLO agents → allow always (existing behavior)

**Implementation approach** (explored):

Use pool-based connection tracking with helper methods:

1. Add `repl_connected: bool = False` field to `Agent` dataclass in `pool.py`
2. Add helper methods to `AgentPool`:
   - `set_repl_connected(agent_id: str, connected: bool) -> None`
   - `is_repl_connected(agent_id: str) -> bool`
3. Pass pool reference to `Dispatcher` on creation
4. REPL calls `pool.set_repl_connected(old_id, False)` / `pool.set_repl_connected(new_id, True)` on agent switch
5. Dispatcher checks `self._pool.is_repl_connected(self._agent_id)` before blocking YOLO send

**"REPL connected" means**: Agent is current_agent_id in active REPL (Option A - most precise)

**Agent switch locations in repl.py** (all need connection updates):
- Line ~1244: Regular `/agent` switch
- Line ~1304: Session restore
- Line ~1352: New agent creation
- REPL startup (initial agent)
- REPL exit (clear all)

---

## Phase 3: Feasibility (Complete)

### Warning Banner
- **Feasibility**: Trivial - single `console.print()` in REPL loop
- **Risk**: None
- **Blockers**: None

### Worker Removal
- **Feasibility**: Simple - remove from ~7 files
- **Risk**: Low - worker was never officially documented, only internal
- **Blockers**: None

### RPC-to-YOLO Block
- **Feasibility**: Simple - add check in `dispatcher.py:_handle_send()`
- **Risk**: Low - clear error message explains why blocked
- **Blockers**: None
- **Consideration**: If user creates YOLO agent in REPL then tries RPC send later, they get a clear error. This is intentional - YOLO requires active supervision.

**Overall**: All three items are low-risk, isolated changes. No architectural concerns.

---

## Phase 4: Scope (Complete)

### Included in v1
- YOLO warning banner on every user turn
- Complete worker preset removal (all files)
- RPC send blocked to YOLO agents

### Deferred to Future
- None - this is a complete plan

### Explicitly Excluded
- Warning suppression options (intentionally annoying)
- Blocking other RPC methods for YOLO (status, cancel, etc. are safe read-only operations)
- Any backward compatibility for worker preset

---

## Phase 5: General Plan (Complete)

### Architecture

```
YOLO Warning Banner:
  repl.py main loop → check permission level → print warning

Worker Removal:
  Delete "worker" string from 7 files (no logic changes)

RPC-to-YOLO Block (nuanced):
  pool.py: Add repl_connected field to Agent + helper methods
  repl.py: Update connection state on agent switch
  dispatcher.py: Check connection before blocking YOLO send
```

### Implementation Approach

1. **Warning Banner**: Insert after input received, before processing. Check agent's permission level via ServiceContainer.

2. **Worker Removal**: Simple search-and-delete. No conditional logic needed since we're not maintaining backward compat.

3. **RPC Block** (nuanced):
   - Add `repl_connected: bool` field to Agent dataclass
   - Add pool helper methods: `set_repl_connected()`, `is_repl_connected()`
   - Pass pool reference to Dispatcher
   - REPL updates connection state on agent switch
   - Dispatcher checks connection before blocking YOLO send

### Error Handling

- RPC block returns proper JSON-RPC error, not HTTP error
- Error message explains WHY blocked and what to do instead

---

## Design Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| Warning frequency | Every turn | YOLO is dangerous; constant reminder is intentional |
| Warning suppression | None | If it's annoying, switch to trusted mode |
| Worker removal | Remove completely, no backward compat | Clean break, worker was never documented as supported |
| RPC block scope | Block `send` only | Creation already blocked; other methods (status, cancel) are safe |
| RPC block condition | Only when no REPL connected | If user is watching, allow RPC send to YOLO |
| "REPL connected" meaning | Agent is current_agent_id | Most precise - user is actively watching that agent |
| Connection tracking | Pool-based with helper methods | Centralized source of truth, type-safe, testable |

---

## Open Questions

1. Should RPC `cancel` also be blocked for YOLO agents? (Probably not - canceling is safe)

---

## Phase 6: Codebase Validation (Complete)

### Warning Banner Validation

- **Insert point confirmed**: `repl.py:1217` - after empty input check (`if not user_input.strip(): continue`)
- **Variables in scope**: `pool`, `current_agent_id`, `console` all available
- **Permission access pattern**: `agent.services.get("permissions").effective_policy.level`
- **Import needed**: `PermissionLevel` from `nexus3.core.permissions`

### Worker Preset Validation

All locations confirmed with exact line numbers:

| File | Lines | Content |
|------|-------|---------|
| `nexus3/core/permissions.py` | 312-314 | `if preset_name == "worker": preset_name = "sandboxed"` |
| `nexus3/core/presets.py` | 176-178 | `if extends == "worker": extends = "sandboxed"` |
| `nexus3/rpc/global_dispatcher.py` | 180 | `valid_presets = {"trusted", "sandboxed", "worker"}` |
| `nexus3/rpc/global_dispatcher.py` | 126 | Docstring mentions worker |
| `nexus3/rpc/global_dispatcher.py` | 291, 293, 322 | `if effective_preset in ("sandboxed", "worker")` |
| `nexus3/cli/repl.py` | 1072-1073 | `elif p_lower in ("--worker", "-w"): perm = "worker"` |

### RPC Block Validation

- **Method signature**: `async def _handle_send(self, params: dict[str, Any]) -> dict[str, Any]:`
- **Location**: `dispatcher.py:114`
- **Permissions access**: Via `self._session._services.get("permissions")`
- **Insert after**: Line 140 (after content validation, before processing)
- **Import needed**: `PermissionLevel` from `nexus3.core.permissions`
- **Pool access**: Dispatcher needs pool reference (pass at init, already done for some cases)

### Connection Tracking Validation

- **Agent dataclass**: `pool.py:246-277` - add `repl_connected: bool = False`
- **Pool helper methods**: Add to AgentPool class
- **Dispatcher init**: `pool.py:590-595` - already passes some refs, add pool
- **REPL switch points**: Lines ~1244, ~1304, ~1352 (all use same pattern)

### Corrections Applied

- Changed from unconditional block to nuanced (check repl_connected)

---

## Phase 7: Detailed Plan (Complete)

### 1. YOLO Warning Banner

**File**: `nexus3/cli/repl.py`

**Add import** (near line 45 with other core imports):
```python
from nexus3.core.permissions import PermissionLevel
```

**Insert after line 1217** (after `continue` for empty input):
```python
                # YOLO mode warning - every turn
                agent = pool.get(current_agent_id)
                if agent:
                    perms = agent.services.get("permissions")
                    if perms and perms.effective_policy.level == PermissionLevel.YOLO:
                        console.print("[bold red]⚠️  YOLO MODE - All actions execute without confirmation[/]")
```

### 2. RPC-to-YOLO Block (Nuanced)

#### 2a. Add connection tracking to Agent

**File**: `nexus3/rpc/pool.py`

**Add field to Agent dataclass** (around line 277):
```python
    repl_connected: bool = False
```

**Add helper methods to AgentPool class**:
```python
    def set_repl_connected(self, agent_id: str, connected: bool) -> None:
        """Set REPL connection state for an agent."""
        agent = self._agents.get(agent_id)
        if agent:
            agent.repl_connected = connected

    def is_repl_connected(self, agent_id: str) -> bool:
        """Check if agent is connected to REPL."""
        agent = self._agents.get(agent_id)
        return agent.repl_connected if agent else False
```

#### 2b. Pass pool to Dispatcher

**File**: `nexus3/rpc/dispatcher.py`

**Update __init__** to accept pool:
```python
def __init__(
    self,
    session: Session,
    context: ContextManager | None = None,
    agent_id: str | None = None,
    log_multiplexer: LogMultiplexer | None = None,
    pool: "AgentPool | None" = None,  # NEW
) -> None:
    # ... existing code ...
    self._pool = pool
```

**Add import** (with other imports):
```python
from nexus3.core.permissions import PermissionLevel
```

**Insert after line 140** (after content validation in `_handle_send`):
```python
        # Block RPC sends to YOLO agents when no REPL connected
        if self._session._services:
            permissions = self._session._services.get("permissions")
            if permissions and permissions.effective_policy.level == PermissionLevel.YOLO:
                if not (self._pool and self._pool.is_repl_connected(self._agent_id)):
                    raise InvalidParamsError(
                        "Cannot send to YOLO agent - no REPL connected"
                    )
```

#### 2c. Update pool to pass itself to Dispatcher

**File**: `nexus3/rpc/pool.py` (around line 590)

Update dispatcher creation:
```python
dispatcher = Dispatcher(
    session,
    context=context,
    agent_id=effective_id,
    log_multiplexer=self._log_multiplexer,
    pool=self,  # NEW
)
```

#### 2d. REPL updates connection state

**File**: `nexus3/cli/repl.py`

**On agent switch** (lines ~1244, ~1304, ~1352):
```python
# Before switching away from old agent
pool.set_repl_connected(current_agent_id, False)

# After switching to new agent
current_agent_id = new_id
pool.set_repl_connected(new_id, True)
```

**On REPL startup** (after initial agent creation):
```python
pool.set_repl_connected(current_agent_id, True)
```

**On REPL exit** (cleanup):
```python
pool.set_repl_connected(current_agent_id, False)
```

### 3. Worker Preset Removal

**File**: `nexus3/core/permissions.py` - Delete lines 312-314:
```python
    # Handle legacy "worker" preset by mapping to sandboxed
    if preset_name == "worker":
        preset_name = "sandboxed"
```

**File**: `nexus3/core/presets.py` - Delete lines 176-178:
```python
            # Handle legacy "worker" reference
            if extends == "worker":
                extends = "sandboxed"
```

**File**: `nexus3/rpc/global_dispatcher.py`:
- Line 180: Change `{"trusted", "sandboxed", "worker"}` → `{"trusted", "sandboxed"}`
- Line 126: Remove "worker" from docstring
- Lines 291, 293, 322: Change `("sandboxed", "worker")` → `"sandboxed"`

**File**: `nexus3/cli/repl.py` - Delete lines 1072-1073:
```python
                elif p_lower in ("--worker", "-w"):
                    perm = "worker"
```

**File**: `nexus3/cli/arg_parser.py` - Remove "worker" from choices

**File**: `nexus3/commands/core.py` - Remove "worker" from valid_permissions

### 4. Documentation Update

**File**: `CLAUDE.md` - Remove all mentions of "worker" preset

---

## Files to Modify

| File | Changes |
|------|---------|
| `nexus3/rpc/pool.py` | Add `repl_connected` field, helper methods, pass pool to Dispatcher |
| `nexus3/rpc/dispatcher.py` | Accept pool param, check connection before blocking YOLO |
| `nexus3/cli/repl.py` | YOLO warning banner + connection state updates on switch |
| `nexus3/rpc/global_dispatcher.py` | Remove "worker" from valid_presets |
| `nexus3/cli/arg_parser.py` | Remove "worker" from CLI choices |
| `nexus3/commands/core.py` | Remove "worker" from valid_permissions |
| `nexus3/core/presets.py` | Remove worker → sandboxed mapping |
| `nexus3/core/permissions.py` | Remove worker → sandboxed mapping |
| `nexus3/cli/repl_commands.py` | Remove worker → sandboxed mapping |
| `CLAUDE.md` | Remove worker from presets documentation |

---

## Phase 8: Final Validation (Complete)

### Line Numbers Verified
| Component | File | Lines | Status |
|-----------|------|-------|--------|
| Agent dataclass | pool.py | 245-277 | ✓ Add field at 278 |
| Dispatcher.__init__ | dispatcher.py | 36-50 | ✓ Add pool param |
| TYPE_CHECKING block | dispatcher.py | 18-20 | ✓ Add AgentPool import |
| Dispatcher creation | pool.py | 589-595 | ✓ Add pool=self |
| REPL startup | repl.py | 464 | ✓ current_agent_id set |
| REPL /agent switch | repl.py | 1244 | ✓ current_agent_id = new_id |
| REPL session restore | repl.py | 1304 | ✓ current_agent_id = ... |
| REPL new agent | repl.py | 1352 | ✓ current_agent_id = ... |
| REPL exit | repl.py | 1228 | ✓ break for /quit |

### Confirmed Working
- All line numbers accurate (no drift)
- TYPE_CHECKING already configured in dispatcher.py
- `InvalidParamsError` already imported in dispatcher.py
- Whisper mode won't interfere (doesn't change current_agent_id)
- No circular import issues

### Imports Needed
- `repl.py`: Add `PermissionLevel` to existing import from `nexus3.core.permissions`
- `dispatcher.py`: Add `from nexus3.core.permissions import PermissionLevel`
- `dispatcher.py`: Add `from nexus3.rpc.pool import AgentPool` in TYPE_CHECKING block

### Risk Assessment
**LOW** - All changes isolated, no circular imports, existing patterns support implementation.

---

## Implementation Checklist

### Phase 1: YOLO Warning Banner
- [ ] **P1.1** Add `PermissionLevel` import to `repl.py`
- [ ] **P1.2** Add YOLO warning print after empty input check in main loop

### Phase 2: Connection Tracking Infrastructure (required for Phase 3)
- [ ] **P2.1** Add `repl_connected: bool = False` field to Agent dataclass in `pool.py`
- [ ] **P2.2** Add `set_repl_connected()` helper method to AgentPool
- [ ] **P2.3** Add `is_repl_connected()` helper method to AgentPool
- [ ] **P2.4** Update Dispatcher.__init__ to accept pool parameter
- [ ] **P2.5** Update Dispatcher creation in pool.py to pass `pool=self`

### Phase 3: RPC-to-YOLO Block (requires Phase 2)
- [ ] **P3.1** Add `PermissionLevel` import to `dispatcher.py`
- [ ] **P3.2** Add YOLO+connection check in `_handle_send()` that raises error when no REPL

### Phase 4: REPL Connection Updates
- [ ] **P4.1** Set connection on REPL startup (initial agent)
- [ ] **P4.2** Update connection on `/agent` switch (~line 1244)
- [ ] **P4.3** Update connection on session restore (~line 1304)
- [ ] **P4.4** Update connection on new agent creation (~line 1352)
- [ ] **P4.5** Clear connection on REPL exit

### Phase 5: Worker Preset Removal (can parallel with P1-P4)
- [ ] **P5.1** Remove worker mapping from `nexus3/core/permissions.py:312-314`
- [ ] **P5.2** Remove worker mapping from `nexus3/core/presets.py:176-178`
- [ ] **P5.3** Remove worker from `nexus3/rpc/global_dispatcher.py` (4 locations)
- [ ] **P5.4** Remove worker flag from `nexus3/cli/repl.py:1072-1073`
- [ ] **P5.5** Remove worker from `nexus3/cli/arg_parser.py`
- [ ] **P5.6** Remove worker from `nexus3/commands/core.py`

### Phase 6: Documentation
- [ ] **P6.1** Remove "worker" from `CLAUDE.md` Built-in Presets table
- [ ] **P6.2** Update `CLAUDE.md` RPC Agent Permission Quirks section to clarify YOLO is REPL-only
- [ ] **P6.3** Update `nexus3/rpc/README.md` with YOLO RPC blocking behavior
- [ ] **P6.4** Ensure error messages in code clearly explain why YOLO RPC send is blocked

### Phase 7: Testing
- [ ] **P7.1** Live test: Start REPL in YOLO mode, verify warning appears every turn
- [ ] **P7.2** Live test: Create YOLO agent in REPL, RPC send should SUCCEED (REPL connected)
- [ ] **P7.3** Live test: Switch to different agent, RPC send to YOLO should FAIL (no REPL)
- [ ] **P7.4** Live test: Try to create agent with `--preset worker`, verify error
- [ ] **P7.5** Run existing test suite to check for regressions

---

## Quick Reference

| Item | File | Line |
|------|------|------|
| YOLO warning insert | `nexus3/cli/repl.py` | After 1217 |
| Agent dataclass | `nexus3/rpc/pool.py` | 246-277 |
| Dispatcher creation | `nexus3/rpc/pool.py` | 590-595 |
| RPC block insert | `nexus3/rpc/dispatcher.py` | After 140 |
| REPL agent switch | `nexus3/cli/repl.py` | ~1244, ~1304, ~1352 |
| Worker in permissions | `nexus3/core/permissions.py` | 312-314 |
| Worker in presets | `nexus3/core/presets.py` | 176-178 |
| Worker in global_dispatcher | `nexus3/rpc/global_dispatcher.py` | 126, 180, 291, 293, 322 |
| Worker flag in repl | `nexus3/cli/repl.py` | 1072-1073 |
