# Plan: Tool Use/Return Preview Enhancements

## OPEN QUESTIONS

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| **Q1** | Two lines vs longer single line for params? | A) Two lines B) Single longer line (~140 chars) C) Dynamic | **B) Longer single line** - simpler |
| **Q2** | Return line: keep arrow or use gumball? | A) Keep `→` arrow B) Use gumball for consistency | **A) Keep arrow** - differentiates call from return |
| **Q3** | Smart path truncation? | A) End truncation B) Middle truncation (preserve start+end) | **B) Middle** - `/home/.../file.py` |

---

## Overview

### Current State

```
  ● read_file: path=/some/very/long/path/that/gets/truncated/to/70...
      → 150 lines, 4.2KB
```

- Call line: Cyan gumball, params truncated to 70 chars
- Return line: Green arrow (success) or red arrow + red text (error)
- Error styling is already correct (red arrow + red message)
- Priority keys already exist: `("path", "file", "file_path", "directory", "dir", "cwd", "agent_id")`

### Goal

```
  ● read_file: path=/home/.../src/very/long/path/file.py, offset=100, limit=50
      → 150 lines, 4.2KB (0.3s)

  ● bash_safe: command="git status --porcelain"
      → Exit code 128: fatal: not a git repository (or any parent dirs) (0.2s)
```

**Key changes:**
1. Expand params from 70 to 140 chars
2. Smart path truncation (middle ellipsis for paths)
3. Expand error message limit from 70 to 120 chars
4. No changes to colors (already correct)

---

## Scope

### Included
- Expand `format_tool_params()` from 70 to 140 chars
- Add smart path truncation (middle ellipsis)
- Expand error message limit from 70 to 120 chars

### NOT Changing
- Call line format (cyan gumball) - already correct
- Success return format (green arrow) - already correct
- Error return format (red arrow + red text) - already correct
- Halted tools (orange gumball) - already correct

---

## Implementation

### Phase 1: Add smart_truncate() Helper

**File:** `nexus3/cli/confirmation_ui.py` (add before `format_tool_params` at line ~20)

```python
def smart_truncate(value: str, max_length: int, preserve_ends: bool = False) -> str:
    """Truncate string, optionally preserving start and end (good for paths).

    Args:
        value: String to truncate
        max_length: Maximum length of result
        preserve_ends: If True, use middle truncation (/home/.../file.py)

    Returns:
        Truncated string, or original if within limit
    """
    if len(value) <= max_length:
        return value
    if preserve_ends and max_length >= 15:
        available = max_length - 5  # Reserve for "/.../"
        start_len = available // 2
        end_len = available - start_len
        return f"{value[:start_len]}/.../{value[-end_len:]}"
    return value[:max_length - 3] + "..."
```

### Phase 2: Update format_tool_params()

**File:** `nexus3/cli/confirmation_ui.py` (line 21)

**Change default max_length:**
```python
# Line 21: Change from
def format_tool_params(arguments: dict, max_length: int = 70) -> str:
# To:
def format_tool_params(arguments: dict, max_length: int = 140) -> str:
```

**Update priority key handling (lines 44-48) to use smart truncation for paths:**
```python
# Current (lines 44-48):
for key in priority_keys:
    if key in arguments and arguments[key]:
        value = escape_rich_markup(str(arguments[key]))
        safe_key = escape_rich_markup(str(key))
        parts.append(f"{safe_key}={value}")

# Change to:
for key in priority_keys:
    if key in arguments and arguments[key]:
        value = str(arguments[key])
        # Use middle truncation for path-like values if very long
        if key in ("path", "file", "file_path", "directory", "dir", "cwd") and len(value) > 60:
            value = smart_truncate(value, max_length=60, preserve_ends=True)
        value = escape_rich_markup(value)
        safe_key = escape_rich_markup(str(key))
        parts.append(f"{safe_key}={value}")
```

### Phase 3: Expand Error Limit in repl.py

**File:** `nexus3/cli/repl.py` (line 786)

```python
# Current (line 786):
error_preview = escape_rich_markup(error[:70] + ("..." if len(error) > 70 else ""))

# Change to:
error_preview = escape_rich_markup(error[:120] + ("..." if len(error) > 120 else ""))
```

### Phase 4: Expand Error Limit in streaming.py

**File:** `nexus3/display/streaming.py` (line 180)

```python
# Current (line 180):
error_preview = tool.error[:70] + ("..." if len(tool.error) > 70 else "")

# Change to:
error_preview = tool.error[:120] + ("..." if len(tool.error) > 120 else "")
```

---

## Files to Modify

| File | Lines | Change |
|------|-------|--------|
| `nexus3/cli/confirmation_ui.py` | ~20 | Add `smart_truncate()` function |
| `nexus3/cli/confirmation_ui.py` | 21 | Change default `max_length` from 70 to 140 |
| `nexus3/cli/confirmation_ui.py` | 44-48 | Use `smart_truncate()` for path-like keys |
| `nexus3/cli/repl.py` | 786 | Change error limit from 70 to 120 |
| `nexus3/display/streaming.py` | 180 | Change error limit from 70 to 120 |

---

## Visual Reference

### Before
```
  ● read_file: path=/home/user/project/src/very/lo...
      → 150 lines, 4.2KB
  ● bash_safe: command="git status"
      → Exit code 128: fatal: not a gi...
```

### After
```
  ● read_file: path=/home/.../src/very/long/path/file.py, offset=100, limit=50
      → 150 lines, 4.2KB (0.3s)
  ● bash_safe: command="git status --porcelain"
      → Exit code 128: fatal: not a git repository (or any of the parent directories) (0.2s)
```

---

## Implementation Checklist

### Phase 1: Parameter Formatting
- [ ] **P1.1** Add `smart_truncate()` helper to `confirmation_ui.py` (before line 21)
- [ ] **P1.2** Update `format_tool_params()` default from 70 to 140 (line 21)
- [ ] **P1.3** Update priority key loop to use `smart_truncate()` for paths (lines 44-48)

### Phase 2: Error Display Expansion
- [ ] **P2.1** Expand error limit from 70 to 120 in `repl.py` (line 786)
- [ ] **P2.2** Expand error limit from 70 to 120 in `streaming.py` (line 180)

### Phase 3: Testing
- [ ] **P3.1** Visual test: long paths show middle truncation (`/home/.../file.py`)
- [ ] **P3.2** Visual test: params now show ~140 chars instead of ~70
- [ ] **P3.3** Visual test: error messages show ~120 chars instead of ~70
- [ ] **P3.4** Visual test: success returns still show green arrow
- [ ] **P3.5** Visual test: error returns still show red arrow + red text
- [ ] **P3.6** Visual test: halted tools still show orange gumball

### Phase 4: Test Updates
- [ ] **P4.1** Update `tests/security/test_rich_markup_injection.py` assertions for 140-char limit

---

## Effort Estimate

~30 minutes implementation, ~20 minutes testing.
