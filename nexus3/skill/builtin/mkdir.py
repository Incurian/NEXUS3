"""Make directory skill for creating directories."""

import asyncio
from pathlib import Path
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import normalize_path, validate_sandbox
from nexus3.core.types import ToolResult
from nexus3.skill.services import ServiceContainer


class MkdirSkill:
    """Skill that creates directories.

    Creates parent directories as needed (like mkdir -p).
    Succeeds silently if directory already exists.

    If allowed_paths is provided, path validation is performed to ensure
    the directory is within the sandbox.
    """

    def __init__(self, allowed_paths: list[Path] | None = None) -> None:
        """Initialize MkdirSkill.

        Args:
            allowed_paths: List of allowed directories for path validation.
                - None: No sandbox validation (unrestricted access)
                - []: Empty list means NO paths allowed (all mkdir denied)
                - [Path(...)]: Only allow mkdir within these directories
        """
        self._allowed_paths = allowed_paths

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
            # Validate sandbox if allowed_paths is configured
            if self._allowed_paths is not None:
                p = validate_sandbox(path, self._allowed_paths)
            else:
                p = normalize_path(path)

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


def mkdir_factory(services: ServiceContainer) -> MkdirSkill:
    """Factory function for MkdirSkill.

    Args:
        services: ServiceContainer for dependency injection. If it contains
            'allowed_paths', sandbox validation will be enabled.

    Returns:
        New MkdirSkill instance
    """
    allowed_paths: list[Path] | None = services.get("allowed_paths")
    return MkdirSkill(allowed_paths=allowed_paths)
