# NEXUS3 Display Module

Terminal display system for NEXUS3, providing Rich-based output with gumball status indicators, animated streaming display, batch tool progress tracking, and a pluggable summary bar.

## Purpose

This module handles all terminal output for NEXUS3:
- Inline scrolling output with gumball status prefixes (`InlinePrinter`)
- Fixed summary bar with animated spinners and task counts (`SummaryBar`)
- Full-screen streaming display for responses and tool batches (`StreamingDisplay`)
- Centralized coordination (`DisplayManager`)
- Shared `Console` singleton and `Theme` for consistent styling
- Activity state tracking and cancellation support

The architecture separates **scrolling content** (inline printing) from **fixed UI** (summary bar), allowing coexistence without conflicts. `StreamingDisplay` provides an alternative full-Rich.Live mode for streaming.

## File Overview

| File | Description |
|------|-------------|
| [`__init__.py`](__init__.py) | Public exports: all classes, enums, functions |
| [`console.py`](console.py) | Shared `Rich.Console` singleton: `get_console()`, `set_console()` |
| [`theme.py`](theme.py) | `Status`, `Activity` enums; `Theme` dataclass; `load_theme()` |
| [`printer.py`](printer.py) | `InlinePrinter`: scrolling output with gumballs |
| [`segments.py`](segments.py) | `SummarySegment` protocol; `ActivitySegment`, `TaskCountSegment`, `CancelHintSegment` |
| [`summary.py`](summary.py) | `SummaryBar`: composes and animates segments via `Rich.Live` |
| [`streaming.py`](streaming.py) | `StreamingDisplay`: accumulates and renders streamed content + tool batches |
| [`manager.py`](manager.py) | `DisplayManager`: orchestrates printer, summary bar, tasks, cancellation |

## Key Types

### Enums

#### `Status` (`theme.py`)
Gumball status indicators.

| Value | Description |
|-------|-------------|
| `ACTIVE` | In-progress |
| `PENDING` | Queued/waiting |
| `COMPLETE` | Successful |
| `ERROR` | Failed |
| `CANCELLED` | User-cancelled |

#### `Activity` (`theme.py`)
Current system activity for summary/activity segments.

| Value | Description |
|-------|-------------|
| `IDLE` | No operation |
| `WAITING` | Awaiting first API byte |
| `THINKING` | Model reasoning (tags detected) |
| `RESPONDING` | Streaming content |
| `TOOL_CALLING` | Executing tools |

#### `ToolState` (`streaming.py`)
Tool execution states in a batch.

| Value | Description |
|-------|-------------|
| `PENDING` | Queued |
| `ACTIVE` | Running |
| `SUCCESS` | Completed OK |
| `ERROR` | Failed |
| `HALTED` | Skipped (prior error) |
| `CANCELLED` | User-cancelled |

### Data Classes

#### `Theme` (`theme.py`)
Centralizes all visual styles.

```python
@dataclass
class Theme:
    gumballs: dict[Status, str]  # e.g., "[cyan]●[/]"
    spinner_frames: str = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    thinking: str = "dim italic"
    thinking_collapsed: str = "dim"
    response: str = ""
    error: str = "bold red"
    user_input: str = "bold"
    summary_style: str = ""
    summary_separator: str = " | "

    def gumball(self, status: Status) -> str:
        return self.gumballs.get(status, "○")
```

**Default Gumballs:**
| Status | Markup |
|--------|--------|
| `ACTIVE` | `[cyan]●[/]` |
| `PENDING` | `[dim]○[/]` |
| `COMPLETE` | `[green]●[/]` |
| `ERROR` | `[red]●[/]` |
| `CANCELLED` | `[yellow]●[/]` |

`load_theme(overrides=None) -> Theme`: Returns default `Theme()` (overrides scaffolded).

#### `ToolStatus` (`streaming.py`)
```python
@dataclass
class ToolStatus:
    name: str
    tool_id: str
    state: ToolState = ToolState.PENDING
    params: str = ""  # Truncated primary arg (e.g., path)
    error: str = ""
    start_time: float = 0.0
```

## Core Classes

### Console (`console.py`)
Shared `Rich.Console` for consistency.

```python
def get_console() -> Console: ...
def set_console(console: Console) -> None: ...
```

**Config:** `highlight=False`, `markup=True`, `force_terminal=True`.

### InlinePrinter (`printer.py`)
Scrolling output with styled gumballs/tasks.

```python
class InlinePrinter:
    def __init__(self, console: Console, theme: Theme) -> None: ...
    def print(self, content: str, style: str | None = None, end: str = "\n") -> None: ...
    def print_gumball(self, status: Status, message: str, indent: int = 0) -> None: ...
    def print_thinking(self, content: str, collapsed: bool = True) -> None: ...
    def print_task_start(self, task_type: str, label: str, indent: int = 2) -> None: ...
    def print_task_end(self, task_type: str, success: bool, indent: int = 2) -> None: ...
    def print_error(self, message: str) -> None: ...
    def print_cancelled(self, message: str = "Cancelled") -> None: ...
    def print_streaming_chunk(self, chunk: str) -> None:  # Raw stdout
    def finish_streaming(self) -> None:  # Newline
```

### Summary Segments (`segments.py`)
`SummarySegment(Protocol)`: `@property visible() -> bool`, `render() -> Text`.

**Built-ins:**
- `ActivitySegment`: Spinner + activity name.
- `TaskCountSegment`: Counts with gumballs (active/pending/done/failed).
  - Methods: `add_task()`, `start_task()`, `complete_task(success=True)`, `reset()`.
- `CancelHintSegment`: `"ESC cancel"` (set `show: bool`).

### SummaryBar (`summary.py`)
Composes/animates segments.

```python
class SummaryBar:
    def __init__(self, console: Console, theme: Theme) -> None: ...
    def register_segment(self, segment: SummarySegment, position: int = -1) -> None: ...
    def unregister_segment(self, segment: SummarySegment) -> None: ...
    def live(self) -> Generator[None, None, None]: ...  # Context mgr
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def refresh(self) -> None: ...
    @property def is_live(self) -> bool: ...
```

Renders visible segments joined by `theme.summary_separator`.

### StreamingDisplay (`streaming.py`)
Rich.Live renderable for streaming + tool batches. Limits to last 20 lines.

```python
class StreamingDisplay:
    MAX_DISPLAY_LINES = 20
    TOOL_TIMER_THRESHOLD = 3.0

    def __init__(self, theme: Theme) -> None: ...
    def __rich__(self) -> RenderableType: ...  # Live refresh

    # Activity
    def set_activity(self, activity: Activity) -> None: ...
    def start_activity_timer(self) -> None: ...
    def get_activity_duration(self) -> float: ...

    # Content
    def add_chunk(self, chunk: str) -> None: ...
    def reset(self) -> None: ...

    # Cancel
    def cancel(self) -> None: ...
    def cancel_all_tools(self) -> None: ...
    @property def is_cancelled(self) -> bool: ...

    # Thinking
    def start_thinking(self) -> None: ...
    def end_thinking(self) -> tuple[bool, float]: ...
    def get_total_thinking_duration(self) -> float: ...
    def clear_thinking_duration(self) -> None: ...
    @property def thinking_duration(self) -> float: ...

    # Errors
    def mark_error(self) -> None: ...
    def clear_error_state(self) -> None: ...
    @property def had_errors(self) -> bool: ...

    # Tools (batch)
    def add_tool_call(self, name: str, tool_id: str) -> None:  # Legacy/stream
    def start_batch(self, tools: list[tuple[str, str, str]]) -> None:  # (name,id,params)
    def set_tool_active(self, tool_id: str) -> None: ...
    def set_tool_complete(self, tool_id: str, success: bool, error: str = "") -> None: ...
    def halt_remaining_tools(self) -> None: ...
    def complete_tool_call(self, tool_id: str) -> None:  # Legacy
    def get_batch_results(self) -> list[ToolStatus]: ...
    def clear_tools(self) -> None: ...
```

**Render Order:** Response (truncated) → Tools → Activity/timer → Status bar.

### DisplayManager (`manager.py`)
Orchestrates all components + cancellation.

```python
class DisplayManager:
    def __init__(self, console: Console | None = None, theme: Theme | None = None) -> None: ...

    @property def cancel_token(self) -> CancellationToken | None: ...
    @property def is_cancelled(self) -> bool: ...
    def cancel(self) -> None: ...

    async def live_session(self) -> AsyncGenerator[None, None]: ...  # Auto start/stop + token
    def stop_live(self) -> None: ...

    # Activity
    def set_activity(self, activity: Activity) -> None: ...

    # Tasks (via TaskCountSegment)
    def add_task(self) -> None: ...
    def start_task(self) -> None: ...
    def complete_task(self, success: bool = True) -> None: ...
    def reset_tasks(self) -> None: ...

    # Printing (delegates)
    def print(self, content: str, style: str | None = None) -> None: ...
    def print_gumball(self, status: Status, message: str, indent: int = 0) -> None: ...
    def print_thinking(self, content: str, collapsed: bool = True) -> None: ...
    def print_task_start(self, task_type: str, label: str) -> None: ...
    def print_task_end(self, task_type: str, success: bool) -> None: ...
    def print_error(self, message: str) -> None: ...
    def print_cancelled(self, message: str = "Cancelled") -> None: ...
    def print_streaming(self, chunk: str) -> None: ...
    def finish_streaming(self) -> None: ...
```

**Defaults:** Registers `ActivitySegment`, `TaskCountSegment`, `CancelHintSegment`.

## Usage Examples

### DisplayManager (Recommended)
```python
from nexus3.display import DisplayManager, Activity

async def handle_request():
    display = DisplayManager()
    async with display.live_session():
        display.set_activity(Activity.WAITING)
        display.stop_live()  # Before streaming
        async for chunk in stream:
            if display.is_cancelled: break
            display.print_streaming(chunk)
        display.finish_streaming()
```

### StreamingDisplay + Tools
```python
from rich.live import Live
from nexus3.display.streaming import StreamingDisplay
from nexus3.display import load_theme

display = StreamingDisplay(load_theme())
with Live(display, refresh_per_second=10):
    display.set_activity(Activity.WAITING)
    # Stream chunks...
    display.start_batch([("read_file", "id1", "file.py"), ...])
    # Update tools...
```

### Custom SummaryBar
```python
from nexus3.display import SummaryBar, get_console, load_theme, SummarySegment
from rich.text import Text

class MySegment(SummarySegment):
    @property
    def visible(self) -> bool: return True
    def render(self) -> Text: return Text("custom")

bar = SummaryBar(get_console(), load_theme())
bar.register_segment(MySegment())
with bar.live(): ...
```

## Architecture Notes
- **Live Conflicts:** Stop `SummaryBar`/`live_session()` before streaming (uses raw stdout).
- **Overflow Prevention:** `StreamingDisplay` truncates to 20 lines.
- **Timers:** Activity ≥1s; tools ≥3s.
- **Cancellation:** `DisplayManager.cancel()` propagates to token/segments.
- **Exports:** All public API from `nexus3.display`.

## Dependencies
- **Rich:** `Console`, `Live`, `Text`, `Group`.
- **Internal:** `nexus3.core.cancel.CancellationToken`.
