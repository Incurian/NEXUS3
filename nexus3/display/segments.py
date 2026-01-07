"""Pluggable segments for the summary bar."""

from typing import Protocol

from rich.text import Text

from nexus3.display.theme import Activity, Status, Theme


class SummarySegment(Protocol):
    """Protocol for summary bar segments."""

    @property
    def visible(self) -> bool:
        """Whether this segment should be displayed."""
        ...

    def render(self) -> Text:
        """Render the segment content."""
        ...


class ActivitySegment:
    """Shows current activity with animated spinner.

    Example: "spinner responding" or "spinner thinking"
    """

    SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, theme: Theme) -> None:
        self.theme = theme
        self.activity: Activity = Activity.IDLE
        self._frame = 0

    @property
    def visible(self) -> bool:
        return self.activity != Activity.IDLE

    def render(self) -> Text:
        spinner = self.SPINNER_FRAMES[self._frame % len(self.SPINNER_FRAMES)]
        self._frame += 1
        return Text(f"{spinner} {self.activity.value}", style="cyan")

    def set_activity(self, activity: Activity) -> None:
        """Update the current activity."""
        self.activity = activity
        if activity == Activity.IDLE:
            self._frame = 0  # Reset spinner


class TaskCountSegment:
    """Shows task counts: active pending done failed"""

    def __init__(self, theme: Theme) -> None:
        self.theme = theme
        self.active = 0
        self.pending = 0
        self.done = 0
        self.failed = 0

    @property
    def visible(self) -> bool:
        return (self.active + self.pending + self.done + self.failed) > 0

    def render(self) -> Text:
        parts: list[str] = []
        if self.active:
            parts.append(f"{self.theme.gumball(Status.ACTIVE)} {self.active} active")
        if self.pending:
            parts.append(f"{self.theme.gumball(Status.PENDING)} {self.pending} pending")
        if self.done:
            parts.append(f"{self.theme.gumball(Status.COMPLETE)} {self.done} done")
        if self.failed:
            parts.append(f"{self.theme.gumball(Status.ERROR)} {self.failed} failed")
        return Text(" ".join(parts))

    def add_task(self) -> None:
        """Register a new pending task."""
        self.pending += 1

    def start_task(self) -> None:
        """Move a task from pending to active."""
        if self.pending > 0:
            self.pending -= 1
        self.active += 1

    def complete_task(self, success: bool = True) -> None:
        """Complete an active task."""
        if self.active > 0:
            self.active -= 1
        if success:
            self.done += 1
        else:
            self.failed += 1

    def reset(self) -> None:
        """Reset all counts."""
        self.active = 0
        self.pending = 0
        self.done = 0
        self.failed = 0


class CancelHintSegment:
    """Shows 'ESC cancel' hint when activity is happening."""

    def __init__(self) -> None:
        self.show = False

    @property
    def visible(self) -> bool:
        return self.show

    def render(self) -> Text:
        return Text("ESC cancel", style="dim")


# Future segments can be added:
# - TokenCountSegment: "1.2k / 8k tokens"
# - SubagentSegment: "agent:analyzer agent:fixer"
# - WorkflowSegment: "Step 2/5: analyzing"
