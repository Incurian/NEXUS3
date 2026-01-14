"""Nexus status skill for getting agent status (tokens + context)."""

import json
from typing import Any

from nexus3.core.types import ToolResult
from nexus3.core.validation import ValidationError, validate_agent_id
from nexus3.skill.base import NexusSkill, nexus_skill_factory


class NexusStatusSkill(NexusSkill):
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

    async def execute(
        self,
        agent_id: str = "",
        port: int | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Get status from a Nexus agent."""
        if not agent_id:
            return ToolResult(error="No agent_id provided")

        try:
            validate_agent_id(agent_id)
        except ValidationError as e:
            return ToolResult(error=f"Invalid agent_id: {e.message}")

        async def get_status(client: Any) -> dict[str, Any]:
            tokens = await client.get_tokens()
            context = await client.get_context()
            return {"tokens": tokens, "context": context}

        # Note: _execute_with_client uses json.dumps without indent,
        # but status benefits from pretty printing, so we override
        from nexus3.client import ClientError, NexusClient
        from nexus3.core.url_validator import UrlSecurityError, validate_url

        actual_port = self._get_port(port)
        url = self._build_url(actual_port, agent_id)
        api_key = self._get_api_key(actual_port)

        try:
            validated_url = validate_url(url, allow_localhost=True)
        except UrlSecurityError as e:
            return ToolResult(error=f"URL validation failed: {e}")

        try:
            async with NexusClient(validated_url, api_key=api_key) as client:
                result = await get_status(client)
                return ToolResult(output=json.dumps(result, indent=2))
        except ClientError as e:
            return ToolResult(error=str(e))


# Factory for dependency injection
nexus_status_factory = nexus_skill_factory(NexusStatusSkill)
