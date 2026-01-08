# NEXUS3 Display Module

Terminal display system for NEXUS3, providing Rich-based output with gumball status indicators, animated streaming display, and batch tool progress tracking.

## Purpose

This module handles all terminal output for NEXUS3:
- Streaming response display with real-time content accumulation
- Batch tool execution progress with per-tool status tracking
- Inline printing with colored gumball status indicators
- Animated summary bar using Rich.Live
- Activity state tracking with timers
- Cancellation support

The architecture separates **scrolling content** (inline printing) from **fixed UI** (summary bar and streaming display), allowing them to coexist without conflicts.

## File Overview

| File | Description |
|------|-------------|
| `theme.py` | Status/Activity enums, Theme dataclass with all visual styling |
| `console.py` | Shared Rich Console singleton for consistent output |
| `streaming.py` | StreamingDisplay - Rich.Live renderable for streaming responses with tool batch tracking |
| `printer.py` | InlinePrinter - scrolling output with gumball prefixes |
| `segments.py` | Pluggable summary bar segments (Activity, TaskCount, CancelHint) |
| `summary.py` | SummaryBar - Rich.Live wrapper for segment composition |
| `manager.py` | DisplayManager - central coordinator for all display components |

## Key Types and Classes

### Core Enums (`theme.py`)

```python
class Status(Enum):
    ACTIVE = "active"       # In-progress operation
    PENDING = "pending"     # Queued/waiting
    COMPLETE = "complete"   # Successful completion
    ERROR = "error"         # Failed operation
    CANCELLED = "cancelled" # User cancelled

class Activity(Enum):
    IDLE = "idle"               # No active operation
    WAITING = "waiting"         # Waiting for first API byte
    THINKING = "thinking"       # Model reasoning (via tags)
    RESPONDING = "responding"   # Streaming response content
    TOOL_CALLING = "tool_calling"  # Executing tool calls
```

### Theme (`theme.py`)

```python
@dataclass
class Theme:
    gumballs: dict[Status, str]     # Rich markup strings like "[cyan]@[/]"
    spinner_frames: str             # Braille animation: "..."
    thinking: str                   # Style for thinking traces
    thinking_collapsed: str         # Style for collapsed thinking
    response: str                   # Style for response text
    error: str                      # Style for errors
    user_input: str                 # Style for user input
    summary_style: str              # Style for summary bar
    summary_separator: str          # Segment separator " | "

    def gumball(self, status: Status) -> str:
        """Get gumball character for a status."""
```

### Console (`console.py`)

Shared Rich Console singleton ensuring all components use the same instance.

```python
def get_console() -> Console:
    """Get the shared Console instance (creates on first access)."""

def set_console(console: Console) -> None:
    """Set a custom Console (useful for testing)."""
```

The console is configured with:
- `highlight=False` - No auto-highlighting, styling is explicit
- `markup=True` - Rich markup enabled for `[cyan]text[/]` syntax
- `force_terminal=True` - Force terminal mode even if detection fails

### StreamingDisplay (`streaming.py`)

A Rich.Live renderable that accumulates streamed content, tracks tool batch execution, and renders the complete display state with timers.

```python
class ToolState(Enum):
    """State of a tool in a batch."""
    PENDING = "pending"
    ACTIVE = "active"
    SUCCESS = "success"
    ERROR = "error"
    HALTED = "halted"      # Didn't run due to previous error in sequence
    CANCELLED = "cancelled" # User cancelled the batch

@dataclass
class ToolStatus:
    """Status of a tool call in a batch."""
    name: str
    tool_id: str
    state: ToolState = ToolState.PENDING
    path: str = ""         # Primary argument (e.g., file path)
    error: str = ""        # Error message if failed
    start_time: float = 0.0  # When tool started executing

class StreamingDisplay:
    """Implements __rich__ for use with Rich.Live."""

    SPINNER_FRAMES = "..."     # Braille spinner animation
    MAX_DISPLAY_LINES = 20     # Limit visible content to prevent overflow
    TOOL_TIMER_THRESHOLD = 3.0 # Show timer after 3 seconds

    def __init__(self, theme: Theme) -> None
    def __rich__(self) -> RenderableType      # Called by Rich.Live on refresh

    # Activity management
    def set_activity(self, activity: Activity) -> None
    def start_activity_timer(self) -> None
    def get_activity_duration(self) -> float

    # Content accumulation
    def add_chunk(self, chunk: str) -> None   # Append to response buffer
    def reset(self) -> None                   # Clear for new response

    # Cancellation
    def cancel(self) -> None                  # Mark as cancelled
    def cancel_all_tools(self) -> None        # Cancel pending/active tools
    @property
    def is_cancelled(self) -> bool

    # Thinking/reasoning tracking
    def start_thinking(self) -> None
    def end_thinking(self) -> tuple[bool, float]  # Returns (was_thinking, duration)
    def get_total_thinking_duration(self) -> float
    def clear_thinking_duration(self) -> None
    @property
    def thinking_duration(self) -> float

    # Error tracking
    def mark_error(self) -> None
    def clear_error_state(self) -> None
    @property
    def had_errors(self) -> bool

    # Tool batch management
    def add_tool_call(self, name: str, tool_id: str) -> None  # Legacy method
    def start_batch(self, tools: list[tuple[str, str, str]]) -> None
    def set_tool_active(self, tool_id: str) -> None
    def set_tool_complete(self, tool_id: str, success: bool, error: str = "") -> None
    def halt_remaining_tools(self) -> None
    def complete_tool_call(self, tool_id: str) -> None  # Legacy method
    def get_batch_results(self) -> list[ToolStatus]
    def clear_tools(self) -> None
```

The `__rich__` method renders:
1. Accumulated response text (truncated to last 20 lines to prevent overflow)
2. Tool batch status with per-tool gumballs
3. Activity status line with animated spinner and elapsed timer
4. Status bar with gumball, state, and "ESC cancel" hint

### InlinePrinter (`printer.py`)

Handles scrolling output with gumball status indicators.

```python
class InlinePrinter:
    def __init__(self, console: Console, theme: Theme) -> None
    def print(self, content: str, style: str | None = None, end: str = "\n") -> None
    def print_gumball(self, status: Status, message: str, indent: int = 0) -> None
    def print_thinking(self, content: str, collapsed: bool = True) -> None
    def print_task_start(self, task_type: str, label: str, indent: int = 2) -> None
    def print_task_end(self, task_type: str, success: bool, indent: int = 2) -> None
    def print_error(self, message: str) -> None
    def print_cancelled(self, message: str = "Cancelled") -> None
    def print_streaming_chunk(self, chunk: str) -> None  # Uses raw sys.stdout
    def finish_streaming(self) -> None
```

### Summary Bar Segments (`segments.py`)

Pluggable segments that implement the `SummarySegment` protocol:

```python
class SummarySegment(Protocol):
    @property
    def visible(self) -> bool: ...
    def render(self) -> Text: ...
```

Built-in segments:

| Segment | Description |
|---------|-------------|
| `ActivitySegment` | Animated spinner + activity name (e.g., "spinner responding") |
| `TaskCountSegment` | Task counts with gumballs (e.g., "active 2 done 3 failed 1") |
| `CancelHintSegment` | Shows "ESC cancel" when `show=True` |

### SummaryBar (`summary.py`)

Rich.Live wrapper that composes registered segments.

```python
class SummaryBar:
    def __init__(self, console: Console, theme: Theme) -> None
    def __rich__(self) -> RenderableType          # Makes it a Rich renderable
    def register_segment(self, segment: SummarySegment, position: int = -1) -> None
    def unregister_segment(self, segment: SummarySegment) -> None
    def live(self) -> Generator[None, None, None] # Context manager
    def start(self) -> None                        # Begin Rich.Live
    def stop(self) -> None                         # End Rich.Live
    def refresh(self) -> None                      # Manual refresh
    @property
    def is_live(self) -> bool
```

### DisplayManager (`manager.py`)

Central coordinator that owns all display components.

```python
class DisplayManager:
    def __init__(self, console: Console | None = None, theme: Theme | None = None)

    # Properties
    @property
    def cancel_token(self) -> CancellationToken | None
    @property
    def is_cancelled(self) -> bool

    # Session management
    async def live_session(self) -> AsyncGenerator[None, None]  # Async context manager
    def stop_live(self) -> None
    def cancel(self) -> None

    # Activity
    def set_activity(self, activity: Activity) -> None

    # Task tracking
    def add_task(self) -> None
    def start_task(self) -> None
    def complete_task(self, success: bool = True) -> None
    def reset_tasks(self) -> None

    # Printing (delegates to InlinePrinter)
    def print(self, content: str, style: str | None = None) -> None
    def print_gumball(self, status: Status, message: str, indent: int = 0) -> None
    def print_thinking(self, content: str, collapsed: bool = True) -> None
    def print_task_start(self, task_type: str, label: str) -> None
    def print_task_end(self, task_type: str, success: bool) -> None
    def print_error(self, message: str) -> None
    def print_cancelled(self, message: str = "Cancelled") -> None
    def print_streaming(self, chunk: str) -> None
    def finish_streaming(self) -> None
```

## Activity States

Activity transitions during a typical request:

```
IDLE -> WAITING -> RESPONDING -> IDLE
              |
              v (if thinking tags detected)
          THINKING -> RESPONDING -> IDLE
              |
              v (if tool calls detected)
         TOOL_CALLING -> WAITING -> RESPONDING -> IDLE
```

| State | Description | Visual |
|-------|-------------|--------|
| `IDLE` | No active operation | No spinner, bar hidden |
| `WAITING` | Waiting for first API byte | Spinner + "Waiting for response... (Ns)" |
| `THINKING` | Model reasoning (via tags) | Spinner + "Thinking... (Ns)" |
| `RESPONDING` | Streaming response content | Spinner + "Responding... (Ns)" |
| `TOOL_CALLING` | Executing tool calls | Spinner + "Running: tool_name \| n complete, m pending (Ns)" |

## Tool Batch Display

When tools are being executed, StreamingDisplay shows batch progress:

```
  ○ read_file: src/main.py           # Pending
  ● write_file: output.txt (5s)      # Active with timer (shown after 3s)
  ● grep: found                      # Success
  ● run_command: failed              # Error
      Permission denied...           # Error preview (first 70 chars)
  ● list_dir: (halted)               # Halted due to previous error
  ● sleep: (cancelled)               # User cancelled

spinner Running: write_file | 1 complete, 2 pending (12s)
spinner ● active | ESC cancel
```

Tool states use different colors:
- Pending: dim `○`
- Active: cyan `●`
- Success: green `●`
- Error: red `●`
- Halted: dark orange `●`
- Cancelled: bright yellow `●`

## Theme System

All visual styling is centralized in `Theme`. The `load_theme()` function returns the default theme (overrides are scaffolded but not yet implemented).

```python
from nexus3.display import Theme, Status, load_theme

theme = load_theme()

# Access gumball for a status
gumball = theme.gumball(Status.ACTIVE)  # Returns "[cyan]@[/]"
```

### Gumball Colors (Default Theme)

| Status | Character | Color | Meaning |
|--------|-----------|-------|---------|
| `ACTIVE` | `●` | cyan | In progress |
| `COMPLETE` | `●` | green | Success |
| `ERROR` | `●` | red | Failure |
| `CANCELLED` | `●` | yellow | User cancelled |
| `PENDING` | `○` | dim | Queued |

### Spinner Animation

The default spinner uses braille characters: `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`

## Dependencies

### Internal (nexus3)

- `nexus3.core.cancel.CancellationToken` - Used by DisplayManager for cancellation support

### External

- `rich.console.Console` - Terminal output
- `rich.live.Live` - Animated display updates
- `rich.text.Text` - Styled text rendering
- `rich.console.Group` - Composing multiple renderables

## Usage Examples

### Basic DisplayManager Usage

```python
from nexus3.display import DisplayManager, Activity, Status

display = DisplayManager()

# Start a live session with cancellation support
async with display.live_session():
    display.set_activity(Activity.WAITING)

    # Stop live before streaming to avoid Rich.Live conflicts
    display.stop_live()

    async for chunk in stream:
        if display.is_cancelled:
            break
        display.print_streaming(chunk)

    display.finish_streaming()
    display.set_activity(Activity.IDLE)
```

### StreamingDisplay with Rich.Live and Tool Batch

```python
from rich.live import Live
from nexus3.display import StreamingDisplay, Activity, load_theme

display = StreamingDisplay(load_theme())

with Live(display, refresh_per_second=10) as live:
    display.start_activity_timer()
    display.set_activity(Activity.WAITING)

    # Stream response
    async for chunk in provider.stream(messages):
        display.add_chunk(chunk)
        live.refresh()

    # Handle tool batch
    if tool_calls:
        tools = [(tc.name, tc.id, get_path(tc)) for tc in tool_calls]
        display.start_batch(tools)

        for tc in tool_calls:
            display.set_tool_active(tc.id)
            live.refresh()

            try:
                result = await execute_tool(tc)
                display.set_tool_complete(tc.id, success=True)
            except Exception as e:
                display.set_tool_complete(tc.id, success=False, error=str(e))
                display.halt_remaining_tools()
                break

            live.refresh()

    display.set_activity(Activity.IDLE)
```

### Gumball Printing

```python
from nexus3.display import DisplayManager, Status

display = DisplayManager()

# Print with status gumballs
display.print_gumball(Status.ACTIVE, "Processing files...")
display.print_gumball(Status.COMPLETE, "Done!")
display.print_gumball(Status.ERROR, "Failed to read file")

# Task progress
display.print_task_start("read_file", "src/main.py")
display.print_task_end("read_file", success=True)
```

### Custom Summary Segments

```python
from rich.text import Text
from nexus3.display import SummaryBar, get_console, load_theme

class TokenSegment:
    """Custom segment showing token usage."""

    def __init__(self):
        self.used = 0
        self.limit = 8000

    @property
    def visible(self) -> bool:
        return self.used > 0

    def render(self) -> Text:
        return Text(f"{self.used:,} / {self.limit:,} tokens", style="dim")

# Register with summary bar
bar = SummaryBar(get_console(), load_theme())
bar.register_segment(TokenSegment())
```

### Cancellation

```python
from nexus3.display import DisplayManager

display = DisplayManager()

async with display.live_session():
    # Somewhere else (e.g., key handler):
    display.cancel()  # Sets cancellation flag

    # In streaming loop:
    if display.is_cancelled:
        display.print_cancelled("Operation cancelled")
        break
```

### Thinking Tracking

```python
from nexus3.display import StreamingDisplay, load_theme

display = StreamingDisplay(load_theme())

# When thinking starts
display.start_thinking()

# When thinking ends
was_thinking, duration = display.end_thinking()
if was_thinking:
    print(f"Thought for {duration:.1f}s")

# Get total thinking time for the turn
total = display.get_total_thinking_duration()
```

## Architecture Notes

1. **Two-System Handoff**: prompt_toolkit handles input; Rich.Live handles animated output. They cannot run simultaneously, so `stop_live()` must be called before streaming.

2. **Shared Console**: All components use `get_console()` to ensure consistent output and proper Rich.Live coordination.

3. **Pluggable Segments**: Summary bar segments implement `SummarySegment` protocol. Add new segments by implementing `visible` property and `render()` method.

4. **Streaming Output**: `InlinePrinter.print_streaming_chunk()` uses raw `sys.stdout` to avoid conflicts with Rich.Live during streaming.

5. **Cancellation Flow**: `DisplayManager.cancel()` sets the cancellation token, updates activity to IDLE, hides the cancel hint, and refreshes the summary bar. `StreamingDisplay.cancel_all_tools()` can cancel pending/active tools in a batch.

6. **Content Overflow Prevention**: StreamingDisplay limits visible content to the last 20 lines to prevent Rich.Live overflow (the "three red dots" issue).

7. **Timer Display**: Activity timers show elapsed time after 1 second. Tool timers show after 3 seconds for active tools.

## Data Flow

```
User Input (prompt_toolkit)
         |
         v
DisplayManager.live_session()
         |
    +----+----+
    |         |
    v         v
SummaryBar  InlinePrinter
(Rich.Live)  (sys.stdout)
    |              |
    v              v
Terminal Output (animated bar + scrolling content)

StreamingDisplay (alternative for full Rich.Live streaming)
    |
    v
Rich.Live context
    |
    v
Terminal Output (accumulated response + tool batch + status bar)
```

## Exports (`__init__.py`)

All public symbols are exported from the module:

```python
from nexus3.display import (
    # Console
    get_console, set_console,
    # Manager
    DisplayManager,
    # Printer
    InlinePrinter,
    # Streaming
    StreamingDisplay,
    # Segments
    SummarySegment, ActivitySegment, TaskCountSegment, CancelHintSegment,
    # Summary bar
    SummaryBar,
    # Theme
    Activity, Status, Theme, load_theme,
)
```

Note: `ToolState` and `ToolStatus` from `streaming.py` are not exported by default but can be imported directly:

```python
from nexus3.display.streaming import ToolState, ToolStatus
```
