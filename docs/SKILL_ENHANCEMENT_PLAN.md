# Skill Enhancement Plan

**Date**: 2026-01-13
**Status**: Draft
**Goal**: Enhance existing skills and add new focused tools to reduce reliance on the `bash` escape valve while maintaining permission granularity.

---

## Executive Summary

The current skill set provides good coverage but has gaps that force users to either:
1. Grant `bash` access (all-or-nothing)
2. Use awkward workarounds (read+concat+write for append)

This plan proposes **3 enhancements** to existing skills and **3 new focused tools** that provide granular permissions while keeping each tool simple and learnable.

---

## Current State

### Existing Skills (16 total)

| Category | Skills |
|----------|--------|
| File I/O | `read_file`, `write_file`, `edit_file`, `list_directory`, `glob`, `grep` |
| Execution | `bash`, `run_python` |
| Agent Mgmt | `nexus_create`, `nexus_destroy`, `nexus_send`, `nexus_cancel`, `nexus_status`, `nexus_shutdown` |
| Utility | `sleep`, `echo` |

### Gap Analysis

| Gap | Current Workaround | Permission Issue |
|-----|-------------------|------------------|
| Read partial file (large files) | Read entire file, waste tokens | None |
| Read last N lines | `bash("tail -n 50 file")` | Requires bash |
| Append to file | read_file → concat → write_file | Awkward, race-prone |
| Get file metadata | `bash("stat file")` | Requires bash |
| Exclude dirs in glob | Manual filtering | None (but tedious) |
| Grep with context | `bash("grep -C3 pattern")` | Requires bash |
| Grep only certain files | `bash("grep --include='*.py'")` | Requires bash |

---

## Proposed Changes

### Part A: Enhance Existing Skills (3 changes)

#### A1: read_file + offset/limit

**Rationale**: Large files waste context tokens. Claude Code's Read tool has this.

**Changes**:
```python
# New parameters
"offset": {
    "type": "integer",
    "description": "Line number to start reading from (1-indexed, default: 1)"
},
"limit": {
    "type": "integer",
    "description": "Maximum number of lines to read (default: all)"
}
```

**Implementation**:
```python
async def execute(self, path: str = "", offset: int = 1, limit: int | None = None, **kwargs) -> ToolResult:
    content = await asyncio.to_thread(p.read_text, encoding="utf-8")
    lines = content.splitlines(keepends=True)

    start_idx = max(0, offset - 1)  # Convert to 0-indexed
    if limit is not None:
        end_idx = start_idx + limit
        lines = lines[start_idx:end_idx]
    else:
        lines = lines[start_idx:]

    # Include line numbers in output for context
    numbered = [f"{start_idx + i + 1}: {line}" for i, line in enumerate(lines)]
    return ToolResult(output="".join(numbered))
```

**Backwards Compatible**: Yes (offset=1, limit=None = current behavior)

**Files**: `nexus3/skill/builtin/read_file.py`

---

#### A2: glob + exclude

**Rationale**: Searching codebases requires excluding `node_modules`, `.git`, `__pycache__`, etc.

**Changes**:
```python
# New parameter
"exclude": {
    "type": "array",
    "items": {"type": "string"},
    "description": "Patterns to exclude (e.g., ['node_modules', '.git', '__pycache__'])"
}
```

**Implementation**:
```python
async def execute(self, pattern: str = "", path: str = ".", max_results: int = 100,
                  exclude: list[str] | None = None, **kwargs) -> ToolResult:
    # In do_glob():
    for match in base_path.glob(pattern):
        # Check exclusions
        if exclude:
            skip = False
            for excl in exclude:
                if excl in str(match):
                    skip = True
                    break
            if skip:
                continue
        # ... rest of logic
```

**Backwards Compatible**: Yes (exclude=None = current behavior)

**Files**: `nexus3/skill/builtin/glob_search.py`

---

#### A3: grep + include + context

**Rationale**: Most grep usage needs file filtering (`*.py`) and context lines.

**Changes**:
```python
# New parameters
"include": {
    "type": "string",
    "description": "Only search files matching this pattern (e.g., '*.py', '*.{js,ts}')"
},
"context": {
    "type": "integer",
    "description": "Number of lines to show before and after each match (default: 0)"
}
```

**Implementation**:
- `include`: Filter `files_to_search` with `fnmatch`
- `context`: Maintain a sliding window of lines, output `context` lines before/after matches

**Complexity**: Medium - context tracking requires careful deduplication when matches are close together

**Backwards Compatible**: Yes

**Files**: `nexus3/skill/builtin/grep.py`

---

### Part B: New Focused Tools (3 additions)

#### B1: tail

**Rationale**: "Last N lines" is extremely common and negative offsets are unintuitive.

**Parameters**:
```python
{
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Path to file"},
        "lines": {"type": "integer", "description": "Number of lines from end (default: 10)"}
    },
    "required": ["path"]
}
```

**Implementation**: Simple `lines[-n:]` slice.

**Permission Integration**: Uses `allowed_paths` like `read_file`.

**Files**: New `nexus3/skill/builtin/tail.py`

---

#### B2: file_info

**Rationale**: File metadata (size, mtime, type) without bash.

**Parameters**:
```python
{
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Path to file or directory"}
    },
    "required": ["path"]
}
```

**Output** (JSON):
```json
{
    "path": "/home/user/file.py",
    "type": "file",
    "size": 1234,
    "size_human": "1.2 KB",
    "modified": "2026-01-13T10:30:00",
    "permissions": "rw-r--r--",
    "exists": true
}
```

**Permission Integration**: Uses `allowed_paths` - can only stat files within sandbox.

**Files**: New `nexus3/skill/builtin/file_info.py`

---

#### B3: append_file

**Rationale**: Appending is common (logs, adding to lists) and read+concat+write is error-prone.

**Parameters**:
```python
{
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Path to file"},
        "content": {"type": "string", "description": "Content to append"},
        "newline": {"type": "boolean", "description": "Add newline before content if file doesn't end with one (default: true)"}
    },
    "required": ["path", "content"]
}
```

**Implementation**:
```python
async def execute(self, path: str, content: str, newline: bool = True, **kwargs) -> ToolResult:
    # Read existing (or empty if new file)
    existing = ""
    if p.exists():
        existing = await asyncio.to_thread(p.read_text, encoding="utf-8")

    # Smart newline handling
    if newline and existing and not existing.endswith("\n"):
        content = "\n" + content

    await asyncio.to_thread(p.write_text, existing + content, encoding="utf-8")
    return ToolResult(output=f"Appended {len(content)} bytes to {path}")
```

**Permission Integration**:
- Uses `allowed_paths` for write validation
- Should be in `DESTRUCTIVE_ACTIONS` for TRUSTED confirmation prompts

**Files**: New `nexus3/skill/builtin/append_file.py`

---

## Implementation Order

| Phase | Change | Complexity | Risk |
|-------|--------|------------|------|
| 1 | `read_file` + offset/limit | Low | None |
| 1 | `tail` (new) | Low | None |
| 1 | `file_info` (new) | Low | None |
| 2 | `glob` + exclude | Low | None |
| 2 | `append_file` (new) | Low | Permission integration |
| 3 | `grep` + include + context | Medium | Context dedup complexity |

**Phase 1**: Quick wins, no breaking changes, most useful
**Phase 2**: Simple additions with permission consideration
**Phase 3**: More complex grep enhancement

---

## File Changes Summary

### Modified Files
| File | Changes |
|------|---------|
| `nexus3/skill/builtin/read_file.py` | Add offset, limit params |
| `nexus3/skill/builtin/glob_search.py` | Add exclude param |
| `nexus3/skill/builtin/grep.py` | Add include, context params |
| `nexus3/skill/builtin/registration.py` | Register 3 new skills |
| `nexus3/core/permissions.py` | Add `append_file` to DESTRUCTIVE_ACTIONS |

### New Files
| File | Description |
|------|-------------|
| `nexus3/skill/builtin/tail.py` | Read last N lines |
| `nexus3/skill/builtin/file_info.py` | Get file metadata |
| `nexus3/skill/builtin/append_file.py` | Append content to file |

### Test Files (New)
| File | Coverage |
|------|----------|
| `tests/unit/test_read_file.py` | offset/limit behavior |
| `tests/unit/test_glob.py` | exclude patterns |
| `tests/unit/test_grep.py` | include, context |
| `tests/unit/test_tail.py` | tail behavior |
| `tests/unit/test_file_info.py` | metadata output |
| `tests/unit/test_append_file.py` | append, permissions |

---

## Permission Matrix (Post-Implementation)

| Skill | YOLO | TRUSTED | SANDBOXED |
|-------|------|---------|-----------|
| `read_file` | Full | Full | allowed_paths only |
| `tail` | Full | Full | allowed_paths only |
| `file_info` | Full | Full | allowed_paths only |
| `write_file` | Full | Confirm | allowed_paths only |
| `append_file` | Full | Confirm | allowed_paths only |
| `edit_file` | Full | Confirm | allowed_paths only |
| `glob` | Full | Full | allowed_paths only |
| `grep` | Full | Full | allowed_paths only |
| `list_directory` | Full | Full | allowed_paths only |
| `bash` | Full | Confirm | **Disabled** |
| `run_python` | Full | Confirm | **Disabled** |

---

## Success Criteria

1. **All existing tests pass** (1108 tests)
2. **New tests cover**:
   - Each new parameter combination
   - Sandbox enforcement for new skills
   - Edge cases (empty files, missing files, etc.)
3. **Documentation updated**:
   - CLAUDE.md skill table
   - skill/README.md with new skills
4. **No bash needed for**:
   - Reading partial files
   - Getting file info
   - Appending to files
   - Searching with exclusions

---

## Out of Scope

These are intentionally NOT included:

| Feature | Reason |
|---------|--------|
| Regex replacement in edit_file | Complex, sed via bash works |
| Binary file support | Rare, base64 via bash works |
| Insert mode (vs replace) | append_file + edit_file covers most cases |
| Git skill | Separate planning document needed |
| HTTP/curl skill | Separate planning document needed |

---

## Next Steps

1. [ ] Review and approve this plan
2. [ ] Implement Phase 1 (read_file, tail, file_info)
3. [ ] Run tests, update docs
4. [ ] Implement Phase 2 (glob, append_file)
5. [ ] Implement Phase 3 (grep)
6. [ ] Final review and merge
