"""Nexus status skill for getting agent status (tokens + context)."""

import json
from typing import Any

from nexus3.client import ClientError, NexusClient
from nexus3.core.types import ToolResult
from nexus3.rpc.auth import discover_api_key
from nexus3.skill.services import ServiceContainer

DEFAULT_PORT = 8765


class NexusStatusSkill:
    """Skill that gets status from a Nexus agent.

    Combines get_tokens and get_context into a single call for
    convenient status checking of remote agents.
    """

    def __init__(self, services: ServiceContainer) -> None:
        """Initialize the skill with service container.

        Args:
            services: ServiceContainer for accessing shared services like api_key.
        """
        self._services = services

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
                "agent_id": {
                    "type": "string",
                    "description": "ID of the agent (e.g., 'worker-1')"
                },
                "port": {
                    "type": "integer",
                    "description": "Server port (default: 8765)"
                }
            },
            "required": ["agent_id"]
        }

    def _get_port(self, port: int | None) -> int:
        """Get the port to use, checking ServiceContainer first."""
        if port is not None:
            return port
        svc_port: int | None = self._services.get("port")
        if svc_port is not None:
            return svc_port
        return DEFAULT_PORT

    def _get_api_key(self, port: int) -> str | None:
        """Get API key from ServiceContainer or auto-discover."""
        api_key: str | None = self._services.get("api_key")
        if api_key:
            return api_key
        return discover_api_key(port=port)

    async def execute(
        self,
        agent_id: str = "",
        port: int | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Get status from a Nexus agent.

        Args:
            agent_id: ID of the agent
            port: Optional server port (default: 8765)

        Returns:
            ToolResult with combined tokens and context info, or error
        """
        if not agent_id:
            return ToolResult(error="No agent_id provided")

        actual_port = self._get_port(port)
        url = f"http://127.0.0.1:{actual_port}/agent/{agent_id}"
        api_key = self._get_api_key(actual_port)

        try:
            async with NexusClient(url, api_key=api_key) as client:
                tokens = await client.get_tokens()
                context = await client.get_context()
                combined = {"tokens": tokens, "context": context}
                return ToolResult(output=json.dumps(combined, indent=2))
        except ClientError as e:
            return ToolResult(error=str(e))


def nexus_status_factory(services: ServiceContainer) -> NexusStatusSkill:
    """Factory function for NexusStatusSkill.

    Args:
        services: ServiceContainer for accessing shared services.

    Returns:
        New NexusStatusSkill instance
    """
    return NexusStatusSkill(services)
