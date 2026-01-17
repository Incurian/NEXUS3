"""Nexus send skill for communicating with Nexus agents."""

import json
from typing import Any

from nexus3.core.types import ToolResult
from nexus3.core.validation import ValidationError, validate_agent_id
from nexus3.skill.base import NexusSkill, nexus_skill_factory


class NexusSendSkill(NexusSkill):
    """Skill that sends a message to a Nexus agent and returns the response."""

    @property
    def name(self) -> str:
        return "nexus_send"

    @property
    def description(self) -> str:
        return (
            "Send a message to a Nexus agent and get the response. "
            "Agent may use tools (up to 100 iterations) before responding. "
            "Returns the full assistant message including any tool results. "
            "If agent halts at max iterations, response includes a warning."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "ID of the agent to send to (e.g., 'worker-1')",
                },
                "content": {
                    "type": "string",
                    "description": "Message to send. Agent will process and respond.",
                },
                "port": {
                    "type": "integer",
                    "description": "Server port (default: 8765)",
                },
            },
            "required": ["agent_id", "content"],
        }

    async def execute(
        self,
        agent_id: str = "",
        content: str = "",
        port: int | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Send a message to a Nexus agent."""
        if not agent_id:
            return ToolResult(error="No agent_id provided")

        try:
            validate_agent_id(agent_id)
        except ValidationError as e:
            return ToolResult(error=f"Invalid agent_id: {e.message}")

        if not content:
            return ToolResult(error="No content provided")

        async def send_and_format(client: Any) -> dict[str, Any]:
            """Send message and format response with halt warning if needed."""
            result = await client.send(content)
            return result

        # Get raw result from client
        result = await self._execute_with_client(
            port=port,
            agent_id=agent_id,
            operation=send_and_format
        )

        # Check for halt status and add warning
        if result.output:
            try:
                data = json.loads(result.output)
                if data.get("halted_at_iteration_limit"):
                    # Add clear warning to the content
                    warning = (
                        f"\n\n[WARNING: Agent '{agent_id}' halted at max tool iterations. "
                        f"Send another message to continue, or use nexus_status to check state.]"
                    )
                    data["content"] = data.get("content", "") + warning
                    return ToolResult(output=json.dumps(data))
            except json.JSONDecodeError:
                pass  # Return original result if not valid JSON

        return result


# Factory for dependency injection
nexus_send_factory = nexus_skill_factory(NexusSendSkill)
