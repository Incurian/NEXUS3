# NEXUS3 Display Module

Terminal display system for NEXUS3 providing a simple animated spinner, inline printing with gumball indicators, and consistent theming.

## Purpose

This module provides a unified terminal UI with several key responsibilities:

- **Spinner** - Animated spinner pinned to bottom, with content printed above (primary interface)
- **Inline printing** - Gumball status indicators and sanitized streaming output
- **Theming** - Customizable colors, styles, and gumball characters

## Architecture Overview

```
Spinner (primary interface)
    |
    +-- Console (shared Rich Console singleton)
    +-- Theme (styling configuration)
    +-- Prints content above spinner via Live.console.print()

Legacy (deprecated - use Spinner instead):
    DisplayManager, StreamingDisplay, SummaryBar, Segments
```

## Module Files

| File | Description |
|------|-------------|
| `__init__.py` | Public exports |
| `spinner.py` | `Spinner` - animated spinner pinned to bottom (primary) |
| `console.py` | Shared Rich Console singleton |
| `theme.py` | `Theme`, `Status`, `Activity` enums |
| `printer.py` | `InlinePrinter` - scrolling output with gumballs |
| `manager.py` | `DisplayManager` - deprecated, use Spinner |
| `streaming.py` | `StreamingDisplay` - deprecated, use Spinner |
| `summary.py` | `SummaryBar` - deprecated, use Spinner |
| `segments.py` | Summary bar segments - deprecated |

## Key Exports

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

    # Legacy (deprecated)
    DisplayManager,       # Use Spinner instead
    StreamingDisplay,     # Use Spinner instead
    SummaryBar,           # Use Spinner instead
    SummarySegment,       # Segment protocol
    ActivitySegment,      # Spinner segment
    TaskCountSegment,     # Task counts
    CancelHintSegment,    # Cancel hint
)
```

---

## Core Components

### Spinner (`spinner.py`)

The primary display interface. Provides an animated spinner pinned to the bottom of the terminal using Rich.Live. All output during an agent turn goes through `spinner.print()`, which prints above the spinner.

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

**Key Methods:**

| Method | Description |
|--------|-------------|
| `show(text, activity)` | Start showing spinner with text |
| `hide()` | Stop spinner, flush stream buffer |
| `update(text, activity)` | Update spinner text and/or activity |
| `print(*args, **kwargs)` | Print above spinner (delegates to console.print) |
| `print_streaming(chunk)` | Buffer streaming text, print complete lines |
| `flush_stream()` | Flush remaining buffer content |

**Properties:**

| Property | Description |
|----------|-------------|
| `is_active` | Whether spinner is currently showing |
| `elapsed` | Seconds since spinner started |
| `live` | Underlying Rich.Live instance (for integration) |

**Key Behaviors:**

- Uses Rich.Live with `transient=True` to avoid leaving spinner in scrollback
- Redirects stdout/stderr through Live to prevent artifacts
- Single-line render with `no_wrap=True` and `overflow="crop"` to prevent wrapping issues
- Shows elapsed time after 1 second
- Shows "ESC cancel" hint by default (configurable via `show_cancel_hint`)
- Streaming output is sanitized via `strip_terminal_escapes()`

---

### Shared Console (`console.py`)

A singleton Rich Console instance ensures consistent output and proper coordination with Rich.Live.

```python
from nexus3.display import get_console, set_console

# Get the shared console (created on first access)
console = get_console()

# For testing: set a custom console
from rich.console import Console
set_console(Console(force_terminal=False))
```

**Console Configuration:**

- `highlight=False` - No auto-highlighting, styling is controlled explicitly
- `markup=True` - Enable Rich markup like `[cyan]text[/]`
- `force_terminal=True` - Force terminal mode even if detection fails
- `legacy_windows=False` - Enable VT100 mode on Windows 10+

All display components should use `get_console()` rather than creating their own Console instances.

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

Represents the current agent activity:

```python
class Activity(Enum):
    IDLE = "idle"               # Not doing anything
    WAITING = "waiting"         # Waiting for first byte from API
    THINKING = "thinking"       # Model is reasoning
    RESPONDING = "responding"   # Model is generating response
    TOOL_CALLING = "tool_calling"  # Executing tool calls
```

#### Theme Configuration

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

#### Usage

```python
from nexus3.display import load_theme, Status

theme = load_theme()
print(theme.gumball(Status.ACTIVE))  # "[cyan]●[/]"
```

---

### InlinePrinter (`printer.py`)

Handles scrolling content output with gumball status indicators.

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

# Thinking traces
printer.print_thinking("Long reasoning...", collapsed=True)
# Output: "● Thinking..." (cyan)

# Error and cancellation
printer.print_error("File not found")
printer.print_cancelled("User cancelled")

# Streaming output (raw stdout, bypasses Rich)
printer.print_streaming_chunk("Hello ")
printer.print_streaming_chunk("World")
printer.finish_streaming()  # Print newline
```

**Streaming Safety:**

`print_streaming_chunk()` uses raw `sys.stdout.write()` to avoid conflicts with Rich.Live. Content is sanitized via `strip_terminal_escapes()` to prevent terminal injection attacks.

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

The Spinner uses Rich.Live internally. Key behaviors:

1. **Single-line rendering** - Spinner is constrained to one line (`no_wrap=True`, `overflow="crop"`) to prevent Live refresh issues
2. **Stdout/stderr redirect** - Live redirects standard streams to print above the spinner
3. **Transient mode** - Spinner doesn't leave artifacts in scrollback when hidden

### Output Sanitization

All streaming output passes through `strip_terminal_escapes()` to prevent terminal injection attacks from malicious content in AI responses.

### Cancellation Flow

1. User presses ESC (handled by REPL key binding)
2. Cancellation token is triggered
3. Loops check cancellation state and break
4. Spinner hides, activity resets to IDLE

---

## Legacy Components (Deprecated)

The following components are deprecated. Use `Spinner` instead for new code.

### DisplayManager (`manager.py`)

Central coordinator that owns InlinePrinter, SummaryBar, and manages cancellation. Provides `live_session()` async context manager.

### StreamingDisplay (`streaming.py`)

Rich.Live compatible display that accumulates streamed content and tracks tool batch execution. Includes `ToolState` enum and `ToolStatus` dataclass for tool tracking.

### SummaryBar (`summary.py`)

Bottom-anchored status bar using Rich.Live with pluggable segments.

### Segments (`segments.py`)

- `SummarySegment` - Protocol for custom segments
- `ActivitySegment` - Shows activity with animated spinner
- `TaskCountSegment` - Shows task status counts
- `CancelHintSegment` - Shows "ESC cancel" hint
