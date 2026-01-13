"""Tests for git skill."""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nexus3.core.permissions import PermissionLevel
from nexus3.skill.builtin.git import (
    BLOCKED_PATTERNS,
    READ_ONLY_COMMANDS,
    GitSkill,
    git_factory,
)
from nexus3.skill.services import ServiceContainer


class TestGitSkillValidation:
    """Tests for git command validation."""

    @pytest.fixture
    def sandboxed_skill(self) -> GitSkill:
        return GitSkill(permission_level=PermissionLevel.SANDBOXED)

    @pytest.fixture
    def trusted_skill(self) -> GitSkill:
        return GitSkill(permission_level=PermissionLevel.TRUSTED)

    @pytest.fixture
    def yolo_skill(self) -> GitSkill:
        return GitSkill(permission_level=PermissionLevel.YOLO)

    def test_empty_command_rejected(self, trusted_skill: GitSkill) -> None:
        """Empty command is rejected."""
        allowed, error = trusted_skill._validate_command("")
        assert not allowed
        assert "No git command" in error

    def test_read_only_commands_allowed_in_sandboxed(
        self, sandboxed_skill: GitSkill
    ) -> None:
        """Read-only commands allowed in SANDBOXED mode."""
        for cmd in READ_ONLY_COMMANDS:
            allowed, error = sandboxed_skill._validate_command(cmd)
            assert allowed, f"Command '{cmd}' should be allowed"

    def test_write_commands_blocked_in_sandboxed(
        self, sandboxed_skill: GitSkill
    ) -> None:
        """Write commands blocked in SANDBOXED mode."""
        write_commands = ["add .", "commit -m 'test'", "push", "pull"]
        for cmd in write_commands:
            allowed, error = sandboxed_skill._validate_command(cmd)
            assert not allowed, f"Command '{cmd}' should be blocked"
            assert "read-only" in error.lower()

    def test_write_commands_allowed_in_trusted(
        self, trusted_skill: GitSkill
    ) -> None:
        """Write commands allowed in TRUSTED mode."""
        write_commands = ["add .", "commit -m 'test'", "push", "pull"]
        for cmd in write_commands:
            allowed, error = trusted_skill._validate_command(cmd)
            assert allowed, f"Command '{cmd}' should be allowed"

    def test_dangerous_commands_blocked_in_trusted(
        self, trusted_skill: GitSkill
    ) -> None:
        """Dangerous commands blocked in TRUSTED mode."""
        dangerous = [
            "reset --hard HEAD~1",
            "push --force",
            "push -f",
            "clean -fd",
            "rebase -i HEAD~3",
        ]
        for cmd in dangerous:
            allowed, error = trusted_skill._validate_command(cmd)
            assert not allowed, f"Command '{cmd}' should be blocked"
            assert "blocked" in error.lower()

    def test_dangerous_commands_allowed_in_yolo(
        self, yolo_skill: GitSkill
    ) -> None:
        """All commands allowed in YOLO mode."""
        dangerous = [
            "reset --hard HEAD~1",
            "push --force",
            "clean -fd",
        ]
        for cmd in dangerous:
            allowed, error = yolo_skill._validate_command(cmd)
            assert allowed, f"Command '{cmd}' should be allowed in YOLO"


class TestGitSkillExecution:
    """Tests for git command execution."""

    @pytest.fixture
    def skill(self) -> GitSkill:
        return GitSkill()

    @pytest.mark.asyncio
    async def test_command_required(self, skill: GitSkill) -> None:
        """Returns error when command not provided."""
        result = await skill.execute(command="")
        assert result.error
        assert "No git command" in result.error

    @pytest.mark.asyncio
    async def test_invalid_directory(self, skill: GitSkill) -> None:
        """Returns error for non-existent directory."""
        result = await skill.execute(command="status", cwd="/nonexistent/path")
        assert result.error
        assert "not found" in result.error.lower() or "outside" in result.error.lower()

    @pytest.mark.asyncio
    async def test_sandbox_enforced(self, tmp_path: Path) -> None:
        """Sandbox is enforced when allowed_paths set."""
        skill = GitSkill(allowed_paths=[tmp_path])
        result = await skill.execute(command="status", cwd="/etc")
        assert result.error
        assert "outside" in result.error.lower() or "sandbox" in result.error.lower()

    @pytest.mark.asyncio
    async def test_git_status_in_repo(self, tmp_path: Path) -> None:
        """Git status works in a git repository."""
        # Initialize a git repo
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)

        skill = GitSkill()
        result = await skill.execute(command="status", cwd=str(tmp_path))

        # Should succeed (not an error)
        assert not result.error
        output = json.loads(result.output)
        assert output["success"] is True
        assert "branch" in output.get("parsed", {}) or "output" in output

    @pytest.mark.asyncio
    async def test_git_not_a_repo(self, tmp_path: Path) -> None:
        """Git returns error when not in a repo."""
        skill = GitSkill()
        result = await skill.execute(command="status", cwd=str(tmp_path))

        # Should return git error
        assert result.error
        assert "not a git repository" in result.error.lower()


class TestGitSkillOutputParsing:
    """Tests for git output parsing."""

    @pytest.fixture
    def skill(self) -> GitSkill:
        return GitSkill()

    def test_parse_status_branch(self, skill: GitSkill) -> None:
        """Parses branch from status output."""
        output = "On branch main\nYour branch is up to date."
        parsed = skill._parse_status_output(output)
        assert parsed["branch"] == "main"

    def test_parse_status_ahead_behind(self, skill: GitSkill) -> None:
        """Parses ahead/behind counts."""
        output = "On branch main\nYour branch is ahead of 'origin/main' by 3 commits."
        parsed = skill._parse_status_output(output)
        assert parsed["ahead"] == 3

    def test_parse_log_commits(self, skill: GitSkill) -> None:
        """Parses commit info from log output."""
        output = """commit abc123
Author: Test <test@example.com>
Date:   Mon Jan 1 00:00:00 2024

    Initial commit

commit def456
Author: Test <test@example.com>
Date:   Tue Jan 2 00:00:00 2024

    Second commit"""

        commits = skill._parse_log_output(output)
        assert len(commits) == 2
        assert commits[0]["sha"] == "abc123"
        assert commits[0]["message"] == "Initial commit"


class TestGitSkillFactory:
    """Tests for git factory."""

    def test_factory_creates_skill(self) -> None:
        """Factory creates skill with configuration."""
        services = ServiceContainer()
        services.register("allowed_paths", [Path("/tmp")])

        skill = git_factory(services)
        assert isinstance(skill, GitSkill)
        assert skill._allowed_paths == [Path("/tmp")]

    def test_factory_gets_permission_level(self) -> None:
        """Factory gets permission level from permissions object."""
        services = ServiceContainer()

        # Mock permissions object
        mock_perms = MagicMock()
        mock_perms.effective_policy.level = PermissionLevel.SANDBOXED
        services.register("permissions", mock_perms)

        skill = git_factory(services)
        assert skill._permission_level == PermissionLevel.SANDBOXED

    def test_factory_defaults_to_trusted(self) -> None:
        """Factory defaults to TRUSTED when no permissions."""
        services = ServiceContainer()
        skill = git_factory(services)
        assert skill._permission_level == PermissionLevel.TRUSTED


class TestGitSkillRegistration:
    """Tests for git skill registration."""

    def test_git_registered(self) -> None:
        """Git skill is registered."""
        from nexus3.skill.builtin.registration import register_builtin_skills
        from nexus3.skill.registry import SkillRegistry

        services = ServiceContainer()
        registry = SkillRegistry(services)
        register_builtin_skills(registry)

        skill = registry.get("git")
        assert skill is not None
        assert skill.name == "git"
