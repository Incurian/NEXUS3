"""Tests for Unix/macOS shell selection behavior in execution skills."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus3.core.permissions import PermissionLevel
from nexus3.skill.builtin import bash as bash_mod
from nexus3.skill.builtin.bash import ShellUnsafeSkill
from nexus3.skill.services import ServiceContainer


def _make_services(
    *,
    permission_level: PermissionLevel | None = None,
    cwd: Path | str | None = None,
) -> ServiceContainer:
    services = ServiceContainer()
    if permission_level is not None:
        services.register("permission_level", permission_level)
    if cwd is not None:
        services.set_cwd(cwd)
    return services


class TestShellUnsafeUnixShellSelection:
    """shell_UNSAFE should use the right shell family on Unix hosts."""

    @pytest.mark.asyncio
    async def test_uses_explicit_zsh_when_requested(self, monkeypatch: pytest.MonkeyPatch) -> None:
        services = _make_services(permission_level=PermissionLevel.TRUSTED)
        skill = ShellUnsafeSkill(services)

        monkeypatch.setattr("nexus3.skill.builtin.bash.sys.platform", "linux")
        monkeypatch.setattr(
            bash_mod,
            "get_safe_env",
            lambda cwd: {"PATH": "/bin:/usr/bin"},
        )

        with (
            patch(
                "nexus3.skill.builtin.bash.shutil.which",
                side_effect=lambda shell, path=None: "/bin/zsh" if shell == "zsh" else None,
            ),
            patch(
                "nexus3.skill.builtin.bash.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=MagicMock()),
            ) as mock_exec,
        ):
            await skill._create_process(work_dir=None, command="echo hello", shell="zsh")

        mock_exec.assert_awaited_once()
        args = mock_exec.await_args.args
        assert args[:3] == ("/bin/zsh", "-lc", "echo hello")

    @pytest.mark.asyncio
    async def test_auto_prefers_supported_shell_env_on_macos(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        services = _make_services(permission_level=PermissionLevel.TRUSTED)
        skill = ShellUnsafeSkill(services)

        monkeypatch.setattr("nexus3.skill.builtin.bash.sys.platform", "darwin")
        monkeypatch.setattr(
            bash_mod,
            "get_safe_env",
            lambda cwd: {"PATH": "/bin:/usr/bin", "SHELL": "/bin/zsh"},
        )
        monkeypatch.setattr(
            bash_mod.os.path,
            "isfile",
            lambda path: path == "/bin/zsh",
        )

        with patch(
            "nexus3.skill.builtin.bash.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=MagicMock()),
        ) as mock_exec:
            await skill._create_process(work_dir=None, command="echo hello", shell="auto")

        mock_exec.assert_awaited_once()
        args = mock_exec.await_args.args
        assert args[:3] == ("/bin/zsh", "-lc", "echo hello")

    @pytest.mark.asyncio
    async def test_auto_keeps_generic_shell_path_on_linux_even_with_shell_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        services = _make_services(permission_level=PermissionLevel.TRUSTED)
        skill = ShellUnsafeSkill(services)

        monkeypatch.setattr("nexus3.skill.builtin.bash.sys.platform", "linux")
        monkeypatch.setattr(
            bash_mod,
            "get_safe_env",
            lambda cwd: {"PATH": "/bin:/usr/bin", "SHELL": "/bin/zsh"},
        )

        with patch(
            "nexus3.skill.builtin.bash.asyncio.create_subprocess_shell",
            new=AsyncMock(return_value=MagicMock()),
        ) as mock_shell:
            await skill._create_process(work_dir=None, command="echo hello", shell="auto")

        mock_shell.assert_awaited_once()
        args = mock_shell.await_args.args
        assert args == ("echo hello",)

    @pytest.mark.asyncio
    async def test_auto_falls_back_for_unknown_unix_shell(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        services = _make_services(permission_level=PermissionLevel.TRUSTED)
        skill = ShellUnsafeSkill(services)

        monkeypatch.setattr("nexus3.skill.builtin.bash.sys.platform", "linux")
        monkeypatch.setattr(
            bash_mod,
            "get_safe_env",
            lambda cwd: {"PATH": "/bin:/usr/bin", "SHELL": "/tmp/custom-shell"},
        )
        monkeypatch.setattr(
            bash_mod.os.path,
            "isfile",
            lambda path: path == "/tmp/custom-shell",
        )

        with patch(
            "nexus3.skill.builtin.bash.asyncio.create_subprocess_shell",
            new=AsyncMock(return_value=MagicMock()),
        ) as mock_shell:
            await skill._create_process(work_dir=None, command="echo hello", shell="auto")

        mock_shell.assert_awaited_once()
        args = mock_shell.await_args.args
        assert args == ("echo hello",)
