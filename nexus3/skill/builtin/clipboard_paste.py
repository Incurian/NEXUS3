"""Paste skill for inserting clipboard content into files."""

import asyncio
from typing import Any

from nexus3.clipboard import ClipboardManager, ClipboardScope, InsertionMode
from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import atomic_write_bytes, detect_line_ending
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory


class PasteSkill(FileSkill):
    """Skill that pastes clipboard content into a target file.

    Supports multiple insertion modes for flexible file modification:
    - after_line/before_line: Insert at specific line number
    - replace_lines: Replace a range of lines
    - at_marker_*: Insert relative to a marker string
    - append/prepend: Add to end or beginning

    Inherits path validation from FileSkill.
    """

    @property
    def name(self) -> str:
        return "paste"

    @property
    def description(self) -> str:
        return (
            "Paste clipboard content into a file. "
            "Supports multiple insertion modes: after_line, before_line, replace_lines, "
            "at_marker_replace, at_marker_after, at_marker_before, append, prepend."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Clipboard key to paste"
                },
                "target": {
                    "type": "string",
                    "description": "Target file path"
                },
                "scope": {
                    "type": "string",
                    "enum": ["agent", "project", "system"],
                    "description": (
                        "Specific scope to search (agent, project, system). "
                        "If not specified, searches agent->project->system automatically."
                    )
                },
                "mode": {
                    "type": "string",
                    "enum": [
                        "after_line", "before_line", "replace_lines",
                        "at_marker_replace", "at_marker_after", "at_marker_before",
                        "append", "prepend"
                    ],
                    "description": "How to insert the content",
                    "default": "append"
                },
                "line_number": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Line number for after_line/before_line modes (1-indexed)"
                },
                "start_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Start line for replace_lines mode (1-indexed, inclusive)"
                },
                "end_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "End line for replace_lines mode (1-indexed, inclusive)"
                },
                "marker": {
                    "type": "string",
                    "description": "Marker string for at_marker_* modes"
                },
                "create_if_missing": {
                    "type": "boolean",
                    "description": "Create file if it doesn't exist (only valid with append mode)",
                    "default": False
                }
            },
            "required": ["key", "target"]
        }

    async def execute(
        self,
        key: str = "",
        target: str = "",
        scope: str | None = None,
        mode: str = "append",
        line_number: int | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
        marker: str | None = None,
        create_if_missing: bool = False,
        **kwargs: Any
    ) -> ToolResult:
        """Paste clipboard content into target file.

        Args:
            key: Clipboard key to paste
            target: Target file path
            scope: Optional scope to search (agent/project/system)
            mode: Insertion mode
            line_number: Line number for after_line/before_line modes
            start_line: Start line for replace_lines mode
            end_line: End line for replace_lines mode
            marker: Marker string for at_marker_* modes
            create_if_missing: Create file if doesn't exist

        Returns:
            ToolResult with success message or error
        """
        if not key:
            return ToolResult(error="No clipboard key provided")

        if not target:
            return ToolResult(error="No target file path provided")

        # Validate mode
        try:
            insertion_mode = InsertionMode(mode)
        except ValueError:
            valid_modes = [m.value for m in InsertionMode]
            return ToolResult(error=f"Invalid mode '{mode}'. Must be one of: {valid_modes}")

        # Validate mode-specific parameters
        param_error = self._validate_mode_params(
            insertion_mode, line_number, start_line, end_line, marker
        )
        if param_error:
            return ToolResult(error=param_error)

        # Get clipboard manager from services
        manager: ClipboardManager | None = self._services.get("clipboard_manager")
        if manager is None:
            return ToolResult(error="Clipboard manager not available")

        # Resolve scope
        resolved_scope: ClipboardScope | None = None
        if scope is not None:
            try:
                resolved_scope = ClipboardScope(scope)
            except ValueError:
                valid_scopes = [s.value for s in ClipboardScope]
                return ToolResult(error=f"Invalid scope '{scope}'. Must be one of: {valid_scopes}")

        # Get clipboard entry
        try:
            entry = manager.get(key, resolved_scope)
        except PermissionError as e:
            return ToolResult(error=str(e))

        if entry is None:
            if resolved_scope:
                return ToolResult(
                    error=f"Clipboard key '{key}' not found"
                    f" in {resolved_scope.value} scope"
                )
            return ToolResult(error=f"Clipboard key '{key}' not found in any accessible scope")

        if entry.is_expired:
            return ToolResult(error=f"Clipboard entry '{key}' has expired")

        # Validate target path
        try:
            p = self._validate_path(target)
        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))

        # Read target file content (or handle creation)
        try:
            if p.exists():
                content_bytes = await asyncio.to_thread(p.read_bytes)
                raw_content = content_bytes.decode("utf-8", errors="replace")
                original_line_ending = detect_line_ending(raw_content)
                # Normalize to LF for processing
                content = raw_content.replace('\r\n', '\n').replace('\r', '\n')
            elif create_if_missing:
                if insertion_mode not in (InsertionMode.APPEND, InsertionMode.PREPEND):
                    return ToolResult(
                        error=f"Cannot use mode '{mode}' with"
                        " create_if_missing on non-existent file"
                    )
                content = ""
                original_line_ending = '\n'
            else:
                return ToolResult(error=f"File not found: {target}")
        except PermissionError:
            return ToolResult(error=f"Permission denied: {target}")

        # Get content to paste (normalize line endings)
        paste_content = entry.content.replace('\r\n', '\n').replace('\r', '\n')

        # Apply insertion
        try:
            new_content = self._apply_insertion(
                content, paste_content, insertion_mode,
                line_number, start_line, end_line, marker
            )
        except ValueError as e:
            return ToolResult(error=str(e))

        # Convert line endings back to original and write
        if original_line_ending != '\n':
            new_content = new_content.replace('\n', original_line_ending)

        try:
            await asyncio.to_thread(atomic_write_bytes, p, new_content.encode('utf-8'))
        except PermissionError:
            return ToolResult(error=f"Permission denied writing to: {target}")
        except Exception as e:
            return ToolResult(error=f"Error writing file: {e}")

        # Build success message
        source_info = f" (from {entry.scope.value} scope)"
        mode_info = self._format_mode_info(
            insertion_mode, line_number, start_line, end_line, marker
        )

        return ToolResult(
            output=f"Pasted {entry.line_count} lines from clipboard key '{key}'{source_info} "
                   f"into {target} ({mode_info})"
        )

    def _validate_mode_params(
        self,
        mode: InsertionMode,
        line_number: int | None,
        start_line: int | None,
        end_line: int | None,
        marker: str | None
    ) -> str | None:
        """Validate mode-specific parameters. Returns error message or None."""
        if mode in (InsertionMode.AFTER_LINE, InsertionMode.BEFORE_LINE):
            if line_number is None:
                return f"Mode '{mode.value}' requires line_number parameter"

        elif mode == InsertionMode.REPLACE_LINES:
            if start_line is None:
                return "Mode 'replace_lines' requires start_line parameter"
            if end_line is None:
                return "Mode 'replace_lines' requires end_line parameter"
            if end_line < start_line:
                return f"end_line ({end_line}) must be >= start_line ({start_line})"

        elif mode in (
            InsertionMode.AT_MARKER_REPLACE,
            InsertionMode.AT_MARKER_AFTER,
            InsertionMode.AT_MARKER_BEFORE
        ):
            if marker is None:
                return f"Mode '{mode.value}' requires marker parameter"
            if not marker:
                return "Marker cannot be empty"

        return None

    def _apply_insertion(
        self,
        content: str,
        paste_content: str,
        mode: InsertionMode,
        line_number: int | None,
        start_line: int | None,
        end_line: int | None,
        marker: str | None
    ) -> str:
        """Apply the insertion based on mode. Returns new content."""
        lines = content.split('\n') if content else []

        # Ensure paste content ends with newline for line-based operations
        # (except when appending to empty file or content doesn't need trailing newline)
        paste_lines = paste_content.rstrip('\n').split('\n')

        if mode == InsertionMode.APPEND:
            if not content:
                return paste_content
            # Ensure content ends with newline before appending
            if content and not content.endswith('\n'):
                return content + '\n' + paste_content
            return content + paste_content

        elif mode == InsertionMode.PREPEND:
            # Ensure paste content ends with newline before existing content
            if paste_content and not paste_content.endswith('\n'):
                return paste_content + '\n' + content
            return paste_content + content

        elif mode == InsertionMode.AFTER_LINE:
            assert line_number is not None
            if line_number > len(lines):
                raise ValueError(
                    f"Line number {line_number} exceeds file length ({len(lines)} lines)"
                )
            # Insert after the specified line
            result_lines = lines[:line_number] + paste_lines + lines[line_number:]
            return '\n'.join(result_lines)

        elif mode == InsertionMode.BEFORE_LINE:
            assert line_number is not None
            if line_number > len(lines) + 1:
                raise ValueError(
                    f"Line number {line_number} exceeds file length ({len(lines)} lines)"
                )
            # Insert before the specified line (1-indexed, so line 1 means at start)
            insert_idx = line_number - 1
            result_lines = lines[:insert_idx] + paste_lines + lines[insert_idx:]
            return '\n'.join(result_lines)

        elif mode == InsertionMode.REPLACE_LINES:
            assert start_line is not None and end_line is not None
            if start_line > len(lines):
                raise ValueError(
                    f"Start line {start_line} exceeds file length ({len(lines)} lines)"
                )
            if end_line > len(lines):
                raise ValueError(
                    f"End line {end_line} exceeds file length ({len(lines)} lines)"
                )
            # Replace lines from start_line to end_line (both inclusive, 1-indexed)
            start_idx = start_line - 1
            end_idx = end_line
            result_lines = lines[:start_idx] + paste_lines + lines[end_idx:]
            return '\n'.join(result_lines)

        elif mode == InsertionMode.AT_MARKER_REPLACE:
            assert marker is not None
            if marker not in content:
                raise ValueError(f"Marker '{marker}' not found in file")
            # Replace the marker with paste content
            return content.replace(marker, paste_content, 1)

        elif mode == InsertionMode.AT_MARKER_AFTER:
            assert marker is not None
            # Find the line containing the marker and insert after it
            marker_line_idx = None
            for i, line in enumerate(lines):
                if marker in line:
                    marker_line_idx = i
                    break
            if marker_line_idx is None:
                raise ValueError(f"Marker '{marker}' not found in file")
            result_lines = (
                lines[:marker_line_idx + 1] + paste_lines + lines[marker_line_idx + 1:]
            )
            return '\n'.join(result_lines)

        elif mode == InsertionMode.AT_MARKER_BEFORE:
            assert marker is not None
            # Find the line containing the marker and insert before it
            marker_line_idx = None
            for i, line in enumerate(lines):
                if marker in line:
                    marker_line_idx = i
                    break
            if marker_line_idx is None:
                raise ValueError(f"Marker '{marker}' not found in file")
            result_lines = (
                lines[:marker_line_idx] + paste_lines + lines[marker_line_idx:]
            )
            return '\n'.join(result_lines)

        raise ValueError(f"Unknown insertion mode: {mode}")

    def _format_mode_info(
        self,
        mode: InsertionMode,
        line_number: int | None,
        start_line: int | None,
        end_line: int | None,
        marker: str | None
    ) -> str:
        """Format mode information for success message."""
        if mode == InsertionMode.APPEND:
            return "appended"
        elif mode == InsertionMode.PREPEND:
            return "prepended"
        elif mode == InsertionMode.AFTER_LINE:
            return f"inserted after line {line_number}"
        elif mode == InsertionMode.BEFORE_LINE:
            return f"inserted before line {line_number}"
        elif mode == InsertionMode.REPLACE_LINES:
            return f"replaced lines {start_line}-{end_line}"
        elif mode == InsertionMode.AT_MARKER_REPLACE:
            marker_preview = (marker or "")[:30]
            if len(marker or "") > 30:
                marker_preview += "..."
            return f"replaced marker '{marker_preview}'"
        elif mode == InsertionMode.AT_MARKER_AFTER:
            marker_preview = (marker or "")[:30]
            if len(marker or "") > 30:
                marker_preview += "..."
            return f"inserted after marker '{marker_preview}'"
        elif mode == InsertionMode.AT_MARKER_BEFORE:
            marker_preview = (marker or "")[:30]
            if len(marker or "") > 30:
                marker_preview += "..."
            return f"inserted before marker '{marker_preview}'"
        return mode.value


# Factory for dependency injection
paste_skill_factory = file_skill_factory(PasteSkill)
