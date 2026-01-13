"""Copy file skill for copying files."""

import asyncio
import shutil
from pathlib import Path
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import normalize_path, validate_sandbox
from nexus3.core.types import ToolResult
from nexus3.skill.services import ServiceContainer


class CopyFileSkill:
    """Skill that copies a file to a new location.

    Preserves file metadata (permissions, timestamps) by default.
    Creates parent directories of destination if needed.

    If allowed_paths is provided, both source and destination paths
    are validated against the sandbox.
    """

    def __init__(self, allowed_paths: list[Path] | None = None) -> None:
        """Initialize CopyFileSkill.

        Args:
            allowed_paths: List of allowed directories for path validation.
                - None: No sandbox validation (unrestricted access)
                - []: Empty list means NO paths allowed (all copies denied)
                - [Path(...)]: Only allow copies within these directories
        """
        self._allowed_paths = allowed_paths

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
            # Validate sandbox for both paths if configured
            if self._allowed_paths is not None:
                src_path = validate_sandbox(source, self._allowed_paths)
                dst_path = validate_sandbox(destination, self._allowed_paths)
            else:
                src_path = normalize_path(source)
                dst_path = normalize_path(destination)

            # Check source exists
            if not src_path.exists():
                return ToolResult(error=f"Source file not found: {source}")

            if not src_path.is_file():
                return ToolResult(error=f"Source is not a file: {source}")

            # Check destination
            if dst_path.exists() and not overwrite:
                return ToolResult(
                    error=f"Destination already exists: {destination}. Use overwrite=true to replace."
                )

            # Create parent directories
            await asyncio.to_thread(dst_path.parent.mkdir, parents=True, exist_ok=True)

            # Copy with metadata
            await asyncio.to_thread(shutil.copy2, src_path, dst_path)

            return ToolResult(output=f"Copied {source} to {destination}")

        except PathSecurityError as e:
            return ToolResult(error=str(e))
        except PermissionError as e:
            return ToolResult(error=f"Permission denied: {e}")
        except OSError as e:
            return ToolResult(error=f"OS error copying file: {e}")
        except Exception as e:
            return ToolResult(error=f"Error copying file: {e}")


def copy_file_factory(services: ServiceContainer) -> CopyFileSkill:
    """Factory function for CopyFileSkill.

    Args:
        services: ServiceContainer for dependency injection. If it contains
            'allowed_paths', sandbox validation will be enabled.

    Returns:
        New CopyFileSkill instance
    """
    allowed_paths: list[Path] | None = services.get("allowed_paths")
    return CopyFileSkill(allowed_paths=allowed_paths)
