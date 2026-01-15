"""MCP skill adapter.

Wraps an MCP tool as a NEXUS3 Skill, allowing MCP tools to be used seamlessly
in the NEXUS3 agent system.

The adapter prefixes the skill name with 'mcp_{server_name}_' to avoid name
collisions with native NEXUS3 skills.

Usage:
    adapter = MCPSkillAdapter(client, tool, "my_mcp_server")
    # Register adapter as a skill in the agent
"""

from typing import Any

from nexus3.core.types import ToolResult
from nexus3.core.validation import validate_tool_arguments
from nexus3.mcp.client import MCPClient
from nexus3.mcp.protocol import MCPTool
from nexus3.skill.base import BaseSkill


class MCPSkillAdapter(BaseSkill):
    """Adapter that wraps an MCPTool as a NEXUS3 Skill."""

    def __init__(
        self,
        client: MCPClient,
        tool: MCPTool,
        server_name: str,
    ) -> None:
        """
        Initialize the MCP skill adapter.

        Args:
            client: Initialized MCPClient connected to the server.
            tool: MCPTool definition from the server.
            server_name: Identifier for the MCP server (used in skill name prefix).
        """
        self._client = client
        self._original_name = tool.name
        self._server_name = server_name

        prefixed_name = f"mcp_{server_name}_{tool.name}"
        super().__init__(
            name=prefixed_name,
            description=tool.description,
            parameters=tool.input_schema,
        )

    @property
    def server_name(self) -> str:
        """Name of the MCP server."""
        return self._server_name

    @property
    def original_name(self) -> str:
        """Original name of the MCP tool (without prefix)."""
        return self._original_name

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute the underlying MCP tool.

        Validates kwargs against input_schema, then calls client.call_tool()
        and converts MCPToolResult to ToolResult.

        Returns:
            ToolResult with output (success) or error.
        """
        # Validate parameters against input_schema before calling MCP server
        try:
            validated_args = validate_tool_arguments(kwargs, self._parameters)
        except ValueError as e:
            return ToolResult(error=f"Invalid parameters for {self.name}: {e}")

        try:
            mcp_result = await self._client.call_tool(
                self._original_name, validated_args
            )
            text_content = mcp_result.to_text()
            if mcp_result.is_error:
                return ToolResult(error=text_content)
            return ToolResult(output=text_content)
        except Exception as e:
            return ToolResult(error=f"MCP execution failed: {str(e)}")
