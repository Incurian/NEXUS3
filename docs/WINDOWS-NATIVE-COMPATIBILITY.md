# Plan: Windows Native Compatibility

## Overview

**Current State:** NEXUS3 has partial Windows support from the MCP improvements (P2.0.1-P2.0.7) including process groups, environment variables, command resolution, and CRLF handling. However, significant gaps remain in keyboard input, environment handling consistency, process termination robustness, and testing.

**Goal:** Achieve full Windows-native compatibility with proper testing and documentation.

**Branch:** `feature/windows-native-compat` (create from `feature/mcp-improvements`)

---

## Scope

### Included in v1

| Category | Items |
|----------|-------|
| **Critical** | ESC key detection using `msvcrt` |
| **Critical** | Replace hardcoded ANSI escape sequences with Rich methods |
| **High** | Unified environment variable handling (env.py + transport.py) |
| **High** | Robust process tree termination with `taskkill` fallback |
| **High** | Error path sanitization for Windows paths (C:\Users\...) |
| **Medium** | Windows file attributes in `file_info` (instead of Unix rwx) |
| **Medium** | Line ending preservation in `edit_file` |
| **Medium** | Git skill process group handling |
| **Medium** | Rich Console Windows configuration (encoding, legacy_windows) |
| **Medium** | CREATE_NO_WINDOW subprocess flag on Windows |
| **Low** | Pytest markers for Windows tests |
| **Low** | Windows troubleshooting documentation |
| **Low** | BOM handling in config file loading |

### Deferred

- GitHub Actions CI for Windows (need any CI first)
- Real Windows integration tests (require Windows environment)
- PowerShell-specific features
- UNC path validation (works but untested)
- HTTP proxy support (requires config schema changes)
- SSL/TLS custom certificates in NexusClient (providers already support)
- Windows certificate store integration
- Windows ACL-based file permissions (os.chmod insufficient)

### Explicitly Excluded

- WSL testing (not Windows proper)
- Wine testing (unreliable)
- Windows 7/8 support (require Windows 10+)

---

## Design Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| ESC key detection on Windows | Use `msvcrt.kbhit()` + `msvcrt.getwch()` | Standard library, no dependencies, async-compatible |
| Environment variable source of truth | Unify in `env.py`, import in `transport.py` | DRY principle; currently duplicated |
| Windows process termination | CTRL_BREAK_EVENT -> taskkill /T /F -> kill() | Graceful first, then reliable tree kill |
| File permissions on Windows | Show RHSA attributes (Readonly/Hidden/System/Archive) | More meaningful than fake rwx bits |
| Line ending preservation | Detect from file, normalize new content to match | Preserves user intent |
| Test organization | Inline with markers (`@pytest.mark.windows`) | Consistent with existing patterns |
| CI strategy | Deferred - mock tests for now | No existing CI; cost/benefit doesn't justify |
| ANSI escape sequences | Replace with Rich cursor control methods | Rich handles Windows Terminal properly |
| force_terminal override | Keep but add legacy_windows=False | Require modern Windows Terminal (10+) |
| Subprocess window flashing | Add CREATE_NO_WINDOW flag | Prevents cmd.exe window appearing |
| Error path sanitization | Add Windows path patterns to errors.py | Prevents username leakage in errors |
| Windows file permissions | Document limitation, defer ACL support | os.chmod insufficient; ACL is complex |
| HTTP proxy support | Defer to future plan | Requires config schema changes |
| Event loop policy | Defer investigation | asyncio.run() works in most cases |

---

## Security Considerations

1. **No new attack surface** - ESC detection only reads keyboard input
2. **Process termination** - `taskkill` is a standard Windows utility, not elevated
3. **Environment variables** - Only adding non-secret system variables
4. **File attributes** - Read-only via `ctypes.windll.kernel32.GetFileAttributesW()`
5. **Error path sanitization** - Prevents username leakage in error messages

### Known Windows Security Limitations (Documented, Not Fixed)

These issues require significant architectural changes and are documented rather than fixed:

1. **File permissions (os.chmod)** - `os.chmod(path, 0o600)` does NOT provide Unix-like "owner-only" protection on Windows. Session files, SQLite databases, and RPC tokens may be readable by other users. **Mitigation:** Users should restrict access to their home directory.

2. **Symlink/junction detection** - `path.is_symlink()` doesn't detect Windows junction points and reparse points. Security assumptions about symlink attacks may be weaker on Windows.

3. **Permission validation** - Code checking `S_IRWXG | S_IRWXO` (group/other permissions) gives false negatives on Windows because these bits don't map to Windows ACLs.

4. **RPC token security** - Token file at `~/.nexus3/rpc.token` relies on Unix permissions which don't work on Windows. On multi-user Windows systems, other users may be able to read the token.

---

## Architecture

### New Module: `nexus3/core/process.py`

Centralized cross-platform process termination:

```
terminate_process_tree()
├── Unix: _terminate_unix()
│   └── SIGTERM → wait → SIGKILL to process group
└── Windows: _terminate_windows()
    └── CTRL_BREAK_EVENT → wait → taskkill /T /F → TerminateProcess
```

### Modified Files

```
nexus3/
├── core/
│   └── process.py          # NEW: Process termination utility
├── cli/
│   └── keys.py             # Windows ESC key detection
├── skill/builtin/
│   ├── env.py              # Add Windows env vars, platform-aware DEFAULT_PATH
│   ├── file_info.py        # Windows file attributes
│   ├── edit_file.py        # Line ending preservation
│   └── git.py              # Process group handling
├── mcp/
│   └── transport.py        # Import from env.py, use process utility
└── skill/
    └── base.py             # Use process termination utility
```

---

## Implementation Details

### Phase 1: Process Termination Utility (Foundation)

**File: `nexus3/core/process.py`** (NEW)

```python
"""Cross-platform process termination utilities.

Provides robust process tree termination:
- Unix: SIGTERM -> wait -> SIGKILL to process group
- Windows: CTRL_BREAK_EVENT -> wait -> taskkill /T /F -> TerminateProcess
"""

import asyncio
import logging
import os
import signal
import sys
from asyncio.subprocess import Process

logger = logging.getLogger(__name__)

GRACEFUL_TIMEOUT = 2.0


async def terminate_process_tree(
    process: Process,
    graceful_timeout: float = GRACEFUL_TIMEOUT,
) -> None:
    """Terminate a process and all its children."""
    if process.returncode is not None:
        return

    pid = process.pid

    if sys.platform == "win32":
        await _terminate_windows(process, pid, graceful_timeout)
    else:
        await _terminate_unix(process, pid, graceful_timeout)


async def _terminate_unix(process: Process, pid: int, graceful_timeout: float) -> None:
    """Unix: SIGTERM -> wait -> SIGKILL to process group."""
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)
        logger.debug("Sent SIGTERM to process group %d", pgid)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.terminate()
        except ProcessLookupError:
            return

    try:
        await asyncio.wait_for(process.wait(), timeout=graceful_timeout)
        return
    except TimeoutError:
        pass

    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGKILL)
        logger.debug("Sent SIGKILL to process group %d", pgid)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except ProcessLookupError:
            pass

    await process.wait()


async def _terminate_windows(process: Process, pid: int, graceful_timeout: float) -> None:
    """Windows: CTRL_BREAK -> wait -> taskkill /T /F -> kill."""
    # Step 1: Graceful CTRL_BREAK_EVENT
    try:
        os.kill(pid, signal.CTRL_BREAK_EVENT)
        logger.debug("Sent CTRL_BREAK_EVENT to process %d", pid)
    except (ProcessLookupError, OSError, AttributeError):
        pass

    try:
        await asyncio.wait_for(process.wait(), timeout=graceful_timeout)
        return
    except TimeoutError:
        pass

    # Step 2: taskkill for process tree
    try:
        taskkill = await asyncio.create_subprocess_exec(
            "taskkill", "/T", "/F", "/PID", str(pid),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(taskkill.wait(), timeout=graceful_timeout)
        logger.debug("taskkill /T /F completed for PID %d", pid)
    except (FileNotFoundError, TimeoutError, OSError) as e:
        logger.debug("taskkill failed: %s", e)

    try:
        await asyncio.wait_for(process.wait(), timeout=0.5)
        return
    except TimeoutError:
        pass

    # Step 3: Final fallback
    try:
        process.kill()
    except ProcessLookupError:
        pass

    await process.wait()
```

### Phase 2: ESC Key Detection

**File: `nexus3/cli/keys.py`** - Replace lines 79-90

```python
    except (ImportError, OSError, AttributeError):
        # Fallback for Windows or when terminal isn't available
        if sys.platform == "win32":
            try:
                import msvcrt

                while True:
                    if not pause_event.is_set():
                        pause_ack_event.set()
                        await pause_event.wait()
                        pause_ack_event.clear()
                        continue

                    if msvcrt.kbhit():
                        char = msvcrt.getwch()
                        if char == ESC:
                            on_escape()

                    await asyncio.sleep(check_interval)

            except (ImportError, OSError, AttributeError):
                pass  # Fall through to sleep-only
            else:
                return

        # Final fallback: No keyboard input available
        while True:
            if not pause_event.is_set():
                pause_ack_event.set()
                await pause_event.wait()
                pause_ack_event.clear()
                continue
            await asyncio.sleep(check_interval)
```

### Phase 3: Unified Environment Variables

**File: `nexus3/skill/builtin/env.py`** - Update SAFE_ENV_VARS and DEFAULT_PATH

```python
import sys

SAFE_ENV_VARS: frozenset[str] = frozenset({
    # Path and execution
    "PATH", "HOME", "USER", "SHELL", "PWD", "LOGNAME",
    # Locale
    "LANG", "LC_ALL", "LC_CTYPE", "LC_COLLATE", "LC_MESSAGES", "TZ",
    # Terminal
    "TERM", "COLORTERM", "COLUMNS", "LINES",
    # Temp directories
    "TMPDIR", "TMP", "TEMP",
    # Windows-specific
    "USERPROFILE", "APPDATA", "LOCALAPPDATA",
    "PATHEXT", "SYSTEMROOT", "COMSPEC",
})

if sys.platform == "win32":
    DEFAULT_PATH = r"C:\Windows\System32;C:\Windows;C:\Windows\System32\Wbem"
else:
    DEFAULT_PATH = "/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin"
```

**File: `nexus3/mcp/transport.py`** - Replace SAFE_ENV_KEYS definition (lines 67-88)

```python
from nexus3.skill.builtin.env import SAFE_ENV_VARS

# Alias for backward compatibility
SAFE_ENV_KEYS = SAFE_ENV_VARS
```

### Phase 4: Windows File Attributes

**File: `nexus3/skill/builtin/file_info.py`** - Replace `_format_permissions`

```python
import sys

def _format_permissions(mode: int, path: Path | None = None) -> str:
    """Format file permissions/attributes in a platform-appropriate way."""
    if sys.platform == "win32" and path is not None:
        return _format_windows_attributes(path)
    return _format_unix_permissions(mode)


def _format_unix_permissions(mode: int) -> str:
    """Format Unix file mode as rwxrwxrwx string."""
    perms = []
    for who in ("USR", "GRP", "OTH"):
        for perm in ("R", "W", "X"):
            flag = getattr(stat, f"S_I{perm}{who}")
            perms.append(perm.lower() if mode & flag else "-")
    return "".join(perms)


def _format_windows_attributes(path: Path) -> str:
    """Format Windows file attributes as RHSA string."""
    import ctypes

    try:
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs == -1:
            return "????"

        FILE_ATTRIBUTE_READONLY = 0x1
        FILE_ATTRIBUTE_HIDDEN = 0x2
        FILE_ATTRIBUTE_SYSTEM = 0x4
        FILE_ATTRIBUTE_ARCHIVE = 0x20

        result = []
        result.append("R" if attrs & FILE_ATTRIBUTE_READONLY else "-")
        result.append("H" if attrs & FILE_ATTRIBUTE_HIDDEN else "-")
        result.append("S" if attrs & FILE_ATTRIBUTE_SYSTEM else "-")
        result.append("A" if attrs & FILE_ATTRIBUTE_ARCHIVE else "-")

        return "".join(result)
    except Exception:
        return "----"
```

Update execute method to pass path:
```python
"permissions": _format_permissions(st.st_mode, p),
```

### Phase 5: Line Ending Preservation

**CRITICAL NOTE**: Python's `read_text()` automatically converts CRLF to LF on Windows before the code sees it. To properly preserve line endings, files must be read in binary mode and decoded manually.

**Files affected**: `edit_file.py`, `append_file.py`, `regex_replace.py`

**File: `nexus3/skill/builtin/edit_file.py`** - Binary read + detection + preservation

```python
def _detect_line_ending(content: str) -> str:
    """Detect the predominant line ending style in content."""
    crlf_count = content.count("\r\n")
    lf_count = content.count("\n") - crlf_count
    cr_count = content.count("\r") - crlf_count

    if crlf_count > lf_count and crlf_count > cr_count:
        return "\r\n"
    elif cr_count > lf_count:
        return "\r"
    else:
        return "\n"
```

Change file reading from `read_text()` to binary read + decode (line 118):
```python
# Before:
content = await asyncio.to_thread(p.read_text, encoding="utf-8")

# After (preserves line endings):
content_bytes = await asyncio.to_thread(p.read_bytes)
content = content_bytes.decode("utf-8", errors="replace")
```

Update `_line_replace()` to use detected line ending when adding newlines.

**File: `nexus3/skill/builtin/append_file.py`** - Fix hardcoded LF in `do_append()` (line 117)

The actual hardcoded `"\n"` is in the `do_append()` function, not `_needs_newline_prefix()`:
```python
# Current (line 116-117):
if newline and p.exists() and _needs_newline_prefix(p):
    to_write = "\n" + content  # ← Hardcoded LF here

# After:
if newline and p.exists() and _needs_newline_prefix(p):
    # Read file to detect line ending
    try:
        existing = p.read_bytes().decode("utf-8", errors="replace")
        line_ending = _detect_line_ending(existing) if existing else "\n"
    except Exception:
        line_ending = "\n"
    to_write = line_ending + content
```

Note: `_needs_newline_prefix()` (line 35) already does binary reading and is fine as-is.

**File: `nexus3/skill/builtin/regex_replace.py`** - Binary read (line 133)

Same pattern as edit_file: change to binary read + decode to preserve line endings.

### Phase 6: Update Consumers

**File: `nexus3/skill/base.py`** - Replace timeout handling (lines ~1016-1032)

```python
except TimeoutError:
    from nexus3.core.process import terminate_process_tree
    await terminate_process_tree(process)
    return ToolResult(error=timeout_message.format(timeout=timeout))
```

**File: `nexus3/mcp/transport.py`** - Replace StdioTransport.close() termination

```python
except TimeoutError:
    from nexus3.core.process import terminate_process_tree
    await terminate_process_tree(self._process)
```

**File: `nexus3/skill/builtin/git.py`** - Convert to asyncio with process groups

Convert `subprocess.run()` to `asyncio.create_subprocess_exec()` with `CREATE_NEW_PROCESS_GROUP` on Windows and `start_new_session=True` on Unix.

### Phase 7: ANSI Escape Sequence Fixes

**IMPORTANT**: Rich's `Control` class does NOT have `move_up()`, `erase_line()`, or `erase_end()` methods. The available methods are: `move_to(x, y)`, `move_to_column(x)`, `move(x, y)`, `clear()`, `home()`, `bell()`, `show_cursor()`, `alt_screen()`.

**Revised approach**: Use `console.file.write()` with ANSI sequences through Rich's Console, which handles Windows Terminal properly when `legacy_windows=False` is set.

**File: `nexus3/display/console.py`** - Update Console initialization FIRST

```python
_console = Console(
    highlight=False,
    markup=True,
    force_terminal=True,
    legacy_windows=False,  # Require Windows 10+ Terminal - enables VT100 sequences
)
```

With `legacy_windows=False`, Rich enables Windows VT100 mode, allowing ANSI sequences to work properly on Windows 10+.

**File: `nexus3/cli/repl.py`** - Line 907 can remain as-is OR use console.file

```python
# Option A: Keep raw ANSI (works with legacy_windows=False)
sys.stdout.write("\033[1A\r\033[2K")
sys.stdout.flush()

# Option B: Use Rich's console.file for consistency
console.file.write("\033[1A\r\033[2K")
console.file.flush()
```

**File: `nexus3/cli/confirmation_ui.py`** - Lines 226-227 same approach

```python
# Option A: Keep raw ANSI (works with legacy_windows=False)
sys.stdout.write(f"\033[{lines_printed}F")
sys.stdout.write("\033[J")
sys.stdout.flush()

# Option B: Use Rich's console.file for consistency
console.file.write(f"\033[{lines_printed}F")
console.file.write("\033[J")
console.file.flush()
```

**Key insight**: The fix is `legacy_windows=False` in console.py, which enables VT100 mode. The ANSI sequences themselves can remain unchanged.

### Phase 8: Error Path Sanitization

**File: `nexus3/core/errors.py`** - Add Windows path patterns

```python
# Existing Unix pattern:
_HOME_PATTERN = re.compile(r'/home/[^/\s]+')

# Add Windows patterns (order matters - most specific first):
# UNC paths: \\server\share
_UNC_PATTERN = re.compile(r'\\\\[^\\]+\\[^\\]+')
# AppData paths (handles usernames with spaces via [^\\]+ which stops at backslash)
_APPDATA_PATTERN = re.compile(r'[A-Za-z]:\\Users\\[^\\]+\\AppData\\[^\\]+', re.IGNORECASE)
# General Windows user paths
_WINDOWS_USER_PATTERN = re.compile(r'[A-Za-z]:\\Users\\[^\\]+', re.IGNORECASE)

def sanitize_error(msg: str) -> str:
    """Remove sensitive paths from error messages."""
    result = msg
    # Unix
    result = _HOME_PATTERN.sub('/home/[user]', result)
    # Windows (apply in order: most specific first)
    result = _UNC_PATTERN.sub(r'\\\\[server]\\[share]', result)
    result = _APPDATA_PATTERN.sub(r'C:\\Users\\[user]\\AppData\\[...]', result)
    result = _WINDOWS_USER_PATTERN.sub(r'C:\\Users\\[user]', result)
    return result
```

**Note**: The `[^\\]+` pattern correctly handles Windows usernames with spaces (e.g., "John Doe") because it matches everything until the next backslash.

### Phase 9: Subprocess Window Handling

**NOTE**: Both `BashSafeSkill` and `ShellUnsafeSkill` are in `bash.py` (there is no separate `shell_unsafe.py` file).

**File: `nexus3/skill/builtin/bash.py`** - Add CREATE_NO_WINDOW to BOTH skills

BashSafeSkill (line 129):
```python
if sys.platform == "win32":
    return await asyncio.create_subprocess_exec(
        *self._args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=work_dir,
        env=get_safe_env(work_dir),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
    )
```

ShellUnsafeSkill (line 240) - same pattern.

**File: `nexus3/skill/builtin/run_python.py`** (line 84) - same pattern.

**File: `nexus3/mcp/transport.py`** (line 288) - same pattern.

**File: `nexus3/skill/builtin/grep.py`** (line 227) - ADD process groups + CREATE_NO_WINDOW

The grep skill was missing from the original plan. It calls ripgrep without process flags:
```python
# Before (line 227):
proc = await asyncio.create_subprocess_exec(
    *cmd,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)

# After (with platform-aware process handling):
if sys.platform == "win32":
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
    )
else:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
```

### Phase 10: Config BOM Handling

**File: `nexus3/config/load_utils.py`** - Handle UTF-8 BOM

```python
def load_json_file(path: Path) -> dict[str, Any]:
    """Load JSON file, handling UTF-8 BOM if present."""
    content = path.read_text(encoding="utf-8-sig")  # utf-8-sig strips BOM
    return json.loads(content)
```

**File: `nexus3/context/loader.py`** - TWO locations need updating:

1. `_load_file()` method (line 205):
```python
return path.read_text(encoding="utf-8-sig")
```

2. `_get_subagent_prompt()` method (line 630) - this direct read was missing from original plan:
```python
agent_prompt = local_nexus.read_text(encoding="utf-8-sig")
```

---

## Testing Strategy

### Pytest Markers

Add to `pyproject.toml`:
```toml
markers = [
    "windows: tests that only run on Windows",
    "windows_mock: tests that mock Windows behavior (run everywhere)",
    "unix_only: tests that only run on Unix",
]
```

### New Test Files

| File | Purpose |
|------|---------|
| `tests/unit/core/test_process.py` | Process termination utility |
| `tests/unit/cli/test_keys_windows.py` | Windows ESC key detection |
| `tests/unit/core/test_paths_windows.py` | Windows path handling |
| `tests/unit/skill/test_line_ending_preservation.py` | Line ending preservation |
| `tests/security/test_windows_process_termination.py` | Windows process tree kill |

### Coverage Requirements

- All new code must have unit tests
- Mock-based tests run on all platforms
- Real Windows tests marked with `@pytest.mark.windows`

---

## Implementation Checklist

### Phase 1: Process Termination Utility (Foundation - Do First)
- [ ] **P1.1** Create `nexus3/core/process.py` with `terminate_process_tree()`
- [ ] **P1.2** Implement `_terminate_unix()` with SIGTERM -> SIGKILL pattern
- [ ] **P1.3** Implement `_terminate_windows()` with taskkill fallback
- [ ] **P1.4** Add unit tests in `tests/unit/core/test_process.py`

### Phase 2: ESC Key Detection (Critical - Can Parallel P3-P5)
- [ ] **P2.1** Update `nexus3/cli/keys.py` with Windows msvcrt implementation
- [ ] **P2.2** Add unit tests in `tests/unit/cli/test_keys_windows.py`
- [ ] **P2.3** Live test on Windows (if available)

### Phase 3: Environment Variable Unification (Can Parallel P2, P4-P5)
- [ ] **P3.1** Add Windows env vars to `nexus3/skill/builtin/env.py`
- [ ] **P3.2** Add platform-aware DEFAULT_PATH to env.py
- [ ] **P3.3** Update `nexus3/mcp/transport.py` to import from env.py
- [ ] **P3.4** Add tests for Windows env vars

### Phase 4: File Attributes (Can Parallel P2-P3, P5)
- [ ] **P4.1** Add `_format_windows_attributes()` to file_info.py
- [ ] **P4.2** Rename existing to `_format_unix_permissions()`
- [ ] **P4.3** Create platform-aware `_format_permissions()` wrapper
- [ ] **P4.4** Update execute() to pass path
- [ ] **P4.5** Add platform-specific tests

### Phase 5: Line Ending Preservation (Can Parallel P2-P4)
- [ ] **P5.0** Add `detect_line_ending()` and `atomic_write_bytes()` to `nexus3/core/paths.py`
- [ ] **P5.1** Update `edit_file.py`: binary read, normalize, detect, process, convert back, binary write
- [ ] **P5.2** Fix `_line_replace()` hardcoded LF (line 218) to use detected line ending
- [ ] **P5.3** Update `regex_replace.py`: same pattern as edit_file
- [ ] **P5.4** Update `append_file.py`: modify `_needs_newline_prefix()` to return (bool, line_ending) tuple
- [ ] **P5.5** Update 4 existing tests in `test_p2_append_file.py` for tuple return type
- [ ] **P5.6** Add new tests in `tests/unit/skill/test_line_ending_preservation.py`

### Phase 6: Update Consumers (Requires P1)
- [ ] **P6.1** Update `nexus3/skill/base.py` to use `terminate_process_tree()`
- [ ] **P6.2** Update `nexus3/mcp/transport.py` to use `terminate_process_tree()`
- [ ] **P6.3** Convert git skill to asyncio with process groups
- [ ] **P6.4** Verify existing tests pass

### Phase 7: ANSI Escape Sequence Fixes (Can Parallel P2-P6)
- [ ] **P7.1** Replace hardcoded ANSI in `repl.py:907` with Rich Control
- [ ] **P7.2** Replace hardcoded ANSI in `confirmation_ui.py:226-227` with Rich Control
- [ ] **P7.3** Update `console.py` to add `legacy_windows=False`
- [ ] **P7.4** Replace Unicode box chars in `repl.py` with Rich renderables (optional)

### Phase 8: Error Path Sanitization (Can Parallel P2-P7)
- [ ] **P8.1** Add Windows path patterns to `errors.py`
- [ ] **P8.2** Add tests for Windows path sanitization

### Phase 9: Subprocess Window Handling (Can Parallel P2-P8)
- [ ] **P9.1** Add CREATE_NO_WINDOW to `bash.py` BashSafeSkill (line 129)
- [ ] **P9.2** Add CREATE_NO_WINDOW to `bash.py` ShellUnsafeSkill (line 240)
- [ ] **P9.3** Add CREATE_NO_WINDOW to `run_python.py` (line 84)
- [ ] **P9.4** Add CREATE_NO_WINDOW to `mcp/transport.py` (line 288)
- [ ] **P9.5** Add process groups + CREATE_NO_WINDOW to `grep.py` (line 227)

### Phase 10: Config BOM Handling (Can Parallel P2-P9)
- [ ] **P10.1** Update `load_utils.py` to use `encoding="utf-8-sig"` (line 36)
- [ ] **P10.2** Update `context/loader.py` `_load_file()` to use utf-8-sig (line 205)
- [ ] **P10.3** Update `context/loader.py` `_get_subagent_prompt()` to use utf-8-sig (line 630)
- [ ] **P10.4** Update `config/loader.py` `_load_json_file()` to use utf-8-sig (line 40)
- [ ] **P10.5** Update `config/loader.py` `_load_from_path()` to use utf-8-sig (line 156)
- [ ] **P10.6** Add test for BOM-prefixed config files

### Phase 11: Testing Infrastructure (Can Start After P1)
- [ ] **P11.1** Add pytest markers to `pyproject.toml`
- [ ] **P11.2** Add auto-skip logic to `tests/conftest.py`
- [ ] **P11.3** Add `@pytest.mark.windows_mock` to existing MCP tests
- [ ] **P11.4** Create `tests/unit/core/test_paths_windows.py`
- [ ] **P11.5** Create `tests/security/test_windows_process_termination.py`

### Phase 12: Documentation (After Implementation)
- [ ] **P12.1** Create `docs/WINDOWS-TROUBLESHOOTING.md`
- [ ] **P12.2** Add Windows section to `CLAUDE.md`
- [ ] **P12.3** Update `nexus3/cli/README.md` Key Monitor section
- [ ] **P12.4** Update `nexus3/core/README.md` with process.py docs
- [ ] **P12.5** Remove Windows ESC key from "Deferred Work" in CLAUDE.md
- [ ] **P12.6** Document Windows file permission limitations

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| msvcrt not available on some Windows configs | Low | Low | Graceful fallback to sleep-only |
| taskkill not available | Very Low | Low | Always present since Windows XP; fallback to kill() |
| Circular import env.py -> transport.py | Low | Medium | env.py has no imports from nexus3 |
| Line ending detection wrong | Low | Medium | Defaults to LF; string replace unaffected |
| ctypes not available | Very Low | Low | Fallback to "----" for attributes |
| Breaks existing tests | Low | High | Comprehensive test suite; run before/after |
| Rich Control API changes | Low | Medium | Rich is stable; pin version if needed |
| CREATE_NO_WINDOW breaks interactive use | Low | Medium | Only apply to non-interactive subprocesses |
| legacy_windows=False breaks old terminals | Medium | Low | Document Windows 10+ requirement |
| utf-8-sig changes behavior | Very Low | Low | Only strips BOM; otherwise identical |
| Windows ACL permissions remain weak | High | Medium | Document as known limitation; security-sensitive users should restrict parent dirs |
| HTTP proxy users blocked | Medium | Medium | Deferred; document workaround (system proxy) |

---

## Quick Reference

| File | Change Type | Lines/Notes |
|------|-------------|-------------|
| `nexus3/core/process.py` | **NEW** | ~100 lines |
| `nexus3/cli/keys.py` | Modify | Replace lines 79-90 |
| `nexus3/cli/repl.py` | Modify | Line 907 ANSI fix; Unicode box chars |
| `nexus3/cli/confirmation_ui.py` | Modify | Lines 226-227 ANSI fix |
| `nexus3/display/console.py` | Modify | Add legacy_windows=False |
| `nexus3/core/errors.py` | Modify | Add Windows path sanitization |
| `nexus3/skill/builtin/env.py` | Modify | SAFE_ENV_VARS, DEFAULT_PATH |
| `nexus3/skill/builtin/bash.py` | Modify | Add CREATE_NO_WINDOW (both BashSafeSkill + ShellUnsafeSkill) |
| `nexus3/skill/builtin/run_python.py` | Modify | Add CREATE_NO_WINDOW |
| `nexus3/skill/builtin/grep.py` | Modify | Add process groups + CREATE_NO_WINDOW |
| `nexus3/core/paths.py` | Modify | Add `detect_line_ending()` and `atomic_write_bytes()` |
| `nexus3/skill/builtin/append_file.py` | Modify | Fix hardcoded LF line ending, return tuple |
| `nexus3/skill/builtin/regex_replace.py` | Modify | Binary read/write for line ending preservation |
| `nexus3/mcp/transport.py` | Modify | Replace lines 67-88; update close(); CREATE_NO_WINDOW |
| `nexus3/skill/builtin/file_info.py` | Modify | Add Windows attributes |
| `nexus3/skill/builtin/edit_file.py` | Modify | Binary read/write, normalize, preserve line endings |
| `nexus3/skill/builtin/git.py` | Modify | Convert to asyncio |
| `nexus3/skill/base.py` | Modify | Use terminate_process_tree() |
| `nexus3/config/load_utils.py` | Modify | Use utf-8-sig for BOM handling |
| `nexus3/context/loader.py` | Modify | Use utf-8-sig for NEXUS.md |
| `tests/conftest.py` | Modify | Add marker auto-skip |
| `pyproject.toml` | Modify | Add pytest markers |
| `docs/WINDOWS-TROUBLESHOOTING.md` | **NEW** | ~200 lines |

---

## Effort Estimate

| Phase | Description | Est. LOC |
|-------|-------------|----------|
| P1 | Process termination utility | ~100 |
| P2 | ESC key detection | ~30 |
| P3 | Environment variable unification | ~20 |
| P4 | Windows file attributes | ~50 |
| P5 | Line ending preservation | ~40 |
| P6 | Consumer updates (base.py, transport.py, git.py) | ~60 |
| P7 | ANSI escape fixes | ~10 |
| P8 | Error path sanitization | ~20 |
| P9 | Subprocess window handling | ~25 |
| P10 | Config BOM handling | ~10 |
| P11 | Testing infrastructure | ~100 |
| P12 | Documentation | ~200 |
| **Total** | | **~665 LOC** |

*Note: Test code (P11) and documentation (P12) account for ~45% of the total.*

---

## Codebase Validation Notes

### Round 1 (2026-01-28)

Investigation with 5 explorer agents covering:
- Process/subprocess handling
- Path/filesystem operations
- MCP implementation
- Networking/display
- Tests/configuration

Key findings:
- ESC key detection completely non-functional (just sleeps in fallback)
- env.py missing 6 Windows env vars that transport.py has
- DEFAULT_PATH is Unix-only
- file_info shows meaningless rwx on Windows
- edit_file adds LF regardless of file's original line endings
- Git skill has no process group handling
- No Windows CI; 21 Windows tests exist but process tests skipped
- CTRL_BREAK_EVENT may not kill entire process tree

### Round 2 (2026-01-28)

Investigation with 6 additional explorer agents covering deeper analysis:
- REPL/CLI user interaction
- Session management and persistence
- Provider and API client code
- Encoding and text handling
- Skills beyond file operations
- Configuration and defaults

Additional findings:

**REPL/CLI:**
- Hardcoded ANSI escape sequences in `repl.py:907` and `confirmation_ui.py:226-227`
- `force_terminal=True` in `console.py:21` bypasses Windows terminal detection
- Hardcoded Unicode box drawing characters display as `?` in cmd.exe
- Fragile prompt_toolkit internal state access (`prompt_session.app.is_running`)

**Session/Persistence:**
- Windows junction points/reparse points not detected by `is_symlink()`
- File permissions model (0o600) doesn't work with Windows ACLs
- Permission checking (`S_IRWXG|S_IRWXO`) doesn't map to Windows security
- Session/token files may be readable by other users on Windows

**Provider/API:**
- No HTTP proxy support (HTTP_PROXY, HTTPS_PROXY env vars)
- SSL/TLS not configurable in NexusClient and HTTPTransport (only in providers)
- No Windows certificate store integration
- Event loop policy not explicitly set (may cause asyncio issues)
- HTTP/2 not configurable (may fail with corporate proxies)

**Encoding/Text:**
- Rich Console missing `encoding` and `legacy_windows` parameters
- BOM handling not implemented for config/context files
- Missing `CREATE_NO_WINDOW` subprocess flag (cmd.exe window flashes)

**Config/Defaults:**
- Error sanitization only handles Unix paths (`/home/user`), not `C:\Users\...`
- MCP test server hardcodes "python3" command (doesn't exist on Windows)
- Secure file permissions rely on `os.chmod()` which is nearly no-op on Windows

All findings incorporated into this plan. Items marked "Deferred" require architectural changes beyond this plan's scope.

### Round 3 - Validation (2026-01-28)

Six validation agents reviewed the plan against the actual codebase. Findings and corrections:

**Phase 1 (Process Termination)**: ✅ VALIDATED
- Interface matches all existing callers perfectly
- All callers are async-compatible
- No circular imports
- Clean integration with `skill/base.py` and `mcp/transport.py`

**Phase 2 (ESC Key Detection)**: ✅ VALIDATED
- msvcrt approach is asyncio-compatible (brief blocking ops + asyncio.sleep)
- Integrates cleanly with pause/resume protocol
- Special character handling is correct

**Phase 3 (Env Var Unification)**: ✅ VALIDATED
- Architecture is correct; better than alternatives
- No breaking changes; backward compatible

**Phase 4 (File Attributes)**: ✅ VALIDATED
- Correct and complete

**Phase 5 (Line Ending Preservation)**: ❌ CRITICAL ISSUE FOUND - CORRECTED
- **Problem**: Python's `read_text()` automatically converts CRLF to LF before skill code sees it
- **Solution**: Changed to binary read + decode pattern
- **Expanded scope**: Added `append_file.py` and `regex_replace.py` (same issue)

**Phase 6 (Git Skill)**: ✅ VALIDATED with notes
- Asyncio conversion is correct
- Process group flags match bash.py
- Acceptable code duplication for Phase 6 scope (future FilteredExecutionSkill noted)

**Phase 7 (ANSI Fixes)**: ⚠️ MINOR ISSUE - CORRECTED
- **Problem**: Missing `from rich.control import Control` import statement
- **Solution**: Added explicit import instructions

**Phase 8 (Error Sanitization)**: ⚠️ ISSUES FOUND - CORRECTED
- **Problems**:
  - Regex `[^\\:\s]+` truncates usernames with spaces (Windows allows "John Doe")
  - Missing UNC path pattern (`\\server\share`)
- **Solutions**:
  - Changed to `[^\\]+` (stops at backslash, handles spaces)
  - Added `_UNC_PATTERN`

**Phase 9 (Subprocess Windows)**: ❌ ISSUES FOUND - CORRECTED
- **Problems**:
  - Plan referenced non-existent `shell_unsafe.py` (both skills in `bash.py`)
  - Missing `grep.py` subprocess call (line 227)
- **Solutions**:
  - Fixed file references
  - Added P9.5 for grep.py with full platform-aware handling

**Phase 10 (BOM Handling)**: ⚠️ INCOMPLETE - CORRECTED
- **Problem**: Missing `context/loader.py` line 630 (`_get_subagent_prompt()`)
- **Solution**: Added P10.3 for this call site

All corrections have been applied to the plan document.

### Round 4 - Validation (2026-01-28)

Six validation agents re-validated the corrected plan. Additional findings:

**Phase 5 (append_file.py)**: ⚠️ CLARIFICATION NEEDED - CORRECTED
- **Finding**: Hardcoded LF is on line 117 in `do_append()`, not line 35
- **Solution**: Updated plan to show correct location and code pattern

**Phase 7 (ANSI Fixes)**: ❌ CRITICAL API ERROR - CORRECTED
- **Finding**: Rich's `Control` class does NOT have `move_up()`, `erase_line()`, or `erase_end()` methods
- **Solution**: Revised approach - the key fix is `legacy_windows=False` in console.py, which enables VT100 mode. ANSI sequences can remain unchanged.

**Phase 8 (Error Sanitization)**: ✅ VALIDATED
- All regex patterns verified correct
- `[^\\]+` properly handles usernames with spaces

**Phase 9 (Subprocess)**: ✅ VALIDATED
- All line numbers accurate
- grep.py correctly added (P9.5)

**Phase 10 (BOM)**: ⚠️ INCOMPLETE - CORRECTED
- **Finding**: Missing 2 call sites in `config/loader.py` (lines 40, 156)
- **Solution**: Added P10.4 and P10.5 for these locations

**Cross-check**: ⚠️ MINOR - CORRECTED
- Test filename inconsistency fixed (standardized on `test_line_ending_preservation.py`)

All Round 4 corrections have been applied.

### Round 5 - Final Validation (2026-01-28)

Six validation agents performed final review. Only one minor issue found:

**Phase 5 (Line Endings)**: ⚠️ WORDING CLARIFICATION - CORRECTED
- **Finding**: P5.5 checklist said "Fix `_needs_newline_prefix()`" but actual fix is in `do_append()`
- **Solution**: Updated checklist to "Fix `append_file.py` `do_append()` to use detected line ending (line 117)"

**All other phases**: ✅ VALIDATED
- Line numbers verified accurate
- Code patterns confirmed correct
- No remaining issues

### Round 6 - Security & Compatibility Review (2026-01-28)

Comprehensive security and compatibility review found **critical issues** requiring plan corrections:

**Phase 8 (Error Sanitization)**: ❌ CRITICAL - CORRECTED
- **Finding**: Patterns only handled backslashes (`\\`), not forward slashes (`/`)
- **Issue**: `C:/Users/alice` would NOT be sanitized, leaking usernames
- **Solution**: Updated all patterns to use `[\\\/]` alternation to handle both slash types
- **Updated**: `_UNC_PATTERN`, `_APPDATA_PATTERN`, `_WINDOWS_USER_PATTERN`

**Phase 5 (Line Endings)**: ❌ CRITICAL DESIGN FLAW - CORRECTED
- **Finding 1**: Double-CRLF bug - `content.replace('\n', '\r\n')` on content with existing `\r\n` creates `\r\r\n`
- **Finding 2**: `atomic_write_text()` uses text mode which re-normalizes on Windows
- **Finding 3**: DRY violation - helper function duplicated across 3 files
- **Solution**: Complete redesign:
  - Add shared `detect_line_ending()` and `atomic_write_bytes()` to `nexus3/core/paths.py`
  - Normalize ALL endings to `\n` BEFORE processing
  - Convert back to detected ending AFTER processing
  - Write as bytes to preserve exact line endings

**All other phases**: ✅ VALIDATED
- Process termination (P1): Secure, no issues
- Environment variables (P3): Safe, minimal risk
- Rich console changes (P7): Compatible, no breaking changes

Plan corrections applied. Ready for implementation.

### Round 7 - Final Security & Compatibility Review (2026-01-28)

Six validation agents performed final security and compatibility review:

**Phase 8 (Error Sanitization)**: ⚠️ ADDITIONAL GAPS FOUND - CORRECTED
- **Finding 1**: Relative paths without drive letter (`..\Users\alice`) not sanitized
- **Finding 2**: Domain\username format (`DOMAIN\alice`, `BUILTIN\Administrators`) not sanitized
- **Solution**: Added `_RELATIVE_USER_PATTERN` and `_DOMAIN_USER_PATTERN` regex patterns
- **Updated**: Plan P8.1 with new patterns and sanitization calls

**Phase 5 (Line Endings)**: ⚠️ BUG IN `_line_replace()` - CORRECTED
- **Finding**: Line 218 in edit_file.py hardcodes `"\n"` when adding trailing newline
- **Solution**: Added P5.2 checklist item to fix this to use detected line ending
- **Updated**: Plan P5.3 with specific fix instructions

**Phase 5 (append_file tests)**: ⚠️ TEST BREAKAGE - DOCUMENTED
- **Finding**: 4 tests in `TestNeedsNewlineHelper` expect bool, will get tuple after P5.4
- **Solution**: Added P5.5 checklist item with test update instructions and new CRLF tests
- **Updated**: Plan with P5.6 section documenting exact test changes needed

**All other phases**: ✅ VALIDATED
- Process termination (P1): Secure, no new issues
- Error sanitization (P8): Now covers all Windows path variants
- Line ending (P5): Full pattern documented including edge cases

All Round 7 corrections have been applied.

---

# Detailed Implementation Guidance

This section provides copy-paste ready code for each phase, allowing subagents with no prior context to implement their assigned phase independently.

---

## Phase 1: Process Termination Utility - Full Implementation

### P1.1-P1.3: Create `nexus3/core/process.py`

```python
"""Cross-platform process termination utilities.

Provides robust process tree termination that works on both Unix and Windows:
- Unix: SIGTERM -> wait -> SIGKILL to process group
- Windows: CTRL_BREAK_EVENT -> wait -> taskkill /T /F -> TerminateProcess
"""

import asyncio
import logging
import os
import signal
import sys
from asyncio.subprocess import Process

logger = logging.getLogger(__name__)

GRACEFUL_TIMEOUT: float = 2.0


async def terminate_process_tree(
    process: Process,
    graceful_timeout: float = GRACEFUL_TIMEOUT,
) -> None:
    """Terminate a process and all its children."""
    if process.returncode is not None:
        return

    pid = process.pid
    if pid is None:
        return

    if sys.platform == "win32":
        await _terminate_windows(process, pid, graceful_timeout)
    else:
        await _terminate_unix(process, pid, graceful_timeout)


async def _terminate_unix(process: Process, pid: int, graceful_timeout: float) -> None:
    """Unix: SIGTERM -> wait -> SIGKILL to process group."""
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)
        logger.debug("Sent SIGTERM to process group %d", pgid)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.terminate()
        except ProcessLookupError:
            return

    try:
        await asyncio.wait_for(process.wait(), timeout=graceful_timeout)
        return
    except TimeoutError:
        pass

    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGKILL)
        logger.debug("Sent SIGKILL to process group %d", pgid)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except ProcessLookupError:
            pass

    try:
        await process.wait()
    except Exception:
        pass


async def _terminate_windows(process: Process, pid: int, graceful_timeout: float) -> None:
    """Windows: CTRL_BREAK -> wait -> taskkill /T /F -> kill."""
    try:
        os.kill(pid, signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
        logger.debug("Sent CTRL_BREAK_EVENT to process %d", pid)
    except (ProcessLookupError, OSError, AttributeError):
        pass

    try:
        await asyncio.wait_for(process.wait(), timeout=graceful_timeout)
        return
    except TimeoutError:
        pass

    try:
        taskkill = await asyncio.create_subprocess_exec(
            "taskkill", "/T", "/F", "/PID", str(pid),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(taskkill.wait(), timeout=graceful_timeout)
        logger.debug("taskkill /T /F completed for PID %d", pid)
    except (FileNotFoundError, TimeoutError, OSError):
        pass

    try:
        await asyncio.wait_for(process.wait(), timeout=0.5)
        return
    except TimeoutError:
        pass

    try:
        process.kill()
    except ProcessLookupError:
        pass

    try:
        await process.wait()
    except Exception:
        pass
```

### P1.4: Integration Points

**Update `nexus3/skill/base.py` lines 1016-1032:**

Replace:
```python
except TimeoutError:
    try:
        if sys.platform == "win32":
            os.kill(process.pid, signal.CTRL_BREAK_EVENT)
        else:
            pgid = os.getpgid(process.pid)
            os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, OSError, AttributeError):
        process.kill()
    await process.wait()
    return ToolResult(error=timeout_message.format(timeout=timeout))
```

With:
```python
except TimeoutError:
    from nexus3.core.process import terminate_process_tree
    await terminate_process_tree(process)
    return ToolResult(error=timeout_message.format(timeout=timeout))
```

**Update `nexus3/mcp/transport.py` lines 476-496** similarly.

---

## Phase 2: ESC Key Detection - Full Implementation

### P2.1: Update `nexus3/cli/keys.py` lines 79-90

Replace:
```python
    except (ImportError, OSError, AttributeError):
        # Fallback for Windows or when terminal isn't available
        while True:
            if not pause_event.is_set():
                pause_ack_event.set()
                await pause_event.wait()
                pause_ack_event.clear()
                continue
            await asyncio.sleep(check_interval)
```

With:
```python
    except (ImportError, OSError, AttributeError):
        # Fallback for Windows or when terminal isn't available
        if sys.platform == "win32":
            try:
                import msvcrt

                while True:
                    if not pause_event.is_set():
                        pause_ack_event.set()
                        await pause_event.wait()
                        pause_ack_event.clear()
                        continue

                    if msvcrt.kbhit():
                        char = msvcrt.getwch()
                        if char == ESC:
                            on_escape()
                        elif char in ('\x00', '\xe0'):
                            if msvcrt.kbhit():
                                msvcrt.getwch()

                    await asyncio.sleep(check_interval)

            except (ImportError, OSError, AttributeError):
                pass
            else:
                return

        # Final fallback: No keyboard input available
        while True:
            if not pause_event.is_set():
                pause_ack_event.set()
                await pause_event.wait()
                pause_ack_event.clear()
                continue
            await asyncio.sleep(check_interval)
```

---

## Phase 3: Environment Variable Unification - Full Implementation

### P3.1-P3.2: Update `nexus3/skill/builtin/env.py`

Add to SAFE_ENV_VARS:
```python
SAFE_ENV_VARS: frozenset[str] = frozenset({
    # Path and execution
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "PWD",
    # Locale
    "LANG", "LC_ALL", "LC_CTYPE", "LC_COLLATE", "LC_MESSAGES", "TZ",
    # Terminal
    "TERM", "COLORTERM", "COLUMNS", "LINES",
    # Temp directories
    "TMPDIR", "TMP", "TEMP",
    # Windows-specific
    "USERPROFILE", "APPDATA", "LOCALAPPDATA",
    "PATHEXT", "SYSTEMROOT", "COMSPEC",
})
```

Add platform-aware DEFAULT_PATH:
```python
import sys

if sys.platform == "win32":
    DEFAULT_PATH = r"C:\Windows\System32;C:\Windows;C:\Windows\System32\Wbem"
else:
    DEFAULT_PATH = "/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin"
```

### P3.3: Update `nexus3/mcp/transport.py` lines 67-128

Replace entire SAFE_ENV_KEYS definition with:
```python
from nexus3.skill.builtin.env import SAFE_ENV_VARS as SAFE_ENV_KEYS, build_safe_env
```

---

## Phase 4: Windows File Attributes - Full Implementation

### P4.1-P4.3: Update `nexus3/skill/builtin/file_info.py`

Replace `_format_permissions` with:
```python
import sys

def _format_permissions(mode: int, path: Path | None = None) -> str:
    """Format file permissions/attributes in a platform-appropriate way."""
    if sys.platform == "win32" and path is not None:
        return _format_windows_attributes(path)
    return _format_unix_permissions(mode)


def _format_unix_permissions(mode: int) -> str:
    """Format Unix file mode as rwxrwxrwx string."""
    perms = []
    for who in ("USR", "GRP", "OTH"):
        for perm in ("R", "W", "X"):
            flag = getattr(stat, f"S_I{perm}{who}")
            perms.append(perm.lower() if mode & flag else "-")
    return "".join(perms)


def _format_windows_attributes(path: Path) -> str:
    """Format Windows file attributes as RHSA string."""
    import ctypes

    try:
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs == 0xFFFFFFFF:
            return "????"

        result = []
        result.append("R" if attrs & 0x1 else "-")   # READONLY
        result.append("H" if attrs & 0x2 else "-")   # HIDDEN
        result.append("S" if attrs & 0x4 else "-")   # SYSTEM
        result.append("A" if attrs & 0x20 else "-")  # ARCHIVE
        return "".join(result)
    except Exception:
        return "----"
```

### P4.4: Update execute() call

Change line 107 from:
```python
"permissions": _format_permissions(st.st_mode),
```
To:
```python
"permissions": _format_permissions(st.st_mode, p),
```

---

## Phase 5: Line Ending Preservation - Full Implementation

**CRITICAL**: Python's `read_text()` automatically converts CRLF to LF. To preserve line endings:
1. Read in binary mode, decode manually
2. Detect original line ending BEFORE normalizing
3. Normalize ALL endings to `\n` for processing (avoid double-CRLF bug)
4. Convert back to detected ending before writing
5. Write in binary mode to preserve exact bytes

### P5.0: Add shared utility to `nexus3/core/paths.py`

Add after `atomic_write_text()` function (around line 183):

```python
def detect_line_ending(content: str) -> str:
    """Detect the predominant line ending style in content.

    Returns:
        "\\r\\n" (CRLF - Windows), "\\n" (LF - Unix), "\\r" (CR - legacy)
    """
    if '\r\n' in content:
        return '\r\n'
    elif '\r' in content:
        return '\r'
    return '\n'


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes to a file atomically using temp file + rename.

    Similar to atomic_write_text but for binary data, preserving exact bytes.
    """
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".tmp_", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
```

### P5.1: Update `nexus3/skill/builtin/edit_file.py`

Add import at top:
```python
from nexus3.core.paths import atomic_write_bytes, detect_line_ending
```

### P5.2: Change file reading to binary mode (line 118)

Replace:
```python
content = await asyncio.to_thread(p.read_text, encoding="utf-8")
```
With:
```python
content_bytes = await asyncio.to_thread(p.read_bytes)
raw_content = content_bytes.decode("utf-8", errors="replace")
original_line_ending = detect_line_ending(raw_content)
# Normalize ALL line endings to \n for processing (avoids double-CRLF bug)
content = raw_content.replace('\r\n', '\n').replace('\r', '\n')
```

### P5.3: Update write logic in `_string_replace()` and `_line_replace()`

Before calling `atomic_write_text()`, convert back to original ending and use binary write:

```python
# Convert normalized \n back to original line ending
if original_line_ending != '\n':
    result_content = result_content.replace('\n', original_line_ending)
# Write as bytes to preserve exact line endings
await asyncio.to_thread(atomic_write_bytes, p, result_content.encode('utf-8'))
```

**CRITICAL**: Also fix the hardcoded LF in `_line_replace()` around line 218:

```python
# BEFORE (bug - hardcoded LF):
if new_content and not new_content.endswith("\n"):
    new_content += "\n"

# AFTER (use detected line ending):
if new_content and not new_content.endswith(("\n", "\r")):
    new_content += original_line_ending
```

Note: The `original_line_ending` variable must be passed to `_line_replace()` or made accessible in that scope.

### P5.4: Update `nexus3/skill/builtin/regex_replace.py` (line 133)

Same pattern - add import, binary read, normalize, process, convert back, binary write:
```python
from nexus3.core.paths import atomic_write_bytes, detect_line_ending

# Read and normalize
content_bytes = await asyncio.to_thread(p.read_bytes)
raw_content = content_bytes.decode("utf-8", errors="replace")
original_line_ending = detect_line_ending(raw_content)
content = raw_content.replace('\r\n', '\n').replace('\r', '\n')

# ... do regex replacement on normalized content ...

# Convert back and write as bytes
if original_line_ending != '\n':
    new_content = new_content.replace('\n', original_line_ending)
await asyncio.to_thread(atomic_write_bytes, p, new_content.encode('utf-8'))
```

### P5.5: Update `nexus3/skill/builtin/append_file.py`

Modify `_needs_newline_prefix()` to also detect line ending from tail bytes:

```python
def _needs_newline_prefix(filepath: os.PathLike[str]) -> tuple[bool, str]:
    """Check if file needs newline prefix and detect its line ending.

    Returns:
        Tuple of (needs_newline: bool, detected_line_ending: str)
    """
    try:
        size = os.path.getsize(filepath)
        if size == 0:
            return False, "\n"

        with open(filepath, "rb") as f:
            # Read last 1KB to detect line ending style
            read_size = min(1024, size)
            f.seek(max(0, size - read_size))
            tail_bytes = f.read()

            # Detect line ending from tail
            tail_str = tail_bytes.decode("utf-8", errors="replace")
            if '\r\n' in tail_str:
                line_ending = '\r\n'
            elif '\r' in tail_str:
                line_ending = '\r'
            else:
                line_ending = '\n'

            needs_prefix = not tail_bytes.endswith(b"\n")
            return needs_prefix, line_ending
    except (OSError, IOError):
        return False, "\n"
```

Update `do_append()` to use the tuple:
```python
def do_append() -> int:
    to_write = content
    if newline and p.exists():
        needs_nl, line_ending = _needs_newline_prefix(p)
        if needs_nl:
            to_write = line_ending + content
    # ... rest unchanged (still uses append mode)
```

### P5.6: Update existing append_file tests

**REQUIRED**: The `_needs_newline_prefix()` return type change from `bool` to `tuple[bool, str]` will break 4 existing tests in `tests/unit/skill/test_p2_append_file.py`:

- Line 145: `TestNeedsNewlineHelper.test_empty_file` - expects `False`, will get `(False, "\n")`
- Line 154: `TestNeedsNewlineHelper.test_file_ends_with_newline` - expects `False`, will get `(False, "\n")`
- Line 163: `TestNeedsNewlineHelper.test_file_not_ending_with_newline` - expects `True`, will get `(True, "\n")`
- Line 171: `TestNeedsNewlineHelper.test_file_with_content_no_trailing_newline` - expects `True`, will get `(True, "\n")`

**Fix**: Update each assertion to unpack the tuple:
```python
# Before:
assert _needs_newline_prefix(test_file) == False

# After:
needs_nl, line_ending = _needs_newline_prefix(test_file)
assert needs_nl == False
assert line_ending == "\n"
```

Also add tests for CRLF files to verify line ending detection:
```python
def test_crlf_file_detection(self, tmp_path: Path):
    test_file = tmp_path / "crlf.txt"
    test_file.write_bytes(b"line1\r\nline2\r\n")
    needs_nl, line_ending = _needs_newline_prefix(test_file)
    assert needs_nl == False
    assert line_ending == "\r\n"

def test_crlf_file_no_trailing_newline(self, tmp_path: Path):
    test_file = tmp_path / "crlf.txt"
    test_file.write_bytes(b"line1\r\nline2")
    needs_nl, line_ending = _needs_newline_prefix(test_file)
    assert needs_nl == True
    assert line_ending == "\r\n"
```

### P5.7: New test file for line ending preservation

Create `tests/unit/skill/test_line_ending_preservation.py`:
```python
import pytest
from pathlib import Path
from nexus3.core.paths import detect_line_ending

class TestDetectLineEnding:
    def test_detect_crlf(self):
        assert detect_line_ending("line1\r\nline2\r\n") == "\r\n"

    def test_detect_lf(self):
        assert detect_line_ending("line1\nline2\n") == "\n"

    def test_detect_cr(self):
        assert detect_line_ending("line1\rline2\r") == "\r"

    def test_empty_defaults_lf(self):
        assert detect_line_ending("") == "\n"


@pytest.mark.asyncio
async def test_edit_file_preserves_crlf(tmp_path: Path, service_container):
    """Verify CRLF line endings are preserved after editing."""
    test_file = tmp_path / "crlf.txt"
    test_file.write_bytes(b"line1\r\nline2\r\nline3\r\n")

    skill = EditFileSkill(service_container)
    await skill.execute(
        path=str(test_file),
        old_string="line2",
        new_string="MODIFIED"
    )

    result = test_file.read_bytes()
    assert b"\r\n" in result, "CRLF should be preserved"
    assert b"\nMODIFIED\r\n" not in result, "Should not have mixed endings"
    assert b"\r\nMODIFIED\r\n" in result, "Edit should use CRLF"
```

---

## Phase 6: Git Skill Process Groups - Full Implementation

### P6.3: Update `nexus3/skill/builtin/git.py`

Add imports:
```python
import os
import signal
import sys
from nexus3.skill.builtin.env import get_safe_env
```

Replace the `execute` method's subprocess execution (lines 273-285) with:
```python
if sys.platform == "win32":
    process = await asyncio.create_subprocess_exec(
        *cmd_parts,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(work_dir),
        env=get_safe_env(str(work_dir)),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
else:
    process = await asyncio.create_subprocess_exec(
        *cmd_parts,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(work_dir),
        env=get_safe_env(str(work_dir)),
        start_new_session=True,
    )

try:
    stdout_bytes, stderr_bytes = await asyncio.wait_for(
        process.communicate(),
        timeout=GIT_TIMEOUT
    )
except TimeoutError:
    from nexus3.core.process import terminate_process_tree
    await terminate_process_tree(process)
    return ToolResult(error=f"Git command timed out after {GIT_TIMEOUT}s")

stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
```

---

## Phase 7: ANSI Escape Sequence Fixes

**CRITICAL NOTE**: Rich's `Control` class does NOT have `move_up()`, `erase_line()`, or `erase_end()` methods. The correct fix is to set `legacy_windows=False` on the Console, which enables Windows VT100 mode and makes ANSI sequences work natively.

### P7.1: Update `nexus3/display/console.py` FIRST (This is the key fix)

```python
_console = Console(
    highlight=False,
    markup=True,
    force_terminal=True,
    legacy_windows=False,  # Enables VT100 mode on Windows 10+
)
```

With this change, Windows Terminal properly interprets ANSI escape sequences.

### P7.2: Update `nexus3/cli/repl.py` line 907 (Optional - for consistency)

The ANSI sequences can remain as-is since `legacy_windows=False` enables VT100 mode. Optionally change `sys.stdout` to `console.file` for consistency:

```python
# Keep the same ANSI sequences, optionally use console.file:
console.file.write("\033[1A\r\033[2K")
console.file.flush()
```

### P7.3: Update `nexus3/cli/confirmation_ui.py` lines 226-227 (Optional - for consistency)

Same approach - ANSI sequences work with `legacy_windows=False`:

```python
# Keep the same ANSI sequences, optionally use console.file:
console.file.write(f"\033[{lines_printed}F")
console.file.write("\033[J")
console.file.flush()
```

**Summary**: The primary fix is `legacy_windows=False` in console.py. The ANSI escape sequences themselves do not need to change - they will work on Windows 10+ once VT100 mode is enabled.

---

## Phase 8: Error Path Sanitization

### P8.1: Update `nexus3/core/errors.py`

Add after existing patterns (around line 62):
```python
# Windows path patterns (order matters - most specific first)
# Handle BOTH backslashes AND forward slashes - Windows accepts either
_UNC_PATTERN = re.compile(r'(?:\\\\|//)[^\\\/]+[\\\/][^\\\/]+')  # \\server\share or //server/share
_APPDATA_PATTERN = re.compile(
    r'[A-Za-z]:[\\\/]Users[\\\/][^\\\/]+[\\\/]AppData[\\\/][^\\\/]+',
    re.IGNORECASE
)
_WINDOWS_USER_PATTERN = re.compile(
    r'[A-Za-z]:[\\\/]Users[\\\/][^\\\/]+',
    re.IGNORECASE
)
# Relative paths without drive letter (e.g., ..\Users\alice\secrets.txt)
_RELATIVE_USER_PATTERN = re.compile(r'(^|\s|\\|/)Users[\\\/][^\\\/\"]+', re.IGNORECASE)
# Domain\username format (e.g., DOMAIN\alice, BUILTIN\Administrators)
_DOMAIN_USER_PATTERN = re.compile(r'\b([A-Z][A-Z0-9_-]*)(\\)[^\\\/\"\s]+', re.IGNORECASE)
```

**Note**: Using `[\\\/]` handles both backslash AND forward slash paths. Using `[^\\\/]+` correctly handles usernames with spaces like "John Doe" and stops at either separator.

Add to `sanitize_error_for_agent()` before the generic path replacement:
```python
# Windows paths (apply in order: most specific first)
# Handle both backslash and forward slash variants
result = _UNC_PATTERN.sub(r'\\\\[server]\\[share]', result)
result = _APPDATA_PATTERN.sub(r'C:\\Users\\[user]\\AppData\\[...]', result)
result = _WINDOWS_USER_PATTERN.sub(r'C:\\Users\\[user]', result)
# Relative paths and domain\user patterns
result = _RELATIVE_USER_PATTERN.sub(r'\1Users\\[user]', result)
result = _DOMAIN_USER_PATTERN.sub(r'[domain]\\[user]', result)
```

### P8.2: Add tests

```python
def test_sanitize_windows_paths():
    """Test Windows path sanitization including edge cases."""
    # Basic Windows path (backslash)
    assert sanitize_error("Error in C:\\Users\\alice\\project") == "Error in C:\\Users\\[user]\\project"

    # Forward slash variant (also valid on Windows)
    assert sanitize_error("Error in C:/Users/alice/project") == "Error in C:\\Users\\[user]\\project"

    # Mixed slashes
    assert sanitize_error("C:\\Users/alice\\file.txt") == "C:\\Users\\[user]\\file.txt"

    # Username with spaces
    assert sanitize_error("Error in C:\\Users\\John Doe\\file.txt") == "Error in C:\\Users\\[user]\\file.txt"

    # AppData path
    assert sanitize_error("Config at C:\\Users\\bob\\AppData\\Local\\NEXUS3") == \
           "Config at C:\\Users\\[user]\\AppData\\[...]"

    # UNC path (backslash)
    assert sanitize_error("Access denied: \\\\fileserver\\projects") == \
           "Access denied: \\\\[server]\\[share]"

    # UNC path (forward slash)
    assert sanitize_error("Access denied: //fileserver/projects") == \
           "Access denied: \\\\[server]\\[share]"

    # Lowercase drive letter
    assert sanitize_error("c:\\users\\test") == "C:\\Users\\[user]"

    # Relative path without drive letter
    assert sanitize_error("Error in ..\\Users\\alice\\secrets.txt") == \
           "Error in ..\\Users\\[user]\\secrets.txt"

    # Domain\username format
    assert sanitize_error("Access denied for DOMAIN\\alice") == \
           "Access denied for [domain]\\[user]"

    # BUILTIN accounts
    assert sanitize_error("BUILTIN\\Administrators denied") == \
           "[domain]\\[user] denied"
```

### Error Message Examples

| Input | Output |
|-------|--------|
| `C:\Users\alice\project\file.txt not found` | `C:\Users\[user]\project\file.txt not found` |
| `C:/Users/alice/project/file.txt not found` | `C:\Users\[user]\project\file.txt not found` |
| `C:\Users\John Doe\secrets\token.txt` | `C:\Users\[user]\secrets\token.txt` |
| `C:\Users\bob\AppData\Local\NEXUS3\config.json` | `C:\Users\[user]\AppData\[...]` |
| `\\fileserver\projects\secret.doc` | `\\[server]\[share]` |
| `//fileserver/projects/secret.doc` | `\\[server]\[share]` |
| `Error: /home/alice/.nexus3/token` | `Error: /home/[user]/.nexus3/token` |
| `..\Users\alice\secrets.txt` | `..\Users\[user]\secrets.txt` |
| `DOMAIN\alice denied access` | `[domain]\[user] denied access` |
| `BUILTIN\Administrators` | `[domain]\[user]` |

*Note: Unix paths continue to work via existing patterns. Windows patterns handle both backslash and forward slash variants, relative paths, and domain\user formats.*

---

## Phase 9: Subprocess Window Handling

**NOTE**: Both shell skills are in `bash.py` (there is no `shell_unsafe.py`).

### P9.1-P9.2: Update `nexus3/skill/builtin/bash.py`

BashSafeSkill (line 129) and ShellUnsafeSkill (line 240), change:
```python
creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
```
To:
```python
creationflags=(
    subprocess.CREATE_NEW_PROCESS_GROUP |
    subprocess.CREATE_NO_WINDOW
),
```

### P9.3: Update `nexus3/skill/builtin/run_python.py` (line 84)

Same change as above.

### P9.4: Update `nexus3/mcp/transport.py` (line 288)

Same change as above.

### P9.5: Update `nexus3/skill/builtin/grep.py` (line 227)

This file was missing from the original plan. Add platform-aware process handling:

```python
import subprocess
import sys

# Replace the existing subprocess call with:
if sys.platform == "win32":
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=(
            subprocess.CREATE_NEW_PROCESS_GROUP |
            subprocess.CREATE_NO_WINDOW
        ),
    )
else:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
```

---

## Phase 10: Config BOM Handling

### P10.1: Update `nexus3/config/load_utils.py` (line 36)

Change:
```python
content = path.read_text(encoding="utf-8")
```
To:
```python
content = path.read_text(encoding="utf-8-sig")
```

### P10.2: Update `nexus3/context/loader.py` `_load_file()` (line 205)

Change:
```python
return path.read_text(encoding="utf-8")
```
To:
```python
return path.read_text(encoding="utf-8-sig")
```

### P10.3: Update `nexus3/context/loader.py` `_get_subagent_prompt()` (line 630)

This direct read was missing from the original plan:
```python
# Before:
agent_prompt = local_nexus.read_text(encoding="utf-8")

# After:
agent_prompt = local_nexus.read_text(encoding="utf-8-sig")
```

### P10.4-P10.5: Update `nexus3/config/loader.py` (TWO locations)

These were discovered in Round 4 validation:

**Line 40 in `_load_json_file()`:**
```python
# Before:
content = path.read_text(encoding="utf-8")

# After:
content = path.read_text(encoding="utf-8-sig")
```

**Line 156 in `_load_from_path()`:**
```python
# Before:
content = path.read_text(encoding="utf-8")

# After:
content = path.read_text(encoding="utf-8-sig")
```

---

## Verification Commands

After implementing each phase:

```bash
# Run all tests
.venv/bin/pytest tests/ -v

# Run security tests
.venv/bin/pytest tests/security/ -v

# Type check
.venv/bin/mypy nexus3/

# Lint
.venv/bin/ruff check nexus3/
```
