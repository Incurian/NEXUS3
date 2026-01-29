"""Tests for edit_file skill with batched edit support."""

import pytest

from nexus3.skill.builtin.edit_file import edit_file_factory
from nexus3.skill.services import ServiceContainer


class TestEditFileSkill:
    """Tests for EditFileSkill."""

    @pytest.fixture
    def services(self, tmp_path):
        """Create ServiceContainer with tmp_path as cwd."""
        services = ServiceContainer()
        services.register("cwd", str(tmp_path))
        return services

    @pytest.fixture
    def skill(self, services):
        """Create edit_file skill instance."""
        return edit_file_factory(services)

    @pytest.fixture
    def test_file(self, tmp_path):
        """Create a test file with multiple lines."""
        content = """import os

def foo():
    x = 1
    return x

def bar():
    y = 2
    return y
"""
        test_file = tmp_path / "test.py"
        test_file.write_text(content)
        return test_file


class TestSingleEdit(TestEditFileSkill):
    """Tests for single-edit mode (existing functionality)."""

    @pytest.mark.asyncio
    async def test_string_replace_success(self, skill, test_file):
        """Test basic old->new replacement."""
        result = await skill.execute(
            path=str(test_file),
            old_string="def foo():",
            new_string="def foo() -> None:"
        )

        assert result.success
        assert "Replaced text" in result.output

        content = test_file.read_text()
        assert "def foo() -> None:" in content
        assert "def foo():" not in content

    @pytest.mark.asyncio
    async def test_string_replace_not_found(self, skill, test_file):
        """Test error when string is not found."""
        result = await skill.execute(
            path=str(test_file),
            old_string="nonexistent string",
            new_string="replacement"
        )

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_string_replace_ambiguous(self, skill, test_file):
        """Test error when string appears multiple times without replace_all."""
        result = await skill.execute(
            path=str(test_file),
            old_string="return",
            new_string="RETURN"
        )

        assert not result.success
        assert "appears" in result.error
        assert "replace_all" in result.error

    @pytest.mark.asyncio
    async def test_string_replace_all(self, skill, test_file):
        """Test replace_all=True replaces all occurrences."""
        result = await skill.execute(
            path=str(test_file),
            old_string="return",
            new_string="RETURN",
            replace_all=True
        )

        assert result.success
        assert "2 occurrence(s)" in result.output

        content = test_file.read_text()
        assert content.count("RETURN") == 2
        assert content.count("return") == 0


class TestBatchEdit(TestEditFileSkill):
    """Tests for batch edit mode (new functionality)."""

    @pytest.mark.asyncio
    async def test_batch_success(self, skill, test_file):
        """Test multiple edits in one call."""
        result = await skill.execute(
            path=str(test_file),
            edits=[
                {"old_string": "import os", "new_string": "import os\nimport sys"},
                {"old_string": "def foo():", "new_string": "def foo() -> None:"}
            ]
        )

        assert result.success
        assert "Applied 2 edits" in result.output
        assert "import os" in result.output
        assert "def foo()" in result.output

        content = test_file.read_text()
        assert "import os\nimport sys" in content
        assert "def foo() -> None:" in content

    @pytest.mark.asyncio
    async def test_batch_rollback(self, skill, test_file):
        """Test that no changes are made if any edit fails."""
        original_content = test_file.read_text()

        result = await skill.execute(
            path=str(test_file),
            edits=[
                {"old_string": "import os", "new_string": "import os\nimport sys"},
                {"old_string": "nonexistent string", "new_string": "replacement"}
            ]
        )

        assert not result.success
        assert "Batch edit failed" in result.error
        assert "no changes made" in result.error
        assert "Edit 2" in result.error
        assert "not found" in result.error

        # File should be unchanged
        assert test_file.read_text() == original_content

    @pytest.mark.asyncio
    async def test_batch_order_matters(self, skill, tmp_path):
        """Test that edits are applied sequentially - first edit changes what second targets."""
        test_file = tmp_path / "order_test.py"
        test_file.write_text("foo = 1\nbar = foo\n")

        # First edit changes "foo" to "baz"
        # Second edit should find "baz" (as changed by first edit)
        # But wait - we validate against ORIGINAL content, so this should work differently

        # Actually, let's test a case where order matters for sequential application:
        # Edit 1: "foo = 1" -> "foo = 2"
        # Edit 2: "foo = 2" -> "foo = 3" (only exists after edit 1)
        # This should fail because edit 2's old_string doesn't exist in original content

        result = await skill.execute(
            path=str(test_file),
            edits=[
                {"old_string": "foo = 1", "new_string": "foo = 2"},
                {"old_string": "foo = 2", "new_string": "foo = 3"}
            ]
        )

        # Edit 2 should fail validation since "foo = 2" isn't in original content
        assert not result.success
        assert "Edit 2" in result.error
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_batch_order_applies_sequentially(self, skill, tmp_path):
        """Test that valid edits are applied in order on in-memory content."""
        test_file = tmp_path / "sequential_test.py"
        test_file.write_text("A = 1\nB = 2\nC = 3\n")

        # All edits exist in original, applied sequentially
        result = await skill.execute(
            path=str(test_file),
            edits=[
                {"old_string": "A = 1", "new_string": "A = 10"},
                {"old_string": "B = 2", "new_string": "B = 20"},
                {"old_string": "C = 3", "new_string": "C = 30"}
            ]
        )

        assert result.success
        content = test_file.read_text()
        assert "A = 10" in content
        assert "B = 20" in content
        assert "C = 30" in content

    @pytest.mark.asyncio
    async def test_batch_mutual_exclusion(self, skill, test_file):
        """Test that edits array cannot be mixed with single-edit params."""
        result = await skill.execute(
            path=str(test_file),
            old_string="import os",
            edits=[
                {"old_string": "def foo():", "new_string": "def foo() -> None:"}
            ]
        )

        assert not result.success
        assert "Cannot use 'edits' array" in result.error
        assert "old_string" in result.error

    @pytest.mark.asyncio
    async def test_batch_mutual_exclusion_new_string(self, skill, test_file):
        """Test that edits array cannot be mixed with new_string param."""
        result = await skill.execute(
            path=str(test_file),
            new_string="replacement",
            edits=[
                {"old_string": "def foo():", "new_string": "def foo() -> None:"}
            ]
        )

        assert not result.success
        assert "Cannot use 'edits' array" in result.error

    @pytest.mark.asyncio
    async def test_batch_replace_all(self, skill, tmp_path):
        """Test that individual edits can use replace_all."""
        test_file = tmp_path / "replace_all_test.py"
        test_file.write_text("foo = 1\nfoo = 2\nbar = 3\n")

        result = await skill.execute(
            path=str(test_file),
            edits=[
                {"old_string": "foo", "new_string": "baz", "replace_all": True}
            ]
        )

        assert result.success
        assert "2 occurrences" in result.output

        content = test_file.read_text()
        assert content.count("baz") == 2
        assert content.count("foo") == 0

    @pytest.mark.asyncio
    async def test_batch_ambiguous_without_replace_all(self, skill, tmp_path):
        """Test that ambiguous edits without replace_all fail validation."""
        test_file = tmp_path / "ambiguous_test.py"
        test_file.write_text("foo = 1\nfoo = 2\nbar = 3\n")

        result = await skill.execute(
            path=str(test_file),
            edits=[
                {"old_string": "foo", "new_string": "baz"}  # No replace_all
            ]
        )

        assert not result.success
        assert "appears 2 times" in result.error
        assert "replace_all" in result.error

    @pytest.mark.asyncio
    async def test_batch_empty_edits_array(self, skill, test_file):
        """Test that empty edits array requires old_string."""
        # With empty edits, batch_mode is False, so old_string is required
        result = await skill.execute(
            path=str(test_file),
            edits=[]
        )

        assert not result.success
        assert "old_string is required" in result.error

    @pytest.mark.asyncio
    async def test_batch_line_numbers_in_output(self, skill, test_file):
        """Test that line numbers reference original file positions."""
        result = await skill.execute(
            path=str(test_file),
            edits=[
                {"old_string": "import os", "new_string": "import os\nimport sys"},
                {"old_string": "def bar():", "new_string": "def bar() -> int:"}
            ]
        )

        assert result.success
        # "import os" is on line 1
        # "def bar():" is on line 7 in original (line 6 is empty)
        assert "line 1" in result.output
        assert "line 7" in result.output

    @pytest.mark.asyncio
    async def test_batch_preserves_line_endings(self, skill, tmp_path):
        """Test that CRLF line endings are preserved in batch mode."""
        test_file = tmp_path / "crlf.py"
        test_file.write_bytes(b"import os\r\ndef foo():\r\n    pass\r\n")

        result = await skill.execute(
            path=str(test_file),
            edits=[
                {"old_string": "def foo():", "new_string": "def foo() -> None:"}
            ]
        )

        assert result.success
        content = test_file.read_bytes()
        assert b"\r\n" in content
        assert b"def foo() -> None:\r\n" in content

    @pytest.mark.asyncio
    async def test_batch_three_edits(self, skill, test_file):
        """Test multiple edits with various patterns."""
        result = await skill.execute(
            path=str(test_file),
            edits=[
                {"old_string": "import os", "new_string": "import os\nimport sys"},
                {"old_string": "x = 1", "new_string": "x = 100"},
                {"old_string": "y = 2", "new_string": "y = 200"}
            ]
        )

        assert result.success
        assert "Applied 3 edits" in result.output

        content = test_file.read_text()
        assert "import sys" in content
        assert "x = 100" in content
        assert "y = 200" in content

    @pytest.mark.asyncio
    async def test_batch_empty_old_string(self, skill, test_file):
        """Test that empty old_string in batch edit fails."""
        result = await skill.execute(
            path=str(test_file),
            edits=[
                {"old_string": "", "new_string": "something"}
            ]
        )

        assert not result.success
        assert "old_string cannot be empty" in result.error

    @pytest.mark.asyncio
    async def test_batch_edit_with_empty_new_string(self, skill, tmp_path):
        """Test that edits can delete text by using empty new_string."""
        test_file = tmp_path / "delete_test.py"
        test_file.write_text("# TODO: remove this\nkeep this\n")

        result = await skill.execute(
            path=str(test_file),
            edits=[
                {"old_string": "# TODO: remove this\n", "new_string": ""}
            ]
        )

        assert result.success
        content = test_file.read_text()
        assert "TODO" not in content
        assert "keep this" in content
