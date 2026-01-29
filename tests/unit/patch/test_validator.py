"""Unit tests for nexus3.patch.validator module."""

import pytest

from nexus3.patch import validate_patch, validate_patch_set
from nexus3.patch.types import Hunk, PatchFile
from nexus3.patch.validator import ValidationResult


class TestValidatePatch:
    """Tests for validate_patch function."""

    def test_valid_patch(self) -> None:
        """Test that a valid patch passes validation."""
        patch = PatchFile(
            old_path="test.py",
            new_path="test.py",
            hunks=[
                Hunk(
                    old_start=1,
                    old_count=3,
                    new_start=1,
                    new_count=4,
                    lines=[
                        (" ", "line1"),
                        ("-", "line2"),
                        ("+", "new_line2a"),
                        ("+", "new_line2b"),
                        (" ", "line3"),
                    ],
                )
            ],
        )

        target_content = "line1\nline2\nline3\n"
        result = validate_patch(patch, target_content)

        assert result.valid is True
        assert len(result.errors) == 0

    def test_line_count_mismatch(self) -> None:
        """Test detection and auto-fix of line count mismatch in header."""
        # Header says -2,+2 but actual lines are -2,+3
        patch = PatchFile(
            old_path="test.py",
            new_path="test.py",
            hunks=[
                Hunk(
                    old_start=1,
                    old_count=2,  # Wrong: should be 2 (1 context + 1 removal)
                    new_start=1,
                    new_count=2,  # Wrong: should be 3 (1 context + 2 additions)
                    lines=[
                        (" ", "line1"),
                        ("-", "line2"),
                        ("+", "new1"),
                        ("+", "new2"),
                    ],
                )
            ],
        )

        target_content = "line1\nline2\n"
        result = validate_patch(patch, target_content)

        # Should be valid (fixable)
        assert result.valid is True
        # Should have warning about count mismatch
        assert any("count mismatch" in w.lower() for w in result.warnings)
        # Should have fixed patch
        assert result.fixed_patch is not None
        fixed_hunk = result.fixed_patch.hunks[0]
        assert fixed_hunk.old_count == 2  # 1 context + 1 removal
        assert fixed_hunk.new_count == 3  # 1 context + 2 additions

    def test_context_mismatch(self) -> None:
        """Test detection of context line mismatch with file content."""
        patch = PatchFile(
            old_path="test.py",
            new_path="test.py",
            hunks=[
                Hunk(
                    old_start=1,
                    old_count=2,
                    new_start=1,
                    new_count=2,
                    lines=[
                        (" ", "wrong context"),  # Doesn't match file
                        ("-", "line2"),
                        ("+", "new line"),
                    ],
                )
            ],
        )

        target_content = "actual line1\nline2\n"
        result = validate_patch(patch, target_content)

        assert result.valid is False
        assert len(result.errors) > 0
        assert any("context mismatch" in e.lower() for e in result.errors)

    def test_removal_mismatch(self) -> None:
        """Test detection when line to remove doesn't match file."""
        patch = PatchFile(
            old_path="test.py",
            new_path="test.py",
            hunks=[
                Hunk(
                    old_start=1,
                    old_count=2,
                    new_start=1,
                    new_count=1,
                    lines=[
                        (" ", "line1"),
                        ("-", "wrong line to remove"),  # Doesn't match
                    ],
                )
            ],
        )

        target_content = "line1\nactual line2\n"
        result = validate_patch(patch, target_content)

        assert result.valid is False
        assert any("mismatch" in e.lower() for e in result.errors)

    def test_trailing_whitespace_warning(self) -> None:
        """Test that trailing whitespace differences generate warnings, not errors."""
        patch = PatchFile(
            old_path="test.py",
            new_path="test.py",
            hunks=[
                Hunk(
                    old_start=1,
                    old_count=2,
                    new_start=1,
                    new_count=2,
                    lines=[
                        (" ", "line1  "),  # Extra trailing spaces
                        ("-", "line2"),
                        ("+", "new line"),
                    ],
                )
            ],
        )

        # File has no trailing spaces
        target_content = "line1\nline2\n"
        result = validate_patch(patch, target_content)

        # Should still be valid (whitespace is auto-fixable)
        assert result.valid is True
        # Should have whitespace warning
        assert any("whitespace" in w.lower() for w in result.warnings)
        # Should have fixed patch with normalized whitespace
        assert result.fixed_patch is not None

    def test_hunk_beyond_file_length(self) -> None:
        """Test error when hunk references lines beyond file length."""
        patch = PatchFile(
            old_path="test.py",
            new_path="test.py",
            hunks=[
                Hunk(
                    old_start=10,  # File only has 2 lines
                    old_count=2,
                    new_start=10,
                    new_count=2,
                    lines=[
                        (" ", "line10"),
                        ("-", "line11"),
                        ("+", "new line"),
                    ],
                )
            ],
        )

        target_content = "line1\nline2\n"
        result = validate_patch(patch, target_content)

        assert result.valid is False
        assert any("only has" in e.lower() for e in result.errors)

    def test_empty_file_patch(self) -> None:
        """Test validating patch against empty file content."""
        patch = PatchFile(
            old_path="test.py",
            new_path="test.py",
            hunks=[
                Hunk(
                    old_start=1,
                    old_count=0,
                    new_start=1,
                    new_count=2,
                    lines=[
                        ("+", "new line1"),
                        ("+", "new line2"),
                    ],
                )
            ],
        )

        # Empty file - additions only should work
        target_content = ""
        result = validate_patch(patch, target_content)

        assert result.valid is True

    def test_new_file_validation(self) -> None:
        """Test that new file patches don't need content validation."""
        patch = PatchFile(
            old_path="/dev/null",
            new_path="newfile.py",
            is_new_file=True,
            hunks=[
                Hunk(
                    old_start=0,
                    old_count=0,
                    new_start=1,
                    new_count=2,
                    lines=[
                        ("+", "line1"),
                        ("+", "line2"),
                    ],
                )
            ],
        )

        # For new files, target content is empty
        result = validate_patch(patch, "")
        assert result.valid is True

    def test_multiple_hunks_validation(self) -> None:
        """Test validating patch with multiple hunks."""
        patch = PatchFile(
            old_path="test.py",
            new_path="test.py",
            hunks=[
                Hunk(
                    old_start=1,
                    old_count=2,
                    new_start=1,
                    new_count=2,
                    lines=[
                        (" ", "line1"),
                        ("-", "line2"),
                        ("+", "new_line2"),
                    ],
                ),
                Hunk(
                    old_start=5,
                    old_count=2,
                    new_start=5,
                    new_count=2,
                    lines=[
                        (" ", "line5"),
                        ("-", "line6"),
                        ("+", "new_line6"),
                    ],
                ),
            ],
        )

        target_content = "line1\nline2\nline3\nline4\nline5\nline6\nline7\n"
        result = validate_patch(patch, target_content)

        assert result.valid is True


class TestValidatePatchSet:
    """Tests for validate_patch_set function."""

    def test_validate_multiple_files(self) -> None:
        """Test validating patches for multiple files."""
        patches = [
            PatchFile(
                old_path="a.py",
                new_path="a.py",
                hunks=[
                    Hunk(
                        old_start=1,
                        old_count=1,
                        new_start=1,
                        new_count=1,
                        lines=[("-", "old"), ("+", "new")],
                    )
                ],
            ),
            PatchFile(
                old_path="b.py",
                new_path="b.py",
                hunks=[
                    Hunk(
                        old_start=1,
                        old_count=1,
                        new_start=1,
                        new_count=1,
                        lines=[("-", "old"), ("+", "new")],
                    )
                ],
            ),
        ]

        def get_content(path: str) -> str:
            return "old\n"

        results = validate_patch_set(patches, get_content)

        assert len(results) == 2
        assert results["a.py"].valid is True
        assert results["b.py"].valid is True

    def test_validate_missing_file(self) -> None:
        """Test error when target file doesn't exist."""
        patches = [
            PatchFile(
                old_path="missing.py",
                new_path="missing.py",
                hunks=[
                    Hunk(
                        old_start=1,
                        old_count=1,
                        new_start=1,
                        new_count=1,
                        lines=[("-", "old"), ("+", "new")],
                    )
                ],
            ),
        ]

        def get_content(path: str) -> str:
            raise FileNotFoundError(f"File not found: {path}")

        results = validate_patch_set(patches, get_content)

        assert len(results) == 1
        assert results["missing.py"].valid is False
        assert any("not found" in e.lower() for e in results["missing.py"].errors)

    def test_validate_new_file_skips_content_check(self) -> None:
        """Test that new files don't try to read non-existent content."""
        patches = [
            PatchFile(
                old_path="/dev/null",
                new_path="new.py",
                is_new_file=True,
                hunks=[
                    Hunk(
                        old_start=0,
                        old_count=0,
                        new_start=1,
                        new_count=1,
                        lines=[("+", "new content")],
                    )
                ],
            ),
        ]

        def get_content(path: str) -> str:
            raise FileNotFoundError("Should not be called for new files")

        results = validate_patch_set(patches, get_content)

        assert results["new.py"].valid is True


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_default_values(self) -> None:
        """Test default values for ValidationResult fields."""
        result = ValidationResult(valid=True)

        assert result.valid is True
        assert result.errors == []
        assert result.warnings == []
        assert result.fixed_patch is None

    def test_with_errors(self) -> None:
        """Test ValidationResult with errors."""
        result = ValidationResult(
            valid=False,
            errors=["Error 1", "Error 2"],
            warnings=["Warning 1"],
        )

        assert result.valid is False
        assert len(result.errors) == 2
        assert len(result.warnings) == 1
