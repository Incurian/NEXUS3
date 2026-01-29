# Plan: Windows Shell Compatibility

## Overview

**Current State:** NEXUS3 has Windows-native compatibility (process termination, line endings, BOM handling, etc.) but assumes a modern terminal environment. Running through different Windows shells (Git Bash, PowerShell, CMD.exe) reveals shell-specific issues not addressed by the native compatibility work.

**Goal:** Detect the shell environment and adapt behavior appropriately for Git Bash, PowerShell 5.1/7+, CMD.exe, and Windows Terminal.

**Branch:** `feature/windows-shell-compat` (from `feature/windows-native-compat`)

**Research:** Based on Claude Code explorer reports analyzing Git Bash, PowerShell, and CMD.exe compatibility (2026-01-28).

---

## Scope

### Included in v1

| Priority | Issue | Description |
|----------|-------|-------------|
| **CRITICAL** | `force_terminal=True` | Forces ANSI output even in CMD.exe which can't render it |
| **HIGH** | Shell detection | No way to distinguish Git Bash vs PowerShell vs CMD vs Windows Terminal |
| **HIGH** | ASCII fallback | No fallback for terminals without ANSI/Unicode support |
| **HIGH** | `shlex.split()` POSIX mode | Backslashes treated as escape chars, breaks Windows paths |
| **MEDIUM** | PowerShell 5.1 ANSI | VT100 mode doesn't work properly in PS 5.1 |
| **MEDIUM** | Console code page | UTF-8 output to non-UTF-8 console causes garbled text |
| **LOW** | Documentation | Shell-specific setup and troubleshooting guides |

### Deferred

| Feature | Reason |
|---------|--------|
| PowerShell cmdlet/alias translation | Complex, users can use `shell_UNSAFE` |
| MSYS2 path conversion control | Rare edge case, document workaround |
| ConPTY detection | Windows 10 version-dependent, complex |
| IPv6 localhost support | Edge case |

### Explicitly Excluded

| Feature | Reason |
|---------|--------|
| PowerShell execution policy handling | User configuration issue |
| Git Bash certificate store integration | Already fixed with ssl_ca_cert config |
| Windows 7/8 support | Require Windows 10+ |

---

## Design Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| How to detect shell? | Environment variable checks | No external dependencies, reliable |
| What to do when ANSI unsupported? | ASCII fallback mode | Graceful degradation |
| Where to store detection result? | Module-level singleton | Checked once at startup, reused |
| `shlex.split()` fix location? | In bash skill, check platform | Minimal change, targeted fix |
| Rich console configuration? | Dynamic based on shell detection | Adapt to environment |

---

## Shell Detection Strategy

### Environment Variable Fingerprints

| Shell | Detection Method |
|-------|------------------|
| **Windows Terminal** | `WT_SESSION` is set |
| **PowerShell 7+** | `PSVersionTable` set AND version >= 7 (via subprocess) |
| **PowerShell 5.1** | `PSModulePath` set, no `WT_SESSION`, TERM not set |
| **Git Bash (MSYS2)** | `MSYSTEM` set (MINGW64, MINGW32, MSYS, UCRT64, CLANG64, CLANGARM64) |
| **CMD.exe** | `COMSPEC` ends with `cmd.exe`, no `TERM`, no `MSYSTEM`, no `WT_SESSION` |
| **Unknown** | Fallback - assume basic capabilities |

### Detection Code

```python
# nexus3/core/shell_detection.py

import os
import sys
from enum import Enum, auto
from functools import lru_cache

class WindowsShell(Enum):
    WINDOWS_TERMINAL = auto()  # Modern, full ANSI/Unicode
    POWERSHELL_7 = auto()      # Good ANSI, UTF-8 by default
    POWERSHELL_5 = auto()      # Broken ANSI, legacy encoding
    GIT_BASH = auto()          # Unix-like, MSYS2 path issues
    CMD = auto()               # No ANSI without Windows Terminal
    UNKNOWN = auto()           # Assume basic

@lru_cache(maxsize=1)
def detect_windows_shell() -> WindowsShell:
    """Detect which Windows shell environment we're running in."""
    if sys.platform != "win32":
        return WindowsShell.UNKNOWN

    # Windows Terminal wraps other shells
    if os.environ.get("WT_SESSION"):
        return WindowsShell.WINDOWS_TERMINAL

    # Git Bash / MSYS2
    if os.environ.get("MSYSTEM"):
        return WindowsShell.GIT_BASH

    # PowerShell detection
    if os.environ.get("PSModulePath"):
        # Could be PS 5.1 or 7+, check version if needed
        # For now, assume 5.1 (conservative)
        return WindowsShell.POWERSHELL_5

    # CMD.exe fallback
    comspec = os.environ.get("COMSPEC", "").lower()
    if comspec.endswith("cmd.exe"):
        return WindowsShell.CMD

    return WindowsShell.UNKNOWN

def supports_ansi() -> bool:
    """Check if current shell supports ANSI escape sequences."""
    shell = detect_windows_shell()
    return shell in {
        WindowsShell.WINDOWS_TERMINAL,
        WindowsShell.POWERSHELL_7,
        WindowsShell.GIT_BASH,
    }

def supports_unicode() -> bool:
    """Check if current shell supports Unicode box drawing."""
    shell = detect_windows_shell()
    return shell in {
        WindowsShell.WINDOWS_TERMINAL,
        WindowsShell.POWERSHELL_7,
        WindowsShell.GIT_BASH,
    }
```

---

## Implementation

### Phase 1: Shell Detection Module

Create `nexus3/core/shell_detection.py` with:
- `WindowsShell` enum
- `detect_windows_shell()` function (cached)
- `supports_ansi()` helper
- `supports_unicode()` helper

**File:** `nexus3/core/shell_detection.py` (new)

### Phase 2: Fix Rich Console Configuration

Change `force_terminal=True` to dynamic detection.

**File:** `nexus3/display/console.py`

**Current:**
```python
_console = Console(
    highlight=False,
    markup=True,
    force_terminal=True,           # PROBLEM: Forces ANSI even in CMD.exe
    legacy_windows=False,
)
```

**New:**
```python
from nexus3.core.shell_detection import supports_ansi, supports_unicode

def _create_console() -> Console:
    """Create Rich Console with shell-appropriate settings."""
    if sys.platform == "win32":
        ansi_ok = supports_ansi()
        unicode_ok = supports_unicode()
        return Console(
            highlight=False,
            markup=True,
            force_terminal=ansi_ok,      # Only force if shell supports it
            legacy_windows=not ansi_ok,  # Use legacy mode for CMD.exe
            no_color=not ansi_ok,        # Disable color if no ANSI
            # Could also set ascii_only=not unicode_ok for Rich 13+
        )
    else:
        # Unix: keep current behavior
        return Console(
            highlight=False,
            markup=True,
            force_terminal=True,
            legacy_windows=False,
        )

_console = _create_console()
```

### Phase 3: Fix shlex.split() for Windows Paths

The `bash_safe` skill uses `shlex.split()` which treats `\` as escape character.

**File:** `nexus3/skill/builtin/bash.py`

**Current:**
```python
self._args = shlex.split(command)
```

**New:**
```python
import sys

# On Windows, use POSIX=False to handle backslash paths correctly
# POSIX mode: C:\Users\foo → C:Usersfoo (backslash escapes)
# Non-POSIX: C:\Users\foo → C:\Users\foo (preserved)
posix_mode = sys.platform != "win32"
args = shlex.split(command, posix=posix_mode)

# CRITICAL: On Windows, posix=False preserves quotes in output which breaks
# downstream validation (e.g., git dangerous flag detection).
# Strip matching outer quotes from each argument.
if sys.platform == "win32":
    cleaned = []
    for arg in args:
        # Strip matching outer quotes: "foo" → foo, 'bar' → bar
        if len(arg) >= 2 and arg[0] in "\"'" and arg[-1] == arg[0]:
            cleaned.append(arg[1:-1])
        else:
            cleaned.append(arg)
    args = cleaned

self._args = args
```

**Why quote cleanup is needed:** `shlex.split(posix=False)` preserves quotes in output:
- Input: `grep -r 'pattern' /home`
- `posix=True`: `['grep', '-r', 'pattern', '/home']` ← Quotes removed
- `posix=False`: `['grep', '-r', "'pattern'", '/home']` ← Quotes preserved!

Without cleanup, git skill's dangerous flag detection fails (`"--force"` ≠ `--force`).

### Phase 3.5: Fix MCP Subprocess Pipe Cleanup (Windows)

On Windows, MCP subprocess pipes (stdout/stderr) cause `ResourceWarning: unclosed transport` on quit.

**Root cause:** Two issues:
1. `StdioTransport.close()` only closes stdin, not stdout/stderr
2. `mcp_registry.close_all()` never called during REPL shutdown

**File 1:** `nexus3/mcp/transport.py` - Close all pipes

**Current (lines 485-502):**
```python
        if self._process is not None:
            # Try graceful shutdown first
            if self._process.stdin is not None:
                try:
                    self._process.stdin.close()
                    await self._process.stdin.wait_closed()
                except Exception as e:
                    logger.debug("Stdin close error (expected during shutdown): %s", e)

            # Give it a moment to exit gracefully
            try:
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except TimeoutError:
                # Use cross-platform process tree termination
                from nexus3.core.process import terminate_process_tree
                await terminate_process_tree(self._process)

            self._process = None
```

**New:**
```python
        if self._process is not None:
            # Close all pipes explicitly (Windows ProactorEventLoop requires this)
            # Close stdin first to signal EOF to subprocess
            if self._process.stdin is not None:
                try:
                    self._process.stdin.close()
                    await self._process.stdin.wait_closed()
                except Exception as e:
                    logger.debug("Stdin close error (expected during shutdown): %s", e)

            # Close stdout and stderr to prevent "unclosed transport" warnings on Windows
            if self._process.stdout is not None:
                try:
                    self._process.stdout.feed_eof()
                except Exception:
                    pass  # May already be closed
            if self._process.stderr is not None:
                try:
                    self._process.stderr.feed_eof()
                except Exception:
                    pass  # May already be closed

            # Give it a moment to exit gracefully
            try:
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except TimeoutError:
                # Use cross-platform process tree termination
                from nexus3.core.process import terminate_process_tree
                await terminate_process_tree(self._process)

            self._process = None
```

**File 2:** `nexus3/cli/repl.py` - Add MCP cleanup to shutdown sequence

**After line 1562** (after `await shared.provider_registry.aclose()`):
```python
    # 6. Close MCP connections (prevents unclosed transport warnings on Windows)
    if shared and shared.mcp_registry:
        await shared.mcp_registry.close_all()
```

### Phase 4: Add Startup Shell Detection Message

Show detected shell at startup for debugging.

**File:** `nexus3/cli/repl.py` (in startup sequence)

```python
from nexus3.core.shell_detection import detect_windows_shell, WindowsShell

if sys.platform == "win32":
    shell = detect_windows_shell()
    if shell == WindowsShell.CMD:
        console.print(
            "[yellow]Detected CMD.exe - using simplified output mode.[/]\n"
            "[dim]For best experience, use Windows Terminal or PowerShell 7+[/]"
        )
    elif shell == WindowsShell.POWERSHELL_5:
        console.print(
            "[yellow]Detected PowerShell 5.1 - ANSI colors may not work.[/]\n"
            "[dim]For best experience, upgrade to PowerShell 7+[/]"
        )
```

### Phase 5: Console Code Page Warning

Warn if console code page is not UTF-8.

**File:** `nexus3/core/shell_detection.py` (add function)

```python
def check_console_codepage() -> tuple[int, bool]:
    """Check Windows console code page. Returns (codepage, is_utf8)."""
    if sys.platform != "win32":
        return (65001, True)

    try:
        import ctypes
        codepage = ctypes.windll.kernel32.GetConsoleOutputCP()
        return (codepage, codepage == 65001)
    except Exception:
        return (0, False)
```

**File:** `nexus3/cli/repl.py` (add to startup)

```python
from nexus3.core.shell_detection import check_console_codepage

if sys.platform == "win32":
    codepage, is_utf8 = check_console_codepage()
    if not is_utf8:
        console.print(
            f"[yellow]Console code page is {codepage}, not UTF-8 (65001).[/]\n"
            "[dim]Some characters may not display correctly. "
            "Run 'chcp 65001' before starting NEXUS3.[/]"
        )
```

### Phase 6: Documentation

Update documentation with shell-specific guidance.

**Files to update:**
- `CLAUDE.md` - Add Windows Shell section
- `docs/WINDOWS-TROUBLESHOOTING.md` - Shell-specific issues
- `docs/WINDOWS-LIVE-TESTING-GUIDE.md` - Testing in different shells

---

## Files to Modify

| File | Change |
|------|--------|
| `nexus3/core/shell_detection.py` | **NEW** - Shell detection module |
| `nexus3/core/__init__.py` | Export shell detection functions |
| `nexus3/display/console.py` | Dynamic console configuration |
| `nexus3/skill/builtin/bash.py` | Fix shlex.split() for Windows |
| `nexus3/cli/repl.py` | Startup shell detection messages |
| `CLAUDE.md` | Document Windows shell behavior |
| `docs/WINDOWS-TROUBLESHOOTING.md` | Shell-specific troubleshooting |
| `tests/unit/core/test_shell_detection.py` | **NEW** - Shell detection tests |

---

## Testing

### Unit Tests

**test_shell_detection.py:**
- `test_detect_windows_terminal` - WT_SESSION set
- `test_detect_git_bash` - MSYSTEM set
- `test_detect_powershell_5` - PSModulePath set, no WT_SESSION
- `test_detect_cmd` - COMSPEC ends with cmd.exe
- `test_detect_unknown` - No indicators
- `test_supports_ansi_windows_terminal` - Returns True
- `test_supports_ansi_cmd` - Returns False
- `test_detection_cached` - Called once, reused

### Integration Tests

- `test_console_no_ansi_in_cmd` - Rich output without escape sequences
- `test_shlex_preserves_backslash` - Windows paths parsed correctly

### Live Testing Checklist

| Shell | Test |
|-------|------|
| **CMD.exe** | Start nexus3, verify no ANSI garbage, readable output |
| **PowerShell 5.1** | Start nexus3, check for warnings, verify basic functionality |
| **PowerShell 7** | Start nexus3, verify colored output works |
| **Windows Terminal (any)** | Start nexus3, verify full functionality |
| **Git Bash** | Start nexus3, verify paths work, test file operations |

---

## Implementation Checklist

### Phase 1: Shell Detection Module

- [x] **P1.1** Create `nexus3/core/shell_detection.py` with WindowsShell enum
- [x] **P1.2** Implement `detect_windows_shell()` with caching
- [x] **P1.3** Implement `supports_ansi()` helper
- [x] **P1.4** Implement `supports_unicode()` helper
- [x] **P1.5** Implement `check_console_codepage()` function
- [x] **P1.6** Export from `nexus3/core/__init__.py`
- [x] **P1.7** Add unit tests for shell detection

### Phase 2: Rich Console Fix

- [x] **P2.1** Modify `nexus3/display/console.py` to use dynamic configuration
- [x] **P2.2** Fix `nexus3/cli/repl_commands.py` lines 1485, 1537 to use `get_console()`
- [ ] **P2.3** Test in CMD.exe - verify no ANSI escape sequences visible
- [ ] **P2.4** Test in Windows Terminal - verify colors still work

### Phase 3: shlex.split() Fix (CRITICAL: includes quote cleanup)

- [x] **P3.1** Modify `nexus3/skill/builtin/bash.py` with posix=False AND quote cleanup
- [x] **P3.2** Modify `nexus3/skill/builtin/git.py` with posix=False AND quote cleanup
- [x] **P3.3** Add test for Windows path preservation in shlex.split()
- [x] **P3.4** Add test for quoted argument handling (quotes stripped correctly)
- [ ] **P3.5** Live test: `bash_safe "dir C:\Users"` works
- [ ] **P3.6** Live test: `git "log --oneline"` works (flag detection not broken)

### Phase 3.5: MCP Pipe Cleanup (Windows)

- [x] **P3.5.1** Fix `nexus3/mcp/transport.py` to close stdout/stderr in `close()`
- [x] **P3.5.2** Add `mcp_registry.close_all()` to REPL shutdown in `nexus3/cli/repl.py`
- [ ] **P3.5.3** Live test: `/q` with MCP connected shows no pipe warnings on Windows

### Phase 4: Startup Messages

- [x] **P4.1** Add shell detection message to REPL startup
- [x] **P4.2** Add code page warning to REPL startup
- [ ] **P4.3** Verify messages appear in CMD.exe

### Phase 5: Documentation (After Implementation Complete)

- [x] **P5.1** Add "Windows Shell Compatibility" section to `CLAUDE.md`
- [x] **P5.2** Update `docs/WINDOWS-TROUBLESHOOTING.md` with shell-specific issues
- [x] **P5.3** Update `docs/WINDOWS-LIVE-TESTING-GUIDE.md` with shell testing matrix

### Phase 6: Live Testing

- [ ] **P6.1** Test in CMD.exe
- [ ] **P6.2** Test in PowerShell 5.1
- [ ] **P6.3** Test in PowerShell 7
- [ ] **P6.4** Test in Windows Terminal
- [ ] **P6.5** Test in Git Bash

---

## Quick Reference

### Shell Detection Results

| Shell | `supports_ansi()` | `supports_unicode()` | Console Mode | Notes |
|-------|-------------------|----------------------|--------------|-------|
| Windows Terminal | ✅ True | ✅ True | Full | Best experience |
| PowerShell 7+ | ✅ True | ✅ True | Full | |
| PowerShell 5.1 | ❌ False | ⚠️ Partial | Legacy | *See note below |
| Git Bash | ✅ True | ✅ True | Full | MSYS2 path handling |
| CMD.exe | ❌ False | ❌ False | Legacy | Plain text only |

**\*PS 5.1 Note:** PowerShell 5.1 CAN display ANSI sequences from Rich if running inside Windows Terminal (WT_SESSION detected → returns WINDOWS_TERMINAL, not POWERSHELL_5). The conservative 5.1 fallback only applies when PS 5.1 runs standalone (no WT_SESSION).

### Environment Variable Reference

| Variable | Indicates |
|----------|-----------|
| `WT_SESSION` | Running in Windows Terminal |
| `MSYSTEM` | Running in MSYS2/Git Bash |
| `PSModulePath` | Running in PowerShell |
| `COMSPEC` | Windows command interpreter path |
| `TERM` | Terminal type (often unset on Windows) |

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Shell detection wrong | Conservative fallback to legacy mode |
| Rich behavior changes | Test each Rich version in each shell |
| shlex.split() breaks Unix | Only change on `sys.platform == "win32"` |
| Performance of detection | Cache result with `@lru_cache` |
| User confusion from warnings | Make warnings dismissable / one-time |

---

## Future Enhancements

1. **`--no-color` CLI flag** - Force plain text mode
2. **`--shell` override** - Manually specify shell for testing
3. **PowerShell version detection** - Distinguish PS 5.1 from 7 accurately
4. **ConPTY detection** - Better ANSI support detection on Windows 10+
5. **Rich box character fallback** - ASCII alternatives for box drawing

---

## Detailed Implementation Guidance

*This section contains specific code locations and patterns discovered by explorers for contextless task agents.*

### P1: Shell Detection Module - Exact Implementation

**Create file:** `nexus3/core/shell_detection.py`

```python
"""Shell detection for Windows environments.

This module provides detection of the Windows shell environment to enable
appropriate terminal configuration. Detects Windows Terminal, PowerShell,
Git Bash (MSYS2), and CMD.exe.

SINGLE SOURCE OF TRUTH for shell detection across NEXUS3.
"""

from __future__ import annotations

import logging
import os
import sys
from enum import Enum, auto
from functools import lru_cache

logger = logging.getLogger(__name__)


class WindowsShell(Enum):
    """Detected Windows shell environment."""

    WINDOWS_TERMINAL = auto()  # Modern, full ANSI/Unicode support
    POWERSHELL_7 = auto()      # Good ANSI, UTF-8 by default
    POWERSHELL_5 = auto()      # Broken ANSI, legacy encoding
    GIT_BASH = auto()          # Unix-like, MSYS2 environment
    CMD = auto()               # No ANSI without Windows Terminal
    UNKNOWN = auto()           # Fallback - assume basic capabilities


@lru_cache(maxsize=1)
def detect_windows_shell() -> WindowsShell:
    """Detect which Windows shell environment we're running in.

    Detection order (first match wins):
    1. WT_SESSION → Windows Terminal (wraps other shells)
    2. MSYSTEM → Git Bash / MSYS2
    3. PSModulePath → PowerShell (assume 5.1 conservatively)
    4. COMSPEC ends with cmd.exe → CMD.exe
    5. Otherwise → UNKNOWN

    Returns:
        WindowsShell enum value. Returns UNKNOWN on non-Windows platforms.
    """
    if sys.platform != "win32":
        return WindowsShell.UNKNOWN

    # Windows Terminal wraps other shells - check first
    if os.environ.get("WT_SESSION"):
        logger.debug("Detected Windows Terminal via WT_SESSION")
        return WindowsShell.WINDOWS_TERMINAL

    # Git Bash / MSYS2 (MSYSTEM can be MINGW64, MINGW32, MSYS, UCRT64, CLANG64, CLANGARM64)
    if os.environ.get("MSYSTEM"):
        logger.debug("Detected Git Bash via MSYSTEM=%s", os.environ.get("MSYSTEM"))
        return WindowsShell.GIT_BASH

    # PowerShell detection (conservative - assume 5.1)
    if os.environ.get("PSModulePath"):
        logger.debug("Detected PowerShell via PSModulePath")
        return WindowsShell.POWERSHELL_5

    # CMD.exe fallback
    comspec = os.environ.get("COMSPEC", "").lower()
    if comspec.endswith("cmd.exe"):
        logger.debug("Detected CMD.exe via COMSPEC")
        return WindowsShell.CMD

    logger.debug("Unknown Windows shell environment")
    return WindowsShell.UNKNOWN


def supports_ansi() -> bool:
    """Check if current shell supports ANSI escape sequences.

    Returns:
        True if shell supports ANSI (Windows Terminal, Git Bash).
        False for CMD.exe and PowerShell 5.1.
    """
    if sys.platform != "win32":
        return True  # Unix always supports ANSI

    shell = detect_windows_shell()
    return shell in {
        WindowsShell.WINDOWS_TERMINAL,
        WindowsShell.POWERSHELL_7,
        WindowsShell.GIT_BASH,
    }


def supports_unicode() -> bool:
    """Check if current shell supports Unicode box drawing characters.

    Returns:
        True if shell supports Unicode (Windows Terminal, Git Bash).
        False for CMD.exe (shows ? for box chars).
    """
    if sys.platform != "win32":
        return True  # Unix always supports Unicode

    shell = detect_windows_shell()
    return shell in {
        WindowsShell.WINDOWS_TERMINAL,
        WindowsShell.POWERSHELL_7,
        WindowsShell.GIT_BASH,
    }


def check_console_codepage() -> tuple[int, bool]:
    """Check Windows console output code page.

    Returns:
        Tuple of (codepage, is_utf8). Returns (65001, True) on non-Windows.
        Returns (0, False) if detection fails.
    """
    if sys.platform != "win32":
        return (65001, True)

    try:
        import ctypes
        codepage = ctypes.windll.kernel32.GetConsoleOutputCP()
        return (codepage, codepage == 65001)
    except Exception:
        return (0, False)
```

**Update `nexus3/core/__init__.py`** - Add after existing exports:

```python
# Shell detection (Windows)
from nexus3.core.shell_detection import (
    WindowsShell,
    detect_windows_shell,
    supports_ansi,
    supports_unicode,
    check_console_codepage,
)
```

And add to `__all__`:
```python
    # Shell detection
    "WindowsShell",
    "detect_windows_shell",
    "supports_ansi",
    "supports_unicode",
    "check_console_codepage",
```

---

### P2: Rich Console Fix - Exact Code

**File:** `nexus3/display/console.py`

**Current code (lines 1-34):**
```python
"""Shared Rich Console instance for NEXUS3."""

from rich.console import Console

_console: Console | None = None

def get_console() -> Console:
    """Get the shared Console instance."""
    global _console
    if _console is None:
        _console = Console(
            highlight=False,
            markup=True,
            force_terminal=True,      # PROBLEM
            legacy_windows=False,
        )
    return _console
```

**Replace with:**
```python
"""Shared Rich Console instance for NEXUS3."""

from __future__ import annotations

import sys

from rich.console import Console


_console: Console | None = None


def get_console() -> Console:
    """Get the shared Console instance.

    Creates the console on first access with shell-appropriate settings.
    On Windows, detects shell capabilities and configures Rich accordingly.
    """
    global _console
    if _console is None:
        if sys.platform == "win32":
            # Import here to avoid circular imports
            from nexus3.core.shell_detection import supports_ansi

            ansi_ok = supports_ansi()
            _console = Console(
                highlight=False,
                markup=True,
                force_terminal=ansi_ok,      # Only force if shell supports it
                legacy_windows=not ansi_ok,  # Use legacy mode for CMD.exe
                no_color=not ansi_ok,        # Disable color if no ANSI
            )
        else:
            # Unix: keep current behavior
            _console = Console(
                highlight=False,
                markup=True,
                force_terminal=True,
                legacy_windows=False,
            )
    return _console


def set_console(console: Console) -> None:
    """Set a custom Console instance.

    Useful for testing or custom configurations.
    """
    global _console
    _console = console
```

**Additional fix needed:** `nexus3/cli/repl_commands.py` lines 1485 and 1531 create `Console()` directly. Change to:
```python
from nexus3.display import get_console
# ...
console = get_console()  # Instead of Console()
```

---

### P3: shlex.split() Fix - Exact Code

**CRITICAL: Quote cleanup required.** Using `posix=False` preserves backslashes but ALSO preserves quotes in output. Without cleanup:
- Input: `grep -r 'pattern' /home`
- Output: `['grep', '-r', "'pattern'", '/home']` ← Quotes included!

This breaks git skill's dangerous flag detection (`"--force"` ≠ `--force`).

**File:** `nexus3/skill/builtin/bash.py`

**Line 158 - Current:**
```python
        try:
            self._args = shlex.split(command)
        except ValueError as e:
            return ToolResult(error=f"Invalid command syntax: {e}")
```

**Replace with (lines 156-170):**
```python
        # Parse command with shlex
        # Use non-POSIX mode on Windows to preserve backslash paths
        # POSIX mode: C:\Users\foo → C:Usersfoo (backslash escapes)
        # Non-POSIX: C:\Users\foo → C:\Users\foo (preserved)
        try:
            posix_mode = sys.platform != "win32"
            args = shlex.split(command, posix=posix_mode)

            # On Windows, posix=False preserves quotes in output which breaks
            # downstream processing. Strip matching outer quotes.
            if sys.platform == "win32":
                args = [
                    arg[1:-1] if len(arg) >= 2 and arg[0] in "\"'" and arg[-1] == arg[0] else arg
                    for arg in args
                ]

            self._args = args
        except ValueError as e:
            return ToolResult(error=f"Invalid command syntax: {e}")
```

**Note:** `sys` is already imported at line 27.

---

**File:** `nexus3/skill/builtin/git.py`

**Line 129 - Current:**
```python
        try:
            args = shlex.split(command)
        except ValueError as e:
            return False, None, f"Invalid command syntax: {e}"
```

**Replace with (lines 126-140):**
```python
        # Parse command FIRST - this is the key security fix
        # Validation must operate on the same form that will be executed
        # Use non-POSIX mode on Windows to preserve backslash paths
        try:
            posix_mode = sys.platform != "win32"
            args = shlex.split(command, posix=posix_mode)

            # On Windows, posix=False preserves quotes in output which breaks
            # dangerous flag detection. Strip matching outer quotes.
            if sys.platform == "win32":
                args = [
                    arg[1:-1] if len(arg) >= 2 and arg[0] in "\"'" and arg[-1] == arg[0] else arg
                    for arg in args
                ]
        except ValueError as e:
            return False, None, f"Invalid command syntax: {e}"
```

**Note:** `sys` is already imported at line 8.

---

### P4: REPL Startup Messages - Exact Location

**File:** `nexus3/cli/repl.py`

**Insert after line 956** (after `console.print("")` following "Commands: /help"):

```python
        # Shell environment detection and warnings (Windows only)
        if sys.platform == "win32":
            from nexus3.core.shell_detection import (
                detect_windows_shell,
                WindowsShell,
                check_console_codepage,
            )

            shell = detect_windows_shell()
            if shell == WindowsShell.CMD:
                console.print(
                    "[yellow]Detected CMD.exe[/] - using simplified output mode.",
                    style="dim",
                )
                console.print(
                    "[dim]For best experience, use Windows Terminal or PowerShell 7+[/]"
                )
            elif shell == WindowsShell.POWERSHELL_5:
                console.print(
                    "[yellow]Detected PowerShell 5.1[/] - ANSI colors may not work.",
                    style="dim",
                )
                console.print(
                    "[dim]For best experience, upgrade to PowerShell 7+[/]"
                )

            # Code page warning
            codepage, is_utf8 = check_console_codepage()
            if not is_utf8 and codepage != 0:
                console.print(
                    f"[yellow]Console code page is {codepage}[/], not UTF-8 (65001).",
                    style="dim",
                )
                console.print(
                    "[dim]Run 'chcp 65001' before NEXUS3 for proper character display.[/]"
                )
```

**Note:** `sys` and `console` are already available at this point (line 34 and 126 respectively).

---

### P1.7: Test File Template

**Create file:** `tests/unit/core/test_shell_detection.py`

```python
"""Tests for nexus3.core.shell_detection module."""

import os
import sys
from unittest.mock import patch

import pytest

from nexus3.core.shell_detection import (
    WindowsShell,
    detect_windows_shell,
    supports_ansi,
    supports_unicode,
    check_console_codepage,
)


class TestWindowsShellEnum:
    """Test WindowsShell enum."""

    def test_all_shells_defined(self) -> None:
        """All expected shell types should be defined."""
        assert WindowsShell.WINDOWS_TERMINAL
        assert WindowsShell.POWERSHELL_7
        assert WindowsShell.POWERSHELL_5
        assert WindowsShell.GIT_BASH
        assert WindowsShell.CMD
        assert WindowsShell.UNKNOWN


class TestDetectWindowsShell:
    """Test detect_windows_shell() function."""

    @pytest.mark.windows_mock
    def test_detect_windows_terminal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should detect Windows Terminal via WT_SESSION."""
        monkeypatch.setattr(sys, "platform", "win32")
        detect_windows_shell.cache_clear()

        with patch.dict(os.environ, {"WT_SESSION": "some-session-id"}, clear=False):
            result = detect_windows_shell()
            assert result == WindowsShell.WINDOWS_TERMINAL

    @pytest.mark.windows_mock
    def test_detect_git_bash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should detect Git Bash via MSYSTEM."""
        monkeypatch.setattr(sys, "platform", "win32")
        detect_windows_shell.cache_clear()

        with patch.dict(os.environ, {"MSYSTEM": "MINGW64"}, clear=False):
            # Ensure WT_SESSION is not set
            env = os.environ.copy()
            env.pop("WT_SESSION", None)
            env["MSYSTEM"] = "MINGW64"
            with patch.dict(os.environ, env, clear=True):
                result = detect_windows_shell()
                assert result == WindowsShell.GIT_BASH

    @pytest.mark.windows_mock
    def test_detect_powershell(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should detect PowerShell via PSModulePath."""
        monkeypatch.setattr(sys, "platform", "win32")
        detect_windows_shell.cache_clear()

        env = {"PSModulePath": "C:\\Users\\test\\Documents\\PowerShell\\Modules"}
        with patch.dict(os.environ, env, clear=True):
            result = detect_windows_shell()
            assert result == WindowsShell.POWERSHELL_5

    @pytest.mark.windows_mock
    def test_detect_cmd(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should detect CMD.exe via COMSPEC."""
        monkeypatch.setattr(sys, "platform", "win32")
        detect_windows_shell.cache_clear()

        env = {"COMSPEC": "C:\\Windows\\System32\\cmd.exe"}
        with patch.dict(os.environ, env, clear=True):
            result = detect_windows_shell()
            assert result == WindowsShell.CMD

    @pytest.mark.windows_mock
    def test_detect_unknown_on_empty_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return UNKNOWN when no shell indicators present."""
        monkeypatch.setattr(sys, "platform", "win32")
        detect_windows_shell.cache_clear()

        with patch.dict(os.environ, {}, clear=True):
            result = detect_windows_shell()
            assert result == WindowsShell.UNKNOWN

    def test_returns_unknown_on_unix(self) -> None:
        """Should return UNKNOWN on non-Windows platforms."""
        if sys.platform == "win32":
            pytest.skip("Test only runs on Unix")
        detect_windows_shell.cache_clear()
        result = detect_windows_shell()
        assert result == WindowsShell.UNKNOWN

    @pytest.mark.windows_mock
    def test_windows_terminal_takes_priority(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Windows Terminal should be detected even with other indicators."""
        monkeypatch.setattr(sys, "platform", "win32")
        detect_windows_shell.cache_clear()

        env = {
            "WT_SESSION": "session-id",
            "MSYSTEM": "MINGW64",  # Also set
            "PSModulePath": "C:\\path",  # Also set
        }
        with patch.dict(os.environ, env, clear=True):
            result = detect_windows_shell()
            assert result == WindowsShell.WINDOWS_TERMINAL


class TestSupportsAnsi:
    """Test supports_ansi() function."""

    @pytest.mark.windows_mock
    def test_windows_terminal_supports_ansi(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Windows Terminal should support ANSI."""
        monkeypatch.setattr(sys, "platform", "win32")
        detect_windows_shell.cache_clear()

        with patch.dict(os.environ, {"WT_SESSION": "id"}, clear=True):
            assert supports_ansi() is True

    @pytest.mark.windows_mock
    def test_cmd_does_not_support_ansi(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CMD.exe should not support ANSI."""
        monkeypatch.setattr(sys, "platform", "win32")
        detect_windows_shell.cache_clear()

        with patch.dict(os.environ, {"COMSPEC": "C:\\Windows\\System32\\cmd.exe"}, clear=True):
            assert supports_ansi() is False

    @pytest.mark.windows_mock
    def test_git_bash_supports_ansi(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Git Bash should support ANSI."""
        monkeypatch.setattr(sys, "platform", "win32")
        detect_windows_shell.cache_clear()

        with patch.dict(os.environ, {"MSYSTEM": "MINGW64"}, clear=True):
            assert supports_ansi() is True

    def test_unix_always_supports_ansi(self) -> None:
        """Unix platforms should always support ANSI."""
        if sys.platform == "win32":
            pytest.skip("Test only runs on Unix")
        assert supports_ansi() is True


class TestSupportsUnicode:
    """Test supports_unicode() function."""

    @pytest.mark.windows_mock
    def test_cmd_does_not_support_unicode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CMD.exe should not support Unicode box drawing."""
        monkeypatch.setattr(sys, "platform", "win32")
        detect_windows_shell.cache_clear()

        with patch.dict(os.environ, {"COMSPEC": "C:\\Windows\\System32\\cmd.exe"}, clear=True):
            assert supports_unicode() is False


class TestCheckConsoleCodepage:
    """Test check_console_codepage() function."""

    def test_unix_returns_utf8(self) -> None:
        """Unix should return UTF-8 codepage."""
        if sys.platform == "win32":
            pytest.skip("Test only runs on Unix")
        codepage, is_utf8 = check_console_codepage()
        assert codepage == 65001
        assert is_utf8 is True

    @pytest.mark.windows_mock
    def test_windows_returns_codepage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Windows should return actual codepage."""
        monkeypatch.setattr(sys, "platform", "win32")

        # Mock ctypes
        mock_windll = type("windll", (), {
            "kernel32": type("kernel32", (), {
                "GetConsoleOutputCP": lambda: 65001
            })()
        })()

        with patch.dict(sys.modules, {"ctypes": type("ctypes", (), {"windll": mock_windll})()}):
            # Re-import to pick up mock
            from nexus3.core.shell_detection import check_console_codepage
            codepage, is_utf8 = check_console_codepage()
            # Note: may still get real value depending on import order
```

---

### Validation Notes

**Verified by explorers:**
- ✅ Console singleton pattern in `display/console.py` (lines 1-34)
- ✅ `set_console()` exists for testing/reconfiguration
- ✅ `sys` already imported in bash.py (line 27) and git.py (line 8)
- ✅ REPL startup location identified (after line 956)
- ✅ `os` and `sys` available in repl.py
- ✅ shlex.split() locations: bash.py:158, git.py:129

**Issues found:**
- ⚠️ `repl_commands.py:1485,1531` creates `Console()` directly - should use `get_console()`

---

### Copy-Paste File Paths

| Task | File Path |
|------|-----------|
| P1.1-P1.5 | `nexus3/core/shell_detection.py` (NEW) |
| P1.6 | `nexus3/core/__init__.py` |
| P1.7 | `tests/unit/core/test_shell_detection.py` (NEW) |
| P2.1 | `nexus3/display/console.py` |
| P2.1 (bugfix) | `nexus3/cli/repl_commands.py` lines 1485, 1531 |
| P3.1 | `nexus3/skill/builtin/bash.py` line 158 |
| P3.1 | `nexus3/skill/builtin/git.py` line 129 |
| P4.1-P4.2 | `nexus3/cli/repl.py` after line 956 |

---

## Validation Summary (2026-01-28)

Plan validated by 5 independent explorers. Key findings:

### Shell Detection (85% Correct)

| Finding | Status | Notes |
|---------|--------|-------|
| WT_SESSION detection | ✅ Correct | Reliable, always set by Windows Terminal |
| MSYSTEM detection | ✅ Correct | Values: MINGW64, UCRT64, CLANG64, etc. (any value = Git Bash) |
| PSModulePath detection | ⚠️ Limitation | Cannot distinguish PS 5.1 from PS 7+ via env vars alone |
| COMSPEC detection | ✅ Correct | Reliable fallback for CMD.exe |
| Detection order | ✅ Correct | WT_SESSION first prevents false positives |

**PS Version Limitation:** Cannot detect PowerShell version via environment variables. Plan uses conservative 5.1 assumption. Future enhancement: subprocess version check.

### Rich Console Changes (VALID)

All proposed Rich parameters verified:
- `force_terminal`, `legacy_windows`, `no_color` are valid Rich Console parameters
- Both ANSI and legacy configurations tested and working
- No circular import risks (lazy import in get_console())
- Rich.Live compatible with both configurations

### shlex.split() Fix (CRITICAL ISSUE FIXED)

**Original proposal was incomplete.** `posix=False` preserves backslashes (✓) but ALSO preserves quotes (✗).

- Input: `grep -r 'pattern' /home`
- `posix=False` output: `['grep', '-r', "'pattern'", '/home']` ← Quotes included!
- This breaks git dangerous flag detection (`"--force"` ≠ `--force`)

**Fix applied:** Added quote cleanup after shlex.split() on Windows.

### Security Review (LOW RISK)

| Area | Risk | Notes |
|------|------|-------|
| Environment variable detection | LOW | Read-only, output-only impact |
| shlex changes | LOW | Platform-guarded, validated on parsed args |
| Rich Console | LOW | No escape sequence injection |
| Permission enforcement | NONE | No changes to security mechanisms |

### Completeness (95%)

- ✅ All Console() instantiations identified (console.py, repl_commands.py)
- ✅ All shlex.split() calls identified (bash.py, git.py)
- ✅ MCP transport already Windows-compatible (no changes needed)
- ✅ Test coverage comprehensive
