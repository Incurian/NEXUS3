"""Tail skill for reading last N lines of a file.

P2.5 SECURITY: Implements efficient tail reading with size limits.
"""

import asyncio
import os
from collections import deque
from pathlib import Path
from typing import Any

from nexus3.core.constants import MAX_FILE_SIZE_BYTES, MAX_OUTPUT_BYTES
from nexus3.core.errors import PathSecurityError
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory


def _tail_lines(
    filepath: Path,
    num_lines: int,
    max_bytes: int = MAX_OUTPUT_BYTES,
) -> tuple[list[tuple[int, str]], int, bool]:
    """Read last N lines from a file efficiently.

    P2.5 SECURITY: Uses a deque to only keep last N lines in memory,
    avoiding loading entire file.

    Args:
        filepath: Path to the file
        num_lines: Number of lines from end
        max_bytes: Maximum total bytes to return

    Returns:
        Tuple of (list of (line_num, line_content), total_lines, was_truncated)
    """
    # Use deque to efficiently keep only last N lines
    line_buffer: deque[tuple[int, str]] = deque(maxlen=num_lines)
    total_lines = 0

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            total_lines += 1
            line_buffer.append((total_lines, line.rstrip()))

    # Check if output would exceed max_bytes
    result = list(line_buffer)
    total_bytes = sum(len(line.encode("utf-8")) + 10 for _, line in result)  # +10 for line number prefix

    truncated = False
    if total_bytes > max_bytes:
        # Trim from start until under limit
        while result and total_bytes > max_bytes:
            removed = result.pop(0)
            total_bytes -= len(removed[1].encode("utf-8")) + 10
            truncated = True

    return result, total_lines, truncated


class TailSkill(FileSkill):
    """Skill that reads the last N lines of a file.

    More intuitive than negative offsets for common use cases like
    reading log files or recent output.

    P2.5 SECURITY: Uses efficient tail reading that doesn't load entire file.
    - Files larger than MAX_FILE_SIZE_BYTES are still accepted (tail is safe)
    - Output is capped at MAX_OUTPUT_BYTES

    Inherits path validation from FileSkill.
    """

    @property
    def name(self) -> str:
        return "tail"

    @property
    def description(self) -> str:
        return "Read the last N lines of a file"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the file to read"
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of lines from end (default: 10)",
                    "default": 10
                }
            },
            "required": ["path"]
        }

    async def execute(
        self,
        path: str = "",
        lines: int = 10,
        **kwargs: Any
    ) -> ToolResult:
        """Read the last N lines of the file.

        Args:
            path: The path to the file to read
            lines: Number of lines from end (default: 10)

        Returns:
            ToolResult with file contents in output, or error message in error
        """
        if not path:
            return ToolResult(error="No path provided")

        if lines < 1:
            return ToolResult(error="Lines must be at least 1")

        try:
            # Validate path (resolves symlinks, checks allowed_paths if set)
            p = self._validate_path(path)

            # P2.5 SECURITY: Efficient tail read (deque keeps only last N lines)
            result, total_lines, truncated = await asyncio.to_thread(
                _tail_lines, p, lines
            )

            if not result:
                return ToolResult(output="(File is empty)")

            # Format with line numbers
            numbered = [f"{line_num}: {content}\n" for line_num, content in result]
            output = "".join(numbered)

            if truncated:
                output += f"\n[... output truncated to fit size limit ...]"

            return ToolResult(output=output)

        except (PathSecurityError, ValueError) as e:
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


# Factory for dependency injection
tail_factory = file_skill_factory(TailSkill)
