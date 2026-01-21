"""Streaming display using Rich.Live for all output."""

import time
from dataclasses import dataclass
from enum import Enum

from rich.console import Group, RenderableType
from rich.text import Text

from nexus3.core.text_safety import strip_terminal_escapes
from nexus3.display.theme import Activity, Theme


class ToolState(Enum):
    """State of a tool in a batch."""
    PENDING = "pending"
    ACTIVE = "active"
    SUCCESS = "success"
    ERROR = "error"
    HALTED = "halted"  # Didn't run due to previous error in sequence
    CANCELLED = "cancelled"  # User cancelled the batch


@dataclass
class ToolStatus:
    """Status of a tool call in a batch."""
    name: str
    tool_id: str
    state: ToolState = ToolState.PENDING
    params: str = ""  # Formatted parameters (truncated)
    error: str = ""  # Error message if failed
    start_time: float = 0.0  # When tool started executing


class StreamingDisplay:
    """Display that accumulates streamed content within Rich.Live.

    This class implements __rich__ so it can be used directly with Rich.Live.
    All content (status, response, etc.) is rendered together on each refresh.

    To avoid Rich.Live overflow (the "three red dots" issue), the display
    limits visible content to the last MAX_DISPLAY_LINES lines.

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
    MAX_DISPLAY_LINES = 20  # Limit visible content to prevent overflow
    TOOL_TIMER_THRESHOLD = 3.0  # Show timer after 3 seconds

    def __init__(self, theme: Theme) -> None:
        self.theme = theme
        self.activity = Activity.IDLE
        self.response = ""
        self._frame = 0
        self._cancelled = False
        self._tools: dict[str, ToolStatus] = {}  # tool_id -> ToolStatus
        self._was_thinking = False  # Track if we were in thinking mode
        self._thinking_start_time: float = 0.0  # When thinking started
        self._thinking_duration: float = 0.0  # How long thinking lasted
        self._activity_start_time: float = 0.0  # When activity started
        self._had_errors = False  # Track if any errors occurred since last reset
        # Track text that came before tools started (for correct scrollback order)
        self._text_before_tools: str = ""
        self._tools_started: bool = False
        self._final_render: bool = False  # Skip spinner/status on final render

    def __rich__(self) -> RenderableType:
        """Render the streaming display state.

        Only used during Live context for streaming phase.
        Content is rendered in order: text_before_tools → tools → text_after_tools
        """
        parts: list[RenderableType] = []

        # Increment frame for spinner animation
        spinner = self.SPINNER_FRAMES[self._frame % len(self.SPINNER_FRAMES)]
        self._frame += 1

        # Text that came before tools (truncated)
        if self._text_before_tools:
            lines = self._text_before_tools.split("\n")
            if len(lines) > self.MAX_DISPLAY_LINES:
                truncated_lines = lines[-self.MAX_DISPLAY_LINES:]
                visible = "...\n" + "\n".join(truncated_lines)
            else:
                visible = self._text_before_tools
            parts.append(Text(visible))

        # Render batch tools with status gumballs
        if self._tools:
            parts.append(Text(""))  # Blank line before tools
            for tool in self._tools.values():
                parts.append(self._render_tool_line(tool))

        # Text that came after tools (truncated)
        if self.response:
            lines = self.response.split("\n")
            if len(lines) > self.MAX_DISPLAY_LINES:
                truncated_lines = lines[-self.MAX_DISPLAY_LINES:]
                visible_response = "...\n" + "\n".join(truncated_lines)
            else:
                visible_response = self.response
            parts.append(Text(""))  # Blank line after tools
            parts.append(Text(visible_response))

        # Activity status line with batch progress and timer (skip on final render)
        if not self._final_render:
            status = self._render_activity_status()
            parts.append(Text(f"\n{spinner} {status}", style="dim cyan"))

            # Status bar
            parts.append(Text("\n"))
            parts.append(self._render_status_bar(spinner))

        return Group(*parts) if parts else Text("")

    def _render_activity_status(self) -> str:
        """Render the activity status with optional timer."""
        # Calculate elapsed time
        elapsed = ""
        if self._activity_start_time > 0:
            elapsed_secs = time.time() - self._activity_start_time
            if elapsed_secs >= 1:
                elapsed = f" ({elapsed_secs:.0f}s)"

        if self.activity == Activity.WAITING:
            return f"Waiting for response...{elapsed}"
        elif self.activity == Activity.THINKING:
            return f"Thinking...{elapsed}"
        elif self.activity == Activity.TOOL_CALLING:
            return self._render_batch_status() + elapsed
        else:
            return f"Responding...{elapsed}"

    def _render_tool_line(self, tool: ToolStatus) -> Text:
        """Render a single tool line with gumball and path."""
        line = Text()

        # Gumball based on state
        if tool.state == ToolState.PENDING:
            line.append("  ○ ", style="dim")
        elif tool.state == ToolState.ACTIVE:
            line.append("  ● ", style="cyan")
        elif tool.state == ToolState.SUCCESS:
            line.append("  ● ", style="green")
        elif tool.state == ToolState.ERROR:
            line.append("  ● ", style="red")
        elif tool.state == ToolState.HALTED:
            line.append("  ● ", style="dark_orange")
        elif tool.state == ToolState.CANCELLED:
            line.append("  ● ", style="bright_yellow")

        # Tool name and params
        line.append(tool.name, style="bold" if tool.state == ToolState.ACTIVE else "")
        if tool.params:
            line.append(f": {tool.params}", style="dim")

        # Duration for active tools > 3s
        if tool.state == ToolState.ACTIVE and tool.start_time > 0:
            duration = time.time() - tool.start_time
            if duration >= self.TOOL_TIMER_THRESHOLD:
                line.append(f" ({duration:.0f}s)", style="dim yellow")

        # Status suffix for error/halted/cancelled
        if tool.state == ToolState.HALTED:
            line.append(" (halted)", style="dark_orange")
        elif tool.state == ToolState.CANCELLED:
            line.append(" (cancelled)", style="bright_yellow")

        # Error on next line (first 70 chars)
        if tool.state == ToolState.ERROR and tool.error:
            error_preview = tool.error[:70] + ("..." if len(tool.error) > 70 else "")
            line.append(f"\n      {error_preview}", style="red dim")

        return line

    def _render_batch_status(self) -> str:
        """Render batch progress: 'Running: tool_name | n complete, m pending'."""
        if not self._tools:
            return "Executing tools..."

        active = [t for t in self._tools.values() if t.state == ToolState.ACTIVE]
        done_states = (ToolState.SUCCESS, ToolState.ERROR)
        complete = sum(1 for t in self._tools.values() if t.state in done_states)
        pending = sum(1 for t in self._tools.values() if t.state == ToolState.PENDING)

        parts = []
        if active:
            parts.append(f"Running: {active[0].name}")
        else:
            parts.append("Executing tools")

        if len(self._tools) > 1:
            progress = []
            if complete:
                progress.append(f"{complete} complete")
            if pending:
                progress.append(f"{pending} pending")
            if progress:
                parts.append(" | " + ", ".join(progress))

        return "".join(parts)

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
        elif activity in (
            Activity.WAITING, Activity.RESPONDING, Activity.THINKING, Activity.TOOL_CALLING
        ):
            if self._activity_start_time == 0:
                self._activity_start_time = time.time()

    def start_activity_timer(self) -> None:
        """Start the activity timer (call when user sends message)."""
        self._activity_start_time = time.time()

    def get_activity_duration(self) -> float:
        """Get how long the current activity has been running."""
        if self._activity_start_time > 0:
            return time.time() - self._activity_start_time
        return 0.0

    def add_chunk(self, chunk: str) -> None:
        """Add a chunk to the response buffer (sanitized at source)."""
        sanitized = strip_terminal_escapes(chunk)
        self.response += sanitized
        if self.activity == Activity.THINKING:
            self.activity = Activity.RESPONDING

    def cancel(self) -> None:
        """Mark as cancelled."""
        self._cancelled = True
        self.activity = Activity.IDLE

    def cancel_all_tools(self) -> None:
        """Mark all tools as cancelled."""
        for tool in self._tools.values():
            if tool.state in (ToolState.PENDING, ToolState.ACTIVE):
                tool.state = ToolState.CANCELLED
        self._cancelled = True
        self.activity = Activity.IDLE

    def reset(self) -> None:
        """Reset for a new response."""
        self.response = ""
        self.activity = Activity.IDLE
        self._frame = 0
        self._cancelled = False
        self._tools.clear()
        self._was_thinking = False
        self._thinking_start_time = 0.0
        self._thinking_duration = 0.0
        self._activity_start_time = 0.0
        self._text_before_tools = ""
        self._tools_started = False
        self._final_render = False
        # Note: _had_errors persists across resets until cleared explicitly

    def clear_error_state(self) -> None:
        """Clear the error state (call when user sends new input)."""
        self._had_errors = False

    def mark_error(self) -> None:
        """Mark that an error occurred."""
        self._had_errors = True

    @property
    def had_errors(self) -> bool:
        """Check if any errors occurred since last clear."""
        return self._had_errors

    def start_thinking(self) -> None:
        """Mark that reasoning/thinking has started."""
        self._was_thinking = True
        self._thinking_start_time = time.time()
        self.activity = Activity.THINKING

    def end_thinking(self) -> tuple[bool, float]:
        """Mark that reasoning/thinking has ended.

        Accumulates thinking time across multiple thinking phases.

        Returns:
            Tuple of (was_thinking, phase_duration_seconds).
        """
        was_thinking = self._was_thinking
        duration = 0.0
        if was_thinking and self._thinking_start_time > 0:
            duration = time.time() - self._thinking_start_time
            self._thinking_duration += duration  # Accumulate
        self._was_thinking = False
        self._thinking_start_time = 0.0
        if self.activity == Activity.THINKING:
            self.activity = Activity.RESPONDING
        return was_thinking, duration

    def get_total_thinking_duration(self) -> float:
        """Get total accumulated thinking duration for this turn."""
        return self._thinking_duration

    def clear_thinking_duration(self) -> None:
        """Clear accumulated thinking duration (call after printing)."""
        self._thinking_duration = 0.0

    @property
    def thinking_duration(self) -> float:
        """Get the accumulated thinking duration."""
        return self._thinking_duration

    @property
    def is_cancelled(self) -> bool:
        """Check if cancelled."""
        return self._cancelled

    @property
    def text_before_tools(self) -> str:
        """Get text that came before the first tool batch."""
        return self._text_before_tools

    @property
    def text_after_tools(self) -> str:
        """Get text that came after tools started (alias for response when tools exist)."""
        return self.response if self._tools_started else ""

    def set_final_render(self, final: bool = True) -> None:
        """Set final render mode (skip spinner/status bar)."""
        self._final_render = final

    def add_tool_call(self, name: str, tool_id: str) -> None:
        """Track a new tool call (detected in stream).

        Legacy method - still used for stream detection.
        """
        if tool_id not in self._tools:
            self._tools[tool_id] = ToolStatus(name=name, tool_id=tool_id, state=ToolState.PENDING)
        self.activity = Activity.TOOL_CALLING

    def start_batch(self, tools: list[tuple[str, str, str]]) -> None:
        """Initialize batch with all tools as pending.

        Args:
            tools: List of (name, tool_id, params) tuples.
        """
        # Capture any text that came before this tool batch
        if not self._tools_started and self.response:
            self._text_before_tools = self.response
            self.response = ""  # Clear so new text goes to "after tools"
        self._tools_started = True

        self._tools.clear()
        for name, tool_id, params in tools:
            self._tools[tool_id] = ToolStatus(
                name=name,
                tool_id=tool_id,
                state=ToolState.PENDING,
                params=params,
            )
        self.activity = Activity.TOOL_CALLING

    def set_tool_active(self, tool_id: str) -> None:
        """Mark a tool as currently executing."""
        if tool_id in self._tools:
            self._tools[tool_id].state = ToolState.ACTIVE
            self._tools[tool_id].start_time = time.time()

    def set_tool_complete(self, tool_id: str, success: bool, error: str = "") -> None:
        """Mark a tool as complete with result."""
        if tool_id in self._tools:
            self._tools[tool_id].state = ToolState.SUCCESS if success else ToolState.ERROR
            if error:
                self._tools[tool_id].error = error
            if not success:
                self._had_errors = True

        # Check if all tools done (including halted/cancelled)
        done_states = (ToolState.SUCCESS, ToolState.ERROR, ToolState.HALTED, ToolState.CANCELLED)
        if all(t.state in done_states for t in self._tools.values()):
            self.activity = Activity.WAITING

    def halt_remaining_tools(self) -> None:
        """Mark all pending tools as halted (due to error in sequence)."""
        for tool in self._tools.values():
            if tool.state == ToolState.PENDING:
                tool.state = ToolState.HALTED
        self.activity = Activity.WAITING

    def complete_tool_call(self, tool_id: str) -> None:
        """Mark a tool call as complete (legacy method)."""
        self.set_tool_complete(tool_id, success=True)

    def get_batch_results(self) -> list[ToolStatus]:
        """Get all tools in current batch for printing to scrollback."""
        return list(self._tools.values())

    def clear_tools(self) -> None:
        """Clear tool tracking for next iteration."""
        self._tools.clear()
