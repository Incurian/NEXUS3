"""Read file skill for reading file contents."""

import asyncio
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory


class ReadFileSkill(FileSkill):
    """Skill that reads the contents of a file.

    Returns the file contents as text, or an error if the file
    cannot be read.

    Inherits path validation from FileSkill.
    """

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read the contents of a file"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the file to read"
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (1-indexed, default: 1)",
                    "minimum": 1,
                    "default": 1
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read (default: all)"
                }
            },
            "required": ["path"]
        }

    async def execute(
        self,
        path: str = "",
        offset: int = 1,
        limit: int | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Read the file and return its contents.

        Args:
            path: The path to the file to read
            offset: Line number to start reading from (1-indexed, default: 1)
            limit: Maximum number of lines to read (default: all)

        Returns:
            ToolResult with file contents in output, or error message in error
        """
        # Note: 'path' required by schema, 'offset' minimum:1 enforced by schema
        try:
            # Validate path (resolves symlinks, checks allowed_paths if set)
            p = self._validate_path(path)

            # Use async file I/O to avoid blocking
            content = await asyncio.to_thread(p.read_text, encoding="utf-8")

            # Apply offset and limit if specified
            if offset > 1 or limit is not None:
                lines = content.splitlines(keepends=True)
                start_idx = offset - 1  # Convert to 0-indexed
                if limit is not None:
                    end_idx = start_idx + limit
                    selected_lines = lines[start_idx:end_idx]
                else:
                    selected_lines = lines[start_idx:]

                # Format with line numbers
                numbered = [
                    f"{start_idx + i + 1}: {line}"
                    for i, line in enumerate(selected_lines)
                ]
                return ToolResult(output="".join(numbered))

            return ToolResult(output=content)
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
read_file_factory = file_skill_factory(ReadFileSkill)
