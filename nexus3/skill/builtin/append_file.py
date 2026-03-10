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


def _needs_newline_prefix(filepath: os.PathLike[str]) -> tuple[bool, str]:
    """Check if file needs newline prefix and detect its line ending.

    Returns:
        Tuple of (needs_newline: bool, detected_line_ending: str)
    """
    try:
        size = os.path.getsize(filepath)
        if size == 0:
            return False, "\n"

        # Read last 1KB to detect line ending style
        with open(filepath, "rb") as f:
            read_size = min(1024, size)
            f.seek(max(0, size - read_size))
            tail_bytes = f.read()

            # Detect line ending from tail
            if b"\r\n" in tail_bytes:
                line_ending = '\r\n'
            elif b"\r" in tail_bytes:
                line_ending = '\r'
            else:
                line_ending = '\n'

            needs_prefix = not tail_bytes.endswith((b"\n", b"\r"))
            return needs_prefix, line_ending
    except OSError:
        return False, "\n"


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
            "Append content to the end of a file. "
            "Use for adding new trailing content (logs/changelog entries, footer blocks). "
            "IMPORTANT: Do not use for in-place edits; use edit_file/edit_lines/patch instead."
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
                    "description": (
                        "Add newline before content if file"
                        " doesn't end with one (default: true)"
                    ),
                    "default": True
                }
            },
            "required": ["path", "content"],
            "additionalProperties": False,
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
                if newline and p.exists():
                    needs_nl, line_ending = _needs_newline_prefix(p)
                    if needs_nl:
                        to_write = line_ending + content

                # P2.6 FIX: Use true append mode instead of read+rewrite
                # This is atomic at the OS level and avoids race conditions.
                # Use binary append to preserve exact newline bytes cross-platform.
                with open(p, "ab") as f:
                    f.write(to_write.encode("utf-8"))

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
