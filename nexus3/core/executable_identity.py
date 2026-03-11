"""Executable identity normalization for command-scoped execution allowances."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _normalize_identity(value: str) -> str:
    """Normalize an executable identity for stable session allowance keys."""
    normalized = os.path.normpath(value)
    if sys.platform == "win32":
        return os.path.normcase(normalized)
    return normalized


def _looks_like_path(program: str) -> bool:
    """Return True when a program value should be treated as a path."""
    if "/" in program or "\\" in program:
        return True
    if program.startswith((".", "~")):
        return True
    return len(program) >= 2 and program[1] == ":" and program[0].isalpha()


def resolve_executable_identity(
    program: str,
    cwd: Path | None = None,
    path_value: str | None = None,
) -> str:
    """Resolve a stable identity for an executable request.

    Resolution preference:
    1. Path-like program values resolve against the effective cwd when possible.
    2. Bare program names resolve through PATH when possible.
    3. Otherwise fall back to a normalized bare program string.
    """
    stripped = program.strip()
    if not stripped:
        raise ValueError("Program is required")

    if _looks_like_path(stripped):
        candidate = Path(os.path.expanduser(stripped))
        if not candidate.is_absolute() and cwd is not None:
            candidate = cwd / candidate
        try:
            return _normalize_identity(str(candidate.resolve(strict=False)))
        except OSError:
            return _normalize_identity(str(candidate))

    resolved = shutil.which(stripped, path=path_value or os.environ.get("PATH"))
    if resolved:
        return _normalize_identity(resolved)

    return _normalize_identity(stripped)
