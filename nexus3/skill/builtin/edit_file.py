"""Exact-string file editing skills."""

import asyncio
from pathlib import Path
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import atomic_write_bytes, detect_line_ending
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory


class _ExactStringEditSkill(FileSkill):
    """Shared helpers for exact-string file editing skills."""

    async def _load_text_file(self, path: str) -> tuple[Path, str, str]:
        """Load a UTF-8 text file and normalize line endings for processing.

        Returns:
            Tuple of (validated_path, normalized_content, original_line_ending)
        """
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
        edits: list[dict[str, Any]],
    ) -> tuple[str, str] | ToolResult:
        """Apply multiple string replacements atomically.

        Validates all edits first, then applies sequentially.
        Returns error if any edit would fail (no partial changes).

        Line numbers in output reference original file positions.

        Args:
            content: The file content to edit
            edits: List of edit dictionaries with old_string, new_string, replace_all

        Returns:
            `(new_content, success_message)` or a ToolResult error.
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
            current_count = new_content.count(info["old_string"])
            if current_count == 0:
                truncated = info["old_string"][:50]
                if len(info["old_string"]) > 50:
                    truncated += "..."
                return ToolResult(
                    error=(
                        "Batch edit failed (no changes made):\n"
                        f"  Edit {info['index']}: \"{truncated}\" no longer matches "
                        "the file after earlier batch edits. Split the call or "
                        "update the later edit to match the post-edit content."
                    )
                )

            if not info["replace_all"] and current_count > 1:
                truncated = info["old_string"][:50]
                if len(info["old_string"]) > 50:
                    truncated += "..."
                return ToolResult(
                    error=(
                        "Batch edit failed (no changes made):\n"
                        f"  Edit {info['index']}: \"{truncated}\" appears "
                        f"{current_count} times after earlier batch edits. "
                        "Use replace_all=true or provide more context."
                    )
                )

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

        return new_content, f"Applied {len(edits)} edits:\n" + "\n".join(lines)


class EditFileSkill(_ExactStringEditSkill):
    """Skill for a single exact-string replacement in a UTF-8 file."""

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            "Replace one exact literal string in a UTF-8 file. "
            "Required: path, old_string, new_string. "
            "Use only for a single literal replacement where old_string is already known exactly. "
            "old_string must match exactly, including whitespace and newlines. "
            "If it appears multiple times, add more context or set replace_all=true. "
            "For multiple literal replacements use edit_file_batch. "
            "Use edit_lines or edit_lines_batch for line-number edits, and "
            "regex_replace for pattern-based edits."
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
                "old_string": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "Exact literal text to replace. Must match the file exactly, "
                        "including whitespace and line breaks."
                    ),
                },
                "new_string": {
                    "type": "string",
                    "description": (
                        "Replacement text. Use an empty string to delete the matched text."
                    ),
                },
                "replace_all": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Replace all matches instead of requiring one unique match."
                    ),
                },
            },
            "required": ["path", "old_string", "new_string"],
            "additionalProperties": False,
        }

    async def execute(
        self,
        path: str = "",
        old_string: str | None = None,
        new_string: str | None = None,
        replace_all: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        """Replace one exact string match in a file."""
        try:
            p, content, original_line_ending = await self._load_text_file(path)
            result = self._string_replace(content, old_string, new_string or "", replace_all)
            if result.error:
                return result

            await self._write_text_file(p, result.output, original_line_ending)

            if replace_all:
                count = content.count(old_string)  # type: ignore[arg-type]
                return ToolResult(output=f"Replaced {count} occurrence(s) in {path}")

            return ToolResult(output=f"Replaced text in {path}")
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


class EditFileBatchSkill(_ExactStringEditSkill):
    """Skill for atomic batches of exact-string replacements in a UTF-8 file."""

    @property
    def name(self) -> str:
        return "edit_file_batch"

    @property
    def description(self) -> str:
        return (
            "Apply multiple exact literal replacements atomically in one UTF-8 file. "
            "Required: path and edits=[{old_string, new_string, replace_all?}, ...]. "
            "Use only when multiple literal replacements should succeed or fail together. "
            "Do not send top-level old_string, new_string, or replace_all. "
            "Each edit must match the original file, and later edits must still match "
            "after earlier edits are applied. Split dependent edits into separate calls "
            "or use patch for structural multi-hunk changes."
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
                            "old_string": {
                                "type": "string",
                                "minLength": 1,
                                "description": (
                                    "Exact literal text to replace in this edit. "
                                    "Must match the file exactly, including whitespace "
                                    "and line breaks."
                                ),
                            },
                            "new_string": {
                                "type": "string",
                                "description": (
                                    "Replacement text for this edit. Use an empty string "
                                    "to delete the matched text."
                                ),
                            },
                            "replace_all": {
                                "type": "boolean",
                                "default": False,
                                "description": (
                                    "Replace all matches for this edit instead of "
                                    "requiring one unique match."
                                ),
                            },
                        },
                        "required": ["old_string", "new_string"],
                        "additionalProperties": False,
                    },
                    "description": (
                        "Atomic array of exact literal replacements. All edits are "
                        "validated first, then applied sequentially in one all-or-none "
                        "update."
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
        """Apply an atomic batch of exact string replacements."""
        try:
            p, content, original_line_ending = await self._load_text_file(path)
            batch_result = self._batch_replace(content, edits or [])
            if isinstance(batch_result, ToolResult):
                return batch_result

            new_content, success_message = batch_result
            await self._write_text_file(p, new_content, original_line_ending)
            return ToolResult(output=success_message)
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


# Factory for dependency injection
edit_file_factory = file_skill_factory(EditFileSkill)
edit_file_batch_factory = file_skill_factory(EditFileBatchSkill)
