"""Security tests for Windows process termination.

These tests verify that process termination handles edge cases securely,
including:
- Already terminated processes (no action taken)
- Processes with no PID (no action taken)
- Windows-specific fallback chain (CTRL_BREAK -> taskkill -> kill)
- Unix process group termination
- ProcessLookupError handling (no exceptions leaked)
"""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus3.core.process import (
    GRACEFUL_TIMEOUT,
    terminate_process_tree,
    _terminate_unix,
    _terminate_windows,
)


class TestTerminateProcessTreeSecurity:
    """Security tests for process tree termination."""

    @pytest.mark.asyncio
    async def test_handles_already_terminated_process(self) -> None:
        """Should handle gracefully if process already terminated."""
        process = MagicMock()
        process.returncode = 0  # Already exited
        process.pid = 12345

        # Should return immediately without error
        await terminate_process_tree(process)

        # Verify no termination methods were called
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_none_pid(self) -> None:
        """Should handle gracefully if process has no PID."""
        process = MagicMock()
        process.returncode = None
        process.pid = None

        # Should not raise
        await terminate_process_tree(process)

        # Verify no termination methods were called
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.windows_mock
    async def test_windows_ctrl_break_first(self) -> None:
        """On Windows, should try CTRL_BREAK_EVENT first."""
        process = MagicMock()
        process.returncode = None
        process.pid = 12345
        process.wait = AsyncMock(return_value=0)

        with patch("nexus3.core.process.os.kill") as mock_kill:
            with patch("nexus3.core.process.signal") as mock_signal:
                mock_signal.CTRL_BREAK_EVENT = 1
                await _terminate_windows(process, 12345, GRACEFUL_TIMEOUT)

                # Should have sent CTRL_BREAK_EVENT
                mock_kill.assert_called_once_with(12345, 1)

    @pytest.mark.asyncio
    @pytest.mark.windows_mock
    async def test_windows_taskkill_fallback(self) -> None:
        """On Windows, should fall back to taskkill if CTRL_BREAK fails."""
        process = MagicMock()
        process.returncode = None
        process.pid = 12345

        # Simulate timeout on wait (CTRL_BREAK didn't work)
        call_count = [0]

        async def mock_wait() -> int:
            call_count[0] += 1
            if call_count[0] <= 2:
                await asyncio.sleep(10)  # Will timeout
            return 0

        process.wait = mock_wait

        mock_taskkill = MagicMock()
        mock_taskkill.wait = AsyncMock(return_value=0)

        with patch("nexus3.core.process.os.kill"):
            with patch("nexus3.core.process.signal") as mock_signal:
                mock_signal.CTRL_BREAK_EVENT = 1
                with patch(
                    "nexus3.core.process.asyncio.create_subprocess_exec",
                    return_value=mock_taskkill,
                ) as mock_exec:
                    await _terminate_windows(process, 12345, 0.01)

                    # Should have called taskkill
                    mock_exec.assert_called_once()
                    call_args = mock_exec.call_args
                    assert call_args[0][:5] == (
                        "taskkill",
                        "/T",
                        "/F",
                        "/PID",
                        "12345",
                    )

    @pytest.mark.asyncio
    @pytest.mark.windows_mock
    async def test_windows_final_kill_fallback(self) -> None:
        """On Windows, should call process.kill() as final fallback."""
        process = MagicMock()
        process.returncode = None
        process.pid = 12345

        # Simulate all waits timing out
        call_count = [0]

        async def mock_wait() -> int:
            call_count[0] += 1
            if call_count[0] <= 3:
                await asyncio.sleep(10)
            return 0

        process.wait = mock_wait

        mock_taskkill = MagicMock()
        mock_taskkill.wait = AsyncMock(return_value=0)

        with patch("nexus3.core.process.os.kill"):
            with patch("nexus3.core.process.signal") as mock_signal:
                mock_signal.CTRL_BREAK_EVENT = 1
                with patch(
                    "nexus3.core.process.asyncio.create_subprocess_exec",
                    return_value=mock_taskkill,
                ):
                    await _terminate_windows(process, 12345, 0.01)

                    # Should have called process.kill() as final fallback
                    process.kill.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.unix_only
    async def test_unix_process_group_termination(self) -> None:
        """On Unix, should send signals to process group."""
        process = MagicMock()
        process.returncode = None
        process.pid = 12345
        process.wait = AsyncMock(return_value=0)

        with patch("nexus3.core.process.os.getpgid", return_value=12345):
            with patch("nexus3.core.process.os.killpg") as mock_killpg:
                await _terminate_unix(process, 12345, GRACEFUL_TIMEOUT)

                # Should have sent SIGTERM to process group
                mock_killpg.assert_called()

    @pytest.mark.asyncio
    async def test_process_lookup_error_handled(self) -> None:
        """Should handle ProcessLookupError gracefully."""
        process = MagicMock()
        process.returncode = None
        process.pid = 12345
        process.wait = AsyncMock(return_value=0)
        process.terminate = MagicMock(side_effect=ProcessLookupError)

        if sys.platform != "win32":
            with patch(
                "nexus3.core.process.os.getpgid", side_effect=ProcessLookupError
            ):
                # Should not raise
                await _terminate_unix(process, 12345, GRACEFUL_TIMEOUT)

    @pytest.mark.asyncio
    @pytest.mark.windows_mock
    async def test_windows_handles_all_errors_gracefully(self) -> None:
        """Windows termination should handle all error types without raising."""
        process = MagicMock()
        process.returncode = None
        process.pid = 12345
        process.wait = AsyncMock(return_value=0)

        # Test OSError on CTRL_BREAK
        with patch("nexus3.core.process.os.kill", side_effect=OSError):
            with patch("nexus3.core.process.signal") as mock_signal:
                mock_signal.CTRL_BREAK_EVENT = 1
                # Should not raise
                await _terminate_windows(process, 12345, GRACEFUL_TIMEOUT)

    @pytest.mark.asyncio
    @pytest.mark.windows_mock
    async def test_windows_handles_attribute_error(self) -> None:
        """Windows should handle AttributeError (missing CTRL_BREAK_EVENT)."""
        process = MagicMock()
        process.returncode = None
        process.pid = 12345
        process.wait = AsyncMock(return_value=0)

        with patch("nexus3.core.process.os.kill", side_effect=AttributeError):
            with patch("nexus3.core.process.signal") as mock_signal:
                mock_signal.CTRL_BREAK_EVENT = 1
                # Should not raise
                await _terminate_windows(process, 12345, GRACEFUL_TIMEOUT)

    @pytest.mark.asyncio
    @pytest.mark.unix_only
    async def test_unix_permission_error_fallback(self) -> None:
        """Unix should fall back to process.terminate() on PermissionError."""
        process = MagicMock()
        process.returncode = None
        process.pid = 12345
        process.wait = AsyncMock(return_value=0)

        with patch("nexus3.core.process.os.getpgid", side_effect=PermissionError):
            await _terminate_unix(process, 12345, GRACEFUL_TIMEOUT)

            # Should have fallen back to process.terminate()
            process.terminate.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.windows_mock
    async def test_windows_taskkill_not_found(self) -> None:
        """Windows should handle missing taskkill executable."""
        process = MagicMock()
        process.returncode = None
        process.pid = 12345

        call_count = [0]

        async def mock_wait() -> int:
            call_count[0] += 1
            if call_count[0] <= 3:
                await asyncio.sleep(10)
            return 0

        process.wait = mock_wait

        with patch("nexus3.core.process.os.kill"):
            with patch("nexus3.core.process.signal") as mock_signal:
                mock_signal.CTRL_BREAK_EVENT = 1
                with patch(
                    "nexus3.core.process.asyncio.create_subprocess_exec",
                    side_effect=FileNotFoundError,
                ):
                    # Should not raise, should fall back to process.kill()
                    await _terminate_windows(process, 12345, 0.01)
                    process.kill.assert_called_once()
