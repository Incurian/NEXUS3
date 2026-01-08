"""Nexus send skill for communicating with Nexus agents."""

import json
from typing import Any

from nexus3.client import ClientError, NexusClient
from nexus3.core.types import ToolResult
from nexus3.skill.services import ServiceContainer


class NexusSendSkill:
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
                "url": {
                    "type": "string",
                    "description": "Agent URL (e.g., http://localhost:8765)"
                },
                "content": {
                    "type": "string",
                    "description": "Message to send"
                },
                "request_id": {
                    "type": "string",
                    "description": "Optional ID for cancellation support"
                }
            },
            "required": ["url", "content"]
        }

    async def execute(
        self, url: str = "", content: str = "", request_id: str = "", **kwargs: Any
    ) -> ToolResult:
        """Send a message to a Nexus agent.

        Args:
            url: The agent URL to connect to
            content: The message to send
            request_id: Optional request ID for cancellation

        Returns:
            ToolResult with response JSON in output, or error message in error
        """
        if not url:
            return ToolResult(error="No url provided")
        if not content:
            return ToolResult(error="No content provided")

        try:
            async with NexusClient(url) as client:
                result = await client.send(content, int(request_id) if request_id else None)
                return ToolResult(output=json.dumps(result))
        except ClientError as e:
            return ToolResult(error=str(e))


def nexus_send_factory(services: ServiceContainer) -> NexusSendSkill:
    """Factory function for NexusSendSkill.

    Args:
        services: ServiceContainer (unused, but required by factory protocol)

    Returns:
        New NexusSendSkill instance
    """
    return NexusSendSkill()
