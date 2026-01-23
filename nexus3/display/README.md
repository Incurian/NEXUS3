# NEXUS3 Display Module

Terminal display system for NEXUS3 providing a simple animated spinner, inline printing with gumball indicators, and consistent theming.

## Purpose

This module provides a unified terminal UI with several key responsibilities:

- **Spinner** - Single animated spinner pinned to bottom, with content printed above (primary interface)
- **Inline scrolling output** - Gumball status indicators and sanitized streaming chunks
- **Theming** - Customizable colors, styles, and gumball characters

## Architecture Overview

```
Spinner (primary - simple animated spinner)
    |
    +-- Console (shared Rich Console)
    +-- Theme (styling)
    +-- Prints content above spinner via Live.console.print()

Legacy (deprecated - use Spinner instead):
    DisplayManager, StreamingDisplay, SummaryBar
```

## Module Files

| File | Description |
|------|-------------|
| `__init__.py` | Public exports |
| `spinner.py` | `Spinner` - animated spinner pinned to bottom (primary) |
| `console.py` | Shared Rich Console singleton |
| `printer.py` | `InlinePrinter` - scrolling output with gumballs |
| `theme.py` | `Theme`, `Status`, `Activity` enums |
| `manager.py` | `DisplayManager` - deprecated, use Spinner |
| `segments.py` | Summary bar segments - deprecated |
| `streaming.py` | `StreamingDisplay` - deprecated, use Spinner |
| `summary.py` | `SummaryBar` - deprecated |

## Key Exports

```python
from nexus3.display import (
    # Console management
    get_console,          # Get shared Console instance
    set_console,          # Set custom Console (for testing)

    # Primary interface (recommended)
    Spinner,              # Simple animated spinner

    # Theme system
    Theme,                # Theme configuration
    Status,               # Status enum (ACTIVE, PENDING, COMPLETE, ERROR, CANCELLED)
    Activity,             # Activity enum (IDLE, WAITING, THINKING, RESPONDING, TOOL_CALLING)
    load_theme,           # Load theme with optional overrides

    # Legacy (deprecated - use Spinner instead)
    DisplayManager,       # Deprecated coordinator
    InlinePrinter,        # Scrolling output
    StreamingDisplay,     # Deprecated Rich.Live streaming
    SummaryBar,           # Deprecated bottom bar
    SummarySegment,       # Deprecated segment protocol
    ActivitySegment,      # Deprecated spinner segment
    TaskCountSegment,     # Deprecated task counts
    CancelHintSegment,    # Deprecated cancel hint
)
```

---

## Core Components

### Spinner (`spinner.py`) - Primary Interface

Simple animated spinner pinned to the bottom of the terminal. All output during an agent turn goes through `spinner.print()`, which prints above the spinner.

```python
from nexus3.display import Spinner, Activity

spinner = Spinner()

# Start spinner
spinner.show("Waiting for response...")

# Print content above spinner
spinner.print("Tool call: read_file")
spinner.print("Result: 42 lines")

# Stream text (no newline)
spinner.print_streaming("Hello ")
spinner.print_streaming("world")
spinner.flush_stream()  # Flush buffer + newline

# Update spinner text
spinner.update("Processing...", activity=Activity.TOOL_CALLING)

# Hide spinner when done
spinner.hide()
```

**Key Methods:**

| Method | Description |
|--------|-------------|
| `show(text, activity)` | Start showing spinner with text |
| `hide()` | Stop spinner, print final state |
| `update(text, activity)` | Update spinner text/activity |
| `print(*args, **kwargs)` | Print above spinner (like console.print) |
| `print_streaming(text)` | Buffer streaming text without newline |
| `flush_stream()` | Flush stream buffer with newline |

---

### Theme System (`theme.py`)

The theme system defines visual styling for all display components.

#### Status Enum

Represents the state of tasks and gumball indicators:

```python
class Status(Enum):
    ACTIVE = "active"       # Currently executing (cyan)
    PENDING = "pending"     # Waiting to start (dim)
    COMPLETE = "complete"   # Finished successfully (green)
    ERROR = "error"         # Failed (red)
    CANCELLED = "cancelled" # User cancelled (yellow)
```

#### Activity Enum

Represents the current agent activity for the summary bar:

```python
class Activity(Enum):
    IDLE = "idle"               # Not doing anything
    WAITING = "waiting"         # Waiting for first byte from API
    THINKING = "thinking"       # Model is reasoning (detected via tags)
    RESPONDING = "responding"   # Model is generating response
    TOOL_CALLING = "tool_calling"  # Executing tool calls
```

#### Theme Configuration

```python
@dataclass
class Theme:
    # Gumball characters with Rich markup
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

#### Usage

```python
# Load default theme
theme = load_theme()

# Load with overrides (future)
theme = load_theme({"thinking": "cyan italic"})

# Get styled gumball
print(theme.gumball(Status.ACTIVE))  # "[cyan]●[/]"
```

---

### Shared Console (`console.py`)

A singleton Rich Console instance ensures consistent output and proper coordination with Rich.Live.

```python
# Get the shared console (created on first access)
console = get_console()

# Console is configured with:
# - highlight=False (no auto-highlighting, we control styling)
# - markup=True (enable [cyan]text[/] markup)
# - force_terminal=True (force terminal mode even if detection fails)

# For testing: set a custom console
from rich.console import Console
set_console(Console(force_terminal=False))
```

All display components should use `get_console()` rather than creating their own Console instances.

---

### InlinePrinter (`printer.py`)

Handles all scrolling content output with gumball status indicators. Output scrolls normally in the terminal.

#### Key Methods

```python
printer = InlinePrinter(console, theme)

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

# Thinking traces
printer.print_thinking("Long reasoning...", collapsed=True)
# Output: "● Thinking..." (cyan)

printer.print_thinking("Long reasoning...", collapsed=False)
# Output: "● <thinking>\nLong reasoning...\n</thinking>"

# Error and cancellation
printer.print_error("File not found")
printer.print_cancelled("User cancelled")

# Streaming output (raw stdout, bypasses Rich)
printer.print_streaming_chunk("Hello ")
printer.print_streaming_chunk("World")
printer.finish_streaming()  # Print newline
```

#### Streaming Safety

`print_streaming_chunk()` uses raw `sys.stdout.write()` to avoid conflicts with Rich.Live. Content is sanitized via `strip_terminal_escapes()` to prevent terminal injection attacks from malicious content.

---

### SummaryBar (`summary.py`)

A bottom-anchored status bar using Rich.Live that displays pluggable segments with animated spinner refresh.

#### Basic Usage

```python
bar = SummaryBar(console, theme)

# Register segments
bar.register_segment(ActivitySegment(theme))
bar.register_segment(TaskCountSegment(theme))
bar.register_segment(CancelHintSegment())

# Context manager usage
with bar.live():
    # Bar auto-refreshes at 8Hz for spinner animation
    segment.set_activity(Activity.RESPONDING)
    bar.refresh()  # Manual refresh after state changes

# Manual start/stop
bar.start()
# ... do work ...
bar.stop()

# Check state
if bar.is_live:
    bar.refresh()
```

#### Segment Protocol

Custom segments must implement the `SummarySegment` protocol:

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

#### Built-in Segments

**ActivitySegment** - Shows current activity with animated spinner:

```python
segment = ActivitySegment(theme)
segment.set_activity(Activity.THINKING)
# Renders: "⠋ thinking" (cyan, spinner animates)
```

**TaskCountSegment** - Shows task status counts:

```python
segment = TaskCountSegment(theme)
segment.add_task()      # pending += 1
segment.start_task()    # pending -= 1, active += 1
segment.complete_task(success=True)   # active -= 1, done += 1
segment.complete_task(success=False)  # active -= 1, failed += 1
segment.reset()         # All counts to 0
# Renders: "● 1 active ○ 2 pending ● 3 done ● 1 failed"
```

**CancelHintSegment** - Shows ESC hint when active:

```python
segment = CancelHintSegment()
segment.show = True
# Renders: "ESC cancel" (dim)
```

---

### StreamingDisplay (`streaming.py`)

A Rich.Live compatible display that accumulates streamed content and tracks tool batch execution. Implements `__rich__` for use directly with Rich.Live.

#### Tool State Tracking

```python
class ToolState(Enum):
    PENDING = "pending"     # Waiting to execute (○ dim)
    ACTIVE = "active"       # Currently running (● cyan, bold)
    SUCCESS = "success"     # Completed successfully (● green)
    ERROR = "error"         # Failed (● red)
    HALTED = "halted"       # Didn't run due to previous error (● dark_orange)
    CANCELLED = "cancelled" # User cancelled (● bright_yellow)
```

#### Basic Usage

```python
display = StreamingDisplay(theme)

with Live(display, refresh_per_second=10) as live:
    # Start activity timer
    display.start_activity_timer()
    display.set_activity(Activity.WAITING)

    # Stream response chunks
    async for chunk in stream:
        display.add_chunk(chunk)  # Auto-sanitizes, truncates to 20 lines
        live.refresh()

    # Track tool batches
    display.start_batch([
        ("read_file", "tool-1", "src/main.py"),
        ("grep", "tool-2", "pattern=TODO"),
    ])

    display.set_tool_active("tool-1")
    # ... execute tool ...
    display.set_tool_complete("tool-1", success=True)

    display.set_tool_active("tool-2")
    display.set_tool_complete("tool-2", success=False, error="Pattern not found")

    # Get results for scrollback
    results = display.get_batch_results()

# Reset for next turn
display.reset()
```

#### Rendered Output

During Rich.Live, the display renders:

```
[Response text, truncated to last 20 lines]
...
Recent response content here

  ● read_file: src/main.py
  ● grep: pattern=TODO (3s)
      Pattern not found...

⠋ Running: grep | 1 complete, 0 pending

⠋ ● active | ESC cancel
```

#### Key Features

**Response truncation**: Limits visible content to `MAX_DISPLAY_LINES` (20) to prevent Rich.Live overflow (the "three red dots" issue).

**Activity timer**: Shows elapsed time for each activity state (e.g., "Waiting for response... (5s)").

**Tool timers**: Shows execution time for tools running longer than `TOOL_TIMER_THRESHOLD` (3 seconds).

**Thinking tracking**: Tracks reasoning phases with start/end times:

```python
display.start_thinking()
# ... model reasons ...
was_thinking, duration = display.end_thinking()
total = display.get_total_thinking_duration()
display.clear_thinking_duration()
```

**Cancellation**:

```python
display.cancel()           # Mark as cancelled, set IDLE
display.cancel_all_tools() # Mark all tools as cancelled
if display.is_cancelled:
    break
```

**Batch progress**: Renders "Running: tool_name | n complete, m pending" during tool execution.

**Error tracking**:

```python
display.mark_error()           # Mark that an error occurred
if display.had_errors:
    # Handle error state
display.clear_error_state()    # Clear on new user input
```

---

### DisplayManager (`manager.py`)

Central coordinator for all terminal display. Owns the printer, summary bar, and manages cancellation.

#### Basic Usage

```python
display = DisplayManager()
# Or with custom console/theme:
display = DisplayManager(console=my_console, theme=my_theme)

async with display.live_session():
    # Summary bar is running with spinner
    # Cancellation token is active

    display.set_activity(Activity.THINKING)
    display.add_task()

    if display.is_cancelled:
        display.print_cancelled()
        return

    display.complete_task(success=True)
    display.set_activity(Activity.IDLE)
```

#### Live Session Management

```python
# Context manager (recommended)
async with display.live_session():
    # Summary bar starts, cancellation token active
    # ESC hint shown when activity != IDLE
    pass
# Summary bar stops, token cleared

# Manual control
display.stop_live()  # Stop before streaming to avoid Rich.Live conflicts
```

#### Activity Management

```python
display.set_activity(Activity.IDLE)
display.set_activity(Activity.WAITING)
display.set_activity(Activity.THINKING)
display.set_activity(Activity.RESPONDING)
display.set_activity(Activity.TOOL_CALLING)
```

#### Task Tracking

```python
display.add_task()                    # Register pending task
display.start_task()                  # Move pending -> active
display.complete_task(success=True)   # Complete active task
display.complete_task(success=False)  # Mark active task as failed
display.reset_tasks()                 # Reset all counts
```

#### Cancellation

```python
# Check if cancelled
if display.is_cancelled:
    display.print_cancelled("Operation cancelled")
    return

# Cancel programmatically
display.cancel()

# Access the token directly
token = display.cancel_token
if token and token.is_cancelled:
    pass
```

#### Printing (Delegates to InlinePrinter)

```python
# Basic printing
display.print("Hello world")
display.print("Error!", style="red")

# Gumballs
display.print_gumball(Status.ACTIVE, "Working...")
display.print_gumball(Status.COMPLETE, "Done", indent=2)

# Tasks
display.print_task_start("read_file", "src/main.py")
display.print_task_end("read_file", success=True)

# Thinking
display.print_thinking("Reasoning content", collapsed=True)

# Errors
display.print_error("Something went wrong")
display.print_cancelled("Cancelled by user")

# Streaming
display.stop_live()  # Important: stop before streaming!
display.print_streaming("chunk1")
display.print_streaming("chunk2")
display.finish_streaming()
```

---

## Integration Patterns

### REPL Integration

The REPL uses both DisplayManager and StreamingDisplay:

```python
display_mgr = DisplayManager()
streaming = StreamingDisplay(theme)

# During turn execution
async with display_mgr.live_session():
    with Live(streaming, refresh_per_second=10) as live:
        streaming.start_activity_timer()
        streaming.set_activity(Activity.WAITING)

        async for event in session.run_turn(message):
            if display_mgr.is_cancelled:
                streaming.cancel_all_tools()
                break

            if isinstance(event, TextDelta):
                streaming.add_chunk(event.content)
                live.refresh()
            elif isinstance(event, ToolStarted):
                streaming.set_tool_active(event.tool_id)
            elif isinstance(event, ToolCompleted):
                streaming.set_tool_complete(
                    event.tool_id,
                    event.success,
                    error=event.error
                )
```

### Non-Streaming Output (InlinePrinter Only)

For output that doesn't need Rich.Live (e.g., status messages):

```python
printer = InlinePrinter(get_console(), load_theme())

printer.print_gumball(Status.ACTIVE, "Starting process...")
# ... do work ...
printer.print_gumball(Status.COMPLETE, "Process complete")
```

### Custom Summary Segments

Create custom segments for specialized status displays:

```python
class TokenCountSegment:
    def __init__(self, theme: Theme) -> None:
        self.theme = theme
        self.used = 0
        self.total = 0

    @property
    def visible(self) -> bool:
        return self.total > 0

    def render(self) -> Text:
        ratio = self.used / self.total if self.total > 0 else 0
        style = "red" if ratio > 0.9 else "yellow" if ratio > 0.7 else "green"
        return Text(f"{self.used:,}/{self.total:,} tokens", style=style)

# Register with summary bar
bar.register_segment(TokenCountSegment(theme))
```

---

## Dependencies

### Internal

- `nexus3.core.cancel` - `CancellationToken` for coordinated cancellation
- `nexus3.core.text_safety` - `strip_terminal_escapes()` for sanitizing output

### External

- `rich` - Console, Live, Text, Group for terminal rendering

---

## Design Notes

### Rich.Live Coordination

Only one Rich.Live context can be active at a time. The display module handles this by:

1. **SummaryBar** uses Rich.Live for the bottom status bar (8Hz refresh)
2. **StreamingDisplay** uses Rich.Live for full-screen streaming display (10Hz)
3. **InlinePrinter** uses raw stdout for streaming chunks to avoid conflicts

Always call `display.stop_live()` before streaming output, or use StreamingDisplay within its own Live context.

### Terminal Overflow Prevention

StreamingDisplay limits visible content to 20 lines (`MAX_DISPLAY_LINES`) to prevent the "three red dots" Rich.Live overflow issue that occurs when content exceeds terminal height.

### Output Sanitization

All streaming output passes through `strip_terminal_escapes()` to prevent terminal injection attacks from malicious content in AI responses.

### Cancellation Flow

1. User presses ESC (handled by REPL key binding)
2. `display.cancel()` is called
3. `CancellationToken.cancel()` is triggered
4. All loops check `display.is_cancelled` and break
5. Activity resets to IDLE, ESC hint hidden

---

## Future Extensions

The segment system is designed for extensibility. Potential additions noted in the code:

- `TokenCountSegment` - "1.2k / 8k tokens"
- `SubagentSegment` - "agent:analyzer agent:fixer"
- `WorkflowSegment` - "Step 2/5: analyzing"

Theme overrides from config are stubbed but not fully implemented.
