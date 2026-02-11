"""Export skill for clipboard entries."""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import datetime
from typing import TYPE_CHECKING, Any

from nexus3.clipboard import ClipboardScope
from nexus3.core.errors import PathSecurityError
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory

if TYPE_CHECKING:
    pass


class ClipboardExportSkill(FileSkill):
    """Export clipboard entries to a JSON file."""

    @property
    def name(self) -> str:
        return "clipboard_export"

    @property
    def description(self) -> str:
        return "Export clipboard entries to a JSON file for backup or sharing."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Output file path for the JSON export",
                },
                "scope": {
                    "type": "string",
                    "enum": ["agent", "project", "system", "all"],
                    "default": "all",
                    "description": "Scope to export (all = all accessible scopes)",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Only export entries with ALL of these tags",
                },
            },
            "required": ["path"],
        }

    async def execute(
        self,
        path: str = "",
        scope: str = "all",
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        # Validate output path
        try:
            output_path = self._validate_path(path)
        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))

        manager = self._services.get("clipboard_manager")
        if manager is None:
            return ToolResult(error="Clipboard service not available")

        # Parse scope
        clip_scope: ClipboardScope | None = None
        if scope != "all":
            try:
                clip_scope = ClipboardScope(scope)
            except ValueError:
                return ToolResult(error=f"Invalid scope: {scope}")

        # Get entries
        try:
            entries = manager.list_entries(clip_scope)
        except PermissionError as e:
            return ToolResult(error=str(e))

        # Filter by tags if specified
        if tags:
            entries = [e for e in entries if all(t in e.tags for t in tags)]

        if not entries:
            return ToolResult(output="No entries to export")

        # Convert to exportable format
        export_data = {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "entry_count": len(entries),
            "entries": [],
        }

        for entry in entries:
            entry_dict = asdict(entry)
            # Convert scope enum to string
            entry_dict["scope"] = entry.scope.value
            export_data["entries"].append(entry_dict)

        # Write to file
        json_content = json.dumps(export_data, indent=2, ensure_ascii=False)
        try:
            await asyncio.to_thread(output_path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(output_path.write_text, json_content, encoding="utf-8")
        except OSError as e:
            return ToolResult(error=f"Cannot write export file: {e}")

        return ToolResult(output=f"Exported {len(entries)} entries to {output_path}")


clipboard_export_factory = file_skill_factory(ClipboardExportSkill)
