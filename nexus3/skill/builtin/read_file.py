"""Read file skill for reading file contents."""

import asyncio
from pathlib import Path
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import normalize_path, validate_sandbox
from nexus3.core.types import ToolResult
from nexus3.skill.services import ServiceContainer


class ReadFileSkill:
    """Skill that reads the contents of a file.

    Returns the file contents as text, or an error if the file
    cannot be read.

    If allowed_paths is provided, path validation is performed to ensure
    the file is within the sandbox. Otherwise, any path is allowed.
    """

    def __init__(self, allowed_paths: list[Path] | None = None) -> None:
        """Initialize ReadFileSkill.

        Args:
            allowed_paths: List of allowed directories. If None, no sandbox
                validation is performed (unrestricted access).
        """
        self._allowed_paths = allowed_paths

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
                }
            },
            "required": ["path"]
        }

    async def execute(self, path: str = "", **kwargs: Any) -> ToolResult:
        """Read the file and return its contents.

        Args:
            path: The path to the file to read

        Returns:
            ToolResult with file contents in output, or error message in error
        """
        if not path:
            return ToolResult(error="No path provided")

        try:
            # Validate sandbox if allowed_paths is configured
            if self._allowed_paths is not None:
                p = validate_sandbox(path, self._allowed_paths)
            else:
                p = normalize_path(path)

            # Use async file I/O to avoid blocking
            content = await asyncio.to_thread(p.read_text, encoding="utf-8")
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


def read_file_factory(services: ServiceContainer) -> ReadFileSkill:
    """Factory function for ReadFileSkill.

    Args:
        services: ServiceContainer for dependency injection. If it contains
            'allowed_paths', sandbox validation will be enabled.

    Returns:
        New ReadFileSkill instance
    """
    allowed_paths: list[Path] | None = services.get("allowed_paths")
    return ReadFileSkill(allowed_paths=allowed_paths)
