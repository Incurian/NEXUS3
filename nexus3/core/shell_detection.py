"""Shell detection for Windows environments.

This module provides detection of the Windows shell environment to enable
appropriate terminal configuration. Detects Windows Terminal, PowerShell,
Git Bash (MSYS2), and CMD.exe.

SINGLE SOURCE OF TRUTH for shell detection across NEXUS3.
"""

from __future__ import annotations

import logging
import ntpath
import os
import shutil
import sys
from enum import Enum, auto
from functools import lru_cache

logger = logging.getLogger(__name__)


def _normalize_windows_path(path: str) -> str:
    """Normalize a Windows path for case-insensitive comparisons."""
    return ntpath.normcase(ntpath.normpath(path))


_WSL_BASH_SHIM_SUFFIXES = (
    _normalize_windows_path(r"\Windows\System32\bash.exe"),
    _normalize_windows_path(r"\AppData\Local\Microsoft\WindowsApps\bash.exe"),
)


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
    if os.environ.get("WT_SESSION"):  # type: ignore[unreachable]
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


def is_windows_wsl_bash_shim(path: str) -> bool:
    """Return True when a resolved bash path is a known WSL launcher shim."""
    normalized = _normalize_windows_path(path)
    return any(normalized.endswith(suffix) for suffix in _WSL_BASH_SHIM_SUFFIXES)


def _iter_path_bash_candidates(path_value: str | None) -> list[str]:
    """Enumerate concrete bash executables from a PATH string."""
    if not path_value:
        return []

    separator = ";" if sys.platform == "win32" else os.pathsep
    seen: set[str] = set()
    candidates: list[str] = []
    for entry in path_value.split(separator):
        if not entry:
            continue
        for name in ("bash.exe", "bash"):
            candidate = ntpath.join(entry, name)
            normalized = _normalize_windows_path(candidate)
            if normalized in seen:
                continue
            seen.add(normalized)
            if os.path.isfile(candidate):
                candidates.append(candidate)
    return candidates


def resolve_git_bash_executable(path_value: str | None = None) -> str | None:
    """Resolve a safe Git-for-Windows bash executable on Windows.

    The returned path must be a concrete executable path, not a bare `bash`
    command name, and must not be one of the WSL launcher shims.
    """
    if sys.platform != "win32":
        return None

    for candidate in _iter_path_bash_candidates(path_value):
        if not is_windows_wsl_bash_shim(candidate):
            return candidate

    install_roots: list[str] = []
    for env_var, suffix in (
        ("ProgramFiles", "Git"),
        ("ProgramFiles(x86)", "Git"),
        ("LocalAppData", ntpath.join("Programs", "Git")),
    ):
        base = os.environ.get(env_var)
        if base:
            install_roots.append(ntpath.join(base, suffix))

    for root in install_roots:
        for relative_path in (
            ntpath.join("usr", "bin", "bash.exe"),
            ntpath.join("bin", "bash.exe"),
        ):
            candidate = ntpath.join(root, relative_path)
            if os.path.isfile(candidate):
                return candidate

    resolved = shutil.which("bash", path=path_value)
    if resolved and not is_windows_wsl_bash_shim(resolved):
        return resolved
    return None


def supports_ansi() -> bool:
    """Check if current shell supports ANSI escape sequences.

    Returns:
        True if shell supports ANSI (Windows Terminal, Git Bash).
        False for CMD.exe and PowerShell 5.1.
    """
    if sys.platform != "win32":
        return True  # Unix always supports ANSI

    shell = detect_windows_shell()  # type: ignore[unreachable]
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

    shell = detect_windows_shell()  # type: ignore[unreachable]
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

    try:  # type: ignore[unreachable]
        import ctypes
        codepage = ctypes.windll.kernel32.GetConsoleOutputCP()
        return (codepage, codepage == 65001)
    except Exception:
        return (0, False)
