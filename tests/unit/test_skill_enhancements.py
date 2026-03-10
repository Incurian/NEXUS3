"""Tests for skill enhancements: read_file offset/limit, glob exclude, grep include/context."""

import base64
import json
from pathlib import Path

import pytest

from nexus3.skill.builtin import grep as grep_module
from nexus3.skill.builtin.glob_search import GlobSkill, glob_factory
from nexus3.skill.builtin.grep import GrepSkill, grep_factory
from nexus3.skill.builtin.read_file import ReadFileSkill, read_file_factory
from nexus3.skill.services import ServiceContainer


def _make_services(
    *,
    allowed_paths: list[Path] | None = None,
    blocked_paths: list[Path] | None = None,
    permission_level: object | None = None,
    cwd: Path | str | None = None,
) -> ServiceContainer:
    """Build a real ServiceContainer for skill factory tests."""
    services = ServiceContainer()
    # Compatibility key still used by get_tool_allowed_paths() fallback paths in tests.
    services.register_runtime_compat("allowed_paths", allowed_paths)
    if blocked_paths is not None:
        services.register("blocked_paths", blocked_paths)
    if permission_level is not None:
        services.register("permission_level", permission_level)
    if cwd is not None:
        services.set_cwd(cwd)
    return services


class TestReadFileOffsetLimit:
    """Tests for read_file offset and limit parameters."""

    @pytest.fixture
    def skill(self) -> ReadFileSkill:
        # Use factory to get validation wrapper
        services = _make_services(allowed_paths=None)
        return read_file_factory(services)

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
        """Default behavior reads entire file with line numbers (P2.5 streaming)."""
        result = await skill.execute(path=str(test_file))
        assert not result.error
        # P2.5: Streaming read always uses line numbers
        assert "1: Line 1" in result.output
        assert "10: Line 10" in result.output

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
    async def test_start_line_end_line_aliases(
        self,
        skill: ReadFileSkill,
        test_file: Path,
    ) -> None:
        """start_line/end_line aliases map to the same read window."""
        result = await skill.execute(path=str(test_file), start_line=3, end_line=4)

        assert not result.error
        assert "3: Line 3" in result.output
        assert "4: Line 4" in result.output
        assert "2: Line 2" not in result.output
        assert "5: Line 5" not in result.output

    @pytest.mark.asyncio
    async def test_alias_and_canonical_params_can_match(
        self,
        skill: ReadFileSkill,
        test_file: Path,
    ) -> None:
        """Mixed canonical and alias params are accepted when they describe the same window."""
        result = await skill.execute(
            path=str(test_file),
            offset=3,
            start_line=3,
            limit=2,
            end_line=4,
        )

        assert not result.error
        assert "3: Line 3" in result.output
        assert "4: Line 4" in result.output

    @pytest.mark.asyncio
    async def test_conflicting_offset_and_start_line_rejected(
        self,
        skill: ReadFileSkill,
        test_file: Path,
    ) -> None:
        """Mixed canonical/alias params fail closed when they disagree on the start."""
        result = await skill.execute(path=str(test_file), offset=2, start_line=3)

        assert result.error is not None
        assert "offset and start_line" in result.error

    @pytest.mark.asyncio
    async def test_conflicting_limit_and_end_line_rejected(
        self,
        skill: ReadFileSkill,
        test_file: Path,
    ) -> None:
        """Mixed canonical/alias params fail closed when they disagree on the range."""
        result = await skill.execute(
            path=str(test_file),
            offset=3,
            limit=2,
            end_line=5,
        )

        assert result.error is not None
        assert "limit and end_line" in result.error

    @pytest.mark.asyncio
    async def test_end_line_before_start_line_rejected(
        self,
        skill: ReadFileSkill,
        test_file: Path,
    ) -> None:
        """end_line must not precede the effective start line."""
        result = await skill.execute(path=str(test_file), start_line=4, end_line=3)

        assert result.error is not None
        assert "end_line" in result.error

    @pytest.mark.asyncio
    async def test_offset_beyond_file_returns_empty(
        self,
        skill: ReadFileSkill,
        test_file: Path,
    ) -> None:
        """Offset beyond file length returns helpful message."""
        result = await skill.execute(path=str(test_file), offset=100)
        assert not result.error
        # P2.5: Returns a helpful message instead of empty string
        assert "beyond end of file" in result.output or "empty" in result.output

    @pytest.mark.asyncio
    async def test_line_numbers_false_returns_raw_text(
        self,
        skill: ReadFileSkill,
        test_file: Path,
    ) -> None:
        """line_numbers=false returns raw lines without numeric prefixes."""
        result = await skill.execute(path=str(test_file), line_numbers=False)

        assert not result.error
        assert result.output.startswith("Line 1\nLine 2\n")
        assert "1: Line 1" not in result.output

    @pytest.mark.asyncio
    async def test_line_numbers_false_preserves_trailing_spaces_and_final_line(
        self,
        skill: ReadFileSkill,
        tmp_path: Path,
    ) -> None:
        """Raw mode should preserve line text instead of stripping whitespace."""
        test_file = tmp_path / "spacing.txt"
        test_file.write_text("keep  \nfinal line")

        result = await skill.execute(path=str(test_file), line_numbers=False)

        assert not result.error
        assert result.output == "keep  \nfinal line"

    @pytest.mark.asyncio
    async def test_invalid_offset_returns_error(
        self,
        skill: ReadFileSkill,
        test_file: Path,
    ) -> None:
        """Offset less than 1 returns error."""
        result = await skill.execute(path=str(test_file), offset=0)
        assert result.error is not None
        # JSON Schema validation produces "less than the minimum of 1"
        assert "minimum" in result.error.lower() or "less than" in result.error.lower()

    @pytest.mark.asyncio
    async def test_invalid_utf8_returns_error(
        self,
        skill: ReadFileSkill,
        tmp_path: Path,
    ) -> None:
        """Invalid UTF-8 input should fail closed instead of replacing bytes."""
        test_file = tmp_path / "binary.txt"
        test_file.write_bytes(b"\x80\x81broken")

        result = await skill.execute(path=str(test_file))

        assert result.error is not None
        assert "UTF-8" in result.error


class TestGlobExclude:
    """Tests for glob exclude parameter."""

    @pytest.fixture
    def skill(self) -> GlobSkill:
        # Use factory to get validation wrapper
        services = _make_services(allowed_paths=None)
        return glob_factory(services)

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
        # Use factory to get validation wrapper
        services = _make_services(allowed_paths=None)
        return grep_factory(services)

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
        lines = [line for line in result.output.split("\n") if line.strip()]
        assert len(lines) > 2  # More than just match lines

    @pytest.mark.asyncio
    async def test_single_file_invalid_utf8_returns_error(self, tmp_path: Path) -> None:
        """Single-file grep should fail closed on invalid UTF-8 in Python fallback."""
        bad_file = tmp_path / "bad.txt"
        bad_file.write_bytes(b"\xffmatch\n")

        services = _make_services(allowed_paths=[tmp_path], cwd=tmp_path)
        skill = grep_factory(services)

        result = await skill.execute(pattern="match", path=str(bad_file))

        assert result.error is not None
        assert "UTF-8" in result.error

    @pytest.mark.asyncio
    async def test_directory_grep_skips_invalid_utf8_files(self, tmp_path: Path) -> None:
        """Directory grep should skip invalid UTF-8 files instead of corrupting them."""
        good_file = tmp_path / "good.txt"
        good_file.write_text("match here\n")
        bad_file = tmp_path / "bad.txt"
        bad_file.write_bytes(b"\xffmatch\n")

        services = _make_services(allowed_paths=[tmp_path], cwd=tmp_path)
        skill = grep_factory(services)

        result = await skill.execute(pattern="match", path=str(tmp_path), recursive=True)

        assert not result.error
        assert "good.txt" in result.output
        assert "bad.txt" not in result.output
        assert "invalid UTF-8 file skipped" in result.output

    @pytest.mark.asyncio
    async def test_directory_grep_skips_invalid_utf8_files_in_ripgrep_path(
        self,
        skill: GrepSkill,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Ripgrep JSON byte payloads should be treated as invalid UTF-8 files."""
        good_file = tmp_path / "good.txt"
        good_file.write_text("match here\n")
        bad_file = tmp_path / "bad.txt"
        bad_file.write_bytes(b"\xffmatch\n")

        lines = [
            json.dumps(
                {
                    "type": "match",
                    "data": {
                        "path": {"text": str(bad_file)},
                        "lines": {
                            "bytes": base64.b64encode(b"\xffmatch\n").decode("ascii")
                        },
                        "line_number": 1,
                    },
                }
            ),
            json.dumps(
                {
                    "type": "match",
                    "data": {
                        "path": {"text": str(good_file)},
                        "lines": {"text": "match here\n"},
                        "line_number": 1,
                    },
                }
            ),
            json.dumps({"type": "summary", "data": {"stats": {"searches": 2}}}),
        ]

        class _FakeProc:
            async def communicate(self) -> tuple[bytes, bytes]:
                return "\n".join(lines).encode("utf-8"), b""

        async def _fake_create_subprocess_exec(*args, **kwargs):
            return _FakeProc()

        monkeypatch.setattr(grep_module, "RG_AVAILABLE", True)
        monkeypatch.setattr(
            grep_module.asyncio,
            "create_subprocess_exec",
            _fake_create_subprocess_exec,
        )

        result = await skill.execute(pattern="match", path=str(tmp_path), recursive=True)

        assert not result.error
        assert str(good_file) in result.output
        assert str(bad_file) not in result.output
        assert "invalid UTF-8 file skipped" in result.output
