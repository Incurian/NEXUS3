"""Path normalization and validation utilities for cross-platform path handling."""

import os
import tempfile
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from nexus3.core.errors import PathSecurityError


class _DecisionReason(Enum):
    """Internal reasons for path decisions (used by shared kernel)."""

    ALLOWED_UNRESTRICTED = auto()
    ALLOWED_WITHIN_PATH = auto()
    DENIED_BLOCKED = auto()
    DENIED_OUTSIDE_ALLOWED = auto()
    DENIED_NO_ALLOWED_PATHS = auto()
    DENIED_RESOLUTION_FAILED = auto()


@dataclass(frozen=True)
class _PathDecisionInternal:
    """Internal path decision result (used by shared kernel).

    This is the shared result type used by both validate_path() and
    PathDecisionEngine.check_access(). It contains all information needed
    to either raise an exception or return a structured PathDecision.
    """

    allowed: bool
    resolved_path: Path | None
    reason: _DecisionReason
    detail: str
    original_path: str
    matched_rule: Path | None = None


def _decide_path(
    path: str | Path,
    allowed_paths: list[Path] | None = None,
    blocked_paths: list[Path] | None = None,
    cwd: Path | None = None,
) -> _PathDecisionInternal:
    """Shared kernel for path access decisions.

    This is the single source of truth for path validation logic.
    Both validate_path() and PathDecisionEngine.check_access() use this.

    Args:
        path: Path to validate (can be relative, contain symlinks, etc.)
        allowed_paths: If set, resolved path must be within one of these.
                       None = unrestricted (TRUSTED/YOLO mode).
                       Empty list [] = nothing allowed (always fails).
        blocked_paths: Paths always denied regardless of allowed_paths.
        cwd: Working directory for resolving relative paths (default: process cwd).

    Returns:
        _PathDecisionInternal with decision, reason, and resolved path.
    """
    original = str(path)

    # Handle empty/None input
    if not path:
        path = "."

    # Normalize and expand
    if isinstance(path, str):
        path = path.replace("\\", "/")
        path = Path(path)

    p = path.expanduser()

    # Resolve relative paths against cwd
    if cwd and not p.is_absolute():
        p = cwd / p

    # Try to resolve the path (follows symlinks)
    try:
        resolved = p.resolve()
    except (OSError, ValueError) as e:
        return _PathDecisionInternal(
            allowed=False,
            resolved_path=None,
            reason=_DecisionReason.DENIED_RESOLUTION_FAILED,
            detail=f"Cannot resolve path: {e}",
            original_path=original,
        )

    # Check blocked first (always enforced)
    if blocked_paths:
        for blocked in blocked_paths:
            try:
                blocked_resolved = blocked.resolve()
                if resolved.is_relative_to(blocked_resolved):
                    return _PathDecisionInternal(
                        allowed=False,
                        resolved_path=None,
                        reason=_DecisionReason.DENIED_BLOCKED,
                        detail=f"Path is blocked: {blocked}",
                        original_path=original,
                        matched_rule=blocked,
                    )
            except (OSError, ValueError):
                continue

    # Check allowed paths
    if allowed_paths is not None:
        # Empty list = nothing allowed
        if not allowed_paths:
            return _PathDecisionInternal(
                allowed=False,
                resolved_path=None,
                reason=_DecisionReason.DENIED_NO_ALLOWED_PATHS,
                detail="No allowed paths configured",
                original_path=original,
            )

        # Check if within any allowed path
        for allowed in allowed_paths:
            try:
                allowed_resolved = allowed.resolve()
                if resolved.is_relative_to(allowed_resolved):
                    return _PathDecisionInternal(
                        allowed=True,
                        resolved_path=resolved,
                        reason=_DecisionReason.ALLOWED_WITHIN_PATH,
                        detail=f"Path within allowed directory: {allowed}",
                        original_path=original,
                        matched_rule=allowed,
                    )
            except (OSError, ValueError):
                continue

        # Not in any allowed path
        allowed_str = ", ".join(str(p) for p in allowed_paths)
        return _PathDecisionInternal(
            allowed=False,
            resolved_path=None,
            reason=_DecisionReason.DENIED_OUTSIDE_ALLOWED,
            detail=f"Path outside allowed directories. Allowed: [{allowed_str}]",
            original_path=original,
        )

    # No allowed_paths = unrestricted
    return _PathDecisionInternal(
        allowed=True,
        resolved_path=resolved,
        reason=_DecisionReason.ALLOWED_UNRESTRICTED,
        detail="Access unrestricted (TRUSTED/YOLO mode)",
        original_path=original,
    )


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write content to a file atomically using temp file + rename.

    This ensures the file is never left in a partial state on crash or interruption.
    The temp file is created in the same directory to ensure same-filesystem rename.

    Args:
        path: Path to write to.
        content: Content to write.
        encoding: Text encoding (default: utf-8).

    Raises:
        OSError: If the file cannot be written.
    """
    # Create temp file in same directory for atomic rename (same filesystem)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".tmp_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        # Atomic rename (on POSIX; Windows may not be truly atomic)
        os.replace(tmp_path, str(path))
    except Exception:
        # Clean up temp file on error
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


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


def validate_path(
    path: str | Path,
    allowed_paths: list[Path] | None = None,
    blocked_paths: list[Path] | None = None,
    cwd: Path | None = None,
) -> Path:
    """Universal path validation for all permission modes.

    Resolves the path (following all symlinks) and validates against
    allowed/blocked lists. This is the exception-raising wrapper around
    the shared _decide_path() kernel.

    Args:
        path: Path to validate (can be relative, contain symlinks, etc.)
        allowed_paths: If set, resolved path must be within one of these.
                       None = unrestricted (TRUSTED/YOLO mode).
                       Empty list [] = nothing allowed (always fails).
        blocked_paths: Paths always denied regardless of allowed_paths.
        cwd: Working directory for resolving relative paths (default: process cwd).

    Returns:
        Resolved absolute path (all symlinks followed).

    Raises:
        PathSecurityError: If path is outside allowed or in blocked.
    """
    decision = _decide_path(
        path=path,
        allowed_paths=allowed_paths,
        blocked_paths=blocked_paths,
        cwd=cwd,
    )

    if not decision.allowed:
        raise PathSecurityError(decision.original_path, decision.detail)

    assert decision.resolved_path is not None
    return decision.resolved_path


def normalize_path(path: str) -> Path:
    """Normalize a path string for cross-platform compatibility.

    Handles:
    - Windows backslashes (\\) converted to forward slashes
    - Tilde expansion (~) for home directory
    - Resolves to absolute path (follows symlinks)

    This is a convenience wrapper around validate_path() with no restrictions.

    Args:
        path: The path string to normalize

    Returns:
        Normalized, resolved Path object
    """
    return validate_path(path, allowed_paths=None, blocked_paths=None)


def normalize_path_str(path: str) -> str:
    """Normalize a path string and return as string.

    Args:
        path: The path string to normalize

    Returns:
        Normalized path as string
    """
    return str(normalize_path(path))


def display_path(path: str | Path) -> str:
    """Format a path for display, keeping it concise.

    Tries to use relative path if under current directory,
    otherwise shows absolute path with ~ for home.

    Args:
        path: The path to format

    Returns:
        Formatted path string for display
    """
    if isinstance(path, str):
        path = normalize_path(path)

    try:
        # Try to make it relative to cwd for brevity
        cwd = Path.cwd()
        if path.is_relative_to(cwd):
            return str(path.relative_to(cwd))
    except (ValueError, OSError):
        pass

    # Try to use ~ for home directory
    try:
        home = Path.home()
        if path.is_relative_to(home):
            return "~/" + str(path.relative_to(home))
    except (ValueError, OSError):
        pass

    return str(path)


def get_default_sandbox() -> list[Path]:
    """Get the default sandbox paths.

    Returns:
        List containing only the current working directory.
    """
    return [Path.cwd()]


def validate_sandbox(path: str | Path, allowed_paths: list[Path]) -> Path:
    """Validate path is within sandbox. Raises PathSecurityError if not.

    This is a convenience wrapper around validate_path() for sandboxed mode.
    Symlinks are allowed as long as they resolve to within allowed_paths.

    Args:
        path: Path to validate (can be relative or absolute)
        allowed_paths: List of allowed base directories.
            IMPORTANT: Empty list [] means NO paths allowed (will always raise).
            This is distinct from None (which isn't accepted by this function).
            The caller should handle None (unrestricted) by skipping validation.

    Returns:
        Resolved absolute path if valid

    Raises:
        PathSecurityError: If path is outside sandbox or allowed_paths is empty.
    """
    return validate_path(path, allowed_paths=allowed_paths, blocked_paths=None)
