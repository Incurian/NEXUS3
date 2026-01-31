"""Echo skill for testing the skill system."""

from typing import TYPE_CHECKING, Any

from nexus3.core.types import ToolResult
from nexus3.skill.base import base_skill_factory

if TYPE_CHECKING:
    from nexus3.skill.services import ServiceContainer


@base_skill_factory
class EchoSkill:
    """Simple skill that echoes back the input message.

    Useful for testing the skill infrastructure without side effects.
    """

    def __init__(self, services: "ServiceContainer | None" = None) -> None:
        pass  # Echo doesn't need services

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


# Export factory for registration
echo_skill_factory = EchoSkill.factory
