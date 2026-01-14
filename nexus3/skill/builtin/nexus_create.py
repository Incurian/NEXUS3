"""Nexus create skill for creating new agents on the server."""

import json
from typing import Any

from nexus3.client import ClientError, NexusClient
from nexus3.core.permissions import (
    AgentPermissions,
    get_builtin_presets,
    resolve_preset,
)
from nexus3.core.types import ToolResult
from nexus3.core.url_validator import UrlSecurityError, validate_url
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
        return (
            "Create a new agent on the Nexus server. "
            "Use initial_message to send a task immediately after creation."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "ID for the new agent (e.g., 'worker-1')",
                },
                "preset": {
                    "type": "string",
                    "description": "Permission preset: trusted, sandboxed, or worker",
                    "enum": ["trusted", "sandboxed", "worker"],
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory / sandbox root for the agent. "
                    "For sandboxed agents, this is the only path they can access.",
                },
                "allowed_write_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Paths where write_file/edit_file are allowed. "
                    "Must be within cwd. Defaults to empty (read-only) for sandboxed.",
                },
                "disable_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of tool names to disable for the new agent",
                },
                "model": {
                    "type": "string",
                    "description": "Model name/alias (e.g., 'fast', 'smart', or full ID)",
                },
                "initial_message": {
                    "type": "string",
                    "description": "Message to send to the agent immediately after creation. "
                    "The agent will process this and the response will be in the result.",
                },
                "port": {
                    "type": "integer",
                    "description": "Server port (default: 8765)",
                },
            },
            "required": ["agent_id"],
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
        preset: str | None = None,
        cwd: str | None = None,
        allowed_write_paths: list[str] | None = None,
        disable_tools: list[str] | None = None,
        model: str | None = None,
        initial_message: str | None = None,
        port: int | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Create a new agent on the Nexus server.

        Args:
            agent_id: ID for the new agent
            preset: Permission preset (trusted, sandboxed, worker)
            cwd: Working directory / sandbox root for the agent
            allowed_write_paths: Paths where writes are allowed (must be within cwd)
            disable_tools: List of tool names to disable
            model: Model name/alias to use (from config.models or full model ID)
            initial_message: Message to send to agent immediately after creation
            port: Optional server port (default: 8765)

        Returns:
            ToolResult with creation result or error (includes response if initial_message provided)
        """
        if not agent_id:
            return ToolResult(error="No agent_id provided")

        # Get parent permissions to enforce ceiling
        parent_perms: AgentPermissions | None = self._services.get("permissions")

        # Validate ceiling if parent has permissions and preset is specified
        if parent_perms and preset:
            builtin = get_builtin_presets()
            if preset in builtin:
                try:
                    requested = resolve_preset(preset)
                    if not parent_perms.can_grant(requested):
                        msg = f"Cannot create agent with '{preset}': exceeds ceiling"
                        return ToolResult(error=msg)
                except ValueError as e:
                    return ToolResult(error=f"Invalid preset: {e}")

        actual_port = self._get_port(port)
        url = f"http://127.0.0.1:{actual_port}"
        api_key = self._get_api_key(actual_port)

        try:
            validated_url = validate_url(url, allow_localhost=True)
        except UrlSecurityError as e:
            return ToolResult(error=f"URL validation failed: {e}")

        try:
            async with NexusClient(validated_url, api_key=api_key) as client:
                # Pass parent agent ID for server-side ceiling enforcement lookup
                parent_agent_id: str | None = self._services.get("agent_id")
                result = await client.create_agent(
                    agent_id,
                    preset=preset,
                    disable_tools=disable_tools,
                    parent_agent_id=parent_agent_id,
                    cwd=cwd,
                    allowed_write_paths=allowed_write_paths,
                    model=model,
                    initial_message=initial_message,
                )
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
