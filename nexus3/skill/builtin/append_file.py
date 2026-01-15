"""Append file skill for appending content to files."""

import asyncio
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import atomic_write_text
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory


class AppendFileSkill(FileSkill):
    """Skill that appends content to a file.

    More atomic than read+concat+write, with smart newline handling.

    Inherits path validation from FileSkill.
    """

    @property
    def name(self) -> str:
        return "append_file"

    @property
    def description(self) -> str:
        return (
            "Append content to a file. "
            "IMPORTANT: Read the file first to understand its current content and structure."
        )

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
            # Validate path (resolves symlinks, checks allowed_paths if set)
            p = self._validate_path(path)

            def do_append() -> int:
                # Read existing content (or empty if new file)
                existing = ""
                if p.exists():
                    existing = p.read_text(encoding="utf-8")

                # Smart newline handling
                to_write = content
                if newline and existing and not existing.endswith("\n"):
                    to_write = "\n" + content

                # Append to file atomically (temp file + rename)
                atomic_write_text(p, existing + to_write)
                return len(to_write)

            chars_written = await asyncio.to_thread(do_append)
            return ToolResult(output=f"Appended {chars_written} characters to {path}")

        except PathSecurityError as e:
            return ToolResult(error=str(e))
        except PermissionError:
            return ToolResult(error=f"Permission denied: {path}")
        except IsADirectoryError:
            return ToolResult(error=f"Path is a directory, not a file: {path}")
        except Exception as e:
            return ToolResult(error=f"Error appending to file: {e}")


# Factory for dependency injection
append_file_factory = file_skill_factory(AppendFileSkill)
