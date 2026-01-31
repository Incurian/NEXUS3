# Plan: edit_file Error Message Bug Fix

## OPEN QUESTIONS

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| **Q1** | Add error categories? | A) No B) Yes (`[File Error]`, `[Content Error]`) | **A) No** - fix the pattern first, categories can come later |
| **Q2** | Add debug logging? | A) No B) Yes, verbose mode | **B) Verbose logging** - helps diagnose future issues |

---

## Overview

**Reported Bug:** `edit_file` returns "File or directory not found" when `old_string` doesn't match, but file exists.

**Expected:** Should return "String not found in file: {old_string[:100]}..."

**Root Cause Found:** Bug is in `sanitize_error_for_agent()` in `nexus3/core/errors.py:109`, NOT in the `edit_file` skill itself.

---

## Root Cause Analysis

### The edit_file Skill is Correct

**File:** `nexus3/skill/builtin/edit_file.py`

The skill returns distinct, correct error messages:
- Line 145: `"File not found: {path}"` for `FileNotFoundError`
- Line 203: `"String not found in file: {old_string[:100]}..."` for content mismatch

### The Bug is in Error Sanitization

**File:** `nexus3/core/errors.py` (line 109)

**Problematic code:**
```python
if "no such file" in error_lower or "not found" in error_lower:
    return "File or directory not found"
```

**Problem:** The pattern `"not found" in error_lower` is too broad and catches:
- "File not found: path.py" → sanitized (correct)
- "String not found in file: def foo()..." → sanitized (WRONG!)
- "Directory not found: /tmp/missing" → sanitized (correct)

### Error Flow

```
1. User: edit_file(path="exists.py", old_string="wrong", new_string="bar")
2. _validate_path("exists.py") succeeds
3. p.read_bytes() succeeds
4. content.count("wrong") returns 0
5. edit_file returns: ToolResult(error="String not found in file: wrong...")
6. Session calls: sanitize_error_for_agent("String not found in file: wrong...", "edit_file")
7. Sanitization detects "not found" → returns "File or directory not found" ← BUG
8. Agent sees: "File or directory not found" (wrong!)
```

---

## The Fix

**File:** `nexus3/core/errors.py` (line 109)

**Current:**
```python
if "no such file" in error_lower or "not found" in error_lower:
    return "File or directory not found"
```

**Fixed:**
```python
# More specific pattern to avoid catching content-level errors like "String not found"
if "no such file" in error_lower or "file not found" in error_lower or "directory not found" in error_lower:
    return "File or directory not found"
```

This fixes the issue because:
- "String not found in file" does NOT contain "file not found" or "directory not found"
- "File not found: path" DOES contain "file not found"
- "Directory not found: /path" DOES contain "directory not found"

---

## Files to Modify

| File | Lines | Change |
|------|-------|--------|
| `nexus3/core/errors.py` | 109 | Use more specific pattern matching |

---

## Testing

### Regression Test to Add

**File:** `tests/unit/test_error_sanitization.py`

```python
def test_string_not_found_preserves_meaning():
    """Ensure content-level errors are not mapped to file errors."""
    error = "String not found in file: def foo()..."
    result = sanitize_error_for_agent(error, "edit_file")
    # Should NOT be mapped to "File or directory not found"
    assert "file or directory not found" not in result.lower()
    # Should preserve the string-not-found meaning
    assert "string" in result.lower() or "not found in file" in result.lower()

def test_file_not_found_sanitized():
    """Ensure file-level errors are still sanitized."""
    error = "File not found: /home/user/secret/passwords.txt"
    result = sanitize_error_for_agent(error, "edit_file")
    assert result == "File or directory not found"
```

---

## Implementation Checklist

### Phase 1: Fix
- [ ] **P1.1** Update pattern in `sanitize_error_for_agent()` (errors.py line 109)

### Phase 2: Testing
- [ ] **P2.1** Add regression test for "String not found in file" preservation
- [ ] **P2.2** Add test confirming "File not found" is still sanitized
- [ ] **P2.3** Live test: edit_file with wrong old_string shows correct error

### Phase 3: Documentation
- [ ] **P3.1** Remove from Known Bugs section in CLAUDE.md (if added)

---

## Optional Enhancement: Debug Logging

If we want better diagnostics for future issues, add logging to edit_file:

**File:** `nexus3/skill/builtin/edit_file.py`

```python
import logging
logger = logging.getLogger(__name__)

async def execute(self, path: str = "", old_string: str | None = None, ...) -> ToolResult:
    logger.debug(f"edit_file: path={path!r}")

    try:
        p = self._validate_path(path)
        logger.debug(f"edit_file: validated path={p}, exists={p.exists()}")
    except Exception as e:
        logger.debug(f"edit_file: path validation failed: {type(e).__name__}: {e}")
        raise

    # ... rest of implementation ...

    count = content.count(old_string)
    logger.debug(f"edit_file: string match count={count}")
    if count == 0:
        logger.debug("edit_file: returning 'String not found' error")
        return ToolResult(error=f"String not found in file: {old_string[:100]}...")
```

This is optional but helpful for diagnosing future issues.

---

## Effort Estimate

~10 minutes implementation, ~15 minutes testing.
