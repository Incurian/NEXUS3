"""Integration tests for MCP client with test server."""

import asyncio
import sys

import pytest

from nexus3.mcp import (
    MCPClient,
    MCPServerConfig,
    MCPServerRegistry,
    MCPSkillAdapter,
    MCPTool,
    MCPToolResult,
)
from nexus3.mcp.transport import HTTPTransport, StdioTransport


@pytest.fixture
async def mcp_client():
    """Create MCP client connected to test server."""
    transport = StdioTransport([sys.executable, "-m", "nexus3.mcp.test_server"])
    async with MCPClient(transport) as client:
        yield client


class TestMCPClientIntegration:
    """Test MCP client with actual test server."""

    @pytest.mark.asyncio
    async def test_initialization(self, mcp_client: MCPClient) -> None:
        """Test client initializes and gets server info."""
        assert mcp_client.is_initialized
        assert mcp_client.server_info is not None
        assert mcp_client.server_info.name == "nexus3-test-server"
        assert mcp_client.server_info.version == "1.0.0"

    @pytest.mark.asyncio
    async def test_list_tools(self, mcp_client: MCPClient) -> None:
        """Test discovering tools from server."""
        tools = await mcp_client.list_tools()

        assert len(tools) == 4

        tool_names = {t.name for t in tools}
        assert tool_names == {"echo", "get_time", "add", "slow_operation"}

        # Check echo tool schema
        echo_tool = next(t for t in tools if t.name == "echo")
        assert echo_tool.description == "Echo back the input message"
        assert "message" in echo_tool.input_schema.get("properties", {})

    @pytest.mark.asyncio
    async def test_call_echo(self, mcp_client: MCPClient) -> None:
        """Test calling echo tool."""
        result = await mcp_client.call_tool("echo", {"message": "hello world"})

        assert isinstance(result, MCPToolResult)
        assert not result.is_error
        assert result.to_text() == "hello world"

    @pytest.mark.asyncio
    async def test_call_add(self, mcp_client: MCPClient) -> None:
        """Test calling add tool."""
        result = await mcp_client.call_tool("add", {"a": 10, "b": 32})

        assert not result.is_error
        assert result.to_text() == "42"

    @pytest.mark.asyncio
    async def test_call_get_time(self, mcp_client: MCPClient) -> None:
        """Test calling get_time tool."""
        result = await mcp_client.call_tool("get_time", {})

        assert not result.is_error
        # Should be an ISO timestamp
        text = result.to_text()
        assert "T" in text  # ISO format has T between date and time

    @pytest.mark.asyncio
    async def test_call_unknown_tool(self, mcp_client: MCPClient) -> None:
        """Test calling unknown tool returns error."""
        from nexus3.mcp import MCPError

        with pytest.raises(MCPError) as exc_info:
            await mcp_client.call_tool("nonexistent", {})

        # -32602 = Invalid params (tool name is a parameter to tools/call)
        assert exc_info.value.code == -32602
        assert "Unknown tool" in exc_info.value.message


class TestStdioTransport:
    """Test StdioTransport directly."""

    @pytest.mark.asyncio
    async def test_transport_connect_disconnect(self) -> None:
        """Test transport connection lifecycle."""
        transport = StdioTransport([sys.executable, "-m", "nexus3.mcp.test_server"])

        await transport.connect()
        assert transport.is_connected

        await transport.close()
        assert not transport.is_connected

    @pytest.mark.asyncio
    async def test_transport_command_not_found(self) -> None:
        """Test transport handles missing command."""
        from nexus3.mcp.transport import MCPTransportError

        transport = StdioTransport(["nonexistent_command_xyz"])

        with pytest.raises(MCPTransportError) as exc_info:
            await transport.connect()

        assert "not found" in exc_info.value.message


class TestMCPServerRegistry:
    """Test MCP server registry."""

    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self) -> None:
        """Test connecting and disconnecting servers."""
        registry = MCPServerRegistry()

        config = MCPServerConfig(
            name="test",
            command=[sys.executable, "-m", "nexus3.mcp.test_server"],
        )

        # Connect
        server = await registry.connect(config)
        assert server.config.name == "test"
        assert server.client.is_initialized
        assert len(server.skills) == 4
        assert len(registry) == 1

        # Disconnect
        result = await registry.disconnect("test")
        assert result is True
        assert len(registry) == 0

        # Disconnect non-existent
        result = await registry.disconnect("test")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_all_skills(self) -> None:
        """Test getting all skills from registry."""
        registry = MCPServerRegistry()

        config = MCPServerConfig(
            name="test",
            command=[sys.executable, "-m", "nexus3.mcp.test_server"],
        )

        await registry.connect(config)
        skills = await registry.get_all_skills()

        assert len(skills) == 4
        skill_names = {s.name for s in skills}
        assert skill_names == {"mcp_test_echo", "mcp_test_get_time", "mcp_test_add", "mcp_test_slow_operation"}

        await registry.close_all()

    @pytest.mark.asyncio
    async def test_agent_visibility(self) -> None:
        """Test connection visibility per agent."""
        registry = MCPServerRegistry()

        config = MCPServerConfig(
            name="private",
            command=[sys.executable, "-m", "nexus3.mcp.test_server"],
        )

        # Connect as agent "main" with private visibility
        await registry.connect(config, owner_agent_id="main", shared=False)

        # Owner can see it
        assert registry.get("private", agent_id="main") is not None
        assert len(registry.list_servers(agent_id="main")) == 1
        assert len(await registry.get_all_skills(agent_id="main")) == 4

        # Other agent cannot see it
        assert registry.get("private", agent_id="worker") is None
        assert len(registry.list_servers(agent_id="worker")) == 0
        assert len(await registry.get_all_skills(agent_id="worker")) == 0

        await registry.close_all()

    @pytest.mark.asyncio
    async def test_shared_visibility(self) -> None:
        """Test shared connection visibility."""
        registry = MCPServerRegistry()

        config = MCPServerConfig(
            name="shared",
            command=[sys.executable, "-m", "nexus3.mcp.test_server"],
        )

        # Connect as agent "main" with shared visibility
        await registry.connect(config, owner_agent_id="main", shared=True)

        # Owner can see it
        assert registry.get("shared", agent_id="main") is not None

        # Other agent can also see it (shared)
        assert registry.get("shared", agent_id="worker") is not None
        assert len(registry.list_servers(agent_id="worker")) == 1
        assert len(await registry.get_all_skills(agent_id="worker")) == 4

        await registry.close_all()

    @pytest.mark.asyncio
    async def test_close_all(self) -> None:
        """Test closing all servers."""
        registry = MCPServerRegistry()

        config = MCPServerConfig(
            name="test",
            command=[sys.executable, "-m", "nexus3.mcp.test_server"],
        )

        await registry.connect(config)
        assert len(registry) == 1

        await registry.close_all()
        assert len(registry) == 0


class TestMCPSkillAdapter:
    """Test MCP skill adapter."""

    @pytest.mark.asyncio
    async def test_skill_properties(self) -> None:
        """Test skill adapter exposes correct properties."""
        registry = MCPServerRegistry()

        config = MCPServerConfig(
            name="test",
            command=[sys.executable, "-m", "nexus3.mcp.test_server"],
        )

        server = await registry.connect(config)
        echo_skill = next(s for s in server.skills if s.original_name == "echo")

        assert echo_skill.name == "mcp_test_echo"
        assert echo_skill.server_name == "test"
        assert echo_skill.original_name == "echo"
        assert echo_skill.description == "Echo back the input message"
        assert "message" in echo_skill.parameters.get("properties", {})

        await registry.close_all()

    @pytest.mark.asyncio
    async def test_skill_execute(self) -> None:
        """Test skill adapter executes tool."""
        registry = MCPServerRegistry()

        config = MCPServerConfig(
            name="test",
            command=[sys.executable, "-m", "nexus3.mcp.test_server"],
        )

        server = await registry.connect(config)
        add_skill = next(s for s in server.skills if s.original_name == "add")

        result = await add_skill.execute(a=5, b=7)

        assert result.success
        assert result.output == "12"

        await registry.close_all()


# --- HTTP Transport Tests ---

@pytest.fixture
async def http_server():
    """Start HTTP test server for tests."""
    from aiohttp import web
    from nexus3.mcp.test_server.http_server import handle_request

    async def handle_post(request: web.Request) -> web.Response:
        body = await request.json()
        response = handle_request(body)
        if response is None:
            return web.Response(status=204)
        return web.json_response(response)

    app = web.Application()
    app.router.add_post("/", handle_post)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 9999)
    await site.start()

    yield "http://127.0.0.1:9999"

    await runner.cleanup()


@pytest.fixture
async def http_mcp_client(http_server: str):
    """Create MCP client connected to HTTP test server."""
    transport = HTTPTransport(http_server)
    async with MCPClient(transport) as client:
        yield client


class TestHTTPTransport:
    """Test HTTP transport with HTTP test server."""

    @pytest.mark.asyncio
    async def test_http_initialization(self, http_mcp_client: MCPClient) -> None:
        """Test HTTP client initializes and gets server info."""
        assert http_mcp_client.is_initialized
        assert http_mcp_client.server_info is not None
        assert http_mcp_client.server_info.name == "nexus3-http-test-server"

    @pytest.mark.asyncio
    async def test_http_list_tools(self, http_mcp_client: MCPClient) -> None:
        """Test HTTP client discovers tools."""
        tools = await http_mcp_client.list_tools()

        assert len(tools) == 4
        tool_names = {t.name for t in tools}
        assert tool_names == {"echo", "get_time", "add", "slow_operation"}

    @pytest.mark.asyncio
    async def test_http_call_echo(self, http_mcp_client: MCPClient) -> None:
        """Test HTTP client calls echo tool."""
        result = await http_mcp_client.call_tool("echo", {"message": "http test"})

        assert not result.is_error
        assert result.to_text() == "http test"

    @pytest.mark.asyncio
    async def test_http_call_add(self, http_mcp_client: MCPClient) -> None:
        """Test HTTP client calls add tool."""
        result = await http_mcp_client.call_tool("add", {"a": 100, "b": 23})

        assert not result.is_error
        assert result.to_text() == "123"

    @pytest.mark.asyncio
    async def test_http_transport_connect_disconnect(self) -> None:
        """Test HTTP transport connection lifecycle."""
        transport = HTTPTransport("http://127.0.0.1:9999")

        await transport.connect()
        assert transport.is_connected

        await transport.close()
        assert not transport.is_connected


class TestRegistryWithHTTP:
    """Test registry with HTTP transport."""

    @pytest.mark.asyncio
    async def test_registry_auto_selects_http(self, http_server: str) -> None:
        """Test registry uses HTTP transport when url is specified."""
        registry = MCPServerRegistry()

        config = MCPServerConfig(
            name="http-test",
            url=http_server,
        )

        server = await registry.connect(config)
        assert server.config.name == "http-test"
        assert len(server.skills) == 4

        await registry.close_all()

    @pytest.mark.asyncio
    async def test_registry_http_skill_execute(self, http_server: str) -> None:
        """Test executing skill via HTTP transport."""
        registry = MCPServerRegistry()

        config = MCPServerConfig(
            name="http-test",
            url=http_server,
        )

        server = await registry.connect(config)
        echo_skill = next(s for s in server.skills if s.original_name == "echo")

        result = await echo_skill.execute(message="via http")

        assert result.success
        assert result.output == "via http"

        await registry.close_all()
