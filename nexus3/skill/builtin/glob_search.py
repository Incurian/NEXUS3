"""Glob search skill for finding files by pattern."""

import asyncio
from pathlib import Path
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import validate_path
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory, validate_skill_parameters


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
        return "Find files matching a glob pattern"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g., '*.py', '**/*.txt', 'src/**/*.js')"
                },
                "path": {
                    "type": "string",
                    "description": "Base directory to search from (default: current directory)"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 100)",
                    "default": 100
                },
                "exclude": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Patterns to exclude (e.g., ['node_modules', '.git', '__pycache__'])"
                }
            },
            "required": ["pattern"]
        }

    @validate_skill_parameters()
    async def execute(
        self,
        pattern: str = "",
        path: str = ".",
        max_results: int = 100,
        exclude: list[str] | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Find files matching glob pattern.

        Args:
            pattern: Glob pattern to match
            path: Base directory to search from
            max_results: Maximum number of results
            exclude: Patterns to exclude from results

        Returns:
            ToolResult with matching file paths or error message
        """
        # Note: 'pattern' required by schema
        try:
            # Validate path (resolves symlinks, checks allowed_paths if set)
            base_path = self._validate_path(path)

            # Verify base path exists and is a directory
            is_dir = await asyncio.to_thread(base_path.is_dir)
            if not is_dir:
                if await asyncio.to_thread(base_path.exists):
                    return ToolResult(error=f"Not a directory: {path}")
                return ToolResult(error=f"Directory not found: {path}")

            # Execute glob
            def do_glob() -> list[Path]:
                results = []
                for match in base_path.glob(pattern):
                    # If sandbox is active, verify each result is within sandbox
                    if self._allowed_paths is not None:
                        try:
                            validate_path(match, allowed_paths=self._allowed_paths)
                        except PathSecurityError:
                            continue  # Skip results outside sandbox

                    # Check exclusion patterns
                    if exclude:
                        match_str = str(match)
                        skip = False
                        for excl in exclude:
                            if excl in match_str:
                                skip = True
                                break
                        if skip:
                            continue

                    results.append(match)
                    if len(results) >= max_results:
                        break
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

        except PathSecurityError as e:
            return ToolResult(error=str(e))
        except Exception as e:
            return ToolResult(error=f"Error searching files: {e}")


# Factory for dependency injection
glob_factory = file_skill_factory(GlobSkill)
