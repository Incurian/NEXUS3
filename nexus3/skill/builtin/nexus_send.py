"""Nexus send skill for communicating with Nexus agents."""

from typing import Any

from nexus3.core.types import ToolResult
from nexus3.core.validation import ValidationError, validate_agent_id
from nexus3.skill.base import NexusSkill, nexus_skill_factory


class NexusSendSkill(NexusSkill):
    """Skill that sends a message to a Nexus agent and returns the response."""

    @property
    def name(self) -> str:
        return "nexus_send"

    @property
    def description(self) -> str:
        return "Send a message to a Nexus agent and get the response"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "ID of the agent to send to (e.g., 'worker-1')"
                },
                "content": {
                    "type": "string",
                    "description": "Message to send"
                },
                "port": {
                    "type": "integer",
                    "description": "Server port (default: 8765)"
                }
            },
            "required": ["agent_id", "content"]
        }

    async def execute(
        self,
        agent_id: str = "",
        content: str = "",
        port: int | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Send a message to a Nexus agent."""
        if not agent_id:
            return ToolResult(error="No agent_id provided")

        try:
            validate_agent_id(agent_id)
        except ValidationError as e:
            return ToolResult(error=f"Invalid agent_id: {e.message}")

        if not content:
            return ToolResult(error="No content provided")

        return await self._execute_with_client(
            port=port,
            agent_id=agent_id,
            operation=lambda client: client.send(content)
        )


# Factory for dependency injection
nexus_send_factory = nexus_skill_factory(NexusSendSkill)
