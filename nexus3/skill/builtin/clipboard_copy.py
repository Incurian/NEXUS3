"""Copy and Cut skills for clipboard operations.

These skills copy file content (or portions thereof) to the clipboard system,
enabling efficient multi-file refactoring without repeated LLM context overhead.
"""

import asyncio
from typing import Any

from nexus3.clipboard import ClipboardManager, ClipboardScope
from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import atomic_write_bytes, detect_line_ending
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory


def _parse_scope(scope_str: str) -> ClipboardScope:
    """Parse scope string to ClipboardScope enum.

    Args:
        scope_str: One of 'agent', 'project', 'system'

    Returns:
        ClipboardScope enum value

    Raises:
        ValueError: If scope_str is not valid
    """
    scope_str = scope_str.lower().strip()
    try:
        return ClipboardScope(scope_str)
    except ValueError as e:
        valid = ", ".join(s.value for s in ClipboardScope)
        raise ValueError(f"Invalid scope '{scope_str}'. Must be one of: {valid}") from e


def _read_lines(
    content: str,
    start_line: int | None,
    end_line: int | None,
) -> tuple[str, int, int]:
    """Extract lines from content.

    Args:
        content: File content (normalized to LF)
        start_line: First line to extract (1-indexed), None for beginning
        end_line: Last line to extract (inclusive), None for end

    Returns:
        Tuple of (extracted content, actual start line, actual end line)

    Raises:
        ValueError: If line numbers are invalid
    """
    lines = content.splitlines(keepends=True)
    total_lines = len(lines)

    if total_lines == 0:
        return "", 1, 1

    # Default to full file
    actual_start = start_line if start_line is not None else 1
    actual_end = end_line if end_line is not None else total_lines

    # Validate
    if actual_start < 1:
        raise ValueError("start_line must be >= 1")
    if actual_start > total_lines:
        raise ValueError(f"start_line {actual_start} exceeds file length ({total_lines} lines)")
    if actual_end < actual_start:
        raise ValueError(f"end_line ({actual_end}) cannot be less than start_line ({actual_start})")
    if actual_end > total_lines:
        actual_end = total_lines  # Clamp to file end

    # Extract (convert to 0-indexed)
    extracted_lines = lines[actual_start - 1:actual_end]
    extracted = "".join(extracted_lines)

    return extracted, actual_start, actual_end


class CopySkill(FileSkill):
    """Copy file content to clipboard.

    Copies file content (or a line range) to the clipboard under a specified key.
    Use the clipboard for efficient multi-file refactoring without repeated
    context overhead from the LLM reading large file chunks.

    Inherits path validation from FileSkill.
    """

    @property
    def name(self) -> str:
        return "copy"

    @property
    def description(self) -> str:
        return (
            "Copy file content to clipboard. "
            "Copies entire file or a line range to clipboard under a key. "
            "Use for multi-file refactoring without LLM context overhead. "
            "Scopes: 'agent' (session only), 'project' (persistent in .nexus3/), "
            "'system' (persistent in ~/.nexus3/). "
            "Keys must be unique within scope - use clipboard_update to modify existing."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Path to the file to copy from"
                },
                "key": {
                    "type": "string",
                    "description": "Clipboard key name (must be unique within scope)"
                },
                "scope": {
                    "type": "string",
                    "description": "Clipboard scope: 'agent' (default), 'project', or 'system'",
                    "enum": ["agent", "project", "system"],
                    "default": "agent"
                },
                "start_line": {
                    "type": "integer",
                    "description": "First line to copy (1-indexed, default: beginning of file)",
                    "minimum": 1
                },
                "end_line": {
                    "type": "integer",
                    "description": "Last line to copy (inclusive, default: end of file)",
                    "minimum": 1
                },
                "short_description": {
                    "type": "string",
                    "description": "Brief description of the copied content"
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for organizing clipboard entries"
                },
                "ttl_seconds": {
                    "type": "integer",
                    "description": "Time-to-live in seconds (None = permanent)",
                    "minimum": 1
                }
            },
            "required": ["source", "key"]
        }

    async def execute(
        self,
        source: str = "",
        key: str = "",
        scope: str = "agent",
        start_line: int | None = None,
        end_line: int | None = None,
        short_description: str | None = None,
        tags: list[str] | None = None,
        ttl_seconds: int | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Copy file content to clipboard.

        Args:
            source: Path to the file to copy from
            key: Clipboard key name
            scope: Clipboard scope ('agent', 'project', 'system')
            start_line: First line to copy (1-indexed)
            end_line: Last line to copy (inclusive)
            short_description: Brief description
            tags: Tags for organizing entries
            ttl_seconds: Time-to-live in seconds

        Returns:
            ToolResult with success message or error
        """
        if not key:
            return ToolResult(error="key is required")

        try:
            # Parse scope
            clipboard_scope = _parse_scope(scope)

            # Validate path (resolves symlinks, checks allowed_paths if set)
            p = self._validate_path(source)

            # Get clipboard manager
            clipboard_manager: ClipboardManager | None = self._services.get("clipboard_manager")
            if clipboard_manager is None:
                return ToolResult(error="Clipboard system not available")

            # Read file content
            try:
                content_bytes = await asyncio.to_thread(p.read_bytes)
                raw_content = content_bytes.decode("utf-8", errors="replace")
                # Normalize to LF for processing
                content = raw_content.replace('\r\n', '\n').replace('\r', '\n')
            except FileNotFoundError:
                return ToolResult(error=f"File not found: {source}")
            except PermissionError:
                return ToolResult(error=f"Permission denied: {source}")
            except IsADirectoryError:
                return ToolResult(error=f"Path is a directory: {source}")

            # Extract lines if specified
            try:
                extracted, actual_start, actual_end = _read_lines(content, start_line, end_line)
            except ValueError as e:
                return ToolResult(error=str(e))

            if not extracted:
                return ToolResult(error="No content to copy (file is empty)")

            # Determine source_lines for metadata
            source_lines = None
            if start_line is not None or end_line is not None:
                source_lines = f"{actual_start}-{actual_end}"

            # Copy to clipboard
            try:
                entry, warning = clipboard_manager.copy(
                    key=key,
                    content=extracted,
                    scope=clipboard_scope,
                    short_description=short_description,
                    source_path=str(p),
                    source_lines=source_lines,
                    tags=tags,
                    ttl_seconds=ttl_seconds,
                )
            except PermissionError as e:
                return ToolResult(error=str(e))
            except ValueError as e:
                return ToolResult(error=str(e))

            # Build success message
            msg_parts = [
                f"Copied to clipboard '{key}' ({clipboard_scope.value} scope):",
                f"  Source: {p}",
            ]
            if source_lines:
                msg_parts.append(f"  Lines: {source_lines}")
            msg_parts.append(f"  Size: {entry.line_count} lines, {entry.byte_count} bytes")

            if warning:
                msg_parts.append(f"  {warning}")

            return ToolResult(output="\n".join(msg_parts))

        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))
        except Exception as e:
            return ToolResult(error=f"Error copying to clipboard: {e}")


class CutSkill(FileSkill):
    """Cut file content (copy to clipboard + remove from source).

    Cuts file content (or a line range) to the clipboard, removing it from
    the source file. For whole-file cuts, the file content is cleared but
    the file itself is not deleted.

    Inherits path validation from FileSkill.
    """

    @property
    def name(self) -> str:
        return "cut"

    @property
    def description(self) -> str:
        return (
            "Cut file content to clipboard (copy + remove from source). "
            "Cuts entire file or a line range to clipboard under a key, "
            "removing the content from the source file. "
            "For whole-file cuts, the file content is cleared but not deleted. "
            "Use for moving code between files without LLM context overhead. "
            "Scopes: 'agent' (session only), 'project' (persistent), 'system' (global)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Path to the file to cut from"
                },
                "key": {
                    "type": "string",
                    "description": "Clipboard key name (must be unique within scope)"
                },
                "scope": {
                    "type": "string",
                    "description": "Clipboard scope: 'agent' (default), 'project', or 'system'",
                    "enum": ["agent", "project", "system"],
                    "default": "agent"
                },
                "start_line": {
                    "type": "integer",
                    "description": "First line to cut (1-indexed, default: beginning of file)",
                    "minimum": 1
                },
                "end_line": {
                    "type": "integer",
                    "description": "Last line to cut (inclusive, default: end of file)",
                    "minimum": 1
                },
                "short_description": {
                    "type": "string",
                    "description": "Brief description of the cut content"
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for organizing clipboard entries"
                },
                "ttl_seconds": {
                    "type": "integer",
                    "description": "Time-to-live in seconds (None = permanent)",
                    "minimum": 1
                }
            },
            "required": ["source", "key"]
        }

    async def execute(
        self,
        source: str = "",
        key: str = "",
        scope: str = "agent",
        start_line: int | None = None,
        end_line: int | None = None,
        short_description: str | None = None,
        tags: list[str] | None = None,
        ttl_seconds: int | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Cut file content to clipboard.

        Args:
            source: Path to the file to cut from
            key: Clipboard key name
            scope: Clipboard scope ('agent', 'project', 'system')
            start_line: First line to cut (1-indexed)
            end_line: Last line to cut (inclusive)
            short_description: Brief description
            tags: Tags for organizing entries
            ttl_seconds: Time-to-live in seconds

        Returns:
            ToolResult with success message or error
        """
        if not key:
            return ToolResult(error="key is required")

        try:
            # Parse scope
            clipboard_scope = _parse_scope(scope)

            # Validate path (resolves symlinks, checks allowed_paths if set)
            p = self._validate_path(source)

            # Get clipboard manager
            clipboard_manager: ClipboardManager | None = self._services.get("clipboard_manager")
            if clipboard_manager is None:
                return ToolResult(error="Clipboard system not available")

            # Read file content
            try:
                content_bytes = await asyncio.to_thread(p.read_bytes)
                raw_content = content_bytes.decode("utf-8", errors="replace")
                original_line_ending = detect_line_ending(raw_content)
                # Normalize to LF for processing
                content = raw_content.replace('\r\n', '\n').replace('\r', '\n')
            except FileNotFoundError:
                return ToolResult(error=f"File not found: {source}")
            except PermissionError:
                return ToolResult(error=f"Permission denied: {source}")
            except IsADirectoryError:
                return ToolResult(error=f"Path is a directory: {source}")

            # Extract lines to cut
            try:
                extracted, actual_start, actual_end = _read_lines(content, start_line, end_line)
            except ValueError as e:
                return ToolResult(error=str(e))

            if not extracted:
                return ToolResult(error="No content to cut (file is empty)")

            # Determine source_lines for metadata
            source_lines = None
            is_whole_file = start_line is None and end_line is None
            if not is_whole_file:
                source_lines = f"{actual_start}-{actual_end}"

            # Copy to clipboard first (before modifying file)
            try:
                entry, warning = clipboard_manager.copy(
                    key=key,
                    content=extracted,
                    scope=clipboard_scope,
                    short_description=short_description,
                    source_path=str(p),
                    source_lines=source_lines,
                    tags=tags,
                    ttl_seconds=ttl_seconds,
                )
            except PermissionError as e:
                return ToolResult(error=str(e))
            except ValueError as e:
                return ToolResult(error=str(e))

            # Now remove the lines from the file
            lines = content.splitlines(keepends=True)

            if is_whole_file:
                # Clear file content but don't delete the file
                new_content = ""
            else:
                # Remove the specified lines
                # actual_start and actual_end are 1-indexed
                new_lines = lines[:actual_start - 1] + lines[actual_end:]
                new_content = "".join(new_lines)

            # Convert line endings back to original and write as binary
            if original_line_ending != '\n' and new_content:
                new_content = new_content.replace('\n', original_line_ending)

            try:
                await asyncio.to_thread(atomic_write_bytes, p, new_content.encode('utf-8'))
            except PermissionError:
                # Clipboard copy succeeded but file write failed
                # Try to roll back by deleting the clipboard entry
                try:
                    clipboard_manager.delete(key, clipboard_scope)
                except Exception:
                    pass  # Best effort rollback
                return ToolResult(
                    error=f"Permission denied writing to {source} (clipboard entry rolled back)"
                )

            # Build success message
            msg_parts = [
                f"Cut to clipboard '{key}' ({clipboard_scope.value} scope):",
                f"  Source: {p}",
            ]
            if source_lines:
                msg_parts.append(f"  Lines removed: {source_lines}")
            else:
                msg_parts.append("  File content cleared")
            msg_parts.append(f"  Size: {entry.line_count} lines, {entry.byte_count} bytes")

            if warning:
                msg_parts.append(f"  {warning}")

            return ToolResult(output="\n".join(msg_parts))

        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))
        except Exception as e:
            return ToolResult(error=f"Error cutting to clipboard: {e}")


# Factories for dependency injection
copy_factory = file_skill_factory(CopySkill)
cut_factory = file_skill_factory(CutSkill)
