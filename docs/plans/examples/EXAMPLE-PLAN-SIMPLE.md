# Example Implementation Plan (Simple)

> **This is a reference example for the Planning SOP.** See `CLAUDE.md` for the planning process documentation. This plan demonstrates the standard structure for focused single-feature implementations. For large multi-phase features, see `EXAMPLE-PLAN-COMPLEX.md`.

---

# Plan: Allow Sandboxed Agents to Send to Parent

## Overview

Enable sandboxed agents to use `nexus_send` but **only to their parent agent**. This allows child agents to report back results without breaking the security sandbox.

**Current state:**
- Sandboxed agents have ALL nexus_* tools disabled via preset
- Parent-child tracking already exists (`parent_agent_id` in `AgentPermissions`)
- Permission system is all-or-nothing at tool level (no parameter validation)

**Goal:** Parameter-level permission validation for `nexus_send` targeting.

---

## Design Decision: Where to Validate

### Option A: In PermissionEnforcer (Recommended)

Add target validation to the centralized permission enforcer.

**Pros:**
- Single source of truth for all permission logic
- Reusable for other tools that might need target restrictions
- Consistent with existing path validation pattern
- Easy to extend (e.g., allow sending to children too)

**Cons:**
- Requires extending ToolPermission dataclass
- Enforcer needs access to agent relationships

### Option B: In NexusSendSkill

Add sandboxed-specific check directly in the skill.

**Pros:**
- Simpler, no permission system changes
- Localized change

**Cons:**
- Scatters permission logic across codebase
- Harder to audit/reason about security
- Doesn't extend to other tools

### Decision: Option A

Centralizing in the enforcer maintains the architecture principle that all permission checks go through one place.

---

## Implementation

### Phase 1: Extend ToolPermission (presets.py)

Add `allowed_targets` field to express target restrictions:

```python
@dataclass
class ToolPermission:
    enabled: bool = True
    allowed_paths: list[Path] | None = None
    timeout: float | None = None
    requires_confirmation: bool | None = None
    # NEW: Target agent restrictions for nexus_* tools
    allowed_targets: TargetRestriction | None = None  # None = unrestricted
```

Define target restriction type:

```python
from typing import Literal

# Special values for relationship-based targeting
TargetRestriction = list[str] | Literal["parent"] | Literal["children"] | Literal["family"]

# Semantics:
# - None: No restriction (can send to any agent)
# - ["parent"]: Can only send to parent_agent_id
# - ["children"]: Can only send to agents in child_agent_ids
# - ["family"]: Can send to parent or children
# - ["agent-1", "agent-2"]: Explicit allowlist of agent IDs
```

**File:** `nexus3/core/presets.py`

**Changes:**
1. Add `allowed_targets` field to `ToolPermission` dataclass
2. Add `to_dict()` / `from_dict()` serialization
3. Update sandboxed preset to enable nexus_send with parent-only restriction

```python
"sandboxed": PermissionPreset(
    name="sandboxed",
    level=PermissionLevel.SANDBOXED,
    description="Immutable sandbox, no execution/agent management",
    network_access=False,
    tool_permissions={
        # Execution tools disabled
        "bash_safe": ToolPermission(enabled=False),
        "shell_UNSAFE": ToolPermission(enabled=False),
        "run_python": ToolPermission(enabled=False),
        # Agent management - mostly disabled
        "nexus_create": ToolPermission(enabled=False),
        "nexus_destroy": ToolPermission(enabled=False),
        "nexus_shutdown": ToolPermission(enabled=False),
        "nexus_cancel": ToolPermission(enabled=False),
        "nexus_status": ToolPermission(enabled=False),
        # NEW: nexus_send enabled but parent-only
        "nexus_send": ToolPermission(enabled=True, allowed_targets="parent"),
    },
),
```

### Phase 2: Extend PermissionEnforcer (enforcer.py)

Add target validation check in the enforcer.

**File:** `nexus3/session/enforcer.py`

**New method:**

```python
# Tools that take agent_id as a target
AGENT_TARGET_TOOLS = frozenset({
    "nexus_send", "nexus_status", "nexus_cancel", "nexus_destroy"
})

def _check_target_allowed(
    self,
    tool_call: ToolCall,
    permissions: AgentPermissions,
) -> ToolResult | None:
    """Check if target agent is allowed by tool permission."""
    if tool_call.name not in AGENT_TARGET_TOOLS:
        return None

    tool_perm = permissions.tool_permissions.get(tool_call.name)
    if not tool_perm or tool_perm.allowed_targets is None:
        return None  # No restriction

    target_agent_id = tool_call.arguments.get("agent_id", "")
    if not target_agent_id:
        return None  # Will fail later with "no agent_id provided"

    allowed = tool_perm.allowed_targets

    # Handle special relationship-based restrictions
    if allowed == "parent":
        if permissions.parent_agent_id and target_agent_id == permissions.parent_agent_id:
            return None  # Allowed
        return ToolResult(
            error=f"Tool '{tool_call.name}' can only target parent agent "
                  f"('{permissions.parent_agent_id or 'none'}')"
        )

    elif allowed == "children":
        child_ids = self._services.get_child_agent_ids() if self._services else None
        if child_ids and target_agent_id in child_ids:
            return None  # Allowed
        return ToolResult(
            error=f"Tool '{tool_call.name}' can only target child agents"
        )

    elif allowed == "family":
        # Parent or children
        if permissions.parent_agent_id and target_agent_id == permissions.parent_agent_id:
            return None
        child_ids = self._services.get_child_agent_ids() if self._services else None
        if child_ids and target_agent_id in child_ids:
            return None
        return ToolResult(
            error=f"Tool '{tool_call.name}' can only target parent or child agents"
        )

    elif isinstance(allowed, list):
        # Explicit allowlist
        if target_agent_id in allowed:
            return None
        return ToolResult(
            error=f"Tool '{tool_call.name}' cannot target agent '{target_agent_id}'"
        )

    return None  # Unknown restriction type, allow (fail-open for forward compat)
```

**Modify `check_all()`:**

```python
def check_all(
    self,
    tool_call: ToolCall,
    permissions: AgentPermissions,
) -> ToolResult | None:
    # Check tool enabled
    error = self._check_enabled(tool_call.name, permissions)
    if error:
        return error

    # Check action allowed
    error = self._check_action_allowed(tool_call.name, permissions)
    if error:
        return error

    # NEW: Check target agent allowed (for nexus_* tools)
    error = self._check_target_allowed(tool_call, permissions)
    if error:
        return error

    # Check path restrictions for ALL paths in tool call
    for target_path in self.extract_target_paths(tool_call):
        error = self._check_path_allowed(tool_call.name, target_path, permissions)
        if error:
            return error

    return None
```

### Phase 3: Update ServiceContainer Interface

The enforcer needs access to child_agent_ids for "children" and "family" restrictions.

**File:** `nexus3/skill/services.py`

Verify `get_child_agent_ids()` exists (it does - used in `_should_skip_confirmation`).

No changes needed - method already exists:
```python
def get_child_agent_ids(self) -> set[str] | None:
    """Get set of child agent IDs (for permission-free destroy)."""
    return self.get("child_agent_ids")
```

### Phase 4: Handle Root Agents (Edge Case)

A root agent has no parent (`parent_agent_id = None`). If a root sandboxed agent tries to nexus_send with `allowed_targets="parent"`, it should fail gracefully.

This is already handled in Phase 2's `_check_target_allowed()`:
```python
if allowed == "parent":
    if permissions.parent_agent_id and target_agent_id == permissions.parent_agent_id:
        return None  # Allowed
    return ToolResult(
        error=f"Tool '{tool_call.name}' can only target parent agent "
              f"('{permissions.parent_agent_id or 'none'}')"
    )
```

If `parent_agent_id` is None, the message will say "can only target parent agent ('none')" which makes it clear there's no valid target.

### Phase 5: Serialization (RPC Transport)

Update `ToolPermission.to_dict()` and `from_dict()` to handle `allowed_targets`.

**File:** `nexus3/core/presets.py`

```python
def to_dict(self) -> dict[str, Any]:
    result: dict[str, Any] = {"enabled": self.enabled}
    if self.allowed_paths is not None:
        result["allowed_paths"] = [str(p) for p in self.allowed_paths]
    if self.timeout is not None:
        result["timeout"] = self.timeout
    if self.requires_confirmation is not None:
        result["requires_confirmation"] = self.requires_confirmation
    # NEW
    if self.allowed_targets is not None:
        result["allowed_targets"] = self.allowed_targets
    return result

@classmethod
def from_dict(cls, data: dict[str, Any]) -> ToolPermission:
    allowed = data.get("allowed_paths")
    return cls(
        enabled=data.get("enabled", True),
        allowed_paths=[Path(p) for p in allowed] if allowed is not None else None,
        timeout=data.get("timeout"),
        requires_confirmation=data.get("requires_confirmation"),
        # NEW
        allowed_targets=data.get("allowed_targets"),
    )
```

---

## Files to Modify

| File | Change |
|------|--------|
| `nexus3/core/presets.py` | Add `allowed_targets` to ToolPermission, update sandboxed preset |
| `nexus3/session/enforcer.py` | Add `_check_target_allowed()`, call from `check_all()` |
| `tests/unit/core/test_presets.py` | Test serialization of allowed_targets |
| `tests/unit/session/test_enforcer.py` | Test target validation logic |
| `tests/integration/test_sandboxed_parent_send.py` | **New** - E2E test of sandboxed→parent messaging |

---

## Testing

### Unit Tests

**test_presets.py:**
- `test_allowed_targets_serialization` - to_dict/from_dict roundtrip
- `test_sandboxed_preset_has_nexus_send_enabled` - verify new preset config

**test_enforcer.py:**
- `test_check_target_parent_allowed` - parent_agent_id matches target
- `test_check_target_parent_denied` - target is not parent
- `test_check_target_parent_no_parent` - root agent with parent restriction
- `test_check_target_children_allowed` - target in child_ids
- `test_check_target_children_denied` - target not in child_ids
- `test_check_target_family_allows_parent` - family includes parent
- `test_check_target_family_allows_child` - family includes children
- `test_check_target_explicit_list` - allowlist of agent IDs
- `test_check_target_no_restriction` - allowed_targets=None passes anything

### Integration Tests

**test_sandboxed_parent_send.py:**
```python
async def test_sandboxed_child_can_send_to_parent():
    """Sandboxed child agent can send message to parent."""
    pool = AgentPool(...)

    # Create parent (trusted)
    await pool.create(AgentConfig(agent_id="parent", preset="trusted"))

    # Create sandboxed child
    await pool.create(AgentConfig(
        agent_id="child",
        preset="sandboxed",
        parent_agent_id="parent",
        parent_permissions=parent_permissions,
    ))

    # Child sends to parent - should succeed
    child_agent = pool.get("child")
    result = await child_agent.dispatcher.dispatch(ToolCall(
        name="nexus_send",
        arguments={"agent_id": "parent", "content": "Hello from child"}
    ))
    assert result.error is None

async def test_sandboxed_child_cannot_send_to_sibling():
    """Sandboxed child agent cannot send to sibling agent."""
    pool = AgentPool(...)

    # Create parent and two children
    await pool.create(AgentConfig(agent_id="parent", preset="trusted"))
    await pool.create(AgentConfig(agent_id="child1", preset="sandboxed", parent_agent_id="parent", ...))
    await pool.create(AgentConfig(agent_id="child2", preset="sandboxed", parent_agent_id="parent", ...))

    # Child1 tries to send to Child2 - should fail
    child1_agent = pool.get("child1")
    result = await child1_agent.dispatcher.dispatch(ToolCall(
        name="nexus_send",
        arguments={"agent_id": "child2", "content": "Hello sibling"}
    ))
    assert "can only target parent agent" in result.error

async def test_sandboxed_root_cannot_send():
    """Root sandboxed agent (no parent) cannot send to anyone."""
    pool = AgentPool(...)

    # Create sandboxed agent with no parent
    await pool.create(AgentConfig(agent_id="lonely", preset="sandboxed"))

    agent = pool.get("lonely")
    result = await agent.dispatcher.dispatch(ToolCall(
        name="nexus_send",
        arguments={"agent_id": "anyone", "content": "Hello?"}
    ))
    assert "can only target parent agent ('none')" in result.error
```

### Live Testing

```bash
# Start server
NEXUS_DEV=1 .venv/bin/python -m nexus3 --serve 9000 &

# Create parent agent
.venv/bin/python -m nexus3 rpc create parent --preset trusted --port 9000

# Create sandboxed child
.venv/bin/python -m nexus3 rpc create child --preset sandboxed --port 9000

# ... hmm, we need a way to set parent_agent_id via CLI

# Alternative: test via REPL with /create commands
nexus3 --fresh
> /create parent --trusted
> /agent parent
> Create a sandboxed worker agent named "child" and send it a task
# (agent uses nexus_create which sets parent_agent_id automatically)
# Then the child should be able to nexus_send back to parent
```

---

## Future Extensions

### 1. Enable nexus_status for Sandboxed

With target restrictions, we could also allow sandboxed agents to check their parent's status:

```python
"nexus_status": ToolPermission(enabled=True, allowed_targets="parent"),
```

This lets children know if parent is still alive / how many tokens remain.

### 2. "Family" Communication

Allow sandboxed agents to talk to siblings via the "family" restriction:

```python
"nexus_send": ToolPermission(enabled=True, allowed_targets="family"),
```

This would enable peer-to-peer coordination among sandboxed workers.

### 3. Per-Agent Dynamic Targets

Instead of just "parent"/"children"/"family", allow explicit agent IDs:

```python
"nexus_send": ToolPermission(
    enabled=True,
    allowed_targets=["coordinator", "logger"]  # Explicit allowlist
),
```

This is already supported in the implementation above.

---

## Effort Estimate

| Phase | Description | LOC |
|-------|-------------|-----|
| 1 | ToolPermission extension | ~20 |
| 2 | Enforcer target validation | ~60 |
| 3 | ServiceContainer (no changes) | 0 |
| 4 | Edge case handling (covered in 2) | 0 |
| 5 | Serialization | ~10 |
| Tests | Unit + integration | ~150 |
| **Total** | | **~240 LOC** |

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Breaking existing sandboxed agents | No - they currently can't use nexus_send at all, so enabling with restriction is additive |
| Complexity creep in permission system | Keep allowed_targets simple (just these 4 cases), document clearly |
| Performance (checking child_ids) | child_ids is a set, O(1) lookup; called once per nexus_* tool invocation |
| Forward compatibility | Unknown restriction values fail-open with warning in logs |

---

## Decision Log

| Question | Decision | Rationale |
|----------|----------|-----------|
| Where to validate? | Enforcer | Centralized permission logic |
| What restriction types? | parent, children, family, list | Covers likely use cases without over-engineering |
| Fail-open or fail-closed for unknown types? | Fail-open with warning | Forward compat if we add new types |
| Enable nexus_status too? | Defer | Start minimal, extend later |

---

## Codebase Validation Notes

*Validated against NEXUS3 codebase on 2026-01-23*

### Confirmed Patterns

| Aspect | Status | Notes |
|--------|--------|-------|
| ToolPermission dataclass | ✓ Exists | In `nexus3/core/presets.py`, has to_dict/from_dict |
| PermissionEnforcer class | ✓ Exists | In `nexus3/session/enforcer.py`, has check_all() |
| ServiceContainer.get_child_agent_ids() | ✓ Exists | Already implemented, returns set[str] or None |
| AgentPermissions.parent_agent_id | ✓ Exists | Field exists with serialization support |
| ToolCall.name & arguments | ✓ Exists | Frozen dataclass in `nexus3/core/types.py` |
| Sandboxed preset | ✓ Exists | nexus_send currently disabled |

### Corrections Required

1. **Missing TargetRestriction Type** - The plan references a union type `TargetRestriction = list[str] | Literal["parent"] | Literal["children"] | Literal["family"]` but never defines it. Must be added to `nexus3/core/presets.py`.

2. **Import Location Wrong** - Plan references `nexus3/core/policy` for ToolPermission, but actual location is `nexus3/core/presets.py`. Current enforcer.py has wrong TYPE_CHECKING import.

3. **Runtime Import Needed** - Enforcer imports ToolPermission under TYPE_CHECKING only, but `_check_target_allowed()` needs runtime access. Must add runtime import from `nexus3.core.presets`.

### Pre-Implementation Fix (Required)

Add to `nexus3/core/presets.py` after imports, before ToolPermission class:

```python
from typing import Literal

TargetRestriction = list[str] | Literal["parent"] | Literal["children"] | Literal["family"]
```

Add to `nexus3/session/enforcer.py` at top (outside TYPE_CHECKING):

```python
from nexus3.core.presets import ToolPermission  # Runtime import
```

---

## Implementation Checklist

Use this checklist to track implementation progress. Each item can be assigned to a task agent.

### Phase 0: Pre-Implementation Fixes

- [ ] **P0.1** Add `TargetRestriction` type alias to `nexus3/core/presets.py`
- [ ] **P0.2** Add runtime import of ToolPermission to `nexus3/session/enforcer.py`
- [ ] **P0.3** Fix TYPE_CHECKING import location (policy.py → presets.py)

### Phase 1: Extend ToolPermission

- [ ] **P1.1** Add `allowed_targets: TargetRestriction | None = None` field to ToolPermission dataclass
- [ ] **P1.2** Update `ToolPermission.to_dict()` to serialize `allowed_targets`
- [ ] **P1.3** Update `ToolPermission.from_dict()` to deserialize `allowed_targets`
- [ ] **P1.4** Add unit tests for ToolPermission serialization with allowed_targets

### Phase 2: Extend PermissionEnforcer

- [ ] **P2.1** Add `AGENT_TARGET_TOOLS` constant (frozenset of tool names)
- [ ] **P2.2** Implement `_check_target_allowed()` method
- [ ] **P2.3** Add call to `_check_target_allowed()` in `check_all()` method
- [ ] **P2.4** Add unit tests for target validation logic:
  - [ ] Test parent allowed (target matches parent_agent_id)
  - [ ] Test parent denied (target != parent)
  - [ ] Test parent denied (no parent - root agent)
  - [ ] Test children allowed (target in child_ids)
  - [ ] Test children denied (target not in child_ids)
  - [ ] Test family allows parent
  - [ ] Test family allows child
  - [ ] Test explicit list allowed
  - [ ] Test no restriction passes anything

### Phase 3: Update Sandboxed Preset

- [ ] **P3.1** Change sandboxed preset's nexus_send from `enabled=False` to `enabled=True, allowed_targets="parent"`
- [ ] **P3.2** Verify no regressions in existing sandboxed agent behavior

### Phase 4: Integration Testing

- [ ] **P4.1** Integration test: sandboxed child sends to parent (should succeed)
- [ ] **P4.2** Integration test: sandboxed child sends to sibling (should fail)
- [ ] **P4.3** Integration test: root sandboxed agent sends to anyone (should fail with "no parent" message)
- [ ] **P4.4** Integration test: trusted agent creates sandboxed child, child reports back

### Phase 5: Live Testing

- [ ] **P5.1** Live test via REPL with actual agents
- [ ] **P5.2** Verify error messages are clear and helpful

### Phase 6: Documentation

- [ ] **P6.1** Update `CLAUDE.md` Permission System section with `allowed_targets` behavior
- [ ] **P6.2** Update `CLAUDE.md` RPC Agent Permission Quirks to note sandboxed agents can now send to parent
- [ ] **P6.3** Update `nexus3/session/README.md` with target validation in enforcer

---

## Quick Reference: File Locations

| Component | File Path |
|-----------|-----------|
| ToolPermission dataclass | `nexus3/core/presets.py` |
| TargetRestriction type (to add) | `nexus3/core/presets.py` |
| PermissionEnforcer | `nexus3/session/enforcer.py` |
| AgentPermissions | `nexus3/core/permissions.py` |
| ToolCall | `nexus3/core/types.py` |
| ServiceContainer | `nexus3/skill/services.py` |
| Sandboxed preset | `nexus3/core/presets.py` |
| Unit tests (existing) | `tests/unit/core/test_presets.py` |
| Unit tests (enforcer) | `tests/unit/session/test_enforcer.py` |
| Integration tests | `tests/integration/test_sandboxed_parent_send.py` |

---

## Target Restriction Reference

| Value | Meaning |
|-------|---------|
| `None` | No restriction - can send to any agent |
| `"parent"` | Can only send to parent_agent_id |
| `"children"` | Can only send to agents in child_agent_ids |
| `"family"` | Can send to parent OR children |
| `["id1", "id2"]` | Explicit allowlist of agent IDs |

---

## Error Message Format

```
Tool 'nexus_send' can only target parent agent ('{parent_id}')
Tool 'nexus_send' can only target parent agent ('none')  # When no parent
Tool 'nexus_send' can only target child agents
Tool 'nexus_send' can only target parent or child agents
Tool 'nexus_send' cannot target agent '{target_id}'  # For explicit list
