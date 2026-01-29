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
