# Plan: Fix Sandboxed Read/Write Permissions

## Goal

Sandboxed agents should:
- READ only within cwd
- WRITE only within explicit write-paths (which must be within cwd)
- Default to READ-ONLY if no write-paths specified

## Issues to Fix

**Test 5 bug**: Sandboxed agents can write inside cwd using `append_file` even without `--write-path`
- **Root cause**: global_dispatcher.py only disables `write_file` and `edit_file`, not other write tools

**Test 8 bug**: Sandboxed agents WITH `--write-path` still can't write
- **Root cause**: session.py:562 checks policy-level sandbox BEFORE per-tool overrides can apply

**Security hole**: RPC root sandboxed agents can have write-paths outside cwd
- **Root cause**: global_dispatcher.py:319-328 only validates containment when `parent_agent_id is not None`

---

## Reduced Plan (3 Steps)

Based on GPT-5.2 review, we're using a minimal approach that doesn't require schema migration.

### Step 1: Fix RPC write-path containment hole

**File**: `nexus3/rpc/global_dispatcher.py`

**Current code** (lines 319-328):
```python
# SECURITY: Validate write paths are within cwd (sandbox root)
if parent_agent_id is not None:  # <-- HOLE: only checks for subagents
    sandbox_root = cwd_path or Path.cwd()
    for wp in write_paths:
        try:
            wp.relative_to(sandbox_root)
        except ValueError as e:
            raise InvalidParamsError(
                f"allowed_write_path '{wp}' is outside sandbox root '{sandbox_root}'"
            ) from e
```

**Change**: Make containment check unconditional for sandboxed/worker presets:
```python
# SECURITY: Validate write paths are within cwd (sandbox root)
# Applies to ALL sandboxed/worker agents, not just subagents
effective_preset = preset or "sandboxed"
if effective_preset in ("sandboxed", "worker") and write_paths:
    sandbox_root = cwd_path if cwd_path is not None else Path.cwd()
    for wp in write_paths:
        try:
            wp.relative_to(sandbox_root)
        except ValueError as e:
            raise InvalidParamsError(
                f"allowed_write_path '{wp}' is outside sandbox root '{sandbox_root}'"
            ) from e
```

**Why first**: Tightens security before we relax session.py checks. No functional change except blocking invalid configurations.

---

### Step 2: Expand tool overrides to all write-capable tools (fixes Test 5)

**File**: `nexus3/rpc/global_dispatcher.py`

**Current code** (lines 346-356):
```python
if effective_preset in ("sandboxed", "worker"):
    tool_overrides: dict[str, ToolPermission] = {}
    if write_paths is not None:
        for tool_name in ("write_file", "edit_file"):  # <-- Missing tools!
            tool_overrides[tool_name] = ToolPermission(
                enabled=True,
                allowed_paths=write_paths,
            )
    else:
        for tool_name in ("write_file", "edit_file"):  # <-- Missing tools!
            tool_overrides[tool_name] = ToolPermission(enabled=False)
```

**Change**: Expand to all write-capable file tools:
```python
# All tools that can modify the filesystem
WRITE_FILE_TOOLS = ("write_file", "edit_file", "append_file", "regex_replace", "mkdir")
MIXED_FILE_TOOLS = ("copy_file", "rename")  # Read source, write destination

if effective_preset in ("sandboxed", "worker"):
    tool_overrides: dict[str, ToolPermission] = {}

    if write_paths is not None and write_paths:
        # Enable write tools with explicit allowed paths
        for tool_name in WRITE_FILE_TOOLS:
            tool_overrides[tool_name] = ToolPermission(
                enabled=True,
                allowed_paths=write_paths,
            )
        # Mixed tools: also restrict to write paths
        # (source validation still uses policy allowed_paths via FileSkill)
        for tool_name in MIXED_FILE_TOOLS:
            tool_overrides[tool_name] = ToolPermission(
                enabled=True,
                allowed_paths=write_paths,
            )
    else:
        # No write paths = disable all write-capable tools
        for tool_name in WRITE_FILE_TOOLS + MIXED_FILE_TOOLS:
            tool_overrides[tool_name] = ToolPermission(enabled=False)

    delta_kwargs["tool_overrides"] = tool_overrides
```

**Why second**: Directly fixes Test 5. Only tightens restrictions (disables more tools by default).

---

### Step 3: Remove session.py early sandbox gate (fixes Test 8)

**File**: `nexus3/session/session.py`

**Current problematic code** (lines 560-565):
```python
# For SANDBOXED: Additional path check (sandbox enforcement)
if target_path is not None:
    if not permissions.effective_policy.can_write_path(target_path):
        return ToolResult(
            error=f"Path '{target_path}' is outside the allowed sandbox"
        )
```

**Change**: Remove this check OR gate it to only apply when no per-tool override exists:

**Option A (Recommended - Remove entirely):**
```python
# REMOVED: Policy-level sandbox check was blocking per-tool overrides.
# Security is now enforced by:
# 1. RPC creation-time validation (write-paths must be within cwd)
# 2. Tool disabled/enabled gating (write tools disabled without explicit paths)
# 3. FileSkill/PathResolver validation (uses per-tool allowed_paths)
#
# if target_path is not None:
#     if not permissions.effective_policy.can_write_path(target_path):
#         return ToolResult(error=...)
```

**Option B (Keep as fallback for tools without overrides):**
```python
# For SANDBOXED: Sandbox enforcement only if no per-tool override
if target_path is not None:
    tool_perm = permissions.tool_permissions.get(tool_call.name)
    # Only apply policy check if tool has no explicit path override
    if tool_perm is None or tool_perm.allowed_paths is None:
        if not permissions.effective_policy.can_write_path(target_path):
            return ToolResult(
                error=f"Path '{target_path}' is outside the allowed sandbox"
            )
```

**Why last**: This is the only change that could widen access. After Steps 1-2:
- Write-paths are guaranteed within cwd (Step 1)
- Write tools are disabled unless explicitly configured (Step 2)
- So removing this check doesn't create escape hatches

---

## Implementation Order

```
Step 1: global_dispatcher.py - Fix write-path containment hole
    ↓ (security tightening, no functional change)
Step 2: global_dispatcher.py - Expand write tool overrides
    ↓ (fixes Test 5, security tightening)
Step 3: session.py - Remove/relax early sandbox gate
    ↓ (fixes Test 8, safe because Steps 1-2 are in place)
```

**Key principle**: Never temporarily widen access between commits.

---

## Validation Checklist

After each step:

- [ ] **After Step 1**: Existing tests pass. RPC sandboxed agents with write-path outside cwd now rejected.
- [ ] **After Step 2**: Test 5 passes (append_file without --write-path is blocked).
- [ ] **After Step 3**: Test 8 passes (write-path is honored).

Full validation:
- [ ] Sandboxed agent can read within cwd
- [ ] Sandboxed agent cannot read outside cwd
- [ ] Sandboxed agent without --write-path cannot write (all write tools disabled)
- [ ] Sandboxed agent with --write-path can write to that path
- [ ] Sandboxed agent with --write-path cannot write outside that path
- [ ] Write-path outside cwd rejected at creation time
- [ ] TRUSTED mode unaffected
- [ ] YOLO mode unaffected

---

## Optional Step 4: Central deny-by-default (future hardening)

**File**: `nexus3/skill/services.py`

Add logic to `get_tool_allowed_paths()` to return `[]` (deny) for write tools in SANDBOXED when no explicit override exists. This prevents future tools from accidentally bypassing restrictions.

```python
def get_tool_allowed_paths(self, tool_name: str) -> list[Path] | None:
    permissions = self.get("permissions")
    if permissions is None:
        return self.get("allowed_paths")

    # Check for per-tool override
    tool_perm = permissions.tool_permissions.get(tool_name)
    if tool_perm is not None and tool_perm.allowed_paths is not None:
        return tool_perm.allowed_paths

    # SANDBOXED: Default deny for write tools without explicit override
    if permissions.effective_policy.level == PermissionLevel.SANDBOXED:
        write_tools = {"write_file", "edit_file", "append_file", "regex_replace",
                       "mkdir", "copy_file", "rename"}
        if tool_name in write_tools:
            return []  # Deny - no writes allowed without explicit paths

    # Fall back to policy-level allowed_paths
    return permissions.effective_policy.allowed_paths
```

This is defense-in-depth: even if someone adds a new write tool and forgets to configure it in global_dispatcher, the central check blocks it.

---

## Files Changed

| Step | File | Change |
|------|------|--------|
| 1 | `nexus3/rpc/global_dispatcher.py` | Make write-path containment check unconditional |
| 2 | `nexus3/rpc/global_dispatcher.py` | Expand tool overrides to all write tools |
| 3 | `nexus3/session/session.py` | Remove/relax early sandbox gate |
| 4 | `nexus3/skill/services.py` | (Optional) Central deny-by-default |

---

## Why This Approach (vs. Full Read/Write Schema)

GPT-5.2 review identified that our original 10-phase plan was overengineered:
- No need for new `read_allowed_paths`/`write_allowed_paths` fields
- No need for schema migration or config loader changes
- No need for PathResolver/FileSkill signature changes
- No need to update all file skill implementations

The reduced plan fixes both bugs with 3 targeted changes to 2 files.

The full read/write schema could be revisited later if we need:
- Different read vs write paths for the same tool
- Config-driven per-tool read/write restrictions
- More granular permission control

For now, the reduced plan is simpler, safer, and sufficient.

---

## Credit

Plan refined with input from GPT-5.2 (via NEXUS3 subagent review).
