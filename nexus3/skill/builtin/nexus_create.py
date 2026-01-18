"""Nexus create skill for creating new agents on the server."""

from pathlib import Path
from typing import Any

from nexus3.core.permissions import (
    AgentPermissions,
    get_builtin_presets,
    resolve_preset,
)
from nexus3.core.types import ToolResult
from nexus3.core.validation import ValidationError, validate_agent_id
from nexus3.skill.base import NexusSkill, nexus_skill_factory


class NexusCreateSkill(NexusSkill):
    """Skill that creates a new agent on the Nexus server."""

    @property
    def name(self) -> str:
        return "nexus_create"

    @property
    def description(self) -> str:
        return (
            "Create a new agent on the Nexus server. "
            "IMPORTANT: Default preset is 'sandboxed' (read-only in cwd). "
            "To enable writes, pass allowed_write_paths. "
            "To get full access, pass preset='trusted' explicitly."
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
                    "description": "Permission preset. Default: 'sandboxed' (cwd-only reads, "
                    "no writes unless allowed_write_paths specified). "
                    "Use 'trusted' for full read access (writes still need explicit paths or cwd).",
                    "enum": ["trusted", "sandboxed", "worker"],
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory / sandbox root. "
                    "CRITICAL for sandboxed agents: this is the ONLY path they can read. "
                    "Defaults to parent's cwd if not specified.",
                },
                "allowed_write_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "REQUIRED for writes on sandboxed agents. "
                    "Without this, all write tools are DISABLED. "
                    "Must be within cwd for sandboxed agents.",
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
                    "By default returns immediately with initial_request_id. "
                    "Set wait_for_initial_response=true to block for response.",
                },
                "wait_for_initial_response": {
                    "type": "boolean",
                    "description": "If true, block until initial_message response is ready "
                    "and include it in result. Default false (returns immediately).",
                },
                "port": {
                    "type": "integer",
                    "description": "Server port (default: 8765)",
                },
            },
            "required": ["agent_id"],
        }

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
        wait_for_initial_response: bool = False,
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

        try:
            validate_agent_id(agent_id)
        except ValidationError as e:
            return ToolResult(error=f"Invalid agent_id: {e.message}")

        # Validate model parameter if provided
        if model:
            model = model.strip()
            if not model:
                return ToolResult(error="Model cannot be empty or whitespace")
            if len(model) > 128:
                return ToolResult(error="Model name too long (max 128 chars)")
            # Disallow suspicious patterns (path traversal, null bytes)
            if "\x00" in model or ".." in model:
                return ToolResult(error="Invalid model name")

        # Get parent permissions to enforce ceiling (local validation for early feedback)
        parent_perms: AgentPermissions | None = self._services.get("permissions")

        # Validate ceiling if parent has permissions and preset is specified
        # Note: Server also validates, this provides early feedback to user
        if parent_perms and preset:
            builtin = get_builtin_presets()
            if preset in builtin:
                try:
                    # Resolve cwd for ceiling validation, matching server-side logic:
                    # - If cwd provided: use it
                    # - If not: inherit from parent (server does this too)
                    if cwd:
                        cwd_path: Path | None = Path(cwd)
                    else:
                        cwd_path = self._services.get("cwd")  # Inherit parent's cwd
                    requested = resolve_preset(preset, cwd=cwd_path)
                    if not parent_perms.can_grant(requested):
                        msg = f"Cannot create agent with '{preset}': exceeds ceiling"
                        return ToolResult(error=msg)
                except ValueError as e:
                    return ToolResult(error=f"Invalid preset: {e}")

        # Get parent agent ID for server-side ceiling enforcement lookup
        parent_agent_id: str | None = self._services.get("agent_id")

        # Use _execute_with_client for DirectAgentAPI optimization
        # agent_id=None for global method (POST /)
        async def create_op(client: Any) -> dict[str, Any]:
            return await client.create_agent(
                agent_id,
                preset=preset,
                disable_tools=disable_tools,
                parent_agent_id=parent_agent_id,
                cwd=cwd,
                allowed_write_paths=allowed_write_paths,
                model=model,
                initial_message=initial_message,
                wait_for_initial_response=wait_for_initial_response,
            )

        return await self._execute_with_client(
            port=port,
            operation=create_op,
            agent_id=None,  # Global method, not agent-specific
        )


# Factory for dependency injection
nexus_create_factory = nexus_skill_factory(NexusCreateSkill)
