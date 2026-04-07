"""Line-based file editing skills."""

import asyncio
from pathlib import Path
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import atomic_write_bytes, detect_line_ending
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory


class _LineEditSkill(FileSkill):
    """Shared helpers for line-based UTF-8 file editing skills."""

    async def _load_text_file(self, path: str) -> tuple[Path, str, str]:
        """Load a UTF-8 text file and normalize line endings for processing."""
        p = self._validate_path(path)

        try:
            content_bytes = await asyncio.to_thread(p.read_bytes)
            raw_content = content_bytes.decode("utf-8")
        except FileNotFoundError as exc:
            raise FileNotFoundError(path) from exc
        except PermissionError as exc:
            raise PermissionError(path) from exc
        except UnicodeDecodeError as exc:
            raise UnicodeDecodeError(
                exc.encoding,
                exc.object,
                exc.start,
                exc.end,
                exc.reason,
            ) from exc

        original_line_ending = detect_line_ending(raw_content)
        content = raw_content.replace("\r\n", "\n").replace("\r", "\n")
        return p, content, original_line_ending

    async def _write_text_file(
        self,
        path: Path,
        content: str,
        original_line_ending: str,
    ) -> None:
        """Persist content while preserving the file's original line endings."""
        output_content = content
        if original_line_ending != "\n":
            output_content = output_content.replace("\n", original_line_ending)
        await asyncio.to_thread(atomic_write_bytes, path, output_content.encode("utf-8"))

    def _line_replace(
        self,
        content: str,
        start_line: int,
        end_line: int | None,
        new_content: str,
        *,
        had_trailing_newline: bool = False,
    ) -> ToolResult:
        """Replace one line range in normalized LF content."""
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

        start_idx = start_line - 1
        end_idx = end_line

        if (
            new_content
            and not new_content.endswith("\n")
            and (end_idx < total_lines or had_trailing_newline)
        ):
            new_content += "\n"

        new_lines = lines[:start_idx] + [new_content] + lines[end_idx:]
        return ToolResult(output="".join(new_lines))

    def _batch_line_replace(
        self,
        content: str,
        edits: list[dict[str, Any]],
        *,
        had_trailing_newline: bool = False,
    ) -> tuple[str, list[dict[str, Any]]] | ToolResult:
        """Apply multiple line-based replacements atomically."""
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


class EditLinesSkill(_LineEditSkill):
    """Replace one line range by explicit line numbers."""

    @property
    def name(self) -> str:
        return "edit_lines"

    @property
    def description(self) -> str:
        return (
            "Replace one line range in a UTF-8 file by explicit line numbers. "
            "Required: path, start_line, new_content. "
            "Use when you know the exact line range for one block/function update. "
            "new_content replaces whole lines and must preserve correct indentation. "
            "For multiple line-range edits use edit_lines_batch. "
            "Use edit_file, edit_file_batch, or regex_replace for text-pattern edits."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the UTF-8 text file to edit",
                },
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
                        "Replacement content for the selected line range. "
                        "Must include correct indentation."
                    ),
                },
            },
            "required": ["path", "start_line", "new_content"],
            "additionalProperties": False,
        }

    async def execute(
        self,
        path: str = "",
        start_line: int | None = None,
        end_line: int | None = None,
        new_content: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Replace one explicit line range in a file."""
        if start_line is None or start_line < 1:
            return ToolResult(error="start_line must be >= 1")
        if new_content is None:
            return ToolResult(error="new_content is required")

        try:
            p, content, original_line_ending = await self._load_text_file(path)
            result = self._line_replace(
                content,
                start_line,
                end_line,
                new_content,
                had_trailing_newline=content.endswith("\n"),
            )
            if result.error:
                return result

            await self._write_text_file(p, result.output, original_line_ending)

            actual_end = end_line if end_line is not None else start_line
            if actual_end != start_line:
                return ToolResult(output=f"Replaced lines {start_line}-{actual_end} in {path}")
            return ToolResult(output=f"Replaced line {start_line} in {path}")
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
        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))
        except Exception as e:
            return ToolResult(error=f"Error editing file: {e}")


class EditLinesBatchSkill(_LineEditSkill):
    """Apply multiple line-range replacements atomically."""

    @property
    def name(self) -> str:
        return "edit_lines_batch"

    @property
    def description(self) -> str:
        return (
            "Apply multiple line-range replacements atomically in one UTF-8 file. "
            "Required: path and edits=[{start_line, end_line?, new_content}, ...]. "
            "Line numbers are interpreted against the original file and applied "
            "bottom-to-top automatically to avoid line drift. "
            "Overlapping ranges fail closed."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the UTF-8 text file to edit",
                },
                "edits": {
                    "type": "array",
                    "minItems": 1,
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
                                    "Replacement content for this range. "
                                    "Must include correct indentation."
                                ),
                            },
                        },
                        "required": ["start_line", "new_content"],
                        "additionalProperties": False,
                    },
                    "description": (
                        "Atomic array of line-range replacements. All ranges use "
                        "original-file line numbers and are applied bottom-to-top."
                    ),
                },
            },
            "required": ["path", "edits"],
            "additionalProperties": False,
        }

    async def execute(
        self,
        path: str = "",
        edits: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Apply an atomic batch of line-range replacements."""
        try:
            p, content, original_line_ending = await self._load_text_file(path)
            batch_result = self._batch_line_replace(
                content,
                edits or [],
                had_trailing_newline=content.endswith("\n"),
            )
            if isinstance(batch_result, ToolResult):
                return batch_result

            output_content, edit_info = batch_result
            await self._write_text_file(p, output_content, original_line_ending)

            summary_lines = [f"Applied {len(edit_info)} line edit(s) to {path}:"]
            for info in edit_info:
                summary_lines.append(
                    f"- {self._format_line_range(info['start_line'], info['end_line'])}"
                )
            return ToolResult(output="\n".join(summary_lines))
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
        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))
        except Exception as e:
            return ToolResult(error=f"Error editing file: {e}")


edit_lines_factory = file_skill_factory(EditLinesSkill)
edit_lines_batch_factory = file_skill_factory(EditLinesBatchSkill)
