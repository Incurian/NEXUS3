from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from nexus3.mcp.client import MCPClient

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from nexus3.ide.discovery import IDEInfo


class DiffOutcome(Enum):
    """Result of an openDiff operation."""

    FILE_SAVED = "FILE_SAVED"
    DIFF_REJECTED = "DIFF_REJECTED"


@dataclass
class Diagnostic:
    """LSP diagnostic from IDE."""

    file_path: str
    line: int
    message: str
    severity: str  # "error", "warning", "info", "hint"
    source: str | None = None


@dataclass
class Selection:
    """Editor text selection."""

    file_path: str
    text: str
    start_line: int
    start_character: int
    end_line: int
    end_character: int


@dataclass
class EditorInfo:
    """Open editor tab info."""

    file_path: str
    is_active: bool = False
    is_dirty: bool = False
    language_id: str | None = None


def _extract_text(result: Any) -> str:
    """Extract text from MCPToolResult.content[0]["text"]."""
    if result.content:
        return result.content[0].get("text", "")
    return ""


class IDEConnection:
    """Typed async wrappers around MCPClient.call_tool()."""

    def __init__(self, client: MCPClient, ide_info: IDEInfo) -> None:
        self._client = client
        self.ide_info = ide_info

    async def open_diff(
        self,
        old_file_path: str,
        new_file_path: str,
        new_file_contents: str,
        tab_name: str,
    ) -> DiffOutcome:
        """Show diff in IDE. BLOCKS until user accepts/rejects."""
        result = await self._client.call_tool("openDiff", {
            "old_file_path": old_file_path,
            "new_file_path": new_file_path,
            "new_file_contents": new_file_contents,
            "tab_name": tab_name,
        })
        text = _extract_text(result)
        if "FILE_SAVED" in text:
            return DiffOutcome.FILE_SAVED
        return DiffOutcome.DIFF_REJECTED

    async def open_file(self, file_path: str, preview: bool = False) -> None:
        """Open a file in the IDE."""
        await self._client.call_tool("openFile", {"filePath": file_path, "preview": preview})

    async def get_diagnostics(self, uri: str | None = None) -> list[Diagnostic]:
        """Get LSP diagnostics from IDE."""
        args: dict[str, Any] = {}
        if uri:
            args["uri"] = uri
        result = await self._client.call_tool("getDiagnostics", args)
        text = _extract_text(result)
        if not text or text == "[]":
            return []
        items = json.loads(text)
        return [
            Diagnostic(
                file_path=d.get("filePath", ""),
                line=d.get("line", 0),
                message=d.get("message", ""),
                severity=d.get("severity", "info"),
                source=d.get("source"),
            )
            for d in items
        ]

    async def get_current_selection(self) -> Selection | None:
        """Get the current editor selection (only if editor has focus)."""
        result = await self._client.call_tool("getCurrentSelection", {})
        return self._parse_selection(result)

    async def get_latest_selection(self) -> Selection | None:
        """Get the latest selection (persists across focus changes)."""
        result = await self._client.call_tool("getLatestSelection", {})
        return self._parse_selection(result)

    async def get_open_editors(self) -> list[EditorInfo]:
        """Get list of open editor tabs."""
        result = await self._client.call_tool("getOpenEditors", {})
        text = _extract_text(result)
        if not text or text == "[]":
            return []
        items = json.loads(text)
        return [
            EditorInfo(
                file_path=e.get("filePath", ""),
                is_active=e.get("isActive", False),
                is_dirty=e.get("isDirty", False),
                language_id=e.get("languageId"),
            )
            for e in items
        ]

    async def get_workspace_folders(self) -> list[str]:
        """Get workspace folder paths."""
        result = await self._client.call_tool("getWorkspaceFolders", {})
        text = _extract_text(result)
        if not text or text == "[]":
            return []
        return json.loads(text)

    async def check_document_dirty(self, file_path: str) -> bool:
        """Check if a document has unsaved changes."""
        result = await self._client.call_tool("checkDocumentDirty", {"filePath": file_path})
        text = _extract_text(result)
        if not text:
            return False
        data = json.loads(text)
        return data.get("dirty", False)

    async def save_document(self, file_path: str) -> None:
        """Save a document in the IDE."""
        await self._client.call_tool("saveDocument", {"filePath": file_path})

    async def close_tab(self, tab_name: str) -> None:
        """Close a specific tab by name."""
        await self._client.call_tool("closeTab", {"tabName": tab_name})

    async def close_all_diff_tabs(self) -> None:
        """Close all NEXUS3 diff tabs."""
        await self._client.call_tool("closeAllDiffTabs", {})

    def _parse_selection(self, result: Any) -> Selection | None:
        """Parse selection from MCPToolResult."""
        text = _extract_text(result)
        if not text or text == "null":
            return None
        data = json.loads(text)
        return Selection(
            file_path=data.get("filePath", ""),
            text=data.get("text", ""),
            start_line=data.get("startLine", 0),
            start_character=data.get("startCharacter", 0),
            end_line=data.get("endLine", 0),
            end_character=data.get("endCharacter", 0),
        )

    @property
    def is_connected(self) -> bool:
        return self._client._transport.is_connected  # noqa: SLF001

    async def close(self) -> None:
        await self._client.close()
