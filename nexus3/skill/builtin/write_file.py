"""Write file skill for writing content to files."""

import asyncio
from pathlib import Path
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import normalize_path, validate_sandbox
from nexus3.core.types import ToolResult
from nexus3.skill.services import ServiceContainer


class WriteFileSkill:
    """Skill that writes content to a file.

    Creates parent directories if needed. Overwrites existing files.

    If allowed_paths is provided, path validation is performed to ensure
    the file is within the sandbox. Otherwise, any path is allowed.
    """

    def __init__(self, allowed_paths: list[Path] | None = None) -> None:
        """Initialize WriteFileSkill.

        Args:
            allowed_paths: List of allowed directories for path validation.
                - None: No sandbox validation (unrestricted access)
                - []: Empty list means NO paths allowed (all writes denied)
                - [Path(...)]: Only allow writes within these directories
        """
        # None = unrestricted, [] = deny all, [paths...] = only within these
        self._allowed_paths = allowed_paths

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write content to a file (creates or overwrites)"

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
            # Validate sandbox if allowed_paths is configured
            if self._allowed_paths is not None:
                p = validate_sandbox(path, self._allowed_paths)
            else:
                p = normalize_path(path)

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


def write_file_factory(services: ServiceContainer) -> WriteFileSkill:
    """Factory function for WriteFileSkill.

    Args:
        services: ServiceContainer for dependency injection. If it contains
            'allowed_paths', sandbox validation will be enabled.

    Returns:
        New WriteFileSkill instance
    """
    allowed_paths: list[Path] | None = services.get("allowed_paths")
    return WriteFileSkill(allowed_paths=allowed_paths)
