"""MCP server registry.

Manages connections to multiple MCP servers, providing persistent clients
and skill adapters for use in NEXUS3 agents.

Connections can be private (visible only to the creating agent) or shared
(visible to all agents). Permissions/allowances are always per-agent.

Usage:
    registry = MCPServerRegistry()

    config = MCPServerConfig(
        name="test",
        command=["python", "-m", "nexus3.mcp.test_server"]
    )
    server = await registry.connect(config, owner_agent_id="main", shared=False)

    # Get skills visible to an agent
    skills = registry.get_skills_for_agent("main")

    # Clean up
    await registry.close_all()
"""

from dataclasses import dataclass, field

from nexus3.core.errors import MCPConfigError
from nexus3.mcp.client import MCPClient
from nexus3.mcp.error_formatter import format_command_not_found, format_server_crash
from nexus3.mcp.errors import MCPErrorContext
from nexus3.mcp.skill_adapter import MCPSkillAdapter
from nexus3.mcp.transport import HTTPTransport, MCPTransportError, StdioTransport


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server connection.

    SECURITY: MCP servers receive only safe environment variables by default.
    Use env for explicit values or env_passthrough for host vars.

    Supports two command formats:
    1. NEXUS3 format: command as list ["npx", "-y", "@anthropic/mcp-server-github"]
    2. Official format: command as string + args array
       {"command": "npx", "args": ["-y", "@anthropic/mcp-server-github"]}

    Attributes:
        name: Friendly name for the server (used in skill prefixes).
        command: Command to launch server (for stdio transport).
            Can be a list (NEXUS3 format) or string (official format, use with args).
        args: Arguments for command when command is a string (official format).
        url: URL for HTTP transport.
        env: Explicit environment variables for subprocess.
        env_passthrough: Names of host env vars to pass to subprocess.
        cwd: Working directory for the server subprocess.
        enabled: Whether this server is enabled.
    """

    name: str
    command: str | list[str] | None = None
    args: list[str] | None = None
    url: str | None = None
    env: dict[str, str] | None = None
    env_passthrough: list[str] | None = None
    cwd: str | None = None
    enabled: bool = True

    def get_command_list(self) -> list[str]:
        """Return command as list, merging command + args if needed.

        Returns:
            Command as list of strings suitable for subprocess execution.
            Empty list if no command configured.
        """
        if isinstance(self.command, list):
            return self.command  # NEXUS3 format
        elif isinstance(self.command, str):
            # Official format: command string + args array
            cmd = [self.command]
            if self.args:
                cmd.extend(self.args)
            return cmd
        return []


@dataclass
class ConnectedServer:
    """Active connection to an MCP server.

    Attributes:
        config: Server configuration.
        client: Active MCP client.
        skills: Skill adapters for this server's tools.
        owner_agent_id: ID of the agent that created this connection.
        shared: If True, connection is visible to all agents.
            If False, only visible to owner_agent_id.
    """

    config: MCPServerConfig
    client: MCPClient
    skills: list[MCPSkillAdapter] = field(default_factory=list)
    owner_agent_id: str = "main"
    shared: bool = False

    def is_visible_to(self, agent_id: str) -> bool:
        """Check if this connection is visible to a given agent.

        Args:
            agent_id: Agent to check visibility for.

        Returns:
            True if shared or if agent_id matches owner.
        """
        return self.shared or self.owner_agent_id == agent_id

    def is_alive(self) -> bool:
        """Check if the connection is still alive.

        For stdio: checks if subprocess is still running.
        For HTTP: returns True (actual check happens on next request).

        Returns:
            True if connection appears alive.
        """
        return self.client.is_connected


class MCPServerRegistry:
    """Registry for managing multiple MCP server connections.

    Tracks connected servers, provides access to their skills, and
    handles cleanup on shutdown. Supports per-agent and shared connections.
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._servers: dict[str, ConnectedServer] = {}

    async def connect(
        self,
        config: MCPServerConfig,
        owner_agent_id: str = "main",
        shared: bool = False,
        timeout: float = 30.0,
    ) -> ConnectedServer:
        """Connect to an MCP server and create skill adapters.

        If a server with the same name is already connected, it will be
        disconnected first.

        Args:
            config: Server configuration.
            owner_agent_id: ID of the agent creating this connection.
            shared: If True, connection is visible to all agents.
            timeout: Maximum time to wait for connection. Default 30s.

        Returns:
            ConnectedServer instance with active client and skills.

        Raises:
            MCPConfigError: If config has neither command nor url, or if server is disabled.
            MCPError: If connection times out or fails.
        """
        # P1.9.5: Create error context for this server
        command_list = config.get_command_list()
        error_context = MCPErrorContext(
            server_name=config.name,
            command=command_list if command_list else None,
        )

        # Check if server is enabled (P2.17: use MCPConfigError for consistency)
        if not config.enabled:
            raise MCPConfigError(
                f"MCP server '{config.name}' is disabled in configuration",
                context=error_context,
            )

        # Disconnect existing if present
        if config.name in self._servers:
            await self.disconnect(config.name)

        # Create transport based on config
        transport: StdioTransport | HTTPTransport
        if command_list:
            transport = StdioTransport(
                command_list,
                env=config.env,
                env_passthrough=config.env_passthrough,
                cwd=config.cwd,
            )
        elif config.url:
            transport = HTTPTransport(config.url)
        else:
            # P2.17: use MCPConfigError for consistency
            raise MCPConfigError(
                f"Server '{config.name}' must have either 'command' or 'url'",
                context=error_context,
            )

        # Create and initialize client with error context
        client = MCPClient(transport)
        try:
            await client.connect(timeout=timeout)
        except MCPTransportError as e:
            # P1.9.5: Capture stderr if available (for stdio transport)
            if isinstance(transport, StdioTransport):
                error_context.stderr_lines = transport.stderr_lines

            # Check for specific error types and format appropriately
            error_msg = str(e)
            if "not found" in error_msg.lower():
                # Command not found - use formatted message
                cmd = command_list[0] if command_list else "unknown"
                raise MCPTransportError(
                    format_command_not_found(error_context, cmd)
                ) from e
            elif "closed" in error_msg.lower() or "exit" in error_msg.lower():
                # Server crashed - use formatted message with stderr
                # Try to extract exit code from message
                import re
                match = re.search(r"exit code[:\s]*(-?\d+)", error_msg, re.IGNORECASE)
                exit_code = int(match.group(1)) if match else None
                raise MCPTransportError(
                    format_server_crash(error_context, exit_code, error_context.stderr_lines)
                ) from e
            else:
                # Generic transport error - include server context
                raise MCPTransportError(
                    f"Failed to connect to MCP server '{config.name}': {e}"
                ) from e

        # List tools and create adapters
        tools = await client.list_tools()
        skills = [MCPSkillAdapter(client, tool, config.name) for tool in tools]

        # Store connected server
        connected = ConnectedServer(
            config=config,
            client=client,
            skills=skills,
            owner_agent_id=owner_agent_id,
            shared=shared,
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

    def get(self, name: str, agent_id: str | None = None) -> ConnectedServer | None:
        """Get a connected server by name.

        Args:
            name: Server name.
            agent_id: If provided, only return if visible to this agent.

        Returns:
            ConnectedServer if found (and visible), None otherwise.
        """
        server = self._servers.get(name)
        if server is None:
            return None
        if agent_id is not None and not server.is_visible_to(agent_id):
            return None
        return server

    def list_servers(self, agent_id: str | None = None) -> list[str]:
        """List names of connected servers.

        Args:
            agent_id: If provided, only return servers visible to this agent.

        Returns:
            List of server names.
        """
        if agent_id is None:
            return list(self._servers.keys())
        return [
            name for name, server in self._servers.items()
            if server.is_visible_to(agent_id)
        ]

    def get_all_skills(self, agent_id: str | None = None) -> list[MCPSkillAdapter]:
        """Get all skill adapters from connected servers.

        Args:
            agent_id: If provided, only return skills from visible servers.

        Returns:
            Combined list of skills from (visible) servers.
        """
        skills: list[MCPSkillAdapter] = []
        for server in self._servers.values():
            if agent_id is None or server.is_visible_to(agent_id):
                skills.extend(server.skills)
        return skills

    def find_skill(self, tool_name: str) -> tuple[MCPSkillAdapter, str] | None:
        """Find MCP skill by tool name.

        Searches all connected servers for a skill matching the given name.

        Args:
            tool_name: The skill name to find (e.g., 'mcp_test_echo').

        Returns:
            Tuple of (skill, server_name) if found, None otherwise.
        """
        for server in self._servers.values():
            for skill in server.skills:
                if skill.name == tool_name:
                    return (skill, server.config.name)
        return None

    def get_server_for_skill(self, skill_name: str) -> ConnectedServer | None:
        """Find which server provides a given skill.

        Args:
            skill_name: Prefixed skill name (e.g., 'mcp_test_echo').

        Returns:
            ConnectedServer if found, None otherwise.
        """
        for server in self._servers.values():
            prefix = f"mcp_{server.config.name}_"
            if skill_name.startswith(prefix):
                return server
        return None

    async def check_connections(self) -> list[str]:
        """Check all connections and remove dead ones.

        For stdio servers, this checks if the subprocess has exited.
        For HTTP servers, this only detects if client was closed.

        Returns:
            List of server names that were removed due to dead connections.
        """
        dead: list[str] = []
        for name, server in list(self._servers.items()):
            if not server.is_alive():
                await self.disconnect(name)
                dead.append(name)
        return dead

    async def close_all(self) -> None:
        """Disconnect all servers.

        Call this during shutdown to clean up all connections.
        """
        for name in list(self._servers.keys()):
            await self.disconnect(name)

    def __len__(self) -> int:
        """Return number of connected servers."""
        return len(self._servers)
