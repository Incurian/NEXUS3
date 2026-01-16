"""Tests for P2.7: Defense-in-depth checks in high-risk execution tools.

These tests verify that bash, shell_UNSAFE, and run_python skills internally
refuse to execute when the permission level is SANDBOXED, even if the skill
was mistakenly registered for a sandboxed agent.

This is defense-in-depth - normally these skills aren't registered for
sandboxed agents, but if misconfiguration occurs, the skills themselves
should refuse to run.
"""

import pytest
from pathlib import Path
from typing import Any

from nexus3.core.permissions import PermissionLevel
from nexus3.core.types import ToolResult
from nexus3.skill.builtin.bash import BashSafeSkill, ShellUnsafeSkill
from nexus3.skill.builtin.run_python import RunPythonSkill


class MockServiceContainer:
    """Mock ServiceContainer for testing permission levels."""

    def __init__(self, permission_level: PermissionLevel | None = None, **kwargs: Any) -> None:
        self._data = kwargs
        self._permission_level = permission_level

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def get_permission_level(self) -> PermissionLevel | None:
        return self._permission_level

    def get_permissions(self) -> None:
        return None

    def get_tool_allowed_paths(self, tool_name: str | None = None) -> list[Path] | None:
        return self._data.get("allowed_paths")

    def get_blocked_paths(self) -> list[Path]:
        return self._data.get("blocked_paths", [])

    def get_cwd(self) -> Path:
        return self._data.get("cwd", Path.cwd())


class TestBashSafeDefenseInDepth:
    """Tests for bash_safe defense-in-depth checks."""

    @pytest.mark.asyncio
    async def test_sandboxed_refuses_execution(self) -> None:
        """SANDBOXED permission level refuses bash_safe execution."""
        services = MockServiceContainer(permission_level=PermissionLevel.SANDBOXED)
        skill = BashSafeSkill(services)

        result = await skill.execute(command="echo hello")

        assert result.error is not None
        assert "SANDBOXED" in result.error
        assert "disabled" in result.error
        assert "defense-in-depth" in result.error

    @pytest.mark.asyncio
    async def test_trusted_allows_execution(self, tmp_path: Path) -> None:
        """TRUSTED permission level allows bash_safe execution."""
        services = MockServiceContainer(
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
        services = MockServiceContainer(
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
        services = MockServiceContainer(
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
        services = MockServiceContainer(permission_level=PermissionLevel.SANDBOXED)
        skill = ShellUnsafeSkill(services)

        result = await skill.execute(command="echo hello")

        assert result.error is not None
        assert "SANDBOXED" in result.error
        assert "disabled" in result.error

    @pytest.mark.asyncio
    async def test_trusted_allows_execution(self, tmp_path: Path) -> None:
        """TRUSTED permission level allows shell_UNSAFE execution."""
        services = MockServiceContainer(
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
        services = MockServiceContainer(
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
        services = MockServiceContainer(permission_level=PermissionLevel.SANDBOXED)
        skill = RunPythonSkill(services)

        result = await skill.execute(code="print('hello')")

        assert result.error is not None
        assert "SANDBOXED" in result.error
        assert "disabled" in result.error
        assert "defense-in-depth" in result.error

    @pytest.mark.asyncio
    async def test_trusted_allows_execution(self, tmp_path: Path) -> None:
        """TRUSTED permission level allows run_python execution."""
        services = MockServiceContainer(
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
        services = MockServiceContainer(
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
        services = MockServiceContainer(permission_level=PermissionLevel.SANDBOXED)
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
        services = MockServiceContainer(permission_level=PermissionLevel.SANDBOXED)

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
        services = MockServiceContainer(permission_level=PermissionLevel.SANDBOXED)
        skill = BashSafeSkill(services)

        result = await skill.execute(command="echo test")

        # Should mention this is defense-in-depth (implies misconfiguration)
        assert "defense-in-depth" in result.error
        # Should mention the skill shouldn't be registered
        assert "should not be registered" in result.error
