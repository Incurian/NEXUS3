"""Tests for Windows-specific behavior in execution shell skills."""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus3.core.permissions import PermissionLevel
from nexus3.skill.builtin import bash as bash_mod
from nexus3.skill.builtin.bash import BashSafeSkill, ShellUnsafeSkill


class MockServiceContainer:
    """Minimal ServiceContainer stub for execution skill tests."""

    def __init__(self, permission_level: PermissionLevel | None = None, **kwargs: Any) -> None:
        self._data = kwargs
        self._permission_level = permission_level

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def get_permission_level(self) -> PermissionLevel | None:
        return self._permission_level

    def get_tool_allowed_paths(self, tool_name: str | None = None) -> list[Path] | None:
        return self._data.get("allowed_paths")

    def get_blocked_paths(self) -> list[Path]:
        return self._data.get("blocked_paths", [])

    def get_cwd(self) -> Path:
        return self._data.get("cwd", Path.cwd())


class TestBashSafeWindowsBehavior:
    """Windows behavior checks for bash_safe."""

    @pytest.mark.asyncio
    async def test_source_is_parsed_like_normal_command(self, tmp_path: Path) -> None:
        services = MockServiceContainer(
            permission_level=PermissionLevel.TRUSTED,
            allowed_paths=[tmp_path],
            cwd=tmp_path,
        )
        skill = BashSafeSkill(services)

        async def raise_missing(_: str | None) -> MagicMock:
            raise FileNotFoundError(2, "The system cannot find the file specified")

        skill._create_process = raise_missing  # type: ignore[method-assign]
        result = await skill.execute(
            command="source .venv/Scripts/activate",
            cwd=str(tmp_path),
        )

        assert result.error is not None
        assert "Failed to execute" in result.error

    @pytest.mark.asyncio
    async def test_winerror_2_returns_default_spawn_error(self, tmp_path: Path) -> None:
        services = MockServiceContainer(
            permission_level=PermissionLevel.TRUSTED,
            allowed_paths=[tmp_path],
            cwd=tmp_path,
        )
        skill = BashSafeSkill(services)

        async def raise_missing(_: str | None) -> MagicMock:
            raise FileNotFoundError(2, "The system cannot find the file specified")

        with patch("nexus3.skill.builtin.bash.sys.platform", "win32"):
            skill._create_process = raise_missing  # type: ignore[method-assign]
            result = await skill.execute(command="missing_executable", cwd=str(tmp_path))

        assert result.error is not None
        assert "Failed to execute" in result.error


class TestShellUnsafeWindowsShellSelection:
    """shell_UNSAFE should use the right shell family on Windows."""

    @pytest.mark.asyncio
    async def test_uses_git_bash_when_msystem_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        services = MockServiceContainer(permission_level=PermissionLevel.TRUSTED)
        skill = ShellUnsafeSkill(services)
        skill._command = "source .venv/Scripts/activate && python -V"

        monkeypatch.setattr("nexus3.skill.builtin.bash.sys.platform", "win32")
        monkeypatch.setenv("MSYSTEM", "MINGW64")
        monkeypatch.delenv("PSModulePath", raising=False)
        monkeypatch.setattr(bash_mod.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
        monkeypatch.setattr(bash_mod.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

        with patch(
            "nexus3.skill.builtin.bash.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=MagicMock()),
        ) as mock_exec:
            await skill._create_process(work_dir=None)

        mock_exec.assert_awaited_once()
        args = mock_exec.await_args.args
        assert args[:3] == ("bash", "-lc", skill._command)

    @pytest.mark.asyncio
    async def test_uses_powershell_when_psmodulepath_set(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        services = MockServiceContainer(permission_level=PermissionLevel.TRUSTED)
        skill = ShellUnsafeSkill(services)
        skill._command = ". .\\.venv\\Scripts\\Activate.ps1; python --version"

        monkeypatch.setattr("nexus3.skill.builtin.bash.sys.platform", "win32")
        monkeypatch.delenv("MSYSTEM", raising=False)
        monkeypatch.setenv("PSModulePath", "C:\\Users\\x\\Documents\\PowerShell\\Modules")
        monkeypatch.setattr(bash_mod.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
        monkeypatch.setattr(bash_mod.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

        with patch(
            "nexus3.skill.builtin.bash.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=MagicMock()),
        ) as mock_exec:
            await skill._create_process(work_dir=None)

        mock_exec.assert_awaited_once()
        args = mock_exec.await_args.args
        assert args[:5] == ("powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command")
        assert args[5] == skill._command

    @pytest.mark.asyncio
    async def test_falls_back_to_cmd_shell_when_no_markers(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        services = MockServiceContainer(permission_level=PermissionLevel.TRUSTED)
        skill = ShellUnsafeSkill(services)
        skill._command = "echo hello"

        monkeypatch.setattr("nexus3.skill.builtin.bash.sys.platform", "win32")
        monkeypatch.delenv("MSYSTEM", raising=False)
        monkeypatch.delenv("PSModulePath", raising=False)
        monkeypatch.setattr(bash_mod.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
        monkeypatch.setattr(bash_mod.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

        with patch(
            "nexus3.skill.builtin.bash.asyncio.create_subprocess_shell",
            new=AsyncMock(return_value=MagicMock()),
        ) as mock_shell:
            await skill._create_process(work_dir=None)

        mock_shell.assert_awaited_once()
        assert mock_shell.await_args.args[0] == "echo hello"
