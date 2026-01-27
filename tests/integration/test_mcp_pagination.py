"""Integration tests for MCP client pagination support."""

import sys

import pytest

from nexus3.mcp import MCPClient, MCPServerConfig, MCPServerRegistry
from nexus3.mcp.transport import StdioTransport


class TestMCPPagination:
    """Test MCPClient handles cursor-based pagination correctly."""

    @pytest.mark.asyncio
    async def test_two_page_pagination(self) -> None:
        """Test listing tools across 2 pages."""
        # 5 tools with page size 3 = 2 pages (3+2)
        env = {"MCP_TOOL_COUNT": "5", "MCP_PAGE_SIZE": "3"}
        transport = StdioTransport(
            [sys.executable, "-m", "nexus3.mcp.test_server.paginating_server"],
            env=env,
        )
        async with MCPClient(transport) as client:
            tools = await client.list_tools()

            assert len(tools) == 5
            tool_names = {t.name for t in tools}
            assert tool_names == {"tool_1", "tool_2", "tool_3", "tool_4", "tool_5"}

    @pytest.mark.asyncio
    async def test_three_page_pagination(self) -> None:
        """Test listing tools across 3 pages."""
        # 7 tools with page size 3 = 3 pages (3+3+1)
        env = {"MCP_TOOL_COUNT": "7", "MCP_PAGE_SIZE": "3"}
        transport = StdioTransport(
            [sys.executable, "-m", "nexus3.mcp.test_server.paginating_server"],
            env=env,
        )
        async with MCPClient(transport) as client:
            tools = await client.list_tools()

            assert len(tools) == 7
            tool_names = {t.name for t in tools}
            expected = {f"tool_{i}" for i in range(1, 8)}
            assert tool_names == expected

    @pytest.mark.asyncio
    async def test_single_page_no_pagination(self) -> None:
        """Test when all tools fit in one page (no nextCursor)."""
        # 2 tools with page size 5 = 1 page, no nextCursor
        env = {"MCP_TOOL_COUNT": "2", "MCP_PAGE_SIZE": "5"}
        transport = StdioTransport(
            [sys.executable, "-m", "nexus3.mcp.test_server.paginating_server"],
            env=env,
        )
        async with MCPClient(transport) as client:
            tools = await client.list_tools()

            assert len(tools) == 2
            tool_names = {t.name for t in tools}
            assert tool_names == {"tool_1", "tool_2"}

    @pytest.mark.asyncio
    async def test_empty_tools_list(self) -> None:
        """Test server with no tools."""
        env = {"MCP_TOOL_COUNT": "0", "MCP_PAGE_SIZE": "2"}
        transport = StdioTransport(
            [sys.executable, "-m", "nexus3.mcp.test_server.paginating_server"],
            env=env,
        )
        async with MCPClient(transport) as client:
            tools = await client.list_tools()

            assert len(tools) == 0

    @pytest.mark.asyncio
    async def test_exact_page_boundary(self) -> None:
        """Test when tools count equals page size (no extra page)."""
        # 4 tools with page size 4 = exactly 1 page
        env = {"MCP_TOOL_COUNT": "4", "MCP_PAGE_SIZE": "4"}
        transport = StdioTransport(
            [sys.executable, "-m", "nexus3.mcp.test_server.paginating_server"],
            env=env,
        )
        async with MCPClient(transport) as client:
            tools = await client.list_tools()

            assert len(tools) == 4

    @pytest.mark.asyncio
    async def test_exact_multiple_boundary(self) -> None:
        """Test when tools count is exact multiple of page size."""
        # 6 tools with page size 3 = exactly 2 full pages (3+3)
        env = {"MCP_TOOL_COUNT": "6", "MCP_PAGE_SIZE": "3"}
        transport = StdioTransport(
            [sys.executable, "-m", "nexus3.mcp.test_server.paginating_server"],
            env=env,
        )
        async with MCPClient(transport) as client:
            tools = await client.list_tools()

            assert len(tools) == 6
            tool_names = {t.name for t in tools}
            expected = {f"tool_{i}" for i in range(1, 7)}
            assert tool_names == expected

    @pytest.mark.asyncio
    async def test_many_pages(self) -> None:
        """Test pagination with many small pages."""
        # 10 tools with page size 2 = 5 pages
        env = {"MCP_TOOL_COUNT": "10", "MCP_PAGE_SIZE": "2"}
        transport = StdioTransport(
            [sys.executable, "-m", "nexus3.mcp.test_server.paginating_server"],
            env=env,
        )
        async with MCPClient(transport) as client:
            tools = await client.list_tools()

            assert len(tools) == 10
            tool_names = {t.name for t in tools}
            expected = {f"tool_{i}" for i in range(1, 11)}
            assert tool_names == expected

    @pytest.mark.asyncio
    async def test_page_size_one(self) -> None:
        """Test with page size of 1 (one tool per page)."""
        # 3 tools with page size 1 = 3 pages
        env = {"MCP_TOOL_COUNT": "3", "MCP_PAGE_SIZE": "1"}
        transport = StdioTransport(
            [sys.executable, "-m", "nexus3.mcp.test_server.paginating_server"],
            env=env,
        )
        async with MCPClient(transport) as client:
            tools = await client.list_tools()

            assert len(tools) == 3
            tool_names = {t.name for t in tools}
            assert tool_names == {"tool_1", "tool_2", "tool_3"}

    @pytest.mark.asyncio
    async def test_registry_pagination(self) -> None:
        """Test registry handles pagination via get_all_skills()."""
        registry = MCPServerRegistry()

        config = MCPServerConfig(
            name="paginating",
            command=[sys.executable, "-m", "nexus3.mcp.test_server.paginating_server"],
            env={"MCP_TOOL_COUNT": "6", "MCP_PAGE_SIZE": "2"},
        )

        await registry.connect(config)
        skills = await registry.get_all_skills()

        # All 6 tools should be discovered across 3 pages
        assert len(skills) == 6

        await registry.close_all()

    @pytest.mark.asyncio
    async def test_tools_preserved_across_pages(self) -> None:
        """Test that tool properties are preserved correctly across pagination."""
        # Use 4 tools with page size 2 = 2 pages
        env = {"MCP_TOOL_COUNT": "4", "MCP_PAGE_SIZE": "2"}
        transport = StdioTransport(
            [sys.executable, "-m", "nexus3.mcp.test_server.paginating_server"],
            env=env,
        )
        async with MCPClient(transport) as client:
            tools = await client.list_tools()

            # Verify all tools have correct descriptions
            for tool in tools:
                # Name is tool_N, description is "Test tool number N"
                num = tool.name.split("_")[1]
                assert tool.description == f"Test tool number {num}"

                # Verify input schema is preserved
                assert "properties" in tool.input_schema
                assert "value" in tool.input_schema["properties"]
