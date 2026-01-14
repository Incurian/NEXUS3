"""Nexus send skill for communicating with Nexus agents."""

import json
from typing import Any

from nexus3.client import ClientError, NexusClient
from nexus3.core.types import ToolResult
from nexus3.core.url_validator import UrlSecurityError, validate_url
from nexus3.core.validation import ValidationError, validate_agent_id
from nexus3.rpc.auth import discover_api_key
from nexus3.skill.services import ServiceContainer


def _get_default_port() -> int:
    """Get default port from config, with fallback to 8765."""
    try:
        from nexus3.config.loader import load_config
        config = load_config()
        return config.server.port
    except Exception:
        return 8765


DEFAULT_PORT = _get_default_port()


class NexusSendSkill:
    """Skill that sends a message to a Nexus agent and returns the response."""

    def __init__(self, services: ServiceContainer) -> None:
        """Initialize the skill with service container.

        Args:
            services: ServiceContainer for accessing shared services like api_key.
        """
        self._services = services

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
        content: str = "",
        port: int | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Send a message to a Nexus agent.

        Args:
            agent_id: ID of the agent to send to
            content: The message to send
            port: Optional server port (default: 8765)

        Returns:
            ToolResult with response JSON in output, or error message in error
        """
        if not agent_id:
            return ToolResult(error="No agent_id provided")

        try:
            validate_agent_id(agent_id)
        except ValidationError as e:
            return ToolResult(error=f"Invalid agent_id: {e.message}")

        if not content:
            return ToolResult(error="No content provided")

        actual_port = self._get_port(port)
        url = f"http://127.0.0.1:{actual_port}/agent/{agent_id}"
        api_key = self._get_api_key(actual_port)

        try:
            validated_url = validate_url(url, allow_localhost=True)
        except UrlSecurityError as e:
            return ToolResult(error=f"URL validation failed: {e}")

        try:
            async with NexusClient(validated_url, api_key=api_key) as client:
                result = await client.send(content)
                return ToolResult(output=json.dumps(result))
        except ClientError as e:
            return ToolResult(error=str(e))


def nexus_send_factory(services: ServiceContainer) -> NexusSendSkill:
    """Factory function for NexusSendSkill.

    Args:
        services: ServiceContainer for accessing shared services.

    Returns:
        New NexusSendSkill instance
    """
    return NexusSendSkill(services)
