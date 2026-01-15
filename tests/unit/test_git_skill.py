"""Tests for git skill."""

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from nexus3.core.permissions import PermissionLevel
from nexus3.skill.builtin.git import (
    DANGEROUS_FLAGS,
    READ_ONLY_COMMANDS,
    GitSkill,
    git_factory,
)
from nexus3.skill.services import ServiceContainer


class MockServiceContainer:
    """Mock ServiceContainer for testing skills."""

    def __init__(self, **kwargs: Any) -> None:
        self._data = kwargs

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def get_tool_allowed_paths(self, tool_name: str) -> list[Path] | None:
        """Return allowed_paths from data."""
        return self._data.get("allowed_paths")

    def get_permission_level(self) -> PermissionLevel | None:
        """Return permission_level from data."""
        return self._data.get("permission_level")


class TestGitSkillValidation:
    """Tests for git command validation."""

    @pytest.fixture
    def sandboxed_skill(self) -> GitSkill:
        services = MockServiceContainer(permission_level=PermissionLevel.SANDBOXED)
        return GitSkill(services)

    @pytest.fixture
    def trusted_skill(self) -> GitSkill:
        services = MockServiceContainer(permission_level=PermissionLevel.TRUSTED)
        return GitSkill(services)

    @pytest.fixture
    def yolo_skill(self) -> GitSkill:
        services = MockServiceContainer(permission_level=PermissionLevel.YOLO)
        return GitSkill(services)

    def test_empty_command_rejected(self, trusted_skill: GitSkill) -> None:
        """Empty command is rejected."""
        allowed, args, error = trusted_skill._validate_command("")
        assert not allowed
        assert args is None
        assert "No git command" in error

    def test_read_only_commands_allowed_in_sandboxed(
        self, sandboxed_skill: GitSkill
    ) -> None:
        """Read-only commands allowed in SANDBOXED mode."""
        for cmd in READ_ONLY_COMMANDS:
            allowed, args, error = sandboxed_skill._validate_command(cmd)
            assert allowed, f"Command '{cmd}' should be allowed"
            assert args is not None

    def test_write_commands_blocked_in_sandboxed(
        self, sandboxed_skill: GitSkill
    ) -> None:
        """Write commands blocked in SANDBOXED mode."""
        write_commands = ["add .", "commit -m 'test'", "push", "pull"]
        for cmd in write_commands:
            allowed, args, error = sandboxed_skill._validate_command(cmd)
            assert not allowed, f"Command '{cmd}' should be blocked"
            assert "read-only" in error.lower()

    def test_write_commands_allowed_in_trusted(
        self, trusted_skill: GitSkill
    ) -> None:
        """Write commands allowed in TRUSTED mode."""
        write_commands = ["add .", "commit -m 'test'", "push", "pull"]
        for cmd in write_commands:
            allowed, args, error = trusted_skill._validate_command(cmd)
            assert allowed, f"Command '{cmd}' should be allowed"
            assert args is not None

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
            allowed, args, error = trusted_skill._validate_command(cmd)
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
            allowed, args, error = yolo_skill._validate_command(cmd)
            assert allowed, f"Command '{cmd}' should be allowed in YOLO"
            assert args is not None


class TestGitSkillBypassPrevention:
    """Tests that quote-based bypass attempts are blocked.

    These tests verify the fix for the vulnerability where validation
    used regex on raw strings but execution used shlex.split().
    Attackers could bypass validation with creative quoting.
    """

    @pytest.fixture
    def trusted_skill(self) -> GitSkill:
        services = MockServiceContainer(permission_level=PermissionLevel.TRUSTED)
        return GitSkill(services)

    def test_quoted_force_flag_blocked(self, trusted_skill: GitSkill) -> None:
        """Quoted --force flag is still blocked after shlex parsing."""
        bypass_attempts = [
            'push "--force"',           # Double-quoted
            "push '--force'",           # Single-quoted
            'push "--force" origin',    # Quoted with extra args
            "push origin '--force'",    # Flag after positional
        ]
        for cmd in bypass_attempts:
            allowed, args, error = trusted_skill._validate_command(cmd)
            assert not allowed, f"Bypass attempt should be blocked: {cmd}"
            assert "blocked" in error.lower()

    def test_quoted_hard_flag_blocked(self, trusted_skill: GitSkill) -> None:
        """Quoted --hard flag is still blocked after shlex parsing."""
        bypass_attempts = [
            'reset "--hard"',
            "reset '--hard'",
            'reset "--hard" HEAD~1',
        ]
        for cmd in bypass_attempts:
            allowed, args, error = trusted_skill._validate_command(cmd)
            assert not allowed, f"Bypass attempt should be blocked: {cmd}"
            assert "blocked" in error.lower()

    def test_quoted_short_flag_blocked(self, trusted_skill: GitSkill) -> None:
        """Quoted short flags (-f, -d) are still blocked."""
        bypass_attempts = [
            'push "-f"',
            "clean '-f'",
            "clean '-d'",
            'rebase "-i"',
        ]
        for cmd in bypass_attempts:
            allowed, args, error = trusted_skill._validate_command(cmd)
            assert not allowed, f"Bypass attempt should be blocked: {cmd}"
            assert "blocked" in error.lower()

    def test_combined_short_flags_blocked(self, trusted_skill: GitSkill) -> None:
        """Combined short flags like -fd are blocked when containing dangerous flags."""
        bypass_attempts = [
            "clean -fd",     # -f and -d combined
            "clean -df",     # Same, different order
            "clean -fxd",    # With extra flag in middle
        ]
        for cmd in bypass_attempts:
            allowed, args, error = trusted_skill._validate_command(cmd)
            assert not allowed, f"Bypass attempt should be blocked: {cmd}"
            assert "blocked" in error.lower()

    def test_invalid_shlex_syntax_rejected(self, trusted_skill: GitSkill) -> None:
        """Malformed quoting that shlex can't parse is rejected."""
        malformed = [
            'push "unclosed',
            "push 'unclosed",
        ]
        for cmd in malformed:
            allowed, args, error = trusted_skill._validate_command(cmd)
            assert not allowed, f"Malformed command should be rejected: {cmd}"
            assert "syntax" in error.lower()

    def test_returns_parsed_args(self, trusted_skill: GitSkill) -> None:
        """Validation returns the parsed args used for execution."""
        allowed, args, error = trusted_skill._validate_command("log --oneline -5")
        assert allowed
        assert args == ["log", "--oneline", "-5"]

    def test_parsed_args_match_execution(self, trusted_skill: GitSkill) -> None:
        """Returned args are what would be executed (no re-parsing)."""
        # Command with quotes that shlex will parse
        allowed, args, error = trusted_skill._validate_command("commit -m 'hello world'")
        assert allowed
        # shlex.split removes quotes, combines the message
        assert args == ["commit", "-m", "hello world"]


class TestGitSkillExecution:
    """Tests for git command execution."""

    @pytest.fixture
    def skill(self) -> GitSkill:
        services = MockServiceContainer()
        return GitSkill(services)

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
        services = MockServiceContainer(allowed_paths=[tmp_path])
        skill = GitSkill(services)
        result = await skill.execute(command="status", cwd="/etc")
        assert result.error
        assert "outside" in result.error.lower() or "sandbox" in result.error.lower()

    @pytest.mark.asyncio
    async def test_git_status_in_repo(self, tmp_path: Path) -> None:
        """Git status works in a git repository."""
        # Initialize a git repo
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)

        services = MockServiceContainer()
        skill = GitSkill(services)
        result = await skill.execute(command="status", cwd=str(tmp_path))

        # Should succeed (not an error)
        assert not result.error
        output = json.loads(result.output)
        assert output["success"] is True
        assert "branch" in output.get("parsed", {}) or "output" in output

    @pytest.mark.asyncio
    async def test_git_not_a_repo(self, tmp_path: Path) -> None:
        """Git returns error when not in a repo."""
        services = MockServiceContainer()
        skill = GitSkill(services)
        result = await skill.execute(command="status", cwd=str(tmp_path))

        # Should return git error
        assert result.error
        assert "not a git repository" in result.error.lower()


class TestGitSkillOutputParsing:
    """Tests for git output parsing."""

    @pytest.fixture
    def skill(self) -> GitSkill:
        services = MockServiceContainer()
        return GitSkill(services)

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
        # Create mock permissions with tool_permissions
        mock_perms = MagicMock()
        mock_perms.tool_permissions = {"git": MagicMock(allowed_paths=[Path("/tmp")])}
        mock_perms.effective_policy.allowed_paths = None
        mock_perms.effective_policy.level = PermissionLevel.TRUSTED
        services.register("permissions", mock_perms)

        skill = git_factory(services)
        assert isinstance(skill, GitSkill)
        assert skill._allowed_paths == [Path("/tmp")]

    def test_factory_gets_permission_level(self) -> None:
        """Factory gets permission level from permissions object."""
        services = ServiceContainer()

        # Mock permissions object
        mock_perms = MagicMock()
        mock_perms.effective_policy.level = PermissionLevel.SANDBOXED
        mock_perms.tool_permissions = {}
        mock_perms.effective_policy.allowed_paths = None
        services.register("permissions", mock_perms)
        services.register("permission_level", PermissionLevel.SANDBOXED)

        skill = git_factory(services)
        assert skill._permission_level == PermissionLevel.SANDBOXED

    def test_factory_defaults_to_trusted(self) -> None:
        """Factory defaults to TRUSTED when no permission_level."""
        services = ServiceContainer()
        # Even without permissions, permission_level service can be set
        services.register("permission_level", PermissionLevel.TRUSTED)
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
