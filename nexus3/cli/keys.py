"""Key handling for NEXUS3 CLI.

Provides ESC key detection during async operations.
"""

import asyncio
import sys
from collections.abc import Callable

# ESC key code
ESC = "\x1b"


async def monitor_for_escape(
    on_escape: Callable[[], None],
    pause_event: asyncio.Event,
    check_interval: float = 0.1,
) -> None:
    """Monitor stdin for ESC key and call callback when detected.

    This should be run as a background task during operations.

    Args:
        on_escape: Callback to invoke when ESC is pressed
        pause_event: asyncio.Event that signals when key monitoring should pause
        check_interval: How often to check for input (seconds)

    Note:
        This function runs until cancelled. It should be used with
        asyncio.create_task() and cancelled when the operation completes.
    """
    try:
        # Try to use non-blocking input (Unix only)
        import select
        import termios
        import tty

        old_settings = termios.tcgetattr(sys.stdin)
        try:
            tty.setcbreak(sys.stdin.fileno())

            while True:
                # Check if paused (for confirmation prompts)
                if pause_event.is_set():
                    # Restore terminal while paused so other input can work
                    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
                    while pause_event.is_set():
                        await asyncio.sleep(check_interval)
                    # Re-enable cbreak mode when resumed
                    tty.setcbreak(sys.stdin.fileno())
                    continue

                # Check if input is available
                readable, _, _ = select.select([sys.stdin], [], [], check_interval)

                if readable:
                    char = sys.stdin.read(1)
                    if char == ESC:
                        on_escape()
                        # Don't break - let the caller cancel us

                await asyncio.sleep(0)  # Yield to event loop

        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

    except (ImportError, OSError, AttributeError):
        # Fallback for Windows or when terminal isn't available
        # On Windows, we'd need msvcrt or similar
        # For now, just sleep and let the operation complete normally
        while True:
            await asyncio.sleep(check_interval)


class KeyMonitor:
    """Context manager for monitoring keys during an operation.

    Example:
        pause_event = asyncio.Event()
        async with KeyMonitor(on_escape=token.cancel, pause_event=pause_event):
            # ESC will trigger token.cancel() while in this block
            await long_operation()
    """

    def __init__(self, on_escape: Callable[[], None], pause_event: asyncio.Event) -> None:
        self.on_escape = on_escape
        self.pause_event = pause_event
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "KeyMonitor":
        self._task = asyncio.create_task(
            monitor_for_escape(self.on_escape, self.pause_event)
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
