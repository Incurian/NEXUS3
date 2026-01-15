"""P1.4: Test that subprocess timeout kills entire process group.

This tests the security issue where process.kill() only kills the parent process,
leaving child processes as orphans that continue running.

The fix uses start_new_session=True + os.killpg() to kill the entire process group.
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest


# Skip on Windows - process groups work differently
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Process groups not available on Windows"
)


@pytest.fixture
def services():
    """Create minimal ServiceContainer for tests."""
    from nexus3.skill.services import ServiceContainer

    container = ServiceContainer()
    container.register("cwd", "/tmp")
    return container


class TestProcessGroupKill:
    """Test that subprocess timeout kills entire process groups."""

    async def test_child_processes_killed_on_timeout_shell_unsafe(
        self, services, tmp_path: Path
    ) -> None:
        """ShellUnsafeSkill should kill child processes on timeout."""
        from nexus3.skill.builtin.bash import ShellUnsafeSkill

        skill = ShellUnsafeSkill(services)

        # Write child PID to file so we can check if it's still running after timeout
        pid_file = tmp_path / "child_pid"

        # Command that spawns a background child which writes its PID then sleeps
        # The parent also sleeps (will be killed by timeout)
        command = f"bash -c 'sleep 300 & echo $! > {pid_file}; sleep 300'"

        # Execute with short timeout
        result = await skill.execute(command=command, timeout=2)

        # Should timeout
        assert result.error is not None
        assert "timed out" in result.error.lower()

        # Wait for cleanup
        await asyncio.sleep(0.5)

        # Check if child PID file exists and if that process was killed
        if pid_file.exists():
            child_pid = int(pid_file.read_text().strip())

            # Check if the child process is still running
            try:
                os.kill(child_pid, 0)  # Signal 0 just checks if process exists
                # If we get here, process is still running - BAD!
                # Clean it up so we don't leave orphans
                os.kill(child_pid, 9)
                pytest.fail(
                    f"Child process {child_pid} survived timeout - "
                    "process group kill failed!"
                )
            except ProcessLookupError:
                # Good - child was killed
                pass
            except PermissionError:
                # Process exists but we can't signal it - might be orphan
                pytest.fail(
                    f"Child process {child_pid} may have survived as orphan"
                )

    async def test_child_processes_killed_on_timeout_run_python(
        self, services, tmp_path: Path
    ) -> None:
        """RunPythonSkill should kill child processes on timeout."""
        from nexus3.skill.builtin.run_python import RunPythonSkill

        skill = RunPythonSkill(services)

        # Python code that spawns a child process
        code = f'''
import subprocess
import time

# Spawn a child that will sleep forever
child = subprocess.Popen(['sleep', '300'])

# Write child PID to a file so we can check if it's still running
with open("{tmp_path}/child_pid", "w") as f:
    f.write(str(child.pid))

# Parent sleeps (will be killed by timeout)
time.sleep(300)
'''

        # Execute with short timeout
        result = await skill.execute(code=code, timeout=2)

        # Should timeout
        assert result.error is not None
        assert "timed out" in result.error.lower()

        # Wait for cleanup
        await asyncio.sleep(0.5)

        # Check if child PID file exists and if that process is still running
        pid_file = tmp_path / "child_pid"
        if pid_file.exists():
            child_pid = int(pid_file.read_text().strip())

            # Check if the child process is still running
            try:
                os.kill(child_pid, 0)  # Signal 0 just checks if process exists
                # If we get here, process is still running - BAD!
                # Clean it up
                os.kill(child_pid, 9)
                pytest.fail(
                    f"Child process {child_pid} survived timeout - "
                    "process group kill failed!"
                )
            except ProcessLookupError:
                # Good - child was killed
                pass
            except PermissionError:
                # Process exists but we can't signal it
                pytest.fail(
                    f"Child process {child_pid} may have survived as orphan"
                )


class TestStartNewSession:
    """Test that start_new_session=True is set in subprocess creation."""

    async def test_process_is_session_leader(self, services) -> None:
        """Spawned processes should be session leaders (PID == PGID)."""
        from nexus3.skill.builtin.bash import ShellUnsafeSkill

        skill = ShellUnsafeSkill(services)

        # With start_new_session=True, the shell process should be its own
        # session leader, meaning its PID equals its PGID
        result = await skill.execute(
            command="ps -o pid=,pgid= -p $$",
            timeout=5
        )

        assert result.output is not None
        # Parse output: should show PID and PGID as equal
        parts = result.output.strip().split()
        if len(parts) >= 2:
            pid = int(parts[0])
            pgid = int(parts[1])
            # With start_new_session=True, the process becomes session leader
            # meaning PID == PGID
            assert pid == pgid, (
                f"Process {pid} is not session leader (PGID={pgid}). "
                "start_new_session=True may not be set."
            )


class TestTimeoutKillFallback:
    """Test that Windows fallback works (process.kill() used when killpg fails)."""

    async def test_basic_timeout_still_works(self, services) -> None:
        """Even without process groups, basic timeout should still kill parent."""
        from nexus3.skill.builtin.bash import ShellUnsafeSkill

        skill = ShellUnsafeSkill(services)

        # Simple sleep that will timeout
        result = await skill.execute(command="sleep 30", timeout=1)

        # Should timeout
        assert result.error is not None
        assert "timed out" in result.error.lower()

    async def test_normal_command_completes(self, services) -> None:
        """Commands that complete before timeout should work normally."""
        from nexus3.skill.builtin.bash import ShellUnsafeSkill

        skill = ShellUnsafeSkill(services)

        result = await skill.execute(command="echo hello", timeout=10)

        assert result.output is not None
        assert "hello" in result.output
        assert not result.error  # Empty string or None means no error
