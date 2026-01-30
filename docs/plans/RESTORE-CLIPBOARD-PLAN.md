# Instructions: Restore Enhanced CLIPBOARD-PLAN.md

## Problem

The file `docs/plans/CLIPBOARD-PLAN.md` was reverted to a simplified v1 version. All enhancements from the validation/update session were lost.

## What Needs to Be Restored

The current plan is missing these integrated enhancements:

### 1. TTL Support
- Add `expires_at REAL` and `ttl_seconds INTEGER` columns to clipboard table
- Add `ClipboardEntry` fields: `expires_at`, `ttl_seconds`
- Add `is_expired` property to ClipboardEntry
- Add manager methods: `count_expired()`, `get_expired()`, `_get_ttl_for_scope()`
- Add storage methods: `count_expired()`, `get_expired()`
- **NO auto-delete** - TTL flags entries but doesn't remove them
- Default TTLs: project=30 days (2592000s), system=1 year (31536000s)
- Add to Future Enhancements: user-in-the-loop cleanup design

### 2. Tags Support
- Add `ClipboardTag` dataclass (id, name, description, created_at)
- Add `tags` table and `clipboard_tags` junction table to SCHEMA_SQL
- Add `tags: list[str]` field to ClipboardEntry
- Add manager methods: `add_tags()`, `remove_tags()`, `list_tags()`
- Add storage methods: `set_tags()`, `get_tags()`
- Add `tags` parameter to CopySkill

### 3. Search Skill
- Add `clipboard_search` skill with LIKE-based content search
- Add `search()` method to ClipboardManager

### 4. Import/Export Skills
- Add `clipboard_export` skill (entries to JSON file)
- Add `clipboard_import` skill (JSON file to entries)

### 5. Session Persistence
- Add `clipboard_agent_entries: dict[str, dict[str, Any]]` to SavedSession
- Add to_dict()/from_dict() handling

## Pattern Fixes Required

### SQLite Patterns
1. Add `PRAGMA foreign_keys = ON` to `_ensure_db()`
2. Add TOCTOU protection (atomic file creation with os.open)
3. Add index on `clipboard_tags(tag_id)`
4. Add partial index on `clipboard(expires_at)` for TTL queries

### Skill Patterns
5. Change path validation from `isinstance(validated, ToolResult)` to:
   ```python
   try:
       source_path = self._validate_path(source)
   except (PathSecurityError, ValueError) as e:
       return ToolResult(error=str(e))
   ```

6. Add async file I/O:
   ```python
   content = await asyncio.to_thread(
       source_path.read_text, encoding="utf-8", errors="replace"
   )
   ```

7. Add imports to skills: `asyncio`, `PathSecurityError` from `nexus3.core.errors`

### Context Injection Patterns
8. Wire ClipboardConfig values (not hardcoded `max_entries=10`)
9. Add TYPE_CHECKING import for ClipboardManager
10. Add clipboard_config parameter to ContextManager.__init__
11. Document token counting fix for truncation methods

### Config Patterns
12. Use direct instantiation: `clipboard: ClipboardConfig = ClipboardConfig()`
13. Use `default={}` not `default_factory=lambda` for dicts

## Files to Update

Apply changes to these sections of `docs/plans/CLIPBOARD-PLAN.md`:

1. **Estimated effort** - Update to ~20-26 hours with new phases
2. **types.py section** - Add ClipboardTag, update ClipboardEntry
3. **SCHEMA_SQL** - Add tags tables, expires_at, ttl_seconds, indexes
4. **storage.py _ensure_db()** - Add PRAGMA, TOCTOU protection
5. **storage.py methods** - Add count_expired, get_expired, set_tags, get_tags
6. **manager.py copy()** - Add tags, ttl_seconds params
7. **manager.py methods** - Add TTL and tag methods
8. **CopySkill imports** - Add asyncio, PathSecurityError
9. **CopySkill parameters** - Add tags, ttl_seconds
10. **CopySkill execute** - Fix path validation, async file I/O
11. **CutSkill execute** - Same fixes
12. **PasteSkill** - Same fixes
13. **Phase 5 Context Injection** - Wire config, add token counting note
14. **ClipboardConfig** - Add TTL config options
15. **Add Phase 5b** - TTL/Expiry Tracking (check-only)
16. **Add Phase 6** - Session Persistence
17. **Future Enhancements** - Add user-in-the-loop cleanup TODO
18. **Checklist** - Update with all new items
19. **Corrections Applied** - Document all 19 fixes

## Reference Documents

- Validation report: `/tmp/claude-1000/-home-inc-repos-NEXUS3-docs/34cfd35e-1e52-471c-99be-f8a5b11aba97/scratchpad/clipboard-validation-report.md`
- Current (reverted) plan: `docs/plans/CLIPBOARD-PLAN.md`

## Verification

After restoration, run explorer agents to validate:
1. SCHEMA_SQL patterns against session/storage.py
2. FileSkill patterns against existing skills
3. ContextManager injection patterns
4. Pool.py integration points
5. Config schema patterns
6. Session persistence patterns
7. Internal consistency check
