"""Write file skill for writing content to files."""

from typing import Any

from nexus3.core.paths import normalize_path
from nexus3.core.types import ToolResult
from nexus3.skill.services import ServiceContainer


class WriteFileSkill:
    """Skill that writes content to a file.

    Creates parent directories if needed. Overwrites existing files.
    """

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
            p = normalize_path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return ToolResult(output=f"Successfully wrote {len(content)} bytes to {path}")
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
        services: ServiceContainer (unused, but required by factory protocol)

    Returns:
        New WriteFileSkill instance
    """
    return WriteFileSkill()
