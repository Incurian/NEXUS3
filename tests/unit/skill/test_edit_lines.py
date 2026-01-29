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
        services.register("cwd", str(tmp_path))
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
        assert "start_line must be >= 1" in result.error

    @pytest.mark.asyncio
    async def test_start_line_validation_negative(self, skill, test_file):
        """Test error when start_line is negative."""
        result = await skill.execute(
            path=str(test_file),
            start_line=-1,
            new_content="content"
        )

        assert not result.success
        assert "start_line must be >= 1" in result.error

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
        """Test that newline is preserved when replacing at end of file."""
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
        # When replacing the last line, we don't force add a newline
        assert content == "line 1\nline 2\nreplaced last"

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
