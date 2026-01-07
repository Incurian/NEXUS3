"""Summary bar component using Rich.Live."""

from collections.abc import Generator
from contextlib import contextmanager

from rich.console import Console, RenderableType
from rich.live import Live
from rich.text import Text

from nexus3.display.segments import SummarySegment
from nexus3.display.theme import Theme


class SummaryBar:
    """Bottom-anchored summary bar using Rich.Live.

    This is the only Rich.Live component - it renders registered segments
    and refreshes automatically to animate spinners.

    Example:
        bar = SummaryBar(console, theme)
        bar.register_segment(ActivitySegment(theme))
        bar.register_segment(TaskCountSegment(theme))

        with bar.live():
            # While in this context, the bar updates automatically
            ...
    """

    def __init__(self, console: Console, theme: Theme) -> None:
        self.console = console
        self.theme = theme
        self.segments: list[SummarySegment] = []
        self._live: Live | None = None

    def register_segment(self, segment: SummarySegment, position: int = -1) -> None:
        """Register a segment to display in the bar.

        Args:
            segment: The segment to add
            position: Position in the bar (-1 for end)
        """
        if position < 0:
            self.segments.append(segment)
        else:
            self.segments.insert(position, segment)

    def unregister_segment(self, segment: SummarySegment) -> None:
        """Remove a segment from the bar."""
        if segment in self.segments:
            self.segments.remove(segment)

    @contextmanager
    def live(self) -> Generator[None, None, None]:
        """Context manager for Rich.Live updates.

        While in this context, the summary bar refreshes automatically.
        """
        self._live = Live(
            self._render(),
            console=self.console,
            refresh_per_second=4,  # 4Hz for smooth spinner animation
            transient=True,        # Don't leave artifacts when done
        )
        try:
            with self._live:
                yield
        finally:
            self._live = None

    def refresh(self) -> None:
        """Manually refresh the summary bar."""
        if self._live:
            self._live.update(self._render())

    def _render(self) -> RenderableType:
        """Compose all visible segments into a single line."""
        visible_segments = [seg for seg in self.segments if seg.visible]

        if not visible_segments:
            return Text("")  # Empty bar when nothing to show

        # Join segments with separator
        result = Text()
        separator = Text(self.theme.summary_separator, style="dim")

        for i, segment in enumerate(visible_segments):
            if i > 0:
                result.append(separator)
            result.append(segment.render())

        return result

    @property
    def is_live(self) -> bool:
        """Check if the summary bar is currently live."""
        return self._live is not None
