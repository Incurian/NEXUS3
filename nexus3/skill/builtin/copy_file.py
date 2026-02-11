"""Copy file skill for copying files."""

import asyncio
import shutil
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory


class CopyFileSkill(FileSkill):
    """Skill that copies a file to a new location.

    Preserves file metadata (permissions, timestamps) by default.
    Creates parent directories of destination if needed.

    Inherits path validation from FileSkill.
    """

    @property
    def name(self) -> str:
        return "copy_file"

    @property
    def description(self) -> str:
        return "Copy a file to a new location (preserves metadata)"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Path to the source file to copy"
                },
                "destination": {
                    "type": "string",
                    "description": "Path for the destination file"
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Overwrite destination if it exists (default: false)",
                    "default": False
                }
            },
            "required": ["source", "destination"]
        }

    async def execute(
        self,
        source: str = "",
        destination: str = "",
        overwrite: bool = False,
        **kwargs: Any
    ) -> ToolResult:
        """Copy a file to the destination.

        Args:
            source: Path to the source file
            destination: Path for the destination file
            overwrite: Whether to overwrite existing destination
            **kwargs: Additional arguments (ignored)

        Returns:
            ToolResult with success message or error
        """
        if not source:
            return ToolResult(error="Source path is required")
        if not destination:
            return ToolResult(error="Destination path is required")

        try:
            # Validate both paths (resolves symlinks, checks allowed_paths if set)
            src_path = self._validate_path(source)
            dst_path = self._validate_path(destination)

            # Check source exists
            if not src_path.exists():
                return ToolResult(error=f"Source file not found: {source}")

            if not src_path.is_file():
                return ToolResult(error=f"Source is not a file: {source}")

            # Check destination
            if dst_path.exists() and not overwrite:
                return ToolResult(
                    error=f"Destination already exists: {destination}."
                    " Use overwrite=true to replace."
                )

            # Create parent directories
            await asyncio.to_thread(dst_path.parent.mkdir, parents=True, exist_ok=True)

            # Copy with metadata
            await asyncio.to_thread(shutil.copy2, src_path, dst_path)

            return ToolResult(output=f"Copied {source} to {destination}")

        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))
        except PermissionError as e:
            return ToolResult(error=f"Permission denied: {e}")
        except OSError as e:
            return ToolResult(error=f"OS error copying file: {e}")
        except Exception as e:
            return ToolResult(error=f"Error copying file: {e}")


# Factory for dependency injection
copy_file_factory = file_skill_factory(CopyFileSkill)
