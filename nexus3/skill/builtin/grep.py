"""Grep skill for searching file contents with regex.

P2.5 SECURITY: Implements file size limits and streaming search.
Issue 6: Optimized with parallel file search using asyncio.gather + semaphore.
Performance: Uses ripgrep when available (10-100x faster for large directories).
"""

import asyncio
import fnmatch
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from nexus3.core.constants import MAX_GREP_FILE_SIZE
from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import validate_path
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory

# Detect ripgrep at module load
RG_AVAILABLE = shutil.which("rg") is not None

# Directories to exclude from Python fallback search
# ripgrep respects .gitignore automatically, so these are only for the fallback
EXCLUDED_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", ".nexus3",
    "venv", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", ".eggs", "*.egg-info",
})

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
        with open(file_path, encoding="utf-8", errors="replace") as f:
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

    except OSError:
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
        if isinstance(result, BaseException):
            # Log silently, don't fail the whole search
            continue
        # result is now narrowed to list[str]
        matches = result
        if matches:  # Non-empty matches
            files_with_matches += 1
            remaining = max_matches - len(all_matches)
            if remaining > 0:
                all_matches.extend(matches[:remaining])
            if len(all_matches) >= max_matches:
                break

    return all_matches, files_with_matches


async def _search_with_ripgrep(
    search_path: Path,
    pattern: str,
    recursive: bool = True,
    ignore_case: bool = False,
    max_matches: int = 100,
    include: str | None = None,
    context: int = 0,
) -> tuple[list[str], int, int]:
    """Search using ripgrep for significantly faster results.

    Args:
        search_path: File or directory to search.
        pattern: Regex pattern to search for.
        recursive: Search subdirectories (default: True).
        ignore_case: Case-insensitive search.
        max_matches: Maximum matches to return.
        include: Only search files matching this pattern (e.g., '*.py').
        context: Lines of context before/after each match.

    Returns:
        (matches, files_with_matches, files_searched)
    """
    # Build ripgrep command
    cmd = ["rg", "--json"]

    # Map parameters to rg flags
    if ignore_case:
        cmd.append("-i")
    if max_matches:
        cmd.extend(["-m", str(max_matches)])
    if context > 0:
        cmd.extend(["-C", str(context)])
    if not recursive:
        cmd.extend(["--max-depth", "1"])

    # Handle include patterns
    if include:
        # Handle brace expansion like '*.{js,ts}'
        if '{' in include and '}' in include:
            prefix, rest = include.split('{', 1)
            options, suffix = rest.split('}', 1)
            for opt in options.split(','):
                cmd.extend(["-g", prefix + opt + suffix])
        else:
            cmd.extend(["-g", include])

    cmd.append(pattern)
    cmd.append(str(search_path))

    # Run ripgrep with platform-specific window handling
    if sys.platform == "win32":
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP |
                subprocess.CREATE_NO_WINDOW
            ),
        )
    else:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )

    stdout, stderr = await proc.communicate()

    # Parse JSON output
    matches: list[str] = []
    files_with_matches: set[str] = set()
    files_searched = 0

    for line in stdout.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = data.get("type")

        if msg_type == "match":
            match_data = data.get("data", {})
            path_data = match_data.get("path", {})
            file_path = path_data.get("text", "")
            line_num = match_data.get("line_number", 0)
            lines = match_data.get("lines", {})
            text = lines.get("text", "").rstrip()

            if file_path:
                files_with_matches.add(file_path)
                # Format: path:line: content
                matches.append(f"{file_path}:{line_num}: {text}")

        elif msg_type == "context":
            # Context lines around matches
            ctx_data = data.get("data", {})
            path_data = ctx_data.get("path", {})
            file_path = path_data.get("text", "")
            line_num = ctx_data.get("line_number", 0)
            lines = ctx_data.get("lines", {})
            text = lines.get("text", "").rstrip()

            if file_path:
                matches.append(f"{file_path}:{line_num}:  {text}")

        elif msg_type == "summary":
            stats = data.get("data", {}).get("stats", {})
            files_searched = stats.get("searches", 0)

    return matches[:max_matches], len(files_with_matches), files_searched


def _should_exclude_dir(dir_name: str) -> bool:
    """Check if a directory should be excluded from Python fallback search."""
    if dir_name in EXCLUDED_DIRS:
        return True
    # Handle patterns like *.egg-info
    for pattern in EXCLUDED_DIRS:
        if "*" in pattern and fnmatch.fnmatch(dir_name, pattern):
            return True
    return False


def _rglob_with_exclusions(root: Path) -> list[Path]:
    """Recursively glob files, skipping excluded directories.

    This is significantly faster than rglob("*") for repos with node_modules, .git, etc.
    """
    results: list[Path] = []

    def _walk(directory: Path) -> None:
        try:
            for entry in directory.iterdir():
                if entry.is_dir():
                    if not _should_exclude_dir(entry.name):
                        _walk(entry)
                else:
                    results.append(entry)
        except (PermissionError, OSError):
            # Skip inaccessible directories
            pass

    _walk(root)
    return results


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
            # Validate path (resolves symlinks, checks allowed_paths if set)
            search_path = self._validate_path(path)

            # Use ripgrep when available and not sandboxed
            # (ripgrep doesn't respect our allowed_paths, so use Python fallback for sandboxed)
            if RG_AVAILABLE and self._allowed_paths is None:
                return await self._search_with_ripgrep(
                    search_path, pattern, recursive, ignore_case,
                    max_matches, include, context
                )

            # Python fallback: compile regex and search manually
            return await self._search_with_python(
                search_path, pattern, recursive, ignore_case,
                max_matches, include, context
            )

        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))
        except Exception as e:
            return ToolResult(error=f"Error searching: {e}")

    async def _search_with_ripgrep(
        self,
        search_path: Path,
        pattern: str,
        recursive: bool,
        ignore_case: bool,
        max_matches: int,
        include: str | None,
        context: int,
    ) -> ToolResult:
        """Search using ripgrep (fast path)."""
        try:
            matches, files_with_matches, files_searched = await _search_with_ripgrep(
                search_path, pattern, recursive, ignore_case,
                max_matches, include, context
            )
        except Exception:
            # Fall back to Python on any ripgrep error
            return await self._search_with_python(
                search_path, pattern, recursive, ignore_case,
                max_matches, include, context
            )

        if not matches:
            return ToolResult(output=f"No matches for '{pattern}' in {search_path}")

        result = "\n".join(matches)
        stats = f"{files_with_matches} files, {files_searched} files searched"
        summary = f"\n\n({len(matches)} matches in {stats})"
        if len(matches) >= max_matches:
            summary = f"\n\n(Limited to {max_matches}, {files_with_matches}+ matched, {stats})"

        return ToolResult(output=result + summary)

    async def _search_with_python(
        self,
        search_path: Path,
        pattern: str,
        recursive: bool,
        ignore_case: bool,
        max_matches: int,
        include: str | None,
        context: int,
    ) -> ToolResult:
        """Search using Python (fallback path, used when sandboxed or rg unavailable)."""
        # Compile regex
        flags = re.IGNORECASE if ignore_case else 0
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return ToolResult(error=f"Invalid regex pattern: {e}")

        # Issue 6: Combine is_file/is_dir checks into one thread call
        is_file, is_dir = await asyncio.to_thread(_check_path_type, search_path)

        if is_file:
            files_to_search = [search_path]
        elif is_dir:
            # Custom rglob that excludes common directories
            if recursive:
                files_to_search = await asyncio.to_thread(
                    lambda: list(_rglob_with_exclusions(search_path))
                )
            else:
                files_to_search = await asyncio.to_thread(
                    lambda: list(search_path.glob("*"))
                )
            # Filter to files only
            files_to_search = [f for f in files_to_search if f.is_file()]
        else:
            return ToolResult(error=f"Path not found: {search_path}")

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
            return ToolResult(output=f"No matches for '{pattern}' in {search_path}{skip_note}")

        result = "\n".join(matches)
        skip = f", {files_skipped_size} skipped" if files_skipped_size > 0 else ""
        stats = f"{files_with_matches} files, {files_searched} searched{skip}"
        summary = f"\n\n({len(matches)} matches in {stats})"
        if len(matches) >= max_matches:
            summary = f"\n\n(Limited to {max_matches}, {files_with_matches}+ matched, {stats})"

        return ToolResult(output=result + summary)


# Factory for dependency injection
grep_factory = file_skill_factory(GrepSkill)
