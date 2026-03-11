"""Glob search skill for finding files by pattern."""

import asyncio
from pathlib import Path, PurePosixPath
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.filesystem_access import FilesystemAccessGateway
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory


class GlobSkill(FileSkill):
    """Skill that finds files matching a glob pattern.

    Supports standard glob patterns like *.py, **/*.txt, etc.

    Inherits path validation from FileSkill.
    """

    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return "Find files or directories matching a glob pattern"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g., '*.py', '**/*.txt', 'src/**/*.js')",
                },
                "path": {
                    "type": "string",
                    "description": "Base directory to search from (default: current directory)",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 100)",
                    "default": 100,
                },
                "recursive": {
                    "type": "boolean",
                    "description": (
                        "Search subdirectories recursively (default: false). "
                        "When true, patterns like '*.py' match nested paths too."
                    ),
                    "default": False,
                },
                "kind": {
                    "type": "string",
                    "enum": ["file", "directory", "any"],
                    "description": (
                        "Restrict results to files, directories, or both "
                        "(default: 'file')"
                    ),
                    "default": "file",
                },
                "exclude": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Relative-path glob patterns or path segments to exclude "
                        "(e.g., ['node_modules', '.git/**', '**/__pycache__/**'])"
                    ),
                },
            },
            "required": ["pattern"],
            "additionalProperties": False,
        }

    async def execute(
        self,
        pattern: str = "",
        path: str = ".",
        max_results: int = 100,
        recursive: bool = False,
        kind: str = "file",
        exclude: list[str] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Find files matching glob pattern.

        Args:
            pattern: Glob pattern to match
            path: Base directory to search from
            max_results: Maximum number of results
            recursive: Search recursively below the base path
            kind: Restrict matches to files, directories, or either
            exclude: Patterns to exclude from results

        Returns:
            ToolResult with matching file paths or error message
        """
        # Note: 'pattern' required by schema
        try:
            # Validate path (resolves symlinks, checks allowed_paths if set)
            base_path = self._validate_path(path)
            fs_gateway = FilesystemAccessGateway(self._services, tool_name=self.name)

            # Verify base path exists and is a directory
            is_dir = await asyncio.to_thread(base_path.is_dir)
            if not is_dir:
                if await asyncio.to_thread(base_path.exists):
                    return ToolResult(error=f"Not a directory: {path}")
                return ToolResult(error=f"Directory not found: {path}")

            normalized_exclude = [_normalize_glob_pattern(item) for item in exclude or []]

            should_recurse = recursive or "**" in pattern

            # Execute bounded directory walk
            def do_glob() -> list[Path]:
                results: list[Path] = []

                def walk(current_dir: Path, relative_dir: PurePosixPath | None = None) -> None:
                    try:
                        entries = sorted(current_dir.iterdir(), key=lambda entry: entry.name)
                    except OSError:
                        return

                    for entry in entries:
                        rel_path = (
                            PurePosixPath(entry.name)
                            if relative_dir is None
                            else relative_dir / entry.name
                        )

                        decision = fs_gateway.decide_path(entry, must_exist=True)
                        if not decision.allowed:
                            continue

                        try:
                            is_dir_entry = entry.is_dir()
                        except OSError:
                            continue

                        if _matches_exclude_patterns(rel_path, normalized_exclude):
                            continue

                        if _matches_glob_pattern(rel_path, pattern) and _matches_kind(
                            is_dir=is_dir_entry,
                            kind=kind,
                        ):
                            results.append(entry)
                            if len(results) >= max_results:
                                return

                        if should_recurse and is_dir_entry and not entry.is_symlink():
                            walk(entry, rel_path)
                            if len(results) >= max_results:
                                return

                walk(base_path)
                return results

            matches = await asyncio.to_thread(do_glob)

            if not matches:
                return ToolResult(output=f"No files matching '{pattern}' in {path}")

            # Format results as relative paths from base_path when possible
            lines = []
            for match in sorted(matches):
                try:
                    rel_path = match.relative_to(base_path)
                    lines.append(str(rel_path))
                except ValueError:
                    lines.append(str(match))

            result = "\n".join(lines)
            if len(matches) >= max_results:
                result += f"\n\n(Limited to {max_results} results)"

            return ToolResult(output=result)

        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))
        except Exception as e:
            return ToolResult(error=f"Error searching files: {e}")


def _normalize_glob_pattern(pattern: str) -> str:
    """Normalize user-provided glob patterns to POSIX-style separators."""
    return pattern.replace("\\", "/").rstrip("/")


def _matches_glob_pattern(rel_path: PurePosixPath, pattern: str) -> bool:
    """Return True when rel_path matches the caller's glob pattern."""
    return any(rel_path.match(candidate) for candidate in _iter_glob_variants(pattern))


def _matches_exclude_patterns(rel_path: PurePosixPath, exclude: list[str]) -> bool:
    """Return True when rel_path should be excluded."""
    for raw_pattern in exclude:
        if not raw_pattern:
            continue
        if _is_plain_path_segment_pattern(raw_pattern):
            if raw_pattern in rel_path.parts:
                return True
            continue
        if any(rel_path.match(candidate) for candidate in _iter_glob_variants(raw_pattern)):
            return True
    return False


def _is_plain_path_segment_pattern(pattern: str) -> bool:
    """Return True when pattern is a literal path segment name."""
    return not any(char in pattern for char in "*?[]/{}")


def _iter_glob_variants(pattern: str) -> tuple[str, ...]:
    """Generate equivalent glob variants for more predictable path matching."""
    normalized = _normalize_glob_pattern(pattern)
    if not normalized:
        return ()

    candidates: list[str] = [normalized]

    if normalized.startswith("**/"):
        trimmed = normalized[3:]
        if trimmed:
            candidates.append(trimmed)
    else:
        candidates.append(f"**/{normalized}")

    if normalized.endswith("/**"):
        prefix = normalized[:-3].rstrip("/")
        if prefix:
            candidates.append(prefix)
            if prefix.startswith("**/"):
                trimmed_prefix = prefix[3:]
                if trimmed_prefix:
                    candidates.append(trimmed_prefix)
            else:
                candidates.append(f"**/{prefix}")

    deduped: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return tuple(deduped)


def _matches_kind(*, is_dir: bool, kind: str) -> bool:
    """Return True when the entry kind matches the caller's filter."""
    if kind == "any":
        return True
    if kind == "directory":
        return is_dir
    return not is_dir


# Factory for dependency injection
glob_factory = file_skill_factory(GlobSkill)
