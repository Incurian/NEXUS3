"""Tail skill for reading last N lines of a file."""

import asyncio
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory


class TailSkill(FileSkill):
    """Skill that reads the last N lines of a file.

    More intuitive than negative offsets for common use cases like
    reading log files or recent output.

    Inherits path validation from FileSkill.
    """

    @property
    def name(self) -> str:
        return "tail"

    @property
    def description(self) -> str:
        return "Read the last N lines of a file"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the file to read"
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of lines from end (default: 10)",
                    "default": 10
                }
            },
            "required": ["path"]
        }

    async def execute(
        self,
        path: str = "",
        lines: int = 10,
        **kwargs: Any
    ) -> ToolResult:
        """Read the last N lines of the file.

        Args:
            path: The path to the file to read
            lines: Number of lines from end (default: 10)

        Returns:
            ToolResult with file contents in output, or error message in error
        """
        if not path:
            return ToolResult(error="No path provided")

        if lines < 1:
            return ToolResult(error="Lines must be at least 1")

        try:
            # Validate path (resolves symlinks, checks allowed_paths if set)
            p = self._validate_path(path)

            # Use async file I/O to avoid blocking
            content = await asyncio.to_thread(p.read_text, encoding="utf-8")

            # Get last N lines
            all_lines = content.splitlines(keepends=True)
            total_lines = len(all_lines)

            if lines >= total_lines:
                # Return entire file with line numbers
                numbered = [
                    f"{i + 1}: {line}"
                    for i, line in enumerate(all_lines)
                ]
            else:
                # Return last N lines with correct line numbers
                start_idx = total_lines - lines
                selected_lines = all_lines[start_idx:]
                numbered = [
                    f"{start_idx + i + 1}: {line}"
                    for i, line in enumerate(selected_lines)
                ]

            return ToolResult(output="".join(numbered))

        except PathSecurityError as e:
            return ToolResult(error=str(e))
        except FileNotFoundError:
            return ToolResult(error=f"File not found: {path}")
        except PermissionError:
            return ToolResult(error=f"Permission denied: {path}")
        except IsADirectoryError:
            return ToolResult(error=f"Path is a directory, not a file: {path}")
        except UnicodeDecodeError:
            return ToolResult(error=f"File is not valid UTF-8 text: {path}")
        except Exception as e:
            return ToolResult(error=f"Error reading file: {e}")


# Factory for dependency injection
tail_factory = file_skill_factory(TailSkill)
