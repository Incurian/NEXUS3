"""Tests for grep parallel search optimization (Issue 6)."""

import json
import re
from pathlib import Path

import pytest

from nexus3.skill.builtin import grep as grep_module
from nexus3.skill.builtin.grep import (
    MAX_CONCURRENT_SEARCHES,
    _check_path_type,
    _search_files_parallel,
    _search_with_ripgrep,
)


class TestCheckPathType:
    """Tests for _check_path_type helper."""

    def test_file_returns_true_false(self, tmp_path: Path) -> None:
        """File should return (True, False)."""
        f = tmp_path / "test.txt"
        f.write_text("hello")
        is_file, is_dir = _check_path_type(f)
        assert is_file is True
        assert is_dir is False

    def test_dir_returns_false_true(self, tmp_path: Path) -> None:
        """Directory should return (False, True)."""
        is_file, is_dir = _check_path_type(tmp_path)
        assert is_file is False
        assert is_dir is True

    def test_nonexistent_returns_false_false(self, tmp_path: Path) -> None:
        """Non-existent path should return (False, False)."""
        nonexistent = tmp_path / "nonexistent"
        is_file, is_dir = _check_path_type(nonexistent)
        assert is_file is False
        assert is_dir is False


class TestSearchFilesParallel:
    """Tests for _search_files_parallel function."""

    @pytest.fixture
    def test_files(self, tmp_path: Path) -> list[tuple[Path, Path]]:
        """Create test files for parallel search."""
        files = []
        for i in range(5):
            f = tmp_path / f"file{i}.txt"
            f.write_text(f"line 1\nmatch{i}\nline 3\n")
            files.append((f, Path(f"file{i}.txt")))
        return files

    @pytest.fixture
    def regex(self) -> re.Pattern[str]:
        """Create a regex pattern that matches 'match'."""
        return re.compile(r"match\d")

    @pytest.mark.asyncio
    async def test_finds_all_matches(
        self, test_files: list[tuple[Path, Path]], regex: re.Pattern[str]
    ) -> None:
        """Parallel search should find matches in all files."""
        matches, files_with_matches, files_skipped_invalid_utf8 = await _search_files_parallel(
            test_files, regex, context=0, max_matches=100
        )
        assert files_with_matches == 5
        assert files_skipped_invalid_utf8 == 0
        assert len(matches) == 5

    @pytest.mark.asyncio
    async def test_respects_max_matches(
        self, test_files: list[tuple[Path, Path]], regex: re.Pattern[str]
    ) -> None:
        """Parallel search should stop at max_matches."""
        matches, _, files_skipped_invalid_utf8 = await _search_files_parallel(
            test_files, regex, context=0, max_matches=3
        )
        assert files_skipped_invalid_utf8 == 0
        assert len(matches) == 3

    @pytest.mark.asyncio
    async def test_empty_files_list(self) -> None:
        """Empty files list should return empty results."""
        regex = re.compile(r"test")
        matches, files_with_matches, files_skipped_invalid_utf8 = await _search_files_parallel(
            [], regex, context=0, max_matches=100
        )
        assert matches == []
        assert files_with_matches == 0
        assert files_skipped_invalid_utf8 == 0

    @pytest.mark.asyncio
    async def test_handles_nonexistent_files(self, tmp_path: Path) -> None:
        """Should handle exceptions from non-existent files gracefully."""
        regex = re.compile(r"test")
        nonexistent = [(tmp_path / "missing.txt", Path("missing.txt"))]
        matches, files_with_matches, files_skipped_invalid_utf8 = await _search_files_parallel(
            nonexistent, regex, context=0, max_matches=100
        )
        assert matches == []
        assert files_with_matches == 0
        assert files_skipped_invalid_utf8 == 0

    @pytest.mark.asyncio
    async def test_with_context_lines(self, tmp_path: Path) -> None:
        """Parallel search should work with context lines."""
        f = tmp_path / "context.txt"
        f.write_text("before\nmatch\nafter\n")
        regex = re.compile(r"match")

        matches, files_with_matches, files_skipped_invalid_utf8 = await _search_files_parallel(
            [(f, Path("context.txt"))],
            regex,
            context=1,
            max_matches=100,
        )
        assert files_with_matches == 1
        assert files_skipped_invalid_utf8 == 0
        # Should include context lines
        assert any("before" in m for m in matches)
        assert any("after" in m for m in matches)

    @pytest.mark.asyncio
    async def test_tracks_invalid_utf8_skips(self, tmp_path: Path) -> None:
        """Parallel search should count invalid UTF-8 files separately."""
        good = tmp_path / "good.txt"
        good.write_text("match\n")
        bad = tmp_path / "bad.txt"
        bad.write_bytes(b"\xffmatch\n")
        regex = re.compile(r"match")

        matches, files_with_matches, files_skipped_invalid_utf8 = await _search_files_parallel(
            [(good, Path("good.txt")), (bad, Path("bad.txt"))],
            regex,
            context=0,
            max_matches=100,
        )

        assert files_with_matches == 1
        assert files_skipped_invalid_utf8 == 1
        assert matches == ["good.txt:1: match"]


class TestSemaphoreBounded:
    """Tests for semaphore concurrency limiting."""

    @pytest.mark.asyncio
    async def test_concurrent_limit_respected(self, tmp_path: Path) -> None:
        """Verify semaphore limits concurrent operations."""
        # Create many files
        files = []
        for i in range(50):
            f = tmp_path / f"file{i}.txt"
            f.write_text(f"test{i}")
            files.append((f, Path(f"file{i}.txt")))

        regex = re.compile(r"test\d+")

        # Run the parallel search
        matches, files_with_matches, files_skipped_invalid_utf8 = await _search_files_parallel(
            files, regex, context=0, max_matches=1000
        )

        # Should find all 50 matches
        assert len(matches) == 50
        assert files_with_matches == 50
        assert files_skipped_invalid_utf8 == 0

    @pytest.mark.asyncio
    async def test_custom_concurrency_limit(self, tmp_path: Path) -> None:
        """Test with custom max_concurrent value."""
        files = []
        for i in range(10):
            f = tmp_path / f"file{i}.txt"
            f.write_text(f"test{i}")
            files.append((f, Path(f"file{i}.txt")))

        regex = re.compile(r"test\d")

        # Use very low concurrency
        matches, files_with_matches, files_skipped_invalid_utf8 = await _search_files_parallel(
            files, regex, context=0, max_matches=100, max_concurrent=2
        )

        assert len(matches) == 10
        assert files_with_matches == 10
        assert files_skipped_invalid_utf8 == 0


class TestMaxConcurrentConstant:
    """Tests for MAX_CONCURRENT_SEARCHES constant."""

    def test_constant_is_reasonable(self) -> None:
        """MAX_CONCURRENT_SEARCHES should be a reasonable value."""
        assert MAX_CONCURRENT_SEARCHES >= 1
        assert MAX_CONCURRENT_SEARCHES <= 100
        # Default value in plan is 10
        assert MAX_CONCURRENT_SEARCHES == 10


class TestRipgrepJsonHandling:
    """Tests for ripgrep JSON parsing edge cases."""

    @pytest.mark.asyncio
    async def test_counts_lines_bytes_payloads_as_invalid_utf8(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`lines.bytes` payloads should be skipped, not rendered as blank matches."""

        class _FakeProcess:
            async def communicate(self) -> tuple[bytes, bytes]:
                match_line = json.dumps(
                    {
                        "type": "match",
                        "data": {
                            "path": {"text": str(tmp_path / "bad.txt")},
                            "lines": {"bytes": "bmVlZGxlgHBheWxvYWQK"},
                            "line_number": 1,
                        },
                    }
                ).encode("utf-8")
                summary_line = json.dumps(
                    {
                        "type": "summary",
                        "data": {"stats": {"searches": 1}},
                    }
                ).encode("utf-8")
                return match_line + b"\n" + summary_line + b"\n", b""

        async def _fake_create_subprocess_exec(*args, **kwargs):
            return _FakeProcess()

        monkeypatch.setattr(
            grep_module.asyncio,
            "create_subprocess_exec",
            _fake_create_subprocess_exec,
        )

        matches, files_with_matches, files_searched, files_skipped_size, invalid_utf8 = (
            await _search_with_ripgrep(
                tmp_path,
                "needle",
                recursive=True,
                ignore_case=False,
                max_matches=100,
                include=None,
                context=0,
            )
        )

        assert matches == []
        assert files_with_matches == 0
        assert files_searched == 1
        assert files_skipped_size == 0
        assert invalid_utf8 == 1
