"""Tests for skill enhancements: read_file offset/limit, glob exclude, grep include/context."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nexus3.skill.builtin.glob_search import GlobSkill
from nexus3.skill.builtin.grep import GrepSkill
from nexus3.skill.builtin.read_file import ReadFileSkill


class TestReadFileOffsetLimit:
    """Tests for read_file offset and limit parameters."""

    @pytest.fixture
    def skill(self) -> ReadFileSkill:
        return ReadFileSkill()

    @pytest.fixture
    def test_file(self, tmp_path: Path) -> Path:
        """Create a test file with numbered lines."""
        file = tmp_path / "test.txt"
        # Lines 1-10
        content = "\n".join(f"Line {i}" for i in range(1, 11))
        file.write_text(content)
        return file

    @pytest.mark.asyncio
    async def test_default_reads_entire_file(self, skill: ReadFileSkill, test_file: Path) -> None:
        """Default behavior reads entire file without line numbers."""
        result = await skill.execute(path=str(test_file))
        assert not result.error
        assert "Line 1" in result.output
        assert "Line 10" in result.output
        # No line numbers in default mode
        assert "1: Line 1" not in result.output

    @pytest.mark.asyncio
    async def test_offset_starts_from_line(self, skill: ReadFileSkill, test_file: Path) -> None:
        """Offset starts reading from specified line."""
        result = await skill.execute(path=str(test_file), offset=5)
        assert not result.error
        # Should start at line 5
        assert "5: Line 5" in result.output
        assert "Line 4" not in result.output

    @pytest.mark.asyncio
    async def test_limit_restricts_lines(self, skill: ReadFileSkill, test_file: Path) -> None:
        """Limit restricts number of lines returned."""
        result = await skill.execute(path=str(test_file), limit=3)
        assert not result.error
        # Should have lines 1-3
        assert "1: Line 1" in result.output
        assert "2: Line 2" in result.output
        assert "3: Line 3" in result.output
        assert "4: Line 4" not in result.output

    @pytest.mark.asyncio
    async def test_offset_and_limit_combined(self, skill: ReadFileSkill, test_file: Path) -> None:
        """Offset and limit work together."""
        result = await skill.execute(path=str(test_file), offset=3, limit=2)
        assert not result.error
        # Should have lines 3-4 only
        assert "3: Line 3" in result.output
        assert "4: Line 4" in result.output
        assert "2: Line 2" not in result.output
        assert "5: Line 5" not in result.output

    @pytest.mark.asyncio
    async def test_offset_beyond_file_returns_empty(self, skill: ReadFileSkill, test_file: Path) -> None:
        """Offset beyond file length returns empty."""
        result = await skill.execute(path=str(test_file), offset=100)
        assert not result.error
        assert result.output == ""

    @pytest.mark.asyncio
    async def test_invalid_offset_returns_error(self, skill: ReadFileSkill, test_file: Path) -> None:
        """Offset less than 1 returns error."""
        result = await skill.execute(path=str(test_file), offset=0)
        assert result.error is not None
        assert "at least 1" in result.error


class TestGlobExclude:
    """Tests for glob exclude parameter."""

    @pytest.fixture
    def skill(self) -> GlobSkill:
        return GlobSkill()

    @pytest.fixture
    def test_dir(self, tmp_path: Path) -> Path:
        """Create test directory structure."""
        # Create files
        (tmp_path / "file1.py").write_text("content")
        (tmp_path / "file2.py").write_text("content")
        # Create node_modules dir
        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / "pkg.py").write_text("content")
        # Create .git dir
        git = tmp_path / ".git"
        git.mkdir()
        (git / "config.py").write_text("content")
        # Create __pycache__
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "mod.cpython-311.pyc").write_text("content")
        return tmp_path

    @pytest.mark.asyncio
    async def test_without_exclude_finds_all(self, skill: GlobSkill, test_dir: Path) -> None:
        """Without exclude, finds all matching files."""
        result = await skill.execute(pattern="**/*.py", path=str(test_dir))
        assert not result.error
        assert "file1.py" in result.output
        assert "node_modules" in result.output or "pkg.py" in result.output

    @pytest.mark.asyncio
    async def test_exclude_single_pattern(self, skill: GlobSkill, test_dir: Path) -> None:
        """Single exclude pattern filters out matches."""
        result = await skill.execute(
            pattern="**/*.py",
            path=str(test_dir),
            exclude=["node_modules"]
        )
        assert not result.error
        assert "file1.py" in result.output
        assert "pkg.py" not in result.output
        assert "node_modules" not in result.output

    @pytest.mark.asyncio
    async def test_exclude_multiple_patterns(self, skill: GlobSkill, test_dir: Path) -> None:
        """Multiple exclude patterns all applied."""
        result = await skill.execute(
            pattern="**/*",
            path=str(test_dir),
            exclude=["node_modules", ".git", "__pycache__"]
        )
        assert not result.error
        assert "file1.py" in result.output
        # None of the excluded dirs should appear
        assert "node_modules" not in result.output
        assert ".git" not in result.output
        assert "__pycache__" not in result.output

    @pytest.mark.asyncio
    async def test_exclude_empty_list_no_effect(self, skill: GlobSkill, test_dir: Path) -> None:
        """Empty exclude list has no effect."""
        result = await skill.execute(
            pattern="**/*.py",
            path=str(test_dir),
            exclude=[]
        )
        assert not result.error
        # Should find node_modules file
        assert "pkg.py" in result.output or "node_modules" in result.output


class TestGrepIncludeContext:
    """Tests for grep include and context parameters."""

    @pytest.fixture
    def skill(self) -> GrepSkill:
        return GrepSkill()

    @pytest.fixture
    def test_dir(self, tmp_path: Path) -> Path:
        """Create test directory with various files."""
        # Python file
        py_file = tmp_path / "code.py"
        py_file.write_text("def hello():\n    print('world')\n    return True\n")

        # TypeScript file
        ts_file = tmp_path / "app.ts"
        ts_file.write_text("function hello() {\n    console.log('world');\n}\n")

        # JavaScript file
        js_file = tmp_path / "util.js"
        js_file.write_text("const x = 'hello';\nconsole.log(x);\n")

        # Text file
        txt_file = tmp_path / "readme.txt"
        txt_file.write_text("Hello from readme\n")

        return tmp_path

    @pytest.fixture
    def context_file(self, tmp_path: Path) -> Path:
        """Create file for context testing."""
        file = tmp_path / "context.txt"
        lines = [
            "Line 1: intro",
            "Line 2: setup",
            "Line 3: TARGET match here",
            "Line 4: follow-up",
            "Line 5: cleanup",
            "Line 6: another section",
            "Line 7: TARGET second match",
            "Line 8: ending",
        ]
        file.write_text("\n".join(lines))
        return file

    @pytest.mark.asyncio
    async def test_include_filters_by_extension(self, skill: GrepSkill, test_dir: Path) -> None:
        """Include filter limits search to matching files."""
        result = await skill.execute(
            pattern="hello",
            path=str(test_dir),
            include="*.py"
        )
        assert not result.error
        # Should find in .py file
        assert "code.py" in result.output
        # Should not find in .ts or .js files
        assert "app.ts" not in result.output
        assert "util.js" not in result.output

    @pytest.mark.asyncio
    async def test_include_brace_expansion(self, skill: GrepSkill, test_dir: Path) -> None:
        """Include supports brace expansion like *.{js,ts}."""
        result = await skill.execute(
            pattern="hello|console",
            path=str(test_dir),
            include="*.{js,ts}"
        )
        assert not result.error
        # Should find in both .js and .ts
        assert "app.ts" in result.output or "util.js" in result.output
        # Should not find in .py
        assert "code.py" not in result.output

    @pytest.mark.asyncio
    async def test_context_shows_surrounding_lines(
        self, skill: GrepSkill, context_file: Path
    ) -> None:
        """Context parameter shows lines before and after match."""
        result = await skill.execute(
            pattern="TARGET",
            path=str(context_file),
            context=1
        )
        assert not result.error
        # Should show context lines
        assert "Line 2" in result.output  # Before first match
        assert "Line 3" in result.output  # Match line
        assert "Line 4" in result.output  # After first match

    @pytest.mark.asyncio
    async def test_context_marks_match_lines(
        self, skill: GrepSkill, context_file: Path
    ) -> None:
        """Match lines are marked with > prefix."""
        result = await skill.execute(
            pattern="TARGET",
            path=str(context_file),
            context=1
        )
        assert not result.error
        # Match lines have > prefix
        assert ":>" in result.output
        # Context lines have space prefix
        assert ": " in result.output

    @pytest.mark.asyncio
    async def test_context_deduplicates_overlapping(
        self, skill: GrepSkill, tmp_path: Path
    ) -> None:
        """Adjacent matches don't duplicate shared context lines."""
        file = tmp_path / "adjacent.txt"
        file.write_text("A\nMATCH1\nB\nMATCH2\nC\n")

        result = await skill.execute(
            pattern="MATCH",
            path=str(file),
            context=1
        )
        assert not result.error
        # Line B should only appear once
        lines = result.output.split("\n")
        b_count = sum(1 for line in lines if ": B" in line or " B" in line)
        assert b_count <= 1

    @pytest.mark.asyncio
    async def test_context_zero_is_default_behavior(
        self, skill: GrepSkill, context_file: Path
    ) -> None:
        """Context=0 gives default grep behavior."""
        result = await skill.execute(
            pattern="TARGET",
            path=str(context_file),
            context=0
        )
        assert not result.error
        # Only match lines, no context
        assert "Line 3" in result.output
        assert "Line 2" not in result.output  # Context line not shown

    @pytest.mark.asyncio
    async def test_include_and_context_together(
        self, skill: GrepSkill, test_dir: Path
    ) -> None:
        """Include and context can be used together."""
        result = await skill.execute(
            pattern="def|return",
            path=str(test_dir),
            include="*.py",
            context=1
        )
        assert not result.error
        # Should have Python file matches with context
        assert "code.py" in result.output
        # Should show context
        lines = [l for l in result.output.split("\n") if l.strip()]
        assert len(lines) > 2  # More than just match lines
