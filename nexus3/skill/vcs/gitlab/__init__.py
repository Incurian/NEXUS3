"""GitLab skill implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nexus3.core.permissions import AgentPermissions
    from nexus3.skill.registry import SkillRegistry
    from nexus3.skill.services import ServiceContainer

from nexus3.core.permissions import PermissionLevel


def can_use_gitlab(permissions: AgentPermissions | None) -> bool:
    """Check if agent can use GitLab tools.

    GitLab tools require TRUSTED+ (no SANDBOXED).
    Returns True if YOLO or TRUSTED, False otherwise.
    """
    if permissions is None:
        return False
    level = permissions.effective_policy.level
    return level in (PermissionLevel.YOLO, PermissionLevel.TRUSTED)


def register_gitlab_skills(
    registry: SkillRegistry,
    services: ServiceContainer,
    permissions: AgentPermissions | None,
) -> int:
    """
    Register GitLab skills if configured and permitted.

    Returns 0 if:
    - Permission level is SANDBOXED (network blocked)
    - No GitLab instances configured
    """
    # Check permission level first (defense in depth)
    if not can_use_gitlab(permissions):
        return 0  # SANDBOXED or no permissions

    # Check configuration
    gitlab_config = services.get_gitlab_config()
    if not gitlab_config or not gitlab_config.instances:
        return 0  # No GitLab configured

    # Import skill classes (deferred to avoid circular imports)
    # Skills may not exist yet during phased implementation
    try:
        # Phase 1: Foundation
        from nexus3.skill.vcs.gitlab.board import GitLabBoardSkill
        from nexus3.skill.vcs.gitlab.branch import GitLabBranchSkill

        # Phase 2: Project Management
        from nexus3.skill.vcs.gitlab.epic import GitLabEpicSkill
        from nexus3.skill.vcs.gitlab.issue import GitLabIssueSkill
        from nexus3.skill.vcs.gitlab.iteration import GitLabIterationSkill
        from nexus3.skill.vcs.gitlab.label import GitLabLabelSkill
        from nexus3.skill.vcs.gitlab.milestone import GitLabMilestoneSkill
        from nexus3.skill.vcs.gitlab.mr import GitLabMRSkill
        from nexus3.skill.vcs.gitlab.repo import GitLabRepoSkill
        from nexus3.skill.vcs.gitlab.tag import GitLabTagSkill
        from nexus3.skill.vcs.gitlab.time_tracking import GitLabTimeSkill
    except ImportError:
        # Skills not yet implemented - return 0 during phased development
        return 0

    # Create factories that capture services and config
    def make_factory(skill_class):
        def factory(svc: ServiceContainer):
            config = svc.get_gitlab_config()
            if not config:
                raise ValueError("GitLab not configured")
            return skill_class(svc, config)
        return factory

    # Register all GitLab skill factories
    skills = [
        # Phase 1: Foundation
        ("gitlab_repo", GitLabRepoSkill),
        ("gitlab_issue", GitLabIssueSkill),
        ("gitlab_mr", GitLabMRSkill),
        ("gitlab_label", GitLabLabelSkill),
        ("gitlab_branch", GitLabBranchSkill),
        ("gitlab_tag", GitLabTagSkill),
        # Phase 2: Project Management
        ("gitlab_epic", GitLabEpicSkill),
        ("gitlab_iteration", GitLabIterationSkill),
        ("gitlab_milestone", GitLabMilestoneSkill),
        ("gitlab_board", GitLabBoardSkill),
        ("gitlab_time", GitLabTimeSkill),
    ]

    for name, skill_class in skills:
        registry.register(name, make_factory(skill_class))

    return len(skills)
