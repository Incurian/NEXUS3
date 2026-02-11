"""Tag management skill for clipboard entries."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus3.clipboard import ClipboardManager, ClipboardScope
from nexus3.core.types import ToolResult
from nexus3.skill.base import base_skill_factory

if TYPE_CHECKING:
    from nexus3.skill.services import ServiceContainer


@base_skill_factory
class ClipboardTagSkill:
    """Manage tags for clipboard entries."""

    def __init__(self, services: ServiceContainer | None = None) -> None:
        self._services = services

    @property
    def name(self) -> str:
        return "clipboard_tag"

    @property
    def description(self) -> str:
        return (
            "Manage clipboard entry tags: list all tags,"
            " add/remove tags from entries, create/delete tags."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "add", "remove", "create", "delete"],
                    "description": "Action to perform",
                },
                "name": {
                    "type": "string",
                    "description": "Tag name (for add/remove/create/delete)",
                },
                "entry_key": {
                    "type": "string",
                    "description": "Clipboard entry key (for add/remove)",
                },
                "scope": {
                    "type": "string",
                    "enum": ["agent", "project", "system"],
                    "description": "Entry scope (for add/remove, required with entry_key)",
                },
                "description": {
                    "type": "string",
                    "description": "Tag description (for create)",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str = "",
        name: str | None = None,
        entry_key: str | None = None,
        scope: str | None = None,
        description: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        manager = self._services.get("clipboard_manager")
        if manager is None:
            return ToolResult(error="Clipboard service not available")

        match action:
            case "list":
                return self._list_tags(manager, scope)
            case "add":
                return self._add_tag(manager, name, entry_key, scope)
            case "remove":
                return self._remove_tag(manager, name, entry_key, scope)
            case "create":
                return self._create_tag(manager, name, description)
            case "delete":
                return self._delete_tag(manager, name)
            case _:
                return ToolResult(error=f"Unknown action: {action}")

    def _list_tags(self, manager: ClipboardManager, scope: str | None) -> ToolResult:
        """List all tags, optionally filtered by scope."""
        clip_scope: ClipboardScope | None = None
        if scope is not None:
            try:
                clip_scope = ClipboardScope(scope)
            except ValueError:
                return ToolResult(error=f"Invalid scope: {scope}")

        try:
            tags = manager.list_tags(clip_scope)
        except PermissionError as e:
            return ToolResult(error=str(e))

        if not tags:
            return ToolResult(output="No tags found")

        lines = [f"Tags ({len(tags)}):", ""]
        for tag in tags:
            lines.append(f"  - {tag}")
        return ToolResult(output="\n".join(lines))

    def _add_tag(
        self, manager: ClipboardManager, name: str | None, entry_key: str | None, scope: str | None
    ) -> ToolResult:
        """Add a tag to an entry."""
        if not name:
            return ToolResult(error="name is required for add action")
        if not entry_key:
            return ToolResult(error="entry_key is required for add action")
        if not scope:
            return ToolResult(error="scope is required for add action")

        try:
            clip_scope = ClipboardScope(scope)
        except ValueError:
            return ToolResult(error=f"Invalid scope: {scope}")

        try:
            manager.add_tags(entry_key, clip_scope, [name])
        except (PermissionError, KeyError) as e:
            return ToolResult(error=str(e))

        return ToolResult(output=f"Added tag '{name}' to '{entry_key}' [{scope}]")

    def _remove_tag(
        self, manager: ClipboardManager, name: str | None, entry_key: str | None, scope: str | None
    ) -> ToolResult:
        """Remove a tag from an entry."""
        if not name:
            return ToolResult(error="name is required for remove action")
        if not entry_key:
            return ToolResult(error="entry_key is required for remove action")
        if not scope:
            return ToolResult(error="scope is required for remove action")

        try:
            clip_scope = ClipboardScope(scope)
        except ValueError:
            return ToolResult(error=f"Invalid scope: {scope}")

        try:
            manager.remove_tags(entry_key, clip_scope, [name])
        except (PermissionError, KeyError) as e:
            return ToolResult(error=str(e))

        return ToolResult(output=f"Removed tag '{name}' from '{entry_key}' [{scope}]")

    def _create_tag(
        self, manager: ClipboardManager, name: str | None,
        description: str | None,
    ) -> ToolResult:
        """Create a new tag."""
        if not name:
            return ToolResult(error="name is required for create action")

        # Tags are created automatically when added to entries
        # This action is for pre-creating tags with descriptions
        # For now, just validate and confirm
        return ToolResult(
            output=f"Tag '{name}' ready to use"
            " (tags are auto-created when added to entries)"
        )

    def _delete_tag(self, manager: ClipboardManager, name: str | None) -> ToolResult:
        """Delete a tag (removes from all entries via CASCADE)."""
        if not name:
            return ToolResult(error="name is required for delete action")

        # Note: The storage layer handles CASCADE deletion
        # We need to add a delete_tag method to manager if not exists
        # For now, return not implemented
        return ToolResult(
            error="delete_tag not yet implemented"
            " - remove tags from entries individually"
        )


clipboard_tag_factory = ClipboardTagSkill.factory
