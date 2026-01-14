"""Write file skill for writing content to files."""

import asyncio
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory


class WriteFileSkill(FileSkill):
    """Skill that writes content to a file.

    Creates parent directories if needed. Overwrites existing files.

    Inherits path validation from FileSkill.
    """

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return (
            "Write content to a file (creates or overwrites). "
            "IMPORTANT: If modifying an existing file, read it first to understand its current state."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file path to write to"
                },
                "content": {
                    "type": "string",
                    "description": "The content to write to the file"
                }
            },
            "required": ["path", "content"]
        }

    async def execute(self, path: str = "", content: str = "", **kwargs: Any) -> ToolResult:
        """Write content to the specified file.

        Args:
            path: The file path to write to
            content: The content to write
            **kwargs: Additional arguments (ignored)

        Returns:
            ToolResult with success message or error
        """
        if not path:
            return ToolResult(error="Path is required")

        try:
            # Validate path (resolves symlinks, checks allowed_paths if set)
            p = self._validate_path(path)

            # Use async file I/O to avoid blocking
            await asyncio.to_thread(p.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(p.write_text, content, encoding="utf-8")
            return ToolResult(output=f"Successfully wrote {len(content)} bytes to {path}")
        except PathSecurityError as e:
            return ToolResult(error=str(e))
        except PermissionError:
            return ToolResult(error=f"Permission denied: {path}")
        except IsADirectoryError:
            return ToolResult(error=f"Path is a directory: {path}")
        except OSError as e:
            return ToolResult(error=f"OS error writing file: {e}")
        except Exception as e:
            return ToolResult(error=f"Error writing file: {e}")


# Factory for dependency injection
write_file_factory = file_skill_factory(WriteFileSkill)
