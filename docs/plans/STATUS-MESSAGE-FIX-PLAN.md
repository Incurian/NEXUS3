# Plan: Status Message State Fix

## OPEN QUESTIONS

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| **Q1** | What message after tools complete? | A) "Waiting for response..." B) "Processing..." C) "Continuing..." | **A) "Waiting..."** - hardcoded in WAITING state |
| **Q2** | Should timer reset? | A) No, cumulative B) Yes, from batch end | **A) Cumulative** - timer maintained by spinner's `_start_time` |

---

## Overview

**Bug:** After all tools complete, spinner shows "Running: [last_tool_name]" instead of transitioning to "Waiting...".

**Root Cause (Confirmed):** `on_batch_complete()` callback at line 798-800 is a no-op:
```python
def on_batch_complete() -> None:
    """Batch finished - no action needed, tools already printed."""
    pass
```

The `on_tool_active()` sets spinner to `Activity.TOOL_CALLING` with text "Running: {name}" but nothing transitions it back when the batch completes.

---

## Activity State Flow

| Event | Activity State | Display Text | Location |
|-------|---------------|--------------|----------|
| Request starts | `WAITING` | "Waiting..." | line 1515 |
| First response chunk | `RESPONDING` | "Responding..." | line 1509 |
| Reasoning detected | `THINKING` | "Thinking..." | line 684 |
| Reasoning ends | `RESPONDING` | "Responding..." | line 689 |
| Tool becomes active | `TOOL_CALLING` | "Running: {name}" | line 745 |
| **Batch completes** | **(BUG: unchanged)** | **(BUG: "Running: {last}")** | **line 798** |
| Next content arrives | `RESPONDING` | "Responding..." | line 1509 |

---

## The Fix (2 lines)

**File:** `nexus3/cli/repl.py` (lines 798-800)

**Current:**
```python
def on_batch_complete() -> None:
    """Batch finished - no action needed, tools already printed."""
    pass
```

**After:**
```python
def on_batch_complete() -> None:
    """Batch finished - transition spinner to waiting for next response."""
    spinner.update(activity=Activity.WAITING)
```

---

## Why This Works

1. `spinner` is in scope (defined at line 629)
2. `Activity` is already imported (line 64: `from nexus3.display import Activity, Spinner, get_console`)
3. `spinner.update(activity=Activity.WAITING)` changes the activity state
4. When activity is WAITING, the Spinner's `__rich__` method renders "Waiting..." (hardcoded, ignores text parameter)
5. Timer continues from `_start_time` - no reset needed
6. When next content arrives, streaming transitions to RESPONDING/THINKING

---

## Files to Modify

| File | Lines | Change |
|------|-------|--------|
| `nexus3/cli/repl.py` | 798-800 | Replace `pass` with `spinner.update(activity=Activity.WAITING)` |

---

## Implementation Checklist

### Phase 1: Fix
- [ ] **P1.1** Replace `pass` with `spinner.update(activity=Activity.WAITING)` (line 799)
- [ ] **P1.2** Update docstring to reflect new behavior (line 798)

### Phase 2: Testing
- [ ] **P2.1** Live test: single tool completes → spinner shows "Waiting..."
- [ ] **P2.2** Live test: batch of tools completes → spinner shows "Waiting..."
- [ ] **P2.3** Live test: timer continues incrementing (no reset)
- [ ] **P2.4** Live test: next model response transitions to "Responding..."

---

## Effort Estimate

~5 minutes implementation, ~10 minutes testing.
