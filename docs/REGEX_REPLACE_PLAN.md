# Regex Replace Skill Plan

**Date**: 2026-01-13
**Status**: Draft
**Goal**: Add regex-based find/replace capability without bloating the existing `edit_file` skill.

---

## Executive Summary

Create a new `regex_replace` skill (separate from `edit_file`) for pattern-based text replacement. This keeps `edit_file` simple (exact string/line replacement) while providing powerful regex capabilities for refactoring tasks.

---

## Why New Skill vs Enhancing edit_file?

| Factor | Enhance edit_file | New regex_replace |
|--------|-------------------|-------------------|
| **API Complexity** | 10+ params, 3 modes | Clean 5-6 params |
| **User Mental Model** | Confusing mode detection | Clear: "exact match" vs "pattern match" |
| **Maintenance** | Complex branching logic | Isolated, testable |
| **Safety** | Harder to add regex timeout | Dedicated safety handling |

**Decision**: New skill. Keep `edit_file` for exact replacements, `regex_replace` for patterns.

---

## Skill Interface

### Parameters

```python
{
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path to file to edit"
        },
        "pattern": {
            "type": "string",
            "description": "Regular expression pattern to match"
        },
        "replacement": {
            "type": "string",
            "description": "Replacement string (supports \\1, \\2, \\g<name> backreferences)"
        },
        "count": {
            "type": "integer",
            "description": "Maximum replacements (0 = all, default: 0)"
        },
        "ignore_case": {
            "type": "boolean",
            "description": "Case-insensitive matching (default: false)"
        },
        "multiline": {
            "type": "boolean",
            "description": "^ and $ match line boundaries (default: false)"
        },
        "dotall": {
            "type": "boolean",
            "description": ". matches newlines (default: false)"
        }
    },
    "required": ["path", "pattern", "replacement"]
}
```

---

## Implementation

```python
"""Regex replace skill for pattern-based file editing."""

import asyncio
import re
from pathlib import Path
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import normalize_path, validate_sandbox
from nexus3.core.types import ToolResult
from nexus3.skill.services import ServiceContainer

# Safety limits
MAX_REPLACEMENTS = 10000
REGEX_TIMEOUT = 5.0  # seconds


class RegexReplaceSkill:
    """Skill that performs regex-based find/replace in files.

    Uses Python's re.sub() with safety limits for catastrophic backtracking.
    Supports backreferences in replacement strings.
    """

    def __init__(self, allowed_paths: list[Path] | None = None) -> None:
        self._allowed_paths = allowed_paths

    @property
    def name(self) -> str:
        return "regex_replace"

    @property
    def description(self) -> str:
        return "Replace text in a file using regular expression pattern"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to file to edit"
                },
                "pattern": {
                    "type": "string",
                    "description": "Regular expression pattern to match"
                },
                "replacement": {
                    "type": "string",
                    "description": "Replacement string (supports \\1, \\g<name> backreferences)"
                },
                "count": {
                    "type": "integer",
                    "description": "Maximum replacements (0 = all)",
                    "default": 0
                },
                "ignore_case": {
                    "type": "boolean",
                    "description": "Case-insensitive matching",
                    "default": False
                },
                "multiline": {
                    "type": "boolean",
                    "description": "^ and $ match line boundaries",
                    "default": False
                },
                "dotall": {
                    "type": "boolean",
                    "description": ". matches newlines",
                    "default": False
                }
            },
            "required": ["path", "pattern", "replacement"]
        }

    async def execute(
        self,
        path: str = "",
        pattern: str = "",
        replacement: str = "",
        count: int = 0,
        ignore_case: bool = False,
        multiline: bool = False,
        dotall: bool = False,
        **kwargs: Any
    ) -> ToolResult:
        """Execute regex replacement.

        Args:
            path: File to edit
            pattern: Regex pattern
            replacement: Replacement string (supports backreferences)
            count: Max replacements (0 = unlimited)
            ignore_case: Case-insensitive flag
            multiline: Multiline flag (^ $ match line boundaries)
            dotall: Dotall flag (. matches newline)

        Returns:
            ToolResult with replacement count or error
        """
        if not path:
            return ToolResult(error="Path is required")
        if not pattern:
            return ToolResult(error="Pattern is required")

        # Build regex flags
        flags = 0
        if ignore_case:
            flags |= re.IGNORECASE
        if multiline:
            flags |= re.MULTILINE
        if dotall:
            flags |= re.DOTALL

        # Compile regex with error handling
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return ToolResult(error=f"Invalid regex pattern: {e}")

        try:
            # Validate path against sandbox
            if self._allowed_paths is not None:
                p = validate_sandbox(path, self._allowed_paths)
            else:
                p = normalize_path(path)

            # Read file
            try:
                content = await asyncio.to_thread(p.read_text, encoding="utf-8")
            except FileNotFoundError:
                return ToolResult(error=f"File not found: {path}")
            except PermissionError:
                return ToolResult(error=f"Permission denied: {path}")

            # Count matches first (for reporting)
            matches = regex.findall(content)
            match_count = len(matches)

            if match_count == 0:
                return ToolResult(output=f"No matches for pattern in {path}")

            # Safety check
            if match_count > MAX_REPLACEMENTS and count == 0:
                return ToolResult(
                    error=f"Pattern matches {match_count} times (max {MAX_REPLACEMENTS}). "
                    f"Use count parameter to limit replacements."
                )

            # Perform replacement with timeout
            try:
                def do_replace() -> str:
                    if count == 0:
                        return regex.sub(replacement, content)
                    else:
                        return regex.sub(replacement, content, count=count)

                new_content = await asyncio.wait_for(
                    asyncio.to_thread(do_replace),
                    timeout=REGEX_TIMEOUT
                )
            except asyncio.TimeoutError:
                return ToolResult(
                    error=f"Regex replacement timed out ({REGEX_TIMEOUT}s). "
                    "Pattern may have catastrophic backtracking."
                )

            # Check if anything changed
            if new_content == content:
                return ToolResult(output=f"Pattern matched but replacement produced no changes")

            # Write result
            await asyncio.to_thread(p.write_text, new_content, encoding="utf-8")

            actual_replacements = min(match_count, count) if count > 0 else match_count
            return ToolResult(
                output=f"Replaced {actual_replacements} match(es) in {path}"
            )

        except PathSecurityError as e:
            return ToolResult(error=str(e))
        except Exception as e:
            return ToolResult(error=f"Error: {e}")


def regex_replace_factory(services: ServiceContainer) -> RegexReplaceSkill:
    """Factory function for RegexReplaceSkill."""
    allowed_paths: list[Path] | None = services.get("allowed_paths")
    return RegexReplaceSkill(allowed_paths=allowed_paths)
```

---

## Common Use Cases

### Import Renaming
```python
regex_replace(
    path="src/app.py",
    pattern=r"from oldmodule import (\w+)",
    replacement=r"from newmodule import \1"
)
```

### Variable Renaming with Word Boundaries
```python
regex_replace(
    path="src/utils.py",
    pattern=r"\bOLD_NAME\b",
    replacement="NEW_NAME",
    ignore_case=False
)
```

### Multiline Docstring Update
```python
regex_replace(
    path="src/func.py",
    pattern=r'""".*?"""',
    replacement='"""Updated docstring."""',
    dotall=True
)
```

### Add Type Hints
```python
regex_replace(
    path="src/func.py",
    pattern=r"def (\w+)\(self\):",
    replacement=r"def \1(self) -> None:"
)
```

---

## Safety Features

| Feature | Implementation |
|---------|----------------|
| **Regex timeout** | 5s `asyncio.wait_for` on `re.sub` |
| **Match limit** | Max 10,000 replacements without explicit `count` |
| **Sandbox validation** | Uses `allowed_paths` from services |
| **Invalid pattern handling** | Catches `re.error`, returns friendly message |
| **Backtracking protection** | Timeout catches catastrophic patterns |

---

## Permission Integration

- Add `regex_replace` to `DESTRUCTIVE_ACTIONS` (it modifies files)
- In TRUSTED mode: Requires confirmation like `edit_file`
- In SANDBOXED mode: Only within `allowed_paths`

```python
# In nexus3/core/permissions.py
DESTRUCTIVE_ACTIONS = {
    "write_file",
    "edit_file",
    "regex_replace",  # Add this
    "bash",
    ...
}
```

---

## File Changes

| File | Changes |
|------|---------|
| `nexus3/skill/builtin/regex_replace.py` | New skill implementation |
| `nexus3/skill/builtin/registration.py` | Register regex_replace_factory |
| `nexus3/core/permissions.py` | Add to DESTRUCTIVE_ACTIONS |

---

## Test Plan

| Category | Tests |
|----------|-------|
| Basic replacement | Simple patterns, backreferences |
| Flags | ignore_case, multiline, dotall combinations |
| Count limiting | count=1, count=5, count=0 |
| Safety | Timeout on catastrophic backtracking, max match limit |
| Errors | Invalid regex, file not found, permission denied |
| Sandbox | Path validation with allowed_paths |
| Edge cases | Empty file, no matches, replacement same as original |

### Catastrophic Backtracking Test
```python
async def test_backtracking_timeout():
    """Verify timeout on patterns like (a+)+$ with long input."""
    skill = RegexReplaceSkill()
    result = await skill.execute(
        path=str(test_file),
        pattern=r"(a+)+$",  # Known catastrophic pattern
        replacement="b"
    )
    assert "timed out" in result.error
```

---

## Comparison: edit_file vs regex_replace

| Feature | edit_file | regex_replace |
|---------|-----------|---------------|
| Exact string match | ✅ Primary use | ❌ Use edit_file |
| Line replacement | ✅ Built-in | ❌ Use edit_file |
| Pattern matching | ❌ | ✅ Primary use |
| Backreferences | ❌ | ✅ \1, \g<name> |
| Case-insensitive | ❌ | ✅ Flag |
| Multiline patterns | ❌ | ✅ Flag |
| Safety timeout | N/A | ✅ 5s limit |

**Guidance for users**: Use `edit_file` for exact replacements (faster, simpler). Use `regex_replace` when you need pattern matching.

---

## Estimated Effort

- Implementation: 2-3 hours
- Tests: 2 hours
- Documentation: 30 min
- **Total**: 4-5 hours
