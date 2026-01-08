"""Path normalization utilities for cross-platform path handling."""

from pathlib import Path


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
