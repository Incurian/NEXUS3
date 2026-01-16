"""Append file skill for appending content to files.

P2.6 SECURITY: Uses true append mode (O_APPEND) to avoid race conditions.
Previous implementation read entire file, concatenated, and rewrote - which
had a TOCTOU race window where concurrent modifications could be lost.
"""

import asyncio
import os
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory


def _needs_newline_prefix(filepath: os.PathLike[str]) -> bool:
    """Check if file exists and doesn't end with newline.

    Only reads the last byte (or few bytes for UTF-8 edge cases) to be efficient.

    Returns:
        True if a newline should be prepended before appending.
    """
    try:
        size = os.path.getsize(filepath)
        if size == 0:
            return False  # Empty file - no newline needed

        # Read just the last few bytes to check for newline
        # (UTF-8 newline is single byte, but be safe)
        with open(filepath, "rb") as f:
            f.seek(max(0, size - 4))
            tail = f.read()
            return not tail.endswith(b"\n")
    except (OSError, IOError):
        return False  # Can't read - will be handled by append


class AppendFileSkill(FileSkill):
    """Skill that appends content to a file.

    P2.6 SECURITY: Uses true append mode (open with 'a') which is atomic at
    the OS level and avoids race conditions from read+concat+write.

    Inherits path validation from FileSkill.
    """

    @property
    def name(self) -> str:
        return "append_file"

    @property
    def description(self) -> str:
        return (
            "Append content to a file. "
            "IMPORTANT: Read the file first to understand its current content and structure."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the file to append to"
                },
                "content": {
                    "type": "string",
                    "description": "Content to append"
                },
                "newline": {
                    "type": "boolean",
                    "description": "Add newline before content if file doesn't end with one (default: true)",
                    "default": True
                }
            },
            "required": ["path", "content"]
        }

    async def execute(
        self,
        path: str = "",
        content: str = "",
        newline: bool = True,
        **kwargs: Any
    ) -> ToolResult:
        """Append content to file using true append mode.

        P2.6 SECURITY: Uses OS-level append mode to avoid race conditions.
        The previous implementation that read/concatenated/wrote had a TOCTOU
        window where concurrent modifications could be lost.

        Args:
            path: The path to the file to append to
            content: Content to append
            newline: Add newline before content if file doesn't end with one

        Returns:
            ToolResult with success message or error
        """
        if not path:
            return ToolResult(error="No path provided")

        if not content:
            return ToolResult(error="No content provided")

        try:
            # Validate path (resolves symlinks, checks allowed_paths if set)
            p = self._validate_path(path)

            def do_append() -> int:
                # Smart newline handling - only read last byte, not entire file
                to_write = content
                if newline and p.exists() and _needs_newline_prefix(p):
                    to_write = "\n" + content

                # P2.6 FIX: Use true append mode instead of read+rewrite
                # This is atomic at the OS level and avoids race conditions
                with open(p, "a", encoding="utf-8") as f:
                    f.write(to_write)

                return len(to_write)

            chars_written = await asyncio.to_thread(do_append)
            return ToolResult(output=f"Appended {chars_written} characters to {path}")

        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))
        except PermissionError:
            return ToolResult(error=f"Permission denied: {path}")
        except IsADirectoryError:
            return ToolResult(error=f"Path is a directory, not a file: {path}")
        except Exception as e:
            return ToolResult(error=f"Error appending to file: {e}")


# Factory for dependency injection
append_file_factory = file_skill_factory(AppendFileSkill)
