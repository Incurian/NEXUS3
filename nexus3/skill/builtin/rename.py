"""Rename/move skill for renaming or moving files and directories."""

import asyncio
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory


class RenameSkill(FileSkill):
    """Skill that renames or moves files and directories.

    Works for both files and directories. Can move across directories
    on the same filesystem. Creates parent directories of destination
    if needed.

    Inherits path validation from FileSkill.
    """

    @property
    def name(self) -> str:
        return "rename"

    @property
    def description(self) -> str:
        return "Rename or move a file or directory"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Current path of the file or directory"
                },
                "destination": {
                    "type": "string",
                    "description": "New path for the file or directory"
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
        """Rename or move a file or directory.

        Args:
            source: Current path of the file or directory
            destination: New path for the file or directory
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
                return ToolResult(error=f"Source not found: {source}")

            # Check destination
            if dst_path.exists():
                if not overwrite:
                    return ToolResult(
                        error=f"Destination already exists: {destination}."
                        " Use overwrite=true to replace."
                    )
                # Remove destination if overwriting
                if dst_path.is_dir():
                    # Don't allow overwriting directory with file or vice versa
                    if not src_path.is_dir():
                        return ToolResult(
                            error=f"Cannot overwrite directory with file: {destination}"
                        )
                    # For directory overwrite, use shutil.rmtree
                    import shutil
                    await asyncio.to_thread(shutil.rmtree, dst_path)
                else:
                    if src_path.is_dir():
                        return ToolResult(
                            error=f"Cannot overwrite file with directory: {destination}"
                        )
                    await asyncio.to_thread(dst_path.unlink)

            # Create parent directories
            await asyncio.to_thread(dst_path.parent.mkdir, parents=True, exist_ok=True)

            # Perform the rename/move
            await asyncio.to_thread(src_path.rename, dst_path)

            item_type = "directory" if dst_path.is_dir() else "file"
            return ToolResult(output=f"Renamed {item_type}: {source} -> {destination}")

        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))
        except PermissionError as e:
            return ToolResult(error=f"Permission denied: {e}")
        except OSError as e:
            # Cross-device move would need shutil.move, but that's more complex
            if "cross-device" in str(e).lower():
                return ToolResult(
                    error=f"Cannot move across filesystems. Use copy_file + delete instead: {e}"
                )
            return ToolResult(error=f"OS error renaming: {e}")
        except Exception as e:
            return ToolResult(error=f"Error renaming: {e}")


# Factory for dependency injection
rename_factory = file_skill_factory(RenameSkill)
