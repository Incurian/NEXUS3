"""Central display coordinator for NEXUS3."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from rich.console import Console

from nexus3.core.cancel import CancellationToken
from nexus3.display.console import get_console
from nexus3.display.printer import InlinePrinter
from nexus3.display.segments import ActivitySegment, CancelHintSegment, TaskCountSegment
from nexus3.display.summary import SummaryBar
from nexus3.display.theme import Activity, Status, Theme, load_theme


class DisplayManager:
    """Central coordinator for all terminal display.

    Owns the printer (inline output), summary bar (Rich.Live), and
    coordinates cancellation. All display should go through this.

    Example:
        display = DisplayManager()

        async with display.live_session():
            display.set_activity(Activity.THINKING)
            async for chunk in stream:
                if display.is_cancelled:
                    break
                display.print_streaming(chunk)
            display.set_activity(Activity.IDLE)
    """

    def __init__(
        self,
        console: Console | None = None,
        theme: Theme | None = None,
    ) -> None:
        self.console = console or get_console()
        self.theme = theme or load_theme()

        # Components
        self.printer = InlinePrinter(self.console, self.theme)
        self.summary = SummaryBar(self.console, self.theme)

        # Default segments
        self._activity_segment = ActivitySegment(self.theme)
        self._task_segment = TaskCountSegment(self.theme)
        self._cancel_hint = CancelHintSegment()

        self.summary.register_segment(self._activity_segment)
        self.summary.register_segment(self._task_segment)
        self.summary.register_segment(self._cancel_hint)

        # Cancellation
        self._cancel_token: CancellationToken | None = None

    @property
    def cancel_token(self) -> CancellationToken | None:
        """Get the current cancellation token."""
        return self._cancel_token

    @property
    def is_cancelled(self) -> bool:
        """Check if current operation is cancelled."""
        return self._cancel_token is not None and self._cancel_token.is_cancelled

    def cancel(self) -> None:
        """Cancel the current operation (called when ESC pressed)."""
        if self._cancel_token:
            self._cancel_token.cancel()
            self._activity_segment.set_activity(Activity.IDLE)
            self._cancel_hint.show = False
            self.summary.refresh()

    @asynccontextmanager
    async def live_session(self) -> AsyncGenerator[None, None]:
        """Context manager for a live display session.

        While in this context:
        - Summary bar is live (refreshes automatically)
        - Cancellation token is active
        - ESC hint is shown when activity is non-idle
        """
        self._cancel_token = CancellationToken()
        try:
            with self.summary.live():
                yield
        finally:
            self._cancel_token = None
            self._cancel_hint.show = False

    # === Activity Management ===

    def set_activity(self, activity: Activity) -> None:
        """Set the current activity state."""
        self._activity_segment.set_activity(activity)
        self._cancel_hint.show = activity != Activity.IDLE
        self.summary.refresh()

    # === Task Tracking ===

    def add_task(self) -> None:
        """Register a new pending task."""
        self._task_segment.add_task()
        self.summary.refresh()

    def start_task(self) -> None:
        """Move a task from pending to active."""
        self._task_segment.start_task()
        self.summary.refresh()

    def complete_task(self, success: bool = True) -> None:
        """Complete an active task."""
        self._task_segment.complete_task(success)
        self.summary.refresh()

    def reset_tasks(self) -> None:
        """Reset task counts."""
        self._task_segment.reset()
        self.summary.refresh()

    # === Inline Printing (delegates to printer) ===

    def print(self, content: str, style: str | None = None) -> None:
        """Print content (scrolls)."""
        self.printer.print(content, style=style)

    def print_gumball(self, status: Status, message: str, indent: int = 0) -> None:
        """Print a gumball indicator with message."""
        self.printer.print_gumball(status, message, indent=indent)

    def print_thinking(self, content: str, collapsed: bool = True) -> None:
        """Print thinking trace inline."""
        self.printer.print_thinking(content, collapsed=collapsed)

    def print_task_start(self, task_type: str, label: str) -> None:
        """Print task starting."""
        self.printer.print_task_start(task_type, label)

    def print_task_end(self, task_type: str, success: bool) -> None:
        """Print task completion."""
        self.printer.print_task_end(task_type, success)

    def print_error(self, message: str) -> None:
        """Print error message."""
        self.printer.print_error(message)

    def print_cancelled(self, message: str = "Cancelled") -> None:
        """Print cancellation message."""
        self.printer.print_cancelled(message)

    def print_streaming(self, chunk: str) -> None:
        """Print a streaming chunk without newline."""
        self.printer.print_streaming_chunk(chunk)

    def finish_streaming(self) -> None:
        """Finish streaming output."""
        self.printer.finish_streaming()
