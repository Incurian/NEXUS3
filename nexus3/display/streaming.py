"""Streaming display using Rich.Live for all output."""

from rich.console import Group, RenderableType
from rich.text import Text

from nexus3.display.theme import Activity, Theme


class StreamingDisplay:
    """Display that accumulates streamed content within Rich.Live.

    This class implements __rich__ so it can be used directly with Rich.Live.
    All content (status, response, etc.) is rendered together on each refresh.

    Example:
        display = StreamingDisplay(theme)
        with Live(display, refresh_per_second=10) as live:
            display.set_activity(Activity.THINKING)
            async for chunk in stream:
                display.add_chunk(chunk)
                live.refresh()
            display.set_activity(Activity.IDLE)
    """

    SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, theme: Theme) -> None:
        self.theme = theme
        self.activity = Activity.IDLE
        self.response = ""
        self._frame = 0
        self._cancelled = False

    def __rich__(self) -> RenderableType:
        """Render the streaming display state.

        Only used during Live context for streaming phase.
        """
        parts: list[RenderableType] = []

        # Increment frame for spinner animation
        spinner = self.SPINNER_FRAMES[self._frame % len(self.SPINNER_FRAMES)]
        self._frame += 1

        # Response content (main area)
        if self.response:
            parts.append(Text(self.response))

        # Activity status line
        if self.activity == Activity.WAITING:
            status = "Waiting for response..."
        elif self.activity == Activity.THINKING:
            status = "Thinking..."
        else:
            status = "Responding..."
        parts.append(Text(f"\n{spinner} {status}", style="dim cyan"))

        # Status bar
        parts.append(Text("\n"))
        parts.append(self._render_status_bar(spinner))

        return Group(*parts) if parts else Text("")

    def _render_status_bar(self, spinner: str) -> Text:
        """Render the status bar with spinner/gumball (always active during streaming)."""
        bar = Text()
        bar.append(f"{spinner} ", style="cyan")
        bar.append("● ", style="cyan")
        bar.append("active", style="cyan")
        bar.append(" | ", style="dim")
        bar.append("ESC cancel", style="dim")
        return bar

    def set_activity(self, activity: Activity) -> None:
        """Update the current activity state."""
        self.activity = activity
        if activity == Activity.IDLE:
            self._frame = 0

    def add_chunk(self, chunk: str) -> None:
        """Add a chunk to the response buffer."""
        self.response += chunk
        if self.activity == Activity.THINKING:
            self.activity = Activity.RESPONDING

    def cancel(self) -> None:
        """Mark as cancelled."""
        self._cancelled = True
        self.activity = Activity.IDLE

    def reset(self) -> None:
        """Reset for a new response."""
        self.response = ""
        self.activity = Activity.IDLE
        self._frame = 0
        self._cancelled = False

    @property
    def is_cancelled(self) -> bool:
        """Check if cancelled."""
        return self._cancelled
