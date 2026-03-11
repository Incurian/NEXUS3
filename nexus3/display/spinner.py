"""Simple spinner display for NEXUS3.

Provides a single animated spinner pinned to the bottom of the terminal,
with all other output printed above it via console.print().
"""

from __future__ import annotations

import sys
import time
from typing import Any

from rich.color import ColorSystem
from rich.console import Console
from rich.live import Live
from rich.style import Style
from rich.text import Text

from nexus3.display.console import get_console
from nexus3.display.safe_sink import SafeSink
from nexus3.display.theme import Activity, Theme, load_theme


class Spinner:
    """Animated spinner with text, pinned to bottom of terminal.

    All output during an agent turn should go through spinner.print_*() helpers
    so trust boundaries are explicit while ensuring text appears above the spinner.

    Usage:
        spinner = Spinner()
        spinner.show("Waiting...")

        # Print content above spinner
        spinner.print_untrusted("Some output")
        spinner.print_trusted("[dim]Debug[/]", end="")

        # Update spinner text
        spinner.update("Processing...")

        # Hide when done
        spinner.hide()
    """

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(
        self,
        console: Console | None = None,
        theme: Theme | None = None,
    ) -> None:
        """Initialize spinner.

        Args:
            console: Rich Console to use. Defaults to shared console.
            theme: Theme for styling. Defaults to default theme.
        """
        self.console = console or get_console()
        self.safe_sink = SafeSink(self.console)
        self.theme = theme or load_theme()
        self.text = ""
        self.activity = Activity.IDLE
        self.show_cancel_hint = True
        self._live: Live | None = None
        self._start_time: float = 0.0
        self._stream_buffer: str = ""  # Buffer for incomplete lines
        self._stream_line_open = False  # Whether visible stream output left cursor mid-line
        self._stream_style: Style | None = None
        if self.theme.response:
            self._stream_style = Style.parse(self.theme.response)

    def show(self, text: str = "", activity: Activity = Activity.WAITING) -> None:
        """Start showing the spinner.

        Args:
            text: Initial text to display next to spinner.
            activity: Initial activity state.
        """
        self.text = text
        self.activity = activity
        self._start_time = time.monotonic()
        self._stream_buffer = ""  # Clear any stale buffer
        self._stream_line_open = False

        if self._live is None:
            # IMPORTANT Rich.Live behaviors:
            #
            # 1) Live refreshes by clearing the *live render region* and
            #    re-rendering. If our spinner line wraps to multiple terminal
            #    lines, Live may clear more than one row and can erase
            #    in-progress streamed assistant output that hasn't terminated
            #    with a newline yet.
            #    -> We enforce a single-line render in __rich__ (no_wrap + crop).
            #
            # 2) Anything that writes directly to stdout/stderr while Live is
            #    running (e.g., warning logs to stderr) can push the live region
            #    into scrollback, leaving a static spinner artifact.
            #    -> Redirect stdout/stderr through Live so it prints above.
            self._live = Live(
                self,
                console=self.console,
                auto_refresh=True,
                refresh_per_second=10,
                transient=True,  # Don't leave spinner in scrollback
                redirect_stdout=True,
                redirect_stderr=True,
            )
            self._live.start()

    def update(self, text: str | None = None, activity: Activity | None = None) -> None:
        """Update spinner text and/or activity.

        Args:
            text: New text to display. None keeps current.
            activity: New activity state. None keeps current.
        """
        if text is not None:
            self.text = text
        if activity is not None:
            self.activity = activity
        if self._live:
            self._live.refresh()

    def hide(self) -> None:
        """Stop and hide the spinner."""
        self.finish_stream()
        if self._live:
            self._live.stop()
            self._live = None
        self.text = ""
        self.activity = Activity.IDLE

    @property
    def live(self) -> Live | None:
        """Get the underlying Live instance for permission prompt integration."""
        return self._live

    @property
    def is_active(self) -> bool:
        """Check if spinner is currently active."""
        return self._live is not None

    @property
    def elapsed(self) -> float:
        """Get elapsed time since spinner started."""
        if self._start_time:
            return time.monotonic() - self._start_time
        return 0.0

    def _print(self, *args: Any, **kwargs: Any) -> None:
        """Print above spinner through active Live console when present."""
        if self._live:
            self._live.console.print(*args, **kwargs)
        else:
            self.console.print(*args, **kwargs)

    def print_trusted(self, *args: Any, **kwargs: Any) -> None:
        """Print trusted content above the spinner without sanitization."""
        self._print(*args, **kwargs)

    def print_untrusted(
        self,
        content: str,
        *,
        style: str | None = None,
        end: str = "\n",
    ) -> None:
        """Print untrusted content above the spinner after sanitization."""
        self._print(self.safe_sink.sanitize_print_content(content), style=style, end=end)

    def print(self, *args: Any, **kwargs: Any) -> None:
        """Backward-compatible trusted print alias.

        Prefer explicit `print_trusted(...)` or `print_untrusted(...)`.
        """
        self.print_trusted(*args, **kwargs)

    def _render_stream_text(self, text: str) -> str:
        """Apply configured response styling to raw streaming text."""
        if not text or self._stream_style is None:
            return text

        no_color = getattr(self.console, "no_color", False)
        if isinstance(no_color, bool) and no_color:
            return text

        color_system = getattr(self.console, "color_system", None)
        if color_system is not None and not isinstance(color_system, ColorSystem):
            color_system = ColorSystem.TRUECOLOR
        legacy_windows = getattr(self.console, "legacy_windows", False)
        if not isinstance(legacy_windows, bool):
            legacy_windows = False
        return self._stream_style.render(
            text,
            color_system=color_system,
            legacy_windows=legacy_windows,
        )

    def _write_stream_text(self, text: str, *, newline: bool = False) -> None:
        """Write already-sanitized streaming text through stdout above Live."""
        if not text:
            return
        rendered = self._render_stream_text(text)
        if newline:
            rendered += "\n"
        sys.stdout.write(rendered)
        sys.stdout.flush()

    def print_streaming(self, chunk: str) -> None:
        """Print a streaming chunk (no newline, sanitized).

        Buffers text until a complete line (ending with newline) is available,
        then prints directly to stdout. Partial lines are buffered until complete.

        Args:
            chunk: Text chunk to print (will be sanitized).
        """
        sanitized = SafeSink.sanitize_stream_content(chunk)
        if not sanitized:
            return

        # Add to buffer
        self._stream_buffer += sanitized

        # Print complete lines (those ending with newline)
        while "\n" in self._stream_buffer:
            line, self._stream_buffer = self._stream_buffer.split("\n", 1)
            self._write_stream_text(line, newline=True)
            self._stream_line_open = False

    def flush_stream(self, *, ensure_newline: bool = True) -> None:
        """Flush any remaining buffered streaming content.

        Call this when streaming ends to ensure partial lines are displayed.
        """
        if not self._stream_buffer:
            return

        remaining = self._stream_buffer
        self._stream_buffer = ""
        if ensure_newline:
            self._write_stream_text(remaining, newline=True)
            self._stream_line_open = False
            return

        self._write_stream_text(remaining)
        self._stream_line_open = True

    def ensure_stream_line_break(self) -> None:
        """Terminate the current visible stream line before non-stream output."""
        if self._stream_buffer:
            self.flush_stream(ensure_newline=True)
            return

        if self._stream_line_open:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._stream_line_open = False

    def prepare_for_block_output(self) -> None:
        """Flush streaming state so the next printed block starts on a fresh line."""
        self.ensure_stream_line_break()

    def finish_stream(self) -> None:
        """Flush and terminate any in-progress streamed output."""
        self.ensure_stream_line_break()

    def __rich__(self) -> Text:
        """Render the spinner for Rich.Live."""
        # Animated spinner frame
        frame_idx = int(time.time() * 10) % len(self.FRAMES)
        frame = self.FRAMES[frame_idx]

        # Build status text
        parts: list[str] = []

        # Activity text
        if self.activity == Activity.WAITING:
            parts.append("Waiting...")
        elif self.activity == Activity.THINKING:
            parts.append("Thinking...")
        elif self.activity == Activity.RESPONDING:
            parts.append("Responding...")
        elif self.activity == Activity.TOOL_CALLING:
            if self.text:
                parts.append(SafeSink.sanitize_print_value(self.text))
            else:
                parts.append("Running tools...")
        else:
            if self.text:
                parts.append(SafeSink.sanitize_print_value(self.text))

        # Elapsed time (show after 1 second)
        elapsed = self.elapsed
        if elapsed >= 1.0:
            parts.append(f"({elapsed:.0f}s)")

        status = " ".join(filter(None, parts))
        # Live renderable must remain single-line.
        status = status.replace("\n", " ").replace("\r", " ")

        # Build the line: spinner + status + cancel hint
        result = Text()
        # CRITICAL: prevent wrapping (wrapping makes Live occupy >1 line, which
        # can cause Live refresh clears to erase the last streamed output line).
        result.no_wrap = True
        result.overflow = "crop"
        result.append(f"{frame} ", style="cyan")
        result.append(status, style="cyan")

        if self.show_cancel_hint:
            result.append(" | ", style="dim")
            result.append("ESC cancel", style="dim")

        return result
