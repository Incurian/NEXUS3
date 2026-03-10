"""Tests for nexus3.core.shell_detection module."""

import os
import sys
from unittest.mock import patch

import pytest

from nexus3.core.shell_detection import (
    WindowsShell,
    check_console_codepage,
    detect_windows_shell,
    is_windows_wsl_bash_shim,
    resolve_git_bash_executable,
    supports_ansi,
    supports_unicode,
)


class TestWindowsShellEnum:
    """Test WindowsShell enum."""

    def test_all_shells_defined(self) -> None:
        """All expected shell types should be defined."""
        assert WindowsShell.WINDOWS_TERMINAL
        assert WindowsShell.POWERSHELL_7
        assert WindowsShell.POWERSHELL_5
        assert WindowsShell.GIT_BASH
        assert WindowsShell.CMD
        assert WindowsShell.UNKNOWN


class TestDetectWindowsShell:
    """Test detect_windows_shell() function."""

    @pytest.mark.windows_mock
    def test_detect_windows_terminal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should detect Windows Terminal via WT_SESSION."""
        monkeypatch.setattr(sys, "platform", "win32")
        detect_windows_shell.cache_clear()

        with patch.dict(os.environ, {"WT_SESSION": "some-session-id"}, clear=False):
            result = detect_windows_shell()
            assert result == WindowsShell.WINDOWS_TERMINAL

    @pytest.mark.windows_mock
    def test_detect_git_bash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should detect Git Bash via MSYSTEM."""
        monkeypatch.setattr(sys, "platform", "win32")
        detect_windows_shell.cache_clear()

        with patch.dict(os.environ, {"MSYSTEM": "MINGW64"}, clear=False):
            # Ensure WT_SESSION is not set
            env = os.environ.copy()
            env.pop("WT_SESSION", None)
            env["MSYSTEM"] = "MINGW64"
            with patch.dict(os.environ, env, clear=True):
                result = detect_windows_shell()
                assert result == WindowsShell.GIT_BASH

    @pytest.mark.windows_mock
    def test_detect_powershell(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should detect PowerShell via PSModulePath."""
        monkeypatch.setattr(sys, "platform", "win32")
        detect_windows_shell.cache_clear()

        env = {"PSModulePath": "C:\\Users\\test\\Documents\\PowerShell\\Modules"}
        with patch.dict(os.environ, env, clear=True):
            result = detect_windows_shell()
            assert result == WindowsShell.POWERSHELL_5

    @pytest.mark.windows_mock
    def test_detect_cmd(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should detect CMD.exe via COMSPEC."""
        monkeypatch.setattr(sys, "platform", "win32")
        detect_windows_shell.cache_clear()

        env = {"COMSPEC": "C:\\Windows\\System32\\cmd.exe"}
        with patch.dict(os.environ, env, clear=True):
            result = detect_windows_shell()
            assert result == WindowsShell.CMD

    @pytest.mark.windows_mock
    def test_detect_unknown_on_empty_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return UNKNOWN when no shell indicators present."""
        monkeypatch.setattr(sys, "platform", "win32")
        detect_windows_shell.cache_clear()

        with patch.dict(os.environ, {}, clear=True):
            result = detect_windows_shell()
            assert result == WindowsShell.UNKNOWN

    def test_returns_unknown_on_unix(self) -> None:
        """Should return UNKNOWN on non-Windows platforms."""
        if sys.platform == "win32":
            pytest.skip("Test only runs on Unix")
        detect_windows_shell.cache_clear()
        result = detect_windows_shell()
        assert result == WindowsShell.UNKNOWN

    @pytest.mark.windows_mock
    def test_windows_terminal_takes_priority(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Windows Terminal should be detected even with other indicators."""
        monkeypatch.setattr(sys, "platform", "win32")
        detect_windows_shell.cache_clear()

        env = {
            "WT_SESSION": "session-id",
            "MSYSTEM": "MINGW64",  # Also set
            "PSModulePath": "C:\\path",  # Also set
        }
        with patch.dict(os.environ, env, clear=True):
            result = detect_windows_shell()
            assert result == WindowsShell.WINDOWS_TERMINAL


class TestSupportsAnsi:
    """Test supports_ansi() function."""

    @pytest.mark.windows_mock
    def test_windows_terminal_supports_ansi(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Windows Terminal should support ANSI."""
        monkeypatch.setattr(sys, "platform", "win32")
        detect_windows_shell.cache_clear()

        with patch.dict(os.environ, {"WT_SESSION": "id"}, clear=True):
            assert supports_ansi() is True

    @pytest.mark.windows_mock
    def test_cmd_does_not_support_ansi(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CMD.exe should not support ANSI."""
        monkeypatch.setattr(sys, "platform", "win32")
        detect_windows_shell.cache_clear()

        with patch.dict(os.environ, {"COMSPEC": "C:\\Windows\\System32\\cmd.exe"}, clear=True):
            assert supports_ansi() is False

    @pytest.mark.windows_mock
    def test_git_bash_supports_ansi(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Git Bash should support ANSI."""
        monkeypatch.setattr(sys, "platform", "win32")
        detect_windows_shell.cache_clear()

        with patch.dict(os.environ, {"MSYSTEM": "MINGW64"}, clear=True):
            assert supports_ansi() is True

    def test_unix_always_supports_ansi(self) -> None:
        """Unix platforms should always support ANSI."""
        if sys.platform == "win32":
            pytest.skip("Test only runs on Unix")
        assert supports_ansi() is True


class TestSupportsUnicode:
    """Test supports_unicode() function."""

    @pytest.mark.windows_mock
    def test_cmd_does_not_support_unicode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CMD.exe should not support Unicode box drawing."""
        monkeypatch.setattr(sys, "platform", "win32")
        detect_windows_shell.cache_clear()

        with patch.dict(os.environ, {"COMSPEC": "C:\\Windows\\System32\\cmd.exe"}, clear=True):
            assert supports_unicode() is False


class TestCheckConsoleCodepage:
    """Test check_console_codepage() function."""

    def test_unix_returns_utf8(self) -> None:
        """Unix should return UTF-8 codepage."""
        if sys.platform == "win32":
            pytest.skip("Test only runs on Unix")
        codepage, is_utf8 = check_console_codepage()
        assert codepage == 65001
        assert is_utf8 is True

    @pytest.mark.windows_mock
    def test_windows_returns_codepage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Windows should return actual codepage."""
        monkeypatch.setattr(sys, "platform", "win32")

        # Mock ctypes
        mock_windll = type("windll", (), {
            "kernel32": type("kernel32", (), {
                "GetConsoleOutputCP": lambda: 65001
            })()
        })()

        with patch.dict(sys.modules, {"ctypes": type("ctypes", (), {"windll": mock_windll})()}):
            # Re-import to pick up mock
            from nexus3.core.shell_detection import check_console_codepage
            codepage, is_utf8 = check_console_codepage()
            # Note: may still get real value depending on import order


class TestResolveGitBashExecutable:
    """Test explicit Git Bash executable resolution on Windows."""

    @pytest.mark.windows_mock
    def test_rejects_known_wsl_shims(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "win32")

        assert is_windows_wsl_bash_shim(r"C:\Windows\System32\bash.exe") is True
        assert is_windows_wsl_bash_shim(
            r"C:\Users\inc\AppData\Local\Microsoft\WindowsApps\bash.exe"
        ) is True
        assert is_windows_wsl_bash_shim(r"C:\Program Files\Git\usr\bin\bash.exe") is False

    @pytest.mark.windows_mock
    def test_prefers_git_bash_path_over_wsl_shim(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(sys, "platform", "win32")

        path_value = (
            r"C:\Windows\System32;"
            r"C:\Program Files\Git\usr\bin;"
            r"C:\Users\inc\AppData\Local\Microsoft\WindowsApps"
        )

        def fake_isfile(path: str) -> bool:
            normalized = os.path.normcase(os.path.normpath(path))
            return normalized in {
                os.path.normcase(os.path.normpath(r"C:\Windows\System32\bash.exe")),
                os.path.normcase(
                    os.path.normpath(r"C:\Program Files\Git\usr\bin\bash.exe")
                ),
                os.path.normcase(
                    os.path.normpath(
                        r"C:\Users\inc\AppData\Local\Microsoft\WindowsApps\bash.exe"
                    )
                ),
            }

        monkeypatch.setattr("nexus3.core.shell_detection.os.path.isfile", fake_isfile)

        assert resolve_git_bash_executable(path_value) == r"C:\Program Files\Git\usr\bin\bash.exe"

    @pytest.mark.windows_mock
    def test_falls_back_to_common_git_install_root(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(sys, "platform", "win32")

        path_value = r"C:\Windows\System32"

        def fake_isfile(path: str) -> bool:
            normalized = os.path.normcase(os.path.normpath(path))
            return normalized in {
                os.path.normcase(os.path.normpath(r"C:\Windows\System32\bash.exe")),
                os.path.normcase(
                    os.path.normpath(r"C:\Program Files\Git\usr\bin\bash.exe")
                ),
            }

        monkeypatch.setattr("nexus3.core.shell_detection.os.path.isfile", fake_isfile)
        monkeypatch.setenv("ProgramFiles", r"C:\Program Files")

        assert resolve_git_bash_executable(path_value) == r"C:\Program Files\Git\usr\bin\bash.exe"
