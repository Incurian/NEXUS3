"""Secure file I/O utilities for NEXUS3.

This module provides atomic, race-condition-free file operations with
proper permission handling for security-sensitive session artifacts.
"""

import os
import stat
from pathlib import Path

# Secure permissions for session directories (owner only)
SECURE_DIR_MODE: int = stat.S_IRWXU  # 0o700

# Secure permissions for session files (owner read/write only)
SECURE_FILE_MODE: int = stat.S_IRUSR | stat.S_IWUSR  # 0o600


def secure_mkdir(path: Path, parents: bool = True) -> None:
    """Create directory with secure permissions (0o700).

    Creates directory with owner-only access. If parents=True, creates
    parent directories as well, all with secure permissions.

    Unlike Path.mkdir(), this ensures the final directory has secure
    permissions even when it already exists.

    Args:
        path: Directory path to create.
        parents: If True, create parent directories as needed.
    """
    if parents:
        # Create parents with secure permissions
        for parent in reversed(list(path.parents)):
            if not parent.exists():
                parent.mkdir(mode=SECURE_DIR_MODE)
                # Re-apply in case umask interfered
                os.chmod(parent, SECURE_DIR_MODE)

    # Create the target directory
    if not path.exists():
        path.mkdir(mode=SECURE_DIR_MODE)

    # Always ensure correct permissions (handles existing dirs)
    os.chmod(path, SECURE_DIR_MODE)


def secure_write_new(path: Path, content: str | bytes) -> None:
    """Atomically create a new file with secure permissions.

    Creates a file with owner-only permissions (0o600) in a single atomic
    operation using os.open() with O_CREAT | O_EXCL. This prevents TOCTOU
    race conditions where another process could read the file before
    permissions are set.

    Args:
        path: Path to the file to create.
        content: Content to write (str or bytes).

    Raises:
        FileExistsError: If the file already exists.
    """
    if isinstance(content, str):
        content = content.encode("utf-8")

    # O_CREAT | O_EXCL ensures atomic creation (fails if exists)
    # Mode is applied at creation time, not after
    fd = os.open(
        str(path),
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        SECURE_FILE_MODE,
    )
    try:
        os.write(fd, content)
        os.fsync(fd)  # Ensure content is on disk
    finally:
        os.close(fd)


def secure_write_atomic(path: Path, content: str | bytes) -> None:
    """Atomically write to a file (new or existing) with secure permissions.

    For new files, creates atomically with secure permissions.
    For existing files, writes to a temp file and renames atomically.

    Args:
        path: Path to the file to write.
        content: Content to write (str or bytes).
    """
    if isinstance(content, str):
        content = content.encode("utf-8")

    if not path.exists():
        # New file - create atomically
        secure_write_new(path, content)
    else:
        # Existing file - write via temp + rename
        temp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            # Create temp with secure permissions
            fd = os.open(
                str(temp_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                SECURE_FILE_MODE,
            )
            try:
                os.write(fd, content)
                os.fsync(fd)
            finally:
                os.close(fd)

            # Atomic rename
            os.replace(temp_path, path)

            # Ensure permissions after replace (some filesystems may not preserve)
            os.chmod(path, SECURE_FILE_MODE)
        except Exception:
            # Clean up temp file on error
            if temp_path.exists():
                temp_path.unlink()
            raise


def ensure_secure_file(path: Path) -> None:
    """Ensure an existing file has secure permissions.

    Use this to fix permissions on files that were created by other means.

    Args:
        path: Path to the file.

    Raises:
        FileNotFoundError: If the file doesn't exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    os.chmod(path, SECURE_FILE_MODE)


def ensure_secure_dir(path: Path) -> None:
    """Ensure an existing directory has secure permissions.

    Use this to fix permissions on directories that were created by other means.

    Args:
        path: Path to the directory.

    Raises:
        FileNotFoundError: If the directory doesn't exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Directory not found: {path}")
    os.chmod(path, SECURE_DIR_MODE)
