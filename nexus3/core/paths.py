"""Path normalization and validation utilities for cross-platform path handling."""

import os
import tempfile
from pathlib import Path

from nexus3.core.errors import PathSecurityError


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


def validate_path(
    path: str | Path,
    allowed_paths: list[Path] | None = None,
    blocked_paths: list[Path] | None = None,
) -> Path:
    """Universal path validation for all permission modes.

    Resolves the path (following all symlinks) and validates against
    allowed/blocked lists. This is the single entry point for all
    path validation in the system.

    Args:
        path: Path to validate (can be relative, contain symlinks, etc.)
        allowed_paths: If set, resolved path must be within one of these.
                       None = unrestricted (TRUSTED/YOLO mode).
                       Empty list [] = nothing allowed (always fails).
        blocked_paths: Paths always denied regardless of allowed_paths.

    Returns:
        Resolved absolute path (all symlinks followed).

    Raises:
        PathSecurityError: If path is outside allowed or in blocked.
    """
    # Handle empty/None input
    if not path:
        path = "."

    # Normalize and resolve (follows all symlinks)
    if isinstance(path, str):
        # Normalize Windows backslashes
        path = path.replace("\\", "/")
        path = Path(path)

    try:
        resolved = path.expanduser().resolve()
    except (OSError, ValueError) as e:
        raise PathSecurityError(str(path), f"Cannot resolve path: {e}") from e

    # Check blocked first (applies to all modes)
    if blocked_paths:
        for blocked in blocked_paths:
            try:
                blocked_resolved = blocked.resolve()
                if resolved.is_relative_to(blocked_resolved):
                    raise PathSecurityError(
                        str(path), f"Path is blocked: {blocked}"
                    )
            except (OSError, ValueError):
                continue

    # Check allowed (None = unrestricted)
    if allowed_paths is not None:
        # Empty list = nothing allowed
        if not allowed_paths:
            raise PathSecurityError(str(path), "No allowed paths configured")

        for allowed in allowed_paths:
            try:
                allowed_resolved = allowed.resolve()
                if resolved.is_relative_to(allowed_resolved):
                    return resolved
            except (OSError, ValueError):
                continue

        # Not in any allowed path
        allowed_str = ", ".join(str(p) for p in allowed_paths)
        raise PathSecurityError(
            str(path), f"Path outside allowed directories. Allowed: [{allowed_str}]"
        )

    return resolved


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
