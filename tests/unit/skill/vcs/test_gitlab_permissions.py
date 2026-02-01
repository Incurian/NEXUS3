"""Tests for GitLab-specific permission logic."""

from pathlib import Path

import pytest

from nexus3.core.allowances import SessionAllowances
from nexus3.core.permissions import AgentPermissions, PermissionLevel, PermissionPolicy
from nexus3.skill.vcs.gitlab.permissions import (
    GITLAB_DESTRUCTIVE_ACTIONS,
    GITLAB_READ_ONLY_ACTIONS,
    can_use_gitlab,
    is_gitlab_read_only,
    requires_gitlab_confirmation,
)


class TestCanUseGitlab:
    """Tests for can_use_gitlab() function."""

    def test_yolo_can_use_gitlab(self, tmp_path: Path) -> None:
        """YOLO agents can use GitLab tools."""
        policy = PermissionPolicy(level=PermissionLevel.YOLO, cwd=tmp_path)
        permissions = AgentPermissions(base_preset="yolo", effective_policy=policy)

        assert can_use_gitlab(permissions) is True

    def test_trusted_can_use_gitlab(self, tmp_path: Path) -> None:
        """TRUSTED agents can use GitLab tools."""
        policy = PermissionPolicy(level=PermissionLevel.TRUSTED, cwd=tmp_path)
        permissions = AgentPermissions(base_preset="trusted", effective_policy=policy)

        assert can_use_gitlab(permissions) is True

    def test_sandboxed_cannot_use_gitlab(self, tmp_path: Path) -> None:
        """SANDBOXED agents cannot use GitLab tools."""
        policy = PermissionPolicy(
            level=PermissionLevel.SANDBOXED,
            cwd=tmp_path,
            allowed_paths=[tmp_path],
        )
        permissions = AgentPermissions(base_preset="sandboxed", effective_policy=policy)

        assert can_use_gitlab(permissions) is False

    def test_none_permissions_cannot_use_gitlab(self) -> None:
        """None permissions cannot use GitLab tools."""
        assert can_use_gitlab(None) is False


class TestIsGitlabReadOnly:
    """Tests for is_gitlab_read_only() function."""

    @pytest.mark.parametrize("action", [
        "list",
        "get",
        "search",
        "diff",
        "commits",
        "pipelines",
        "jobs",
        "variables",
        "log",
        "status",
        "browse",
        "list-protected",
        "list-user-lists",
        "cadences",
    ])
    def test_read_only_actions(self, action: str) -> None:
        """Read-only actions are correctly identified."""
        assert is_gitlab_read_only(action) is True

    @pytest.mark.parametrize("action", [
        "create",
        "update",
        "delete",
        "close",
        "reopen",
        "merge",
        "approve",
        "unapprove",
        "comment",
        "reply",
        "resolve",
        "unresolve",
        "publish",
        "add",
        "remove",
        "spend",
        "estimate",
        "reset",
        "retry",
        "cancel",
        "play",
        "erase",
        "download",
        "download-file",
        "download-ref",
        "keep",
        "protect",
        "unprotect",
        "enable",
        "create-user-list",
        "update-user-list",
        "delete-user-list",
        "fork",
    ])
    def test_destructive_actions(self, action: str) -> None:
        """Destructive actions are not read-only."""
        assert is_gitlab_read_only(action) is False

    def test_unknown_action(self) -> None:
        """Unknown actions are not read-only (fail-safe)."""
        assert is_gitlab_read_only("unknown_action") is False
        assert is_gitlab_read_only("") is False


class TestReadOnlyDestructiveConsistency:
    """Tests to ensure read-only and destructive sets are disjoint."""

    def test_no_overlap(self) -> None:
        """Read-only and destructive action sets don't overlap."""
        overlap = GITLAB_READ_ONLY_ACTIONS & GITLAB_DESTRUCTIVE_ACTIONS
        assert overlap == set(), f"Overlapping actions: {overlap}"

    def test_all_read_only_are_documented(self) -> None:
        """All read-only actions should be in the frozenset."""
        expected = {
            "list", "get", "search", "diff", "commits", "pipelines",
            "jobs", "variables", "log", "status", "browse",
            "list-protected", "list-user-lists", "cadences",
        }
        assert GITLAB_READ_ONLY_ACTIONS == expected

    def test_all_destructive_are_documented(self) -> None:
        """All destructive actions should be in the frozenset."""
        expected = {
            "create", "update", "delete", "close", "reopen", "merge",
            "approve", "unapprove", "comment", "reply", "resolve",
            "unresolve", "publish", "add", "remove", "spend", "estimate",
            "reset", "retry", "cancel", "play", "erase", "download",
            "download-file", "download-ref", "keep", "protect", "unprotect",
            "enable", "create-user-list", "update-user-list", "delete-user-list",
            "fork",
        }
        assert GITLAB_DESTRUCTIVE_ACTIONS == expected


class TestRequiresGitlabConfirmation:
    """Tests for requires_gitlab_confirmation() function."""

    @pytest.fixture
    def yolo_permissions(self, tmp_path: Path) -> AgentPermissions:
        """YOLO permissions."""
        policy = PermissionPolicy(level=PermissionLevel.YOLO, cwd=tmp_path)
        return AgentPermissions(base_preset="yolo", effective_policy=policy)

    @pytest.fixture
    def trusted_permissions(self, tmp_path: Path) -> AgentPermissions:
        """TRUSTED permissions."""
        policy = PermissionPolicy(level=PermissionLevel.TRUSTED, cwd=tmp_path)
        return AgentPermissions(base_preset="trusted", effective_policy=policy)

    @pytest.fixture
    def sandboxed_permissions(self, tmp_path: Path) -> AgentPermissions:
        """SANDBOXED permissions."""
        policy = PermissionPolicy(
            level=PermissionLevel.SANDBOXED,
            cwd=tmp_path,
            allowed_paths=[tmp_path],
        )
        return AgentPermissions(base_preset="sandboxed", effective_policy=policy)

    def test_none_permissions_requires_confirmation(self) -> None:
        """None permissions require confirmation (defense in depth)."""
        assert requires_gitlab_confirmation(
            permissions=None,
            skill_name="gitlab_issue",
            instance_host="gitlab.com",
            action="create",
        ) is True

    def test_yolo_never_requires_confirmation(self, yolo_permissions: AgentPermissions) -> None:
        """YOLO mode never requires confirmation."""
        # Read-only action
        assert requires_gitlab_confirmation(
            permissions=yolo_permissions,
            skill_name="gitlab_issue",
            instance_host="gitlab.com",
            action="list",
        ) is False

        # Destructive action
        assert requires_gitlab_confirmation(
            permissions=yolo_permissions,
            skill_name="gitlab_issue",
            instance_host="gitlab.com",
            action="create",
        ) is False

    def test_trusted_read_only_no_confirmation(self, trusted_permissions: AgentPermissions) -> None:
        """TRUSTED mode doesn't require confirmation for read-only actions."""
        assert requires_gitlab_confirmation(
            permissions=trusted_permissions,
            skill_name="gitlab_issue",
            instance_host="gitlab.com",
            action="list",
        ) is False

        assert requires_gitlab_confirmation(
            permissions=trusted_permissions,
            skill_name="gitlab_mr",
            instance_host="gitlab.com",
            action="get",
        ) is False

    def test_trusted_destructive_requires_confirmation(self, trusted_permissions: AgentPermissions) -> None:
        """TRUSTED mode requires confirmation for destructive actions."""
        assert requires_gitlab_confirmation(
            permissions=trusted_permissions,
            skill_name="gitlab_issue",
            instance_host="gitlab.com",
            action="create",
        ) is True

        assert requires_gitlab_confirmation(
            permissions=trusted_permissions,
            skill_name="gitlab_mr",
            instance_host="gitlab.com",
            action="merge",
        ) is True

    def test_trusted_with_session_allowance(self, trusted_permissions: AgentPermissions) -> None:
        """TRUSTED mode skips confirmation if skill@instance is allowed in session."""
        # Add allowance
        trusted_permissions.session_allowances.add_gitlab_skill(
            "gitlab_issue", "gitlab.com"
        )

        # Now destructive action doesn't require confirmation
        assert requires_gitlab_confirmation(
            permissions=trusted_permissions,
            skill_name="gitlab_issue",
            instance_host="gitlab.com",
            action="create",
        ) is False

    def test_session_allowance_is_skill_specific(self, trusted_permissions: AgentPermissions) -> None:
        """Session allowance for one skill doesn't apply to another."""
        # Allow gitlab_issue
        trusted_permissions.session_allowances.add_gitlab_skill(
            "gitlab_issue", "gitlab.com"
        )

        # gitlab_issue doesn't need confirmation
        assert requires_gitlab_confirmation(
            permissions=trusted_permissions,
            skill_name="gitlab_issue",
            instance_host="gitlab.com",
            action="create",
        ) is False

        # gitlab_mr still needs confirmation
        assert requires_gitlab_confirmation(
            permissions=trusted_permissions,
            skill_name="gitlab_mr",
            instance_host="gitlab.com",
            action="create",
        ) is True

    def test_session_allowance_is_instance_specific(self, trusted_permissions: AgentPermissions) -> None:
        """Session allowance for one instance doesn't apply to another."""
        # Allow gitlab_issue on gitlab.com
        trusted_permissions.session_allowances.add_gitlab_skill(
            "gitlab_issue", "gitlab.com"
        )

        # gitlab.com doesn't need confirmation
        assert requires_gitlab_confirmation(
            permissions=trusted_permissions,
            skill_name="gitlab_issue",
            instance_host="gitlab.com",
            action="create",
        ) is False

        # work.gitlab.com still needs confirmation
        assert requires_gitlab_confirmation(
            permissions=trusted_permissions,
            skill_name="gitlab_issue",
            instance_host="work.gitlab.com",
            action="create",
        ) is True


class TestSessionAllowancesGitlab:
    """Tests for GitLab-specific session allowances."""

    def test_is_gitlab_skill_allowed(self) -> None:
        """is_gitlab_skill_allowed checks skill@instance key."""
        allowances = SessionAllowances()

        assert allowances.is_gitlab_skill_allowed("gitlab_issue", "gitlab.com") is False

        allowances.add_gitlab_skill("gitlab_issue", "gitlab.com")

        assert allowances.is_gitlab_skill_allowed("gitlab_issue", "gitlab.com") is True
        assert allowances.is_gitlab_skill_allowed("gitlab_mr", "gitlab.com") is False
        assert allowances.is_gitlab_skill_allowed("gitlab_issue", "other.com") is False

    def test_add_gitlab_skill(self) -> None:
        """add_gitlab_skill adds to gitlab_skills set."""
        allowances = SessionAllowances()

        allowances.add_gitlab_skill("gitlab_mr", "work.gitlab.com")

        assert "gitlab_mr@work.gitlab.com" in allowances.gitlab_skills

    def test_gitlab_skills_in_serialization(self) -> None:
        """GitLab skills are serialized/deserialized."""
        allowances = SessionAllowances()
        allowances.add_gitlab_skill("gitlab_issue", "gitlab.com")
        allowances.add_gitlab_skill("gitlab_mr", "work.gitlab.com")

        # Serialize
        data = allowances.to_dict()
        assert "gitlab_skills" in data
        assert set(data["gitlab_skills"]) == {
            "gitlab_issue@gitlab.com",
            "gitlab_mr@work.gitlab.com",
        }

        # Deserialize
        restored = SessionAllowances.from_dict(data)
        assert restored.is_gitlab_skill_allowed("gitlab_issue", "gitlab.com")
        assert restored.is_gitlab_skill_allowed("gitlab_mr", "work.gitlab.com")
