"""Edit lines skill for line-based file editing."""

import asyncio
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import atomic_write_bytes, detect_line_ending
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory


class EditLinesSkill(FileSkill):
    """Skill that replaces lines by line number.

    For multiple edits in the same file, work bottom-to-top to avoid
    line number drift. Consider using edit_file for safer string-based
    edits when possible.

    Inherits path validation from FileSkill.
    """

    @property
    def name(self) -> str:
        return "edit_lines"

    @property
    def description(self) -> str:
        return (
            "Replace lines by line number. "
            "IMPORTANT: new_content must include proper indentation - the entire line is replaced. "
            "For Python, match the original indentation (spaces/tabs) exactly. "
            "For multiple edits, work bottom-to-top to avoid line number drift. "
            "Use edit_file for safer string-based edits that preserve context."
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
                    "description": "First line to replace (1-indexed)"
                },
                "end_line": {
                    "type": "integer",
                    "description": "Last line to replace (inclusive, defaults to start_line)"
                },
                "new_content": {
                    "type": "string",
                    "description": (
                        "Content to insert (must include proper indentation - "
                        "the entire line is replaced, not just the text)"
                    )
                }
            },
            "required": ["path", "start_line", "new_content"]
        }

    async def execute(
        self,
        path: str = "",
        start_line: int | None = None,
        end_line: int | None = None,
        new_content: str = "",
        **kwargs: Any
    ) -> ToolResult:
        """Replace lines in the file by line number.

        Args:
            path: File to edit
            start_line: First line to replace (1-indexed)
            end_line: Last line to replace (inclusive, defaults to start_line)
            new_content: Content to insert

        Returns:
            ToolResult with success message or error
        """
        # Validate start_line
        if start_line is None or start_line < 1:
            return ToolResult(error="start_line must be >= 1")

        try:
            # Validate path (resolves symlinks, checks allowed_paths if set)
            p = self._validate_path(path)

            # Read current content (binary to preserve line endings)
            try:
                content_bytes = await asyncio.to_thread(p.read_bytes)
                raw_content = content_bytes.decode("utf-8", errors="replace")
                original_line_ending = detect_line_ending(raw_content)
                # Normalize to LF for processing
                content = raw_content.replace('\r\n', '\n').replace('\r', '\n')
            except FileNotFoundError:
                return ToolResult(error=f"File not found: {path}")
            except PermissionError:
                return ToolResult(error=f"Permission denied: {path}")

            # Perform the line replacement
            result = self._line_replace(content, start_line, end_line, new_content)

            if result.error:
                return result

            # Convert line endings back to original and write as binary
            output_content = result.output
            if original_line_ending != '\n':
                output_content = output_content.replace('\n', original_line_ending)
            await asyncio.to_thread(atomic_write_bytes, p, output_content.encode('utf-8'))

            # Return success message
            actual_end = end_line if end_line is not None else start_line
            if actual_end != start_line:
                return ToolResult(output=f"Replaced lines {start_line}-{actual_end} in {path}")
            else:
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
        new_content: str
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
        if new_content and not new_content.endswith("\n") and end_idx < total_lines:
            new_content += "\n"

        # Build new content
        new_lines = lines[:start_idx] + [new_content] + lines[end_idx:]
        result = "".join(new_lines)

        return ToolResult(output=result)


# Factory for dependency injection
edit_lines_factory = file_skill_factory(EditLinesSkill)
