"""Tests for line-based file edit skills."""

import pytest

from nexus3.skill.builtin.edit_lines import edit_lines_batch_factory, edit_lines_factory
from nexus3.skill.services import ServiceContainer


class TestEditLinesSkill:
    """Shared fixtures for line-edit skill tests."""

    @pytest.fixture
    def services(self, tmp_path):
        services = ServiceContainer()
        services.set_cwd(str(tmp_path))
        return services

    @pytest.fixture
    def skill(self, services):
        return edit_lines_factory(services)

    @pytest.fixture
    def batch_skill(self, services):
        return edit_lines_batch_factory(services)

    @pytest.fixture
    def test_file(self, tmp_path):
        content = "line 1\nline 2\nline 3\nline 4\nline 5\n"
        test_file = tmp_path / "test.txt"
        test_file.write_text(content)
        return test_file


class TestSingleEdit(TestEditLinesSkill):
    """Tests for the single-range edit_lines contract."""

    def test_single_edit_schema_is_single_purpose(self, skill):
        params = skill.parameters

        assert params["required"] == ["path", "start_line", "new_content"]
        assert "edits" not in params["properties"]

    @pytest.mark.asyncio
    async def test_single_line_replace(self, skill, test_file):
        result = await skill.execute(
            path=str(test_file),
            start_line=2,
            new_content="replaced line 2",
        )

        assert result.success
        assert "Replaced line 2" in result.output
        assert test_file.read_text().splitlines() == [
            "line 1",
            "replaced line 2",
            "line 3",
            "line 4",
            "line 5",
        ]

    @pytest.mark.asyncio
    async def test_range_replace(self, skill, test_file):
        result = await skill.execute(
            path=str(test_file),
            start_line=2,
            end_line=4,
            new_content="single replacement",
        )

        assert result.success
        assert "Replaced lines 2-4" in result.output
        assert test_file.read_text().splitlines() == ["line 1", "single replacement", "line 5"]

    @pytest.mark.asyncio
    async def test_start_line_validation_zero(self, skill, test_file):
        result = await skill.execute(path=str(test_file), start_line=0, new_content="content")

        assert not result.success
        assert "minimum" in result.error.lower() or "less than" in result.error.lower()

    @pytest.mark.asyncio
    async def test_start_line_validation_negative(self, skill, test_file):
        result = await skill.execute(path=str(test_file), start_line=-1, new_content="content")

        assert not result.success
        assert "minimum" in result.error.lower() or "less than" in result.error.lower()

    @pytest.mark.asyncio
    async def test_new_content_required(self, skill, test_file):
        result = await skill.execute(path=str(test_file), start_line=2)

        assert not result.success
        assert "new_content" in result.error

    @pytest.mark.asyncio
    async def test_end_line_validation(self, skill, test_file):
        result = await skill.execute(
            path=str(test_file),
            start_line=3,
            end_line=1,
            new_content="content",
        )

        assert not result.success
        assert "end_line (1) cannot be less than start_line (3)" in result.error

    @pytest.mark.asyncio
    async def test_line_out_of_bounds_start(self, skill, test_file):
        result = await skill.execute(
            path=str(test_file),
            start_line=10,
            new_content="content",
        )

        assert not result.success
        assert "start_line 10 exceeds file length (5 lines)" in result.error

    @pytest.mark.asyncio
    async def test_line_out_of_bounds_end(self, skill, test_file):
        result = await skill.execute(
            path=str(test_file),
            start_line=3,
            end_line=10,
            new_content="content",
        )

        assert not result.success
        assert "end_line 10 exceeds file length (5 lines)" in result.error

    @pytest.mark.asyncio
    async def test_newline_handling_middle(self, skill, test_file):
        result = await skill.execute(
            path=str(test_file),
            start_line=2,
            new_content="no trailing newline",
        )

        assert result.success
        assert "no trailing newline\nline 3" in test_file.read_text()

    @pytest.mark.asyncio
    async def test_newline_handling_end(self, skill, tmp_path):
        test_file = tmp_path / "trailing.txt"
        test_file.write_text("line 1\nline 2\nline 3\n")

        result = await skill.execute(
            path=str(test_file),
            start_line=3,
            new_content="replaced last",
        )

        assert result.success
        assert test_file.read_text() == "line 1\nline 2\nreplaced last\n"

    @pytest.mark.asyncio
    async def test_non_utf8_file_rejected_with_patch_guidance(self, skill, tmp_path):
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
        result = await skill.execute(
            path=str(test_file),
            start_line=2,
            new_content="line a\nline b\nline c\n",
        )

        assert result.success
        assert test_file.read_text().splitlines() == [
            "line 1",
            "line a",
            "line b",
            "line c",
            "line 3",
            "line 4",
            "line 5",
        ]

    @pytest.mark.asyncio
    async def test_crlf_line_endings(self, skill, tmp_path):
        test_file = tmp_path / "crlf.txt"
        test_file.write_bytes(b"line 1\r\nline 2\r\nline 3\r\n")

        result = await skill.execute(
            path=str(test_file),
            start_line=2,
            new_content="replaced",
        )

        assert result.success
        assert test_file.read_bytes() == b"line 1\r\nreplaced\r\nline 3\r\n"

    @pytest.mark.asyncio
    async def test_file_not_found(self, skill, tmp_path):
        result = await skill.execute(
            path=str(tmp_path / "nonexistent.txt"),
            start_line=1,
            new_content="content",
        )

        assert not result.success
        assert "File not found" in result.error

    @pytest.mark.asyncio
    async def test_empty_content_replacement(self, skill, test_file):
        result = await skill.execute(
            path=str(test_file),
            start_line=2,
            end_line=4,
            new_content="",
        )

        assert result.success
        assert test_file.read_text().splitlines() == ["line 1", "line 5"]

    @pytest.mark.asyncio
    async def test_first_line_replacement(self, skill, test_file):
        result = await skill.execute(
            path=str(test_file),
            start_line=1,
            new_content="new first line",
        )

        assert result.success
        assert test_file.read_text().splitlines()[:2] == ["new first line", "line 2"]

    @pytest.mark.asyncio
    async def test_last_line_replacement(self, skill, test_file):
        result = await skill.execute(
            path=str(test_file),
            start_line=5,
            new_content="new last line",
        )

        assert result.success
        assert test_file.read_text().splitlines()[4] == "new last line"

    @pytest.mark.asyncio
    async def test_end_line_defaults_to_start_line(self, skill, test_file):
        result = await skill.execute(
            path=str(test_file),
            start_line=3,
            new_content="replaced",
        )

        assert result.success
        assert "Replaced line 3" in result.output
        assert test_file.read_text().splitlines()[2] == "replaced"

    @pytest.mark.asyncio
    async def test_same_start_and_end_line(self, skill, test_file):
        result = await skill.execute(
            path=str(test_file),
            start_line=3,
            end_line=3,
            new_content="replaced",
        )

        assert result.success
        assert "Replaced line 3" in result.output
        assert test_file.read_text().splitlines()[2] == "replaced"


class TestBatchEdit(TestEditLinesSkill):
    """Tests for the dedicated edit_lines_batch contract."""

    def test_batch_schema_is_batch_only(self, batch_skill):
        params = batch_skill.parameters

        assert params["required"] == ["path", "edits"]
        assert "start_line" not in params["properties"]
        assert "end_line" not in params["properties"]
        assert "new_content" not in params["properties"]

    @pytest.mark.asyncio
    async def test_batch_replaces_multiple_ranges(self, batch_skill, test_file):
        result = await batch_skill.execute(
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
        assert test_file.read_text().splitlines() == [
            "line 1",
            "batch line 2",
            "line 3",
            "batch tail",
        ]

    @pytest.mark.asyncio
    async def test_batch_applies_out_of_order_ranges_without_drift(self, batch_skill, test_file):
        result = await batch_skill.execute(
            path=str(test_file),
            edits=[
                {"start_line": 4, "new_content": "replace line 4"},
                {"start_line": 2, "end_line": 3, "new_content": "replace lines 2-3"},
            ],
        )

        assert result.success
        assert test_file.read_text().splitlines() == [
            "line 1",
            "replace lines 2-3",
            "replace line 4",
            "line 5",
        ]

    @pytest.mark.asyncio
    async def test_batch_rejects_overlapping_ranges(self, batch_skill, test_file):
        original = test_file.read_text()

        result = await batch_skill.execute(
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
    async def test_batch_rejects_empty_edits_array(self, batch_skill, test_file):
        result = await batch_skill.execute(path=str(test_file), edits=[])

        assert not result.success
        assert "edits" in result.error
        assert "non-empty" in result.error.lower()

    @pytest.mark.asyncio
    async def test_batch_rejects_legacy_top_level_single_edit_fields(
        self,
        batch_skill,
        test_file,
    ):
        result = await batch_skill.execute(
            path=str(test_file),
            start_line=2,
            edits=[{"start_line": 3, "new_content": "other"}],
        )

        assert not result.success
        assert "start_line" in result.error
        assert (
            "unexpected" in result.error.lower() or "additional properties" in result.error.lower()
        )

    @pytest.mark.asyncio
    async def test_batch_allows_empty_replacement_strings(self, batch_skill, test_file):
        result = await batch_skill.execute(
            path=str(test_file),
            edits=[{"start_line": 2, "new_content": ""}],
        )

        assert result.success
        assert test_file.read_text().splitlines() == ["line 1", "line 3", "line 4", "line 5"]
