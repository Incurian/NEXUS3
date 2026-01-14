"""Make directory skill for creating directories."""

import asyncio
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory


class MkdirSkill(FileSkill):
    """Skill that creates directories.

    Creates parent directories as needed (like mkdir -p).
    Succeeds silently if directory already exists.

    Inherits path validation from FileSkill.
    """

    @property
    def name(self) -> str:
        return "mkdir"

    @property
    def description(self) -> str:
        return "Create a directory (and parent directories if needed)"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path of the directory to create"
                }
            },
            "required": ["path"]
        }

    async def execute(self, path: str = "", **kwargs: Any) -> ToolResult:
        """Create the directory.

        Args:
            path: Path of the directory to create
            **kwargs: Additional arguments (ignored)

        Returns:
            ToolResult with success message or error
        """
        if not path:
            return ToolResult(error="Path is required")

        try:
            # Validate path (resolves symlinks, checks allowed_paths if set)
            p = self._validate_path(path)

            # Check if path exists as a file
            if p.exists() and not p.is_dir():
                return ToolResult(error=f"Path exists and is not a directory: {path}")

            # Create directory (and parents)
            already_exists = p.exists()
            await asyncio.to_thread(p.mkdir, parents=True, exist_ok=True)

            if already_exists:
                return ToolResult(output=f"Directory already exists: {path}")
            else:
                return ToolResult(output=f"Created directory: {path}")

        except PathSecurityError as e:
            return ToolResult(error=str(e))
        except PermissionError:
            return ToolResult(error=f"Permission denied: {path}")
        except OSError as e:
            return ToolResult(error=f"OS error creating directory: {e}")
        except Exception as e:
            return ToolResult(error=f"Error creating directory: {e}")


# Factory for dependency injection
mkdir_factory = file_skill_factory(MkdirSkill)
