"""Tests for regex_replace skill."""

import tempfile
from pathlib import Path

import pytest

from nexus3.skill.builtin.regex_replace import (
    MAX_REPLACEMENTS,
    RegexReplaceSkill,
    regex_replace_factory,
)
from nexus3.skill.services import ServiceContainer


class TestRegexReplaceBasic:
    """Basic tests for regex_replace skill."""

    @pytest.fixture
    def skill(self) -> RegexReplaceSkill:
        return RegexReplaceSkill()

    @pytest.fixture
    def test_file(self, tmp_path: Path) -> Path:
        """Create a test file."""
        file = tmp_path / "test.txt"
        file.write_text("Hello world\nHello again\nGoodbye world\n")
        return file

    @pytest.mark.asyncio
    async def test_simple_replacement(
        self, skill: RegexReplaceSkill, test_file: Path
    ) -> None:
        """Simple pattern replacement works."""
        result = await skill.execute(
            path=str(test_file),
            pattern="Hello",
            replacement="Hi"
        )
        assert not result.error
        assert "2 match" in result.output

        content = test_file.read_text()
        assert "Hi world" in content
        assert "Hi again" in content
        assert "Hello" not in content

    @pytest.mark.asyncio
    async def test_regex_pattern(
        self, skill: RegexReplaceSkill, test_file: Path
    ) -> None:
        """Regex pattern with special chars works."""
        result = await skill.execute(
            path=str(test_file),
            pattern=r"\bworld\b",
            replacement="universe"
        )
        assert not result.error
        assert "2 match" in result.output

        content = test_file.read_text()
        assert "Hello universe" in content
        assert "Goodbye universe" in content

    @pytest.mark.asyncio
    async def test_backreference(
        self, skill: RegexReplaceSkill, tmp_path: Path
    ) -> None:
        """Backreferences in replacement work."""
        file = tmp_path / "code.py"
        file.write_text("from oldmodule import foo\nfrom oldmodule import bar\n")

        result = await skill.execute(
            path=str(file),
            pattern=r"from oldmodule import (\w+)",
            replacement=r"from newmodule import \1"
        )
        assert not result.error

        content = file.read_text()
        assert "from newmodule import foo" in content
        assert "from newmodule import bar" in content

    @pytest.mark.asyncio
    async def test_count_limits_replacements(
        self, skill: RegexReplaceSkill, test_file: Path
    ) -> None:
        """Count parameter limits replacements."""
        result = await skill.execute(
            path=str(test_file),
            pattern="Hello",
            replacement="Hi",
            count=1
        )
        assert not result.error
        assert "1 match" in result.output

        content = test_file.read_text()
        assert content.count("Hi") == 1
        assert content.count("Hello") == 1  # One still left

    @pytest.mark.asyncio
    async def test_no_matches(
        self, skill: RegexReplaceSkill, test_file: Path
    ) -> None:
        """Returns message when no matches found."""
        result = await skill.execute(
            path=str(test_file),
            pattern="NOTFOUND",
            replacement="X"
        )
        assert not result.error
        assert "No matches" in result.output

        # File unchanged
        assert "Hello world" in test_file.read_text()


class TestRegexReplaceFlags:
    """Tests for regex flags."""

    @pytest.fixture
    def skill(self) -> RegexReplaceSkill:
        return RegexReplaceSkill()

    @pytest.mark.asyncio
    async def test_ignore_case(self, skill: RegexReplaceSkill, tmp_path: Path) -> None:
        """Case-insensitive matching works."""
        file = tmp_path / "test.txt"
        file.write_text("HELLO hello HeLLo\n")

        result = await skill.execute(
            path=str(file),
            pattern="hello",
            replacement="hi",
            ignore_case=True
        )
        assert not result.error
        assert "3 match" in result.output
        assert file.read_text() == "hi hi hi\n"

    @pytest.mark.asyncio
    async def test_multiline(self, skill: RegexReplaceSkill, tmp_path: Path) -> None:
        """Multiline flag makes ^ and $ match line boundaries."""
        file = tmp_path / "test.txt"
        file.write_text("start of line 1\nstart of line 2\nend\n")

        result = await skill.execute(
            path=str(file),
            pattern="^start",
            replacement="BEGIN",
            multiline=True
        )
        assert not result.error
        assert "2 match" in result.output

        content = file.read_text()
        assert "BEGIN of line 1" in content
        assert "BEGIN of line 2" in content

    @pytest.mark.asyncio
    async def test_dotall(self, skill: RegexReplaceSkill, tmp_path: Path) -> None:
        """Dotall flag makes . match newlines."""
        file = tmp_path / "test.txt"
        file.write_text('"""docstring\nspans\nlines"""')

        result = await skill.execute(
            path=str(file),
            pattern=r'""".*?"""',
            replacement='"""new doc"""',
            dotall=True
        )
        assert not result.error
        assert file.read_text() == '"""new doc"""'


class TestRegexReplaceSafety:
    """Tests for safety features."""

    @pytest.fixture
    def skill(self) -> RegexReplaceSkill:
        return RegexReplaceSkill()

    @pytest.mark.asyncio
    async def test_path_required(self, skill: RegexReplaceSkill) -> None:
        """Path is required."""
        result = await skill.execute(path="", pattern="x", replacement="y")
        assert result.error
        assert "Path" in result.error

    @pytest.mark.asyncio
    async def test_pattern_required(self, skill: RegexReplaceSkill) -> None:
        """Pattern is required."""
        result = await skill.execute(path="/tmp/x", pattern="", replacement="y")
        assert result.error
        assert "Pattern" in result.error

    @pytest.mark.asyncio
    async def test_invalid_regex_rejected(
        self, skill: RegexReplaceSkill, tmp_path: Path
    ) -> None:
        """Invalid regex pattern returns error."""
        file = tmp_path / "test.txt"
        file.write_text("test")

        result = await skill.execute(
            path=str(file),
            pattern="[unclosed",
            replacement="x"
        )
        assert result.error
        assert "Invalid regex" in result.error

    @pytest.mark.asyncio
    async def test_file_not_found(self, skill: RegexReplaceSkill) -> None:
        """Returns error for non-existent file."""
        result = await skill.execute(
            path="/nonexistent/file.txt",
            pattern="x",
            replacement="y"
        )
        assert result.error
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_too_many_matches_blocked(
        self, skill: RegexReplaceSkill, tmp_path: Path
    ) -> None:
        """Too many matches without count parameter returns error."""
        file = tmp_path / "big.txt"
        # Create file with more than MAX_REPLACEMENTS matches
        file.write_text("x " * (MAX_REPLACEMENTS + 100))

        result = await skill.execute(
            path=str(file),
            pattern="x",
            replacement="y"
        )
        assert result.error
        assert str(MAX_REPLACEMENTS) in result.error
        assert "count" in result.error.lower()

    @pytest.mark.asyncio
    async def test_sandbox_enforced(self, tmp_path: Path) -> None:
        """Sandbox is enforced when allowed_paths set."""
        outside = Path(tempfile.gettempdir()) / "outside_regex.txt"
        outside.write_text("test")

        try:
            skill = RegexReplaceSkill(allowed_paths=[tmp_path])
            result = await skill.execute(
                path=str(outside),
                pattern="test",
                replacement="new"
            )
            assert result.error
            assert "outside" in result.error.lower() or "sandbox" in result.error.lower()
        finally:
            outside.unlink()

    @pytest.mark.asyncio
    async def test_replacement_no_change(
        self, skill: RegexReplaceSkill, tmp_path: Path
    ) -> None:
        """Returns message when replacement produces no change."""
        file = tmp_path / "test.txt"
        file.write_text("hello")

        result = await skill.execute(
            path=str(file),
            pattern="hello",
            replacement="hello"  # Same as original
        )
        assert not result.error
        assert "no changes" in result.output.lower()


class TestRegexReplaceFactory:
    """Tests for regex_replace factory."""

    def test_factory_creates_skill(self) -> None:
        """Factory creates skill with configuration."""
        services = ServiceContainer()
        services.register("allowed_paths", [Path("/tmp")])

        skill = regex_replace_factory(services)
        assert isinstance(skill, RegexReplaceSkill)
        assert skill._allowed_paths == [Path("/tmp")]


class TestRegexReplaceRegistration:
    """Tests for regex_replace skill registration."""

    def test_regex_replace_registered(self) -> None:
        """regex_replace skill is registered."""
        from nexus3.skill.builtin.registration import register_builtin_skills
        from nexus3.skill.registry import SkillRegistry

        services = ServiceContainer()
        registry = SkillRegistry(services)
        register_builtin_skills(registry)

        skill = registry.get("regex_replace")
        assert skill is not None
        assert skill.name == "regex_replace"

    def test_regex_replace_in_destructive_actions(self) -> None:
        """regex_replace is in DESTRUCTIVE_ACTIONS."""
        from nexus3.core.permissions import DESTRUCTIVE_ACTIONS

        assert "regex_replace" in DESTRUCTIVE_ACTIONS
