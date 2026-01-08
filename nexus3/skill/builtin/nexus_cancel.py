"""Nexus cancel skill for cancelling in-progress requests on a Nexus agent."""

import json
from typing import Any

from nexus3.client import ClientError, NexusClient
from nexus3.core.types import ToolResult
from nexus3.skill.services import ServiceContainer


class NexusCancelSkill:
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
                "url": {
                    "type": "string",
                    "description": "Agent URL (e.g., http://127.0.0.1:8765)",
                },
                "request_id": {
                    "type": "string",
                    "description": "Request ID to cancel",
                },
            },
            "required": ["url", "request_id"],
        }

    async def execute(
        self, url: str = "", request_id: str = "", **kwargs: Any
    ) -> ToolResult:
        """Cancel an in-progress request on a Nexus agent.

        Args:
            url: The agent URL
            request_id: The request ID to cancel

        Returns:
            ToolResult with cancellation result or error
        """
        if not url:
            return ToolResult(error="No URL provided")
        if not request_id:
            return ToolResult(error="No request_id provided")

        try:
            async with NexusClient(url) as client:
                result = await client.cancel(int(request_id))
                return ToolResult(output=json.dumps(result))
        except ClientError as e:
            return ToolResult(error=str(e))


def nexus_cancel_factory(services: ServiceContainer) -> NexusCancelSkill:
    """Factory function for NexusCancelSkill.

    Args:
        services: ServiceContainer (unused, but required by factory protocol)

    Returns:
        New NexusCancelSkill instance
    """
    return NexusCancelSkill()
