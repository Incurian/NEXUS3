from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import pytest

from nexus3.ide.connection import (
    DiffOutcome,
    Diagnostic,
    EditorInfo,
    IDEConnection,
    Selection,
)
from nexus3.ide.discovery import IDEInfo


@dataclass
class FakeMCPToolResult:
    content: list[dict[str, Any]]
    is_error: bool = False


def _make_ide_info() -> IDEInfo:
    from pathlib import Path

    return IDEInfo(
        pid=1234,
        workspace_folders=["/test"],
        ide_name="Test IDE",
        transport="ws",
        auth_token="token",
        port=9999,
        lock_path=Path("/tmp/9999.lock"),
    )


def _make_connection(call_tool_return: Any = None) -> tuple[IDEConnection, AsyncMock]:
    client = AsyncMock()
    client.call_tool = AsyncMock(return_value=call_tool_return)
    # For is_connected property
    client._transport = AsyncMock()
    client._transport.is_connected = True
    conn = IDEConnection(client, _make_ide_info())
    return conn, client


class TestOpenDiff:
    @pytest.mark.asyncio
    async def test_file_saved(self) -> None:
        result = FakeMCPToolResult(content=[{"type": "text", "text": "FILE_SAVED"}])
        conn, client = _make_connection(result)

        outcome = await conn.open_diff("/old.py", "/new.py", "content", "test")
        assert outcome == DiffOutcome.FILE_SAVED
        client.call_tool.assert_called_once_with("openDiff", {
            "old_file_path": "/old.py",
            "new_file_path": "/new.py",
            "new_file_contents": "content",
            "tab_name": "test",
        })

    @pytest.mark.asyncio
    async def test_diff_rejected(self) -> None:
        result = FakeMCPToolResult(content=[{"type": "text", "text": "DIFF_REJECTED"}])
        conn, _ = _make_connection(result)

        outcome = await conn.open_diff("/old.py", "/new.py", "content", "test")
        assert outcome == DiffOutcome.DIFF_REJECTED

    @pytest.mark.asyncio
    async def test_empty_content_returns_rejected(self) -> None:
        result = FakeMCPToolResult(content=[])
        conn, _ = _make_connection(result)

        outcome = await conn.open_diff("/old.py", "/new.py", "content", "test")
        assert outcome == DiffOutcome.DIFF_REJECTED


class TestGetDiagnostics:
    @pytest.mark.asyncio
    async def test_parse_diagnostics(self) -> None:
        diag_json = '[{"filePath":"/a.py","line":10,"message":"err","severity":"error","source":"pylint"}]'
        result = FakeMCPToolResult(content=[{"type": "text", "text": diag_json}])
        conn, _ = _make_connection(result)

        diags = await conn.get_diagnostics()
        assert len(diags) == 1
        assert diags[0].file_path == "/a.py"
        assert diags[0].line == 10
        assert diags[0].severity == "error"
        assert diags[0].source == "pylint"

    @pytest.mark.asyncio
    async def test_empty_diagnostics(self) -> None:
        result = FakeMCPToolResult(content=[{"type": "text", "text": "[]"}])
        conn, _ = _make_connection(result)

        diags = await conn.get_diagnostics()
        assert diags == []

    @pytest.mark.asyncio
    async def test_diagnostics_with_uri(self) -> None:
        result = FakeMCPToolResult(content=[{"type": "text", "text": "[]"}])
        conn, client = _make_connection(result)

        await conn.get_diagnostics(uri="file:///a.py")
        client.call_tool.assert_called_once_with("getDiagnostics", {"uri": "file:///a.py"})


class TestGetSelection:
    @pytest.mark.asyncio
    async def test_parse_selection(self) -> None:
        sel_json = '{"filePath":"/a.py","text":"hello","startLine":1,"startCharacter":0,"endLine":1,"endCharacter":5}'
        result = FakeMCPToolResult(content=[{"type": "text", "text": sel_json}])
        conn, _ = _make_connection(result)

        sel = await conn.get_current_selection()
        assert sel is not None
        assert sel.file_path == "/a.py"
        assert sel.text == "hello"
        assert sel.start_line == 1

    @pytest.mark.asyncio
    async def test_null_selection(self) -> None:
        result = FakeMCPToolResult(content=[{"type": "text", "text": "null"}])
        conn, _ = _make_connection(result)

        sel = await conn.get_latest_selection()
        assert sel is None


class TestGetOpenEditors:
    @pytest.mark.asyncio
    async def test_parse_editors(self) -> None:
        editors_json = '[{"filePath":"/a.py","isActive":true,"isDirty":false,"languageId":"python"}]'
        result = FakeMCPToolResult(content=[{"type": "text", "text": editors_json}])
        conn, _ = _make_connection(result)

        editors = await conn.get_open_editors()
        assert len(editors) == 1
        assert editors[0].file_path == "/a.py"
        assert editors[0].is_active is True
        assert editors[0].language_id == "python"


class TestGetWorkspaceFolders:
    @pytest.mark.asyncio
    async def test_parse_folders(self) -> None:
        result = FakeMCPToolResult(content=[{"type": "text", "text": '["/home/user/project"]'}])
        conn, _ = _make_connection(result)

        folders = await conn.get_workspace_folders()
        assert folders == ["/home/user/project"]


class TestCheckDocumentDirty:
    @pytest.mark.asyncio
    async def test_dirty_true(self) -> None:
        result = FakeMCPToolResult(content=[{"type": "text", "text": '{"dirty":true}'}])
        conn, _ = _make_connection(result)

        assert await conn.check_document_dirty("/a.py") is True

    @pytest.mark.asyncio
    async def test_dirty_false(self) -> None:
        result = FakeMCPToolResult(content=[{"type": "text", "text": '{"dirty":false}'}])
        conn, _ = _make_connection(result)

        assert await conn.check_document_dirty("/a.py") is False


class TestIsConnected:
    def test_connected(self) -> None:
        conn, _ = _make_connection()
        assert conn.is_connected is True
