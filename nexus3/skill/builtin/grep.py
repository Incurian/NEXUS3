"""Grep skill for searching file contents with regex.

P2.5 SECURITY: Implements file size limits and streaming search.
Issue 6: Optimized with parallel file search using asyncio.gather + semaphore.
"""

import asyncio
import fnmatch
import re
from pathlib import Path
from typing import Any

from nexus3.core.constants import MAX_GREP_FILE_SIZE
from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import validate_path
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory

# Bounded concurrency for parallel file search
MAX_CONCURRENT_SEARCHES = 10


def _check_path_type(p: Path) -> tuple[bool, bool]:
    """Check if path is file and/or directory in a single call.

    Returns:
        (is_file, is_dir)
    """
    return p.is_file(), p.is_dir()


def _search_file_streaming(
    file_path: Path,
    regex: re.Pattern[str],
    rel_path: Path | str,
    context: int,
    max_matches: int,
    current_matches: int,
) -> tuple[list[str], bool]:
    """Search a file line-by-line without loading entire file.

    P2.5 SECURITY: Streams file content to avoid memory issues.

    Returns:
        Tuple of (matches, hit_limit)
    """
    matches: list[str] = []
    lines_buffer: list[str] = []  # For context
    match_indices: list[int] = []

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            for line_num, line in enumerate(f, 1):
                line = line.rstrip()

                if context > 0:
                    lines_buffer.append(line)
                    if regex.search(line):
                        match_indices.append(line_num - 1)  # 0-indexed in buffer

                        if current_matches + len(match_indices) >= max_matches:
                            break
                else:
                    if regex.search(line):
                        matches.append(f"{rel_path}:{line_num}: {line}")
                        if current_matches + len(matches) >= max_matches:
                            return matches, True

    except (OSError, IOError):
        return [], False

    # Process context matches
    if context > 0 and match_indices:
        printed_lines: set[int] = set()
        for match_idx in match_indices:
            start = max(0, match_idx - context)
            end = min(len(lines_buffer), match_idx + context + 1)

            if printed_lines and start > max(printed_lines) + 1:
                matches.append("--")

            for idx in range(start, end):
                if idx in printed_lines:
                    continue
                printed_lines.add(idx)

                line = lines_buffer[idx]
                prefix = ">" if idx == match_idx else " "
                matches.append(f"{rel_path}:{idx + 1}:{prefix} {line}")

    hit_limit = current_matches + len(matches) >= max_matches
    return matches, hit_limit


async def _search_files_parallel(
    files: list[tuple[Path, Path | str]],
    regex: re.Pattern[str],
    context: int,
    max_matches: int,
    max_concurrent: int = MAX_CONCURRENT_SEARCHES,
) -> tuple[list[str], int]:
    """Search multiple files in parallel with bounded concurrency.

    Issue 6: Uses asyncio.gather with semaphore to limit concurrent threads,
    reducing overhead from 1000+ sequential asyncio.to_thread calls.

    Args:
        files: List of (file_path, rel_path) tuples to search.
        regex: Compiled regex pattern.
        context: Lines of context around matches.
        max_matches: Maximum matches to return.
        max_concurrent: Maximum concurrent file searches.

    Returns:
        (all_matches, files_with_matches_count)
    """
    if not files:
        return [], 0

    semaphore = asyncio.Semaphore(max_concurrent)

    async def search_one(file_path: Path, rel_path: Path | str) -> list[str]:
        async with semaphore:
            matches, _ = await asyncio.to_thread(
                _search_file_streaming,
                file_path,
                regex,
                rel_path,
                context,
                max_matches,
                0,  # current_matches=0, we aggregate later
            )
            return matches

    # Create all tasks upfront
    tasks = [search_one(fp, rp) for fp, rp in files]

    # Run all searches in parallel with bounded concurrency
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Aggregate results, stopping at max_matches
    all_matches: list[str] = []
    files_with_matches = 0

    for result in results:
        if isinstance(result, Exception):
            # Log silently, don't fail the whole search
            continue
        if result:  # Non-empty matches
            files_with_matches += 1
            remaining = max_matches - len(all_matches)
            if remaining > 0:
                all_matches.extend(result[:remaining])
            if len(all_matches) >= max_matches:
                break

    return all_matches, files_with_matches


class GrepSkill(FileSkill):
    """Skill that searches file contents using regular expressions.

    Supports searching a single file or recursively searching a directory.

    P2.5 SECURITY: Uses streaming search with size limits.
    - Files larger than MAX_GREP_FILE_SIZE are skipped
    - Search stops at max_matches
    - Output is bounded

    Inherits path validation from FileSkill.
    """

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return "Search file contents using regex pattern"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regular expression pattern to search for"
                },
                "path": {
                    "type": "string",
                    "description": "File or directory to search"
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Search subdirectories recursively (default: true)",
                    "default": True
                },
                "ignore_case": {
                    "type": "boolean",
                    "description": "Case-insensitive search (default: false)",
                    "default": False
                },
                "max_matches": {
                    "type": "integer",
                    "description": "Maximum number of matches to return (default: 100)",
                    "default": 100
                },
                "include": {
                    "type": "string",
                    "description": "Only search files matching pattern (e.g., '*.py', '*.{js,ts}')"
                },
                "context": {
                    "type": "integer",
                    "description": "Number of lines before and after each match (default: 0)",
                    "default": 0
                }
            },
            "required": ["pattern", "path"]
        }

    async def execute(
        self,
        pattern: str = "",
        path: str = "",
        recursive: bool = True,
        ignore_case: bool = False,
        max_matches: int = 100,
        include: str | None = None,
        context: int = 0,
        **kwargs: Any
    ) -> ToolResult:
        """Search for pattern in file(s).

        Args:
            pattern: Regex pattern to search for
            path: File or directory to search
            recursive: Search subdirectories
            ignore_case: Case-insensitive matching
            max_matches: Maximum matches to return
            include: Only search files matching this pattern
            context: Lines of context before/after each match

        Returns:
            ToolResult with matching lines or error message
        """
        # Note: 'pattern' and 'path' required by schema
        try:
            # Compile regex
            flags = re.IGNORECASE if ignore_case else 0
            try:
                regex = re.compile(pattern, flags)
            except re.error as e:
                return ToolResult(error=f"Invalid regex pattern: {e}")

            # Validate path (resolves symlinks, checks allowed_paths if set)
            search_path = self._validate_path(path)

            # Issue 6: Combine is_file/is_dir checks into one thread call
            is_file, is_dir = await asyncio.to_thread(_check_path_type, search_path)

            if is_file:
                files_to_search = [search_path]
            elif is_dir:
                if recursive:
                    files_to_search = await asyncio.to_thread(
                        lambda: list(search_path.rglob("*"))
                    )
                else:
                    files_to_search = await asyncio.to_thread(
                        lambda: list(search_path.glob("*"))
                    )
                # Filter to files only
                files_to_search = [f for f in files_to_search if f.is_file()]
            else:
                return ToolResult(error=f"Path not found: {path}")

            # Filter by include pattern if specified
            if include and len(files_to_search) > 1:
                # Handle brace expansion like '*.{js,ts}'
                if '{' in include and '}' in include:
                    # Extract patterns from braces
                    prefix, rest = include.split('{', 1)
                    options, suffix = rest.split('}', 1)
                    patterns = [prefix + opt + suffix for opt in options.split(',')]
                    files_to_search = [
                        f for f in files_to_search
                        if any(fnmatch.fnmatch(f.name, p) for p in patterns)
                    ]
                else:
                    files_to_search = [
                        f for f in files_to_search
                        if fnmatch.fnmatch(f.name, include)
                    ]

            # Issue 6: Pre-filter files before parallel search
            # This moves validation/size checks out of the hot loop
            valid_files: list[tuple[Path, Path | str]] = []
            files_skipped_size = 0

            for file_path in files_to_search:
                # Validate each file against sandbox
                if self._allowed_paths is not None:
                    try:
                        validate_path(file_path, allowed_paths=self._allowed_paths)
                    except PathSecurityError:
                        continue

                # P2.5 SECURITY: Skip files that are too large
                try:
                    file_size = file_path.stat().st_size
                    if file_size > MAX_GREP_FILE_SIZE:
                        files_skipped_size += 1
                        continue
                except OSError:
                    continue

                # Format relative path
                try:
                    rel_path: Path | str = file_path.relative_to(search_path)
                except ValueError:
                    rel_path = file_path

                valid_files.append((file_path, rel_path))

            # Issue 6: Parallel search with bounded concurrency
            files_searched = len(valid_files)
            matches, files_with_matches = await _search_files_parallel(
                valid_files,
                regex,
                context,
                max_matches,
            )

            if not matches:
                skip_note = ""
                if files_skipped_size > 0:
                    skip_note = f" ({files_skipped_size} large files skipped)"
                return ToolResult(output=f"No matches for '{pattern}' in {path}{skip_note}")

            result = "\n".join(matches)
            skip_note = f", {files_skipped_size} large files skipped" if files_skipped_size > 0 else ""
            summary = f"\n\n({len(matches)} matches in {files_with_matches} files, {files_searched} files searched{skip_note})"
            if len(matches) >= max_matches:
                summary = f"\n\n(Limited to {max_matches} matches, {files_with_matches}+ files matched, {files_searched} files searched{skip_note})"

            return ToolResult(output=result + summary)

        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))
        except Exception as e:
            return ToolResult(error=f"Error searching: {e}")


# Factory for dependency injection
grep_factory = file_skill_factory(GrepSkill)
