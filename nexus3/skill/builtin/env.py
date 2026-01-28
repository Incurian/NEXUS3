"""Secure environment handling for subprocess execution.

This module provides sanitized environment variables for subprocesses,
preventing secret leakage from the parent process environment.
"""

import os
import sys
from collections.abc import Mapping

# Environment variables safe to pass to subprocesses
# These are essential for process execution but should not contain secrets
SAFE_ENV_VARS: frozenset[str] = frozenset({
    # Path and execution
    "PATH",
    "HOME",
    "USER",
    "SHELL",
    "PWD",

    # Locale settings
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LC_COLLATE",
    "LC_MESSAGES",
    "TZ",

    # Terminal settings
    "TERM",
    "COLORTERM",
    "COLUMNS",
    "LINES",

    # Temp directories
    "TMPDIR",
    "TMP",
    "TEMP",

    # Windows-specific (P3 Env Variable Unification)
    "USERPROFILE",    # Windows user home directory
    "APPDATA",        # Windows roaming app data
    "LOCALAPPDATA",   # Windows local app data
    "PATHEXT",        # Windows executable extensions (.exe, .cmd, .bat)
    "SYSTEMROOT",     # Windows system root (C:\Windows)
    "COMSPEC",        # Windows command interpreter (cmd.exe)
})

# Default PATH if none available (platform-aware)
if sys.platform == "win32":
    DEFAULT_PATH = r"C:\Windows\System32;C:\Windows;C:\Windows\System32\Wbem"
else:
    DEFAULT_PATH = "/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin"


def get_safe_env(cwd: str | None = None) -> dict[str, str]:
    """Get a sanitized environment for subprocess execution.

    Only passes through environment variables that are:
    - Essential for process execution (PATH, HOME, etc.)
    - Locale/terminal settings
    - Unlikely to contain secrets

    Explicitly blocks:
    - API keys (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.)
    - Tokens (GITHUB_TOKEN, AWS_*, etc.)
    - Database credentials
    - Any variable not in the safe list

    Args:
        cwd: Optional working directory to set as PWD.

    Returns:
        Dictionary of safe environment variables.
    """
    env: dict[str, str] = {}

    # Copy only safe variables that exist
    for var in SAFE_ENV_VARS:
        value = os.environ.get(var)
        if value is not None:
            env[var] = value

    # Override PWD if cwd specified
    if cwd is not None:
        env["PWD"] = cwd

    # Ensure PATH exists (critical for finding executables)
    if "PATH" not in env or not env["PATH"]:
        env["PATH"] = os.defpath or DEFAULT_PATH

    return env


def get_full_env(cwd: str | None = None) -> dict[str, str]:
    """Get the full environment (for trusted/opt-in scenarios).

    WARNING: This passes all environment variables including secrets.
    Only use this when explicitly requested by configuration for trusted
    workflows that require full environment access.

    Args:
        cwd: Optional working directory to set as PWD.

    Returns:
        Full copy of current environment.
    """
    env = dict(os.environ)
    if cwd is not None:
        env["PWD"] = cwd
    return env


def filter_env(
    base_env: Mapping[str, str],
    additional_vars: frozenset[str] | None = None,
    block_vars: frozenset[str] | None = None,
) -> dict[str, str]:
    """Filter environment with custom allow/block rules.

    Args:
        base_env: Base environment to filter.
        additional_vars: Additional variables to allow beyond SAFE_ENV_VARS.
        block_vars: Variables to explicitly block (takes precedence).

    Returns:
        Filtered environment dictionary.
    """
    allowed = SAFE_ENV_VARS | (additional_vars or frozenset())
    blocked = block_vars or frozenset()

    return {
        k: v
        for k, v in base_env.items()
        if k in allowed and k not in blocked
    }
