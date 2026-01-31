# Plan: Error Sanitization Pattern Fixes

## OPEN QUESTIONS

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| **Q1** | Add Windows path tests? | A) No B) Yes, comprehensive | **B) Yes** - currently 0% coverage |
| **Q2** | Add debug logging to edit_file? | A) No B) Yes, verbose mode | **A) No** - overkill for this fix |

---

## Overview

**Original Bug:** `edit_file` returns "File or directory not found" when `old_string` doesn't match, but file exists.

**Root Cause:** Two overly broad patterns in `sanitize_error_for_agent()`:

1. **Line 109:** `"not found"` catches "String not found in file" (content error → file error)
2. **Line 64:** `_PATH_PATTERN` matches URLs and non-filesystem paths (loses useful info)

**Solution:** Fix both patterns to be more specific without losing security coverage.

---

## Bug Analysis

### Bug 1: "not found" Pattern Too Broad

**File:** `nexus3/core/errors.py` (line 109)

**Current code:**
```python
if "no such file" in error_lower or "not found" in error_lower:
    return "File or directory not found"
```

**False positives:**
| Error Message | Actual Meaning | Incorrectly Maps To |
|---------------|----------------|---------------------|
| "String not found in file: def foo()" | Content search failed | "File or directory not found" |
| "Clipboard key 'backup' not found" | Key doesn't exist | "File or directory not found" |
| "Marker 'END' not found in file" | Insertion marker missing | "File or directory not found" |
| "No patch hunks found in diff" | Empty diff | "File or directory not found" |

### Bug 2: Path Pattern Too Broad

**File:** `nexus3/core/errors.py` (line 64)

**Current code:**
```python
_PATH_PATTERN = re.compile(r'(/[^\s:]+)+')
```

**False positives:**
| Input | Matched | Problem |
|-------|---------|---------|
| `http://example.com/api/v1` | `/api/v1` | URL path mangled to `[path]` |
| `https://docs.example.com/guide` | `/guide` | Documentation URL corrupted |
| `/r/python` | `/r/python` | Reddit link sanitized |
| `$50/month` | `/month` | Price expression broken |

**Real impact:** Provider errors, MCP help text, and GitLab errors all contain URLs that get incorrectly sanitized.

---

## The Fixes

### Fix 1: More Specific "not found" Pattern

**File:** `nexus3/core/errors.py` (line 109)

**Current:**
```python
if "no such file" in error_lower or "not found" in error_lower:
    return "File or directory not found"
```

**Fixed:**
```python
if "no such file" in error_lower or "file not found" in error_lower or "directory not found" in error_lower:
    return "File or directory not found"
```

**Why this works:**
- "String not found in file" does NOT contain "file not found"
- "File not found: /path" DOES contain "file not found"
- "Directory not found: /path" DOES contain "directory not found"
- "Path not found" and "Source not found" also contain "not found" but checking these specific phrases is still safe

**Additional patterns to catch:**
```python
if ("no such file" in error_lower or
    "file not found" in error_lower or
    "directory not found" in error_lower or
    "path not found" in error_lower or
    "source not found" in error_lower):
    return "File or directory not found"
```

### Fix 2: More Selective Path Pattern

**File:** `nexus3/core/errors.py` (line 64)

**Current:**
```python
_PATH_PATTERN = re.compile(r'(/[^\s:]+)+')
```

**Fixed:**
```python
_PATH_PATTERN = re.compile(r'(?<![:/\w])/(?!/)(?![rug]/)[^\s:]+')
```

**Pattern breakdown:**
```
(?<![:/\w])   - Negative lookbehind: NOT preceded by : / or word char
               (prevents matching after http: or within words)
/             - Literal forward slash
(?!/)         - Negative lookahead: NOT followed by another /
               (prevents matching // in URLs)
(?![rug]/)    - Negative lookahead: NOT /r/ /u/ /g/
               (prevents matching Reddit/social paths)
[^\s:]+       - One or more non-whitespace/non-colon chars
```

**What this preserves:**
| Input | Before | After |
|-------|--------|-------|
| `http://example.com/api/v1` | `http:[server]\[share][path]` | `http://example.com/api/v1` ✓ |
| `/r/python` | `[path]` | `/r/python` ✓ |
| `$50/month` | `$50[path]` | `$50/month` ✓ |
| `/home/alice/secret.txt` | `[path]` | `[path]` ✓ |
| `/etc/passwd` | `[path]` | `[path]` ✓ |

---

## Files to Modify

| File | Line | Change |
|------|------|--------|
| `nexus3/core/errors.py` | 64 | Update `_PATH_PATTERN` regex |
| `nexus3/core/errors.py` | 109 | Use more specific "not found" patterns |
| `tests/unit/test_error_sanitization.py` | EOF | Add regression tests |

---

## Implementation

### Phase 1: Fix Patterns (errors.py)

**Change 1 - Line 64:**
```python
# FROM:
_PATH_PATTERN = re.compile(r'(/[^\s:]+)+')

# TO:
_PATH_PATTERN = re.compile(r'(?<![:/\w])/(?!/)(?![rug]/)[^\s:]+')
```

**Change 2 - Line 109:**
```python
# FROM:
if "no such file" in error_lower or "not found" in error_lower:
    return "File or directory not found"

# TO:
if (
    "no such file" in error_lower
    or "file not found" in error_lower
    or "directory not found" in error_lower
    or "path not found" in error_lower
    or "source not found" in error_lower
):
    return "File or directory not found"
```

### Phase 2: Add Tests (test_error_sanitization.py)

Add the following tests at the end of the `TestSanitizeErrorForAgent` class:

```python
# === Bug fix: "String not found" should not become "File not found" ===

def test_string_not_found_preserves_meaning(self):
    """Content-level errors should not be mapped to file errors."""
    error = "String not found in file: def foo()..."
    result = sanitize_error_for_agent(error, "edit_file")
    assert "file or directory not found" not in result.lower()
    assert "string" in result.lower() or "not found in file" in result.lower()

def test_clipboard_key_not_found_preserves_meaning(self):
    """Clipboard key errors should not become file errors."""
    error = "Clipboard key 'backup' not found in agent scope"
    result = sanitize_error_for_agent(error, "clipboard_get")
    assert "file or directory not found" not in result.lower()
    assert "clipboard" in result.lower() or "key" in result.lower()

def test_marker_not_found_preserves_meaning(self):
    """Marker errors should not become file errors."""
    error = "Marker 'SECTION_END' not found in file"
    result = sanitize_error_for_agent(error, "paste")
    assert "file or directory not found" not in result.lower()
    assert "marker" in result.lower()

def test_file_not_found_still_sanitized(self):
    """File-level errors should still be sanitized."""
    error = "File not found: /home/user/secret/passwords.txt"
    result = sanitize_error_for_agent(error, "read_file")
    assert result == "File or directory not found"

def test_directory_not_found_still_sanitized(self):
    """Directory-level errors should still be sanitized."""
    error = "Directory not found: /home/user/.ssh"
    result = sanitize_error_for_agent(error, "list_directory")
    assert result == "File or directory not found"

def test_path_not_found_still_sanitized(self):
    """Path not found errors should still be sanitized."""
    error = "Path not found: /etc/secret.conf"
    result = sanitize_error_for_agent(error, "grep")
    assert result == "File or directory not found"

def test_source_not_found_still_sanitized(self):
    """Source not found errors should still be sanitized."""
    error = "Source not found: /home/alice/file.txt"
    result = sanitize_error_for_agent(error, "copy_file")
    assert result == "File or directory not found"

# === Bug fix: URLs should not be mangled ===

def test_url_http_preserved(self):
    """HTTP URLs should not have paths sanitized."""
    error = "Error connecting to http://example.com/api/v1/users"
    result = sanitize_error_for_agent(error, "bash")
    assert "http://example.com/api/v1/users" in result

def test_url_https_preserved(self):
    """HTTPS URLs should not have paths sanitized."""
    error = "Failed to fetch https://docs.example.com/guide/setup"
    result = sanitize_error_for_agent(error, "bash")
    assert "https://docs.example.com/guide/setup" in result

def test_url_with_port_preserved(self):
    """URLs with ports should not have paths sanitized."""
    error = "Connection refused: http://localhost:8765/agent/main"
    result = sanitize_error_for_agent(error, "nexus_send")
    assert "http://localhost:8765/agent/main" in result

def test_social_media_path_preserved(self):
    """Reddit-style paths should not be sanitized."""
    error = "Check /r/python for more info"
    result = sanitize_error_for_agent(error, "bash")
    assert "/r/python" in result

def test_price_expression_preserved(self):
    """Price expressions like $50/month should not be sanitized."""
    error = "Cost is $50/month for this service"
    result = sanitize_error_for_agent(error, "bash")
    assert "$50/month" in result

def test_filesystem_paths_still_sanitized(self):
    """Real filesystem paths should still be sanitized."""
    error = "Cannot read /home/alice/secrets.txt"
    result = sanitize_error_for_agent(error, "read_file")
    assert "/home/alice" not in result
    assert "[path]" in result or "[user]" in result

def test_etc_paths_still_sanitized(self):
    """System paths should still be sanitized."""
    error = "Access denied to /etc/shadow"
    result = sanitize_error_for_agent(error, "read_file")
    assert "/etc/shadow" not in result

def test_var_paths_still_sanitized(self):
    """Var paths should still be sanitized."""
    error = "Log file at /var/log/auth.log"
    result = sanitize_error_for_agent(error, "read_file")
    assert "/var/log" not in result

# === Windows path tests (previously untested) ===

def test_windows_user_path_backslash(self):
    """Windows user paths with backslashes should be sanitized."""
    error = "Cannot write to C:\\Users\\alice\\Documents\\secret.txt"
    result = sanitize_error_for_agent(error, "write_file")
    assert "alice" not in result

def test_windows_user_path_forward_slash(self):
    """Windows user paths with forward slashes should be sanitized."""
    error = "Error at C:/Users/bob/AppData/Local/config.json"
    result = sanitize_error_for_agent(error, "read_file")
    assert "bob" not in result

def test_unc_path_sanitized(self):
    """UNC paths should be sanitized."""
    error = "Cannot access \\\\fileserver\\Projects\\secret.doc"
    result = sanitize_error_for_agent(error, "read_file")
    assert "fileserver" not in result

def test_domain_user_sanitized(self):
    """Domain\\user patterns should be sanitized."""
    error = "Permission denied for DOMAIN\\alice"
    result = sanitize_error_for_agent(error, "bash")
    assert "alice" not in result
```

---

## Implementation Checklist

### Phase 1: Pattern Fixes
- [ ] **P1.1** Update `_PATH_PATTERN` at line 64 to exclude URLs and social paths
- [ ] **P1.2** Update "not found" pattern at line 109 to be more specific

### Phase 2: Testing
- [ ] **P2.1** Add tests for "String not found" preservation (edit_file bug)
- [ ] **P2.2** Add tests for clipboard/marker "not found" preservation
- [ ] **P2.3** Add tests confirming file/directory/path/source "not found" still sanitized
- [ ] **P2.4** Add tests for URL preservation (http, https, localhost)
- [ ] **P2.5** Add tests for social media path preservation (/r/, /u/, /g/)
- [ ] **P2.6** Add tests for price expression preservation ($50/month)
- [ ] **P2.7** Add tests confirming filesystem paths still sanitized
- [ ] **P2.8** Add Windows path tests (user paths, UNC, domain\user)
- [ ] **P2.9** Run full test suite: `.venv/bin/pytest tests/unit/test_error_sanitization.py -v`

### Phase 3: Live Testing
- [ ] **P3.1** Test edit_file with wrong old_string shows "String not found" (not "File not found")
- [ ] **P3.2** Test error with URL shows URL intact
- [ ] **P3.3** Test error with filesystem path shows `[path]`

---

## Validation Notes

**Explored 2026-01-31:**
- Confirmed `_PATH_PATTERN` at line 64, applied at line 141
- Confirmed "not found" pattern at line 109
- Identified 15+ skills returning "not found" style errors that could be affected
- Found real URL-containing errors in provider, MCP, GitLab, and RPC client code
- Windows patterns have 0% test coverage (5 patterns defined, 0 tests)
- Proposed path pattern tested against 26 cases: all pass

---

## Effort Estimate

~30 minutes implementation, ~30 minutes testing.
