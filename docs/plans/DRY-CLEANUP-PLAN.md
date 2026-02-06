# Plan: DRY Cleanup & Dead Code Elimination

## Overview

Comprehensive cleanup plan based on Opus 4.6 codebase review (2026-02-05). Covers DRY violations, dead code removal, naming collisions, and minor security/correctness fixes across the NEXUS3 codebase (~53,000 lines, 187 .py files).

**Status:** All decisions resolved. Ready for implementation.

## Scope

### Included
- P1: Extract platform-aware subprocess helpers (eliminates ~15 call sites of Windows/Unix branching)
- P2: Consolidate `_get_default_port()` (triplicated function)
- P3: Extract `_normalize_line()` in patch module (identical duplication)
- P4: Rename `ContextConfig` collision (two different classes, same name)
- P5: Delete `PromptBuilder`/`StructuredPrompt` (238 lines dead code), relocate `inject_datetime_into_prompt` tests
- P6: Replace `assert` with proper check in `rpc/http.py` (correctness)
- P7: Inherit `GitLabAPIError` from `NexusError` (error hierarchy consistency)
- P8: Clean up `ToolPermission` noqa import
- P9: Remove unused `StreamingDisplay` export (already marked deprecated)
- P10: GitLab `subprocess.run()` -> async (sync blocking in async context; 33 callers + 8 sync helpers + 41 cascade)

### Deferred to Future
- ToolResult error pattern consolidation (424 occurrences, 56 files - too large for this plan)
- Confirmation UI table-driven refactor (already in CLAUDE.md deferred work)
- HTTP error response helper in rpc/http.py (borderline - current code is readable)
- Large file splits (repl.py, repl_commands.py, pool.py, session.py - already tracked)

### Explicitly Excluded
- Any behavioral changes to skills or RPC protocol
- New features or capabilities
- Test-only changes (unless required by code changes)

---

## Design Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| P1: subprocess helper scope | Extract both `create_subprocess_exec()` AND `create_subprocess_shell()` | Only 1 shell call site, but fully DRY means zero platform branching in skill code |
| Where to put subprocess helpers? | `core/process.py` | Already has `WINDOWS_CREATIONFLAGS`, `terminate_process_tree()`, and platform detection via `sys.platform` |
| Where to put default port? | `core/constants.py` | Already has `get_defaults_dir()`, `get_nexus_dir()` - infrastructure constants belong here |
| P5: PromptBuilder fate | **Delete** | Written Jan 16, 2026 as "proper fix" but never wired in. Production code grew past it (clipboard injection, subagent dedup, README boundaries, get_system_info expansion). Not a strict improvement anymore. Dead code. |
| P5: inject_datetime tests | Move to new `tests/unit/context/test_inject_datetime.py` | These test a security fix in manager.py and must survive PromptBuilder deletion |
| ContextConfig rename target | Rename `context/manager.py` version to `ContextWindowConfig` | The schema.py version maps to `config.json` keys and shouldn't change. The manager version is about context window sizing. |
| P7: GitLabAPIError inheritance | Change to `NexusError` | Constructors compatible. `super().__init__()` passes a single string. `self.message` kept after `super()` for `repl_commands.py:2343`. |
| P9: StreamingDisplay | **Remove export** (not just comment) | Already marked "deprecated", zero external imports, purely internal to display/ module |

---

## Implementation Details

Each item below is self-contained. A model implementing any single item needs only the information in that section.

---

### P1: Platform-Aware Subprocess Helpers

**Goal:** Eliminate the repeated `if sys.platform == "win32": ... else: ...` branching that appears at every `asyncio.create_subprocess_exec()` and `asyncio.create_subprocess_shell()` call site. Add two helper functions to `core/process.py`.

**File to edit:** `nexus3/core/process.py`

**What to add** (after the existing `WINDOWS_CREATIONFLAGS` definition, before `terminate_process_tree`):

```python
async def create_subprocess_exec(
    *args: str,
    stdin: int | None = asyncio.subprocess.PIPE,
    stdout: int | None = asyncio.subprocess.PIPE,
    stderr: int | None = asyncio.subprocess.PIPE,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    **kwargs: Any,
) -> asyncio.subprocess.Process:
    """Create subprocess with platform-appropriate process group flags.

    On Unix: sets start_new_session=True for process group isolation.
    On Windows: sets CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP flags.

    This is the standard way to create subprocesses in NEXUS3. All skill
    code should use this instead of calling asyncio.create_subprocess_exec()
    directly with platform branching.
    """
    if sys.platform == "win32":
        kwargs["creationflags"] = WINDOWS_CREATIONFLAGS
    else:
        kwargs.setdefault("start_new_session", True)
    return await asyncio.create_subprocess_exec(
        *args, stdin=stdin, stdout=stdout, stderr=stderr, cwd=cwd, env=env, **kwargs,
    )


async def create_subprocess_shell(
    command: str,
    stdin: int | None = asyncio.subprocess.PIPE,
    stdout: int | None = asyncio.subprocess.PIPE,
    stderr: int | None = asyncio.subprocess.PIPE,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    **kwargs: Any,
) -> asyncio.subprocess.Process:
    """Create shell subprocess with platform-appropriate process group flags.

    Same as create_subprocess_exec() but uses shell=True interpretation.
    Only used by shell_UNSAFE skill - prefer create_subprocess_exec() for safety.
    """
    if sys.platform == "win32":
        kwargs["creationflags"] = WINDOWS_CREATIONFLAGS
    else:
        kwargs.setdefault("start_new_session", True)
    return await asyncio.create_subprocess_shell(
        command, stdin=stdin, stdout=stdout, stderr=stderr, cwd=cwd, env=env, **kwargs,
    )
```

**Required imports to add at top of `core/process.py`:**
```python
from pathlib import Path
from typing import Any
```

**Consumer files to update** (replace platform-branching `if/else` blocks with single calls):

#### 1. `nexus3/skill/builtin/bash.py` — `BashSafeSkill._create_process()` (lines ~113-139)

**Before (two branches, ~20 lines):**
```python
async def _create_process(self, work_dir: str | None) -> asyncio.subprocess.Process:
    """Create subprocess without shell."""
    if sys.platform == "win32":
        return await asyncio.create_subprocess_exec(
            *self._args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
            env=get_safe_env(work_dir),
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW),
        )
    else:
        return await asyncio.create_subprocess_exec(
            *self._args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
            env=get_safe_env(work_dir),
            start_new_session=True,
        )
```

**After (single call):**
```python
async def _create_process(self, work_dir: str | None) -> asyncio.subprocess.Process:
    """Create subprocess without shell."""
    return await create_subprocess_exec(
        *self._args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=work_dir,
        env=get_safe_env(work_dir),
    )
```

**Import to add:** `from nexus3.core.process import create_subprocess_exec`
**Import to remove:** `import subprocess` (safe to remove — only used for `CREATE_*` constants which are gone)
**Import to keep:** `import sys` — still needed at lines 161 and 166 for shlex Windows mode detection

#### 2. `nexus3/skill/builtin/bash.py` — `ShellUnsafeSkill._create_process()` (lines ~241-267)

**After:**
```python
async def _create_process(self, work_dir: str | None) -> asyncio.subprocess.Process:
    """Create shell subprocess."""
    return await create_subprocess_shell(
        self._command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=work_dir,
        env=get_safe_env(work_dir),
    )
```

**Import to add:** `from nexus3.core.process import create_subprocess_exec, create_subprocess_shell`

#### 3. `nexus3/skill/builtin/run_python.py` — `_create_process()` (lines ~70-96)

**After:**
```python
async def _create_process(self, work_dir: str | None) -> asyncio.subprocess.Process:
    """Create a Python subprocess."""
    return await create_subprocess_exec(
        sys.executable, "-c", self._code,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=work_dir,
        env=get_safe_env(work_dir),
    )
```

**Note:** Keep `import sys` — it's still needed for `sys.executable`.
**Import to add:** `from nexus3.core.process import create_subprocess_exec`
**Import to remove:** `import subprocess` (safe — only used for `CREATE_*` constants)

#### 4. `nexus3/skill/builtin/git.py` — `execute()` method (lines ~284-305)

**Before:**
```python
if sys.platform == "win32":
    process = await asyncio.create_subprocess_exec(
        *cmd_parts,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=str(work_dir), env=get_safe_env(str(work_dir)),
        creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW),
    )
else:
    process = await asyncio.create_subprocess_exec(
        *cmd_parts,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=str(work_dir), env=get_safe_env(str(work_dir)),
        start_new_session=True,
    )
```

**After:**
```python
process = await create_subprocess_exec(
    *cmd_parts,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    cwd=str(work_dir),
    env=get_safe_env(str(work_dir)),
)
```

**Import to add:** `from nexus3.core.process import create_subprocess_exec`
**Import to remove:** `import subprocess` (safe to remove)
**Import to keep:** `import sys` — still needed at lines 130 and 135 for shlex Windows mode detection in `_validate_command()`

#### 5. `nexus3/skill/builtin/grep.py` — grep execution (lines ~228-245)

**Before:**
```python
if sys.platform == "win32":
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW),
    )
else:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
```

**After:**
```python
proc = await create_subprocess_exec(
    *cmd,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
```

**Note:** No `cwd` or `env` kwargs here — the helper defaults are fine (stdin=PIPE is also fine for grep since it doesn't use stdin).
**Import to add:** `from nexus3.core.process import create_subprocess_exec`
**Import to remove:** `import subprocess` and `import sys` (both safe — no other uses in grep.py)

#### 6. `nexus3/skill/builtin/concat_files.py` — 3 pairs of calls (6 total, lines ~427-517)

This file has 3 separate subprocess calls, each with Windows/Unix branching:
- `_git_available()` — `git rev-parse --is-inside-work-tree` (lines ~427-442)
- `_find_files_git()` — `git ls-files -z` for tracked files (lines ~481-496)
- `_find_files_git()` — `git ls-files -z --others` for untracked files (lines ~502-517)

**Pattern for each — before (example for first one):**
```python
if IS_WINDOWS:
    proc = await asyncio.create_subprocess_exec(
        "git", "rev-parse", "--is-inside-work-tree",
        cwd=path, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        creationflags=WINDOWS_CREATIONFLAGS,
    )
else:
    proc = await asyncio.create_subprocess_exec(
        "git", "rev-parse", "--is-inside-work-tree",
        cwd=path, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
```

**After:**
```python
proc = await create_subprocess_exec(
    "git", "rev-parse", "--is-inside-work-tree",
    cwd=path,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
```

Apply the same pattern to all 3 pairs. Each becomes a single call.

**Import to change:** `from nexus3.core.process import WINDOWS_CREATIONFLAGS` → `from nexus3.core.process import create_subprocess_exec`. Note: `IS_WINDOWS` is defined locally at line 211 (`IS_WINDOWS = sys.platform == "win32"`) and is used extensively elsewhere in the file for non-subprocess purposes — do NOT remove it. There is no `import subprocess` in this file.
**Import to keep:** `import sys` (needed for local `IS_WINDOWS` definition)

#### 7. `nexus3/mcp/transport.py` — MCP server launch (lines ~297-322)

**Before:**
```python
if sys.platform == "win32":
    self._process = await asyncio.create_subprocess_exec(
        *resolved_command,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=env, cwd=self._cwd,
        creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW),
    )
else:
    self._process = await asyncio.create_subprocess_exec(
        *resolved_command,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=env, cwd=self._cwd,
        start_new_session=True,
    )
```

**After:**
```python
self._process = await create_subprocess_exec(
    *resolved_command,
    stdin=asyncio.subprocess.PIPE,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    env=env,
    cwd=self._cwd,
)
```

**Import to add:** `from nexus3.core.process import create_subprocess_exec`
**Import to remove:** `import subprocess` (safe — only used for `CREATE_*` constants)
**Import to keep:** `import sys` — still needed at line 154 for `resolve_command()` (`sys.platform != "win32"` check)

#### 8. `nexus3/core/process.py` — taskkill call in `_terminate_windows()` (line ~125)

This is inside the same file where the helpers are defined. Currently:
```python
taskkill = await asyncio.create_subprocess_exec(
    "taskkill", "/T", "/F", "/PID", str(pid),
    stdout=asyncio.subprocess.DEVNULL,
    stderr=asyncio.subprocess.DEVNULL,
    creationflags=WINDOWS_CREATIONFLAGS,
)
```

**Decision:** Leave this as-is. It's a Windows-only code path inside a Windows-only function (`_terminate_windows`). Using the helper here would be circular and misleading since the helper adds `start_new_session` on Unix, but this code never runs on Unix.

**Cleanup after all consumer updates:**
- Run `ruff check nexus3/ --select F401` to catch any now-unused imports in consumer files
- Summary of import changes per file:
  - `bash.py`: remove `import subprocess`, keep `import sys` (shlex at lines 161, 166)
  - `run_python.py`: remove `import subprocess`, keep `import sys` (sys.executable)
  - `git.py`: remove `import subprocess`, keep `import sys` (shlex at lines 130, 135)
  - `grep.py`: remove `import subprocess` and `import sys` (both now unused)
  - `concat_files.py`: change `from nexus3.core.process import WINDOWS_CREATIONFLAGS` → `from nexus3.core.process import create_subprocess_exec`. Keep `import sys` (local `IS_WINDOWS` at line 211, used extensively for non-subprocess logic). No `import subprocess` exists.
  - `mcp/transport.py`: remove `import subprocess`, keep `import sys` (resolve_command at line 154)

---

### P2: Consolidate `_get_default_port()`

**Goal:** Three identical functions become one. The function reads config for a port, falling back to 8765.

**File to edit:** `nexus3/core/constants.py`

**What to add** (at the end of the file):

```python
def get_default_port() -> int:
    """Get default JSON-RPC server port from config, with fallback to 8765.

    Reads the server.port field from the merged NEXUS3 config (global + local).
    If config loading fails for any reason, returns 8765.
    """
    try:
        from nexus3.config.loader import load_config
        config = load_config()
        return config.server.port
    except Exception:
        return 8765
```

**Consumer updates:**

#### 1. `nexus3/client.py` (lines 18-25)

**Before:**
```python
def _get_default_port() -> int:
    """Get default port from config, with fallback."""
    try:
        from nexus3.config.loader import load_config
        config = load_config()
        return config.server.port
    except Exception:
        return 8765
```

**After:** Delete the function entirely. Add import:
```python
from nexus3.core.constants import get_default_port
```

Then find all call sites of `_get_default_port()` in this file and replace with `get_default_port()`.

#### 2. `nexus3/cli/client_commands.py` (lines 30-37)

Same pattern as above. Delete the local function, add import, replace calls.

#### 3. `nexus3/skill/base.py` (lines ~654-662)

This is a classmethod on `NexusSkill`:
```python
@classmethod
def _get_default_port(cls) -> int:
    if cls._default_port is None:
        cls._default_port = ...
    return cls._default_port
```

**After:**
```python
@classmethod
def _get_default_port(cls) -> int:
    if cls._default_port is None:
        cls._default_port = get_default_port()
    return cls._default_port
```

This one keeps the caching wrapper but delegates the actual logic.

**Import to add:** `from nexus3.core.constants import get_default_port`

---

### P3: Extract `_normalize_line()` in patch module

**Goal:** One shared function instead of two identical copies.

**File to edit:** `nexus3/patch/__init__.py`

**What to add:**
```python
def normalize_line(line: str) -> str:
    """Normalize a line for comparison (strip trailing whitespace)."""
    return line.rstrip()
```

Note: public name (no underscore prefix) since it's a module-level export.

**Consumer updates:**

#### 1. `nexus3/patch/applier.py` (line ~41-43)

Delete the local `_normalize_line` function. Add import:
```python
from nexus3.patch import normalize_line
```

Replace all calls from `_normalize_line(...)` to `normalize_line(...)` throughout the file (3 call sites: lines ~60, 60, 248).

#### 2. `nexus3/patch/validator.py` (line ~30-32)

Same: delete local function, add import, rename 4 call sites (lines ~104, 105, 153, 153).

---

### P4: Rename `ContextConfig` in context/manager.py

**Goal:** Resolve the name collision where two different classes are both called `ContextConfig`.

- `nexus3/config/schema.py:317` — `class ContextConfig(BaseModel)` — maps to `config.json` `"context"` key. **Do not rename.**
- `nexus3/context/manager.py:173` — `@dataclass class ContextConfig` — runtime context window sizing. **Rename to `ContextWindowConfig`.**

**Steps:**

1. In `nexus3/context/manager.py`: rename the class from `ContextConfig` to `ContextWindowConfig`. This is a dataclass with fields `max_tokens`, `reserve_tokens`, `truncation_strategy`. Also rename **3 internal references** within the same file:
   - Line 196: `config = ContextConfig(max_tokens=8000)` (in docstring example)
   - Line 208: `config: ContextConfig | None = None,` (in `ContextManager.__init__` parameter)
   - Line 225: `self.config = config or ContextConfig()` (in `ContextManager.__init__` body)

2. Update production imports:
   - `nexus3/context/__init__.py` (line 25): change import and `__all__` entry
   - `nexus3/rpc/pool.py` (line 46): update import and usages at lines 579 and 902

3. Update test imports (5 files):
   - `tests/integration/test_permission_enforcement.py` (line 24)
   - `tests/integration/test_chat.py` (line 12)
   - `tests/integration/test_skill_execution.py` (line 14)
   - `tests/unit/test_context_manager.py` (line 5)
   - `tests/unit/session/test_session_cancellation.py` (line 15)

4. Update `nexus3/context/README.md` — rename `ContextConfig` references to the **runtime** (context/manager) version. Lines to rename: 156, 173, 254, 257, 616, 753, 765. **WARNING: Line 651 references the `config/schema.py` `ContextConfig` (in a table row mentioning `config.schema`) — do NOT rename that one.**

5. `nexus3/session/session.py` does NOT import this — no change needed.

**Important:** Do NOT rename the `ContextConfig` in `config/schema.py`. That one maps to user-facing config.json and must stay as-is. Also do NOT touch `tests/unit/test_context_loader.py` or `tests/security/test_p2_18_readme_injection.py` — those import the config/schema.py version.

---

### P5: Delete PromptBuilder, Relocate inject_datetime Tests

**Goal:** Remove 238 lines of dead code (PromptBuilder, StructuredPrompt, PromptSection, EnvironmentBlock). Preserve the 11 tests for `inject_datetime_into_prompt()` which test a security fix.

#### Step 1: Create new test file

**Create:** `tests/unit/context/test_inject_datetime.py`

**Contents:** Copy lines 346-476 from `tests/unit/context/test_prompt_builder.py` (the entire `TestInjectDatetimeIntoPrompt` class), preceded by a module docstring and the single import it needs:

```python
"""Tests for inject_datetime_into_prompt() in context/manager.py.

This function finds the "# Environment" section header at a line boundary
and inserts the datetime string after it. It replaced a brittle str.replace()
approach that could match the marker anywhere in prompt content.

Tests cover:
- Injection at Environment header (standard case)
- Header at start of file
- No Environment section (fallback: append to end)
- Header at EOF with no trailing newline
- Ignoring inline "# Environment" mentions (security fix)
- Multiple Environment headers (uses first valid one)
- Content preservation after header
- Empty and whitespace-only prompts
- Rejecting "# Environment Variables" (partial match)
- Real system prompt format from loader
"""

from nexus3.context.manager import inject_datetime_into_prompt


class TestInjectDatetimeIntoPrompt:
    # ... (copy lines 346-476 from test_prompt_builder.py verbatim, starting from the class body)
```

#### Step 2: Delete files

- **Delete:** `nexus3/context/prompt_builder.py` (238 lines)
- **Delete:** `tests/unit/context/test_prompt_builder.py` (476 lines — all PromptBuilder tests; the inject_datetime tests now live in the new file)

#### Step 3: Edit `nexus3/context/__init__.py`

**Remove these lines (29-34):**
```python
from nexus3.context.prompt_builder import (
    EnvironmentBlock,
    PromptBuilder,
    PromptSection,
    StructuredPrompt,
)
```

**Remove from `__all__` (lines 67-71):**
```python
    # Prompt builder
    "EnvironmentBlock",
    "PromptBuilder",
    "PromptSection",
    "StructuredPrompt",
```

The file should go from 73 lines to ~63 lines.

#### Step 4: Edit `nexus3/context/README.md`

Remove these sections (use line numbers as guide, but match by content):
- **Line 25:** Remove `└── prompt_builder.py  # StructuredPrompt - typed prompt construction` from the file tree
- **Lines 515-585:** Remove the entire `### PromptBuilder` section (from `---` before it through the end of the code example)
- **Lines 620-626:** Remove the `# Prompt Builder` import example block:
  ```python
  # Prompt Builder
  from nexus3.context import (
      EnvironmentBlock,
      PromptBuilder,
      PromptSection,
      StructuredPrompt,
  )
  ```

#### Verification

After all edits, run:
```bash
.venv/bin/pytest tests/unit/context/test_inject_datetime.py -v  # New test file passes
.venv/bin/ruff check nexus3/context/  # No import errors
.venv/bin/python -c "from nexus3.context import ContextManager, inject_datetime_into_prompt"  # Imports work
```

---

### P6: Replace `assert` in rpc/http.py

**Goal:** Replace an `assert` statement (which is stripped by `python -O`) with proper error handling.

**File:** `nexus3/rpc/http.py` around line 554

**Before:**
```python
# Safety check: dispatcher must be set by now
assert dispatcher is not None, "dispatcher should be set after routing/restore"
```

**After:**
```python
# Safety check: dispatcher must be set by now
if dispatcher is None:
    error_response = make_error_response(
        None, INTERNAL_ERROR, "Internal routing error"
    )
    await send_http_response(writer, 500, serialize_response(error_response))
    return
```

**Context:** The `make_error_response`, `INTERNAL_ERROR`, and `serialize_response` are already imported at the top of this file. The `send_http_response` function is defined in the same file. This pattern is used 8 other times in the same function (5 complete, 3 with pre-created errors) — match their style exactly.

---

### P7: Inherit `GitLabAPIError` from `NexusError`

**Goal:** Bring GitLab errors into the error hierarchy so `except NexusError` catches them.

**File:** `nexus3/skill/vcs/gitlab/client.py`

**Before (lines 16-23):**
```python
class GitLabAPIError(Exception):
    """GitLab API error with status code and message."""

    def __init__(self, status_code: int, message: str, response_body: Any = None):
        self.status_code = status_code
        self.message = message
        self.response_body = response_body
        super().__init__(f"GitLab API error {status_code}: {message}")
```

**After:**
```python
from nexus3.core.errors import NexusError

class GitLabAPIError(NexusError):
    """GitLab API error with status code and message."""

    def __init__(self, status_code: int, message: str, response_body: Any = None):
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(f"GitLab API error {status_code}: {message}")
        self.message = message  # Override NexusError's formatted message — repl_commands.py reads this
```

**Key change details:**
1. Add `from nexus3.core.errors import NexusError` to imports
2. Change `class GitLabAPIError(Exception)` to `class GitLabAPIError(NexusError)`
3. **Keep `self.message = message`** but move it AFTER `super().__init__()`. `NexusError.__init__` sets `self.message` to the formatted string, but `cli/repl_commands.py:2343` reads `e.message` expecting the raw message (e.g., `"Unauthorized"` not `"GitLab API error 401: Unauthorized"`). Setting it after `super()` overrides NexusError's value.

**Catch sites** (3 total, not just 1):
- `nexus3/skill/vcs/gitlab/base.py:186` — `except GitLabAPIError as e: return self._format_error(e)` — uses `e.status_code` and `str(e)`
- `nexus3/skill/vcs/gitlab/artifact.py:298` — `except GitLabAPIError as e: if e.status_code == 404:` — uses `e.status_code`
- `nexus3/cli/repl_commands.py:2343` — uses `e.message` directly (this is why we keep `self.message = message`)

---

### P8: Clean up `ToolPermission` noqa import

**Goal:** Remove unused import that's suppressing a linter warning.

**File:** `nexus3/session/enforcer.py` line 16

**Before:**
```python
from nexus3.core.presets import ToolPermission  # noqa: F401 - needed for P2
```

**After:** Delete this line entirely.

**Verification:** `ToolPermission` is never referenced in `enforcer.py` beyond this import line. The comment says "needed for P2" — that phase is complete and the import is no longer needed.

---

### P9: Remove unused `StreamingDisplay` export

**Goal:** Remove dead export from `display/__init__.py`. `StreamingDisplay` is already marked deprecated and has zero external imports.

**File:** `nexus3/display/__init__.py`

**Before (line 16):**
```python
from nexus3.display.streaming import StreamingDisplay
```

**After:** Delete this import line.

**Before (`__all__`, lines 30-31):**
```python
    # Streaming (deprecated - use Spinner instead)
    "StreamingDisplay",
```

**After:** Delete both lines.

**Verification:** Run `grep -rn "StreamingDisplay" nexus3/ tests/` to confirm nothing imports it from the package. The class itself in `display/streaming.py` is unchanged — it's still importable directly if anyone ever needs it.

---

### P10: GitLab sync subprocess -> async

**Goal:** Replace blocking `subprocess.run()` calls with async subprocess, and consolidate two identical `git remote get-url origin` calls into one method.

**Depends on:** P1 (for `create_subprocess_exec` in `core/process.py`). Must be implemented after Phase 1.

**File:** `nexus3/skill/vcs/gitlab/base.py`

#### Step 1: Add shared async method

Add this method to the `GitLabSkill` class (after `_extract_host`, before `_get_client`):

```python
async def _get_remote_url(self, cwd: str | Path | None = None) -> str | None:
    """Get git remote origin URL, or None if not in a git repo.

    Args:
        cwd: Working directory to run git in. Defaults to services cwd.

    Returns:
        Remote URL string, or None if unavailable.
    """
    try:
        work_dir = str(Path(cwd)) if cwd else str(self._services.get_cwd())
        proc = await create_subprocess_exec(
            "git", "remote", "get-url", "origin",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode != 0:
            return None
        return stdout.decode().strip()
    except Exception:
        return None
```

**Imports to add at top of file:**
```python
import asyncio
from nexus3.core.process import create_subprocess_exec
```

**Imports to keep:** `from pathlib import Path` — already exists at line 6, used by the new `_get_remote_url()` method.

**Imports to remove:**
```python
import subprocess  # No longer needed (only used for the two subprocess.run calls being replaced)
```

#### Step 2: Update `_detect_instance_from_remote()` (lines 66-94)

**Before:** synchronous method calling `subprocess.run()` directly.

**After:** Make async, use `_get_remote_url()`:

```python
async def _detect_instance_from_remote(self) -> GitLabInstance | None:
    """Detect GitLab instance from current git remote."""
    remote_url = await self._get_remote_url()
    if not remote_url:
        return None

    remote_host = self._extract_host(remote_url)
    for instance in self._config.instances.values():
        if instance.host == remote_host:
            return instance

    return None
```

#### Step 3: Update `_resolve_project()` (lines 111-141)

**Before:** synchronous method calling `subprocess.run()` directly.

**After:** Make async, use `_get_remote_url()`:

```python
async def _resolve_project(
    self,
    project: str | None,
    cwd: str | None = None,
) -> str:
    """Resolve project path.

    Priority:
    1. Explicit project parameter
    2. Detect from git remote
    """
    if project:
        return project

    remote_url = await self._get_remote_url(cwd=cwd)
    if remote_url:
        return self._extract_project_path(remote_url)

    raise ValueError("No project specified and could not detect from git remote")
```

#### Step 4: Update `_resolve_instance()` (line 56)

This calls `_detect_instance_from_remote()` which is now async:

**Before:**
```python
detected = self._detect_instance_from_remote()
```

**After:**
```python
detected = await self._detect_instance_from_remote()
```

#### Step 5: Update `execute()` method (line 180)

`_resolve_instance()` now awaits `_detect_instance_from_remote()`, but `execute()` already calls `self._resolve_instance()` without await (it was sync). Since `_resolve_instance` now calls an async method, it must become async too.

Check: `_resolve_instance` is called in `execute()` at line 180:
```python
instance = self._resolve_instance(kwargs.get("instance"))
```

**After:**
```python
instance = await self._resolve_instance(kwargs.get("instance"))
```

And mark `_resolve_instance` as `async def`:
```python
async def _resolve_instance(self, instance_name: str | None = None) -> GitLabInstance:
```

#### Step 6: Update callers of `_resolve_project()`

There are **33 call sites across 19 files** in `nexus3/skill/vcs/gitlab/` (excluding base.py definition).

**IMPORTANT:** Not all call sites are directly in `async def` methods. **8 of 33 call sites are in sync helper methods** that must ALSO become `async def`, which then cascades to their callers.

##### 6a: Direct calls in `async def _execute_impl()` methods (25 calls)

These are simple — just add `await`:

```python
# Before:
project_path = self._resolve_project(kwargs.get("project"))

# After:
project_path = await self._resolve_project(kwargs.get("project"))
```

Files with direct async calls:
- `repo.py` (2 calls)
- `issue.py`, `mr.py`, `label.py`, `branch.py`, `tag.py`, `pipeline.py`, `job.py`, `artifact.py`, `feature_flag.py` (1 call each)
- `approval.py` (6 calls)
- `discussion.py` (2 calls — lines 326, 341; the 3rd call is in a sync helper)
- `deploy_key.py` (6 calls — lines 143, 178, 216, 240, 267, 280; the 7th call is in a sync helper)

##### 6b: Calls in sync helper methods that must become async (8 calls + 41 cascade callers)

These 8 sync methods call `_resolve_project()` and must become `async def`. Then every caller of those methods must add `await`.

| File | Sync Method | Line | Method Must Become |
|------|------------|------|--------------------|
| `deploy_key.py` | `_get_base_path(self, client, project)` | 66 | `async def _get_base_path(...)` |
| `board.py` | `_get_base_path(self, client, project, group)` | 111 | `async def _get_base_path(...)` |
| `variable.py` | `_get_base_path(self, client, project, group)` | 92 | `async def _get_base_path(...)` |
| `deploy_token.py` | `_get_base_path(self, client, project, group)` | 93 | `async def _get_base_path(...)` |
| `milestone.py` | `_get_base_path(self, client, project, group)` | 100 | `async def _get_base_path(...)` |
| `draft_note.py` | `_get_mr_path(self, client, project)` | 78 | `async def _get_mr_path(...)` |
| `time_tracking.py` | `_get_target_path(self, client, project, iid, target_type)` | 76 | `async def _get_target_path(...)` |
| `discussion.py` | `_get_target_path(self, client, project, iid, target_type)` | 81 | `async def _get_target_path(...)` |

**Cascade:** Each of these helper methods is called from `async def` methods, so their callers just need `await` added:

| File | Helper Method | Callers That Need `await` |
|------|--------------|---------------------------|
| `deploy_key.py` | `_get_base_path` | 6 callers (lines 144, 179, 217, 241, 268, 281) |
| `board.py` | `_get_base_path` | 9 callers (lines 200, 224, 290, 311, 334, 345, 371, 407, 431) |
| `variable.py` | `_get_base_path` | 5 callers (lines 148, 187, 225, 262, 290) |
| `deploy_token.py` | `_get_base_path` | 4 callers (lines 150, 188, 225, 267) |
| `milestone.py` | `_get_base_path` | 7 callers (lines 166, 210, 245, 271, 297, 308, 331) |
| `draft_note.py` | `_get_mr_path` | 5 callers (lines 132, 171, 221, 232, 242) |
| `time_tracking.py` | `_get_target_path` | 1 caller (line 105) |
| `discussion.py` | `_get_target_path` | 4 callers (lines 179, 225, 270, 312) |

**Implementation approach for each file with a sync helper:**
1. Add `async` to the helper method signature: `def _get_base_path(` → `async def _get_base_path(`
2. Add `await` to the `self._resolve_project(` call inside it
3. Add `await` to every call site of the helper method (e.g., `self._get_base_path(` → `await self._get_base_path(`)

No callers pass `cwd` to `_resolve_project()` in production code — they all use `kwargs.get("project")` or `project` parameter.

#### Step 7: Update tests

**File:** `tests/unit/skill/vcs/test_gitlab_skills.py`

##### 7a: Tests that directly call `_resolve_project()` (class `TestGitLabSkillProjectResolution`, lines 668-725)

4 sync tests must become async:
- `test_resolve_project_explicit` (line 678): add `async def`, add `await`
- `test_resolve_project_from_https_remote` (line 683): add `async def`, add `await`, change mock target from `subprocess.run` to the new async subprocess
- `test_resolve_project_from_ssh_remote` (line 697): same
- `test_resolve_project_no_remote_raises` (line 711): same

##### 7b: Tests that directly call `_resolve_instance()` (class `TestGitLabSkillInstanceResolution`, lines 727-766)

3 sync tests must become async:
- `test_resolve_instance_explicit` (line 749): add `async def`, add `await`
- `test_resolve_instance_default` (line 754): add `async def`, add `await`, mock `_detect_instance_from_remote` must return a coroutine
- `test_resolve_instance_nonexistent_raises` (line 760): add `async def`, add `await`

##### 7c: Tests that mock `_resolve_instance` via `patch.object` (lines 598-665)

5 async tests that use `patch.object(skill, "_resolve_instance", side_effect=...)`. Since `_resolve_instance` becomes async, verify `unittest.mock.patch.object` auto-detects async and uses `AsyncMock`. If tests fail, add `new_callable=AsyncMock`.

##### 7d: Tests that mock `_resolve_project` via `patch.object` (29 instances, lines 83-578)

These use `patch.object(skill, "_resolve_project", return_value="group/project")`. Should auto-work with Python 3.8+ async detection in `unittest.mock`, but verify after implementation.

---

## Testing Strategy

### Automated Tests
- Run full test suite after each phase: `.venv/bin/pytest tests/ -v`
- Run ruff after each phase: `.venv/bin/ruff check nexus3/`
- Run mypy for type checking: `.venv/bin/mypy nexus3/`

### Live Testing
Per CLAUDE.md SOP, after P1 (subprocess helper) and P10 (GitLab async):
1. Start server: `NEXUS_DEV=1 .venv/bin/python -m nexus3 --serve 9000 &`
2. Create test agent: `.venv/bin/python -m nexus3 rpc create test-agent --preset trusted --port 9000`
3. Test file operations: `.venv/bin/python -m nexus3 rpc send test-agent "list the files in the current directory" --port 9000`
4. Test git operations: `.venv/bin/python -m nexus3 rpc send test-agent "run git status" --port 9000`
5. Cleanup: `.venv/bin/python -m nexus3 rpc destroy test-agent --port 9000`

---

## Implementation Checklist

### Phase 1: Foundation (P1-P3)
- [ ] **P1.1** Add `create_subprocess_exec()` and `create_subprocess_shell()` to `core/process.py`
- [ ] **P1.2** Update `skill/builtin/bash.py` — both BashSafe and ShellUnsafe `_create_process()` methods
- [ ] **P1.3** Update `skill/builtin/run_python.py` — `_create_process()` method
- [ ] **P1.4** Update `skill/builtin/git.py` — subprocess call in `execute()`
- [ ] **P1.5** Update `skill/builtin/grep.py` — subprocess call
- [ ] **P1.6** Update `skill/builtin/concat_files.py` — 3 pairs of calls (6 → 3)
- [ ] **P1.7** Update `mcp/transport.py` — MCP server launch
- [ ] **P1.8** Clean up imports per file (see "Cleanup after all consumer updates" in P1 details for exact list)
- [ ] **P1.9** Run `ruff check` and `pytest` — verify no regressions
- [ ] **P2.1** Add `get_default_port()` to `core/constants.py`
- [ ] **P2.2** Update `client.py` — delete local function, import from constants
- [ ] **P2.3** Update `cli/client_commands.py` — delete local function, import from constants
- [ ] **P2.4** Update `skill/base.py` — delegate to `get_default_port()` from constants
- [ ] **P3.1** Add `normalize_line()` to `patch/__init__.py`
- [ ] **P3.2** Update `patch/applier.py` — delete local, import from package, rename calls
- [ ] **P3.3** Update `patch/validator.py` — delete local, import from package, rename calls
- [ ] **P3.4** Run tests for phase 1

### Phase 2: Naming & Dead Code (P4-P5)

**Same-file conflicts:** P4.3 and P5.5 both edit `context/__init__.py`. P4.4 and P5.6 both edit `context/README.md`. Run P4 items before P5 items, or do P4+P5 edits to each file together.

- [ ] **P4.1** Rename `ContextConfig` to `ContextWindowConfig` in `context/manager.py` (class def + 3 internal refs at lines 196, 208, 225)
- [ ] **P4.2** Update imports in `rpc/pool.py` and 5 test files (see P4 details for complete file list)
- [ ] **P4.3** Update `context/__init__.py` re-export (same file as P5.5 — coordinate)
- [ ] **P4.4** Update `context/README.md` (rename lines 156, 173, 254, 257, 616, 753, 765 — but NOT line 651 which is config/schema version) (same file as P5.6 — coordinate)
- [ ] **P5.1** Create `tests/unit/context/test_inject_datetime.py` with the 11 tests from `TestInjectDatetimeIntoPrompt`
- [ ] **P5.2** Verify new test file passes: `.venv/bin/pytest tests/unit/context/test_inject_datetime.py -v`
- [ ] **P5.3** Delete `nexus3/context/prompt_builder.py`
- [ ] **P5.4** Delete `tests/unit/context/test_prompt_builder.py`
- [ ] **P5.5** Remove PromptBuilder imports and `__all__` entries from `context/__init__.py` (same file as P4.3)
- [ ] **P5.6** Remove PromptBuilder sections from `context/README.md` (same file as P4.4)
- [ ] **P5.7** Run tests for phase 2

### Phase 3: Correctness & Consistency (P6-P10)
- [ ] **P6.1** Replace `assert` with proper error handling in `rpc/http.py`
- [ ] **P7.1** Change `GitLabAPIError` to inherit from `NexusError`, keep `self.message = message` but move after `super().__init__()`
- [ ] **P8.1** Remove unused `ToolPermission` import from `session/enforcer.py`
- [ ] **P9.1** Remove `StreamingDisplay` import and `__all__` entry from `display/__init__.py`
- [ ] **P10.1** Add async `_get_remote_url()` method to `GitLabSkill` in `gitlab/base.py`
- [ ] **P10.2** Make `_detect_instance_from_remote()` async, use `_get_remote_url()`
- [ ] **P10.3** Make `_resolve_instance()` async, add `await` to detection call
- [ ] **P10.4** Make `_resolve_project()` async, use `_get_remote_url()`
- [ ] **P10.5** Update `execute()` to `await self._resolve_instance()`
- [ ] **P10.6** Add `import asyncio` and `from nexus3.core.process import create_subprocess_exec` to base.py, remove `import subprocess` (requires P1 complete)
- [ ] **P10.7** Add `await` to 25 direct `_resolve_project()` calls in async methods across 13 files
- [ ] **P10.8** Convert 8 sync helper methods to async (`_get_base_path`, `_get_mr_path`, `_get_target_path`) — see Step 6b table
- [ ] **P10.9** Add `await` to 41 callers of the newly-async helper methods — see Step 6b cascade table
- [ ] **P10.10** Update `tests/unit/skill/vcs/test_gitlab_skills.py` — make 7 sync tests async, update mocks (see Step 7)
- [ ] **P10.11** Run full test suite
- [ ] **P10.12** Live test with server

### Phase 4: Documentation
- [ ] **D1** Update `CLAUDE.md` "Deferred Work > DRY Cleanups" to mark completed items
- [ ] **D2** Update `core/README.md` to document `create_subprocess_exec()`, `create_subprocess_shell()`, and `get_default_port()`
- [ ] **D3** Update `patch/README.md` if it references `_normalize_line()`
- [ ] **D4** Update `MEMORY.md` to reflect changes

---

## Quick Reference

| Item | Current Location | Target Location |
|------|-----------------|-----------------|
| Platform subprocess branching | 7 files, ~15 call sites | `core/process.py` → `create_subprocess_exec()`, `create_subprocess_shell()` |
| `_get_default_port()` | client.py, client_commands.py, base.py | `core/constants.py` → `get_default_port()` |
| `_normalize_line()` | patch/applier.py, patch/validator.py | `patch/__init__.py` → `normalize_line()` |
| `ContextConfig` (runtime) | context/manager.py | context/manager.py → `ContextWindowConfig` |
| `PromptBuilder` + friends | context/prompt_builder.py (238 lines) | **DELETED** |
| inject_datetime tests | test_prompt_builder.py (lines 346-475) | `test_inject_datetime.py` (new file) |
| `assert` in http.py | rpc/http.py:554 | proper error response |
| `GitLabAPIError` | extends `Exception` | extends `NexusError` (keep `self.message = message`) |
| `ToolPermission` import | session/enforcer.py:16 | **DELETED** |
| `StreamingDisplay` export | display/__init__.py | **DELETED** |
| GitLab subprocess.run | gitlab/base.py (2 calls) + 33 callers + 41 cascade | async `_get_remote_url()`, async helpers |
