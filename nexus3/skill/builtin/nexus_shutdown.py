"""Nexus shutdown skill for requesting graceful shutdown of a Nexus agent."""

import json
from typing import Any

from nexus3.client import ClientError, NexusClient
from nexus3.core.types import ToolResult
from nexus3.skill.services import ServiceContainer


class NexusShutdownSkill:
    """Skill that requests graceful shutdown of a Nexus agent.

    Connects to a running Nexus JSON-RPC server and requests shutdown.
    """

    @property
    def name(self) -> str:
        return "nexus_shutdown"

    @property
    def description(self) -> str:
        return "Request graceful shutdown of a Nexus agent"

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
        """Request shutdown of the specified Nexus agent.

        Args:
            url: The URL of the Nexus agent to shutdown

        Returns:
            ToolResult with shutdown acknowledgment or error message
        """
        if not url:
            return ToolResult(error="No URL provided")

        try:
            async with NexusClient(url) as client:
                result = await client.shutdown()
                return ToolResult(output=json.dumps(result))
        except ClientError as e:
            return ToolResult(error=str(e))


def nexus_shutdown_factory(services: ServiceContainer) -> NexusShutdownSkill:
    """Factory function for NexusShutdownSkill.

    Args:
        services: ServiceContainer (unused, but required by factory protocol)

    Returns:
        New NexusShutdownSkill instance
    """
    return NexusShutdownSkill()
