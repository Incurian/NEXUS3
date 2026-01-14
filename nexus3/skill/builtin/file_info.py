"""File info skill for getting file metadata."""

import asyncio
import json
import stat
from datetime import datetime, timezone
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory


def _format_size(size_bytes: int) -> str:
    """Format byte size as human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            if unit == "B":
                return f"{size_bytes} {unit}"
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def _format_permissions(mode: int) -> str:
    """Format file mode as rwxrwxrwx string."""
    perms = []
    for who in ("USR", "GRP", "OTH"):
        for perm in ("R", "W", "X"):
            flag = getattr(stat, f"S_I{perm}{who}")
            perms.append(perm.lower() if mode & flag else "-")
    return "".join(perms)


class FileInfoSkill(FileSkill):
    """Skill that gets file or directory metadata.

    Returns information like size, modification time, type, and permissions
    without needing bash access.

    Inherits path validation from FileSkill.
    """

    @property
    def name(self) -> str:
        return "file_info"

    @property
    def description(self) -> str:
        return "Get metadata about a file or directory (size, modified, permissions)"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the file or directory"
                }
            },
            "required": ["path"]
        }

    async def execute(self, path: str = "", **kwargs: Any) -> ToolResult:
        """Get file or directory metadata.

        Args:
            path: The path to stat

        Returns:
            ToolResult with JSON metadata in output, or error message in error
        """
        if not path:
            return ToolResult(error="No path provided")

        try:
            # Validate path (resolves symlinks, checks allowed_paths if set)
            p = self._validate_path(path)

            # Use async to avoid blocking on stat
            def do_stat() -> dict[str, Any]:
                if not p.exists():
                    raise FileNotFoundError(f"Path does not exist: {path}")

                st = p.stat()

                # Determine type
                if p.is_file():
                    file_type = "file"
                elif p.is_dir():
                    file_type = "directory"
                elif p.is_symlink():
                    file_type = "symlink"
                else:
                    file_type = "other"

                # Format modification time in ISO format
                mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)

                return {
                    "path": str(p.resolve()),
                    "type": file_type,
                    "size": st.st_size,
                    "size_human": _format_size(st.st_size),
                    "modified": mtime.isoformat(),
                    "permissions": _format_permissions(st.st_mode),
                    "exists": True
                }

            info = await asyncio.to_thread(do_stat)
            return ToolResult(output=json.dumps(info, indent=2))

        except PathSecurityError as e:
            return ToolResult(error=str(e))
        except FileNotFoundError:
            # Return structured response for non-existent paths
            return ToolResult(output=json.dumps({
                "path": path,
                "exists": False
            }, indent=2))
        except PermissionError:
            return ToolResult(error=f"Permission denied: {path}")
        except Exception as e:
            return ToolResult(error=f"Error getting file info: {e}")


# Factory for dependency injection
file_info_factory = file_skill_factory(FileInfoSkill)
