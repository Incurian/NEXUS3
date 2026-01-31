"""Sleep skill for testing execution modes and timeouts."""

import asyncio
from typing import TYPE_CHECKING, Any

from nexus3.core.types import ToolResult
from nexus3.skill.base import base_skill_factory

if TYPE_CHECKING:
    from nexus3.skill.services import ServiceContainer

# Maximum allowed sleep duration (1 hour)
MAX_SLEEP_SECONDS = 3600


@base_skill_factory
class SleepSkill:
    """Sleep for a specified duration. Useful for testing parallel execution."""

    def __init__(self, services: "ServiceContainer | None" = None) -> None:
        pass  # Sleep doesn't need services

    @property
    def name(self) -> str:
        return "sleep"

    @property
    def description(self) -> str:
        return "Sleep for a specified number of seconds (for testing)"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "number",
                    "description": f"Number of seconds to sleep (max {MAX_SLEEP_SECONDS})",
                },
                "label": {
                    "type": "string",
                    "description": "Optional label to identify this sleep in output",
                },
            },
            "required": ["seconds"],
        }

    async def execute(
        self, seconds: float = 1.0, label: str = "", **kwargs: Any
    ) -> ToolResult:
        """Sleep for the specified duration."""
        if seconds < 0:
            return ToolResult(error="Sleep duration must be non-negative")
        if seconds > MAX_SLEEP_SECONDS:
            return ToolResult(
                error=f"Sleep duration {seconds}s exceeds maximum ({MAX_SLEEP_SECONDS}s)"
            )

        await asyncio.sleep(seconds)
        if label:
            return ToolResult(output=f"Slept {seconds}s ({label})")
        return ToolResult(output=f"Slept {seconds}s")


# Export factory for registration
sleep_skill_factory = SleepSkill.factory
