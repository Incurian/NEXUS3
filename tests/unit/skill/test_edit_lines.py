"""Tests for edit_lines skill."""

import pytest

from nexus3.skill.builtin.edit_lines import edit_lines_factory
from nexus3.skill.services import ServiceContainer


class TestEditLinesSkill:
    """Tests for EditLinesSkill."""

    @pytest.fixture
    def services(self, tmp_path):
        """Create ServiceContainer with tmp_path as cwd."""
        services = ServiceContainer()
        services.set_cwd(str(tmp_path))
        return services

    @pytest.fixture
    def skill(self, services):
        """Create edit_lines skill instance."""
        return edit_lines_factory(services)

    @pytest.fixture
    def test_file(self, tmp_path):
        """Create a test file with multiple lines."""
        content = "line 1\nline 2\nline 3\nline 4\nline 5\n"
        test_file = tmp_path / "test.txt"
        test_file.write_text(content)
        return test_file

    @pytest.mark.asyncio
    async def test_single_line_replace(self, skill, test_file):
        """Test replacing a single line."""
        result = await skill.execute(
            path=str(test_file),
            start_line=2,
            new_content="replaced line 2"
        )

        assert result.success
        assert "Replaced line 2" in result.output

        content = test_file.read_text()
        lines = content.splitlines()
        assert lines[0] == "line 1"
        assert lines[1] == "replaced line 2"
        assert lines[2] == "line 3"
        assert len(lines) == 5

    @pytest.mark.asyncio
    async def test_range_replace(self, skill, test_file):
        """Test replacing a range of lines (start_line to end_line)."""
        result = await skill.execute(
            path=str(test_file),
            start_line=2,
            end_line=4,
            new_content="single replacement"
        )

        assert result.success
        assert "Replaced lines 2-4" in result.output

        content = test_file.read_text()
        lines = content.splitlines()
        assert lines[0] == "line 1"
        assert lines[1] == "single replacement"
        assert lines[2] == "line 5"
        assert len(lines) == 3

    @pytest.mark.asyncio
    async def test_start_line_validation_zero(self, skill, test_file):
        """Test error when start_line is 0."""
        result = await skill.execute(
            path=str(test_file),
            start_line=0,
            new_content="content"
        )

        assert not result.success
        assert "minimum" in result.error.lower() or "less than" in result.error.lower()

    @pytest.mark.asyncio
    async def test_start_line_validation_negative(self, skill, test_file):
        """Test error when start_line is negative."""
        result = await skill.execute(
            path=str(test_file),
            start_line=-1,
            new_content="content"
        )

        assert not result.success
        assert "minimum" in result.error.lower() or "less than" in result.error.lower()

    @pytest.mark.asyncio
    async def test_new_content_required_in_single_mode(self, skill, test_file):
        """Single-edit mode should still require new_content explicitly."""
        result = await skill.execute(
            path=str(test_file),
            start_line=2,
        )

        assert not result.success
        assert "new_content is required" in result.error

    @pytest.mark.asyncio
    async def test_end_line_validation(self, skill, test_file):
        """Test error when end_line is less than start_line."""
        result = await skill.execute(
            path=str(test_file),
            start_line=3,
            end_line=1,
            new_content="content"
        )

        assert not result.success
        assert "end_line (1) cannot be less than start_line (3)" in result.error

    @pytest.mark.asyncio
    async def test_line_out_of_bounds_start(self, skill, test_file):
        """Test error when start_line exceeds file length."""
        result = await skill.execute(
            path=str(test_file),
            start_line=10,
            new_content="content"
        )

        assert not result.success
        assert "start_line 10 exceeds file length (5 lines)" in result.error

    @pytest.mark.asyncio
    async def test_line_out_of_bounds_end(self, skill, test_file):
        """Test error when end_line exceeds file length."""
        result = await skill.execute(
            path=str(test_file),
            start_line=3,
            end_line=10,
            new_content="content"
        )

        assert not result.success
        assert "end_line 10 exceeds file length (5 lines)" in result.error

    @pytest.mark.asyncio
    async def test_newline_handling_middle(self, skill, test_file):
        """Test that newline is added when replacing in the middle of file."""
        result = await skill.execute(
            path=str(test_file),
            start_line=2,
            new_content="no trailing newline"
        )

        assert result.success
        content = test_file.read_text()
        # The replacement should have a newline added
        assert "no trailing newline\nline 3" in content

    @pytest.mark.asyncio
    async def test_newline_handling_end(self, skill, tmp_path):
        """Test that trailing newline state is preserved at end of file."""
        # Create file with trailing newline
        test_file = tmp_path / "trailing.txt"
        test_file.write_text("line 1\nline 2\nline 3\n")

        skill = edit_lines_factory(ServiceContainer())

        result = await skill.execute(
            path=str(test_file),
            start_line=3,
            new_content="replaced last"
        )

        assert result.success
        content = test_file.read_text()
        assert content == "line 1\nline 2\nreplaced last\n"

    @pytest.mark.asyncio
    async def test_non_utf8_file_rejected_with_patch_guidance(self, skill, tmp_path):
        """Non-UTF8 files should fail closed with byte-strict patch guidance."""
        test_file = tmp_path / "non_utf8.txt"
        test_file.write_bytes(b"prefix\xffsuffix\n")

        result = await skill.execute(
            path=str(test_file),
            start_line=1,
            new_content="replacement",
        )

        assert not result.success
        assert "valid UTF-8 text" in result.error
        assert "byte_strict" in result.error

    @pytest.mark.asyncio
    async def test_newline_content_preserved(self, skill, test_file):
        """Test that content with explicit newlines is preserved."""
        result = await skill.execute(
            path=str(test_file),
            start_line=2,
            new_content="line a\nline b\nline c\n"
        )

        assert result.success
        content = test_file.read_text()
        lines = content.splitlines()
        assert lines[0] == "line 1"
        assert lines[1] == "line a"
        assert lines[2] == "line b"
        assert lines[3] == "line c"
        assert lines[4] == "line 3"

    @pytest.mark.asyncio
    async def test_crlf_line_endings(self, skill, tmp_path):
        """Test that CRLF line endings are preserved."""
        test_file = tmp_path / "crlf.txt"
        test_file.write_bytes(b"line 1\r\nline 2\r\nline 3\r\n")

        result = await skill.execute(
            path=str(test_file),
            start_line=2,
            new_content="replaced"
        )

        assert result.success
        content = test_file.read_bytes()
        # Line endings should be preserved as CRLF
        assert b"\r\n" in content
        assert content == b"line 1\r\nreplaced\r\nline 3\r\n"

    @pytest.mark.asyncio
    async def test_file_not_found(self, skill, tmp_path):
        """Test error when file doesn't exist."""
        result = await skill.execute(
            path=str(tmp_path / "nonexistent.txt"),
            start_line=1,
            new_content="content"
        )

        assert not result.success
        assert "File not found" in result.error

    @pytest.mark.asyncio
    async def test_empty_content_replacement(self, skill, test_file):
        """Test replacing lines with empty content (deleting lines)."""
        result = await skill.execute(
            path=str(test_file),
            start_line=2,
            end_line=4,
            new_content=""
        )

        assert result.success
        content = test_file.read_text()
        lines = content.splitlines()
        # Lines 2-4 should be deleted
        assert lines[0] == "line 1"
        assert lines[1] == "line 5"
        assert len(lines) == 2

    @pytest.mark.asyncio
    async def test_first_line_replacement(self, skill, test_file):
        """Test replacing the first line."""
        result = await skill.execute(
            path=str(test_file),
            start_line=1,
            new_content="new first line"
        )

        assert result.success
        content = test_file.read_text()
        lines = content.splitlines()
        assert lines[0] == "new first line"
        assert lines[1] == "line 2"

    @pytest.mark.asyncio
    async def test_last_line_replacement(self, skill, test_file):
        """Test replacing the last line."""
        result = await skill.execute(
            path=str(test_file),
            start_line=5,
            new_content="new last line"
        )

        assert result.success
        content = test_file.read_text()
        lines = content.splitlines()
        assert lines[4] == "new last line"
        assert len(lines) == 5

    @pytest.mark.asyncio
    async def test_end_line_defaults_to_start_line(self, skill, test_file):
        """Test that end_line defaults to start_line when not provided."""
        result = await skill.execute(
            path=str(test_file),
            start_line=3,
            new_content="replaced"
        )

        assert result.success
        assert "Replaced line 3" in result.output  # Single line, not range

        content = test_file.read_text()
        lines = content.splitlines()
        assert lines[2] == "replaced"
        assert len(lines) == 5  # Same number of lines

    @pytest.mark.asyncio
    async def test_same_start_and_end_line(self, skill, test_file):
        """Test when start_line equals end_line explicitly."""
        result = await skill.execute(
            path=str(test_file),
            start_line=3,
            end_line=3,
            new_content="replaced"
        )

        assert result.success
        assert "Replaced line 3" in result.output  # Should show single line format

        content = test_file.read_text()
        lines = content.splitlines()
        assert lines[2] == "replaced"

    @pytest.mark.asyncio
    async def test_batch_replaces_multiple_ranges(self, skill, test_file):
        """Batch mode applies multiple line-range edits atomically."""
        result = await skill.execute(
            path=str(test_file),
            edits=[
                {"start_line": 2, "new_content": "batch line 2"},
                {"start_line": 4, "end_line": 5, "new_content": "batch tail"},
            ],
        )

        assert result.success
        assert "Applied 2 line edit(s)" in result.output
        assert "line 2" in result.output
        assert "lines 4-5" in result.output

        content = test_file.read_text().splitlines()
        assert content == ["line 1", "batch line 2", "line 3", "batch tail"]

    @pytest.mark.asyncio
    async def test_batch_applies_out_of_order_ranges_without_drift(self, skill, test_file):
        """Batch mode should use original line numbers, not caller ordering."""
        result = await skill.execute(
            path=str(test_file),
            edits=[
                {"start_line": 4, "new_content": "replace line 4"},
                {"start_line": 2, "end_line": 3, "new_content": "replace lines 2-3"},
            ],
        )

        assert result.success
        content = test_file.read_text().splitlines()
        assert content == ["line 1", "replace lines 2-3", "replace line 4", "line 5"]

    @pytest.mark.asyncio
    async def test_batch_rejects_overlapping_ranges(self, skill, test_file):
        """Overlapping batch ranges should fail closed without changing the file."""
        original = test_file.read_text()

        result = await skill.execute(
            path=str(test_file),
            edits=[
                {"start_line": 2, "end_line": 3, "new_content": "first"},
                {"start_line": 3, "end_line": 4, "new_content": "second"},
            ],
        )

        assert not result.success
        assert "Batch edit failed" in result.error
        assert "overlaps" in result.error
        assert test_file.read_text() == original

    @pytest.mark.asyncio
    async def test_batch_rejects_empty_edits_array(self, skill, test_file):
        """Providing an empty edits array should fail as batch mode, not single mode."""
        result = await skill.execute(
            path=str(test_file),
            edits=[],
        )

        assert not result.success
        assert "edits array cannot be empty" in result.error

    @pytest.mark.asyncio
    async def test_batch_rejects_mixed_single_edit_parameters(self, skill, test_file):
        """Batch mode should not accept top-level line edit fields."""
        result = await skill.execute(
            path=str(test_file),
            start_line=2,
            new_content="replacement",
            edits=[{"start_line": 3, "new_content": "other"}],
        )

        assert not result.success
        assert "Cannot use 'edits' array" in result.error

    @pytest.mark.asyncio
    async def test_batch_allows_empty_placeholder_single_edit_fields(self, skill, test_file):
        """Exact empty placeholder single-edit fields should not trip mixed-mode rejection."""
        result = await skill.execute(
            path=str(test_file),
            new_content="",
            edits=[{"start_line": 2, "new_content": "placeholder-safe"}],
        )

        assert result.success
        assert "Applied 1 line edit(s)" in result.output
        assert test_file.read_text().splitlines()[1] == "placeholder-safe"
