"""Cross-platform process termination utilities.

Provides robust process tree termination that works on both Unix and Windows:
- Unix: SIGTERM -> wait -> SIGKILL to process group
- Windows: CTRL_BREAK_EVENT -> wait -> taskkill /T /F -> TerminateProcess
"""

import asyncio
import logging
import os
import signal
import subprocess
import sys
from asyncio.subprocess import Process

logger = logging.getLogger(__name__)

GRACEFUL_TIMEOUT: float = 2.0

# Windows-specific creation flags (only defined on Windows)
if sys.platform == "win32":
    WINDOWS_CREATIONFLAGS = (
        subprocess.CREATE_NEW_PROCESS_GROUP |
        subprocess.CREATE_NO_WINDOW
    )
else:
    WINDOWS_CREATIONFLAGS = 0


async def terminate_process_tree(
    process: Process,
    graceful_timeout: float = GRACEFUL_TIMEOUT,
) -> None:
    """Terminate a process and all its children.

    Attempts graceful termination first, then falls back to forceful kill.

    Args:
        process: The asyncio subprocess to terminate.
        graceful_timeout: Time in seconds to wait for graceful termination
            before escalating to forceful kill.

    On Unix:
        1. Send SIGTERM to process group
        2. Wait for graceful_timeout
        3. If still running, send SIGKILL to process group

    On Windows:
        1. Send CTRL_BREAK_EVENT
        2. Wait for graceful_timeout
        3. If still running, use taskkill /T /F for tree kill
        4. If still running, call process.kill() as final fallback
    """
    if process.returncode is not None:
        return

    pid = process.pid
    if pid is None:
        return

    if sys.platform == "win32":
        await _terminate_windows(process, pid, graceful_timeout)
    else:
        await _terminate_unix(process, pid, graceful_timeout)


async def _terminate_unix(process: Process, pid: int, graceful_timeout: float) -> None:
    """Unix: SIGTERM -> wait -> SIGKILL to process group."""
    # Step 1: Graceful SIGTERM to process group
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)
        logger.debug("Sent SIGTERM to process group %d", pgid)
    except (ProcessLookupError, PermissionError, OSError):
        # Process group not found or no permission, try single process
        try:
            process.terminate()
        except ProcessLookupError:
            return

    # Step 2: Wait for graceful termination
    try:
        await asyncio.wait_for(process.wait(), timeout=graceful_timeout)
        return
    except TimeoutError:
        pass

    # Step 3: Forceful SIGKILL to process group
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGKILL)
        logger.debug("Sent SIGKILL to process group %d", pgid)
    except (ProcessLookupError, PermissionError, OSError):
        # Process group not found, try single process
        try:
            process.kill()
        except ProcessLookupError:
            pass

    # Step 4: Wait for process to fully exit
    try:
        await process.wait()
    except Exception:
        pass


async def _terminate_windows(process: Process, pid: int, graceful_timeout: float) -> None:
    """Windows: CTRL_BREAK -> wait -> taskkill /T /F -> kill."""
    # Step 1: Graceful CTRL_BREAK_EVENT
    try:
        os.kill(pid, signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
        logger.debug("Sent CTRL_BREAK_EVENT to process %d", pid)
    except (ProcessLookupError, OSError, AttributeError):
        pass

    # Step 2: Wait for graceful termination
    try:
        await asyncio.wait_for(process.wait(), timeout=graceful_timeout)
        return
    except TimeoutError:
        pass

    # Step 3: taskkill for process tree
    try:
        taskkill = await asyncio.create_subprocess_exec(
            "taskkill", "/T", "/F", "/PID", str(pid),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            creationflags=WINDOWS_CREATIONFLAGS,
        )
        await asyncio.wait_for(taskkill.wait(), timeout=graceful_timeout)
        logger.debug("taskkill /T /F completed for PID %d", pid)
    except (FileNotFoundError, TimeoutError, OSError):
        pass

    # Step 4: Check if process exited after taskkill
    try:
        await asyncio.wait_for(process.wait(), timeout=0.5)
        return
    except TimeoutError:
        pass

    # Step 5: Final fallback - direct kill
    try:
        process.kill()
    except ProcessLookupError:
        pass

    # Step 6: Wait for process to fully exit
    try:
        await process.wait()
    except Exception:
        pass
