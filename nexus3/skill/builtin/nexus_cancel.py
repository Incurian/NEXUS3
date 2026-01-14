"""Nexus cancel skill for cancelling in-progress requests on a Nexus agent."""

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


class NexusCancelSkill:
    """Skill that cancels an in-progress request on a Nexus agent."""

    def __init__(self, services: ServiceContainer) -> None:
        """Initialize the skill with service container.

        Args:
            services: ServiceContainer for accessing shared services like api_key.
        """
        self._services = services

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
                    "type": "string",
                    "description": "Request ID to cancel"
                },
                "port": {
                    "type": "integer",
                    "description": "Server port (default: 8765)"
                }
            },
            "required": ["agent_id", "request_id"]
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
        request_id: str = "",
        port: int | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Cancel an in-progress request on a Nexus agent.

        Args:
            agent_id: ID of the agent
            request_id: The request ID to cancel
            port: Optional server port (default: 8765)

        Returns:
            ToolResult with cancellation result or error
        """
        if not agent_id:
            return ToolResult(error="No agent_id provided")

        try:
            validate_agent_id(agent_id)
        except ValidationError as e:
            return ToolResult(error=f"Invalid agent_id: {e.message}")

        if not request_id:
            return ToolResult(error="No request_id provided")

        actual_port = self._get_port(port)
        url = f"http://127.0.0.1:{actual_port}/agent/{agent_id}"
        api_key = self._get_api_key(actual_port)

        try:
            validated_url = validate_url(url, allow_localhost=True)
        except UrlSecurityError as e:
            return ToolResult(error=f"URL validation failed: {e}")

        # Validate request_id format - must be a positive integer
        try:
            req_id = int(request_id)
            if req_id <= 0:
                return ToolResult(error="Request ID must be a positive integer")
        except ValueError:
            return ToolResult(error=f"Invalid request ID format: {request_id}")

        try:
            async with NexusClient(validated_url, api_key=api_key) as client:
                result = await client.cancel(req_id)
                return ToolResult(output=json.dumps(result))
        except ClientError as e:
            return ToolResult(error=str(e))


def nexus_cancel_factory(services: ServiceContainer) -> NexusCancelSkill:
    """Factory function for NexusCancelSkill.

    Args:
        services: ServiceContainer for accessing shared services.

    Returns:
        New NexusCancelSkill instance
    """
    return NexusCancelSkill(services)
