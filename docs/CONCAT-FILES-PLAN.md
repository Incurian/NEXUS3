# concat_files Skill Implementation Plan

## Overview

Add a `concat_files` skill that recursively finds files by extension and concatenates them into a single output file. This enables agents to bundle source code for analysis, context loading, or export.

Based on the CLI tool in `.archive/concat_files.py`.

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Output destination | Write to file, return path | Prevents large outputs from filling context window |
| Size limits | None | User controls via `--max-total` and `--lines` |
| Dry-run | Parameter (`dry_run: bool`) | Single skill, good description explains both modes |
| Permissions | Validate search dir only | All found files are under validated directory |
| Token counting | Use `TokenCounter` | Accurate counts; lazy-load to avoid slowdown |
| Tree structure | Include if available | Check for `tree` command at runtime |
| Base class | `FileSkill` | Reuses path validation, consistent with other file skills |
| Skill name | `concat_files` | Clear, matches CLI tool |

---

## File Location

```
nexus3/skill/builtin/concat_files.py
```

---

## Parameters (JSON Schema)

```python
{
    "type": "object",
    "properties": {
        "extensions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "File extensions to include (without dots), e.g. ['py', 'ts']"
        },
        "path": {
            "type": "string",
            "default": ".",
            "description": "Directory to search (default: current directory)"
        },
        "exclude": {
            "type": "array",
            "items": {"type": "string"},
            "default": [],
            "description": "Additional patterns to exclude (e.g. ['test', 'vendor'])"
        },
        "lines": {
            "type": "integer",
            "default": 0,
            "description": "Max lines per file (0 = unlimited)"
        },
        "max_total": {
            "type": "integer",
            "default": 0,
            "description": "Max total lines across all files (0 = unlimited)"
        },
        "format": {
            "type": "string",
            "enum": ["plain", "markdown", "xml"],
            "default": "plain",
            "description": "Output format"
        },
        "sort": {
            "type": "string",
            "enum": ["alpha", "mtime", "size"],
            "default": "alpha",
            "description": "File sort order"
        },
        "gitignore": {
            "type": "boolean",
            "default": false,
            "description": "Respect .gitignore rules (requires git)"
        },
        "dry_run": {
            "type": "boolean",
            "default": false,
            "description": "Return stats without creating file"
        }
    },
    "required": ["extensions"]
}
```

---

## Tool Description (for LLM)

```
Concatenate source files into a single output file.

Recursively finds files with specified extensions and combines them with
headers showing file paths and line counts. Useful for bundling code for
analysis or export.

USAGE:
  concat_files(extensions=["py"])           # All Python files in CWD
  concat_files(extensions=["py", "ts"], path="src")  # Python + TypeScript in src/
  concat_files(extensions=["py"], dry_run=True)      # Preview without creating file

OUTPUT:
  Returns the path to the created file (e.g., "project_py_files.txt").
  The file contains concatenated source with headers for each file.

DRY RUN MODE:
  When dry_run=True, returns stats instead of creating a file:
  - File count and list
  - Total lines and characters
  - Estimated token count (useful for context budgeting)

OPTIONS:
  - format: "plain" (comments), "markdown" (code fences), "xml" (structured)
  - sort: "alpha" (path), "mtime" (newest first), "size" (largest first)
  - lines: Limit lines per file (truncates large files)
  - max_total: Stop after N total lines (budget-aware)
  - exclude: Additional patterns to skip (e.g., ["test", "fixtures"])
  - gitignore: Use .gitignore rules for filtering

DEFAULT EXCLUSIONS:
  node_modules, .git, __pycache__, .venv, dist, build, target, vendor, etc.
```

---

## Implementation Structure

```python
"""Concatenate source files skill."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Literal

from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory, handle_file_errors

if TYPE_CHECKING:
    from nexus3.skill.services import ServiceContainer


# --- Constants ---

DEFAULT_EXCLUDES: frozenset[str] = frozenset({
    "node_modules", ".git", "__pycache__", ".venv", "venv", ".tox",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
    ".egg-info", ".next", ".nuxt", "coverage", ".coverage", "htmlcov",
    "target", "vendor", "Debug", "Release", "x64", "x86", ".vs", "packages",
})

EXT_TO_LANG: dict[str, str] = {
    "py": "python", "js": "javascript", "ts": "typescript",
    "jsx": "jsx", "tsx": "tsx", "rs": "rust", "go": "go",
    # ... (full mapping from concat_files.py)
}

OutputFormat = Literal["plain", "markdown", "xml"]
SortOrder = Literal["alpha", "mtime", "size"]


# --- Data Classes ---

@dataclass
class FileInfo:
    """Information about a file to concatenate."""
    path: Path
    lines: int
    chars: int
    mtime: float
    size: int


@dataclass
class DryRunResult:
    """Result of a dry-run analysis."""
    file_count: int
    binary_skipped: int
    total_lines: int
    total_chars: int
    estimated_tokens: int
    files: list[dict[str, Any]]  # [{path, lines, included_lines}, ...]


# --- Skill Implementation ---

class ConcatFilesSkill(FileSkill):
    """Skill for concatenating source files."""

    @property
    def name(self) -> str:
        return "concat_files"

    @property
    def description(self) -> str:
        return """Concatenate source files into a single output file.

Recursively finds files with specified extensions and combines them with
headers showing file paths and line counts. Returns the output file path.

Use dry_run=True to preview stats (file count, lines, tokens) without
creating a file. Useful for context budgeting before bundling large codebases.

Default exclusions: node_modules, .git, __pycache__, .venv, dist, build, etc."""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "extensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File extensions to include (without dots)"
                },
                "path": {
                    "type": "string",
                    "default": ".",
                    "description": "Directory to search"
                },
                "exclude": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                    "description": "Additional patterns to exclude"
                },
                "lines": {
                    "type": "integer",
                    "default": 0,
                    "description": "Max lines per file (0 = unlimited)"
                },
                "max_total": {
                    "type": "integer",
                    "default": 0,
                    "description": "Max total lines (0 = unlimited)"
                },
                "format": {
                    "type": "string",
                    "enum": ["plain", "markdown", "xml"],
                    "default": "plain"
                },
                "sort": {
                    "type": "string",
                    "enum": ["alpha", "mtime", "size"],
                    "default": "alpha"
                },
                "gitignore": {
                    "type": "boolean",
                    "default": False
                },
                "dry_run": {
                    "type": "boolean",
                    "default": False
                }
            },
            "required": ["extensions"]
        }

    @handle_file_errors
    async def execute(
        self,
        extensions: list[str] | None = None,
        path: str = ".",
        exclude: list[str] | None = None,
        lines: int = 0,
        max_total: int = 0,
        format: str = "plain",
        sort: str = "alpha",
        gitignore: bool = False,
        dry_run: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        """Execute the concat_files skill."""

        # Validate required parameter
        if not extensions:
            return ToolResult(error="extensions parameter is required")

        # Validate search directory (security check via FileSkill)
        search_dir = self._validate_path(path)
        if not search_dir.is_dir():
            return ToolResult(error=f"Not a directory: {path}")

        # Find files
        all_excludes = DEFAULT_EXCLUDES | set(exclude or [])
        if gitignore and _git_available(search_dir):
            files = _find_files_git(search_dir, extensions, exclude or [])
        else:
            files = _find_files_glob(search_dir, extensions, all_excludes)

        if not files:
            return ToolResult(
                output=f"No files with extensions {extensions} found in '{path}'"
            )

        # Get file info, filter binary
        file_infos, binary_count = _collect_file_info(files)

        # Sort
        file_infos = _sort_files(file_infos, sort)

        # Dry run mode
        if dry_run:
            result = _compute_dry_run(
                file_infos,
                lines,
                max_total,
                format,
                self._services,  # For TokenCounter
            )
            return ToolResult(output=json.dumps({
                "dry_run": True,
                "file_count": result.file_count,
                "binary_skipped": result.binary_skipped + binary_count,
                "total_lines": result.total_lines,
                "total_chars": result.total_chars,
                "estimated_tokens": result.estimated_tokens,
                "files": result.files,
            }, indent=2))

        # Generate output file
        output_path = _generate_output_path(search_dir, extensions, lines, format)

        # Write concatenated content
        stats = _write_concatenated(
            output_path,
            file_infos,
            extensions,
            search_dir,
            lines,
            max_total,
            format,
            exclude or [],
            gitignore,
        )

        return ToolResult(output=json.dumps({
            "output_file": str(output_path),
            "file_count": len(file_infos),
            "binary_skipped": binary_count,
            "total_lines": stats["lines"],
            "total_chars": stats["chars"],
            "estimated_tokens": stats["tokens"],
        }))


# --- Helper Functions ---

def _is_binary(path: Path) -> bool:
    """Check if file is binary (has null bytes in first 8KB)."""
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(8192)
    except (OSError, IOError):
        return True


def _git_available(search_dir: Path) -> bool:
    """Check if git is available and directory is in a repo."""
    try:
        subprocess.run(
            ["git", "-C", str(search_dir), "rev-parse", "--git-dir"],
            capture_output=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _find_files_glob(
    search_dir: Path,
    extensions: list[str],
    excludes: frozenset[str]
) -> list[Path]:
    """Find files using pathlib glob."""
    files: list[Path] = []
    for ext in extensions:
        for path in search_dir.glob(f"**/*.{ext}"):
            if path.is_file() and not _should_exclude(path, excludes):
                files.append(path)
    return files


def _find_files_git(
    search_dir: Path,
    extensions: list[str],
    user_excludes: list[str],
) -> list[Path]:
    """Find files using git ls-files (respects .gitignore)."""
    # Implementation from concat_files.py
    ...


def _should_exclude(path: Path, excludes: frozenset[str]) -> bool:
    """Check if path matches any exclude pattern."""
    for part in path.parts:
        if part in excludes:
            return True
        for exc in excludes:
            if exc.startswith("*") and part.endswith(exc[1:]):
                return True
    return False


def _collect_file_info(files: list[Path]) -> tuple[list[FileInfo], int]:
    """Collect FileInfo for each file, filtering binary files."""
    infos: list[FileInfo] = []
    binary_count = 0

    for path in files:
        if _is_binary(path):
            binary_count += 1
            continue
        try:
            stat = path.stat()
            content = path.read_text(encoding="utf-8", errors="replace")
            lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
            infos.append(FileInfo(
                path=path,
                lines=lines,
                chars=len(content),
                mtime=stat.st_mtime,
                size=stat.st_size,
            ))
        except (OSError, IOError):
            binary_count += 1

    return infos, binary_count


def _sort_files(files: list[FileInfo], order: str) -> list[FileInfo]:
    """Sort files by specified order."""
    if order == "alpha":
        return sorted(files, key=lambda f: str(f.path))
    elif order == "mtime":
        return sorted(files, key=lambda f: f.mtime, reverse=True)
    elif order == "size":
        return sorted(files, key=lambda f: f.size, reverse=True)
    return files


def _compute_dry_run(
    files: list[FileInfo],
    max_lines: int,
    max_total: int,
    format: str,
    services: "ServiceContainer",
) -> DryRunResult:
    """Compute dry-run statistics."""
    # Try to use TokenCounter for accurate estimates
    token_counter = None
    try:
        token_counter = services.get("token_counter")
    except Exception:
        pass

    total_lines = 0
    total_chars = 0
    file_details: list[dict[str, Any]] = []

    for info in files:
        included = info.lines
        chars = info.chars

        # Apply per-file limit
        if max_lines > 0 and included > max_lines:
            avg_chars = chars / (info.lines + 1) if info.lines > 0 else 0
            included = max_lines
            chars = int(avg_chars * included)

        # Check total limit
        if max_total > 0:
            remaining = max_total - total_lines
            if remaining <= 0:
                break
            if included > remaining:
                included = remaining

        total_lines += included
        total_chars += chars
        file_details.append({
            "path": str(PurePosixPath(info.path)),
            "lines": info.lines,
            "included_lines": included,
        })

    # Add header overhead
    overhead = {"plain": 200, "markdown": 150, "xml": 250}.get(format, 200)
    total_chars += len(files) * overhead + 500

    # Estimate tokens
    if token_counter:
        # Use actual token counter if available
        estimated_tokens = token_counter.count(" " * total_chars)
    else:
        # Fallback: ~4 chars per token
        estimated_tokens = (total_chars + 3) // 4

    return DryRunResult(
        file_count=len(files),
        binary_skipped=0,
        total_lines=total_lines,
        total_chars=total_chars,
        estimated_tokens=estimated_tokens,
        files=file_details,
    )


def _generate_output_path(
    search_dir: Path,
    extensions: list[str],
    max_lines: int,
    format: str,
) -> Path:
    """Generate output filename."""
    if search_dir == Path("."):
        dir_name = Path.cwd().name
    else:
        dir_name = search_dir.name

    ext_string = "_".join(extensions)
    file_ext = {"plain": "txt", "markdown": "md", "xml": "xml"}.get(format, "txt")

    if max_lines > 0:
        return Path(f"{dir_name}_{ext_string}_{max_lines}lines.{file_ext}")
    return Path(f"{dir_name}_{ext_string}_files.{file_ext}")


def _write_concatenated(
    output_path: Path,
    files: list[FileInfo],
    extensions: list[str],
    search_dir: Path,
    max_lines: int,
    max_total: int,
    format: str,
    excludes: list[str],
    gitignore: bool,
) -> dict[str, int]:
    """Write concatenated output and return stats."""
    # Implementation adapted from concat_files.py
    # Uses OutputWriter pattern for format-specific output
    ...
    return {"lines": 0, "chars": 0, "tokens": 0}


def _get_lang_for_file(path: Path) -> str:
    """Get language identifier for markdown code fences."""
    ext = path.suffix.lstrip(".").lower()
    name = path.name.lower()

    if name == "dockerfile":
        return "dockerfile"
    if name in ("makefile", "gnumakefile"):
        return "makefile"

    return EXT_TO_LANG.get(ext, ext)


def _normalize_path(path: Path) -> str:
    """Normalize path for display (forward slashes)."""
    return str(PurePosixPath(path))
```

---

## Registration

**In skill file** - add factory assignment after class definition:

```python
# At end of nexus3/skill/builtin/concat_files.py
concat_files_factory = file_skill_factory(ConcatFilesSkill)
```

**In registration.py** - add import and register:

```python
# Add import at top
from nexus3.skill.builtin.concat_files import concat_files_factory

# In register_builtin_skills function (note: takes only registry, not services)
def register_builtin_skills(registry: SkillRegistry) -> None:
    # ... existing registrations ...

    # File aggregation
    registry.register("concat_files", concat_files_factory)
```

---

## Testing Plan

### Unit Tests (`tests/unit/skill/test_concat_files.py`)

1. **Parameter validation**
   - Missing extensions returns error
   - Invalid path returns error
   - Invalid format/sort values rejected by schema

2. **File discovery**
   - Finds files with single extension
   - Finds files with multiple extensions
   - Respects default exclusions
   - Respects user exclusions
   - Handles empty directories

3. **Binary detection**
   - Skips binary files
   - Reports binary count in output

4. **Sorting**
   - Alpha sort orders by path
   - Mtime sort orders newest first
   - Size sort orders largest first

5. **Line limits**
   - Per-file limit truncates correctly
   - Total limit stops at budget
   - Combined limits work together

6. **Dry run**
   - Returns stats without creating file
   - Token estimate is reasonable
   - File list is accurate

7. **Output formats**
   - Plain format has comment headers
   - Markdown format has code fences
   - XML format is valid XML

### Integration Tests (`tests/integration/test_concat_files.py`)

1. **Permission integration**
   - Sandboxed agent can only concat within CWD
   - Path outside allowed_paths rejected
   - Trusted agent has broader access

2. **Real file operations**
   - Creates output file with correct content
   - Handles unicode files
   - Handles files with various line endings

3. **Gitignore integration**
   - Respects .gitignore when flag set
   - Falls back gracefully when git unavailable

### Live Testing (MANDATORY per CLAUDE.md)

```bash
# Start server
nexus3 &

# Create test agent
nexus3 rpc create test-concat --preset trusted

# Test basic usage
nexus3 rpc send test-concat "Use concat_files to bundle all Python files in nexus3/skill/builtin"

# Test dry run
nexus3 rpc send test-concat "Use concat_files with dry_run=True to see stats for all .py files in nexus3/"

# Verify output
ls -la *.txt  # Check created file
cat <output_file> | head -50  # Verify content

# Cleanup
nexus3 rpc destroy test-concat
```

---

## Implementation Order

1. **Create skill file** with basic structure and parameter schema
2. **Implement file discovery** (`_find_files_glob`, `_should_exclude`)
3. **Implement file info collection** (`_collect_file_info`, `_is_binary`)
4. **Implement dry-run mode** (`_compute_dry_run`)
5. **Implement output writing** (plain format first)
6. **Add markdown and XML formats**
7. **Add gitignore support**
8. **Register skill**
9. **Write unit tests**
10. **Write integration tests**
11. **Live test with real agent**

---

## Future Enhancements (Out of Scope)

- `--include` glob patterns (beyond extensions)
- Content search/filter within files
- Compression output option
- Streaming for very large outputs
- MCP tool exposure

---

## Codebase Validation Notes

*Validated against NEXUS3 codebase on 2026-01-23*

### Confirmed Patterns

| Aspect | Status | Notes |
|--------|--------|-------|
| FileSkill base class | ✓ Correct | Provides `_validate_path()` and services access |
| handle_file_errors decorator | ✓ Correct | Converts exceptions to ToolResult errors |
| _validate_path returns Path | ✓ Correct | Raises exceptions on invalid paths |
| Path security model | ✓ Correct | Validating search dir covers all found files |
| TokenCounter | ✓ Exists | Located at `nexus3/context/token_counter.py` |

### Corrections Applied

1. **Removed `@file_skill_factory` class decorator** - The factory is not a class decorator. Correct pattern is assigning the factory after class definition: `concat_files_factory = file_skill_factory(ConcatFilesSkill)`

2. **Fixed registration function signature** - Changed from `register_builtin_skills(registry, services)` to `register_builtin_skills(registry)`. Services are injected by SkillRegistry internally.

3. **Fixed registration call** - Changed from `registry.register(ConcatFilesSkill.factory(services))` to `registry.register("concat_files", concat_files_factory)`. Uses two-argument form with name and factory.

4. **Fixed TokenCounter method** - Changed from `token_counter.count_text()` to `token_counter.count()`.

### Notes

- TokenCounter may not be registered in ServiceContainer by default. The code gracefully handles this with try/except fallback to `chars // 4` heuristic.
- FileSkill validates paths using PathResolver which follows symlinks and checks containment.

---

## Implementation Checklist

Use this checklist to track implementation progress. Each item can be assigned to a task agent.

### Phase 1: Core Implementation

- [ ] **P1.1** Create `nexus3/skill/builtin/concat_files.py` with class skeleton
- [ ] **P1.2** Add parameter schema (extensions, path, exclude, lines, max_total, format, sort, gitignore, dry_run)
- [ ] **P1.3** Implement `DEFAULT_EXCLUDES` constant and `EXT_TO_LANG` mapping
- [ ] **P1.4** Implement `_is_binary()` helper function
- [ ] **P1.5** Implement `_find_files_glob()` for file discovery
- [ ] **P1.6** Implement `_should_exclude()` for pattern matching
- [ ] **P1.7** Implement `FileInfo` and `DryRunResult` dataclasses

### Phase 2: File Processing

- [ ] **P2.1** Implement `_collect_file_info()` (read files, count lines, filter binary)
- [ ] **P2.2** Implement `_sort_files()` (alpha, mtime, size)
- [ ] **P2.3** Implement `_compute_dry_run()` with token estimation
- [ ] **P2.4** Implement `_generate_output_path()` for output filename

### Phase 3: Output Writing

- [ ] **P3.1** Implement `_write_concatenated()` with plain format
- [ ] **P3.2** Add markdown format (code fences with language)
- [ ] **P3.3** Add XML format (structured with file elements)
- [ ] **P3.4** Implement `_get_lang_for_file()` for language detection

### Phase 4: Git Integration

- [ ] **P4.1** Implement `_git_available()` helper
- [ ] **P4.2** Implement `_find_files_git()` using `git ls-files`
- [ ] **P4.3** Handle gitignore flag in main execute method

### Phase 5: Registration & Testing

- [ ] **P5.1** Add `concat_files_factory = file_skill_factory(ConcatFilesSkill)`
- [ ] **P5.2** Register in `nexus3/skill/builtin/registration.py`
- [ ] **P5.3** Write unit tests for parameter validation
- [ ] **P5.4** Write unit tests for file discovery
- [ ] **P5.5** Write unit tests for binary detection
- [ ] **P5.6** Write unit tests for sorting
- [ ] **P5.7** Write unit tests for line limits
- [ ] **P5.8** Write unit tests for dry-run mode
- [ ] **P5.9** Write unit tests for output formats

### Phase 6: Integration & Live Testing

- [ ] **P6.1** Integration test: sandboxed agent path restrictions
- [ ] **P6.2** Integration test: file creation with correct content
- [ ] **P6.3** Integration test: unicode and line ending handling
- [ ] **P6.4** Integration test: gitignore integration
- [ ] **P6.5** Live test with real NEXUS3 agent
- [ ] **P6.6** Verify no regressions in existing skills

---

## Quick Reference: File Locations

| Component | File Path |
|-----------|-----------|
| Skill implementation | `nexus3/skill/builtin/concat_files.py` |
| Skill registration | `nexus3/skill/builtin/registration.py` |
| Base class | `nexus3/skill/base.py` (FileSkill) |
| TokenCounter | `nexus3/context/token_counter.py` |
| Reference implementation | `.archive/concat_files.py` |
| Unit tests | `tests/unit/skill/test_concat_files.py` |
| Integration tests | `tests/integration/test_concat_files.py` |

---

## Output Format Reference

**Plain format:**
```
# ====================================
# File: path/to/file.py
# Lines: 42
# ====================================
<file content>
```

**Markdown format:**
```markdown
## path/to/file.py (42 lines)

```python
<file content>
```
```

**XML format:**
```xml
<file path="path/to/file.py" lines="42">
<![CDATA[
<file content>
]]>
</file>
```
