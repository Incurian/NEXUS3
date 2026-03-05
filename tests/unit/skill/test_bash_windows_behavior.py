"""Tests for Windows-specific behavior in execution shell skills."""

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus3.core.permissions import PermissionLevel
from nexus3.skill.builtin import bash as bash_mod
from nexus3.skill.builtin.bash import BashSafeSkill, ShellUnsafeSkill
from nexus3.skill.builtin.run_python import RunPythonSkill


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

        async def raise_missing(_: str | None, __: list[str]) -> MagicMock:
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

        async def raise_missing(_: str | None, __: list[str]) -> MagicMock:
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
        command = "source .venv/Scripts/activate && python -V"

        monkeypatch.setattr("nexus3.skill.builtin.bash.sys.platform", "win32")
        monkeypatch.setenv("MSYSTEM", "MINGW64")
        monkeypatch.delenv("PSModulePath", raising=False)
        monkeypatch.setattr(bash_mod.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
        monkeypatch.setattr(bash_mod.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

        with patch(
            "nexus3.skill.builtin.bash.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=MagicMock()),
        ) as mock_exec:
            await skill._create_process(work_dir=None, command=command)

        mock_exec.assert_awaited_once()
        args = mock_exec.await_args.args
        assert args[:3] == ("bash", "-lc", command)

    @pytest.mark.asyncio
    async def test_uses_powershell_when_psmodulepath_set(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        services = MockServiceContainer(permission_level=PermissionLevel.TRUSTED)
        skill = ShellUnsafeSkill(services)
        command = ". .\\.venv\\Scripts\\Activate.ps1; python --version"

        monkeypatch.setattr("nexus3.skill.builtin.bash.sys.platform", "win32")
        monkeypatch.delenv("MSYSTEM", raising=False)
        monkeypatch.setenv("PSModulePath", "C:\\Users\\x\\Documents\\PowerShell\\Modules")
        monkeypatch.setattr(bash_mod.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
        monkeypatch.setattr(bash_mod.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

        with patch(
            "nexus3.skill.builtin.bash.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=MagicMock()),
        ) as mock_exec:
            await skill._create_process(work_dir=None, command=command)

        mock_exec.assert_awaited_once()
        args = mock_exec.await_args.args
        assert args[:5] == ("powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command")
        assert args[5] == command

    @pytest.mark.asyncio
    async def test_falls_back_to_cmd_shell_when_no_markers(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        services = MockServiceContainer(permission_level=PermissionLevel.TRUSTED)
        skill = ShellUnsafeSkill(services)
        command = "echo hello"

        monkeypatch.setattr("nexus3.skill.builtin.bash.sys.platform", "win32")
        monkeypatch.delenv("MSYSTEM", raising=False)
        monkeypatch.delenv("PSModulePath", raising=False)
        monkeypatch.setattr(bash_mod.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
        monkeypatch.setattr(bash_mod.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

        with patch(
            "nexus3.skill.builtin.bash.asyncio.create_subprocess_shell",
            new=AsyncMock(return_value=MagicMock()),
        ) as mock_shell:
            await skill._create_process(work_dir=None, command=command)

        mock_shell.assert_awaited_once()
        assert mock_shell.await_args.args[0] == command


class TestRunPythonConcurrencySafety:
    """run_python should preserve per-call code payloads under concurrency."""

    @pytest.mark.asyncio
    async def test_execute_passes_code_per_call_without_shared_state(self) -> None:
        services = MockServiceContainer(permission_level=PermissionLevel.TRUSTED)
        skill = RunPythonSkill(services)
        seen_codes: list[str] = []

        class _FakeProcess:
            def __init__(self, code: str) -> None:
                self.returncode = 0
                self._code = code

            async def communicate(self) -> tuple[bytes, bytes]:
                await asyncio.sleep(0.01)
                return (self._code.encode("utf-8"), b"")

        async def fake_create_process(work_dir: str | None, code: str) -> _FakeProcess:
            seen_codes.append(code)
            await asyncio.sleep(0.01)
            return _FakeProcess(code)

        skill._create_process = fake_create_process  # type: ignore[method-assign]

        first = "print('first')"
        second = "print('second')"
        results = await asyncio.gather(
            skill.execute(code=first),
            skill.execute(code=second),
        )

        assert sorted(seen_codes) == sorted([first, second])
        assert sorted(result.output for result in results) == sorted([first, second])
