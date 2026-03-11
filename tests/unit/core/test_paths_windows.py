"""Tests for Windows-specific path handling in nexus3/core/paths.py."""

from pathlib import Path

import pytest

import nexus3.core.paths as paths_module
from nexus3.core.paths import (
    _normalize_input_path_string,
    atomic_write_bytes,
    atomic_write_text,
    detect_line_ending,
)


class TestDetectLineEnding:
    """Tests for line ending detection."""

    def test_detect_crlf(self) -> None:
        """Should detect CRLF (Windows) line endings."""
        assert detect_line_ending("line1\r\nline2\r\n") == "\r\n"

    def test_detect_lf(self) -> None:
        """Should detect LF (Unix) line endings."""
        assert detect_line_ending("line1\nline2\n") == "\n"

    def test_detect_cr(self) -> None:
        """Should detect CR (legacy Mac) line endings."""
        assert detect_line_ending("line1\rline2\r") == "\r"

    def test_empty_defaults_lf(self) -> None:
        """Empty content should default to LF."""
        assert detect_line_ending("") == "\n"

    def test_no_line_endings_defaults_lf(self) -> None:
        """Content without line endings should default to LF."""
        assert detect_line_ending("single line no ending") == "\n"

    def test_mixed_prefers_crlf(self) -> None:
        """If CRLF is present, prefer it (common Windows git scenario)."""
        assert detect_line_ending("line1\r\nline2\nline3") == "\r\n"

    def test_crlf_at_end_only(self) -> None:
        """Should detect CRLF even if only at the end."""
        assert detect_line_ending("line1\r\n") == "\r\n"

    def test_lf_before_cr(self) -> None:
        """Should detect CR when LF not present but CR is."""
        assert detect_line_ending("line1\rline2") == "\r"


class TestAtomicWriteBytes:
    """Tests for atomic binary file writing."""

    def test_writes_exact_bytes(self, tmp_path: Path) -> None:
        """Should write exact bytes without modification."""
        test_file = tmp_path / "test.bin"
        data = b"hello\r\nworld\r\n"
        atomic_write_bytes(test_file, data)
        assert test_file.read_bytes() == data

    def test_preserves_crlf(self, tmp_path: Path) -> None:
        """Should preserve CRLF line endings in binary write."""
        test_file = tmp_path / "crlf.txt"
        data = b"line1\r\nline2\r\n"
        atomic_write_bytes(test_file, data)
        # Read in binary to verify exact bytes
        assert b"\r\n" in test_file.read_bytes()
        assert test_file.read_bytes().count(b"\r\n") == 2

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        """Should overwrite existing file content."""
        test_file = tmp_path / "existing.txt"
        test_file.write_bytes(b"old content")
        atomic_write_bytes(test_file, b"new content")
        assert test_file.read_bytes() == b"new content"

    def test_atomic_on_error(self, tmp_path: Path) -> None:
        """Original file should remain if write fails (e.g., parent dir removed)."""
        test_file = tmp_path / "atomic_test.txt"
        test_file.write_bytes(b"original")

        # Try to write to a file in a non-existent directory
        bad_file = tmp_path / "nonexistent" / "file.txt"
        with pytest.raises(FileNotFoundError):
            atomic_write_bytes(bad_file, b"new")

        # Original should be unchanged
        assert test_file.read_bytes() == b"original"

    def test_creates_new_file(self, tmp_path: Path) -> None:
        """Should create file if it doesn't exist."""
        test_file = tmp_path / "new_file.txt"
        assert not test_file.exists()
        atomic_write_bytes(test_file, b"content")
        assert test_file.exists()
        assert test_file.read_bytes() == b"content"

    def test_empty_bytes(self, tmp_path: Path) -> None:
        """Should handle empty bytes."""
        test_file = tmp_path / "empty.txt"
        atomic_write_bytes(test_file, b"")
        assert test_file.read_bytes() == b""

    def test_binary_data(self, tmp_path: Path) -> None:
        """Should handle arbitrary binary data."""
        test_file = tmp_path / "binary.bin"
        # Mix of binary data including null bytes
        data = b"\x00\x01\x02\xff\xfe\xfd"
        atomic_write_bytes(test_file, data)
        assert test_file.read_bytes() == data


class TestAtomicWriteText:
    """Tests for atomic text writing without newline translation."""

    def test_writes_exact_newline_bytes(self, tmp_path: Path) -> None:
        """Text writes should preserve caller-provided newline bytes exactly."""
        test_file = tmp_path / "text.txt"
        content = "line1\r\nline2\r\n"

        atomic_write_text(test_file, content)

        assert test_file.read_bytes() == content.encode("utf-8")

    def test_disables_platform_newline_translation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Text writes should pass newline='' to the text writer."""
        test_file = tmp_path / "translated.txt"
        captured: dict[str, object] = {}
        original_fdopen = paths_module.os.fdopen

        def recording_fdopen(fd: int, *args: object, **kwargs: object):
            captured["newline"] = kwargs.get("newline")
            return original_fdopen(fd, *args, **kwargs)

        monkeypatch.setattr(paths_module.os, "fdopen", recording_fdopen)

        atomic_write_text(test_file, "line1\nline2\n")

        assert captured["newline"] == ""


class TestWindowsPathInputNormalization:
    """Tests for narrow Windows path-shape normalization."""

    def test_backslashes_become_forward_slashes(self) -> None:
        """Backslash input should normalize regardless of host platform."""
        assert _normalize_input_path_string(r"D:\Repo\file.txt") == "D:/Repo/file.txt"

    def test_non_windows_does_not_rewrite_git_bash_drive_paths(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Git Bash-style paths are only rewritten on native Windows hosts."""
        monkeypatch.setattr(paths_module.sys, "platform", "linux")

        assert _normalize_input_path_string("/d/Repo/file.txt") == "/d/Repo/file.txt"

    def test_windows_rewrites_git_bash_drive_paths(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Native Windows should accept Git Bash /d/... compatibility input."""
        monkeypatch.setattr(paths_module.sys, "platform", "win32")

        assert _normalize_input_path_string("/d/Repo/file.txt") == "D:/Repo/file.txt"
        assert _normalize_input_path_string("/d") == "D:/"

    def test_windows_rewrites_wsl_mount_paths(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Native Windows should accept WSL-style /mnt/d/... compatibility input."""
        monkeypatch.setattr(paths_module.sys, "platform", "win32")

        assert _normalize_input_path_string("/mnt/d/Repo/file.txt") == "D:/Repo/file.txt"
        assert _normalize_input_path_string("/mnt/d") == "D:/"

    def test_windows_preserves_unc_paths(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """UNC share paths should not be mistaken for drive-root rewrites."""
        monkeypatch.setattr(paths_module.sys, "platform", "win32")

        assert _normalize_input_path_string("//server/share/file.txt") == "//server/share/file.txt"
