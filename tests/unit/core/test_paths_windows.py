"""Tests for Windows-specific path handling in nexus3/core/paths.py."""

import pytest
from pathlib import Path

from nexus3.core.paths import detect_line_ending, atomic_write_bytes


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
