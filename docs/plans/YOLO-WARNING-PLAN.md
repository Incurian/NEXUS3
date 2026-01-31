# Plan: YOLO Warning Enhancement

## OPEN QUESTIONS

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| **Q1** | Warning verbosity? | A) Single line B) Multi-line with capabilities C) Full block | **B) Multi-line** - balance awareness vs noise |
| **Q2** | Show on every prompt? | A) Every prompt B) Only on switch/start C) Configurable | **A) Every prompt** - YOLO is dangerous |
| **Q3** | Show on mode switch? | A) No B) Yes, show capabilities C) Require confirmation | **B) Show capabilities** |
| **Q4** | Include escape hint? | A) No B) Show `/permissions trusted` | **B) Always show** - escape hatch |
| **Q5** | Visual style? | A) Bold red text B) Yellow box C) Red background panel | **C) Red panel** - max visibility |

---

## Overview

**Current:** Single line warning (line 1260)
```
⚠️  YOLO MODE - All actions execute without confirmation
```

**Goal:** Enhanced warning with capabilities and escape hint using Rich Panel
```
╭─ ⚠ WARNING ─────────────────────────────────────────────────────────╮
│ ⚠️  YOLO MODE - All actions execute without confirmation            │
│                                                                      │
│ Enabled: Shell execution, file writes anywhere, network access      │
│ To switch: /permissions trusted                                     │
╰──────────────────────────────────────────────────────────────────────╯
```

---

## Scope

### Included
- Enhanced persistent YOLO warning with capability list
- Warning on switch to YOLO via `/permissions yolo`
- Hint showing how to switch to safer mode

### Deferred
- Config option to disable (for power users)
- Confirmation requirement when switching to YOLO

---

## Implementation

### Phase 1: Add Warning Constants

**File:** `nexus3/cli/repl_commands.py` (add near top, after imports ~line 44)

```python
# YOLO mode warning text
YOLO_WARNING_CAPABILITIES = """Enabled: Shell execution, file writes anywhere, network access, agent management
To switch to safer mode: /permissions trusted"""

YOLO_WARNING_PERSISTENT = f"""[bold]YOLO MODE[/bold] - All actions execute without confirmation

{YOLO_WARNING_CAPABILITIES}"""
```

### Phase 2: Add Import to repl.py

**File:** `nexus3/cli/repl.py` (add near line 45 with other Rich imports)

```python
from rich.panel import Panel
```

### Phase 3: Update Persistent Warning

**File:** `nexus3/cli/repl.py` (lines 1255-1260)

**Current code:**
```python
# YOLO mode warning - show before prompt so user sees it before typing
agent = pool.get(current_agent_id)
if agent:
    perms = agent.services.get("permissions")
    if perms and perms.effective_policy.level == PermissionLevel.YOLO:
        console.print("[bold red]⚠️  YOLO MODE - All actions execute without confirmation[/]")
```

**New code:**
```python
# YOLO mode warning - show before prompt so user sees it before typing
agent = pool.get(current_agent_id)
if agent:
    perms = agent.services.get("permissions")
    if perms and perms.effective_policy.level == PermissionLevel.YOLO:
        from nexus3.cli.repl_commands import YOLO_WARNING_PERSISTENT
        console.print(Panel(
            YOLO_WARNING_PERSISTENT,
            border_style="bold red",
            title="[bold red]⚠ WARNING[/]",
            padding=(0, 1),
        ))
```

### Phase 4: Add Switch Warning

**File:** `nexus3/cli/repl_commands.py` - `_change_preset()` function (line ~1163)

**Add before applying the preset (before `agent.services.register(...)` at line ~1170):**

```python
async def _change_preset(
    agent: Agent,
    perms: AgentPermissions,
    preset_name: str,
    custom_presets: dict[str, PermissionPreset],
) -> CommandOutput:
    """Change to a different permission preset."""
    # ... existing validation code ...

    # Show warning when switching to YOLO
    if preset_name == "yolo":
        from rich.panel import Panel
        from nexus3.display import get_console
        console = get_console()
        console.print(Panel(
            "⚠️  Switching to YOLO MODE\n\n" + YOLO_WARNING_CAPABILITIES,
            border_style="bold red",
            title="[bold red]⚠ WARNING[/]",
            padding=(0, 1),
        ))

    # Apply the preset (existing code continues here)
    agent.services.register(...)
```

---

## Files to Modify

| File | Lines | Change |
|------|-------|--------|
| `nexus3/cli/repl_commands.py` | ~44 | Add `YOLO_WARNING_CAPABILITIES` and `YOLO_WARNING_PERSISTENT` constants |
| `nexus3/cli/repl_commands.py` | ~1163 | Add switch warning in `_change_preset()` |
| `nexus3/cli/repl.py` | ~45 | Add `from rich.panel import Panel` import |
| `nexus3/cli/repl.py` | 1255-1260 | Replace persistent warning with Panel version |

---

## Implementation Checklist

### Phase 1: Warning Constants
- [ ] **P1.1** Add `YOLO_WARNING_CAPABILITIES` constant to `repl_commands.py`
- [ ] **P1.2** Add `YOLO_WARNING_PERSISTENT` constant to `repl_commands.py`

### Phase 2: Persistent Warning
- [ ] **P2.1** Add `from rich.panel import Panel` import to `repl.py`
- [ ] **P2.2** Update REPL loop warning (lines 1255-1260) to use Panel

### Phase 3: Switch Warning
- [ ] **P3.1** Add warning display in `_change_preset()` before applying YOLO preset

### Phase 4: Testing
- [ ] **P4.1** Live test: persistent warning displays as Panel on each prompt
- [ ] **P4.2** Live test: switch warning appears when running `/permissions yolo`
- [ ] **P4.3** Live test: no warning when switching to trusted/sandboxed

---

## Effort Estimate

~20 minutes implementation, ~10 minutes testing.
