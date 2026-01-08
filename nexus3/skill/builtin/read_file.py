"""Read file skill for reading file contents."""

from typing import Any

from nexus3.core.paths import normalize_path
from nexus3.core.types import ToolResult
from nexus3.skill.services import ServiceContainer


class ReadFileSkill:
    """Skill that reads the contents of a file.

    Returns the file contents as text, or an error if the file
    cannot be read.
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
            p = normalize_path(path)
            content = p.read_text(encoding="utf-8")
            return ToolResult(output=content)
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
        services: ServiceContainer (unused, but required by factory protocol)

    Returns:
        New ReadFileSkill instance
    """
    return ReadFileSkill()
