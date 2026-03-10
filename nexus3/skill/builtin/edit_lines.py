"""Edit lines skill for line-based file editing."""

import asyncio
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import atomic_write_bytes, detect_line_ending
from nexus3.core.types import ToolResult
from nexus3.skill.argument_normalization import normalize_empty_optional_string
from nexus3.skill.base import FileSkill, file_skill_factory


class EditLinesSkill(FileSkill):
    """Skill that replaces lines by line number.

    For multiple separate calls in the same file, work bottom-to-top to avoid
    line number drift. Batch mode via ``edits`` handles ordering automatically.
    Consider using edit_file for safer string-based edits when possible.

    Inherits path validation from FileSkill.
    """

    @property
    def name(self) -> str:
        return "edit_lines"

    @property
    def description(self) -> str:
        return (
            "Replace one or more lines by line number. "
            "Use when you know exact line ranges for a block/function update. "
            "IMPORTANT: new_content replaces whole lines and must preserve correct indentation. "
            "Batch mode via 'edits' applies original-file line ranges atomically and "
            "automatically avoids line drift. "
            "Use edit_file/regex_replace for text-pattern edits."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to edit"
                },
                "start_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "First line to replace (1-indexed)"
                },
                "end_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Last line to replace (inclusive, defaults to start_line)"
                },
                "new_content": {
                    "type": "string",
                    "description": (
                        "Content to insert (must include proper indentation - "
                        "the entire line is replaced, not just the text)"
                    )
                },
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "start_line": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "First line to replace (1-indexed)",
                            },
                            "end_line": {
                                "type": "integer",
                                "minimum": 1,
                                "description": (
                                    "Last line to replace (inclusive, defaults to start_line)"
                                ),
                            },
                            "new_content": {
                                "type": "string",
                                "description": (
                                    "Content to insert for this range "
                                    "(must include proper indentation)"
                                ),
                            },
                        },
                        "required": ["start_line", "new_content"],
                        "additionalProperties": False,
                    },
                    "description": (
                        "Atomic array of line-range replacements. Line numbers are "
                        "interpreted against the original file and applied "
                        "bottom-to-top automatically. Overlapping ranges fail closed. "
                        "Cannot be used with top-level start_line/end_line/new_content."
                    ),
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        }

    async def execute(
        self,
        path: str = "",
        start_line: int | None = None,
        end_line: int | None = None,
        new_content: str | None = None,
        edits: list[dict[str, Any]] | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Replace lines in the file by line number.

        Args:
            path: File to edit
            start_line: First line to replace (1-indexed)
            end_line: Last line to replace (inclusive, defaults to start_line)
            new_content: Content to insert
            edits: Atomic array of line replacements (batch mode)

        Returns:
            ToolResult with success message or error
        """
        batch_mode = edits is not None

        # Some tool-callers may send empty-string placeholders for omitted
        # single-edit fields in batch mode. Normalize the optional text field
        # centrally instead of checking for one exact ad hoc shape.
        if batch_mode:
            new_content = normalize_empty_optional_string(new_content)

        if batch_mode:
            if start_line is not None or end_line is not None or new_content is not None:
                return ToolResult(
                    error=(
                        "Cannot use 'edits' array with single-edit parameters "
                        "(start_line/end_line/new_content)"
                    )
                )
        else:
            if start_line is None or start_line < 1:
                return ToolResult(error="start_line must be >= 1")
            if new_content is None:
                return ToolResult(error="new_content is required")

        try:
            # Validate path (resolves symlinks, checks allowed_paths if set)
            p = self._validate_path(path)

            # Read current content (binary to preserve line endings)
            try:
                content_bytes = await asyncio.to_thread(p.read_bytes)
                raw_content = content_bytes.decode("utf-8")
                original_line_ending = detect_line_ending(raw_content)
                # Normalize to LF for processing
                content = raw_content.replace('\r\n', '\n').replace('\r', '\n')
            except FileNotFoundError:
                return ToolResult(error=f"File not found: {path}")
            except PermissionError:
                return ToolResult(error=f"Permission denied: {path}")
            except UnicodeDecodeError:
                return ToolResult(
                    error=(
                        f"File is not valid UTF-8 text: {path}. "
                        "Use patch with fidelity_mode='byte_strict' for byte-sensitive edits."
                    )
                )

            if batch_mode:
                batch_result = self._batch_line_replace(
                    content,
                    edits or [],
                    had_trailing_newline=content.endswith("\n"),
                )
                if isinstance(batch_result, ToolResult):
                    return batch_result
                output_content, edit_info = batch_result
            else:
                result = self._line_replace(
                    content,
                    start_line,
                    end_line,
                    new_content,
                    had_trailing_newline=content.endswith("\n"),
                )
                if result.error:
                    return result
                output_content = result.output

            # Convert line endings back to original and write as binary
            if original_line_ending != '\n':
                output_content = output_content.replace('\n', original_line_ending)
            await asyncio.to_thread(atomic_write_bytes, p, output_content.encode('utf-8'))

            if batch_mode:
                summary_lines = [f"Applied {len(edit_info)} line edit(s) to {path}:"]
                for info in edit_info:
                    summary_lines.append(
                        f"- {self._format_line_range(info['start_line'], info['end_line'])}"
                    )
                return ToolResult(output="\n".join(summary_lines))

            actual_end = end_line if end_line is not None else start_line
            if actual_end != start_line:
                return ToolResult(output=f"Replaced lines {start_line}-{actual_end} in {path}")
            return ToolResult(output=f"Replaced line {start_line} in {path}")

        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))
        except Exception as e:
            return ToolResult(error=f"Error editing file: {e}")

    def _line_replace(
        self,
        content: str,
        start_line: int,
        end_line: int | None,
        new_content: str,
        *,
        had_trailing_newline: bool = False,
    ) -> ToolResult:
        """Perform line-based replacement.

        Args:
            content: File content (normalized to LF)
            start_line: First line to replace (1-indexed)
            end_line: Last line to replace (inclusive), None defaults to start_line
            new_content: Content to insert

        Returns:
            ToolResult with new content as output, or error
        """
        lines = content.splitlines(keepends=True)
        total_lines = len(lines)

        if start_line > total_lines:
            return ToolResult(
                error=f"start_line {start_line} exceeds file length ({total_lines} lines)"
            )

        if end_line is None:
            end_line = start_line

        if end_line < start_line:
            return ToolResult(
                error=f"end_line ({end_line}) cannot be less than start_line ({start_line})"
            )

        if end_line > total_lines:
            return ToolResult(
                error=f"end_line {end_line} exceeds file length ({total_lines} lines)"
            )

        # Convert to 0-indexed
        start_idx = start_line - 1
        end_idx = end_line  # exclusive, so end_line is correct for slicing

        # Ensure new_content ends with newline if we're not at end of file
        if (
            new_content
            and not new_content.endswith("\n")
            and (end_idx < total_lines or had_trailing_newline)
        ):
            new_content += "\n"

        # Build new content
        new_lines = lines[:start_idx] + [new_content] + lines[end_idx:]
        result = "".join(new_lines)

        return ToolResult(output=result)

    def _batch_line_replace(
        self,
        content: str,
        edits: list[dict[str, Any]],
        *,
        had_trailing_newline: bool = False,
    ) -> tuple[str, list[dict[str, Any]]] | ToolResult:
        """Apply multiple line-based replacements atomically.

        Batch edit line numbers are interpreted against the original file. Edits
        are validated first, then applied bottom-to-top to avoid line drift.
        Overlapping ranges are rejected.
        """
        if not edits:
            return ToolResult(error="edits array cannot be empty")

        lines = content.splitlines(keepends=True)
        total_lines = len(lines)
        edit_info: list[dict[str, Any]] = []

        for i, edit in enumerate(edits, 1):
            start = edit.get("start_line")
            end = edit.get("end_line")
            replacement = edit.get("new_content", "")

            if start is None or not isinstance(start, int) or start < 1:
                return ToolResult(
                    error=(
                        "Batch edit failed (no changes made):\n"
                        f"  Edit {i}: start_line must be >= 1"
                    )
                )

            if end is not None and (not isinstance(end, int) or end < 1):
                return ToolResult(
                    error=(
                        "Batch edit failed (no changes made):\n"
                        f"  Edit {i}: end_line must be >= 1"
                    )
                )

            actual_end = end if end is not None else start

            if actual_end < start:
                return ToolResult(
                    error=(
                        "Batch edit failed (no changes made):\n"
                        f"  Edit {i}: end_line ({actual_end}) cannot be less than "
                        f"start_line ({start})"
                    )
                )

            if start > total_lines:
                return ToolResult(
                    error=(
                        "Batch edit failed (no changes made):\n"
                        f"  Edit {i}: start_line {start} exceeds file length "
                        f"({total_lines} lines)"
                    )
                )

            if actual_end > total_lines:
                return ToolResult(
                    error=(
                        "Batch edit failed (no changes made):\n"
                        f"  Edit {i}: end_line {actual_end} exceeds file length "
                        f"({total_lines} lines)"
                    )
                )

            edit_info.append(
                {
                    "index": i,
                    "start_line": start,
                    "end_line": actual_end,
                    "new_content": replacement,
                }
            )

        sorted_by_start = sorted(
            edit_info,
            key=lambda info: (info["start_line"], info["end_line"]),
        )
        for previous, current in zip(sorted_by_start, sorted_by_start[1:], strict=False):
            if current["start_line"] <= previous["end_line"]:
                prev_range = self._format_line_range(
                    previous["start_line"], previous["end_line"]
                )
                current_range = self._format_line_range(
                    current["start_line"], current["end_line"]
                )
                return ToolResult(
                    error=(
                        "Batch edit failed (no changes made):\n"
                        f"  Edit {current['index']} ({current_range}) overlaps "
                        f"Edit {previous['index']} ({prev_range}). Merge overlapping "
                        "ranges or split them into separate non-overlapping edits."
                    )
                )

        updated_lines = lines[:]
        for info in sorted(edit_info, key=lambda entry: entry["start_line"], reverse=True):
            replacement = info["new_content"]
            if (
                replacement
                and not replacement.endswith("\n")
                and (info["end_line"] < total_lines or had_trailing_newline)
            ):
                replacement += "\n"

            start_idx = info["start_line"] - 1
            end_idx = info["end_line"]
            updated_lines = updated_lines[:start_idx] + [replacement] + updated_lines[end_idx:]

        return "".join(updated_lines), edit_info

    def _format_line_range(self, start_line: int, end_line: int) -> str:
        """Format a line range for user-facing messages."""
        if start_line == end_line:
            return f"line {start_line}"
        return f"lines {start_line}-{end_line}"

# Factory for dependency injection
edit_lines_factory = file_skill_factory(EditLinesSkill)
