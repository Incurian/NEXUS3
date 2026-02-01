"""Search skill for clipboard entries."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus3.clipboard import ClipboardManager, ClipboardScope, format_entry_detail
from nexus3.core.types import ToolResult
from nexus3.skill.base import base_skill_factory

if TYPE_CHECKING:
    from nexus3.skill.services import ServiceContainer


@base_skill_factory
class ClipboardSearchSkill:
    """Search clipboard entries by content or description."""

    def __init__(self, services: "ServiceContainer | None" = None) -> None:
        self._services = services

    @property
    def name(self) -> str:
        return "clipboard_search"

    @property
    def description(self) -> str:
        return "Search clipboard entries by content or description substring."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search substring (case-insensitive)",
                },
                "scope": {
                    "type": "string",
                    "enum": ["agent", "project", "system"],
                    "description": "Scope to search (omit for all accessible scopes)",
                },
                "max_results": {
                    "type": "integer",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum results to return",
                },
            },
            "required": ["query"],
        }

    async def execute(
        self,
        query: str = "",
        scope: str | None = None,
        max_results: int = 50,
        **kwargs: Any,
    ) -> ToolResult:
        if not query:
            return ToolResult(error="Query cannot be empty")

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
            results = manager.search(query, scope=clip_scope)
            # Apply limit if specified
            if max_results and len(results) > max_results:
                results = results[:max_results]
        except PermissionError as e:
            return ToolResult(error=str(e))

        if not results:
            scope_msg = f" in {scope} scope" if scope else ""
            return ToolResult(output=f"No matches found for '{query}'{scope_msg}")

        lines = [f"Found {len(results)} match(es) for '{query}':", ""]
        for entry in results:
            lines.append(format_entry_detail(entry, verbose=False))
            lines.append("")

        return ToolResult(output="\n".join(lines))


clipboard_search_factory = ClipboardSearchSkill.factory
