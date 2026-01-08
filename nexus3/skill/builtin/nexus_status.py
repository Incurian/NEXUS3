"""Nexus status skill for getting agent status (tokens + context)."""

import json
from typing import Any

from nexus3.client import ClientError, NexusClient
from nexus3.core.types import ToolResult
from nexus3.skill.services import ServiceContainer


class NexusStatusSkill:
    """Skill that gets status from a Nexus agent.

    Combines get_tokens and get_context into a single call for
    convenient status checking of remote agents.
    """

    @property
    def name(self) -> str:
        return "nexus_status"

    @property
    def description(self) -> str:
        return "Get status of a Nexus agent (token usage and context info)"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Agent URL (e.g., http://localhost:8765)"
                }
            },
            "required": ["url"]
        }

    async def execute(self, url: str = "", **kwargs: Any) -> ToolResult:
        """Get status from a Nexus agent.

        Args:
            url: The URL of the Nexus agent

        Returns:
            ToolResult with combined tokens and context info, or error
        """
        if not url:
            return ToolResult(error="No URL provided")

        try:
            async with NexusClient(url) as client:
                tokens = await client.get_tokens()
                context = await client.get_context()
                combined = {"tokens": tokens, "context": context}
                return ToolResult(output=json.dumps(combined, indent=2))
        except ClientError as e:
            return ToolResult(error=str(e))


def nexus_status_factory(services: ServiceContainer) -> NexusStatusSkill:
    """Factory function for NexusStatusSkill.

    Args:
        services: ServiceContainer (unused, but required by factory protocol)

    Returns:
        New NexusStatusSkill instance
    """
    return NexusStatusSkill()
