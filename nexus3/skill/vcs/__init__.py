"""VCS (Version Control Service) skills for GitLab and GitHub integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nexus3.core.permissions import AgentPermissions
    from nexus3.skill.registry import SkillRegistry
    from nexus3.skill.services import ServiceContainer


def register_vcs_skills(
    registry: SkillRegistry,
    services: ServiceContainer,
    permissions: AgentPermissions | None,
) -> int:
    """
    Register VCS skills based on configuration and permissions.

    Only registers skills for configured platforms. Skips registration
    entirely if permission level is SANDBOXED (network blocked).

    Returns total number of skills registered.
    """
    count = 0

    # GitLab skills
    gitlab_config = services.get_gitlab_config()
    if gitlab_config and gitlab_config.instances:
        from nexus3.skill.vcs.gitlab import register_gitlab_skills
        count += register_gitlab_skills(registry, services, permissions)

    # GitHub skills (future)
    # github_config = services.get_github_config()
    # if github_config and github_config.instances:
    #     from nexus3.skill.vcs.github import register_github_skills
    #     count += register_github_skills(registry, services, permissions)

    return count
