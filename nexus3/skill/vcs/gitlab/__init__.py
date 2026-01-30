"""GitLab skill implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nexus3.core.permissions import AgentPermissions
    from nexus3.skill.registry import SkillRegistry
    from nexus3.skill.services import ServiceContainer

from nexus3.skill.vcs.gitlab.permissions import can_use_gitlab

# Re-export for backwards compatibility
__all__ = ["can_use_gitlab", "register_gitlab_skills"]


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
        from nexus3.skill.vcs.gitlab.approval import GitLabApprovalSkill
        from nexus3.skill.vcs.gitlab.artifact import GitLabArtifactSkill
        from nexus3.skill.vcs.gitlab.board import GitLabBoardSkill
        from nexus3.skill.vcs.gitlab.branch import GitLabBranchSkill
        from nexus3.skill.vcs.gitlab.deploy_key import GitLabDeployKeySkill
        from nexus3.skill.vcs.gitlab.deploy_token import GitLabDeployTokenSkill
        from nexus3.skill.vcs.gitlab.discussion import GitLabDiscussionSkill
        from nexus3.skill.vcs.gitlab.draft_note import GitLabDraftSkill
        from nexus3.skill.vcs.gitlab.epic import GitLabEpicSkill
        from nexus3.skill.vcs.gitlab.feature_flag import GitLabFeatureFlagSkill
        from nexus3.skill.vcs.gitlab.issue import GitLabIssueSkill
        from nexus3.skill.vcs.gitlab.iteration import GitLabIterationSkill
        from nexus3.skill.vcs.gitlab.job import GitLabJobSkill
        from nexus3.skill.vcs.gitlab.label import GitLabLabelSkill
        from nexus3.skill.vcs.gitlab.milestone import GitLabMilestoneSkill
        from nexus3.skill.vcs.gitlab.mr import GitLabMRSkill
        from nexus3.skill.vcs.gitlab.pipeline import GitLabPipelineSkill
        from nexus3.skill.vcs.gitlab.repo import GitLabRepoSkill
        from nexus3.skill.vcs.gitlab.tag import GitLabTagSkill
        from nexus3.skill.vcs.gitlab.time_tracking import GitLabTimeSkill
        from nexus3.skill.vcs.gitlab.variable import GitLabVariableSkill
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
        # Phase 3: Code Review
        ("gitlab_approval", GitLabApprovalSkill),
        ("gitlab_draft", GitLabDraftSkill),
        ("gitlab_discussion", GitLabDiscussionSkill),
        # Phase 4: CI/CD
        ("gitlab_pipeline", GitLabPipelineSkill),
        ("gitlab_job", GitLabJobSkill),
        ("gitlab_artifact", GitLabArtifactSkill),
        ("gitlab_variable", GitLabVariableSkill),
        # Phase 5: Config
        ("gitlab_deploy_key", GitLabDeployKeySkill),
        ("gitlab_deploy_token", GitLabDeployTokenSkill),
        ("gitlab_feature_flag", GitLabFeatureFlagSkill),
    ]

    for name, skill_class in skills:
        registry.register(name, make_factory(skill_class))

    return len(skills)
