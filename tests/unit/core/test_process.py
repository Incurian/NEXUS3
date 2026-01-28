"""Tests for nexus3.core.process module.

Tests cover:
- Process already exited (returncode is not None)
- Process with no PID
- Unix termination: SIGTERM -> wait -> SIGKILL pattern
- Windows termination: CTRL_BREAK -> taskkill -> kill pattern
- Graceful timeout handling
- Error handling (ProcessLookupError, PermissionError, OSError)
"""

import asyncio
import signal
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus3.core.process import (
    GRACEFUL_TIMEOUT,
    terminate_process_tree,
    _terminate_unix,
    _terminate_windows,
)


class TestTerminateProcessTree:
    """Test the main terminate_process_tree function."""

    @pytest.mark.asyncio
    async def test_already_exited(self) -> None:
        """Process with returncode set should return immediately."""
        process = MagicMock()
        process.returncode = 0

        await terminate_process_tree(process)

        # Should not try to terminate
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_pid(self) -> None:
        """Process with no PID should return immediately."""
        process = MagicMock()
        process.returncode = None
        process.pid = None

        await terminate_process_tree(process)

        # Should not try to terminate
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatches_to_unix(self) -> None:
        """On Unix, should call _terminate_unix."""
        process = MagicMock()
        process.returncode = None
        process.pid = 1234

        with patch("nexus3.core.process.sys") as mock_sys:
            mock_sys.platform = "linux"
            with patch("nexus3.core.process._terminate_unix", new_callable=AsyncMock) as mock_unix:
                await terminate_process_tree(process, graceful_timeout=1.0)
                mock_unix.assert_called_once_with(process, 1234, 1.0)

    @pytest.mark.asyncio
    async def test_dispatches_to_windows(self) -> None:
        """On Windows, should call _terminate_windows."""
        process = MagicMock()
        process.returncode = None
        process.pid = 1234

        with patch("nexus3.core.process.sys") as mock_sys:
            mock_sys.platform = "win32"
            with patch("nexus3.core.process._terminate_windows", new_callable=AsyncMock) as mock_windows:
                await terminate_process_tree(process, graceful_timeout=1.0)
                mock_windows.assert_called_once_with(process, 1234, 1.0)

    def test_default_timeout(self) -> None:
        """Default graceful timeout should be 2.0 seconds."""
        assert GRACEFUL_TIMEOUT == 2.0


@pytest.mark.skipif(sys.platform == "win32", reason="Unix-specific tests")
class TestTerminateUnix:
    """Test Unix termination implementation."""

    @pytest.mark.asyncio
    async def test_sigterm_to_process_group(self) -> None:
        """Should send SIGTERM to process group first."""
        process = MagicMock()
        process.wait = AsyncMock(return_value=0)

        with patch("nexus3.core.process.os.getpgid", return_value=5678) as mock_getpgid:
            with patch("nexus3.core.process.os.killpg") as mock_killpg:
                await _terminate_unix(process, 1234, 2.0)

                mock_getpgid.assert_called_with(1234)
                mock_killpg.assert_called_with(5678, signal.SIGTERM)

    @pytest.mark.asyncio
    async def test_graceful_exit_no_sigkill(self) -> None:
        """If process exits gracefully, should not send SIGKILL."""
        process = MagicMock()
        process.wait = AsyncMock(return_value=0)

        with patch("nexus3.core.process.os.getpgid", return_value=5678):
            with patch("nexus3.core.process.os.killpg") as mock_killpg:
                await _terminate_unix(process, 1234, 2.0)

                # Only one call (SIGTERM)
                assert mock_killpg.call_count == 1
                mock_killpg.assert_called_with(5678, signal.SIGTERM)

    @pytest.mark.asyncio
    async def test_sigkill_after_timeout(self) -> None:
        """If process doesn't exit gracefully, should send SIGKILL."""
        process = MagicMock()

        # First wait times out, second completes
        call_count = [0]

        async def mock_wait():
            call_count[0] += 1
            if call_count[0] == 1:
                await asyncio.sleep(10)  # Will timeout
            return 0

        process.wait = mock_wait

        with patch("nexus3.core.process.os.getpgid", return_value=5678):
            with patch("nexus3.core.process.os.killpg") as mock_killpg:
                await _terminate_unix(process, 1234, 0.01)

                # Should have two calls: SIGTERM then SIGKILL
                assert mock_killpg.call_count == 2
                calls = mock_killpg.call_args_list
                assert calls[0][0] == (5678, signal.SIGTERM)
                assert calls[1][0] == (5678, signal.SIGKILL)

    @pytest.mark.asyncio
    async def test_process_lookup_error_on_sigterm(self) -> None:
        """ProcessLookupError on SIGTERM should fall back to process.terminate()."""
        process = MagicMock()
        process.wait = AsyncMock(return_value=0)

        with patch("nexus3.core.process.os.getpgid", side_effect=ProcessLookupError):
            await _terminate_unix(process, 1234, 2.0)

            process.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_permission_error_on_sigterm(self) -> None:
        """PermissionError on SIGTERM should fall back to process.terminate()."""
        process = MagicMock()
        process.wait = AsyncMock(return_value=0)

        with patch("nexus3.core.process.os.getpgid", side_effect=PermissionError):
            await _terminate_unix(process, 1234, 2.0)

            process.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_oserror_on_killpg(self) -> None:
        """OSError on killpg should fall back to process.terminate()."""
        process = MagicMock()
        process.wait = AsyncMock(return_value=0)

        with patch("nexus3.core.process.os.getpgid", return_value=5678):
            with patch("nexus3.core.process.os.killpg", side_effect=OSError):
                await _terminate_unix(process, 1234, 2.0)

                process.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_terminate_raises_process_lookup_error(self) -> None:
        """If both killpg and terminate fail with ProcessLookupError, should return."""
        process = MagicMock()
        process.terminate.side_effect = ProcessLookupError

        with patch("nexus3.core.process.os.getpgid", side_effect=ProcessLookupError):
            # Should not raise
            await _terminate_unix(process, 1234, 2.0)

    @pytest.mark.asyncio
    async def test_sigkill_process_lookup_error(self) -> None:
        """ProcessLookupError on SIGKILL should fall back to process.kill()."""
        process = MagicMock()

        call_count = [0]

        async def mock_wait():
            call_count[0] += 1
            if call_count[0] == 1:
                await asyncio.sleep(10)  # Will timeout
            return 0

        process.wait = mock_wait

        with patch("nexus3.core.process.os.getpgid", return_value=5678) as mock_getpgid:
            # First call succeeds (for SIGTERM), second fails (for SIGKILL)
            mock_getpgid.side_effect = [5678, ProcessLookupError]
            with patch("nexus3.core.process.os.killpg") as mock_killpg:
                await _terminate_unix(process, 1234, 0.01)

                process.kill.assert_called_once()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific tests")
class TestTerminateWindowsReal:
    """Real Windows termination tests (only run on Windows)."""

    @pytest.mark.asyncio
    async def test_ctrl_break_event_signal_exists(self) -> None:
        """Verify CTRL_BREAK_EVENT signal exists on Windows."""
        assert hasattr(signal, "CTRL_BREAK_EVENT")


class TestTerminateWindowsMocked:
    """Mocked Windows termination tests (run everywhere)."""

    @pytest.mark.asyncio
    async def test_ctrl_break_sent_first(self) -> None:
        """Should send CTRL_BREAK_EVENT first."""
        process = MagicMock()
        process.wait = AsyncMock(return_value=0)

        with patch("nexus3.core.process.os.kill") as mock_kill:
            # Create a fake CTRL_BREAK_EVENT
            with patch("nexus3.core.process.signal") as mock_signal:
                mock_signal.CTRL_BREAK_EVENT = 1  # Fake value
                await _terminate_windows(process, 1234, 2.0)

                mock_kill.assert_called_once_with(1234, 1)

    @pytest.mark.asyncio
    async def test_graceful_exit_no_taskkill(self) -> None:
        """If process exits gracefully, should not call taskkill."""
        process = MagicMock()
        process.wait = AsyncMock(return_value=0)

        with patch("nexus3.core.process.os.kill"):
            with patch("nexus3.core.process.signal") as mock_signal:
                mock_signal.CTRL_BREAK_EVENT = 1
                with patch("nexus3.core.process.asyncio.create_subprocess_exec") as mock_exec:
                    await _terminate_windows(process, 1234, 2.0)

                    mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_taskkill_after_timeout(self) -> None:
        """If CTRL_BREAK doesn't work, should call taskkill."""
        process = MagicMock()

        call_count = [0]

        async def mock_wait():
            call_count[0] += 1
            if call_count[0] <= 2:
                await asyncio.sleep(10)  # Will timeout
            return 0

        process.wait = mock_wait

        taskkill_proc = MagicMock()
        taskkill_proc.wait = AsyncMock(return_value=0)

        with patch("nexus3.core.process.os.kill"):
            with patch("nexus3.core.process.signal") as mock_signal:
                mock_signal.CTRL_BREAK_EVENT = 1
                with patch("nexus3.core.process.asyncio.create_subprocess_exec",
                           return_value=taskkill_proc) as mock_exec:
                    await _terminate_windows(process, 1234, 0.01)

                    mock_exec.assert_called_once_with(
                        "taskkill", "/T", "/F", "/PID", "1234",
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )

    @pytest.mark.asyncio
    async def test_process_kill_after_taskkill_timeout(self) -> None:
        """If taskkill doesn't work, should call process.kill()."""
        process = MagicMock()

        call_count = [0]

        async def mock_wait():
            call_count[0] += 1
            if call_count[0] <= 3:
                await asyncio.sleep(10)  # Will timeout
            return 0

        process.wait = mock_wait

        taskkill_proc = MagicMock()
        taskkill_proc.wait = AsyncMock(return_value=0)

        with patch("nexus3.core.process.os.kill"):
            with patch("nexus3.core.process.signal") as mock_signal:
                mock_signal.CTRL_BREAK_EVENT = 1
                with patch("nexus3.core.process.asyncio.create_subprocess_exec",
                           return_value=taskkill_proc):
                    await _terminate_windows(process, 1234, 0.01)

                    process.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_ctrl_break_process_lookup_error(self) -> None:
        """ProcessLookupError on CTRL_BREAK should continue to taskkill."""
        process = MagicMock()
        process.wait = AsyncMock(return_value=0)

        with patch("nexus3.core.process.os.kill", side_effect=ProcessLookupError):
            with patch("nexus3.core.process.signal") as mock_signal:
                mock_signal.CTRL_BREAK_EVENT = 1
                # Should not raise
                await _terminate_windows(process, 1234, 2.0)

    @pytest.mark.asyncio
    async def test_ctrl_break_oserror(self) -> None:
        """OSError on CTRL_BREAK should continue to taskkill."""
        process = MagicMock()
        process.wait = AsyncMock(return_value=0)

        with patch("nexus3.core.process.os.kill", side_effect=OSError):
            with patch("nexus3.core.process.signal") as mock_signal:
                mock_signal.CTRL_BREAK_EVENT = 1
                # Should not raise
                await _terminate_windows(process, 1234, 2.0)

    @pytest.mark.asyncio
    async def test_ctrl_break_attribute_error(self) -> None:
        """AttributeError on CTRL_BREAK should continue to taskkill."""
        process = MagicMock()
        process.wait = AsyncMock(return_value=0)

        with patch("nexus3.core.process.os.kill", side_effect=AttributeError):
            with patch("nexus3.core.process.signal") as mock_signal:
                mock_signal.CTRL_BREAK_EVENT = 1
                # Should not raise
                await _terminate_windows(process, 1234, 2.0)

    @pytest.mark.asyncio
    async def test_taskkill_file_not_found(self) -> None:
        """FileNotFoundError for taskkill should fall back to process.kill()."""
        process = MagicMock()

        call_count = [0]

        async def mock_wait():
            call_count[0] += 1
            if call_count[0] <= 3:
                await asyncio.sleep(10)  # Will timeout
            return 0

        process.wait = mock_wait

        with patch("nexus3.core.process.os.kill"):
            with patch("nexus3.core.process.signal") as mock_signal:
                mock_signal.CTRL_BREAK_EVENT = 1
                with patch("nexus3.core.process.asyncio.create_subprocess_exec",
                           side_effect=FileNotFoundError):
                    await _terminate_windows(process, 1234, 0.01)

                    process.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_taskkill_oserror(self) -> None:
        """OSError from taskkill should fall back to process.kill()."""
        process = MagicMock()

        call_count = [0]

        async def mock_wait():
            call_count[0] += 1
            if call_count[0] <= 3:
                await asyncio.sleep(10)  # Will timeout
            return 0

        process.wait = mock_wait

        with patch("nexus3.core.process.os.kill"):
            with patch("nexus3.core.process.signal") as mock_signal:
                mock_signal.CTRL_BREAK_EVENT = 1
                with patch("nexus3.core.process.asyncio.create_subprocess_exec",
                           side_effect=OSError):
                    await _terminate_windows(process, 1234, 0.01)

                    process.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_final_kill_process_lookup_error(self) -> None:
        """ProcessLookupError on final kill should be handled gracefully."""
        process = MagicMock()
        process.kill.side_effect = ProcessLookupError

        call_count = [0]

        async def mock_wait():
            call_count[0] += 1
            if call_count[0] <= 3:
                await asyncio.sleep(10)  # Will timeout
            return 0

        process.wait = mock_wait

        with patch("nexus3.core.process.os.kill"):
            with patch("nexus3.core.process.signal") as mock_signal:
                mock_signal.CTRL_BREAK_EVENT = 1
                with patch("nexus3.core.process.asyncio.create_subprocess_exec",
                           side_effect=FileNotFoundError):
                    # Should not raise
                    await _terminate_windows(process, 1234, 0.01)


class TestCustomTimeout:
    """Test custom graceful timeout values."""

    @pytest.mark.asyncio
    async def test_custom_timeout_passed_through(self) -> None:
        """Custom timeout should be used for wait_for calls."""
        process = MagicMock()
        process.returncode = None
        process.pid = 1234
        process.wait = AsyncMock(return_value=0)

        with patch("nexus3.core.process.sys") as mock_sys:
            mock_sys.platform = "linux"
            with patch("nexus3.core.process.os.getpgid", return_value=5678):
                with patch("nexus3.core.process.os.killpg"):
                    with patch("nexus3.core.process.asyncio.wait_for",
                               wraps=asyncio.wait_for) as mock_wait_for:
                        await terminate_process_tree(process, graceful_timeout=5.0)

                        # Check that wait_for was called with the custom timeout
                        assert any(
                            call.kwargs.get("timeout") == 5.0
                            for call in mock_wait_for.call_args_list
                        )

    @pytest.mark.asyncio
    async def test_zero_timeout(self) -> None:
        """Zero timeout should immediately escalate to forceful kill."""
        process = MagicMock()

        wait_call_count = [0]

        async def mock_wait():
            wait_call_count[0] += 1
            # Simulate process that takes a bit to exit
            if wait_call_count[0] == 1:
                await asyncio.sleep(0.1)
            return 0

        process.wait = mock_wait

        with patch("nexus3.core.process.os.getpgid", return_value=5678):
            with patch("nexus3.core.process.os.killpg") as mock_killpg:
                # Use very small timeout
                await _terminate_unix(process, 1234, 0.001)

                # Should have escalated to SIGKILL
                assert mock_killpg.call_count == 2
