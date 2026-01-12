"""Glob search skill for finding files by pattern."""

import asyncio
from pathlib import Path
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import normalize_path, validate_sandbox
from nexus3.core.types import ToolResult
from nexus3.skill.services import ServiceContainer


class GlobSkill:
    """Skill that finds files matching a glob pattern.

    Supports standard glob patterns like *.py, **/*.txt, etc.

    If allowed_paths is provided, both the base path and all results
    are validated against the sandbox.
    """

    def __init__(self, allowed_paths: list[Path] | None = None) -> None:
        """Initialize GlobSkill.

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
                }
            },
            "required": ["pattern"]
        }

    async def execute(
        self,
        pattern: str = "",
        path: str = ".",
        max_results: int = 100,
        **kwargs: Any
    ) -> ToolResult:
        """Find files matching glob pattern.

        Args:
            pattern: Glob pattern to match
            path: Base directory to search from
            max_results: Maximum number of results

        Returns:
            ToolResult with matching file paths or error message
        """
        if not pattern:
            return ToolResult(error="Pattern is required")

        try:
            # Validate sandbox if allowed_paths is configured
            if self._allowed_paths is not None:
                base_path = validate_sandbox(path, self._allowed_paths)
            else:
                base_path = normalize_path(path)

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
                            validate_sandbox(match, self._allowed_paths)
                        except PathSecurityError:
                            continue  # Skip results outside sandbox
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


def glob_factory(services: ServiceContainer) -> GlobSkill:
    """Factory function for GlobSkill.

    Args:
        services: ServiceContainer for dependency injection. If it contains
            'allowed_paths', sandbox validation will be enabled.

    Returns:
        New GlobSkill instance
    """
    allowed_paths: list[Path] | None = services.get("allowed_paths")
    return GlobSkill(allowed_paths=allowed_paths)
