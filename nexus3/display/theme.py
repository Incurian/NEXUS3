"""Theme definitions for NEXUS3 display system."""

from dataclasses import dataclass, field
from enum import Enum


class Status(Enum):
    """Status states for gumball indicators."""
    ACTIVE = "active"
    PENDING = "pending"
    COMPLETE = "complete"
    ERROR = "error"
    CANCELLED = "cancelled"


class Activity(Enum):
    """Current activity states for the summary bar."""
    IDLE = "idle"
    THINKING = "thinking"
    RESPONDING = "responding"
    TOOL_CALLING = "tool_calling"


@dataclass
class Theme:
    """Visual theme configuration.

    All styling in one place for easy customization.
    """
    # Gumball characters with Rich markup colors
    gumballs: dict[Status, str] = field(default_factory=lambda: {
        Status.ACTIVE: "[cyan]●[/]",
        Status.PENDING: "[dim]○[/]",
        Status.COMPLETE: "[green]●[/]",
        Status.ERROR: "[red]●[/]",
        Status.CANCELLED: "[yellow]●[/]",
    })

    # Spinner frames for animated spinner in summary bar
    spinner_frames: str = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    # Text styles (Rich style strings)
    thinking: str = "dim italic"
    thinking_collapsed: str = "dim"
    response: str = ""
    error: str = "bold red"
    user_input: str = "bold"

    # Summary bar styles
    summary_style: str = ""
    summary_separator: str = " | "

    def gumball(self, status: Status) -> str:
        """Get the gumball character for a status."""
        return self.gumballs.get(status, "○")


# Default theme instance
DEFAULT_THEME = Theme()


def load_theme(overrides: dict[str, str] | None = None) -> Theme:
    """Load theme with optional overrides from config."""
    if not overrides:
        return Theme()

    # Apply overrides (future: deep merge from config)
    theme = Theme()
    # Could override individual fields here from config
    return theme
