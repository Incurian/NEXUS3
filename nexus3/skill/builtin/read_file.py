"""Read file skill for reading file contents.

P2.5 SECURITY: Implements streaming reads with size limits to prevent memory DoS.
"""

import asyncio
import os
from pathlib import Path
from typing import Any

from nexus3.core.constants import MAX_FILE_SIZE_BYTES, MAX_OUTPUT_BYTES, MAX_READ_LINES
from nexus3.core.errors import PathSecurityError
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory


def _stream_read_lines(
    filepath: Path,
    offset: int = 1,
    limit: int | None = None,
    max_bytes: int = MAX_OUTPUT_BYTES,
) -> tuple[list[str], bool]:
    """Stream-read lines from a file with limits.

    P2.5 SECURITY: Reads line-by-line to avoid loading entire file into memory.

    Args:
        filepath: Path to the file
        offset: 1-indexed line number to start from
        limit: Maximum lines to read (None = use MAX_READ_LINES)
        max_bytes: Maximum total bytes to read

    Returns:
        Tuple of (lines with line numbers, was_truncated)
    """
    effective_limit = limit if limit is not None else MAX_READ_LINES
    lines: list[str] = []
    total_bytes = 0
    line_num = 0
    truncated = False
    start_idx = offset - 1  # Convert to 0-indexed

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line_num += 1

            # Skip lines before offset
            if line_num <= start_idx:
                continue

            # Check byte limit
            line_bytes = len(line.encode("utf-8"))
            if total_bytes + line_bytes > max_bytes:
                truncated = True
                break

            # Add line with number
            lines.append(f"{line_num}: {line.rstrip()}\n")
            total_bytes += line_bytes

            # Check line limit
            if len(lines) >= effective_limit:
                truncated = True
                break

    return lines, truncated


class ReadFileSkill(FileSkill):
    """Skill that reads the contents of a file.

    Returns the file contents as text, or an error if the file
    cannot be read.

    P2.5 SECURITY: Uses streaming reads with size limits to prevent memory DoS.
    - Files larger than MAX_FILE_SIZE_BYTES are rejected
    - Output is capped at MAX_OUTPUT_BYTES
    - Lines are capped at MAX_READ_LINES if no limit specified

    Inherits path validation from FileSkill.
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
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (1-indexed, default: 1)",
                    "minimum": 1,
                    "default": 1
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read (default: 10000)"
                }
            },
            "required": ["path"]
        }

    async def execute(
        self,
        path: str = "",
        offset: int = 1,
        limit: int | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Read the file and return its contents.

        Args:
            path: The path to the file to read
            offset: Line number to start reading from (1-indexed, default: 1)
            limit: Maximum number of lines to read (default: 10000)

        Returns:
            ToolResult with file contents in output, or error message in error
        """
        # Note: 'path' required by schema, 'offset' minimum:1 enforced by schema
        try:
            # Validate path (resolves symlinks, checks allowed_paths if set)
            p = self._validate_path(path)

            # P2.5 SECURITY: Check file size before reading
            file_size = await asyncio.to_thread(os.path.getsize, p)
            if file_size > MAX_FILE_SIZE_BYTES:
                size_mb = file_size / (1024 * 1024)
                max_mb = MAX_FILE_SIZE_BYTES / (1024 * 1024)
                return ToolResult(
                    error=f"File too large: {size_mb:.1f}MB (max: {max_mb:.0f}MB). "
                    f"Use 'tail' for last lines or specify offset/limit."
                )

            # P2.5 SECURITY: Stream-read with limits
            lines, truncated = await asyncio.to_thread(
                _stream_read_lines, p, offset, limit
            )

            if not lines:
                return ToolResult(output=f"(File is empty or offset {offset} is beyond end of file)")

            content = "".join(lines)
            if truncated:
                content += f"\n[... truncated at {len(lines)} lines / {len(content)} bytes ...]"

            return ToolResult(output=content)

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
read_file_factory = file_skill_factory(ReadFileSkill)
