"""Visibility helpers for AgentPool MCP and GitLab integration.

This module contains extraction-only logic that was previously embedded in
`nexus3.rpc.pool`:
- visibility authorization adapters
- schema->VCS GitLab config conversion
- MCP/GitLab visibility authorization evaluation
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nexus3.core.authorization_kernel import (
    AdapterAuthorizationKernel,
    AuthorizationAction,
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResource,
    AuthorizationResourceType,
)
from nexus3.core.permissions import AgentPermissions
from nexus3.skill.vcs.config import GitLabConfig as VCSGitLabConfig
from nexus3.skill.vcs.config import GitLabInstance

if TYPE_CHECKING:
    from nexus3.config.schema import Config


class _McpVisibilityAuthorizationAdapter:
    """Kernel adapter for AgentPool MCP tool visibility checks."""

    def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision | None:
        if request.action != AuthorizationAction.TOOL_EXECUTE:
            return None
        if request.resource.resource_type != AuthorizationResourceType.TOOL:
            return None
        if request.context.get("mcp_level_allowed") is True:
            return AuthorizationDecision.allow(request, reason="mcp_level_allowed")
        return AuthorizationDecision.deny(request, reason="mcp_level_denied")


class _GitLabVisibilityAuthorizationAdapter:
    """Kernel adapter for AgentPool GitLab tool visibility checks."""

    def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision | None:
        if request.action != AuthorizationAction.TOOL_EXECUTE:
            return None
        if request.resource.resource_type != AuthorizationResourceType.TOOL:
            return None
        if request.context.get("gitlab_level_allowed") is True:
            return AuthorizationDecision.allow(request, reason="gitlab_level_allowed")
        return AuthorizationDecision.deny(request, reason="gitlab_level_denied")


def _convert_gitlab_config(config: Config) -> VCSGitLabConfig | None:
    """Convert schema GitLabConfig to VCS GitLabConfig.

    Returns None if no GitLab instances are configured or if gitlab is not
    properly configured (for example, mocked config in tests).
    """
    try:
        schema_config = config.gitlab
        if not hasattr(schema_config, "instances") or not isinstance(
            schema_config.instances, dict
        ):
            return None
        if not schema_config.instances:
            return None

        instances: dict[str, GitLabInstance] = {}
        for name, inst in schema_config.instances.items():
            instances[name] = GitLabInstance(
                url=inst.url,
                token=inst.token,
                token_env=inst.token_env,
                username=inst.username,
                email=inst.email,
                user_id=inst.user_id,
            )

        return VCSGitLabConfig(
            instances=instances,
            default_instance=schema_config.default_instance,
        )
    except (AttributeError, TypeError, ValueError):
        return None


def is_mcp_visible_for_agent(
    *,
    kernel: AdapterAuthorizationKernel,
    agent_id: str,
    permissions: AgentPermissions,
    check_stage: str,
) -> bool:
    """Evaluate MCP visibility through the provided authorization kernel."""
    from nexus3.mcp.permissions import can_use_mcp

    kernel_request = AuthorizationRequest(
        action=AuthorizationAction.TOOL_EXECUTE,
        resource=AuthorizationResource(
            resource_type=AuthorizationResourceType.TOOL,
            identifier="mcp_visibility",
        ),
        principal_id=agent_id,
        context={
            "mcp_level_allowed": can_use_mcp(permissions),
            "check_stage": check_stage,
        },
    )
    return kernel.authorize(kernel_request).allowed


def is_gitlab_visible_for_agent(
    *,
    kernel: AdapterAuthorizationKernel,
    agent_id: str,
    permissions: AgentPermissions,
    check_stage: str,
) -> bool:
    """Evaluate GitLab visibility through the provided authorization kernel."""
    from nexus3.skill.vcs.gitlab.permissions import can_use_gitlab

    kernel_request = AuthorizationRequest(
        action=AuthorizationAction.TOOL_EXECUTE,
        resource=AuthorizationResource(
            resource_type=AuthorizationResourceType.TOOL,
            identifier="gitlab_visibility",
        ),
        principal_id=agent_id,
        context={
            "gitlab_level_allowed": can_use_gitlab(permissions),
            "check_stage": check_stage,
        },
    )
    return kernel.authorize(kernel_request).allowed

