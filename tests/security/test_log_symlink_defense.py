"""Tests for log append symlink defense (Fix 2.2).

This module tests that log file appends refuse to follow symlinks,
preventing symlink-based attacks on log files.
"""

import os
import stat
from pathlib import Path

import pytest

from nexus3.core.secure_io import (
    SECURE_FILE_MODE,
    SymlinkError,
    secure_append,
)


class TestSecureAppend:
    """Tests for secure_append function."""

    def test_append_creates_new_file(self, tmp_path: Path) -> None:
        """secure_append creates file if it doesn't exist."""
        target = tmp_path / "new_file.txt"
        assert not target.exists()

        secure_append(target, "hello")

        assert target.exists()
        assert target.read_text() == "hello"

    def test_append_to_existing_file(self, tmp_path: Path) -> None:
        """secure_append appends to existing file."""
        target = tmp_path / "existing.txt"
        target.write_text("first\n")

        secure_append(target, "second\n")

        assert target.read_text() == "first\nsecond\n"

    def test_append_multiple_times(self, tmp_path: Path) -> None:
        """secure_append can append multiple times."""
        target = tmp_path / "multi.txt"

        secure_append(target, "line1\n")
        secure_append(target, "line2\n")
        secure_append(target, "line3\n")

        assert target.read_text() == "line1\nline2\nline3\n"

    def test_append_bytes_content(self, tmp_path: Path) -> None:
        """secure_append handles bytes content."""
        target = tmp_path / "bytes.txt"

        secure_append(target, b"binary content")

        assert target.read_bytes() == b"binary content"

    def test_append_with_encoding(self, tmp_path: Path) -> None:
        """secure_append respects encoding parameter."""
        target = tmp_path / "encoded.txt"

        # Unicode content with explicit encoding
        secure_append(target, "cafe\u0301", encoding="utf-8")

        # Should be UTF-8 encoded
        assert target.read_bytes() == "cafe\u0301".encode("utf-8")

    def test_append_refuses_symlink(self, tmp_path: Path) -> None:
        """secure_append raises SymlinkError for symlinks."""
        real_file = tmp_path / "real.txt"
        real_file.write_text("original")

        symlink = tmp_path / "link.txt"
        symlink.symlink_to(real_file)

        with pytest.raises(SymlinkError) as exc_info:
            secure_append(symlink, "malicious")

        assert "Refusing to append through symlink" in str(exc_info.value)
        assert str(symlink) in str(exc_info.value)
        # Original file unchanged
        assert real_file.read_text() == "original"

    def test_append_refuses_dangling_symlink(self, tmp_path: Path) -> None:
        """secure_append raises SymlinkError for dangling symlinks."""
        non_existent = tmp_path / "ghost.txt"
        symlink = tmp_path / "dangling.txt"
        symlink.symlink_to(non_existent)

        with pytest.raises(SymlinkError) as exc_info:
            secure_append(symlink, "content")

        assert "Refusing to append through symlink" in str(exc_info.value)

    def test_new_file_has_secure_permissions(self, tmp_path: Path) -> None:
        """New files created by secure_append have 0o600 permissions."""
        target = tmp_path / "secure.txt"

        secure_append(target, "secret")

        mode = stat.S_IMODE(target.stat().st_mode)
        assert mode == SECURE_FILE_MODE  # 0o600

    def test_append_to_file_with_lax_permissions(self, tmp_path: Path) -> None:
        """secure_append works on files with lax permissions (doesn't change them)."""
        target = tmp_path / "lax.txt"
        target.write_text("initial")
        os.chmod(target, 0o644)

        secure_append(target, "\nappended")

        # Content appended
        assert target.read_text() == "initial\nappended"
        # Note: secure_append doesn't change permissions of existing files
        # It only sets permissions when creating new files

    def test_append_handles_parent_directory_missing(self, tmp_path: Path) -> None:
        """secure_append raises FileNotFoundError for missing parent directory."""
        target = tmp_path / "missing_dir" / "file.txt"

        with pytest.raises(FileNotFoundError):
            secure_append(target, "content")

    def test_symlinkerror_is_oserror_subclass(self) -> None:
        """SymlinkError is a subclass of OSError."""
        assert issubclass(SymlinkError, OSError)

    def test_symlinkerror_can_be_caught_as_oserror(self, tmp_path: Path) -> None:
        """SymlinkError can be caught as OSError."""
        real_file = tmp_path / "real.txt"
        real_file.write_text("content")
        symlink = tmp_path / "link.txt"
        symlink.symlink_to(real_file)

        caught = False
        try:
            secure_append(symlink, "data")
        except OSError as e:
            caught = True
            assert isinstance(e, SymlinkError)

        assert caught


class TestMarkdownWriterSymlinkDefense:
    """Tests that MarkdownWriter uses secure_append."""

    def test_markdown_writer_refuses_symlink(self, tmp_path: Path) -> None:
        """MarkdownWriter._append refuses to follow symlinks."""
        from nexus3.session.markdown import MarkdownWriter

        # Create session directory
        session_dir = tmp_path / "session"
        session_dir.mkdir()

        # Create MarkdownWriter
        writer = MarkdownWriter(session_dir, verbose_enabled=False)

        # Replace context.md with a symlink
        target = tmp_path / "stolen.txt"
        target.write_text("")

        # Remove the real context.md and replace with symlink
        writer.context_path.unlink()
        writer.context_path.symlink_to(target)

        # Attempt to write should fail
        with pytest.raises(SymlinkError):
            writer.write_user("test message")

        # Target file unchanged
        assert target.read_text() == ""

    def test_raw_writer_refuses_symlink(self, tmp_path: Path) -> None:
        """RawWriter._append_jsonl refuses to follow symlinks."""
        from nexus3.session.markdown import RawWriter

        # Create session directory
        session_dir = tmp_path / "session"
        session_dir.mkdir()

        # Create RawWriter
        writer = RawWriter(session_dir)

        # Create a symlink target
        target = tmp_path / "stolen.jsonl"
        target.write_text("")

        # Create symlink at raw.jsonl location
        writer.raw_path.symlink_to(target)

        # Attempt to write should fail
        with pytest.raises(SymlinkError):
            writer.write_request("/endpoint", {"key": "value"})

        # Target file unchanged
        assert target.read_text() == ""


class TestSecureAppendEdgeCases:
    """Edge case tests for secure_append."""

    def test_append_empty_string(self, tmp_path: Path) -> None:
        """secure_append handles empty string content."""
        target = tmp_path / "empty.txt"
        target.write_text("existing")

        secure_append(target, "")

        assert target.read_text() == "existing"

    def test_append_empty_bytes(self, tmp_path: Path) -> None:
        """secure_append handles empty bytes content."""
        target = tmp_path / "empty_bytes.txt"
        target.write_text("existing")

        secure_append(target, b"")

        assert target.read_text() == "existing"

    def test_append_newline_handling(self, tmp_path: Path) -> None:
        """secure_append preserves newlines correctly."""
        target = tmp_path / "newlines.txt"

        secure_append(target, "line1\n")
        secure_append(target, "line2\r\n")
        secure_append(target, "line3")

        content = target.read_bytes()
        assert content == b"line1\nline2\r\nline3"

    def test_append_unicode_content(self, tmp_path: Path) -> None:
        """secure_append handles unicode content correctly."""
        target = tmp_path / "unicode.txt"

        # Various unicode characters
        content = "Hello  Emoji: \U0001F600  CJK: \u4e2d\u6587"
        secure_append(target, content)

        assert target.read_text(encoding="utf-8") == content

    def test_append_concurrent_creates(self, tmp_path: Path) -> None:
        """secure_append handles race on file creation gracefully."""
        # O_CREAT without O_EXCL allows multiple processes to create
        # The file is created atomically by whichever gets there first
        target = tmp_path / "race.txt"

        secure_append(target, "first\n")
        secure_append(target, "second\n")

        # Both appends should succeed
        assert target.read_text() == "first\nsecond\n"
