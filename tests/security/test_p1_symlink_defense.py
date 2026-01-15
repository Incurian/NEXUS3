"""P1.1: Test that session save operations refuse to follow symlinks.

This tests the security bug where _secure_write_file() would follow symlinks,
allowing an attacker to overwrite arbitrary files by creating symlinks in
the sessions directory.

The fix adds O_NOFOLLOW to os.open() which causes ELOOP error on symlinks.
"""

import os
import tempfile
from pathlib import Path

import pytest


class TestSecureWriteFileSymlinkDefense:
    """Test _secure_write_file refuses to follow symlinks."""

    def test_refuses_to_write_to_symlink(self, tmp_path: Path) -> None:
        """CRITICAL: Writing to a symlink must be rejected."""
        from nexus3.session.session_manager import (
            SessionManagerError,
            _secure_write_file,
        )

        # Create a target file that the symlink points to
        target_file = tmp_path / "target.txt"
        target_file.write_text("original content")

        # Create a symlink that points to the target
        symlink_path = tmp_path / "symlink.txt"
        symlink_path.symlink_to(target_file)

        # Attempt to write through the symlink - should be rejected
        with pytest.raises(SessionManagerError) as exc_info:
            _secure_write_file(symlink_path, "malicious content")

        assert "symlink" in str(exc_info.value).lower()
        assert "potential attack" in str(exc_info.value).lower()

        # Verify target file was NOT modified
        assert target_file.read_text() == "original content", (
            "SECURITY BUG: Target file was modified through symlink!"
        )

    def test_writes_to_regular_file(self, tmp_path: Path) -> None:
        """Regular file writes should work normally."""
        from nexus3.session.session_manager import _secure_write_file

        regular_file = tmp_path / "regular.txt"
        _secure_write_file(regular_file, "test content")

        assert regular_file.read_text() == "test content"

    def test_creates_new_file_with_secure_permissions(self, tmp_path: Path) -> None:
        """New files should be created with 0o600 permissions."""
        from nexus3.session.session_manager import _secure_write_file

        new_file = tmp_path / "new_file.txt"
        _secure_write_file(new_file, "content")

        mode = new_file.stat().st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"

    def test_overwrites_existing_regular_file(self, tmp_path: Path) -> None:
        """Existing regular files can be overwritten."""
        from nexus3.session.session_manager import _secure_write_file

        existing_file = tmp_path / "existing.txt"
        existing_file.write_text("old content")

        _secure_write_file(existing_file, "new content")

        assert existing_file.read_text() == "new content"

    def test_refuses_dangling_symlink(self, tmp_path: Path) -> None:
        """Dangling symlinks (pointing to nonexistent file) should also be rejected."""
        from nexus3.session.session_manager import (
            SessionManagerError,
            _secure_write_file,
        )

        # Create a symlink to a nonexistent target
        dangling_symlink = tmp_path / "dangling.txt"
        nonexistent_target = tmp_path / "nonexistent.txt"
        dangling_symlink.symlink_to(nonexistent_target)

        # Should still be rejected because it's a symlink
        with pytest.raises(SessionManagerError):
            _secure_write_file(dangling_symlink, "content")


class TestSessionManagerSymlinkDefense:
    """Test SessionManager operations refuse symlinks at session paths."""

    def test_save_session_refuses_symlink(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """save_session should refuse if session path is a symlink."""
        from nexus3.session.session_manager import SessionManager, SessionManagerError
        from nexus3.session.persistence import SavedSession

        # Patch get_nexus_dir to use our temp path
        monkeypatch.setattr(
            "nexus3.session.session_manager.get_nexus_dir",
            lambda: tmp_path / ".nexus3",
        )

        manager = SessionManager()

        # Create a symlink where the session file would be written
        sessions_dir = tmp_path / ".nexus3" / "sessions"
        sessions_dir.mkdir(parents=True)

        target_file = tmp_path / "attack_target.txt"
        target_file.write_text("sensitive data")

        # Create symlink at the session path
        session_symlink = sessions_dir / "malicious-session.json"
        session_symlink.symlink_to(target_file)

        # Create a saved session to save
        from datetime import datetime
        saved = SavedSession(
            agent_id="malicious-session",
            created_at=datetime.now(),
            modified_at=datetime.now(),
            messages=[],
            system_prompt="test",
            system_prompt_path=None,
            working_directory="/tmp",
            permission_level="trusted",
            token_usage={},
            provenance="user",
        )

        # save_session should refuse
        with pytest.raises(SessionManagerError):
            manager.save_session(saved)

        # Target should not be modified
        assert target_file.read_text() == "sensitive data"
