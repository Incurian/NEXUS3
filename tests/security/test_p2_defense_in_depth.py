"""Tests for P2.7: Defense-in-depth checks in high-risk execution tools.

These tests verify that bash, shell_UNSAFE, and run_python skills internally
refuse to execute when the permission level is SANDBOXED, even if the skill
was mistakenly registered for a sandboxed agent.

This is defense-in-depth - normally these skills aren't registered for
sandboxed agents, but if misconfiguration occurs, the skills themselves
should refuse to run.
"""

from pathlib import Path

import pytest

from nexus3.core.permissions import PermissionLevel
from nexus3.skill.builtin.bash import BashSafeSkill, ShellUnsafeSkill
from nexus3.skill.builtin.run_python import RunPythonSkill
from nexus3.skill.services import ServiceContainer


def _make_services(
    permission_level: PermissionLevel | None = None,
    *,
    allowed_paths: list[Path] | None = None,
    blocked_paths: list[Path] | None = None,
    cwd: Path | None = None,
) -> ServiceContainer:
    services = ServiceContainer()

    if permission_level is not None:
        services.register("permission_level", permission_level)
    if allowed_paths is not None:
        services.register_runtime_compat("allowed_paths", allowed_paths)
    if blocked_paths is not None:
        services.register("blocked_paths", blocked_paths)
    if cwd is not None:
        services.set_cwd(cwd)

    return services


class TestBashSafeDefenseInDepth:
    """Tests for bash_safe defense-in-depth checks."""

    @pytest.mark.asyncio
    async def test_sandboxed_refuses_execution(self) -> None:
        """SANDBOXED permission level refuses bash_safe execution."""
        services = _make_services(permission_level=PermissionLevel.SANDBOXED)
        skill = BashSafeSkill(services)

        result = await skill.execute(command="echo hello")

        assert result.error is not None
        assert "SANDBOXED" in result.error
        assert "disabled" in result.error
        assert "defense-in-depth" in result.error

    @pytest.mark.asyncio
    async def test_trusted_allows_execution(self, tmp_path: Path) -> None:
        """TRUSTED permission level allows bash_safe execution."""
        services = _make_services(
            permission_level=PermissionLevel.TRUSTED,
            allowed_paths=[tmp_path],
            cwd=tmp_path,
        )
        skill = BashSafeSkill(services)

        result = await skill.execute(command="echo hello", cwd=str(tmp_path))

        assert result.error is None or result.error == ""
        assert "hello" in result.output

    @pytest.mark.asyncio
    async def test_yolo_allows_execution(self, tmp_path: Path) -> None:
        """YOLO permission level allows bash_safe execution."""
        services = _make_services(
            permission_level=PermissionLevel.YOLO,
            allowed_paths=[tmp_path],
            cwd=tmp_path,
        )
        skill = BashSafeSkill(services)

        result = await skill.execute(command="echo hello", cwd=str(tmp_path))

        assert result.error is None or result.error == ""
        assert "hello" in result.output

    @pytest.mark.asyncio
    async def test_none_permission_allows_execution(self, tmp_path: Path) -> None:
        """None permission level (unset) allows execution (backwards compat)."""
        services = _make_services(
            permission_level=None,
            allowed_paths=[tmp_path],
            cwd=tmp_path,
        )
        skill = BashSafeSkill(services)

        result = await skill.execute(command="echo hello", cwd=str(tmp_path))

        # None means permission level not set - allow for backwards compat
        assert result.error is None or result.error == ""


class TestShellUnsafeDefenseInDepth:
    """Tests for shell_UNSAFE defense-in-depth checks."""

    @pytest.mark.asyncio
    async def test_sandboxed_refuses_execution(self) -> None:
        """SANDBOXED permission level refuses shell_UNSAFE execution."""
        services = _make_services(permission_level=PermissionLevel.SANDBOXED)
        skill = ShellUnsafeSkill(services)

        result = await skill.execute(command="echo hello")

        assert result.error is not None
        assert "SANDBOXED" in result.error
        assert "disabled" in result.error

    @pytest.mark.asyncio
    async def test_trusted_allows_execution(self, tmp_path: Path) -> None:
        """TRUSTED permission level allows shell_UNSAFE execution."""
        services = _make_services(
            permission_level=PermissionLevel.TRUSTED,
            allowed_paths=[tmp_path],
            cwd=tmp_path,
        )
        skill = ShellUnsafeSkill(services)

        result = await skill.execute(command="echo hello", cwd=str(tmp_path))

        assert result.error is None or result.error == ""
        assert "hello" in result.output

    @pytest.mark.asyncio
    async def test_shell_features_work_when_allowed(self, tmp_path: Path) -> None:
        """Shell features (pipes, etc.) work when permission allows."""
        services = _make_services(
            permission_level=PermissionLevel.TRUSTED,
            allowed_paths=[tmp_path],
            cwd=tmp_path,
        )
        skill = ShellUnsafeSkill(services)

        # Use a pipe - this only works with shell=True
        result = await skill.execute(command="echo hello | cat", cwd=str(tmp_path))

        assert result.error is None or result.error == ""
        assert "hello" in result.output


class TestRunPythonDefenseInDepth:
    """Tests for run_python defense-in-depth checks."""

    @pytest.mark.asyncio
    async def test_sandboxed_refuses_execution(self) -> None:
        """SANDBOXED permission level refuses run_python execution."""
        services = _make_services(permission_level=PermissionLevel.SANDBOXED)
        skill = RunPythonSkill(services)

        result = await skill.execute(code="print('hello')")

        assert result.error is not None
        assert "SANDBOXED" in result.error
        assert "disabled" in result.error
        assert "defense-in-depth" in result.error

    @pytest.mark.asyncio
    async def test_trusted_allows_execution(self, tmp_path: Path) -> None:
        """TRUSTED permission level allows run_python execution."""
        services = _make_services(
            permission_level=PermissionLevel.TRUSTED,
            allowed_paths=[tmp_path],
            cwd=tmp_path,
        )
        skill = RunPythonSkill(services)

        result = await skill.execute(code="print('hello')", cwd=str(tmp_path))

        assert result.error is None or result.error == ""
        assert "hello" in result.output

    @pytest.mark.asyncio
    async def test_yolo_allows_execution(self, tmp_path: Path) -> None:
        """YOLO permission level allows run_python execution."""
        services = _make_services(
            permission_level=PermissionLevel.YOLO,
            allowed_paths=[tmp_path],
            cwd=tmp_path,
        )
        skill = RunPythonSkill(services)

        result = await skill.execute(code="print('hello')", cwd=str(tmp_path))

        assert result.error is None or result.error == ""
        assert "hello" in result.output

    @pytest.mark.asyncio
    async def test_code_actually_blocked_not_just_error_message(self) -> None:
        """Verify code doesn't run at all in SANDBOXED mode (not just error after)."""
        services = _make_services(permission_level=PermissionLevel.SANDBOXED)
        skill = RunPythonSkill(services)

        # This code would create a file if it ran
        result = await skill.execute(code="import pathlib; pathlib.Path('/tmp/p27_test').touch()")

        assert result.error is not None
        assert "SANDBOXED" in result.error
        # File should not exist
        import pathlib
        assert not pathlib.Path("/tmp/p27_test").exists()


class TestDefenseInDepthErrorMessages:
    """Tests for error message quality."""

    @pytest.mark.asyncio
    async def test_error_includes_skill_name(self) -> None:
        """Error message includes the skill name for debugging."""
        services = _make_services(permission_level=PermissionLevel.SANDBOXED)

        bash_skill = BashSafeSkill(services)
        result = await bash_skill.execute(command="echo test")
        assert "bash_safe" in result.error

        shell_skill = ShellUnsafeSkill(services)
        result = await shell_skill.execute(command="echo test")
        assert "shell_UNSAFE" in result.error

        python_skill = RunPythonSkill(services)
        result = await python_skill.execute(code="print('test')")
        assert "run_python" in result.error

    @pytest.mark.asyncio
    async def test_error_is_actionable(self) -> None:
        """Error message helps diagnose misconfiguration."""
        services = _make_services(permission_level=PermissionLevel.SANDBOXED)
        skill = BashSafeSkill(services)

        result = await skill.execute(command="echo test")

        # Should mention this is defense-in-depth (implies misconfiguration)
        assert "defense-in-depth" in result.error
        # Should mention the skill shouldn't be registered
        assert "should not be registered" in result.error
