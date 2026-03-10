"""Focused tests for tool dispatch behavior."""

from unittest.mock import MagicMock

from nexus3.core.types import ToolCall
from nexus3.mcp.protocol import MCPTool
from nexus3.mcp.registry import ConnectedServer, MCPServerConfig, MCPServerRegistry
from nexus3.mcp.skill_adapter import MCPSkillAdapter
from nexus3.session.dispatcher import ToolDispatcher
from nexus3.skill.services import ServiceContainer


def _register_mcp_server(
    registry: MCPServerRegistry,
    *,
    server_name: str,
    owner_agent_id: str,
    shared: bool,
    tool_name: str = "echo",
) -> None:
    tool = MCPTool(
        name=tool_name,
        description=f"{server_name} {tool_name}",
        input_schema={"type": "object", "properties": {}},
    )
    client = MagicMock()
    skill = MCPSkillAdapter(client, tool, server_name)
    registry._servers[server_name] = ConnectedServer(
        config=MCPServerConfig(name=server_name, command=["echo", server_name]),
        client=client,
        skills=[skill],
        owner_agent_id=owner_agent_id,
        shared=shared,
    )


class TestToolDispatcherMcpVisibility:
    """MCP lookup should honor per-agent visibility at runtime."""

    def test_private_mcp_skill_hidden_from_non_owner(self) -> None:
        registry = MCPServerRegistry()
        _register_mcp_server(
            registry,
            server_name="private",
            owner_agent_id="owner-agent",
            shared=False,
        )

        services = ServiceContainer()
        services.register("mcp_registry", registry)
        services.register("agent_id", "worker-agent")
        dispatcher = ToolDispatcher(services=services)

        tool_call = ToolCall(id="tc-1", name="mcp_private_echo", arguments={})

        assert dispatcher.find_skill(tool_call) == (None, None)

    def test_private_mcp_skill_visible_to_owner(self) -> None:
        registry = MCPServerRegistry()
        _register_mcp_server(
            registry,
            server_name="private",
            owner_agent_id="owner-agent",
            shared=False,
        )

        services = ServiceContainer()
        services.register("mcp_registry", registry)
        services.register("agent_id", "owner-agent")
        dispatcher = ToolDispatcher(services=services)

        tool_call = ToolCall(id="tc-1", name="mcp_private_echo", arguments={})
        skill, server_name = dispatcher.find_skill(tool_call)

        assert skill is not None
        assert skill.name == "mcp_private_echo"
        assert server_name == "private"

    def test_shared_mcp_skill_visible_to_other_agents(self) -> None:
        registry = MCPServerRegistry()
        _register_mcp_server(
            registry,
            server_name="shared",
            owner_agent_id="owner-agent",
            shared=True,
        )

        services = ServiceContainer()
        services.register("mcp_registry", registry)
        services.register("agent_id", "worker-agent")
        dispatcher = ToolDispatcher(services=services)

        tool_call = ToolCall(id="tc-1", name="mcp_shared_echo", arguments={})
        skill, server_name = dispatcher.find_skill(tool_call)

        assert skill is not None
        assert skill.name == "mcp_shared_echo"
        assert server_name == "shared"
