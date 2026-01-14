"""Nexus shutdown skill for requesting graceful shutdown of the Nexus server."""

from typing import Any

from nexus3.core.types import ToolResult
from nexus3.skill.base import NexusSkill, nexus_skill_factory


class NexusShutdownSkill(NexusSkill):
    """Skill that requests graceful shutdown of the Nexus server.

    Connects to a running Nexus JSON-RPC server and requests shutdown.
    This stops the entire server, not just a single agent.
    """

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

    async def execute(self, port: int | None = None, **kwargs: Any) -> ToolResult:
        """Request shutdown of the Nexus server."""
        return await self._execute_with_client(
            port=port,
            agent_id=None,
            operation=lambda client: client.shutdown_server()
        )


# Factory for dependency injection
nexus_shutdown_factory = nexus_skill_factory(NexusShutdownSkill)
