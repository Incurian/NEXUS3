"""Echo skill for testing the skill system."""

from typing import Any

from nexus3.core.types import ToolResult
from nexus3.skill.services import ServiceContainer


class EchoSkill:
    """Simple skill that echoes back the input message.

    Useful for testing the skill infrastructure without side effects.
    """

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo back the input message. Useful for testing."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The message to echo back"
                }
            },
            "required": ["message"]
        }

    async def execute(self, message: str = "", **kwargs: Any) -> ToolResult:
        """Echo the message back."""
        return ToolResult(output=message)


def echo_skill_factory(services: ServiceContainer) -> EchoSkill:
    """Factory function for EchoSkill.

    Args:
        services: ServiceContainer (unused, but required by factory protocol)

    Returns:
        New EchoSkill instance
    """
    return EchoSkill()
