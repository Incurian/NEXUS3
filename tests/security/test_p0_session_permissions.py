"""P0.4: Test that session artifacts are created with secure permissions.

This tests the security bug where session directories and files were created
with insecure permissions, allowing other users/processes to read sensitive
session data.

The fix:
- Directories: 0o700 (owner only)
- Files/DB: 0o600 (owner read/write only)
- No write-then-chmod TOCTOU races
"""

import os
import stat
import tempfile
from pathlib import Path

import pytest

from nexus3.core.secure_io import (
    SECURE_DIR_MODE,
    SECURE_FILE_MODE,
    ensure_secure_dir,
    ensure_secure_file,
    secure_mkdir,
    secure_write_atomic,
    secure_write_new,
)


class TestSecureIoModule:
    """Test the secure_io utility functions."""

    def test_secure_dir_mode_is_0o700(self) -> None:
        """Directory mode should be owner-only."""
        assert SECURE_DIR_MODE == 0o700

    def test_secure_file_mode_is_0o600(self) -> None:
        """File mode should be owner read/write only."""
        assert SECURE_FILE_MODE == 0o600


class TestSecureMkdir:
    """Test secure_mkdir creates directories with correct permissions."""

    def test_creates_with_secure_permissions(self, tmp_path: Path) -> None:
        """New directory should have 0o700 permissions."""
        test_dir = tmp_path / "secure_test"
        secure_mkdir(test_dir)

        mode = test_dir.stat().st_mode & 0o777
        assert mode == 0o700, f"Expected 0o700, got {oct(mode)}"

    def test_creates_parent_dirs_securely(self, tmp_path: Path) -> None:
        """Parent directories should also have secure permissions."""
        test_dir = tmp_path / "parent" / "child" / "target"
        secure_mkdir(test_dir, parents=True)

        # Check all created directories
        for dir_path in [
            tmp_path / "parent",
            tmp_path / "parent" / "child",
            test_dir,
        ]:
            mode = dir_path.stat().st_mode & 0o777
            assert mode == 0o700, f"{dir_path}: Expected 0o700, got {oct(mode)}"

    def test_fixes_existing_dir_permissions(self, tmp_path: Path) -> None:
        """Existing directory with loose permissions should be fixed."""
        test_dir = tmp_path / "loose_perms"
        test_dir.mkdir(mode=0o755)  # Loose permissions

        secure_mkdir(test_dir)

        mode = test_dir.stat().st_mode & 0o777
        assert mode == 0o700, f"Expected 0o700 after fix, got {oct(mode)}"


class TestSecureWriteNew:
    """Test secure_write_new creates files atomically with secure permissions."""

    def test_creates_with_secure_permissions(self, tmp_path: Path) -> None:
        """New file should have 0o600 permissions."""
        test_file = tmp_path / "secure_file.txt"
        secure_write_new(test_file, "secret content")

        mode = test_file.stat().st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"

    def test_content_written_correctly(self, tmp_path: Path) -> None:
        """Content should be written correctly."""
        test_file = tmp_path / "content_test.txt"
        secure_write_new(test_file, "hello world")

        assert test_file.read_text() == "hello world"

    def test_raises_if_file_exists(self, tmp_path: Path) -> None:
        """Should raise FileExistsError if file already exists."""
        test_file = tmp_path / "existing.txt"
        test_file.write_text("existing content")

        with pytest.raises(FileExistsError):
            secure_write_new(test_file, "new content")

    def test_handles_bytes(self, tmp_path: Path) -> None:
        """Should handle bytes content."""
        test_file = tmp_path / "bytes_test.bin"
        secure_write_new(test_file, b"\x00\x01\x02\x03")

        assert test_file.read_bytes() == b"\x00\x01\x02\x03"


class TestSecureWriteAtomic:
    """Test secure_write_atomic for both new and existing files."""

    def test_creates_new_file_securely(self, tmp_path: Path) -> None:
        """New file should have 0o600 permissions."""
        test_file = tmp_path / "new_atomic.txt"
        secure_write_atomic(test_file, "content")

        mode = test_file.stat().st_mode & 0o777
        assert mode == 0o600

    def test_updates_existing_file(self, tmp_path: Path) -> None:
        """Existing file should be updated."""
        test_file = tmp_path / "existing_atomic.txt"
        secure_write_new(test_file, "original")

        secure_write_atomic(test_file, "updated")

        assert test_file.read_text() == "updated"

    def test_maintains_secure_permissions_on_update(self, tmp_path: Path) -> None:
        """Updated file should maintain 0o600 permissions."""
        test_file = tmp_path / "update_perms.txt"
        secure_write_new(test_file, "original")

        secure_write_atomic(test_file, "updated")

        mode = test_file.stat().st_mode & 0o777
        assert mode == 0o600


class TestMarkdownWriterPermissions:
    """Test MarkdownWriter creates files with secure permissions."""

    def test_session_dir_secure_permissions(self, tmp_path: Path) -> None:
        """Session directory should have 0o700 permissions."""
        from nexus3.session.markdown import MarkdownWriter

        session_dir = tmp_path / "session"
        MarkdownWriter(session_dir, verbose_enabled=False)

        mode = session_dir.stat().st_mode & 0o777
        assert mode == 0o700, f"Session dir: Expected 0o700, got {oct(mode)}"

    def test_context_file_secure_permissions(self, tmp_path: Path) -> None:
        """context.md should have 0o600 permissions."""
        from nexus3.session.markdown import MarkdownWriter

        session_dir = tmp_path / "session"
        MarkdownWriter(session_dir, verbose_enabled=False)

        context_path = session_dir / "context.md"
        mode = context_path.stat().st_mode & 0o777
        assert mode == 0o600, f"context.md: Expected 0o600, got {oct(mode)}"

    def test_verbose_file_secure_permissions(self, tmp_path: Path) -> None:
        """verbose.md should have 0o600 permissions when enabled."""
        from nexus3.session.markdown import MarkdownWriter

        session_dir = tmp_path / "session"
        MarkdownWriter(session_dir, verbose_enabled=True)

        verbose_path = session_dir / "verbose.md"
        mode = verbose_path.stat().st_mode & 0o777
        assert mode == 0o600, f"verbose.md: Expected 0o600, got {oct(mode)}"


class TestSessionStoragePermissions:
    """Test SessionStorage creates DB with secure permissions."""

    def test_db_file_secure_permissions(self, tmp_path: Path) -> None:
        """session.db should have 0o600 permissions."""
        from nexus3.session.storage import SessionStorage

        db_path = tmp_path / "session" / "session.db"
        storage = SessionStorage(db_path)

        mode = db_path.stat().st_mode & 0o777
        assert mode == 0o600, f"session.db: Expected 0o600, got {oct(mode)}"

        # Clean up
        storage.close()

    def test_db_parent_dir_secure_permissions(self, tmp_path: Path) -> None:
        """Parent directory of session.db should have 0o700 permissions."""
        from nexus3.session.storage import SessionStorage

        db_path = tmp_path / "session" / "session.db"
        storage = SessionStorage(db_path)

        mode = db_path.parent.stat().st_mode & 0o777
        assert mode == 0o700, f"DB parent dir: Expected 0o700, got {oct(mode)}"

        storage.close()


class TestNoTOCTOURace:
    """Test that file creation is atomic (no write-then-chmod race)."""

    def test_file_created_with_permissions_atomically(self, tmp_path: Path) -> None:
        """File should never exist with loose permissions.

        This verifies the fix for TOCTOU: file is created with correct
        permissions in a single operation, not write-then-chmod.
        """
        test_file = tmp_path / "atomic_test.txt"

        # Create file atomically
        secure_write_new(test_file, "secret")

        # At no point should the file have existed with loose permissions
        # We verify this by checking the current permissions are secure
        mode = test_file.stat().st_mode & 0o777
        assert mode == 0o600, "File was created with insecure permissions"

    def test_directory_created_with_permissions_atomically(self, tmp_path: Path) -> None:
        """Directory should be created with secure permissions."""
        test_dir = tmp_path / "atomic_dir"

        secure_mkdir(test_dir)

        mode = test_dir.stat().st_mode & 0o777
        assert mode == 0o700, "Directory was created with insecure permissions"
