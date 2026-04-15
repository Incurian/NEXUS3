"""Read file skill for reading file contents.

P2.5 SECURITY: Implements streaming reads with size limits to prevent memory DoS.
"""

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from nexus3.core.constants import MAX_FILE_SIZE_BYTES, MAX_OUTPUT_BYTES, MAX_READ_LINES
from nexus3.core.errors import PathSecurityError
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory


@dataclass(frozen=True)
class _ReadWindow:
    """Metadata for a streamed read_file window."""

    lines: list[str]
    truncated: bool
    last_line_number: int | None
    next_offset: int | None
    truncation_reason: Literal["line_limit", "byte_limit"] | None


def _stream_read_lines(
    filepath: Path,
    offset: int = 1,
    limit: int | None = None,
    max_bytes: int = MAX_OUTPUT_BYTES,
    line_numbers: bool = True,
) -> _ReadWindow:
    """Stream-read lines from a file with limits.

    P2.5 SECURITY: Reads line-by-line to avoid loading entire file into memory.

    Args:
        filepath: Path to the file
        offset: 1-indexed line number to start from
        limit: Maximum lines to read (None = use MAX_READ_LINES)
        max_bytes: Maximum total bytes to read
        line_numbers: Whether to prefix each line with its original line number

    Returns:
        Read window details, including continuation metadata when truncated.
    """
    effective_limit = limit if limit is not None else MAX_READ_LINES
    lines: list[str] = []
    total_bytes = 0
    line_num = 0
    truncated = False
    last_line_number: int | None = None
    next_offset: int | None = None
    truncation_reason: Literal["line_limit", "byte_limit"] | None = None
    start_idx = offset - 1  # Convert to 0-indexed

    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line_num += 1

            # Skip lines before offset
            if line_num <= start_idx:
                continue

            line_text = line.removesuffix("\n")
            rendered_line = f"{line_num}: {line_text}" if line_numbers else line_text
            if line.endswith("\n"):
                rendered_line += "\n"

            # Check byte limit against the actual rendered output
            line_bytes = len(rendered_line.encode("utf-8"))
            if total_bytes + line_bytes > max_bytes:
                truncated = True
                next_offset = line_num
                truncation_reason = "byte_limit"
                break

            lines.append(rendered_line)
            total_bytes += line_bytes
            last_line_number = line_num

            # Check line limit
            if len(lines) >= effective_limit:
                peek = f.readline()
                if peek:
                    truncated = True
                    next_offset = line_num + 1
                    truncation_reason = "line_limit"
                break

    return _ReadWindow(
        lines=lines,
        truncated=truncated,
        last_line_number=last_line_number,
        next_offset=next_offset,
        truncation_reason=truncation_reason,
    )


def _resolve_line_window(
    offset: int | None,
    limit: int | None,
    start_line: int | None,
    end_line: int | None,
) -> tuple[int, int | None]:
    """Normalize offset/limit and start_line/end_line aliases.

    `offset`/`limit` remain the canonical paging contract. `start_line` and
    `end_line` are compatibility aliases for cross-tool consistency.
    """
    if offset is not None and start_line is not None and offset != start_line:
        raise ValueError(
            "read_file offset and start_line must match when both are provided"
        )

    effective_offset = start_line if start_line is not None else offset
    if effective_offset is None:
        effective_offset = 1

    if end_line is not None and end_line < effective_offset:
        raise ValueError("read_file end_line must be >= start_line/offset")

    alias_limit = None
    if end_line is not None:
        alias_limit = end_line - effective_offset + 1

    if limit is not None and alias_limit is not None and limit != alias_limit:
        raise ValueError(
            "read_file limit and end_line must describe the same line window"
        )

    effective_limit = alias_limit if alias_limit is not None else limit
    return effective_offset, effective_limit


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
        return (
            "Read UTF-8 file contents with optional offset/limit paging. "
            "Use offset and limit as the canonical line-window parameters."
        )

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
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read (default: 10000)"
                },
                "line_numbers": {
                    "type": "boolean",
                    "description": (
                        "Prefix each returned line with its original line number. "
                        "Default: true"
                    ),
                    "default": True,
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        }

    async def execute(
        self,
        path: str = "",
        offset: int | None = None,
        limit: int | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
        line_numbers: bool = True,
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

            effective_offset, effective_limit = _resolve_line_window(
                offset,
                limit,
                start_line,
                end_line,
            )

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
            window = await asyncio.to_thread(
                _stream_read_lines,
                p,
                effective_offset,
                effective_limit,
                MAX_OUTPUT_BYTES,
                line_numbers,
            )

            if not window.lines:
                if window.truncated and window.truncation_reason == "byte_limit":
                    return ToolResult(
                        output=(
                            f"(Unable to return line {effective_offset}: the rendered output "
                            "for that line exceeds the read_file output limit. "
                            "Retry with a later offset or use a narrower read.)"
                        )
                    )
                return ToolResult(
                    output=f"(File is empty or offset {effective_offset}"
                    " is beyond end of file)"
                )

            content = "".join(window.lines)
            if window.truncated and window.last_line_number is not None:
                line_window = f"{effective_offset}-{window.last_line_number}"
                if (
                    window.truncation_reason == "byte_limit"
                    and window.next_offset is not None
                ):
                    content += (
                        "\n"
                        f"[read_file returned lines {line_window}; output limit reached "
                        f"before line {window.next_offset}; continue with offset="
                        f"{window.next_offset}]"
                    )
                elif window.next_offset is not None:
                    content += (
                        "\n"
                        f"[read_file returned lines {line_window}; more content remains; "
                        f"continue with offset={window.next_offset}]"
                    )
                else:
                    content += f"\n[read_file returned lines {line_window}; more content remains]"

            return ToolResult(output=content)

        except UnicodeDecodeError:
            return ToolResult(error=f"File is not valid UTF-8 text: {path}")
        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))
        except FileNotFoundError:
            return ToolResult(error=f"File not found: {path}")
        except PermissionError:
            return ToolResult(error=f"Permission denied: {path}")
        except IsADirectoryError:
            return ToolResult(error=f"Path is a directory, not a file: {path}")
        except Exception as e:
            return ToolResult(error=f"Error reading file: {e}")


# Factory for dependency injection
read_file_factory = file_skill_factory(ReadFileSkill)
