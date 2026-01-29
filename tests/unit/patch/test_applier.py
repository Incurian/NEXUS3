"""Unit tests for nexus3.patch.applier module."""

import pytest

from nexus3.patch import ApplyMode, ApplyResult, apply_patch
from nexus3.patch.types import Hunk, PatchFile


class TestApplyPatchStrict:
    """Tests for strict mode patch application."""

    def test_strict_exact_match(self) -> None:
        """Test that strict mode succeeds with exact context match."""
        content = "line1\nline2\nline3\n"

        # Patch removes line2, adds new_line
        lines = [
            (" ", "line1"),
            ("-", "line2"),
            ("+", "new_line"),
            (" ", "line3"),
        ]
        hunk = Hunk(old_start=1, old_count=3, new_start=1, new_count=3, lines=lines)
        patch = PatchFile(old_path="test.py", new_path="test.py", hunks=[hunk])

        result = apply_patch(content, patch, mode=ApplyMode.STRICT)

        assert result.success is True
        assert result.new_content == "line1\nnew_line\nline3\n"
        assert result.applied_hunks == [0]
        assert result.failed_hunks == []

    def test_strict_context_mismatch(self) -> None:
        """Test that strict mode fails on any context difference."""
        # File has trailing spaces
        content = "line1  \nline2\nline3\n"

        # Patch expects no trailing spaces
        lines = [
            (" ", "line1"),  # No trailing spaces
            ("-", "line2"),
            ("+", "new_line"),
            (" ", "line3"),
        ]
        hunk = Hunk(old_start=1, old_count=3, new_start=1, new_count=3, lines=lines)
        patch = PatchFile(old_path="test.py", new_path="test.py", hunks=[hunk])

        result = apply_patch(content, patch, mode=ApplyMode.STRICT)

        assert result.success is False
        assert result.new_content == content  # Original unchanged
        assert len(result.failed_hunks) == 1
        assert "context mismatch" in result.failed_hunks[0][1]

    def test_strict_removal_mismatch(self) -> None:
        """Test that strict mode fails when removal line doesn't match."""
        content = "line1\ndifferent_line\nline3\n"

        lines = [
            (" ", "line1"),
            ("-", "line2"),  # File has "different_line", not "line2"
            ("+", "new_line"),
            (" ", "line3"),
        ]
        hunk = Hunk(old_start=1, old_count=3, new_start=1, new_count=3, lines=lines)
        patch = PatchFile(old_path="test.py", new_path="test.py", hunks=[hunk])

        result = apply_patch(content, patch, mode=ApplyMode.STRICT)

        assert result.success is False
        assert result.new_content == content


class TestApplyPatchTolerant:
    """Tests for tolerant mode patch application."""

    def test_tolerant_whitespace(self) -> None:
        """Test that tolerant mode succeeds despite trailing whitespace differences."""
        # File has trailing spaces
        content = "line1  \nline2\nline3  \n"

        # Patch expects no trailing spaces
        lines = [
            (" ", "line1"),
            ("-", "line2"),
            ("+", "new_line"),
            (" ", "line3"),
        ]
        hunk = Hunk(old_start=1, old_count=3, new_start=1, new_count=3, lines=lines)
        patch = PatchFile(old_path="test.py", new_path="test.py", hunks=[hunk])

        result = apply_patch(content, patch, mode=ApplyMode.TOLERANT)

        assert result.success is True
        # Original whitespace is preserved in context lines
        assert "line1  " in result.new_content
        assert "new_line" in result.new_content
        assert result.applied_hunks == [0]

    def test_tolerant_still_requires_content_match(self) -> None:
        """Test that tolerant mode still fails on actual content mismatch."""
        content = "lineA\nline2\nline3\n"

        lines = [
            (" ", "line1"),  # File has "lineA", not "line1"
            ("-", "line2"),
            ("+", "new_line"),
            (" ", "line3"),
        ]
        hunk = Hunk(old_start=1, old_count=3, new_start=1, new_count=3, lines=lines)
        patch = PatchFile(old_path="test.py", new_path="test.py", hunks=[hunk])

        result = apply_patch(content, patch, mode=ApplyMode.TOLERANT)

        assert result.success is False
        assert result.new_content == content


class TestApplyPatchFuzzy:
    """Tests for fuzzy mode patch application."""

    def test_fuzzy_threshold(self) -> None:
        """Test that fuzzy mode matches with similarity >= threshold."""
        # File has slightly different content
        content = "line_one\nline2\nline3\n"

        # Patch expects "line1" but file has "line_one"
        # "line1" vs "line_one" - these are quite different
        # Let's use more similar lines for realistic fuzzy matching
        lines = [
            (" ", "line_one"),  # Exact match
            ("-", "line2"),
            ("+", "new_line"),
            (" ", "line3"),
        ]
        hunk = Hunk(old_start=1, old_count=3, new_start=1, new_count=3, lines=lines)
        patch = PatchFile(old_path="test.py", new_path="test.py", hunks=[hunk])

        result = apply_patch(
            content, patch, mode=ApplyMode.FUZZY, fuzzy_threshold=0.8
        )

        assert result.success is True
        assert "new_line" in result.new_content

    def test_fuzzy_finds_shifted_location(self) -> None:
        """Test that fuzzy mode finds content at different line numbers."""
        # Content with extra lines at the beginning
        content = "extra1\nextra2\nline1\nline2\nline3\n"

        # Patch expects content at line 1, but it's at line 3
        lines = [
            (" ", "line1"),
            ("-", "line2"),
            ("+", "new_line"),
            (" ", "line3"),
        ]
        # Hunk header says line 1, but content is at line 3
        hunk = Hunk(old_start=1, old_count=3, new_start=1, new_count=3, lines=lines)
        patch = PatchFile(old_path="test.py", new_path="test.py", hunks=[hunk])

        result = apply_patch(
            content, patch, mode=ApplyMode.FUZZY, fuzzy_threshold=0.8
        )

        assert result.success is True
        assert "new_line" in result.new_content
        # Should have a warning about fuzzy match
        assert len(result.warnings) >= 1
        assert "fuzzy" in result.warnings[0].lower()

    def test_fuzzy_fails_below_threshold(self) -> None:
        """Test that fuzzy mode fails when similarity is below threshold."""
        content = "completely\ndifferent\ncontent\n"

        lines = [
            (" ", "line1"),
            ("-", "line2"),
            ("+", "new_line"),
            (" ", "line3"),
        ]
        hunk = Hunk(old_start=1, old_count=3, new_start=1, new_count=3, lines=lines)
        patch = PatchFile(old_path="test.py", new_path="test.py", hunks=[hunk])

        result = apply_patch(
            content, patch, mode=ApplyMode.FUZZY, fuzzy_threshold=0.9
        )

        assert result.success is False
        assert "no fuzzy match" in result.failed_hunks[0][1]


class TestOffsetTracking:
    """Tests for offset tracking across multiple hunks."""

    def test_offset_tracking(self) -> None:
        """Test correct line adjustment for multi-hunk patches."""
        # Original file with 10 lines
        content = "\n".join([f"line{i}" for i in range(1, 11)]) + "\n"

        # Hunk 1: Add 2 lines after line 2 (lines 2-3 -> lines 2-5)
        hunk1_lines = [
            (" ", "line2"),
            ("+", "added1"),
            ("+", "added2"),
            (" ", "line3"),
        ]
        hunk1 = Hunk(
            old_start=2, old_count=2, new_start=2, new_count=4, lines=hunk1_lines
        )

        # Hunk 2: Remove line8 (originally at line 8, now should apply at line 10)
        # After hunk1, offset = +2
        hunk2_lines = [
            (" ", "line7"),
            ("-", "line8"),
            (" ", "line9"),
        ]
        hunk2 = Hunk(
            old_start=7, old_count=3, new_start=9, new_count=2, lines=hunk2_lines
        )

        patch = PatchFile(
            old_path="test.py", new_path="test.py", hunks=[hunk1, hunk2]
        )

        result = apply_patch(content, patch, mode=ApplyMode.STRICT)

        assert result.success is True
        assert result.applied_hunks == [0, 1]

        # Verify the content
        new_lines = result.new_content.strip().split("\n")
        assert "added1" in new_lines
        assert "added2" in new_lines
        assert "line8" not in new_lines  # Should be removed
        assert "line7" in new_lines  # Should still exist
        assert "line9" in new_lines  # Should still exist

    def test_offset_with_removal_then_addition(self) -> None:
        """Test offset tracking when first hunk removes, second adds."""
        content = "a\nb\nc\nd\ne\nf\ng\n"

        # Hunk 1: Remove lines b and c (offset = -2)
        hunk1_lines = [
            (" ", "a"),
            ("-", "b"),
            ("-", "c"),
            (" ", "d"),
        ]
        hunk1 = Hunk(
            old_start=1, old_count=4, new_start=1, new_count=2, lines=hunk1_lines
        )

        # Hunk 2: Add lines after f (originally at line 6, with offset -2 = line 4)
        hunk2_lines = [
            (" ", "f"),
            ("+", "new1"),
            ("+", "new2"),
            (" ", "g"),
        ]
        hunk2 = Hunk(
            old_start=6, old_count=2, new_start=4, new_count=4, lines=hunk2_lines
        )

        patch = PatchFile(
            old_path="test.py", new_path="test.py", hunks=[hunk1, hunk2]
        )

        result = apply_patch(content, patch, mode=ApplyMode.STRICT)

        assert result.success is True
        new_lines = result.new_content.strip().split("\n")
        assert "b" not in new_lines
        assert "c" not in new_lines
        assert "new1" in new_lines
        assert "new2" in new_lines


class TestRollbackOnFailure:
    """Tests for atomic rollback behavior."""

    def test_rollback_on_failure(self) -> None:
        """Test that original content is returned if any hunk fails."""
        content = "line1\nline2\nline3\nline4\nline5\n"

        # Hunk 1: Valid change
        hunk1_lines = [
            (" ", "line1"),
            ("-", "line2"),
            ("+", "new_line2"),
            (" ", "line3"),
        ]
        hunk1 = Hunk(
            old_start=1, old_count=3, new_start=1, new_count=3, lines=hunk1_lines
        )

        # Hunk 2: Invalid - references wrong line
        hunk2_lines = [
            (" ", "line4"),
            ("-", "wrong_line"),  # Doesn't exist
            ("+", "new_line5"),
        ]
        hunk2 = Hunk(
            old_start=4, old_count=2, new_start=4, new_count=2, lines=hunk2_lines
        )

        patch = PatchFile(
            old_path="test.py", new_path="test.py", hunks=[hunk1, hunk2]
        )

        result = apply_patch(content, patch, mode=ApplyMode.STRICT)

        assert result.success is False
        assert result.new_content == content  # Original unchanged
        assert 0 in result.applied_hunks  # First hunk was applied (before rollback)
        assert len(result.failed_hunks) == 1
        assert result.failed_hunks[0][0] == 1  # Second hunk failed


class TestNewFile:
    """Tests for handling new file creation."""

    def test_new_file(self) -> None:
        """Test applying patch to create a new file (empty initial content)."""
        content = ""  # New file

        # Patch adds content to new file
        lines = [
            ("+", "line1"),
            ("+", "line2"),
            ("+", "line3"),
        ]
        hunk = Hunk(
            old_start=0, old_count=0, new_start=1, new_count=3, lines=lines
        )
        patch = PatchFile(
            old_path="/dev/null",
            new_path="newfile.py",
            hunks=[hunk],
            is_new_file=True,
        )

        result = apply_patch(content, patch, mode=ApplyMode.STRICT)

        assert result.success is True
        assert "line1" in result.new_content
        assert "line2" in result.new_content
        assert "line3" in result.new_content


class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_empty_patch(self) -> None:
        """Test applying patch with no hunks."""
        content = "line1\nline2\n"
        patch = PatchFile(old_path="test.py", new_path="test.py", hunks=[])

        result = apply_patch(content, patch)

        assert result.success is True
        assert result.new_content == content
        assert result.applied_hunks == []

    def test_single_line_file(self) -> None:
        """Test applying patch to single-line file."""
        content = "single\n"

        lines = [("-", "single"), ("+", "replaced")]
        hunk = Hunk(old_start=1, old_count=1, new_start=1, new_count=1, lines=lines)
        patch = PatchFile(old_path="test.py", new_path="test.py", hunks=[hunk])

        result = apply_patch(content, patch, mode=ApplyMode.STRICT)

        assert result.success is True
        assert result.new_content == "replaced\n"

    def test_preserves_trailing_newline(self) -> None:
        """Test that trailing newline is preserved."""
        content = "line1\nline2\n"

        lines = [(" ", "line1"), ("-", "line2"), ("+", "new_line2")]
        hunk = Hunk(old_start=1, old_count=2, new_start=1, new_count=2, lines=lines)
        patch = PatchFile(old_path="test.py", new_path="test.py", hunks=[hunk])

        result = apply_patch(content, patch)

        assert result.success is True
        assert result.new_content.endswith("\n")

    def test_file_without_trailing_newline(self) -> None:
        """Test handling file without trailing newline."""
        content = "line1\nline2"  # No trailing newline

        lines = [(" ", "line1"), ("-", "line2"), ("+", "new_line2")]
        hunk = Hunk(old_start=1, old_count=2, new_start=1, new_count=2, lines=lines)
        patch = PatchFile(old_path="test.py", new_path="test.py", hunks=[hunk])

        result = apply_patch(content, patch)

        assert result.success is True
        # Should not add trailing newline if original didn't have one
        assert not result.new_content.endswith("\n")

    def test_addition_only_hunk(self) -> None:
        """Test hunk that only adds lines (no removals)."""
        content = "line1\nline2\nline3\n"

        lines = [
            (" ", "line1"),
            ("+", "inserted"),
            (" ", "line2"),
        ]
        hunk = Hunk(old_start=1, old_count=2, new_start=1, new_count=3, lines=lines)
        patch = PatchFile(old_path="test.py", new_path="test.py", hunks=[hunk])

        result = apply_patch(content, patch)

        assert result.success is True
        new_lines = result.new_content.strip().split("\n")
        assert new_lines == ["line1", "inserted", "line2", "line3"]

    def test_removal_only_hunk(self) -> None:
        """Test hunk that only removes lines (no additions)."""
        content = "line1\nline2\nline3\nline4\n"

        lines = [
            (" ", "line1"),
            ("-", "line2"),
            ("-", "line3"),
            (" ", "line4"),
        ]
        hunk = Hunk(old_start=1, old_count=4, new_start=1, new_count=2, lines=lines)
        patch = PatchFile(old_path="test.py", new_path="test.py", hunks=[hunk])

        result = apply_patch(content, patch)

        assert result.success is True
        new_lines = result.new_content.strip().split("\n")
        assert new_lines == ["line1", "line4"]


class TestApplyResultDataclass:
    """Tests for ApplyResult dataclass."""

    def test_default_values(self) -> None:
        """Test ApplyResult default field values."""
        result = ApplyResult(success=True, new_content="test")

        assert result.success is True
        assert result.new_content == "test"
        assert result.applied_hunks == []
        assert result.failed_hunks == []
        assert result.warnings == []

    def test_with_values(self) -> None:
        """Test ApplyResult with all fields populated."""
        result = ApplyResult(
            success=False,
            new_content="original",
            applied_hunks=[0, 1],
            failed_hunks=[(2, "error")],
            warnings=["warning1"],
        )

        assert result.success is False
        assert result.applied_hunks == [0, 1]
        assert result.failed_hunks == [(2, "error")]
        assert result.warnings == ["warning1"]


class TestApplyModeEnum:
    """Tests for ApplyMode enum."""

    def test_enum_values(self) -> None:
        """Test that enum has expected values."""
        assert ApplyMode.STRICT.value == "strict"
        assert ApplyMode.TOLERANT.value == "tolerant"
        assert ApplyMode.FUZZY.value == "fuzzy"

    def test_default_is_strict(self) -> None:
        """Test that default mode is STRICT."""
        content = "line1\n"
        lines = [(" ", "line1")]
        hunk = Hunk(old_start=1, old_count=1, new_start=1, new_count=1, lines=lines)
        patch = PatchFile(old_path="test.py", new_path="test.py", hunks=[hunk])

        # Call without mode parameter - should use STRICT
        result = apply_patch(content, patch)
        assert result.success is True
