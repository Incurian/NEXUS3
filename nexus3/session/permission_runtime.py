"""Permission runtime helpers extracted from Session."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from nexus3.core.authorization_kernel import (
    AdapterAuthorizationKernel,
    AuthorizationAction,
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResource,
    AuthorizationResourceType,
)
from nexus3.core.permissions import AgentPermissions, ConfirmationResult
from nexus3.core.types import ToolCall, ToolResult
from nexus3.session.confirmation import ConfirmationController

if TYPE_CHECKING:
    from nexus3.skill.base import Skill
    from nexus3.skill.services import ServiceContainer


ConfirmationCallback = Callable[[ToolCall, Path | None, Path], Awaitable[ConfirmationResult]]


class _McpLevelAuthorizationAdapter:
    """Kernel adapter mirroring MCP level gating in session tool execution."""

    def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision | None:
        if request.action != AuthorizationAction.TOOL_EXECUTE:
            return None
        if request.resource.resource_type != AuthorizationResourceType.TOOL:
            return None

        if bool(request.context.get("mcp_level_allowed", False)):
            return AuthorizationDecision.allow(request, reason="mcp_level_allowed")
        return AuthorizationDecision.deny(request, reason="mcp_level_denied")


class _GitLabLevelAuthorizationAdapter:
    """Kernel adapter mirroring GitLab level gating in session tool execution."""

    def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision | None:
        if request.action != AuthorizationAction.TOOL_EXECUTE:
            return None
        if request.resource.resource_type != AuthorizationResourceType.TOOL:
            return None

        if bool(request.context.get("gitlab_level_allowed", False)):
            return AuthorizationDecision.allow(request, reason="gitlab_level_allowed")
        return AuthorizationDecision.deny(request, reason="gitlab_level_denied")


async def handle_mcp_permissions(
    tool_call: ToolCall,
    skill: Skill | None,
    server_name: str,
    permissions: AgentPermissions,
    *,
    authorization_kernel: AdapterAuthorizationKernel,
    confirmation: ConfirmationController,
    services: ServiceContainer | None,
    on_confirm: ConfirmationCallback | None,
) -> ToolResult | None:
    """Handle MCP-specific permission checks and confirmation."""
    from nexus3.core.permissions import PermissionLevel
    from nexus3.mcp.permissions import can_use_mcp

    mcp_level_allowed = can_use_mcp(permissions)
    requester_id = services.get("agent_id") if services else None
    principal_id = requester_id if isinstance(requester_id, str) and requester_id else "unknown"
    mcp_registry = services.get_mcp_registry() if services else None
    kernel_request = AuthorizationRequest(
        action=AuthorizationAction.TOOL_EXECUTE,
        resource=AuthorizationResource(
            resource_type=AuthorizationResourceType.TOOL,
            identifier=tool_call.name,
        ),
        principal_id=principal_id,
        context={"mcp_level_allowed": mcp_level_allowed},
    )
    kernel_decision = authorization_kernel.authorize(kernel_request)
    if not kernel_decision.allowed:
        return ToolResult(error="MCP tools require TRUSTED or YOLO permission level")

    if not skill:
        return None  # Let caller handle unknown skill

    if (
        isinstance(requester_id, str)
        and requester_id
        and mcp_registry is not None
        and mcp_registry.get(server_name, agent_id=requester_id) is None
    ):
        return ToolResult(error=f"Unknown skill: {tool_call.name}")

    # Check if confirmation needed for this MCP tool/server
    level = permissions.effective_policy.level
    if level != PermissionLevel.YOLO:
        allowances = permissions.session_allowances
        server_allowed = allowances.is_mcp_server_allowed(server_name)
        tool_allowed = allowances.is_mcp_tool_allowed(tool_call.name)

        if not server_allowed and not tool_allowed:
            agent_cwd = services.get_cwd() if services else Path.cwd()
            result = await confirmation.request(tool_call, None, agent_cwd, on_confirm)

            if result == ConfirmationResult.DENY:
                return ToolResult(error="MCP tool action denied by user")

            confirmation.apply_mcp_result(permissions, result, tool_call.name, server_name)

    return None


async def handle_gitlab_permissions(
    tool_call: ToolCall,
    skill: Skill | None,
    permissions: AgentPermissions,
    *,
    authorization_kernel: AdapterAuthorizationKernel,
    confirmation: ConfirmationController,
    services: ServiceContainer | None,
    on_confirm: ConfirmationCallback | None,
) -> ToolResult | None:
    """Handle GitLab-specific permission checks and confirmation."""
    from nexus3.skill.vcs.gitlab.permissions import (
        can_use_gitlab,
        requires_gitlab_confirmation,
    )

    gitlab_level_allowed = can_use_gitlab(permissions)
    requester_id = services.get("agent_id") if services else None
    principal_id = requester_id if isinstance(requester_id, str) and requester_id else "unknown"
    kernel_request = AuthorizationRequest(
        action=AuthorizationAction.TOOL_EXECUTE,
        resource=AuthorizationResource(
            resource_type=AuthorizationResourceType.TOOL,
            identifier=tool_call.name,
        ),
        principal_id=principal_id,
        context={"gitlab_level_allowed": gitlab_level_allowed},
    )
    kernel_decision = authorization_kernel.authorize(kernel_request)
    if not kernel_decision.allowed:
        return ToolResult(error="GitLab tools require TRUSTED or YOLO permission level")

    if not skill:
        return None  # Let caller handle unknown skill

    # Extract action and instance from arguments
    action = tool_call.arguments.get("action", "")
    instance_name = tool_call.arguments.get("instance")

    # Resolve instance to get host
    gitlab_config = services.get_gitlab_config() if services else None
    if not gitlab_config:
        return None  # Should not happen if skill exists

    instance = gitlab_config.get_instance(instance_name)
    if not instance:
        # Let skill handle the error (will produce better error message)
        return None

    instance_host = instance.host

    # Check if confirmation needed
    if requires_gitlab_confirmation(permissions, tool_call.name, instance_host, action):
        agent_cwd = services.get_cwd() if services else Path.cwd()
        result = await confirmation.request(tool_call, None, agent_cwd, on_confirm)

        if result == ConfirmationResult.DENY:
            return ToolResult(error="GitLab action denied by user")

        confirmation.apply_gitlab_result(permissions, result, tool_call.name, instance_host)

    return None
