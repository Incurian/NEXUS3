"""Management skills for clipboard: list, get, update, delete, clear."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, TypeVar

from nexus3.clipboard import ClipboardManager, ClipboardScope, format_entry_detail
from nexus3.core.types import ToolResult
from nexus3.skill.base import _wrap_with_validation

if TYPE_CHECKING:
    from nexus3.skill.services import ServiceContainer


# Type variable for service-based skills
_S = TypeVar("_S", bound="ClipboardSkillBase")


def clipboard_skill_factory(cls: type[_S]) -> Callable[["ServiceContainer"], _S]:
    """Factory for clipboard skills that need ServiceContainer.

    Similar to file_skill_factory but for skills that only need clipboard access.

    Args:
        cls: A clipboard skill class with __init__(services).

    Returns:
        A factory function that creates skill instances with services injected.
    """
    def factory(services: "ServiceContainer") -> _S:
        skill = cls(services)
        _wrap_with_validation(skill)
        return skill

    # Attach as class attribute for convenience
    cls.factory = factory  # type: ignore[attr-defined]
    return factory


class ClipboardSkillBase:
    """Base class for clipboard management skills.

    Provides services injection without file path validation.
    """

    def __init__(self, services: "ServiceContainer") -> None:
        """Initialize with ServiceContainer for clipboard access.

        Args:
            services: ServiceContainer for accessing clipboard_manager.
        """
        self._services = services


class ClipboardListSkill(ClipboardSkillBase):
    """List available clipboard entries."""

    @property
    def name(self) -> str:
        return "clipboard_list"

    @property
    def description(self) -> str:
        return "List clipboard entries across all accessible scopes."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["agent", "project", "system"],
                    "description": "Filter by scope. Omit to show all accessible scopes.",
                },
                "verbose": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include content preview (first/last 3 lines)",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter to entries having ALL of these tags (AND logic)",
                },
                "any_tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter to entries having ANY of these tags (OR logic)",
                },
            },
        }

    async def execute(
        self,
        scope: str | None = None,
        verbose: bool = False,
        tags: list[str] | None = None,
        any_tags: list[str] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        manager = self._services.get("clipboard_manager")
        if manager is None:
            return ToolResult(error="Clipboard service not available")

        clip_scope: ClipboardScope | None = None
        if scope is not None:
            try:
                clip_scope = ClipboardScope(scope)
            except ValueError:
                return ToolResult(error=f"Invalid scope: {scope}")

        try:
            entries = manager.list_entries(clip_scope)
        except PermissionError as e:
            return ToolResult(error=str(e))

        # Apply tag filters
        if tags:
            entries = [e for e in entries if all(t in e.tags for t in tags)]
        if any_tags:
            entries = [e for e in entries if any(t in e.tags for t in any_tags)]

        if not entries:
            if scope:
                return ToolResult(output=f"No clipboard entries in {scope} scope")
            return ToolResult(output="No clipboard entries")

        lines = ["Clipboard entries:", ""]
        for entry in entries:
            lines.append(format_entry_detail(entry, verbose=verbose))
            lines.append("")

        return ToolResult(output="\n".join(lines))


class ClipboardGetSkill(ClipboardSkillBase):
    """Get clipboard entry content."""

    @property
    def name(self) -> str:
        return "clipboard_get"

    @property
    def description(self) -> str:
        return (
            "Get the content of a clipboard entry. Use sparingly for large entries "
            "as content enters LLM context. For inspection, use clipboard_list(verbose=True)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Clipboard key",
                },
                "scope": {
                    "type": "string",
                    "enum": ["agent", "project", "system"],
                    "description": "Scope to search. Omit to search agent→project→system.",
                },
                "start_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Return subset starting at this line",
                },
                "end_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Return subset ending at this line (inclusive)",
                },
            },
            "required": ["key"],
        }

    async def execute(
        self,
        key: str = "",
        scope: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        manager = self._services.get("clipboard_manager")
        if manager is None:
            return ToolResult(error="Clipboard service not available")

        clip_scope: ClipboardScope | None = None
        if scope is not None:
            try:
                clip_scope = ClipboardScope(scope)
            except ValueError:
                return ToolResult(error=f"Invalid scope: {scope}")

        try:
            entry = manager.get(key, clip_scope)
        except PermissionError as e:
            return ToolResult(error=str(e))

        if entry is None:
            if scope:
                return ToolResult(error=f"Key '{key}' not found in {scope} scope")
            return ToolResult(error=f"Key '{key}' not found in any accessible scope")

        content = entry.content

        # Apply line range if specified
        if start_line is not None or end_line is not None:
            lines = content.splitlines(keepends=True)
            start = (start_line or 1) - 1
            end = end_line or len(lines)

            if start < 0 or start >= len(lines):
                return ToolResult(error=f"start_line out of range (entry has {len(lines)} lines)")
            if end > len(lines):
                return ToolResult(error=f"end_line out of range (entry has {len(lines)} lines)")
            if end <= start:
                return ToolResult(error="end_line must be greater than start_line")

            content = "".join(lines[start:end])

        return ToolResult(output=content)


class ClipboardUpdateSkill(ClipboardSkillBase):
    """Update an existing clipboard entry."""

    @property
    def name(self) -> str:
        return "clipboard_update"

    @property
    def description(self) -> str:
        return (
            "Update an existing clipboard entry. Can update content from a file, "
            "change description, or rename the key."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Existing clipboard key to update",
                },
                "scope": {
                    "type": "string",
                    "enum": ["agent", "project", "system"],
                    "description": "Scope of the entry (required)",
                },
                "source": {
                    "type": "string",
                    "description": "New file to copy content from",
                },
                "content": {
                    "type": "string",
                    "description": "New content directly (use source for files)",
                },
                "start_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "If source provided, first line to copy",
                },
                "end_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "If source provided, last line to copy",
                },
                "short_description": {
                    "type": "string",
                    "description": "New description",
                },
                "new_key": {
                    "type": "string",
                    "description": "Rename entry to this key",
                },
                "ttl_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Set new TTL in seconds. Entry expires after this time. Omit to keep current TTL.",
                },
            },
            "required": ["key", "scope"],
        }

    async def execute(
        self,
        key: str = "",
        scope: str = "",
        source: str | None = None,
        content: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
        short_description: str | None = None,
        new_key: str | None = None,
        ttl_seconds: int | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        manager = self._services.get("clipboard_manager")
        if manager is None:
            return ToolResult(error="Clipboard service not available")

        try:
            clip_scope = ClipboardScope(scope)
        except ValueError:
            return ToolResult(error=f"Invalid scope: {scope}")

        # If source provided, read file content
        new_content = content
        source_path_str: str | None = None
        source_lines_str: str | None = None

        if source is not None:
            import asyncio
            from pathlib import Path
            source_path = Path(source).expanduser().resolve()
            try:
                file_content = await asyncio.to_thread(
                    source_path.read_text, encoding="utf-8", errors="replace"
                )
            except OSError as e:
                return ToolResult(error=f"Cannot read source file: {e}")

            if start_line is not None:
                lines = file_content.splitlines(keepends=True)
                if start_line < 1 or start_line > len(lines):
                    return ToolResult(error=f"start_line out of range (file has {len(lines)} lines)")
                end = end_line if end_line is not None else start_line
                if end > len(lines):
                    return ToolResult(error=f"end_line out of range (file has {len(lines)} lines)")
                new_content = "".join(lines[start_line - 1:end])
                source_lines_str = f"{start_line}-{end}" if end != start_line else str(start_line)
            else:
                new_content = file_content

            source_path_str = str(source_path)

        try:
            entry, warning = manager.update(
                key,
                clip_scope,
                content=new_content,
                short_description=short_description,
                source_path=source_path_str,
                source_lines=source_lines_str,
                new_key=new_key,
                ttl_seconds=ttl_seconds,
            )
        except (PermissionError, KeyError, ValueError) as e:
            return ToolResult(error=str(e))

        msg = f"Updated clipboard '{entry.key}' [{scope} scope]: {entry.line_count} lines"
        if warning:
            msg = f"{warning}\n{msg}"

        return ToolResult(output=msg)


class ClipboardDeleteSkill(ClipboardSkillBase):
    """Delete a clipboard entry."""

    @property
    def name(self) -> str:
        return "clipboard_delete"

    @property
    def description(self) -> str:
        return "Delete a clipboard entry."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Clipboard key to delete",
                },
                "scope": {
                    "type": "string",
                    "enum": ["agent", "project", "system"],
                    "description": "Scope of the entry (required)",
                },
            },
            "required": ["key", "scope"],
        }

    async def execute(
        self,
        key: str = "",
        scope: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        manager = self._services.get("clipboard_manager")
        if manager is None:
            return ToolResult(error="Clipboard service not available")

        try:
            clip_scope = ClipboardScope(scope)
        except ValueError:
            return ToolResult(error=f"Invalid scope: {scope}")

        try:
            deleted = manager.delete(key, clip_scope)
        except PermissionError as e:
            return ToolResult(error=str(e))

        if deleted:
            return ToolResult(output=f"Deleted clipboard '{key}' from {scope} scope")
        else:
            return ToolResult(error=f"Key '{key}' not found in {scope} scope")


class ClipboardClearSkill(ClipboardSkillBase):
    """Clear all entries in a clipboard scope."""

    @property
    def name(self) -> str:
        return "clipboard_clear"

    @property
    def description(self) -> str:
        return "Clear all entries in a clipboard scope. Requires confirm=True."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["agent", "project", "system"],
                    "description": "Scope to clear (required)",
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Must be true to proceed",
                },
            },
            "required": ["scope", "confirm"],
        }

    async def execute(
        self,
        scope: str = "",
        confirm: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        if not confirm:
            return ToolResult(error="Must set confirm=True to clear clipboard")

        manager = self._services.get("clipboard_manager")
        if manager is None:
            return ToolResult(error="Clipboard service not available")

        try:
            clip_scope = ClipboardScope(scope)
        except ValueError:
            return ToolResult(error=f"Invalid scope: {scope}")

        try:
            count = manager.clear(clip_scope)
        except PermissionError as e:
            return ToolResult(error=str(e))

        return ToolResult(output=f"Cleared {count} entries from {scope} clipboard")


# Factories
clipboard_list_factory = clipboard_skill_factory(ClipboardListSkill)
clipboard_get_factory = clipboard_skill_factory(ClipboardGetSkill)
clipboard_update_factory = clipboard_skill_factory(ClipboardUpdateSkill)
clipboard_delete_factory = clipboard_skill_factory(ClipboardDeleteSkill)
clipboard_clear_factory = clipboard_skill_factory(ClipboardClearSkill)
