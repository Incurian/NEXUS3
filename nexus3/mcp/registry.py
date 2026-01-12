"""MCP server registry.

Manages connections to multiple MCP servers, providing persistent clients
and skill adapters for use in NEXUS3 agents.

Usage:
    registry = MCPServerRegistry()

    config = MCPServerConfig(
        name="test",
        command=["python", "-m", "nexus3.mcp.test_server"]
    )
    server = await registry.connect(config, allow_all=True)

    # Get all MCP skills
    skills = registry.get_all_skills()

    # Clean up
    await registry.close_all()
"""

from dataclasses import dataclass, field

from nexus3.mcp.client import MCPClient
from nexus3.mcp.skill_adapter import MCPSkillAdapter
from nexus3.mcp.transport import HTTPTransport, StdioTransport


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server connection.

    Attributes:
        name: Friendly name for the server (used in skill prefixes).
        command: Command to launch server (for stdio transport).
        url: URL for HTTP transport.
        env: Environment variables for subprocess.
        enabled: Whether this server is enabled.
    """

    name: str
    command: list[str] | None = None
    url: str | None = None
    env: dict[str, str] | None = None
    enabled: bool = True


@dataclass
class ConnectedServer:
    """Active connection to an MCP server.

    Attributes:
        config: Server configuration.
        client: Active MCP client.
        skills: Skill adapters for this server's tools.
        allowed_all: Whether user chose to allow all tools without prompts.
    """

    config: MCPServerConfig
    client: MCPClient
    skills: list[MCPSkillAdapter] = field(default_factory=list)
    allowed_all: bool = False


class MCPServerRegistry:
    """Registry for managing multiple MCP server connections.

    Tracks connected servers, provides access to their skills, and
    handles cleanup on shutdown.
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._servers: dict[str, ConnectedServer] = {}

    async def connect(
        self,
        config: MCPServerConfig,
        allow_all: bool = False,
    ) -> ConnectedServer:
        """Connect to an MCP server and create skill adapters.

        If a server with the same name is already connected, it will be
        disconnected first.

        Args:
            config: Server configuration.
            allow_all: If True, allow all tools from this server without
                individual confirmation prompts.

        Returns:
            ConnectedServer instance with active client and skills.

        Raises:
            ValueError: If config has neither command nor url.
        """
        # Disconnect existing if present
        if config.name in self._servers:
            await self.disconnect(config.name)

        # Create transport based on config
        if config.command:
            transport = StdioTransport(config.command, env=config.env)
        elif config.url:
            transport = HTTPTransport(config.url)
        else:
            raise ValueError(f"Server '{config.name}' must have either 'command' or 'url'")

        # Create and initialize client
        client = MCPClient(transport)
        await client.connect()

        # List tools and create adapters
        tools = await client.list_tools()
        skills = [MCPSkillAdapter(client, tool, config.name) for tool in tools]

        # Store connected server
        connected = ConnectedServer(
            config=config,
            client=client,
            skills=skills,
            allowed_all=allow_all,
        )
        self._servers[config.name] = connected
        return connected

    async def disconnect(self, name: str) -> bool:
        """Disconnect and clean up a server.

        Args:
            name: Server name to disconnect.

        Returns:
            True if server was disconnected, False if not found.
        """
        server = self._servers.pop(name, None)
        if server is not None:
            await server.client.close()
            return True
        return False

    def get(self, name: str) -> ConnectedServer | None:
        """Get a connected server by name.

        Args:
            name: Server name.

        Returns:
            ConnectedServer if found, None otherwise.
        """
        return self._servers.get(name)

    def list_servers(self) -> list[str]:
        """List names of all connected servers.

        Returns:
            List of server names.
        """
        return list(self._servers.keys())

    def get_all_skills(self) -> list[MCPSkillAdapter]:
        """Get all skill adapters from all connected servers.

        Returns:
            Combined list of skills from all servers.
        """
        skills: list[MCPSkillAdapter] = []
        for server in self._servers.values():
            skills.extend(server.skills)
        return skills

    def is_tool_allowed(self, skill_name: str) -> bool:
        """Check if a skill is from an 'allow_all' server.

        Used to determine if a tool call needs individual confirmation.

        Args:
            skill_name: Prefixed skill name (e.g., 'mcp_test_echo').

        Returns:
            True if the skill's server has allowed_all=True.
        """
        for server in self._servers.values():
            if server.allowed_all:
                prefix = f"mcp_{server.config.name}_"
                if skill_name.startswith(prefix):
                    return True
        return False

    async def close_all(self) -> None:
        """Disconnect all servers.

        Call this during shutdown to clean up all connections.
        """
        for name in list(self._servers.keys()):
            await self.disconnect(name)

    def __len__(self) -> int:
        """Return number of connected servers."""
        return len(self._servers)
