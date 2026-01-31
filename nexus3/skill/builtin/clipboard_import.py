"""Import skill for clipboard entries."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nexus3.clipboard import ClipboardManager, ClipboardScope
from nexus3.core.errors import PathSecurityError
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory

if TYPE_CHECKING:
    from nexus3.skill.services import ServiceContainer


class ClipboardImportSkill(FileSkill):
    """Import clipboard entries from a JSON file."""

    @property
    def name(self) -> str:
        return "clipboard_import"

    @property
    def description(self) -> str:
        return "Import clipboard entries from a JSON export file."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the JSON export file",
                },
                "scope": {
                    "type": "string",
                    "enum": ["agent", "project", "system"],
                    "default": "agent",
                    "description": "Target scope for imported entries",
                },
                "conflict": {
                    "type": "string",
                    "enum": ["skip", "overwrite"],
                    "default": "skip",
                    "description": "How to handle existing keys: skip or overwrite",
                },
                "dry_run": {
                    "type": "boolean",
                    "default": True,
                    "description": "If true, show what would be imported without actually importing",
                },
            },
            "required": ["path"],
        }

    async def execute(
        self,
        path: str = "",
        scope: str = "agent",
        conflict: str = "skip",
        dry_run: bool = True,
        **kwargs: Any,
    ) -> ToolResult:
        # Validate input path
        try:
            input_path = self._validate_path(path)
        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))

        if not input_path.exists():
            return ToolResult(error=f"File not found: {input_path}")

        manager = self._services.get("clipboard_manager")
        if manager is None:
            return ToolResult(error="Clipboard service not available")

        # Parse target scope
        try:
            clip_scope = ClipboardScope(scope)
        except ValueError:
            return ToolResult(error=f"Invalid scope: {scope}")

        # Read and parse JSON
        try:
            file_content = await asyncio.to_thread(input_path.read_text, encoding="utf-8")
            data = json.loads(file_content)
        except json.JSONDecodeError as e:
            return ToolResult(error=f"Invalid JSON: {e}")
        except OSError as e:
            return ToolResult(error=f"Cannot read file: {e}")

        # Validate format
        if data.get("version") != "1.0":
            version = data.get("version", "unknown")
            return ToolResult(error=f"Unsupported export format version: {version}")

        entries = data.get("entries", [])
        if not entries:
            return ToolResult(output="No entries in export file")

        imported = 0
        skipped = 0
        overwritten = 0
        errors = []

        for entry_dict in entries:
            key = entry_dict.get("key")
            if not key:
                errors.append("Entry missing 'key' field")
                continue

            content = entry_dict.get("content", "")
            short_description = entry_dict.get("short_description")
            tags = entry_dict.get("tags", [])

            # Check if exists
            existing = manager.get(key, clip_scope)

            if existing:
                if conflict == "skip":
                    skipped += 1
                    continue
                elif conflict == "overwrite":
                    if not dry_run:
                        try:
                            manager.delete(key, clip_scope)
                        except (PermissionError, KeyError):
                            pass
                    overwritten += 1

            if not dry_run:
                try:
                    manager.copy(
                        key=key,
                        content=content,
                        scope=clip_scope,
                        short_description=short_description,
                        tags=tags if tags else None,
                    )
                except (PermissionError, ValueError) as e:
                    errors.append(f"Failed to import '{key}': {e}")
                    continue

            imported += 1

        # Build result message
        if dry_run:
            msg = f"Dry run: would import {imported} entries"
            if overwritten:
                msg += f", overwrite {overwritten}"
            if skipped:
                msg += f", skip {skipped} (existing)"
            msg += "\nSet dry_run=false to perform the import."
        else:
            msg = f"Imported {imported} entries to {scope} scope"
            if overwritten:
                msg += f" ({overwritten} overwritten)"
            if skipped:
                msg += f", skipped {skipped}"

        if errors:
            msg += f"\nErrors: {len(errors)}"
            for err in errors[:5]:  # Show first 5 errors
                msg += f"\n  - {err}"
            if len(errors) > 5:
                msg += f"\n  ... and {len(errors) - 5} more"

        return ToolResult(output=msg)


clipboard_import_factory = file_skill_factory(ClipboardImportSkill)
