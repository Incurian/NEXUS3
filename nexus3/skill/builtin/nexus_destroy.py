"""Nexus destroy skill for removing agents from the server."""

from typing import Any

from nexus3.core.types import ToolResult
from nexus3.core.validation import ValidationError, validate_agent_id
from nexus3.skill.base import NexusSkill, nexus_skill_factory


class NexusDestroySkill(NexusSkill):
    """Skill that destroys an agent on the Nexus server.

    This removes the agent from the pool but keeps the server running.
    Use nexus_shutdown to stop the entire server.
    """

    @property
    def name(self) -> str:
        return "nexus_destroy"

    @property
    def description(self) -> str:
        return "Destroy an agent on the Nexus server (server keeps running)"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "ID of the agent to destroy (e.g., 'worker-1')"
                },
                "port": {
                    "type": "integer",
                    "description": "Server port (default: 8765)"
                }
            },
            "required": ["agent_id"]
        }

    async def execute(
        self,
        agent_id: str = "",
        port: int | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Destroy an agent on the Nexus server."""
        if not agent_id:
            return ToolResult(error="No agent_id provided")

        try:
            validate_agent_id(agent_id)
        except ValidationError as e:
            return ToolResult(error=f"Invalid agent_id: {e.message}")

        return await self._execute_with_client(
            port=port,
            agent_id=None,  # destroy_agent is a global method
            operation=lambda client: client.destroy_agent(agent_id)
        )


# Factory for dependency injection
nexus_destroy_factory = nexus_skill_factory(NexusDestroySkill)
