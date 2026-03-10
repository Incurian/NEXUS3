"""Import skill for clipboard entries."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from nexus3.clipboard import ClipboardScope
from nexus3.core.errors import PathSecurityError
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory

if TYPE_CHECKING:
    pass


def _validate_import_data(data: Any) -> tuple[str, list[dict[str, Any]]]:
    """Validate clipboard import JSON and return normalized entries."""
    if not isinstance(data, dict):
        raise ValueError("Import file must contain a top-level JSON object")

    version = data.get("version", "unknown")
    if version != "1.0":
        raise ValueError(f"Unsupported export format version: {version}")

    raw_entries = data.get("entries", [])
    if not isinstance(raw_entries, list):
        raise ValueError("'entries' must be a JSON array")

    entries: list[dict[str, Any]] = []
    for index, raw_entry in enumerate(raw_entries, start=1):
        if not isinstance(raw_entry, dict):
            raise ValueError(f"Entry {index} must be a JSON object")

        key = raw_entry.get("key")
        if not isinstance(key, str) or not key:
            raise ValueError(f"Entry {index} has invalid 'key'")

        content = raw_entry.get("content", "")
        if not isinstance(content, str):
            raise ValueError(f"Entry {index} has non-string 'content'")

        short_description = raw_entry.get("short_description")
        if short_description is not None and not isinstance(short_description, str):
            raise ValueError(f"Entry {index} has non-string 'short_description'")

        tags = raw_entry.get("tags", [])
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            raise ValueError(f"Entry {index} has invalid 'tags'")

        entries.append(
            {
                "key": key,
                "content": content,
                "short_description": short_description,
                "tags": tags,
            }
        )

    return version, entries


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
                    "description": (
                        "If true, show what would be imported without actually importing"
                    ),
                },
            },
            "required": ["path"],
            "additionalProperties": False,
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

        try:
            _, entries = _validate_import_data(data)
        except ValueError as e:
            return ToolResult(error=f"Invalid import format: {e}")

        if not entries:
            return ToolResult(output="No entries in export file")

        imported = 0
        skipped = 0
        overwritten = 0
        errors = []

        for entry_dict in entries:
            key = entry_dict["key"]
            content = entry_dict["content"]
            short_description = entry_dict["short_description"]
            tags = entry_dict["tags"]

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
