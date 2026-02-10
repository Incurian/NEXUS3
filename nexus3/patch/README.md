# nexus3/patch

Pure Python unified diff parsing, validation, and application.

## Overview

The patch module provides tools for working with unified diffs (the format used by `git diff`, `diff -u`, etc.). It's designed to handle LLM-generated patches gracefully, with validation that can auto-fix common errors.

## Architecture

```
nexus3/patch/
├── __init__.py     # Public exports
├── types.py        # Hunk, PatchFile, PatchSet dataclasses
├── parser.py       # Parse unified diff text into structured objects
├── validator.py    # Validate patches and auto-fix common LLM errors
└── applier.py      # Apply patches with configurable strictness
```

## Quick Start

```python
from nexus3.patch import (
    parse_unified_diff,
    validate_patch,
    apply_patch,
    ApplyMode,
)

# Parse a diff
diff_text = """--- a/example.py
+++ b/example.py
@@ -1,3 +1,4 @@
 import os
+import sys

 def main():
"""
patches = parse_unified_diff(diff_text)

# Validate against target file
target_content = "import os\n\ndef main():\n    pass\n"
result = validate_patch(patches[0], target_content)
if not result.valid:
    print(f"Errors: {result.errors}")
    # Use auto-fixed version if available
    if result.fixed_patch:
        patches[0] = result.fixed_patch

# Apply the patch
apply_result = apply_patch(target_content, patches[0], mode=ApplyMode.STRICT)
if apply_result.success:
    new_content = apply_result.new_content
    print(f"Applied {len(apply_result.applied_hunks)} hunks")
```

## Apply Modes

| Mode | Description |
|------|-------------|
| `STRICT` | Exact context match required. Fails on any whitespace difference. |
| `TOLERANT` | Ignores trailing whitespace when matching context/removal lines. Also strips trailing whitespace from added lines. |
| `FUZZY` | Uses SequenceMatcher similarity to find context within a +/-50 line search window. Configurable threshold (default 0.8). Also strips trailing whitespace from added lines. |

```python
# Tolerant mode for whitespace-insensitive matching
result = apply_patch(content, patch, mode=ApplyMode.TOLERANT)

# Fuzzy mode with custom threshold
result = apply_patch(content, patch, mode=ApplyMode.FUZZY, fuzzy_threshold=0.7)
if result.warnings:
    print(f"Fuzzy matches: {result.warnings}")
```

## Validation Features

The validator detects and can auto-fix:

| Issue | Detection | Auto-Fix |
|-------|-----------|----------|
| Line count mismatch | Header says 3 lines, hunk has 4 | Recomputes header from actual lines (reported as warning, not error) |
| Trailing whitespace | Diff has `line ` but file has `line` | Normalizes context/removal lines to match file |
| Context mismatch | Context line doesn't match file | Reports error (not auto-fixable) |

```python
result = validate_patch(patch, target_content)
if result.fixed_patch:
    # Use the corrected version
    patch = result.fixed_patch
```

### Multi-File Validation

Use `validate_patch_set()` to validate multiple patches at once. New files (`is_new_file=True`) are automatically passed without content validation. Missing target files result in a file-not-found error (catches `FileNotFoundError` from the callback).

```python
from nexus3.patch import validate_patch_set

def read_file(path: str) -> str:
    return Path(path).read_text()

patches = parse_unified_diff(multi_file_diff)
results = validate_patch_set(patches, get_content=read_file)

for path, result in results.items():
    if not result.valid:
        print(f"{path}: {result.errors}")
```

## Data Types

### Hunk

Represents a single change region in a file.

```python
@dataclass
class Hunk:
    old_start: int      # Line number in original (1-indexed)
    old_count: int      # Lines affected in original
    new_start: int      # Line number in new version
    new_count: int      # Lines in new version
    lines: list[tuple[str, str]]  # (prefix, content)
    context: str = ""   # Optional function context from @@ line

    # Helper methods
    def count_removals(self) -> int: ...   # Count '-' lines
    def count_additions(self) -> int: ...  # Count '+' lines
    def count_context(self) -> int: ...    # Count ' ' lines
    def compute_counts(self) -> tuple[int, int]: ...  # (old_count, new_count) from lines
```

Line prefixes:
- `" "` (space) - Context line (unchanged)
- `"-"` - Line removed
- `"+"` - Line added

### PatchFile

Represents all changes to a single file.

```python
@dataclass
class PatchFile:
    old_path: str       # Original file path (without a/ prefix)
    new_path: str       # New file path (without b/ prefix)
    hunks: list[Hunk]
    is_new_file: bool   # True if old_path is /dev/null
    is_deleted: bool    # True if new_path is /dev/null

    @property
    def path(self) -> str:
        """Effective file path (new_path for edits/creates, old_path for deletes)."""
```

### PatchSet

A collection of patches for multiple files.

```python
@dataclass
class PatchSet:
    files: list[PatchFile]

    def get_file(self, path: str) -> PatchFile | None:
        """Get patch for a specific file path (matches path, old_path, or new_path)."""

    def file_paths(self) -> list[str]:
        """Get list of all affected file paths."""
```

### ValidationResult

Result of patch validation.

```python
@dataclass
class ValidationResult:
    valid: bool                    # True if patch can be applied
    errors: list[str]              # Critical errors preventing application
    warnings: list[str]            # Non-critical issues (patch may still apply)
    fixed_patch: PatchFile | None  # Auto-corrected version if fixable
```

### ApplyResult

Result of applying a patch.

```python
@dataclass
class ApplyResult:
    success: bool
    new_content: str             # Patched content if success, original content if failed
    applied_hunks: list[int]     # Indices of applied hunks
    failed_hunks: list[tuple[int, str]]  # (index, reason)
    warnings: list[str]          # Fuzzy match warnings, etc.
```

## Diff Format Reference

Standard unified diff format:

```diff
--- a/path/to/file.py
+++ b/path/to/file.py
@@ -start,count +start,count @@ optional context
 context line (unchanged)
-removed line
+added line
 context line
```

Git extended format (also supported):

```diff
diff --git a/file.py b/file.py
index abc123..def456 100644
--- a/file.py
+++ b/file.py
@@ -1,3 +1,4 @@
...
```

## Integration with Skill System

The `patch` skill (`nexus3/skill/builtin/patch.py`) wraps this module:

```python
# Via skill
result = await patch_skill.execute(
    target="example.py",
    diff=diff_text,
    mode="fuzzy",
    dry_run=True
)
```

See the skill's parameters for full options including `diff_file` for loading patches from disk.

## Error Handling

The module is designed to fail gracefully:

- Malformed diffs return empty `PatchFile` lists (parser)
- Invalid patches return `ValidationResult` with errors (validator)
- Failed hunks result in `ApplyResult` with `success=False` and original content unchanged (applier)
- Missing target files return `ValidationResult` with file-not-found error

**Atomic rollback:** `apply_patch` processes hunks sequentially. If any hunk fails, the original content is returned unchanged -- partial application never occurs.

No exceptions are raised for invalid input - check return values instead.

---

## Public API

All exports from `nexus3.patch`:

```python
from nexus3.patch import (
    # Types
    Hunk,
    PatchFile,
    PatchSet,
    # Parser
    parse_unified_diff,
    # Validator
    ValidationResult,
    validate_patch,
    validate_patch_set,
    # Applier
    ApplyMode,
    ApplyResult,
    apply_patch,
)
```

---

## Dependencies

### Internal Dependencies

None - this module is self-contained.

### External Dependencies

| Package | Usage | Required |
|---------|-------|----------|
| `difflib` | Fuzzy matching (SequenceMatcher) in applier | Yes (stdlib) |
| `re` | Hunk/file header parsing in parser | Yes (stdlib) |

---

## Status

Production-ready. Last updated: 2026-02-01
