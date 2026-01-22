"""Simple spinner display for NEXUS3.

Provides a single animated spinner pinned to the bottom of the terminal,
with all other output printed above it via console.print().
"""

from __future__ import annotations

import time
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.text import Text

from nexus3.core.text_safety import strip_terminal_escapes
from nexus3.display.console import get_console
from nexus3.display.theme import Activity, Theme, load_theme


class Spinner:
    """Animated spinner with text, pinned to bottom of terminal.

    All output during an agent turn should go through spinner.print() which
    delegates to the Live console, ensuring text appears above the spinner.

    Usage:
        spinner = Spinner()
        spinner.show("Waiting...")

        # Print content above spinner
        spinner.print("Some output")
        spinner.print("More output", end="")  # streaming

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
        self.theme = theme or load_theme()
        self.text = ""
        self.activity = Activity.IDLE
        self.show_cancel_hint = True
        self._live: Live | None = None
        self._start_time: float = 0.0
        self._stream_buffer: str = ""  # Buffer for incomplete lines

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
        # Flush any remaining buffered stream content before hiding
        self.flush_stream()
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

    def print(self, *args: Any, **kwargs: Any) -> None:
        """Print above the spinner.

        When Live is active, this delegates to live.console.print() so the
        output appears above the spinner. When Live is not active, prints
        directly to the console.

        Args:
            *args: Positional arguments passed to console.print().
            **kwargs: Keyword arguments passed to console.print().
        """
        if self._live:
            self._live.console.print(*args, **kwargs)
        else:
            self.console.print(*args, **kwargs)

    def print_streaming(self, chunk: str) -> None:
        """Print a streaming chunk (no newline, sanitized).

        Buffers text until a complete line (ending with newline) is available,
        then prints directly to stdout. Partial lines are buffered until complete.

        Args:
            chunk: Text chunk to print (will be sanitized).
        """
        import sys
        sanitized = strip_terminal_escapes(chunk)
        if not sanitized:
            return

        # Add to buffer
        self._stream_buffer += sanitized

        # Print complete lines (those ending with newline)
        while "\n" in self._stream_buffer:
            line, self._stream_buffer = self._stream_buffer.split("\n", 1)
            # Bypass Rich entirely - write directly to stdout
            sys.stdout.write(line + "\n")
            sys.stdout.flush()

    def flush_stream(self) -> None:
        """Flush any remaining buffered streaming content.

        Call this when streaming ends to ensure partial lines are displayed.
        """
        import sys
        if self._stream_buffer:
            sys.stdout.write(self._stream_buffer)
            sys.stdout.flush()
            self._stream_buffer = ""

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
            parts.append(self.text or "Running tools...")
        else:
            parts.append(self.text or "")

        # Elapsed time (show after 1 second)
        elapsed = self.elapsed
        if elapsed >= 1.0:
            parts.append(f"({elapsed:.0f}s)")

        status = " ".join(filter(None, parts))
        # Live renderable must remain single-line.
        status = status.replace("\n", " ")

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
