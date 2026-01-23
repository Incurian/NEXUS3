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

### YOLO-Requires-REPL
- Block RPC `send` to agents with YOLO permission level
- Return clear error: "Cannot send to YOLO agent via RPC - YOLO requires interactive REPL"

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

**Block point**: Add check in `dispatcher.py:_handle_send()` before processing

```python
# In _handle_send(), after getting agent:
if agent.services.get("permissions").effective_policy.level == PermissionLevel.YOLO:
    raise JsonRpcError(
        code=-32001,
        message="Cannot send to YOLO agent via RPC - YOLO requires interactive REPL"
    )
```

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

No new modules or classes needed. All changes are surgical edits to existing code.

```
YOLO Warning Banner:
  repl.py main loop → check permission level → print warning

Worker Removal:
  Delete "worker" string from 7 files (no logic changes)

RPC-to-YOLO Block:
  dispatcher._handle_send() → check permission level → raise JsonRpcError
```

### Implementation Approach

1. **Warning Banner**: Insert after input received, before processing. Check agent's permission level via ServiceContainer.

2. **Worker Removal**: Simple search-and-delete. No conditional logic needed since we're not maintaining backward compat.

3. **RPC Block**: Add permission check at start of `_handle_send()`. Return JSON-RPC error code -32001 (custom app error) with clear message.

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

### Corrections Applied

None needed - original plan was accurate.

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

### 2. RPC-to-YOLO Block

**File**: `nexus3/rpc/dispatcher.py`

**Add import** (with other imports):
```python
from nexus3.core.permissions import PermissionLevel
```

**Insert after line 140** (after content validation in `_handle_send`):
```python
        # Block RPC sends to YOLO agents - YOLO requires interactive REPL
        if self._session._services:
            permissions = self._session._services.get("permissions")
            if permissions and permissions.effective_policy.level == PermissionLevel.YOLO:
                raise InvalidParamsError(
                    "Cannot send to YOLO agent via RPC - YOLO requires interactive REPL"
                )
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
| `nexus3/cli/repl.py` | Add YOLO warning banner in main loop |
| `nexus3/rpc/dispatcher.py` | Block RPC send to YOLO agents |
| `nexus3/rpc/global_dispatcher.py` | Remove "worker" from valid_presets |
| `nexus3/cli/arg_parser.py` | Remove "worker" from CLI choices |
| `nexus3/commands/core.py` | Remove "worker" from valid_permissions |
| `nexus3/core/presets.py` | Remove worker → sandboxed mapping |
| `nexus3/core/permissions.py` | Remove worker → sandboxed mapping |
| `nexus3/cli/repl_commands.py` | Remove worker → sandboxed mapping |
| `CLAUDE.md` | Remove worker from presets documentation |

---

## Phase 8: Final Validation (Complete)

Subagent verified all implementation details:

### Confirmed Working
- All line numbers accurate (no drift since exploration)
- All variables in scope at insertion points (`pool`, `current_agent_id`, `console`)
- `InvalidParamsError` already imported in dispatcher.py
- `self._session._services` pattern is correct for permissions access
- Rich console markup will render correctly

### Imports Needed (as noted in Phase 7)
- `repl.py`: Add `PermissionLevel` to existing import from `nexus3.core.permissions`
- `dispatcher.py`: Add new import `from nexus3.core.permissions import PermissionLevel`

### Risk Assessment
**LOW** - All changes isolated, no circular imports, no dependency changes.

---

## Implementation Checklist

### Phase 1: YOLO Warning Banner
- [ ] **P1.1** Add `PermissionLevel` import to `repl.py`
- [ ] **P1.2** Add YOLO warning print after empty input check in main loop

### Phase 2: RPC-to-YOLO Block
- [ ] **P2.1** Add `PermissionLevel` import to `dispatcher.py`
- [ ] **P2.2** Add YOLO check in `_handle_send()` that raises error

### Phase 3: Worker Preset Removal (can parallel)
- [ ] **P3.1** Remove worker mapping from `nexus3/core/permissions.py:312-314`
- [ ] **P3.2** Remove worker mapping from `nexus3/core/presets.py:176-178`
- [ ] **P3.3** Remove worker from `nexus3/rpc/global_dispatcher.py` (4 locations)
- [ ] **P3.4** Remove worker flag from `nexus3/cli/repl.py:1072-1073`
- [ ] **P3.5** Remove worker from `nexus3/cli/arg_parser.py`
- [ ] **P3.6** Remove worker from `nexus3/commands/core.py`

### Phase 4: Documentation
- [ ] **P4.1** Remove worker from `CLAUDE.md` presets documentation

### Phase 5: Testing
- [ ] **P5.1** Live test: Start REPL in YOLO mode, verify warning appears every turn
- [ ] **P5.2** Live test: Create YOLO agent in REPL, try RPC send, verify error
- [ ] **P5.3** Live test: Try to create agent with `--preset worker`, verify error
- [ ] **P5.4** Run existing test suite to check for regressions

---

## Quick Reference

| Item | File | Line |
|------|------|------|
| YOLO warning insert | `nexus3/cli/repl.py` | After 1217 |
| RPC block insert | `nexus3/rpc/dispatcher.py` | After 140 |
| Worker in permissions | `nexus3/core/permissions.py` | 312-314 |
| Worker in presets | `nexus3/core/presets.py` | 176-178 |
| Worker in global_dispatcher | `nexus3/rpc/global_dispatcher.py` | 126, 180, 291, 293, 322 |
| Worker flag in repl | `nexus3/cli/repl.py` | 1072-1073 |
