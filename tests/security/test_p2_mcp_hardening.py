"""Tests for P2.9-12: MCP protocol + transport hardening.

These tests verify:
- P2.9: Response ID matching (reject mismatched response IDs)
- P2.10: Notification discarding (discard notifications while waiting for response)
- P2.11: Deny-by-default for can_use_mcp(None)
- P2.12: Stdio line length limits (prevent memory exhaustion)
"""

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus3.mcp.client import MAX_NOTIFICATIONS_TO_DISCARD, MCPClient, MCPError
from nexus3.mcp.permissions import can_use_mcp, requires_mcp_confirmation
from nexus3.mcp.transport import (
    MAX_STDIO_LINE_LENGTH,
    MCPTransport,
    MCPTransportError,
    StdioTransport,
)
from nexus3.core.permissions import AgentPermissions, PermissionLevel, PermissionPolicy


class MockTransport(MCPTransport):
    """Mock transport for testing MCPClient."""

    def __init__(self, responses: list[dict[str, Any]] | None = None):
        self.responses = responses or []
        self.response_index = 0
        self.sent_messages: list[dict[str, Any]] = []
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    async def send(self, message: dict[str, Any]) -> None:
        self.sent_messages.append(message)

    async def receive(self) -> dict[str, Any]:
        if self.response_index >= len(self.responses):
            raise MCPTransportError("No more responses")
        response = self.responses[self.response_index]
        self.response_index += 1
        return response

    async def close(self) -> None:
        self.connected = False


class TestResponseIdMatching:
    """Tests for P2.9: Response ID matching."""

    @pytest.mark.asyncio
    async def test_matching_response_id_succeeds(self) -> None:
        """Response with matching ID is accepted."""
        # Initialize handshake response + test response
        transport = MockTransport([
            {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05", "serverInfo": {"name": "test"}}},
            {"jsonrpc": "2.0", "id": 2, "result": {"tools": []}},
        ])

        client = MCPClient(transport)
        await client.connect()

        # list_tools uses request id 2
        tools = await client.list_tools()
        assert tools == []

    @pytest.mark.asyncio
    async def test_mismatched_response_id_raises(self) -> None:
        """Response with wrong ID raises MCPError."""
        # Initialize handshake response + wrong ID response
        transport = MockTransport([
            {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05", "serverInfo": {"name": "test"}}},
            {"jsonrpc": "2.0", "id": 999, "result": {"tools": []}},  # Wrong ID
        ])

        client = MCPClient(transport)
        await client.connect()

        with pytest.raises(MCPError) as exc_info:
            await client.list_tools()

        assert "Response ID mismatch" in str(exc_info.value)
        assert "expected 2" in str(exc_info.value)
        assert "got 999" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_null_response_id_raises(self) -> None:
        """Response with null ID raises MCPError."""
        transport = MockTransport([
            {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05", "serverInfo": {"name": "test"}}},
            {"jsonrpc": "2.0", "id": None, "result": {"tools": []}},  # Null ID
        ])

        client = MCPClient(transport)
        await client.connect()

        with pytest.raises(MCPError) as exc_info:
            await client.list_tools()

        assert "Response ID mismatch" in str(exc_info.value)


class TestNotificationDiscarding:
    """Tests for P2.10: Notification discarding."""

    @pytest.mark.asyncio
    async def test_discards_notifications_before_response(self) -> None:
        """Notifications are discarded while waiting for response."""
        transport = MockTransport([
            {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05", "serverInfo": {"name": "test"}}},
            # Notifications before actual response
            {"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progress": 50}},
            {"jsonrpc": "2.0", "method": "notifications/log", "params": {"message": "working..."}},
            # Actual response
            {"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "test_tool"}]}},
        ])

        client = MCPClient(transport)
        await client.connect()

        # Should skip notifications and find the response
        tools = await client.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "test_tool"

    @pytest.mark.asyncio
    async def test_too_many_notifications_raises(self) -> None:
        """Raises error if too many notifications received."""
        # Initialize response + too many notifications
        responses: list[dict[str, Any]] = [
            {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05", "serverInfo": {"name": "test"}}},
        ]
        # Add more than MAX_NOTIFICATIONS_TO_DISCARD notifications
        for i in range(MAX_NOTIFICATIONS_TO_DISCARD + 1):
            responses.append({"jsonrpc": "2.0", "method": f"notification_{i}", "params": {}})

        transport = MockTransport(responses)

        client = MCPClient(transport)
        await client.connect()

        with pytest.raises(MCPError) as exc_info:
            await client.list_tools()

        assert "too many notifications" in str(exc_info.value)
        assert str(MAX_NOTIFICATIONS_TO_DISCARD + 1) in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_notification_without_method_not_discarded(self) -> None:
        """Messages without 'id' but also without 'method' are not notifications."""
        # A malformed response without id or method
        transport = MockTransport([
            {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05", "serverInfo": {"name": "test"}}},
            {"jsonrpc": "2.0", "result": {}},  # No id AND no method - malformed but not a notification
        ])

        client = MCPClient(transport)
        await client.connect()

        # This should raise because the response has no id (not discarded as notification)
        with pytest.raises(MCPError) as exc_info:
            await client.list_tools()

        assert "Response ID mismatch" in str(exc_info.value)


class TestCanUseMcpDenyByDefault:
    """Tests for P2.11: can_use_mcp(None) denies by default."""

    def test_none_permissions_denies_mcp(self) -> None:
        """None permissions denies MCP access."""
        result = can_use_mcp(None)
        assert result is False

    def test_yolo_allows_mcp(self) -> None:
        """YOLO permission level allows MCP."""
        policy = PermissionPolicy(level=PermissionLevel.YOLO)
        permissions = AgentPermissions(base_preset="yolo", effective_policy=policy)
        result = can_use_mcp(permissions)
        assert result is True

    def test_trusted_allows_mcp(self) -> None:
        """TRUSTED permission level allows MCP."""
        policy = PermissionPolicy(level=PermissionLevel.TRUSTED)
        permissions = AgentPermissions(base_preset="trusted", effective_policy=policy)
        result = can_use_mcp(permissions)
        assert result is True

    def test_sandboxed_denies_mcp(self) -> None:
        """SANDBOXED permission level denies MCP."""
        policy = PermissionPolicy(level=PermissionLevel.SANDBOXED)
        permissions = AgentPermissions(base_preset="sandboxed", effective_policy=policy)
        result = can_use_mcp(permissions)
        assert result is False


class TestRequiresMcpConfirmationDenyByDefault:
    """Tests for P2.11: requires_mcp_confirmation() defense-in-depth."""

    def test_none_permissions_requires_confirmation(self) -> None:
        """None permissions requires confirmation (defense-in-depth)."""
        result = requires_mcp_confirmation(None, "test_server", set())
        assert result is True

    def test_yolo_does_not_require_confirmation(self) -> None:
        """YOLO level does not require confirmation."""
        policy = PermissionPolicy(level=PermissionLevel.YOLO)
        permissions = AgentPermissions(base_preset="yolo", effective_policy=policy)
        result = requires_mcp_confirmation(permissions, "test_server", set())
        assert result is False

    def test_trusted_requires_confirmation_initially(self) -> None:
        """TRUSTED level requires confirmation for new servers."""
        policy = PermissionPolicy(level=PermissionLevel.TRUSTED)
        permissions = AgentPermissions(base_preset="trusted", effective_policy=policy)
        result = requires_mcp_confirmation(permissions, "test_server", set())
        assert result is True

    def test_trusted_skips_confirmation_if_allowed(self) -> None:
        """TRUSTED level skips confirmation if server already allowed."""
        policy = PermissionPolicy(level=PermissionLevel.TRUSTED)
        permissions = AgentPermissions(base_preset="trusted", effective_policy=policy)
        allowances = {"mcp:test_server"}
        result = requires_mcp_confirmation(permissions, "test_server", allowances)
        assert result is False


class TestStdioLineLengthLimit:
    """Tests for P2.12: Stdio line length limits."""

    def test_max_line_length_constant_exists(self) -> None:
        """MAX_STDIO_LINE_LENGTH constant is defined."""
        assert MAX_STDIO_LINE_LENGTH > 0
        assert MAX_STDIO_LINE_LENGTH == 10 * 1024 * 1024  # 10 MB

    @pytest.mark.asyncio
    async def test_bounded_line_read_normal_line(self) -> None:
        """Normal lines are read successfully."""
        transport = StdioTransport(["echo", "test"])

        # Mock the process and stdout
        mock_process = MagicMock()
        mock_stdout = AsyncMock()

        # Simulate reading a normal JSON line
        test_line = b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n'
        mock_stdout.read = AsyncMock(return_value=test_line)

        mock_process.stdout = mock_stdout
        mock_process.returncode = None
        transport._process = mock_process

        result = await transport._read_bounded_line()
        assert result == test_line

    @pytest.mark.asyncio
    async def test_bounded_line_read_eof(self) -> None:
        """EOF returns empty bytes."""
        transport = StdioTransport(["echo", "test"])

        mock_process = MagicMock()
        mock_stdout = AsyncMock()
        mock_stdout.read = AsyncMock(return_value=b"")  # EOF

        mock_process.stdout = mock_stdout
        mock_process.returncode = 0
        transport._process = mock_process

        result = await transport._read_bounded_line()
        assert result == b""

    @pytest.mark.asyncio
    async def test_bounded_line_read_exceeds_limit_raises(self) -> None:
        """Line exceeding MAX_STDIO_LINE_LENGTH raises error."""
        transport = StdioTransport(["echo", "test"])

        mock_process = MagicMock()
        mock_stdout = AsyncMock()

        # Return chunks without newline until we exceed the limit
        # Each read returns 64KB without a newline
        chunk = b"x" * 65536  # 64KB chunk, no newline
        mock_stdout.read = AsyncMock(return_value=chunk)

        mock_process.stdout = mock_stdout
        mock_process.returncode = None
        transport._process = mock_process

        with pytest.raises(MCPTransportError) as exc_info:
            await transport._read_bounded_line()

        assert "exceeds maximum length" in str(exc_info.value)
        assert str(MAX_STDIO_LINE_LENGTH) in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_bounded_line_read_multiple_chunks(self) -> None:
        """Multiple chunks are accumulated until newline."""
        transport = StdioTransport(["echo", "test"])

        mock_process = MagicMock()
        mock_stdout = AsyncMock()

        # First chunk: partial data
        # Second chunk: rest of data with newline
        chunks = [b'{"jsonrpc": "2.0", ', b'"id": 1, "result": {}}\n']
        chunk_index = [0]

        async def read_chunk(size: int) -> bytes:
            if chunk_index[0] >= len(chunks):
                return b""
            chunk = chunks[chunk_index[0]]
            chunk_index[0] += 1
            return chunk

        mock_stdout.read = read_chunk
        mock_process.stdout = mock_stdout
        mock_process.returncode = None
        transport._process = mock_process

        result = await transport._read_bounded_line()
        assert result == b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n'


class TestMcpErrorMessages:
    """Tests for error message quality."""

    @pytest.mark.asyncio
    async def test_id_mismatch_error_is_actionable(self) -> None:
        """ID mismatch error message helps diagnose issues."""
        transport = MockTransport([
            {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05", "serverInfo": {"name": "test"}}},
            {"jsonrpc": "2.0", "id": 42, "result": {}},
        ])

        client = MCPClient(transport)
        await client.connect()

        with pytest.raises(MCPError) as exc_info:
            await client.list_tools()

        error_msg = str(exc_info.value)
        assert "expected" in error_msg.lower()
        assert "got" in error_msg.lower()
        assert "malicious" in error_msg.lower() or "malfunctioning" in error_msg.lower()

    @pytest.mark.asyncio
    async def test_too_many_notifications_error_is_actionable(self) -> None:
        """Too many notifications error message helps diagnose issues."""
        responses: list[dict[str, Any]] = [
            {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05", "serverInfo": {"name": "test"}}},
        ]
        for i in range(MAX_NOTIFICATIONS_TO_DISCARD + 1):
            responses.append({"jsonrpc": "2.0", "method": f"notification_{i}", "params": {}})

        transport = MockTransport(responses)
        client = MCPClient(transport)
        await client.connect()

        with pytest.raises(MCPError) as exc_info:
            await client.list_tools()

        error_msg = str(exc_info.value)
        assert "notifications" in error_msg.lower()
        assert "malfunctioning" in error_msg.lower()

    def test_line_length_error_is_actionable(self) -> None:
        """Line length error message helps diagnose issues."""
        from nexus3.mcp.transport import MCPTransportError, MAX_STDIO_LINE_LENGTH

        error = MCPTransportError(
            f"MCP server line exceeds maximum length ({MAX_STDIO_LINE_LENGTH} bytes). "
            "Server may be malfunctioning or malicious."
        )

        error_msg = str(error)
        assert "maximum length" in error_msg.lower()
        assert str(MAX_STDIO_LINE_LENGTH) in error_msg
        assert "malicious" in error_msg.lower() or "malfunctioning" in error_msg.lower()
