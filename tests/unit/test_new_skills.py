"""Tests for new skills: tail, file_info, append_file."""

import asyncio
import json
import stat
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from nexus3.skill.builtin.append_file import AppendFileSkill, append_file_factory
from nexus3.skill.builtin.file_info import FileInfoSkill, file_info_factory
from nexus3.skill.builtin.tail import TailSkill, tail_factory
from nexus3.skill.services import ServiceContainer


class MockServiceContainer:
    """Mock ServiceContainer for testing skills."""

    def __init__(self, **kwargs: Any) -> None:
        self._data = kwargs

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def get_tool_allowed_paths(self, tool_name: str) -> list[Path] | None:
        """Return allowed_paths from data."""
        return self._data.get("allowed_paths")


class TestTailSkill:
    """Tests for tail skill."""

    @pytest.fixture
    def skill(self) -> TailSkill:
        services = MockServiceContainer()
        return TailSkill(services)

    @pytest.fixture
    def test_file(self, tmp_path: Path) -> Path:
        """Create a test file with numbered lines."""
        file = tmp_path / "test.txt"
        content = "\n".join(f"Line {i}" for i in range(1, 21))
        file.write_text(content)
        return file

    @pytest.mark.asyncio
    async def test_default_returns_last_10_lines(self, skill: TailSkill, test_file: Path) -> None:
        """Default behavior returns last 10 lines."""
        result = await skill.execute(path=str(test_file))
        assert not result.error
        # Should have lines 11-20
        assert "11: Line 11" in result.output
        assert "20: Line 20" in result.output
        # Should not have earlier lines
        assert "10: Line 10" not in result.output

    @pytest.mark.asyncio
    async def test_custom_line_count(self, skill: TailSkill, test_file: Path) -> None:
        """Custom line count works."""
        result = await skill.execute(path=str(test_file), lines=5)
        assert not result.error
        # Should have last 5 lines
        assert "16: Line 16" in result.output
        assert "20: Line 20" in result.output
        assert "15: Line 15" not in result.output

    @pytest.mark.asyncio
    async def test_more_lines_than_file(self, skill: TailSkill, test_file: Path) -> None:
        """Requesting more lines than file has returns whole file."""
        result = await skill.execute(path=str(test_file), lines=100)
        assert not result.error
        # Should have all lines
        assert "1: Line 1" in result.output
        assert "20: Line 20" in result.output

    @pytest.mark.asyncio
    async def test_lines_must_be_positive(self, skill: TailSkill, test_file: Path) -> None:
        """Lines parameter must be at least 1."""
        result = await skill.execute(path=str(test_file), lines=0)
        assert result.error is not None
        assert "at least 1" in result.error

    @pytest.mark.asyncio
    async def test_file_not_found(self, skill: TailSkill, tmp_path: Path) -> None:
        """Returns error for non-existent file."""
        result = await skill.execute(path=str(tmp_path / "nonexistent.txt"))
        assert result.error is not None
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_path_required(self, skill: TailSkill) -> None:
        """Returns error when path not provided."""
        result = await skill.execute(path="")
        assert result.error is not None
        assert "path" in result.error.lower()

    @pytest.mark.asyncio
    async def test_sandbox_enforcement(self, tmp_path: Path) -> None:
        """Sandbox is enforced when allowed_paths configured."""
        # Create file outside sandbox
        outside = Path(tempfile.gettempdir()) / "outside.txt"
        outside.write_text("test")

        try:
            services = MockServiceContainer(allowed_paths=[tmp_path])
            skill = TailSkill(services)
            result = await skill.execute(path=str(outside))
            assert result.error is not None
        finally:
            outside.unlink()

    def test_factory_creates_skill(self) -> None:
        """Factory creates skill with proper configuration."""
        # Create mock permissions with tool_permissions to test per-tool lookup
        from unittest.mock import MagicMock
        services = ServiceContainer()
        mock_perms = MagicMock()
        mock_perms.tool_permissions = {}
        mock_perms.effective_policy.allowed_paths = [Path("/tmp")]
        services.register("permissions", mock_perms)
        skill = tail_factory(services)
        assert isinstance(skill, TailSkill)
        assert skill._allowed_paths == [Path("/tmp")]


class TestFileInfoSkill:
    """Tests for file_info skill."""

    @pytest.fixture
    def skill(self) -> FileInfoSkill:
        services = MockServiceContainer()
        return FileInfoSkill(services)

    @pytest.mark.asyncio
    async def test_file_info(self, skill: FileInfoSkill, tmp_path: Path) -> None:
        """Returns correct info for a file."""
        file = tmp_path / "test.txt"
        file.write_text("hello world")

        result = await skill.execute(path=str(file))
        assert not result.error

        info = json.loads(result.output)
        assert info["type"] == "file"
        assert info["size"] == 11
        assert info["exists"] is True
        assert "modified" in info
        assert "permissions" in info

    @pytest.mark.asyncio
    async def test_directory_info(self, skill: FileInfoSkill, tmp_path: Path) -> None:
        """Returns correct info for a directory."""
        result = await skill.execute(path=str(tmp_path))
        assert not result.error

        info = json.loads(result.output)
        assert info["type"] == "directory"
        assert info["exists"] is True

    @pytest.mark.asyncio
    async def test_nonexistent_path(self, skill: FileInfoSkill, tmp_path: Path) -> None:
        """Returns exists=false for non-existent path."""
        result = await skill.execute(path=str(tmp_path / "nonexistent"))
        assert not result.error

        info = json.loads(result.output)
        assert info["exists"] is False

    @pytest.mark.asyncio
    async def test_human_readable_size(self, skill: FileInfoSkill, tmp_path: Path) -> None:
        """Size is formatted in human-readable form."""
        file = tmp_path / "big.txt"
        file.write_text("x" * 2048)  # 2KB

        result = await skill.execute(path=str(file))
        info = json.loads(result.output)
        assert "KB" in info["size_human"]

    @pytest.mark.asyncio
    async def test_path_required(self, skill: FileInfoSkill) -> None:
        """Returns error when path not provided."""
        result = await skill.execute(path="")
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_sandbox_enforcement(self, tmp_path: Path) -> None:
        """Sandbox is enforced when allowed_paths configured."""
        outside = Path(tempfile.gettempdir()) / "outside_info.txt"
        outside.write_text("test")

        try:
            services = MockServiceContainer(allowed_paths=[tmp_path])
            skill = FileInfoSkill(services)
            result = await skill.execute(path=str(outside))
            assert result.error is not None
        finally:
            outside.unlink()

    def test_factory_creates_skill(self) -> None:
        """Factory creates skill with proper configuration."""
        services = ServiceContainer()
        services.register("allowed_paths", [Path("/tmp")])
        skill = file_info_factory(services)
        assert isinstance(skill, FileInfoSkill)


class TestAppendFileSkill:
    """Tests for append_file skill."""

    @pytest.fixture
    def skill(self) -> AppendFileSkill:
        services = MockServiceContainer()
        return AppendFileSkill(services)

    @pytest.mark.asyncio
    async def test_append_to_existing_file(self, skill: AppendFileSkill, tmp_path: Path) -> None:
        """Appends content to existing file."""
        file = tmp_path / "test.txt"
        file.write_text("Hello")

        result = await skill.execute(path=str(file), content=" World")
        assert not result.error

        assert file.read_text() == "Hello\n World"  # Newline added

    @pytest.mark.asyncio
    async def test_append_to_file_ending_with_newline(
        self, skill: AppendFileSkill, tmp_path: Path
    ) -> None:
        """No extra newline if file already ends with one."""
        file = tmp_path / "test.txt"
        file.write_text("Hello\n")

        result = await skill.execute(path=str(file), content="World")
        assert not result.error

        assert file.read_text() == "Hello\nWorld"

    @pytest.mark.asyncio
    async def test_create_new_file(self, skill: AppendFileSkill, tmp_path: Path) -> None:
        """Creates file if it doesn't exist."""
        file = tmp_path / "new.txt"

        result = await skill.execute(path=str(file), content="New content")
        assert not result.error
        assert file.exists()
        assert file.read_text() == "New content"

    @pytest.mark.asyncio
    async def test_newline_false_no_auto_newline(
        self, skill: AppendFileSkill, tmp_path: Path
    ) -> None:
        """newline=False disables automatic newline."""
        file = tmp_path / "test.txt"
        file.write_text("Hello")

        result = await skill.execute(path=str(file), content=" World", newline=False)
        assert not result.error

        assert file.read_text() == "Hello World"  # No newline added

    @pytest.mark.asyncio
    async def test_path_required(self, skill: AppendFileSkill) -> None:
        """Returns error when path not provided."""
        result = await skill.execute(path="", content="test")
        assert result.error is not None
        assert "path" in result.error.lower()

    @pytest.mark.asyncio
    async def test_content_required(self, skill: AppendFileSkill, tmp_path: Path) -> None:
        """Returns error when content not provided."""
        file = tmp_path / "test.txt"
        file.write_text("existing")

        result = await skill.execute(path=str(file), content="")
        assert result.error is not None
        assert "content" in result.error.lower()

    @pytest.mark.asyncio
    async def test_sandbox_enforcement(self, tmp_path: Path) -> None:
        """Sandbox is enforced when allowed_paths configured."""
        outside = Path(tempfile.gettempdir()) / "outside_append.txt"
        outside.write_text("test")

        try:
            services = MockServiceContainer(allowed_paths=[tmp_path])
            skill = AppendFileSkill(services)
            result = await skill.execute(path=str(outside), content="more")
            assert result.error is not None
        finally:
            outside.unlink()

    @pytest.mark.asyncio
    async def test_reports_bytes_written(self, skill: AppendFileSkill, tmp_path: Path) -> None:
        """Reports number of bytes written."""
        file = tmp_path / "test.txt"
        file.write_text("")

        result = await skill.execute(path=str(file), content="12345")
        assert not result.error
        assert "5 bytes" in result.output

    def test_factory_creates_skill(self) -> None:
        """Factory creates skill with proper configuration."""
        services = ServiceContainer()
        services.register("allowed_paths", [Path("/tmp")])
        skill = append_file_factory(services)
        assert isinstance(skill, AppendFileSkill)


class TestSkillRegistration:
    """Tests for skill registration."""

    def test_new_skills_registered(self) -> None:
        """Verify new skills are registered in the registry."""
        from nexus3.skill.builtin.registration import register_builtin_skills
        from nexus3.skill.registry import SkillRegistry
        from nexus3.skill.services import ServiceContainer

        services = ServiceContainer()
        registry = SkillRegistry(services)
        register_builtin_skills(registry)

        # New skills should be registered (check they can be retrieved)
        assert registry.get("tail") is not None
        assert registry.get("file_info") is not None
        assert registry.get("append_file") is not None

        # Verify they work
        tail = registry.get("tail")
        assert tail is not None
        assert tail.name == "tail"

        file_info = registry.get("file_info")
        assert file_info is not None
        assert file_info.name == "file_info"

        append = registry.get("append_file")
        assert append is not None
        assert append.name == "append_file"


class TestPermissionUpdates:
    """Tests for permission system updates."""

    def test_append_file_in_destructive_actions(self) -> None:
        """append_file should be in DESTRUCTIVE_ACTIONS."""
        from nexus3.core.permissions import DESTRUCTIVE_ACTIONS

        assert "append_file" in DESTRUCTIVE_ACTIONS
