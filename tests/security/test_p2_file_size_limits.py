"""P2.5: Test file size/line limits and streaming reads.

This tests the security fix where file tools have size limits to prevent
memory DoS attacks from reading huge files.

The fix:
- read_file: Rejects files > MAX_FILE_SIZE_BYTES, streams line-by-line
- tail: Uses deque to only keep last N lines in memory
- grep: Skips files > MAX_GREP_FILE_SIZE, streams search
"""

import os
from pathlib import Path

import pytest

from nexus3.core.constants import (
    MAX_FILE_SIZE_BYTES,
    MAX_GREP_FILE_SIZE,
    MAX_OUTPUT_BYTES,
    MAX_READ_LINES,
)


class TestReadFileSizeLimits:
    """Test read_file size and line limits."""

    @pytest.mark.asyncio
    async def test_rejects_file_over_size_limit(self, tmp_path: Path) -> None:
        """Files larger than MAX_FILE_SIZE_BYTES should be rejected."""
        from nexus3.skill.builtin.read_file import ReadFileSkill
        from nexus3.skill.services import ServiceContainer

        # Create a file just over the limit
        large_file = tmp_path / "large.txt"
        # Write content larger than limit
        with open(large_file, "w") as f:
            # Write 11MB (over 10MB limit)
            f.write("x" * (MAX_FILE_SIZE_BYTES + 1024 * 1024))

        services = ServiceContainer()
        services.register("cwd", tmp_path)

        skill = ReadFileSkill(services)
        result = await skill.execute(path=str(large_file))

        assert result.error is not None
        assert "too large" in result.error.lower()

    @pytest.mark.asyncio
    async def test_respects_line_limit(self, tmp_path: Path) -> None:
        """Should stop reading after limit lines."""
        from nexus3.skill.builtin.read_file import ReadFileSkill
        from nexus3.skill.services import ServiceContainer

        test_file = tmp_path / "lines.txt"
        # Write more lines than the limit
        with open(test_file, "w") as f:
            for i in range(100):
                f.write(f"Line {i}\n")

        services = ServiceContainer()
        services.register("cwd", tmp_path)

        skill = ReadFileSkill(services)
        result = await skill.execute(path=str(test_file), limit=10)

        assert result.output is not None
        assert not result.error
        # Should have exactly 10 lines (plus truncation message)
        lines = result.output.strip().split("\n")
        # Count actual content lines (lines with line numbers, not truncation/empty)
        content_lines = [l for l in lines if l and ":" in l and not l.startswith("[")]
        assert len(content_lines) == 10

    @pytest.mark.asyncio
    async def test_default_line_limit_applied(self, tmp_path: Path) -> None:
        """Without explicit limit, should use MAX_READ_LINES."""
        from nexus3.skill.builtin.read_file import ReadFileSkill
        from nexus3.skill.services import ServiceContainer

        test_file = tmp_path / "many_lines.txt"
        # Write more lines than MAX_READ_LINES
        with open(test_file, "w") as f:
            for i in range(MAX_READ_LINES + 100):
                f.write(f"Line {i}\n")

        services = ServiceContainer()
        services.register("cwd", tmp_path)

        skill = ReadFileSkill(services)
        result = await skill.execute(path=str(test_file))

        assert result.output is not None
        # Should be truncated
        assert "truncated" in result.output.lower()

    @pytest.mark.asyncio
    async def test_streaming_read_with_offset(self, tmp_path: Path) -> None:
        """Streaming read should work correctly with offset."""
        from nexus3.skill.builtin.read_file import ReadFileSkill
        from nexus3.skill.services import ServiceContainer

        test_file = tmp_path / "offset.txt"
        with open(test_file, "w") as f:
            for i in range(20):
                f.write(f"Line {i}\n")

        services = ServiceContainer()
        services.register("cwd", tmp_path)

        skill = ReadFileSkill(services)
        result = await skill.execute(path=str(test_file), offset=10, limit=5)

        assert result.output is not None
        # Should start from line 10
        assert "10:" in result.output
        assert "14:" in result.output
        # Should not include line 15 (only 5 lines from offset 10)
        assert "15:" not in result.output

    @pytest.mark.asyncio
    async def test_small_file_reads_fully(self, tmp_path: Path) -> None:
        """Small files should be read completely."""
        from nexus3.skill.builtin.read_file import ReadFileSkill
        from nexus3.skill.services import ServiceContainer

        test_file = tmp_path / "small.txt"
        test_file.write_text("Line 1\nLine 2\nLine 3\n")

        services = ServiceContainer()
        services.register("cwd", tmp_path)

        skill = ReadFileSkill(services)
        result = await skill.execute(path=str(test_file))

        assert result.output is not None
        assert "Line 1" in result.output
        assert "Line 2" in result.output
        assert "Line 3" in result.output


class TestTailSizeLimits:
    """Test tail memory efficiency."""

    @pytest.mark.asyncio
    async def test_tail_large_file_memory_efficient(self, tmp_path: Path) -> None:
        """Tail should work on large files without loading entire file."""
        from nexus3.skill.builtin.tail import TailSkill
        from nexus3.skill.services import ServiceContainer

        large_file = tmp_path / "large_log.txt"
        # Create a file with many lines
        with open(large_file, "w") as f:
            for i in range(100000):
                f.write(f"Log line {i}\n")

        services = ServiceContainer()
        services.register("cwd", tmp_path)

        skill = TailSkill(services)
        result = await skill.execute(path=str(large_file), lines=10)

        assert result.output is not None
        assert not result.error
        # Should have the last 10 lines
        assert "99990:" in result.output or "99991:" in result.output

    @pytest.mark.asyncio
    async def test_tail_respects_output_limit(self, tmp_path: Path) -> None:
        """Tail output should be bounded by MAX_OUTPUT_BYTES."""
        from nexus3.skill.builtin.tail import TailSkill
        from nexus3.skill.services import ServiceContainer

        test_file = tmp_path / "long_lines.txt"
        # Create file with very long lines
        with open(test_file, "w") as f:
            for i in range(100):
                f.write("x" * 50000 + f" line {i}\n")

        services = ServiceContainer()
        services.register("cwd", tmp_path)

        skill = TailSkill(services)
        result = await skill.execute(path=str(test_file), lines=50)

        assert result.output is not None
        # Output should be bounded
        assert len(result.output.encode("utf-8")) <= MAX_OUTPUT_BYTES + 1000  # Some buffer for message


class TestGrepSizeLimits:
    """Test grep file size limits."""

    @pytest.mark.asyncio
    async def test_grep_skips_large_files(self, tmp_path: Path) -> None:
        """Grep should skip files larger than MAX_GREP_FILE_SIZE."""
        from nexus3.skill.builtin.grep import GrepSkill
        from nexus3.skill.services import ServiceContainer

        # Create a large file
        large_file = tmp_path / "large.txt"
        with open(large_file, "w") as f:
            # Write content larger than grep limit
            for i in range(MAX_GREP_FILE_SIZE // 100 + 1000):
                f.write("x" * 100 + f" FINDME line {i}\n")

        # Create a small file
        small_file = tmp_path / "small.txt"
        small_file.write_text("FINDME in small file\n")

        services = ServiceContainer()
        services.register("cwd", tmp_path)

        skill = GrepSkill(services)
        result = await skill.execute(pattern="FINDME", path=str(tmp_path))

        assert result.output is not None
        # Should find match in small file
        assert "small.txt" in result.output
        # Should mention skipped files
        assert "skipped" in result.output.lower()

    @pytest.mark.asyncio
    async def test_grep_stops_at_max_matches(self, tmp_path: Path) -> None:
        """Grep should stop at max_matches."""
        from nexus3.skill.builtin.grep import GrepSkill
        from nexus3.skill.services import ServiceContainer

        test_file = tmp_path / "many_matches.txt"
        with open(test_file, "w") as f:
            for i in range(200):
                f.write(f"MATCH line {i}\n")

        services = ServiceContainer()
        services.register("cwd", tmp_path)

        skill = GrepSkill(services)
        result = await skill.execute(
            pattern="MATCH", path=str(test_file), max_matches=10
        )

        assert result.output is not None
        # Should be limited
        assert "Limited to 10" in result.output

    @pytest.mark.asyncio
    async def test_grep_streaming_preserves_correctness(self, tmp_path: Path) -> None:
        """Streaming grep should produce correct results."""
        from nexus3.skill.builtin.grep import GrepSkill
        from nexus3.skill.services import ServiceContainer

        test_file = tmp_path / "test.txt"
        test_file.write_text("line one\nMATCH line two\nline three\nMATCH line four\n")

        services = ServiceContainer()
        services.register("cwd", tmp_path)

        skill = GrepSkill(services)
        result = await skill.execute(pattern="MATCH", path=str(test_file))

        assert result.output is not None
        assert "line two" in result.output
        assert "line four" in result.output
        assert "2 matches" in result.output


class TestConstantsExist:
    """Verify security constants are properly defined."""

    def test_file_size_limit_defined(self) -> None:
        """MAX_FILE_SIZE_BYTES should be defined and reasonable."""
        assert MAX_FILE_SIZE_BYTES > 0
        assert MAX_FILE_SIZE_BYTES <= 100 * 1024 * 1024  # Not more than 100MB

    def test_output_limit_defined(self) -> None:
        """MAX_OUTPUT_BYTES should be defined and reasonable."""
        assert MAX_OUTPUT_BYTES > 0
        assert MAX_OUTPUT_BYTES <= 10 * 1024 * 1024  # Not more than 10MB

    def test_line_limit_defined(self) -> None:
        """MAX_READ_LINES should be defined and reasonable."""
        assert MAX_READ_LINES > 0
        assert MAX_READ_LINES <= 100000  # Not more than 100k lines

    def test_grep_size_limit_defined(self) -> None:
        """MAX_GREP_FILE_SIZE should be defined and reasonable."""
        assert MAX_GREP_FILE_SIZE > 0
        assert MAX_GREP_FILE_SIZE <= MAX_FILE_SIZE_BYTES
