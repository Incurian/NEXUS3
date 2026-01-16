"""Tool dispatch - resolves tool calls to skill implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nexus3.core.types import ToolCall
    from nexus3.mcp.registry import MCPServerRegistry
    from nexus3.mcp.skill_adapter import MCPSkillAdapter
    from nexus3.skill.base import Skill
    from nexus3.skill.registry import SkillRegistry
    from nexus3.skill.services import ServiceContainer


class ToolDispatcher:
    """Resolves tool calls to their implementing skills.

    Handles both built-in skills (via SkillRegistry) and MCP tools
    (via MCPServerRegistry).
    """

    def __init__(
        self,
        registry: SkillRegistry | None = None,
        services: ServiceContainer | None = None,
    ) -> None:
        self._registry = registry
        self._services = services

    def find_skill(self, tool_call: ToolCall) -> tuple[Skill | None, str | None]:
        """Find the skill for a tool call.

        Args:
            tool_call: The tool call to resolve.

        Returns:
            Tuple of (skill, mcp_server_name).
            - For built-in skills: (skill, None)
            - For MCP skills: (skill, server_name)
            - If not found: (None, None)
        """
        # Try built-in registry first
        if self._registry:
            skill = self._registry.get(tool_call.name)
            if skill:
                return (skill, None)

        # Try MCP registry for mcp_* prefixed tools
        if tool_call.name.startswith("mcp_") and self._services:
            mcp_result = self._find_mcp_skill(tool_call.name)
            if mcp_result:
                return mcp_result

        return (None, None)

    def _find_mcp_skill(self, tool_name: str) -> tuple[MCPSkillAdapter, str] | None:
        """Find MCP skill by name.

        Uses the public MCPServerRegistry.find_skill() API.

        Returns:
            Tuple of (skill, server_name) or None if not found.
        """
        mcp_registry: MCPServerRegistry | None = (
            self._services.get_mcp_registry() if self._services else None
        )
        if not mcp_registry:
            return None

        return mcp_registry.find_skill(tool_name)
