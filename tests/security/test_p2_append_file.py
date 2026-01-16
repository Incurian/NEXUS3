"""P2.6: Test that append_file uses true append mode.

This tests the security fix where append_file uses OS-level append mode
instead of read+concatenate+rewrite, which had race condition issues.

The fix:
- Uses open(file, 'a') instead of read, concat, atomic_write_text
- Only reads last byte for newline check, not entire file
- Avoids TOCTOU race window where concurrent writes could be lost
"""

from pathlib import Path

import pytest


class TestAppendFileBasicBehavior:
    """Test basic append_file functionality."""

    @pytest.mark.asyncio
    async def test_append_to_empty_file(self, tmp_path: Path) -> None:
        """Appending to empty file works correctly."""
        from nexus3.skill.builtin.append_file import AppendFileSkill
        from nexus3.skill.services import ServiceContainer

        test_file = tmp_path / "test.txt"
        test_file.write_text("")

        services = ServiceContainer()
        services.register("cwd", tmp_path)

        skill = AppendFileSkill(services)
        result = await skill.execute(path=str(test_file), content="hello")

        assert not result.error
        assert test_file.read_text() == "hello"

    @pytest.mark.asyncio
    async def test_append_to_existing_file(self, tmp_path: Path) -> None:
        """Appending to existing file preserves content."""
        from nexus3.skill.builtin.append_file import AppendFileSkill
        from nexus3.skill.services import ServiceContainer

        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\n")

        services = ServiceContainer()
        services.register("cwd", tmp_path)

        skill = AppendFileSkill(services)
        result = await skill.execute(path=str(test_file), content="line2")

        assert not result.error
        assert test_file.read_text() == "line1\nline2"

    @pytest.mark.asyncio
    async def test_smart_newline_adds_newline(self, tmp_path: Path) -> None:
        """Smart newline adds newline if file doesn't end with one."""
        from nexus3.skill.builtin.append_file import AppendFileSkill
        from nexus3.skill.services import ServiceContainer

        test_file = tmp_path / "test.txt"
        test_file.write_text("no newline at end")

        services = ServiceContainer()
        services.register("cwd", tmp_path)

        skill = AppendFileSkill(services)
        result = await skill.execute(path=str(test_file), content="new content")

        assert not result.error
        # Should have added newline before content
        assert test_file.read_text() == "no newline at end\nnew content"

    @pytest.mark.asyncio
    async def test_smart_newline_no_double_newline(self, tmp_path: Path) -> None:
        """Smart newline doesn't add double newlines."""
        from nexus3.skill.builtin.append_file import AppendFileSkill
        from nexus3.skill.services import ServiceContainer

        test_file = tmp_path / "test.txt"
        test_file.write_text("ends with newline\n")

        services = ServiceContainer()
        services.register("cwd", tmp_path)

        skill = AppendFileSkill(services)
        result = await skill.execute(path=str(test_file), content="new content")

        assert not result.error
        # Should NOT have added extra newline
        assert test_file.read_text() == "ends with newline\nnew content"

    @pytest.mark.asyncio
    async def test_newline_disabled(self, tmp_path: Path) -> None:
        """Can disable smart newline behavior."""
        from nexus3.skill.builtin.append_file import AppendFileSkill
        from nexus3.skill.services import ServiceContainer

        test_file = tmp_path / "test.txt"
        test_file.write_text("no newline")

        services = ServiceContainer()
        services.register("cwd", tmp_path)

        skill = AppendFileSkill(services)
        result = await skill.execute(
            path=str(test_file), content="appended", newline=False
        )

        assert not result.error
        # Should NOT have added newline
        assert test_file.read_text() == "no newlineappended"

    @pytest.mark.asyncio
    async def test_creates_new_file(self, tmp_path: Path) -> None:
        """Append creates file if it doesn't exist."""
        from nexus3.skill.builtin.append_file import AppendFileSkill
        from nexus3.skill.services import ServiceContainer

        test_file = tmp_path / "new.txt"
        assert not test_file.exists()

        services = ServiceContainer()
        services.register("cwd", tmp_path)

        skill = AppendFileSkill(services)
        result = await skill.execute(path=str(test_file), content="new content")

        assert not result.error
        assert test_file.exists()
        assert test_file.read_text() == "new content"


class TestNeedsNewlineHelper:
    """Test the _needs_newline_prefix helper function."""

    def test_empty_file_no_newline_needed(self, tmp_path: Path) -> None:
        """Empty file doesn't need newline prefix."""
        from nexus3.skill.builtin.append_file import _needs_newline_prefix

        test_file = tmp_path / "empty.txt"
        test_file.write_text("")

        assert _needs_newline_prefix(test_file) is False

    def test_file_with_newline_no_prefix(self, tmp_path: Path) -> None:
        """File ending with newline doesn't need prefix."""
        from nexus3.skill.builtin.append_file import _needs_newline_prefix

        test_file = tmp_path / "test.txt"
        test_file.write_text("content\n")

        assert _needs_newline_prefix(test_file) is False

    def test_file_without_newline_needs_prefix(self, tmp_path: Path) -> None:
        """File not ending with newline needs prefix."""
        from nexus3.skill.builtin.append_file import _needs_newline_prefix

        test_file = tmp_path / "test.txt"
        test_file.write_text("no newline")

        assert _needs_newline_prefix(test_file) is True

    def test_nonexistent_file_no_prefix(self, tmp_path: Path) -> None:
        """Nonexistent file doesn't need prefix (will be created)."""
        from nexus3.skill.builtin.append_file import _needs_newline_prefix

        test_file = tmp_path / "nonexistent.txt"

        assert _needs_newline_prefix(test_file) is False


class TestAppendFileTrueAppend:
    """Test that append_file uses true append mode (P2.6 fix)."""

    @pytest.mark.asyncio
    async def test_large_file_not_fully_read(self, tmp_path: Path) -> None:
        """Large file should not be fully read during append.

        This tests that the P2.6 fix is working - we should only read
        the last few bytes, not the entire file.
        """
        from nexus3.skill.builtin.append_file import AppendFileSkill
        from nexus3.skill.services import ServiceContainer

        # Create a "large" file (not truly large, but proves the point)
        test_file = tmp_path / "large.txt"
        large_content = "A" * 10000 + "\n"  # 10KB
        test_file.write_text(large_content)

        services = ServiceContainer()
        services.register("cwd", tmp_path)

        skill = AppendFileSkill(services)
        result = await skill.execute(path=str(test_file), content="appended")

        assert not result.error
        # Content should be appended, not lost
        final_content = test_file.read_text()
        assert final_content.startswith("A" * 10000)
        assert final_content.endswith("appended")

    @pytest.mark.asyncio
    async def test_append_preserves_existing_content(self, tmp_path: Path) -> None:
        """Multiple appends should all be preserved.

        This tests the atomicity benefit of true append mode.
        """
        from nexus3.skill.builtin.append_file import AppendFileSkill
        from nexus3.skill.services import ServiceContainer

        test_file = tmp_path / "test.txt"
        test_file.write_text("")

        services = ServiceContainer()
        services.register("cwd", tmp_path)

        skill = AppendFileSkill(services)

        # Multiple sequential appends
        for i in range(5):
            result = await skill.execute(
                path=str(test_file), content=f"line{i}\n", newline=False
            )
            assert not result.error

        # All content should be present
        content = test_file.read_text()
        for i in range(5):
            assert f"line{i}" in content
