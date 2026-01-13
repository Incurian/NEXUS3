"""Append file skill for appending content to files."""

import asyncio
from pathlib import Path
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import normalize_path, validate_sandbox
from nexus3.core.types import ToolResult
from nexus3.skill.services import ServiceContainer


class AppendFileSkill:
    """Skill that appends content to a file.

    More atomic than read+concat+write, with smart newline handling.

    If allowed_paths is provided, path validation is performed to ensure
    the file is within the sandbox. Otherwise, any path is allowed.
    """

    def __init__(self, allowed_paths: list[Path] | None = None) -> None:
        """Initialize AppendFileSkill.

        Args:
            allowed_paths: List of allowed directories for path validation.
                - None: No sandbox validation (unrestricted access)
                - []: Empty list means NO paths allowed (all appends denied)
                - [Path(...)]: Only allow appends within these directories
        """
        self._allowed_paths = allowed_paths

    @property
    def name(self) -> str:
        return "append_file"

    @property
    def description(self) -> str:
        return "Append content to a file"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the file to append to"
                },
                "content": {
                    "type": "string",
                    "description": "Content to append"
                },
                "newline": {
                    "type": "boolean",
                    "description": "Add newline before content if file doesn't end with one (default: true)",
                    "default": True
                }
            },
            "required": ["path", "content"]
        }

    async def execute(
        self,
        path: str = "",
        content: str = "",
        newline: bool = True,
        **kwargs: Any
    ) -> ToolResult:
        """Append content to file.

        Args:
            path: The path to the file to append to
            content: Content to append
            newline: Add newline before content if file doesn't end with one

        Returns:
            ToolResult with success message or error
        """
        if not path:
            return ToolResult(error="No path provided")

        if not content:
            return ToolResult(error="No content provided")

        try:
            # Validate sandbox if allowed_paths is configured
            if self._allowed_paths is not None:
                p = validate_sandbox(path, self._allowed_paths)
            else:
                p = normalize_path(path)

            def do_append() -> int:
                # Read existing content (or empty if new file)
                existing = ""
                if p.exists():
                    existing = p.read_text(encoding="utf-8")

                # Smart newline handling
                to_write = content
                if newline and existing and not existing.endswith("\n"):
                    to_write = "\n" + content

                # Append to file
                p.write_text(existing + to_write, encoding="utf-8")
                return len(to_write)

            bytes_written = await asyncio.to_thread(do_append)
            return ToolResult(output=f"Appended {bytes_written} bytes to {path}")

        except PathSecurityError as e:
            return ToolResult(error=str(e))
        except PermissionError:
            return ToolResult(error=f"Permission denied: {path}")
        except IsADirectoryError:
            return ToolResult(error=f"Path is a directory, not a file: {path}")
        except Exception as e:
            return ToolResult(error=f"Error appending to file: {e}")


def append_file_factory(services: ServiceContainer) -> AppendFileSkill:
    """Factory function for AppendFileSkill.

    Args:
        services: ServiceContainer for dependency injection. If it contains
            'allowed_paths', sandbox validation will be enabled.

    Returns:
        New AppendFileSkill instance
    """
    allowed_paths: list[Path] | None = services.get("allowed_paths")
    return AppendFileSkill(allowed_paths=allowed_paths)
