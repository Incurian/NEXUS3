# Clipboard Plan Validation Report

Generated: 2026-01-30

## Summary

| Area | Status | Critical Issues |
|------|--------|-----------------|
| Internal Consistency | ISSUES | Code examples don't match checklist/schema reference |
| Skill Patterns | MINOR | Path validation uses wrong pattern |
| SQLite Patterns | ISSUES | Missing tables, foreign keys not enabled |
| Pool.py Integration | VALID | All integration points verified |
| Session Persistence | VALID | Pattern matches existing code |
| Context Injection | GAP | Token counting doesn't include injected content |
| Config Schema | VALID | Pydantic patterns correct |

---

## 1. Internal Consistency Issues (Agent adf3117)

### SCHEMA_SQL Missing Items
The code example in Implementation Details (lines 204-227) is missing:
- `expires_at` REAL column - mentioned in Schema Reference line 2576
- `ttl_seconds` INTEGER column - mentioned in Schema Reference line 2577
- `tags` table - mentioned in Schema Reference lines 2579-2587
- `clipboard_tags` junction table - mentioned in Schema Reference lines 2588-2594

### ClipboardTag Type Missing
- Referenced in Files Summary (line 2227) and checklist P1.2
- NOT defined in types.py code section (lines 48-184)
- Should have: id, name, description, created_at fields

### Skill Parameters Don't Match Checklist
- P2.2: "Add `tags` parameter to CopySkill" - NOT in code (lines 937-971)
- P2.3: "Add `ttl_seconds` parameter to CopySkill" - NOT in code

### ClipboardEntry Missing Fields
Schema Reference lists expires_at and ttl_seconds, but ClipboardEntry dataclass (lines 82-96) doesn't have them.

### Manager Methods Not Shown
- `cleanup_expired()` - called by P5b.1
- `_get_ttl_for_scope()` - called by P1.8
- `search()` - called by clipboard_search skill
- Tag management methods - called by P1.7

### Config Not Wired
Line 2002 shows hardcoded values:
```python
max_entries=10,  # TODO: get from config
```
But P5.3 says to wire config options.

---

## 2. Skill Pattern Issues (Agent acc850e)

### Path Validation Wrong Pattern
Plan uses isinstance check:
```python
validated = self._validate_path(source)
if isinstance(validated, ToolResult):
    return validated
```

Should use try/except (actual NEXUS3 pattern):
```python
try:
    source_path = self._validate_path(source)
except (PathSecurityError, ValueError) as e:
    return ToolResult(error=str(e))
```

### File I/O Not Async
Plan uses sync file operations:
```python
content = source_path.read_text(encoding="utf-8", errors="replace")
```

Should use asyncio.to_thread():
```python
content = await asyncio.to_thread(source_path.read_text, encoding="utf-8", errors="replace")
```

### What's Correct
- FileSkill.__init__(services) pattern
- self._services.get("clipboard_manager") pattern
- file_skill_factory(SkillClass) usage
- JSON Schema parameter format
- ToolResult(output=...) and ToolResult(error=...) usage

---

## 3. SQLite Pattern Issues (Agent afa6027)

### Missing PRAGMA foreign_keys
Clipboard schema defines CASCADE deletes but doesn't enable foreign keys:
```python
# MISSING from _ensure_db():
self._conn.execute("PRAGMA foreign_keys = ON")
```
Without this, CASCADE deletes won't work.

### Schema Code Incomplete
The SCHEMA_SQL shown (lines 204-227) is missing tags tables entirely.

Needs to add:
```sql
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS clipboard_tags (
    clipboard_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (clipboard_id, tag_id),
    FOREIGN KEY (clipboard_id) REFERENCES clipboard(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name);
CREATE INDEX IF NOT EXISTS idx_clipboard_tags_tag ON clipboard_tags(tag_id);
```

### What's Correct
- row_factory = sqlite3.Row
- WAL mode (valid choice)
- Schema versioning via metadata table
- UNIQUE constraints and indexes

---

## 4. Pool.py Integration (Agent a5f4b4b) - ALL VALID

### Verified Integration Points
- `_create_unlocked()` at lines 433-650 has correct insertion point after ServiceContainer
- `_restore_unlocked()` at lines 767-900+ exists with same pattern
- `destroy()` at lines 977-1055 has hook for TTL cleanup
- `permissions.effective_policy.level` exists and returns PermissionLevel enum
- `agent_cwd` available at line 566
- ServiceContainer.register() and .get() methods exist with correct signatures

### Recommended Insertion Points
- Clipboard registration: after line 567 (after cwd registration)
- TTL cleanup in destroy(): before line 1053 (before logger.close())
- Session restoration: after line 857 in _restore_unlocked()

---

## 5. Session Persistence (Agent a8b627d) - ALL VALID

### Verified Patterns
- SavedSession is @dataclass with to_dict() and from_dict() methods
- Current schema version is 1
- Complex fields like session_allowances use dict[str, Any] with field(default_factory=dict)
- Backwards compat via .get() with defaults - no migration code needed

### Recommended Implementation
```python
clipboard_agent_entries: dict[str, dict[str, Any]] = field(default_factory=dict)
```

In to_dict():
```python
"clipboard_agent_entries": self.clipboard_agent_entries,
```

In from_dict():
```python
clipboard_agent_entries=data.get("clipboard_agent_entries", {}),
```

---

## 6. Context Manager Injection (Agent a8f3af4)

### What's Correct
- Datetime injection pattern in build_messages() works as described
- ContextManager.__init__() can accept additional parameters
- Instance variable pattern (_clipboard_manager) matches _logger

### Critical Gap: Token Counting
Truncation methods count system tokens WITHOUT injection:
```python
# Line 515, 555
system_tokens = self._counter.count(self._system_prompt)  # RAW, no injection
```

But get_token_usage() counts WITH injection:
```python
# Line 393
system_tokens = self._counter.count(prompt_with_time)  # WITH datetime
```

When clipboard is added, mismatch gets worse. Truncation won't account for clipboard section size.

### Recommended Fix
Update truncation methods to inject datetime (and clipboard) before counting:
```python
datetime_line = get_current_datetime_str()
prompt_with_time = inject_datetime_into_prompt(self._system_prompt, datetime_line)
if self._clipboard_manager:
    clipboard_section = format_clipboard_context(...)
    if clipboard_section:
        prompt_with_time += "\n\n" + clipboard_section
system_tokens = self._counter.count(prompt_with_time)
```

### Import Strategy
Use TYPE_CHECKING to avoid circular imports:
```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from nexus3.clipboard import ClipboardManager
from nexus3.clipboard import format_clipboard_context
```

---

## 7. Config Schema (Agent ac95393) - ALL VALID

### Verified Patterns
- ClipboardConfig follows Pydantic BaseModel pattern
- ConfigDict(extra="forbid") matches existing configs
- Field() with validators (ge, le) matches existing patterns
- dict[str, int | None] for per_scope_ttl is valid Pydantic type
- default_factory=lambda for mutable defaults is correct
- Root Config integration matches existing nested configs

### User Override Example
```json
{
  "clipboard": {
    "enabled": true,
    "max_injected_entries": 15,
    "per_scope_ttl": {
      "project": 86400
    }
  }
}
```

---

## Action Items to Fix Plan

### Critical (Must Fix)
1. Add tags and clipboard_tags tables to SCHEMA_SQL code
2. Add expires_at and ttl_seconds columns to clipboard table schema
3. Add PRAGMA foreign_keys = ON to _ensure_db()
4. Define ClipboardTag dataclass in types.py
5. Add expires_at and ttl_seconds fields to ClipboardEntry
6. Add tags and ttl_seconds parameters to CopySkill.parameters

### Medium (Should Fix)
7. Change path validation from isinstance to try/except
8. Add asyncio.to_thread() for file I/O
9. Fix token counting in truncation methods
10. Wire ClipboardConfig values into injection (remove hardcoded)

### Low (Nice to Have)
11. Add index on clipboard_tags(tag_id)
12. Document TYPE_CHECKING import strategy
