"""Nexus cancel skill for cancelling in-progress requests on a Nexus agent."""

from typing import Any

from nexus3.core.types import ToolResult
from nexus3.core.validation import ValidationError, validate_agent_id
from nexus3.skill.base import NexusSkill, nexus_skill_factory


class NexusCancelSkill(NexusSkill):
    """Skill that cancels an in-progress request on a Nexus agent."""

    @property
    def name(self) -> str:
        return "nexus_cancel"

    @property
    def description(self) -> str:
        return "Cancel an in-progress request on a Nexus agent"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "ID of the agent (e.g., 'worker-1')"
                },
                "request_id": {
                    "type": ["string", "integer"],
                    "description": "Request ID to cancel (string or integer)"
                },
                "port": {
                    "type": "integer",
                    "description": "Server port (default: 8765)"
                }
            },
            "required": ["agent_id", "request_id"],
            "additionalProperties": False,
        }

    async def execute(
        self,
        agent_id: str = "",
        request_id: str | int | None = None,
        port: int | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Cancel an in-progress request on a Nexus agent."""
        if not agent_id:
            return ToolResult(error="No agent_id provided")

        try:
            validate_agent_id(agent_id)
        except ValidationError as e:
            return ToolResult(error=f"Invalid agent_id: {e.message}")

        if request_id is None:
            return ToolResult(error="No request_id provided")
        if isinstance(request_id, bool):
            return ToolResult(error="Request ID must be string or integer")

        if isinstance(request_id, str):
            request_id_stripped = request_id.strip()
            if not request_id_stripped:
                return ToolResult(error="Request ID must be a non-empty string")
            normalized_request_id: str | int = request_id_stripped
        else:
            normalized_request_id = request_id

        return await self._execute_with_client(
            port=port,
            agent_id=agent_id,
            operation=lambda client: client.cancel(normalized_request_id)
        )


# Factory for dependency injection
nexus_cancel_factory = nexus_skill_factory(NexusCancelSkill)
