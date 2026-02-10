# nexus3/display

Terminal display system for NEXUS3 providing animated spinners, inline printing with gumball indicators, streaming output, and consistent theming.

## Purpose

This module provides a unified terminal UI with several key responsibilities:

- **Spinner** - Animated spinner pinned to bottom, with content printed above (primary interface)
- **Streaming display** - Rich.Live compatible display with tool batch tracking
- **Inline printing** - Gumball status indicators and sanitized streaming output
- **Theming** - Customizable colors, styles, and gumball characters

---

## Public API (`__init__.py`)

```python
from nexus3.display import (
    # Console management
    get_console,          # Get shared Console instance
    set_console,          # Set custom Console (for testing)

    # Primary interface
    Spinner,              # Animated spinner with Live rendering

    # Theme system
    Theme,                # Theme configuration dataclass
    Status,               # Status enum (ACTIVE, PENDING, COMPLETE, ERROR, CANCELLED)
    Activity,             # Activity enum (IDLE, WAITING, THINKING, RESPONDING, TOOL_CALLING)
    load_theme,           # Load theme with optional overrides

    # Printing
    InlinePrinter,        # Scrolling output with gumballs

    # Legacy (deprecated - use Spinner instead)
    DisplayManager,       # Coordinator for printer, summary bar, cancellation
    StreamingDisplay,     # Rich.Live compatible display with tool tracking
    SummaryBar,           # Bottom-anchored status bar
    SummarySegment,       # Segment protocol
    ActivitySegment,      # Spinner segment
    TaskCountSegment,     # Task counts
    CancelHintSegment,    # Cancel hint
)
```

---

## Module Reference

### spinner.py - Primary Display Interface

The primary display interface. Provides an animated spinner pinned to the bottom of the terminal using Rich.Live. All output during an agent turn goes through `spinner.print()`, which prints above the spinner.

| Class | Description |
|-------|-------------|
| `Spinner` | Animated spinner with text, pinned to bottom of terminal |

**Constructor:**

```python
Spinner(
    console: Console | None = None,  # Rich Console (defaults to shared)
    theme: Theme | None = None,      # Theme for styling (defaults to load_theme())
)
```

**Methods:**

| Method | Description |
|--------|-------------|
| `show(text, activity)` | Start showing spinner with text and activity state |
| `hide()` | Stop spinner, flush stream buffer |
| `update(text, activity)` | Update spinner text and/or activity |
| `print(*args, **kwargs)` | Print above spinner (delegates to console.print) |
| `print_streaming(chunk)` | Buffer streaming text, print complete lines |
| `flush_stream()` | Flush remaining buffer content |

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `is_active` | `bool` | Whether spinner is currently showing |
| `elapsed` | `float` | Seconds since spinner started |
| `live` | `Live \| None` | Underlying Rich.Live instance (for integration) |
| `text` | `str` | Current spinner text |
| `activity` | `Activity` | Current activity state |
| `show_cancel_hint` | `bool` | Whether to show "ESC cancel" hint (default True) |

**Usage:**

```python
from nexus3.display import Spinner, Activity

spinner = Spinner()

# Start spinner
spinner.show("Waiting for response...")

# Print content above spinner
spinner.print("Tool call: read_file")
spinner.print("Result: 42 lines")

# Stream text (buffered until newline)
spinner.print_streaming("Hello ")
spinner.print_streaming("world\n")  # Prints when newline received
spinner.flush_stream()  # Force flush any remaining buffer

# Update spinner text and activity
spinner.update("Processing...", activity=Activity.TOOL_CALLING)

# Hide spinner when done
spinner.hide()
```

**Key Behaviors:**

- Uses Rich.Live with `transient=True` to avoid leaving spinner in scrollback
- Redirects stdout/stderr through Live to prevent artifacts
- Single-line render with `no_wrap=True` and `overflow="crop"` to prevent wrapping issues
- Shows elapsed time after 1 second
- Shows "ESC cancel" hint by default (configurable via `show_cancel_hint`)
- Streaming output is sanitized via `strip_terminal_escapes()`
- Activity-specific text in `__rich__` render: "Waiting..." / "Thinking..." / "Responding..." / custom text or "Running tools..." for TOOL_CALLING

---

### console.py - Shared Console

A singleton Rich Console instance ensures consistent output and proper coordination with Rich.Live.

| Function | Description |
|----------|-------------|
| `get_console()` | Get the shared Console instance (creates on first access) |
| `set_console(console)` | Set a custom Console instance (for testing) |

**Console Configuration (Unix):**

- `highlight=False` - No auto-highlighting, styling is controlled explicitly
- `markup=True` - Enable Rich markup like `[cyan]text[/]`
- `force_terminal=True` - Force terminal mode even if detection fails
- `legacy_windows=False` - Enable VT100 mode on Windows 10+

**Console Configuration (Windows):**

The console detects Windows shell capabilities via `supports_ansi()` from `nexus3.core.shell_detection`:

- If ANSI is supported: `force_terminal=True`, `legacy_windows=False`, `no_color=False`
- If ANSI not supported: `force_terminal=False`, `legacy_windows=True`, `no_color=True`

**Usage:**

```python
from nexus3.display import get_console, set_console

# Get the shared console (created on first access)
console = get_console()

# For testing: set a custom console
from rich.console import Console
set_console(Console(force_terminal=False))
```

---

### theme.py - Theme System

The theme system defines visual styling for all display components.

| Export | Description |
|--------|-------------|
| `Status` | Enum for task states (ACTIVE, PENDING, COMPLETE, ERROR, CANCELLED) |
| `Activity` | Enum for agent activities (IDLE, WAITING, THINKING, RESPONDING, TOOL_CALLING) |
| `Theme` | Dataclass with all styling configuration |
| `DEFAULT_THEME` | Pre-created default theme instance |
| `load_theme(overrides)` | Load theme with optional overrides |

**Status Enum:**

| Value | Description | Default Color |
|-------|-------------|---------------|
| `ACTIVE` | Currently executing | cyan |
| `PENDING` | Waiting to start | dim |
| `COMPLETE` | Finished successfully | green |
| `ERROR` | Failed | red |
| `CANCELLED` | User cancelled | yellow |

**Activity Enum:**

| Value | Description |
|-------|-------------|
| `IDLE` | Not doing anything |
| `WAITING` | Waiting for first byte from API |
| `THINKING` | Model is reasoning (detected via tags) |
| `RESPONDING` | Model is generating response |
| `TOOL_CALLING` | Executing tool calls |

**Theme Configuration:**

```python
@dataclass
class Theme:
    # Gumball characters with Rich markup colors
    gumballs: dict[Status, str] = {
        Status.ACTIVE: "[cyan]●[/]",
        Status.PENDING: "[dim]○[/]",
        Status.COMPLETE: "[green]●[/]",
        Status.ERROR: "[red]●[/]",
        Status.CANCELLED: "[yellow]●[/]",
    }

    # Spinner animation frames (Braille pattern)
    spinner_frames: str = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    # Text styles (Rich style strings)
    thinking: str = "dim italic"
    thinking_collapsed: str = "dim"
    response: str = ""
    error: str = "bold red"
    user_input: str = "bold"

    # Summary bar
    summary_style: str = ""
    summary_separator: str = " | "

    def gumball(self, status: Status) -> str:
        """Get gumball character for a status."""
```

**Usage:**

```python
from nexus3.display import load_theme, Status

theme = load_theme()
print(theme.gumball(Status.ACTIVE))  # "[cyan]●[/]"
```

---

### printer.py - Inline Printing

Handles scrolling content output with gumball status indicators.

| Class | Description |
|-------|-------------|
| `InlinePrinter` | Scrolling output with gumball indicators |

**Constructor:**

```python
InlinePrinter(console: Console, theme: Theme)
```

**Methods:**

| Method | Description |
|--------|-------------|
| `print(content, style, end)` | Print content with optional Rich style |
| `print_gumball(status, message, indent)` | Print gumball indicator with message |
| `print_thinking(content, collapsed)` | Print thinking trace inline |
| `print_task_start(task_type, label, indent)` | Print task starting indicator |
| `print_task_end(task_type, success, indent)` | Print task completion indicator |
| `print_error(message)` | Print error message with red gumball |
| `print_cancelled(message)` | Print cancellation message with yellow gumball |
| `print_streaming_chunk(chunk)` | Print sanitized chunk without newline (raw stdout) |
| `finish_streaming()` | Print newline after streaming |

**Usage:**

```python
from nexus3.display import InlinePrinter, get_console, load_theme, Status

printer = InlinePrinter(get_console(), load_theme())

# Basic printing
printer.print("Hello world")
printer.print("Error!", style="red")

# Gumball indicators
printer.print_gumball(Status.ACTIVE, "Processing file.py")
printer.print_gumball(Status.COMPLETE, "Done", indent=2)
# Output: "  ● Done" (green)

# Task tracking
printer.print_task_start("read_file", "src/main.py")
# Output: "  ● read_file: src/main.py" (cyan)

printer.print_task_end("read_file", success=True)
# Output: "  ● read_file: complete" (green)

# Streaming output (raw stdout, bypasses Rich)
printer.print_streaming_chunk("Hello ")
printer.print_streaming_chunk("World")
printer.finish_streaming()  # Print newline
```

**Streaming Safety:**

`print_streaming_chunk()` uses raw `sys.stdout.write()` to avoid conflicts with Rich.Live. Content is sanitized via `strip_terminal_escapes()` to prevent terminal injection attacks.

---

### streaming.py - Streaming Display (Advanced)

Rich.Live compatible display that accumulates streamed content and tracks tool batch execution.

| Export | Description |
|--------|-------------|
| `StreamingDisplay` | Display that accumulates content for Live rendering |
| `ToolState` | Enum for tool states (PENDING, ACTIVE, SUCCESS, ERROR, HALTED, CANCELLED) |
| `ToolStatus` | Dataclass for tool call status tracking |

**ToolState Enum:**

| Value | Description |
|-------|-------------|
| `PENDING` | Tool waiting to execute |
| `ACTIVE` | Tool currently executing |
| `SUCCESS` | Tool completed successfully |
| `ERROR` | Tool failed with error |
| `HALTED` | Tool didn't run due to previous error in sequence |
| `CANCELLED` | Tool cancelled by user |

**StreamingDisplay Class:**

```python
class StreamingDisplay:
    SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    MAX_DISPLAY_LINES = 20  # Limit visible content to prevent overflow
    TOOL_TIMER_THRESHOLD = 3.0  # Show timer after 3 seconds

    def __init__(self, theme: Theme) -> None: ...
```

**Key Methods:**

| Method | Description |
|--------|-------------|
| `set_activity(activity)` | Update current activity state |
| `start_activity_timer()` | Start timing current activity |
| `get_activity_duration()` | Get elapsed time for current activity |
| `add_chunk(chunk)` | Add text chunk to response buffer (sanitized); transitions THINKING to RESPONDING |
| `cancel()` | Mark display as cancelled |
| `cancel_all_tools()` | Mark all pending/active tools as cancelled |
| `reset()` | Reset for new response (note: `_had_errors` persists across resets) |
| `set_final_render(final)` | Set final render mode (skips spinner/status bar in `__rich__`) |

**Error State Methods:**

| Method | Description |
|--------|-------------|
| `mark_error()` | Mark that an error occurred |
| `clear_error_state()` | Clear the error state (call when user sends new input) |

**Thinking State Methods:**

| Method | Description |
|--------|-------------|
| `start_thinking()` | Mark thinking/reasoning started |
| `end_thinking()` | Mark thinking ended, returns (was_thinking, duration); accumulates across phases |
| `get_total_thinking_duration()` | Get accumulated thinking time |
| `clear_thinking_duration()` | Clear accumulated thinking time |

**Tool Batch Methods:**

| Method | Description |
|--------|-------------|
| `start_batch(tools)` | Initialize batch with list of (name, tool_id, params); captures text_before_tools |
| `set_tool_active(tool_id)` | Mark tool as currently executing |
| `set_tool_complete(tool_id, success, error)` | Mark tool as complete |
| `halt_remaining_tools()` | Mark pending tools as halted (due to earlier error) |
| `get_batch_results()` | Get all tools for printing to scrollback |
| `clear_tools()` | Clear tool tracking for next iteration |
| `add_tool_call(name, tool_id)` | Track a tool call detected in stream (legacy) |
| `complete_tool_call(tool_id)` | Mark tool call as complete (legacy, delegates to `set_tool_complete`) |

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `is_cancelled` | `bool` | Check if cancelled |
| `had_errors` | `bool` | Check if any errors occurred since last `clear_error_state()` |
| `text_before_tools` | `str` | Text that came before first tool batch |
| `text_after_tools` | `str` | Text that came after tools started (empty if no tools) |
| `thinking_duration` | `float` | Accumulated thinking duration |

**Usage:**

```python
from nexus3.display import StreamingDisplay, Activity
from nexus3.display.streaming import ToolState
from rich.live import Live

display = StreamingDisplay(load_theme())

with Live(display, refresh_per_second=10) as live:
    display.set_activity(Activity.WAITING)
    display.start_activity_timer()

    # Stream text
    async for chunk in stream:
        display.add_chunk(chunk)
        live.refresh()

    # Track tool batch
    display.start_batch([
        ("read_file", "tc1", "path=/src/main.py"),
        ("grep", "tc2", "pattern=TODO"),
    ])

    display.set_tool_active("tc1")
    # ... execute tool ...
    display.set_tool_complete("tc1", success=True)

    display.set_activity(Activity.IDLE)

    # Error state persists across resets
    display.mark_error()
    print(display.had_errors)  # True
    display.reset()
    print(display.had_errors)  # Still True
    display.clear_error_state()
    print(display.had_errors)  # False

    # Final render (skip spinner/status bar for scrollback print)
    display.set_final_render(True)
```

---

### summary.py - Summary Bar (Legacy)

Bottom-anchored status bar using Rich.Live with pluggable segments.

| Class | Description |
|-------|-------------|
| `SummaryBar` | Status bar with registered segments |

**Constructor:**

```python
SummaryBar(console: Console, theme: Theme)
```

**Methods:**

| Method | Description |
|--------|-------------|
| `register_segment(segment, position)` | Add segment to bar |
| `unregister_segment(segment)` | Remove segment from bar |
| `live()` | Context manager for Rich.Live updates |
| `start()` | Start live display (begin spinner animation) |
| `stop()` | Stop live display |
| `refresh()` | Manually refresh the bar |

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `is_live` | `bool` | Whether bar is currently live |

**Usage:**

```python
from nexus3.display import SummaryBar, get_console, load_theme
from nexus3.display.segments import ActivitySegment, TaskCountSegment

bar = SummaryBar(get_console(), load_theme())
bar.register_segment(ActivitySegment(load_theme()))
bar.register_segment(TaskCountSegment(load_theme()))

with bar.live():
    # Bar refreshes automatically at 8Hz
    pass
```

---

### segments.py - Summary Bar Segments (Legacy)

Pluggable segments for the summary bar.

| Export | Description |
|--------|-------------|
| `SummarySegment` | Protocol for custom segments |
| `ActivitySegment` | Shows activity with animated spinner |
| `TaskCountSegment` | Shows task status counts |
| `CancelHintSegment` | Shows "ESC cancel" hint |

**SummarySegment Protocol:**

```python
class SummarySegment(Protocol):
    @property
    def visible(self) -> bool:
        """Whether this segment should be displayed."""
        ...

    def render(self) -> Text:
        """Render the segment content."""
        ...
```

**ActivitySegment:**

Shows current activity with animated spinner (e.g., "spinner responding").

| Method | Description |
|--------|-------------|
| `set_activity(activity)` | Update current activity |

**TaskCountSegment:**

Shows task counts with gumballs (e.g., "● 1 active ○ 2 pending ● 3 done").

| Method | Description |
|--------|-------------|
| `add_task()` | Register new pending task |
| `start_task()` | Move task from pending to active |
| `complete_task(success)` | Complete active task |
| `reset()` | Reset all counts |

**CancelHintSegment:**

Shows "ESC cancel" hint when `show` is True.

---

### manager.py - Display Manager (Legacy)

Central coordinator that owns InlinePrinter, SummaryBar, and manages cancellation.

| Class | Description |
|-------|-------------|
| `DisplayManager` | Coordinator for all display components |

**Constructor:**

```python
DisplayManager(
    console: Console | None = None,
    theme: Theme | None = None,
)
```

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `cancel_token` | `CancellationToken \| None` | Current cancellation token |
| `is_cancelled` | `bool` | Whether current operation is cancelled |

**Key Methods:**

| Method | Description |
|--------|-------------|
| `live_session()` | Async context manager for live display session |
| `stop_live()` | Stop live display (call before streaming) |
| `cancel()` | Cancel current operation (ESC pressed) |
| `set_activity(activity)` | Set current activity state |

**Task Tracking:**

| Method | Description |
|--------|-------------|
| `add_task()` | Register new pending task |
| `start_task()` | Move task from pending to active |
| `complete_task(success)` | Complete active task |
| `reset_tasks()` | Reset task counts |

**Printing (delegates to InlinePrinter):**

| Method | Description |
|--------|-------------|
| `print(content, style)` | Print content |
| `print_gumball(status, message, indent)` | Print gumball indicator |
| `print_thinking(content, collapsed)` | Print thinking trace |
| `print_task_start(task_type, label)` | Print task starting |
| `print_task_end(task_type, success)` | Print task completion |
| `print_error(message)` | Print error |
| `print_cancelled(message)` | Print cancellation |
| `print_streaming(chunk)` | Print streaming chunk |
| `finish_streaming()` | Finish streaming output |

---

## Dependencies

### Internal

- `nexus3.core.cancel` - `CancellationToken` for coordinated cancellation
- `nexus3.core.text_safety` - `strip_terminal_escapes()`, `escape_rich_markup()` for sanitizing output
- `nexus3.core.shell_detection` - `supports_ansi()` for Windows console detection

### External

- `rich` - Console, Live, Text, Group for terminal rendering

---

## Architecture

```
Primary Interface:
    Spinner (spinner.py)
        |
        +-- Console (console.py - shared singleton)
        +-- Theme (theme.py - styling configuration)
        +-- Prints content above spinner via Live.console.print()
        +-- Streaming buffer with line-based flushing

Advanced Interface:
    StreamingDisplay (streaming.py)
        |
        +-- Theme (styling)
        +-- Tool batch tracking (ToolStatus)
        +-- Thinking state tracking
        +-- Implements __rich__ for Live rendering

Legacy Components:
    DisplayManager (manager.py)
        |
        +-- InlinePrinter (printer.py)
        +-- SummaryBar (summary.py)
        |       |
        |       +-- Segments (segments.py)
        |           +-- ActivitySegment
        |           +-- TaskCountSegment
        |           +-- CancelHintSegment
        |
        +-- CancellationToken
```

---

## Design Notes

### Rich.Live Coordination

The Spinner uses Rich.Live internally. Key behaviors:

1. **Single-line rendering** - Spinner is constrained to one line (`no_wrap=True`, `overflow="crop"`) to prevent Live refresh issues
2. **Stdout/stderr redirect** - Live redirects standard streams to print above the spinner
3. **Transient mode** - Spinner doesn't leave artifacts in scrollback when hidden

### Output Sanitization

All streaming output passes through `strip_terminal_escapes()` to prevent terminal injection attacks from malicious content in AI responses.

### Streaming Buffer

The Spinner buffers streaming output until complete lines are available:
- Chunks are accumulated in `_stream_buffer`
- When a newline is encountered, complete lines are printed via raw `sys.stdout.write()`
- `flush_stream()` prints any remaining partial line when streaming ends

### Tool Batch Tracking

StreamingDisplay tracks tool batches with:
- `text_before_tools` - Text received before first tool batch
- Tool status (pending/active/success/error/halted/cancelled)
- Duration tracking for long-running tools (shows timer after 3 seconds)
- Error preview (first 120 chars, Rich markup escaped) for failed tools

### Error State Persistence

`StreamingDisplay.had_errors` intentionally persists across `reset()` calls. This allows the REPL to detect if errors occurred across multiple turns. Call `clear_error_state()` explicitly when the user sends new input.

### Final Render Mode

`set_final_render(True)` causes `__rich__` to skip the spinner animation and status bar. This is used when printing the final state to scrollback after Live stops, so only the content (text and tool results) appears without transient UI elements.

### Cancellation Flow

1. User presses ESC (handled by REPL key binding)
2. Cancellation token is triggered
3. Loops check cancellation state and break
4. Spinner hides, activity resets to IDLE
