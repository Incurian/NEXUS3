"""List directory skill for listing files and directories."""

import asyncio
import os
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import normalize_path, validate_sandbox
from nexus3.core.types import ToolResult
from nexus3.skill.services import ServiceContainer


class ListDirectorySkill:
    """Skill that lists contents of a directory.

    Returns file names, optionally with metadata (size, mtime, permissions).

    If allowed_paths is provided, path validation is performed to ensure
    the directory is within the sandbox. Otherwise, any path is allowed.
    """

    def __init__(self, allowed_paths: list[Path] | None = None) -> None:
        """Initialize ListDirectorySkill.

        Args:
            allowed_paths: List of allowed directories for path validation.
                - None: No sandbox validation (unrestricted access)
                - []: Empty list means NO paths allowed (all listings denied)
                - [Path(...)]: Only allow listings within these directories
        """
        # None = unrestricted, [] = deny all, [paths...] = only within these
        self._allowed_paths = allowed_paths

    @property
    def name(self) -> str:
        return "list_directory"

    @property
    def description(self) -> str:
        return "List contents of a directory"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path to list (default: current directory)"
                },
                "all": {
                    "type": "boolean",
                    "description": "Include hidden files (starting with .)",
                    "default": False
                },
                "long": {
                    "type": "boolean",
                    "description": "Include size, modification time, and permissions",
                    "default": False
                }
            },
            "required": []
        }

    async def execute(
        self,
        path: str = ".",
        all: bool = False,  # noqa: A002 - matches parameter name
        long: bool = False,
        **kwargs: Any
    ) -> ToolResult:
        """List directory contents.

        Args:
            path: Directory path to list (default: current directory)
            all: Include hidden files
            long: Include detailed metadata

        Returns:
            ToolResult with directory listing or error message
        """
        try:
            # Validate sandbox if allowed_paths is configured
            if self._allowed_paths is not None:
                p = validate_sandbox(path, self._allowed_paths)
            else:
                p = normalize_path(path)

            # Verify it's a directory
            is_dir = await asyncio.to_thread(p.is_dir)
            if not is_dir:
                if await asyncio.to_thread(p.exists):
                    return ToolResult(error=f"Not a directory: {path}")
                return ToolResult(error=f"Directory not found: {path}")

            # Get directory entries
            entries = await asyncio.to_thread(list, p.iterdir())

            # Filter hidden files unless 'all' is True
            if not all:
                entries = [e for e in entries if not e.name.startswith(".")]

            # Sort entries: directories first, then files, alphabetically
            entries.sort(key=lambda e: (not e.is_dir(), e.name.lower()))

            if long:
                lines = []
                for entry in entries:
                    try:
                        stat_info = await asyncio.to_thread(entry.stat)
                        size = stat_info.st_size
                        mtime = datetime.fromtimestamp(stat_info.st_mtime)
                        mtime_str = mtime.strftime("%Y-%m-%d %H:%M")
                        mode = stat_info.st_mode

                        # Build permission string
                        perms = _format_permissions(mode)

                        # Type indicator
                        type_char = "d" if stat.S_ISDIR(mode) else "-"

                        # Size formatting
                        size_str = _format_size(size)

                        lines.append(f"{type_char}{perms}  {size_str:>8}  {mtime_str}  {entry.name}")
                    except (OSError, PermissionError) as e:
                        lines.append(f"?  ?  ?  {entry.name}  (error: {e})")

                output = "\n".join(lines)
            else:
                # Simple listing
                output = "\n".join(e.name + ("/" if e.is_dir() else "") for e in entries)

            if not output:
                output = "(empty directory)"

            return ToolResult(output=output)

        except PathSecurityError as e:
            return ToolResult(error=str(e))
        except PermissionError:
            return ToolResult(error=f"Permission denied: {path}")
        except Exception as e:
            return ToolResult(error=f"Error listing directory: {e}")


def _format_permissions(mode: int) -> str:
    """Format file permissions as rwxrwxrwx string."""
    perms = ""
    for who in [stat.S_IRUSR, stat.S_IWUSR, stat.S_IXUSR,
                stat.S_IRGRP, stat.S_IWGRP, stat.S_IXGRP,
                stat.S_IROTH, stat.S_IWOTH, stat.S_IXOTH]:
        if mode & who:
            if who in (stat.S_IRUSR, stat.S_IRGRP, stat.S_IROTH):
                perms += "r"
            elif who in (stat.S_IWUSR, stat.S_IWGRP, stat.S_IWOTH):
                perms += "w"
            else:
                perms += "x"
        else:
            perms += "-"
    return perms


def _format_size(size: int) -> str:
    """Format file size in human-readable form."""
    if size < 1024:
        return f"{size}B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f}K"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f}M"
    else:
        return f"{size / (1024 * 1024 * 1024):.1f}G"


def list_directory_factory(services: ServiceContainer) -> ListDirectorySkill:
    """Factory function for ListDirectorySkill.

    Args:
        services: ServiceContainer for dependency injection. If it contains
            'allowed_paths', sandbox validation will be enabled.

    Returns:
        New ListDirectorySkill instance
    """
    allowed_paths: list[Path] | None = services.get("allowed_paths")
    return ListDirectorySkill(allowed_paths=allowed_paths)
