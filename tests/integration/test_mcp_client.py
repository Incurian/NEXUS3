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


class TestMCPUtilities:
    """Test MCP utility operations."""

    @pytest.mark.asyncio
    async def test_ping(self, mcp_client: MCPClient) -> None:
        """Test pinging server."""
        latency = await mcp_client.ping()

        # Should be a positive number (milliseconds)
        assert latency > 0
        assert latency < 5000  # Should be fast for local server


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

aiohttp = pytest.importorskip("aiohttp", reason="aiohttp not installed")


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


class TestMCPPrompts:
    """Test MCP prompt operations with test server."""

    @pytest.mark.asyncio
    async def test_list_prompts(self, mcp_client: MCPClient) -> None:
        """Test listing prompts from server."""
        prompts = await mcp_client.list_prompts()

        assert len(prompts) == 3
        names = {p.name for p in prompts}
        assert "greeting" in names
        assert "code_review" in names
        assert "summarize" in names

    @pytest.mark.asyncio
    async def test_prompts_property_caches_results(self, mcp_client: MCPClient) -> None:
        """Test that prompts property returns cached results."""
        # Initially empty
        assert mcp_client.prompts == []

        # After list_prompts, property returns cached results
        prompts = await mcp_client.list_prompts()
        assert mcp_client.prompts == prompts
        assert len(mcp_client.prompts) == 3

    @pytest.mark.asyncio
    async def test_get_prompt_greeting(self, mcp_client: MCPClient) -> None:
        """Test getting greeting prompt with arguments."""
        result = await mcp_client.get_prompt("greeting", {"name": "Alice"})

        assert result.description == "Generate a greeting message"
        assert len(result.messages) == 1
        assert "Alice" in result.messages[0].get_text()

    @pytest.mark.asyncio
    async def test_get_prompt_code_review(self, mcp_client: MCPClient) -> None:
        """Test getting code review prompt."""
        result = await mcp_client.get_prompt(
            "code_review",
            {"language": "Python", "focus": "security"}
        )

        text = result.messages[0].get_text()
        assert "Python" in text
        assert "security" in text

    @pytest.mark.asyncio
    async def test_get_prompt_not_found(self, mcp_client: MCPClient) -> None:
        """Test getting non-existent prompt."""
        from nexus3.mcp import MCPError

        with pytest.raises(MCPError) as exc_info:
            await mcp_client.get_prompt("nonexistent")

        assert exc_info.value.code == -32602
        assert "not found" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_prompt_arguments_structure(self, mcp_client: MCPClient) -> None:
        """Test prompt argument metadata."""
        prompts = await mcp_client.list_prompts()
        greeting = next(p for p in prompts if p.name == "greeting")

        assert len(greeting.arguments) == 2
        name_arg = next(a for a in greeting.arguments if a.name == "name")
        assert name_arg.required is True

        formal_arg = next(a for a in greeting.arguments if a.name == "formal")
        assert formal_arg.required is False

    @pytest.mark.asyncio
    async def test_get_prompt_without_arguments(self, mcp_client: MCPClient) -> None:
        """Test getting prompt without providing optional arguments."""
        result = await mcp_client.get_prompt("summarize")

        assert result.description == "Summarize text content"
        assert len(result.messages) == 1


class TestMCPResources:
    """Test MCP resource operations with test server."""

    @pytest.mark.asyncio
    async def test_list_resources(self, mcp_client: MCPClient) -> None:
        """Test listing resources from server."""
        resources = await mcp_client.list_resources()

        assert len(resources) == 3
        uris = {r.uri for r in resources}
        assert "file:///readme.txt" in uris
        assert "file:///config.json" in uris
        assert "file:///data/users.csv" in uris

    @pytest.mark.asyncio
    async def test_resources_property_caches_results(self, mcp_client: MCPClient) -> None:
        """Test that resources property returns cached results."""
        # Initially empty
        assert mcp_client.resources == []

        # After list_resources, property returns cached results
        resources = await mcp_client.list_resources()
        assert mcp_client.resources == resources
        assert len(mcp_client.resources) == 3

    @pytest.mark.asyncio
    async def test_resource_metadata(self, mcp_client: MCPClient) -> None:
        """Test resource metadata parsing."""
        resources = await mcp_client.list_resources()

        readme = next(r for r in resources if r.uri == "file:///readme.txt")
        assert readme.name == "README"
        assert readme.description == "Project readme file"
        assert readme.mime_type == "text/plain"

        config = next(r for r in resources if r.uri == "file:///config.json")
        assert config.name == "Configuration"
        assert config.mime_type == "application/json"

    @pytest.mark.asyncio
    async def test_read_resource_text(self, mcp_client: MCPClient) -> None:
        """Test reading a text resource."""
        contents = await mcp_client.read_resource("file:///readme.txt")

        assert len(contents) == 1
        assert contents[0].uri == "file:///readme.txt"
        assert contents[0].mime_type == "text/plain"
        assert "Test Project" in contents[0].text

    @pytest.mark.asyncio
    async def test_read_resource_json(self, mcp_client: MCPClient) -> None:
        """Test reading a JSON resource."""
        contents = await mcp_client.read_resource("file:///config.json")

        assert len(contents) == 1
        assert contents[0].mime_type == "application/json"
        assert "test-server" in contents[0].text
        assert contents[0].blob is None

    @pytest.mark.asyncio
    async def test_read_resource_csv(self, mcp_client: MCPClient) -> None:
        """Test reading a CSV resource."""
        contents = await mcp_client.read_resource("file:///data/users.csv")

        assert len(contents) == 1
        assert contents[0].mime_type == "text/csv"
        assert "Alice" in contents[0].text
        assert "Bob" in contents[0].text

    @pytest.mark.asyncio
    async def test_read_resource_not_found(self, mcp_client: MCPClient) -> None:
        """Test reading non-existent resource."""
        from nexus3.mcp import MCPError

        with pytest.raises(MCPError) as exc_info:
            await mcp_client.read_resource("file:///nonexistent.txt")

        assert exc_info.value.code == -32602
        assert "not found" in exc_info.value.message.lower()
