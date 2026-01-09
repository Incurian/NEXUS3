"""Nexus create skill for creating new agents on the server."""

import json
from typing import Any

from nexus3.client import ClientError, NexusClient
from nexus3.core.types import ToolResult
from nexus3.rpc.auth import discover_api_key
from nexus3.skill.services import ServiceContainer

DEFAULT_PORT = 8765


class NexusCreateSkill:
    """Skill that creates a new agent on the Nexus server."""

    def __init__(self, services: ServiceContainer) -> None:
        """Initialize the skill with service container.

        Args:
            services: ServiceContainer for accessing shared services like api_key.
        """
        self._services = services

    @property
    def name(self) -> str:
        return "nexus_create"

    @property
    def description(self) -> str:
        return "Create a new agent on the Nexus server"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "ID for the new agent (e.g., 'worker-1')"
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
        """Create a new agent on the Nexus server.

        Args:
            agent_id: ID for the new agent
            port: Optional server port (default: 8765)

        Returns:
            ToolResult with creation result or error
        """
        if not agent_id:
            return ToolResult(error="No agent_id provided")

        actual_port = self._get_port(port)
        url = f"http://127.0.0.1:{actual_port}"
        api_key = self._get_api_key(actual_port)

        try:
            async with NexusClient(url, api_key=api_key) as client:
                result = await client.create_agent(agent_id)
                return ToolResult(output=json.dumps(result))
        except ClientError as e:
            return ToolResult(error=str(e))


def nexus_create_factory(services: ServiceContainer) -> NexusCreateSkill:
    """Factory function for NexusCreateSkill.

    Args:
        services: ServiceContainer for accessing shared services.

    Returns:
        New NexusCreateSkill instance
    """
    return NexusCreateSkill(services)
