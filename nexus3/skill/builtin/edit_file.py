"""Edit file skill for making targeted edits to files."""

import asyncio
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory


class EditFileSkill(FileSkill):
    """Skill that makes targeted edits to files.

    Supports two modes:
    1. String replacement: Find and replace text (old_string -> new_string)
    2. Line-based: Replace lines by line number range

    String replacement is preferred as it's safer for multiple edits.
    Line-based edits should be done bottom-to-top to avoid line drift.

    Inherits path validation from FileSkill.
    """

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            "Edit a file using string replacement or line-based editing. "
            "IMPORTANT: Read the file first to verify your old_string matches exactly."
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
                # String replacement mode
                "old_string": {
                    "type": "string",
                    "description": "Text to find and replace (must be unique in file unless replace_all=true)"
                },
                "new_string": {
                    "type": "string",
                    "description": "Replacement text"
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences (default: false, requires unique match)",
                    "default": False
                },
                # Line-based mode
                "start_line": {
                    "type": "integer",
                    "description": "First line to replace (1-indexed, for line-based mode)"
                },
                "end_line": {
                    "type": "integer",
                    "description": "Last line to replace (inclusive, defaults to start_line)"
                },
                "new_content": {
                    "type": "string",
                    "description": "Content to insert (for line-based mode)"
                }
            },
            "required": ["path"]
        }

    async def execute(
        self,
        path: str = "",
        old_string: str | None = None,
        new_string: str | None = None,
        replace_all: bool = False,
        start_line: int | None = None,
        end_line: int | None = None,
        new_content: str | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Edit the file using specified mode.

        Args:
            path: File to edit
            old_string: Text to find (string mode)
            new_string: Replacement text (string mode)
            replace_all: Replace all occurrences (string mode)
            start_line: First line to replace (line mode)
            end_line: Last line to replace (line mode)
            new_content: Replacement content (line mode)

        Returns:
            ToolResult with success message or error
        """
        # Note: 'path' required by schema
        # Determine which mode to use
        string_mode = old_string is not None
        line_mode = start_line is not None

        if string_mode and line_mode:
            return ToolResult(error="Cannot use both string replacement and line-based mode")

        if not string_mode and not line_mode:
            return ToolResult(error="Must provide either old_string (string mode) or start_line (line mode)")

        try:
            # Validate path (resolves symlinks, checks allowed_paths if set)
            p = self._validate_path(path)

            # Read current content
            try:
                content = await asyncio.to_thread(p.read_text, encoding="utf-8")
            except FileNotFoundError:
                return ToolResult(error=f"File not found: {path}")
            except PermissionError:
                return ToolResult(error=f"Permission denied: {path}")

            if string_mode:
                result = self._string_replace(content, old_string, new_string or "", replace_all)
            else:
                result = self._line_replace(content, start_line, end_line, new_content or "")

            if result.error:
                return result

            # Write updated content
            await asyncio.to_thread(p.write_text, result.output, encoding="utf-8")

            # Return success message (not the content)
            if string_mode:
                if replace_all:
                    count = content.count(old_string)
                    return ToolResult(output=f"Replaced {count} occurrence(s) in {path}")
                else:
                    return ToolResult(output=f"Replaced text in {path}")
            else:
                if end_line and end_line != start_line:
                    return ToolResult(output=f"Replaced lines {start_line}-{end_line} in {path}")
                else:
                    return ToolResult(output=f"Replaced line {start_line} in {path}")

        except PathSecurityError as e:
            return ToolResult(error=str(e))
        except Exception as e:
            return ToolResult(error=f"Error editing file: {e}")

    def _string_replace(
        self,
        content: str,
        old_string: str | None,
        new_string: str,
        replace_all: bool
    ) -> ToolResult:
        """Perform string-based replacement."""
        if not old_string:
            return ToolResult(error="old_string cannot be empty")

        count = content.count(old_string)

        if count == 0:
            return ToolResult(error=f"String not found in file: {old_string[:100]}...")

        if not replace_all and count > 1:
            return ToolResult(
                error=f"String appears {count} times. Use replace_all=true or provide more context for unique match."
            )

        if replace_all:
            new_content = content.replace(old_string, new_string)
        else:
            new_content = content.replace(old_string, new_string, 1)

        return ToolResult(output=new_content)

    def _line_replace(
        self,
        content: str,
        start_line: int | None,
        end_line: int | None,
        new_content: str
    ) -> ToolResult:
        """Perform line-based replacement."""
        if start_line is None or start_line < 1:
            return ToolResult(error="start_line must be >= 1")

        lines = content.splitlines(keepends=True)
        total_lines = len(lines)

        # Handle files that don't end with newline
        if content and not content.endswith("\n"):
            # Last line doesn't have a newline
            pass

        if start_line > total_lines:
            return ToolResult(error=f"start_line {start_line} exceeds file length ({total_lines} lines)")

        if end_line is None:
            end_line = start_line

        if end_line < start_line:
            return ToolResult(error=f"end_line ({end_line}) cannot be less than start_line ({start_line})")

        if end_line > total_lines:
            return ToolResult(error=f"end_line {end_line} exceeds file length ({total_lines} lines)")

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
edit_file_factory = file_skill_factory(EditFileSkill)
