"""Grep skill for searching file contents with regex."""

import asyncio
import re
from pathlib import Path
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import normalize_path, validate_sandbox
from nexus3.core.types import ToolResult
from nexus3.skill.services import ServiceContainer


class GrepSkill:
    """Skill that searches file contents using regular expressions.

    Supports searching a single file or recursively searching a directory.

    If allowed_paths is provided, path validation is performed to ensure
    searches are within the sandbox.
    """

    def __init__(self, allowed_paths: list[Path] | None = None) -> None:
        """Initialize GrepSkill.

        Args:
            allowed_paths: List of allowed directories for path validation.
                - None: No sandbox validation (unrestricted access)
                - []: Empty list means NO paths allowed (all searches denied)
                - [Path(...)]: Only allow searches within these directories
        """
        # None = unrestricted, [] = deny all, [paths...] = only within these
        self._allowed_paths = allowed_paths

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
        **kwargs: Any
    ) -> ToolResult:
        """Search for pattern in file(s).

        Args:
            pattern: Regex pattern to search for
            path: File or directory to search
            recursive: Search subdirectories
            ignore_case: Case-insensitive matching
            max_matches: Maximum matches to return

        Returns:
            ToolResult with matching lines or error message
        """
        if not pattern:
            return ToolResult(error="Pattern is required")
        if not path:
            return ToolResult(error="Path is required")

        try:
            # Compile regex
            flags = re.IGNORECASE if ignore_case else 0
            try:
                regex = re.compile(pattern, flags)
            except re.error as e:
                return ToolResult(error=f"Invalid regex pattern: {e}")

            # Validate sandbox if allowed_paths is configured
            if self._allowed_paths is not None:
                search_path = validate_sandbox(path, self._allowed_paths)
            else:
                search_path = normalize_path(path)

            # Determine files to search
            is_file = await asyncio.to_thread(search_path.is_file)
            is_dir = await asyncio.to_thread(search_path.is_dir)

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

            # Search files
            matches: list[str] = []
            files_searched = 0
            files_with_matches = 0

            for file_path in files_to_search:
                if len(matches) >= max_matches:
                    break

                # Validate each file against sandbox
                if self._allowed_paths is not None:
                    try:
                        validate_sandbox(file_path, self._allowed_paths)
                    except PathSecurityError:
                        continue

                # Skip binary files and unreadable files
                try:
                    content = await asyncio.to_thread(
                        file_path.read_text, encoding="utf-8"
                    )
                    files_searched += 1
                except (UnicodeDecodeError, PermissionError, OSError):
                    continue

                # Search for matches
                file_has_match = False
                for line_num, line in enumerate(content.splitlines(), 1):
                    if regex.search(line):
                        if not file_has_match:
                            file_has_match = True
                            files_with_matches += 1

                        # Format output
                        try:
                            rel_path = file_path.relative_to(search_path)
                        except ValueError:
                            rel_path = file_path

                        matches.append(f"{rel_path}:{line_num}: {line.rstrip()}")

                        if len(matches) >= max_matches:
                            break

            if not matches:
                return ToolResult(output=f"No matches for '{pattern}' in {path}")

            result = "\n".join(matches)
            summary = f"\n\n({len(matches)} matches in {files_with_matches} files, {files_searched} files searched)"
            if len(matches) >= max_matches:
                summary = f"\n\n(Limited to {max_matches} matches, {files_with_matches}+ files matched, {files_searched} files searched)"

            return ToolResult(output=result + summary)

        except PathSecurityError as e:
            return ToolResult(error=str(e))
        except Exception as e:
            return ToolResult(error=f"Error searching: {e}")


def grep_factory(services: ServiceContainer) -> GrepSkill:
    """Factory function for GrepSkill.

    Args:
        services: ServiceContainer for dependency injection. If it contains
            'allowed_paths', sandbox validation will be enabled.

    Returns:
        New GrepSkill instance
    """
    allowed_paths: list[Path] | None = services.get("allowed_paths")
    return GrepSkill(allowed_paths=allowed_paths)
