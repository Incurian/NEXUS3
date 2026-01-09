"""Nexus shutdown skill for requesting graceful shutdown of the Nexus server."""

import json
from typing import Any

from nexus3.client import ClientError, NexusClient
from nexus3.core.types import ToolResult
from nexus3.core.url_validator import UrlSecurityError, validate_url
from nexus3.rpc.auth import discover_api_key
from nexus3.skill.services import ServiceContainer

DEFAULT_PORT = 8765


class NexusShutdownSkill:
    """Skill that requests graceful shutdown of the Nexus server.

    Connects to a running Nexus JSON-RPC server and requests shutdown.
    This stops the entire server, not just a single agent.
    """

    def __init__(self, services: ServiceContainer) -> None:
        """Initialize the skill with service container.

        Args:
            services: ServiceContainer for accessing shared services like api_key.
        """
        self._services = services

    @property
    def name(self) -> str:
        return "nexus_shutdown"

    @property
    def description(self) -> str:
        return "Request graceful shutdown of the Nexus server (stops all agents)"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "port": {
                    "type": "integer",
                    "description": "Server port (default: 8765)"
                }
            },
            "required": []
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

    async def execute(self, port: int | None = None, **kwargs: Any) -> ToolResult:
        """Request shutdown of the Nexus server.

        Args:
            port: Optional server port (default: 8765)

        Returns:
            ToolResult with shutdown acknowledgment or error message
        """
        actual_port = self._get_port(port)
        url = f"http://127.0.0.1:{actual_port}"
        api_key = self._get_api_key(actual_port)

        try:
            validated_url = validate_url(url, allow_localhost=True)
        except UrlSecurityError as e:
            return ToolResult(error=f"URL validation failed: {e}")

        try:
            async with NexusClient(validated_url, api_key=api_key) as client:
                result = await client.shutdown_server()
                return ToolResult(output=json.dumps(result))
        except ClientError as e:
            return ToolResult(error=str(e))


def nexus_shutdown_factory(services: ServiceContainer) -> NexusShutdownSkill:
    """Factory function for NexusShutdownSkill.

    Args:
        services: ServiceContainer for accessing shared services.

    Returns:
        New NexusShutdownSkill instance
    """
    return NexusShutdownSkill(services)
