"""Edit file skill for making targeted edits to files."""

import asyncio
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import atomic_write_bytes, detect_line_ending
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory


class EditFileSkill(FileSkill):
    """Skill that makes targeted edits to files using string replacement.

    Finds and replaces text in files. The old_string must be unique in the
    file unless replace_all=true. This is safer than line-based editing
    because it doesn't depend on line numbers.

    Supports batched edits via the `edits` parameter for multiple string
    replacements in a single atomic operation.

    For line-based editing, use the edit_lines skill instead.

    Inherits path validation from FileSkill.
    """

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            "Edit a file using string replacement. "
            "IMPORTANT: Read the file first to verify your old_string matches exactly. "
            "For line-based editing, use edit_lines instead. "
            "For multiple edits, use the 'edits' array parameter for atomic batch operations."
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
                "old_string": {
                    "type": "string",
                    "description": (
                        "Text to find and replace "
                        "(must be unique in file unless replace_all=true)"
                    )
                },
                "new_string": {
                    "type": "string",
                    "description": "Replacement text"
                },
                "replace_all": {
                    "type": "boolean",
                    "description": (
                        "Replace all occurrences (default: false, requires unique match)"
                    ),
                    "default": False
                },
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "old_string": {
                                "type": "string",
                                "description": "Text to find"
                            },
                            "new_string": {
                                "type": "string",
                                "description": "Replacement text"
                            },
                            "replace_all": {
                                "type": "boolean",
                                "default": False,
                                "description": "Replace all occurrences"
                            }
                        },
                        "required": ["old_string", "new_string"]
                    },
                    "description": (
                        "Array of string replacements (atomic - all or none). "
                        "Cannot be used with old_string/new_string."
                    )
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
        edits: list[dict[str, Any]] | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Edit the file using string replacement.

        Args:
            path: File to edit
            old_string: Text to find (single edit mode)
            new_string: Replacement text (single edit mode)
            replace_all: Replace all occurrences (single edit mode)
            edits: Array of string replacements (batch mode)

        Returns:
            ToolResult with success message or error
        """
        # Detect batch mode
        batch_mode = edits is not None and len(edits) > 0

        if batch_mode:
            # Cannot mix with single-edit params
            if old_string is not None or new_string is not None:
                return ToolResult(
                    error="Cannot use 'edits' array with single-edit parameters "
                    "(old_string/new_string)"
                )
        else:
            # Single edit mode requires old_string
            if old_string is None:
                return ToolResult(error="old_string is required")

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

            if batch_mode:
                # Batch edit mode
                result = self._batch_replace(content, edits)  # type: ignore[arg-type]
            else:
                # Single edit mode
                result = self._string_replace(
                    content, old_string, new_string or "", replace_all
                )

            if result.error:
                return result

            # Convert line endings back to original and write as binary
            # For batch mode, result.output is the new content
            # For single mode with success message, we need to get the actual content
            if batch_mode:
                output_content = result._new_content  # type: ignore[attr-defined]
            else:
                output_content = result.output

            if original_line_ending != '\n':
                output_content = output_content.replace('\n', original_line_ending)
            await asyncio.to_thread(atomic_write_bytes, p, output_content.encode('utf-8'))

            # For batch mode, result.output already has the success message
            if batch_mode:
                return ToolResult(output=result.output)

            # Return success message (not the content) for single edit
            if replace_all:
                count = content.count(old_string)  # type: ignore[arg-type]
                return ToolResult(output=f"Replaced {count} occurrence(s) in {path}")
            else:
                return ToolResult(output=f"Replaced text in {path}")

        except (PathSecurityError, ValueError) as e:
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
                error=(
                    f"String appears {count} times. "
                    "Use replace_all=true or provide more context for unique match."
                )
            )

        if replace_all:
            new_content = content.replace(old_string, new_string)
        else:
            new_content = content.replace(old_string, new_string, 1)

        return ToolResult(output=new_content)

    def _find_line_number(self, content: str, substring: str, occurrence: int = 1) -> int:
        """Find line number where substring starts (1-indexed).

        Args:
            content: The file content to search
            substring: The substring to find
            occurrence: Which occurrence to find (1-indexed, default 1)

        Returns:
            Line number (1-indexed) where the occurrence starts
        """
        start_pos = 0
        for _ in range(occurrence):
            pos = content.find(substring, start_pos)
            if pos == -1:
                return -1
            start_pos = pos + 1

        # Count newlines before the found position to get line number
        return content[:start_pos - 1].count('\n') + 1

    def _batch_replace(
        self,
        content: str,
        edits: list[dict[str, Any]]
    ) -> ToolResult:
        """Apply multiple string replacements atomically.

        Validates all edits first, then applies sequentially.
        Returns error if any edit would fail (no partial changes).

        Line numbers in output reference original file positions.

        Args:
            content: The file content to edit
            edits: List of edit dictionaries with old_string, new_string, replace_all

        Returns:
            ToolResult with success message or error. On success, the result
            has a _new_content attribute with the modified content.
        """
        if not edits:
            return ToolResult(error="edits array cannot be empty")

        # Phase 1: Validate all edits and record original line numbers
        edit_info: list[dict[str, Any]] = []

        for i, edit in enumerate(edits, 1):
            old_string = edit.get("old_string")
            new_string = edit.get("new_string", "")
            replace_all_edit = edit.get("replace_all", False)

            if not old_string:
                return ToolResult(
                    error=f"Batch edit failed (no changes made):\n"
                    f"  Edit {i}: old_string cannot be empty"
                )

            count = content.count(old_string)

            if count == 0:
                truncated = old_string[:50] + "..." if len(old_string) > 50 else old_string
                return ToolResult(
                    error=f"Batch edit failed (no changes made):\n"
                    f"  Edit {i}: \"{truncated}\" not found in file"
                )

            if not replace_all_edit and count > 1:
                truncated = old_string[:50] + "..." if len(old_string) > 50 else old_string
                return ToolResult(
                    error=(
                        f"Batch edit failed (no changes made):\n"
                        f"  Edit {i}: \"{truncated}\" appears {count} times. "
                        f"Use replace_all=true or provide more context."
                    )
                )

            # Record line number(s) in original content
            line_num = self._find_line_number(content, old_string)
            edit_info.append({
                "index": i,
                "old_string": old_string,
                "new_string": new_string,
                "replace_all": replace_all_edit,
                "line_num": line_num,
                "count": count
            })

        # Phase 2: Apply all edits sequentially to in-memory content
        new_content = content
        for info in edit_info:
            if info["replace_all"]:
                new_content = new_content.replace(info["old_string"], info["new_string"])
            else:
                new_content = new_content.replace(info["old_string"], info["new_string"], 1)

        # Build success message with original line numbers
        lines = []
        for info in edit_info:
            truncated = info["old_string"][:30]
            if len(info["old_string"]) > 30:
                truncated += "..."
            truncated = truncated.replace('\n', '\\n')

            if info["replace_all"] and info["count"] > 1:
                lines.append(
                    f"  {info['index']}. Replaced \"{truncated}\" ({info['count']} occurrences)"
                )
            else:
                lines.append(
                    f"  {info['index']}. Replaced \"{truncated}\" (line {info['line_num']})"
                )

        # Create result with embedded content for the caller
        result = ToolResult(output=f"Applied {len(edits)} edits:\n" + "\n".join(lines))
        # Attach the new content as a private attribute for the execute method
        object.__setattr__(result, '_new_content', new_content)
        return result


# Factory for dependency injection
edit_file_factory = file_skill_factory(EditFileSkill)
