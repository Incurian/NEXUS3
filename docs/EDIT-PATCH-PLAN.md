# Plan: Enhanced File Editing - Tool Separation, Batched Edits & Patch Skill

## Overview

Three enhancements to address agent file editing struggles:

1. **Tool separation** - Split `edit_file` into two distinct tools to eliminate mode confusion
2. **Batched edit_file** - Multiple string replacements in one atomic call
3. **New patch skill** - Apply unified diffs with strict validation

**Estimated effort**: Part 0 (1hr), Part 1 (1hr), Part 2 (3-4hr)

---

## Part 0: Separate edit_file into Two Tools

### Problem

Agents frequently hit this error:
```
Cannot use both string replacement and line-based mode
```

**Root cause**: `edit_file` has two mutually exclusive modes (string replacement vs line-based) but all parameters are listed together. Agents see 6 parameters and sometimes mix them, not realizing they're exclusive.

### Solution

Split into two distinct tools:

| New Tool | Parameters | Purpose |
|----------|------------|---------|
| `edit_file` | `old_string`, `new_string`, `replace_all` | String-based find/replace (safer) |
| `edit_lines` | `start_line`, `end_line`, `new_content` | Line-number-based replacement |

This eliminates mode confusion entirely - each tool has a single clear purpose.

### Implementation

**New file:** `nexus3/skill/builtin/edit_lines.py`

```python
class EditLinesSkill(FileSkill):
    """Replace lines by line number range."""

    @property
    def name(self) -> str:
        return "edit_lines"

    @property
    def description(self) -> str:
        return (
            "Replace lines by line number. For multiple edits, work bottom-to-top "
            "to avoid line number drift. Use edit_file for safer string-based edits."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to file"},
                "start_line": {"type": "integer", "description": "First line to replace (1-indexed)"},
                "end_line": {"type": "integer", "description": "Last line to replace (inclusive, defaults to start_line)"},
                "new_content": {"type": "string", "description": "Content to insert"}
            },
            "required": ["path", "start_line", "new_content"]
        }

    async def execute(self, path: str = "", start_line: int = 0, end_line: int | None = None, new_content: str = "", **kwargs: Any) -> ToolResult:
        # Move existing _line_replace() logic here
        ...
```

**Modify:** `nexus3/skill/builtin/edit_file.py`

1. Remove line-based parameters (`start_line`, `end_line`, `new_content`)
2. Remove mode detection logic
3. Keep only string replacement functionality
4. Simplify description to focus on string replacement

**Modify:** `nexus3/skill/builtin/registration.py`

```python
# Add import
from nexus3.skill.builtin.edit_lines import edit_lines_factory

# Add registration (after edit_file)
registry.register("edit_lines", edit_lines_factory)
```

### Migration

**Decision: Clean break** (no deprecation period)

Rationale:
- NEXUS3 is pre-1.0; agents are internal/controlled
- Deprecation warnings add code complexity for little benefit
- Line-based edits are rarely used (agents prefer string replacement)
- Clear error message guides migration: "edit_file no longer supports line-based edits. Use edit_lines instead."

If line-based params (`start_line`, `end_line`, `new_content`) are passed to `edit_file`, return clear error:
```python
return ToolResult(error="edit_file no longer supports line-based editing. Use edit_lines(path, start_line, new_content) instead.")
```

---

## Part 1: Batched edit_file Extension

### Design

Add optional `edits` array parameter alongside existing single-edit parameters:

```python
# Single edit (existing - unchanged)
edit_file(path="foo.py", old_string="x", new_string="y")

# Batched edits (new)
edit_file(path="foo.py", edits=[
    {"old_string": "import os", "new_string": "import os\nimport sys"},
    {"old_string": "def foo():", "new_string": "def foo() -> None:"},
    {"old_string": "return x", "new_string": "return result"}
])
```

### Semantics

- **Transaction guarantee**: All edits succeed or none apply (atomic)
- **Order matters**: Edits applied sequentially on in-memory content
- **Each edit validated**: Must find exactly 1 match (unless `replace_all`)
- **Single file**: All edits target same file (path parameter)
- **Mutual exclusion**: Cannot mix `edits` array with single-edit params

### Implementation

**File:** `nexus3/skill/builtin/edit_file.py`

1. Add `edits` parameter to schema:
   ```python
   "edits": {
       "type": "array",
       "items": {
           "type": "object",
           "properties": {
               "old_string": {"type": "string"},
               "new_string": {"type": "string"},
               "replace_all": {"type": "boolean", "default": False}
           },
           "required": ["old_string", "new_string"]
       },
       "description": "Array of string replacements (atomic - all or none)"
   }
   ```

2. Add `_batch_replace()` method:
   - Validate all edits before applying any
   - Track line number shifts for better error messages
   - Return combined result summary

3. Modify `execute()`:
   - Detect batch mode: `if edits is not None`
   - Validate mutual exclusion with single-edit params
   - Call `_batch_replace()` for batch mode

### Output Format

Line numbers refer to the **original file** (before any edits), not cumulative positions.

```
Applied 3 edits to foo.py:
  1. Replaced "import os" (line 1)
  2. Replaced "def foo():" (line 5)
  3. Replaced "return x" (line 12)
```

On failure (no changes written):
```
Batch edit failed (no changes made):
  Edit 2: "def bar():" not found in file
```

On ambiguous match:
```
Batch edit failed (no changes made):
  Edit 1: "x = 1" appears 3 times. Use replace_all=true or provide more context.
```

---

## Part 2: New Patch Skill

### Design

New skill that applies unified diffs with strict validation:

```python
# From file
patch(path="changes.diff")

# Inline diff
patch(diff="""--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
 import os
+import sys

 def main():
""")
```

### Architecture

Create new module `nexus3/patch/` with:

```
nexus3/patch/
├── __init__.py      # Public API
├── types.py         # Hunk, PatchFile, PatchSet dataclasses
├── parser.py        # Parse unified diff → structured objects
├── validator.py     # Detect/fix common LLM errors
└── applier.py       # Apply hunks with configurable strictness
```

**Skill file:** `nexus3/skill/builtin/patch.py`

### Parser (`parser.py`, ~120 LOC)

Parse unified diff format:
- `--- a/path` and `+++ b/path` headers
- `@@ -start,count +start,count @@` hunk headers
- Context lines (space prefix), removals (`-`), additions (`+`)
- Handle Git extended format (`diff --git`)

```python
@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[tuple[str, str]]  # (prefix, content)

@dataclass
class PatchFile:
    old_path: str
    new_path: str
    hunks: list[Hunk]

def parse_unified_diff(text: str) -> list[PatchFile]: ...
```

### Validator (`validator.py`, ~80 LOC)

Detect and optionally auto-fix common LLM errors:

| Error | Detection | Fix |
|-------|-----------|-----|
| Line count mismatch | Recount vs header | Recompute header |
| Trailing whitespace | Diff vs target | Normalize |
| Missing newline at EOF | Check last line | Add if needed |

```python
@dataclass
class ValidationResult:
    valid: bool
    errors: list[str]
    warnings: list[str]
    fixed_patch: PatchFile | None  # Auto-corrected version

def validate_patch(patch: PatchFile, target_content: str) -> ValidationResult: ...
```

### Applier (`applier.py`, ~150 LOC)

Apply hunks with configurable strictness:

```python
class ApplyMode(Enum):
    STRICT = "strict"      # Exact context match required
    TOLERANT = "tolerant"  # Allow whitespace differences
    FUZZY = "fuzzy"        # SequenceMatcher fallback (configurable threshold)

@dataclass
class ApplyResult:
    success: bool
    new_content: str
    applied_hunks: list[int]
    failed_hunks: list[tuple[int, str]]  # (index, reason)
    offset: int  # Cumulative line offset for diagnostics

def apply_patch(
    content: str,
    patch: PatchFile,
    mode: ApplyMode = ApplyMode.STRICT,
    fuzzy_threshold: float = 0.8
) -> ApplyResult: ...
```

**Offset tracking**: When applying multiple hunks, each hunk changes line numbers for subsequent hunks. The applier tracks cumulative offset:
- Hunk 1 at line 10 adds 2 lines → offset becomes +2
- Hunk 2 at line 50 now applies at line 52 (50 + offset)
- If Hunk 2 removes 3 lines → offset becomes +2-3 = -1

This is standard unified diff application semantics.

### Skill Parameters

```python
{
    "diff": {
        "type": "string",
        "description": "Unified diff content (inline)"
    },
    "diff_file": {
        "type": "string",
        "description": "Path to .diff/.patch file to read"
    },
    "target": {
        "type": "string",
        "description": "Target file to patch (required)"
    },
    "mode": {
        "type": "string",
        "enum": ["strict", "tolerant", "fuzzy"],
        "default": "strict",
        "description": "Matching strictness"
    },
    "fuzzy_threshold": {
        "type": "number",
        "minimum": 0.5,
        "maximum": 1.0,
        "default": 0.8,
        "description": "Similarity threshold for fuzzy mode (0.5-1.0)"
    },
    "dry_run": {
        "type": "boolean",
        "default": False,
        "description": "Validate without applying"
    }
}
```

**Parameter notes:**
- `diff` vs `diff_file`: Mutually exclusive. Use `diff` for inline content, `diff_file` to read from disk.
- `target`: Required. Explicit target file path. The diff's `--- a/path` header is informational only.
- If diff contains multiple files, only hunks matching `target` basename are used (with warning).

**Example with multi-file diff:**
```
patch(diff="...", target="src/foo.py")
# → Warning: Diff contains 3 files, applying only hunks for foo.py
# → Applied 2 hunks to src/foo.py
```

### Security

- **Path validation**: All target paths must be within allowed_paths
- **No subprocess**: Pure Python parsing and application
- **No path traversal**: Reject `..` in diff paths, validate against cwd
- **Atomic writes**: Use existing `atomic_write_text()`

### Output Format

Success:
```
Applied patch to foo.py: 3 hunks applied
```

Partial failure:
```
Patch failed on foo.py:
  Hunks 1-2: applied
  Hunk 3 failed: context mismatch at line 45
    Expected: "    return None"
    Found:    "    return result"
No changes made (atomic rollback).
```

Fuzzy match warning:
```
Applied patch to foo.py: 3 hunks applied
  Warning: Hunk 2 applied via fuzzy match (87% similarity at line 23)
```

Dry run:
```
Dry run - no changes made:
  foo.py: 3 hunks would apply
```

---

## Implementation Order

### Batch 0: Tool Separation (edit_file → edit_file + edit_lines)
1. Create `nexus3/skill/builtin/edit_lines.py` with line-based logic extracted from edit_file
2. Remove line-based parameters from `edit_file.py`, simplify to string-only
3. Register `edit_lines` in skill registry
4. Add unit tests for `edit_lines`
5. Update existing `edit_file` tests to remove line-based cases

### Batch 1: Batched edit_file
1. Extend schema with `edits` array parameter
2. Add `_batch_replace()` method with validation-first logic
3. Add unit tests for batch operations

### Batch 2: Patch module core
1. Create `nexus3/patch/types.py` - dataclasses
2. Create `nexus3/patch/parser.py` - unified diff parser
3. Create `nexus3/patch/validator.py` - error detection
4. Add parser unit tests

### Batch 3: Patch application
1. Create `nexus3/patch/applier.py` - hunk application logic
2. Implement strict/tolerant/fuzzy modes
3. Add applier unit tests

### Batch 4: Patch skill
1. Create `nexus3/skill/builtin/patch.py`
2. Wire into skill registry
3. Add integration tests

---

## Files to Modify

| File | Change |
|------|--------|
| `nexus3/skill/builtin/edit_file.py` | Remove line-based params, add `edits` param, `_batch_replace()` |
| `nexus3/skill/builtin/edit_lines.py` | **New** - line-based editing extracted from edit_file |
| `nexus3/skill/builtin/registration.py` | Add import and register `edit_lines`, `patch` |
| `nexus3/patch/__init__.py` | **New** - public API |
| `nexus3/patch/types.py` | **New** - dataclasses |
| `nexus3/patch/parser.py` | **New** - diff parser |
| `nexus3/patch/validator.py` | **New** - LLM error handling |
| `nexus3/patch/applier.py` | **New** - hunk application |
| `nexus3/skill/builtin/patch.py` | **New** - skill wrapper |
| `tests/unit/skill/test_edit_file.py` | **New** - string replacement + batch edit tests |
| `tests/unit/skill/test_edit_lines.py` | **New** - line-based editing tests |
| `tests/unit/patch/test_parser.py` | **New** - parser tests |
| `tests/unit/patch/test_applier.py` | **New** - applier tests |
| `tests/unit/skill/test_patch.py` | **New** - skill tests |

**Note:** There are currently no unit tests for `edit_file` - only security tests in `tests/security/test_multipath_confirmation.py`. All skill tests are new.

---

## Verification

### Unit Tests

**test_edit_file.py:**
- `test_string_replace_success` - basic old→new replacement
- `test_string_replace_not_found` - error when string missing
- `test_string_replace_ambiguous` - error when multiple matches without replace_all
- `test_string_replace_all` - replace_all=True works
- `test_rejects_line_params` - clear error if start_line/end_line passed
- `test_batch_success` - multiple edits in one call
- `test_batch_rollback` - no changes if any edit fails
- `test_batch_order_matters` - edits applied sequentially
- `test_batch_mutual_exclusion` - cannot mix edits array with single-edit params

**test_edit_lines.py:**
- `test_single_line_replace` - replace one line
- `test_range_replace` - replace lines start_line to end_line
- `test_start_line_validation` - error if < 1
- `test_end_line_validation` - error if end < start
- `test_line_out_of_bounds` - error if line > file length
- `test_newline_handling` - preserves/adds trailing newline correctly
- `test_rejects_string_params` - clear error if old_string passed

**test_parser.py:**
- `test_parse_simple_hunk` - single hunk, add/remove lines
- `test_parse_multiple_hunks` - multiple hunks same file
- `test_parse_git_format` - `diff --git a/...` header
- `test_parse_context_only` - hunk with only context lines
- `test_malformed_header` - graceful error on bad `@@` line
- `test_no_newline_at_eof` - `\ No newline at end of file` marker

**test_applier.py:**
- `test_strict_exact_match` - succeeds with exact context
- `test_strict_context_mismatch` - fails on any difference
- `test_tolerant_whitespace` - succeeds despite whitespace diffs
- `test_fuzzy_threshold` - matches with similarity ≥ threshold
- `test_offset_tracking` - correct line adjustment for multi-hunk
- `test_rollback_on_failure` - returns original content if any hunk fails

### Integration Tests
- `test_edit_lines_atomic_write` - verify temp file + rename
- `test_batch_edit_atomic_rollback` - verify file unchanged on failure
- `test_patch_inline_diff` - apply inline diff string
- `test_patch_from_file` - load and apply .diff file
- `test_patch_permission_enforcement` - respects allowed_paths

### Live Testing
```bash
nexus3 --fresh

# Test tool separation
> Use edit_file with old_string="x", new_string="y"
> Try edit_file with start_line=1 (should error with migration hint)
> Use edit_lines with start_line=1, new_content="test"

# Test batch edit
> Use edit_file with edits=[{old_string: "a", new_string: "b"}, ...]

# Test patch skill
> Use patch with inline diff to add an import
```

---

## Design Decisions

### Resolved

1. **Multi-file patches**: Single file per `patch()` call - simpler, explicit target
2. **Batch modes**: String replacement only for batched `edit_file` - line edits can use patch skill
3. **Fuzzy threshold**: Configurable via `fuzzy_threshold` param (default 0.8, range 0.5-1.0)
4. **Migration strategy**: Clean break, no deprecation period (see Part 0)
5. **Line numbers in batch output**: Reference original file positions
6. **Diff source parameter naming**: `diff` (inline) vs `diff_file` (path) - avoids confusion with `target`

### Open Questions

1. **Validator auto-fix**: Should validator automatically fix common LLM errors and apply the corrected patch, or just report errors?
   - **Proposal**: Auto-fix by default, add `strict_validation=True` param to disable
   - **Rationale**: LLMs frequently produce off-by-one line counts; auto-fix improves success rate

2. **Batch edit limit**: Should there be a max number of edits in one batch call?
   - **Proposal**: No limit initially; add if abuse observed
   - **Rationale**: Large batches are useful; tool timeout provides natural limit

---

## Dependencies

- Part 1 (batch edit) can proceed independently of Part 0 (tool separation)
- Part 2 (patch) is independent of Parts 0 and 1
- All parts can be implemented in parallel if desired

---

## Codebase Validation Notes

*Validated against NEXUS3 codebase on 2026-01-23*

### Confirmed Patterns

| Aspect | Status | Notes |
|--------|--------|-------|
| edit_file.py location | ✓ Exists | `nexus3/skill/builtin/edit_file.py` |
| Dual modes in edit_file | ✓ Confirmed | Both string and line-based modes present |
| Mode confusion error | ✓ Confirmed | Returns "Cannot use both..." error |
| FileSkill base class | ✓ Correct | Provides _validate_path() and services |
| file_skill_factory | ✓ Correct | Returns factory, attaches as cls.factory |
| Registration pattern | ✓ Correct | `registry.register(name, factory)` |
| No unit tests | ✓ Confirmed | Only security tests exist for edit_file |
| atomic_write_text | ✓ Exists | `nexus3/core/paths.py` line 156 |
| ToolResult pattern | ✓ Correct | Frozen dataclass with output/error fields |

### Verification Summary

All proposed architectural patterns match the current codebase:
- FileSkill inheritance pattern matches current file skills
- Factory registration matches current registry system
- ToolResult usage is standard across all skills
- atomic_write_text exists and is used in similar skills
- Parameter validation is automatically wrapped by file_skill_factory

**No corrections required** - the plan accurately reflects the codebase.

---

## Implementation Checklist

Use this checklist to track implementation progress. Each item can be assigned to a task agent.

### Part 0: Tool Separation (edit_file → edit_file + edit_lines)

- [ ] **P0.1** Create `nexus3/skill/builtin/edit_lines.py` with class skeleton
- [ ] **P0.2** Move line-based replacement logic from edit_file.py to EditLinesSkill
- [ ] **P0.3** Implement EditLinesSkill parameters (path, start_line, end_line, new_content)
- [ ] **P0.4** Add `edit_lines_factory = file_skill_factory(EditLinesSkill)`
- [ ] **P0.5** Register edit_lines in registration.py
- [ ] **P0.6** Remove line-based parameters from edit_file.py (start_line, end_line, new_content)
- [ ] **P0.7** Add migration error in edit_file for line params: "Use edit_lines instead"
- [ ] **P0.8** Update edit_file description to focus on string replacement only
- [ ] **P0.9** Add unit tests for edit_lines (single line, range, bounds validation)
- [ ] **P0.10** Update any existing edit_file tests

### Part 1: Batched edit_file

- [ ] **P1.1** Add `edits` array parameter to edit_file schema
- [ ] **P1.2** Implement `_batch_replace()` method with validation-first logic
- [ ] **P1.3** Add mutual exclusion check (edits vs single-edit params)
- [ ] **P1.4** Implement line number tracking for original file positions
- [ ] **P1.5** Add unit tests for batch success
- [ ] **P1.6** Add unit tests for batch rollback on failure
- [ ] **P1.7** Add unit tests for batch order matters
- [ ] **P1.8** Add unit tests for mutual exclusion check

### Part 2: Patch Module Core

- [ ] **P2.1** Create `nexus3/patch/` directory
- [ ] **P2.2** Implement `nexus3/patch/types.py` (Hunk, PatchFile, PatchSet dataclasses)
- [ ] **P2.3** Implement `nexus3/patch/parser.py` (parse_unified_diff function)
- [ ] **P2.4** Implement `nexus3/patch/validator.py` (ValidationResult, validate_patch)
- [ ] **P2.5** Implement `nexus3/patch/__init__.py` (public API exports)
- [ ] **P2.6** Add unit tests for parser (simple hunk, multiple hunks, git format)
- [ ] **P2.7** Add unit tests for validator (line count mismatch, whitespace)

### Part 3: Patch Application

- [ ] **P3.1** Implement `nexus3/patch/applier.py` with ApplyMode enum
- [ ] **P3.2** Implement strict mode (exact context match)
- [ ] **P3.3** Implement tolerant mode (whitespace tolerance)
- [ ] **P3.4** Implement fuzzy mode (SequenceMatcher fallback)
- [ ] **P3.5** Implement offset tracking for multi-hunk patches
- [ ] **P3.6** Add unit tests for each mode
- [ ] **P3.7** Add unit tests for offset tracking
- [ ] **P3.8** Add unit tests for rollback on failure

### Part 4: Patch Skill

- [ ] **P4.1** Create `nexus3/skill/builtin/patch.py` with PatchSkill class
- [ ] **P4.2** Implement parameters (diff, diff_file, target, mode, fuzzy_threshold, dry_run)
- [ ] **P4.3** Implement path validation for target file
- [ ] **P4.4** Implement path validation for diff_file
- [ ] **P4.5** Add `patch_factory = file_skill_factory(PatchSkill)`
- [ ] **P4.6** Register patch in registration.py
- [ ] **P4.7** Add unit tests for inline diff
- [ ] **P4.8** Add unit tests for file-based diff
- [ ] **P4.9** Add unit tests for dry-run mode

### Phase 5: Integration & Live Testing

- [ ] **P5.1** Integration test: edit_lines atomic write
- [ ] **P5.2** Integration test: batch edit atomic rollback
- [ ] **P5.3** Integration test: patch inline diff
- [ ] **P5.4** Integration test: patch from file
- [ ] **P5.5** Integration test: patch permission enforcement
- [ ] **P5.6** Live test with real NEXUS3 agent (all three tools)
- [ ] **P5.7** Verify no regressions in existing file skills

---

## Quick Reference: File Locations

| Component | File Path |
|-----------|-----------|
| edit_file skill | `nexus3/skill/builtin/edit_file.py` |
| edit_lines skill (new) | `nexus3/skill/builtin/edit_lines.py` |
| patch skill (new) | `nexus3/skill/builtin/patch.py` |
| Patch module types | `nexus3/patch/types.py` |
| Patch parser | `nexus3/patch/parser.py` |
| Patch validator | `nexus3/patch/validator.py` |
| Patch applier | `nexus3/patch/applier.py` |
| Skill registration | `nexus3/skill/builtin/registration.py` |
| FileSkill base | `nexus3/skill/base.py` |
| atomic_write_text | `nexus3/core/paths.py` |
| Unit tests (edit) | `tests/unit/skill/test_edit_file.py` |
| Unit tests (lines) | `tests/unit/skill/test_edit_lines.py` |
| Unit tests (patch) | `tests/unit/skill/test_patch.py` |
| Unit tests (parser) | `tests/unit/patch/test_parser.py` |
| Unit tests (applier) | `tests/unit/patch/test_applier.py` |

---

## Patch Hunk Format Reference

**Unified diff header:**
```
--- a/path/to/file.py
+++ b/path/to/file.py
@@ -start,count +start,count @@ optional context
 context line
-removed line
+added line
 context line
```

**Line prefixes:**
| Prefix | Meaning |
|--------|---------|
| ` ` (space) | Context line (unchanged) |
| `-` | Line removed from original |
| `+` | Line added in new version |
| `\ ` | No newline at end of file marker |
