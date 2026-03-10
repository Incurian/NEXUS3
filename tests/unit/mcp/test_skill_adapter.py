"""Focused tests for MCP skill adapter sanitization boundaries."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus3.mcp.protocol import MCPTool, MCPToolResult
from nexus3.mcp.skill_adapter import MCPSkillAdapter


class TestMCPSkillAdapterSanitization:
    """Validate adapter output/error payload sanitization."""

    @pytest.mark.asyncio
    async def test_execute_sanitizes_success_output_payload(self) -> None:
        tool = MCPTool(name="echo", description="Echo", input_schema={})
        mcp_result = MCPToolResult(
            content=[{"type": "text", "text": "\x1b[31m[bold]done[/bold]\x1b[0m"}],
            is_error=False,
        )

        mock_client = MagicMock()
        mock_client.call_tool = AsyncMock(return_value=mcp_result)

        adapter = MCPSkillAdapter(mock_client, tool, "test-server")
        result = await adapter.execute()

        mock_client.call_tool.assert_awaited_once_with("echo", {})
        assert result.error == ""
        assert result.output == r"\[bold]done\[/bold]"
        assert "\x1b[" not in result.output

    @pytest.mark.asyncio
    async def test_empty_input_schema_treats_tool_as_no_arg_contract(self) -> None:
        tool = MCPTool(name="echo", description="Echo", input_schema={})
        mcp_result = MCPToolResult(
            content=[{"type": "text", "text": "ok"}],
            is_error=False,
        )

        mock_client = MagicMock()
        mock_client.call_tool = AsyncMock(return_value=mcp_result)

        adapter = MCPSkillAdapter(mock_client, tool, "test-server")
        result = await adapter.execute(unexpected="value")

        mock_client.call_tool.assert_awaited_once_with("echo", {})
        assert result.success

    @pytest.mark.asyncio
    async def test_execute_sanitizes_error_payload(self) -> None:
        tool = MCPTool(name="echo", description="Echo", input_schema={})
        mcp_result = MCPToolResult(
            content=[{"type": "text", "text": "\x1b[33m[red]boom[/red]\x1b[0m"}],
            is_error=True,
        )

        mock_client = MagicMock()
        mock_client.call_tool = AsyncMock(return_value=mcp_result)

        adapter = MCPSkillAdapter(mock_client, tool, "test-server")
        result = await adapter.execute()

        mock_client.call_tool.assert_awaited_once_with("echo", {})
        assert result.output == ""
        assert result.error == r"\[red]boom\[/red]"
        assert "\x1b[" not in result.error

    @pytest.mark.asyncio
    async def test_execute_preserves_open_ended_validated_arguments(self) -> None:
        tool = MCPTool(
            name="echo",
            description="Echo",
            input_schema={
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
        )
        mcp_result = MCPToolResult(content=[{"type": "text", "text": "ok"}], is_error=False)

        mock_client = MagicMock()
        mock_client.call_tool = AsyncMock(return_value=mcp_result)

        adapter = MCPSkillAdapter(mock_client, tool, "test-server")
        result = await adapter.execute(dynamic_key="value")

        mock_client.call_tool.assert_awaited_once_with("echo", {"dynamic_key": "value"})
        assert result.success

    @pytest.mark.asyncio
    async def test_execute_returns_tool_error_for_invalid_arguments(self) -> None:
        tool = MCPTool(
            name="echo",
            description="Echo",
            input_schema={
                "type": "object",
                "properties": {"count": {"type": "integer"}},
                "required": ["count"],
                "additionalProperties": False,
            },
        )

        mock_client = MagicMock()
        mock_client.call_tool = AsyncMock()

        adapter = MCPSkillAdapter(mock_client, tool, "test-server")
        result = await adapter.execute(count="not-an-int")

        assert result.output == ""
        assert "Invalid parameters for mcp_test-server_echo" in result.error
        assert "integer" in result.error
        mock_client.call_tool.assert_not_awaited()
