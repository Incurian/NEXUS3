"""Path normalization utilities for cross-platform path handling."""

from pathlib import Path

from nexus3.core.errors import PathSecurityError


def normalize_path(path: str) -> Path:
    """Normalize a path string for cross-platform compatibility.

    Handles:
    - Windows backslashes (\\) converted to forward slashes
    - Tilde expansion (~) for home directory
    - Resolves to absolute path

    Args:
        path: The path string to normalize

    Returns:
        Normalized Path object
    """
    if not path:
        return Path(".")

    # Normalize Windows backslashes to forward slashes
    normalized = path.replace("\\", "/")

    # Create Path and expand user home
    p = Path(normalized).expanduser()

    return p


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


def _has_symlink_component(path: Path) -> bool:
    """Check if any component of the path is a symlink.

    Args:
        path: Resolved absolute path to check

    Returns:
        True if any parent directory or the path itself is a symlink
    """
    # Check each component from root to the path
    parts = path.parts
    current = Path(parts[0])  # Start with root

    for part in parts[1:]:
        current = current / part
        # Check if this component exists and is a symlink
        # Use lstat to not follow the symlink
        try:
            if current.is_symlink():
                return True
        except OSError:
            # Path component doesn't exist yet, that's okay
            pass

    return False


def validate_sandbox(path: str | Path, allowed_paths: list[Path]) -> Path:
    """Validate path is within sandbox. Raises PathSecurityError if not.

    Args:
        path: Path to validate (can be relative or absolute)
        allowed_paths: List of allowed base directories.
            IMPORTANT: Empty list [] means NO paths allowed (will always raise).
            This is distinct from None (which isn't accepted by this function).
            The caller should handle None (unrestricted) by skipping validation.

    Returns:
        Resolved absolute path if valid

    Raises:
        PathSecurityError: If path is outside sandbox, involves symlinks,
            or allowed_paths is empty (nothing allowed)
    """
    # [] = nothing allowed, always fails. Caller should skip validation for None.
    if not allowed_paths:
        raise PathSecurityError(str(path), "No allowed paths configured")

    # Convert to Path if string
    if isinstance(path, str):
        path = Path(path)

    # Resolve to absolute path (this also normalizes .. and .)
    try:
        resolved = path.resolve()
    except (OSError, ValueError) as e:
        raise PathSecurityError(str(path), f"Cannot resolve path: {e}") from e

    # Block symlinks in any component of the path
    if _has_symlink_component(resolved):
        raise PathSecurityError(str(path), "Symlinks not allowed in path")

    # Resolve allowed paths and check containment
    for allowed in allowed_paths:
        try:
            allowed_resolved = allowed.resolve()
        except (OSError, ValueError):
            continue

        try:
            if resolved.is_relative_to(allowed_resolved):
                return resolved
        except (ValueError, TypeError):
            continue

    # Build helpful error message
    allowed_str = ", ".join(str(p) for p in allowed_paths)
    raise PathSecurityError(
        str(path),
        f"Path outside sandbox. Allowed: [{allowed_str}]"
    )
