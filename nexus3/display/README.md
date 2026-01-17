# NEXUS3 Display Module

Terminal display system for NEXUS3, providing Rich-based inline printing with gumball status indicators, a pluggable animated summary bar, streaming display for responses and tool batches, centralized management, consistent theming, and cancellation support.

## Purpose

Handles all terminal output in NEXUS3:
- **Inline scrolling output** (`InlinePrinter`): Gumballs, tasks, thinking traces, errors (uses Rich.Console). Includes ANSI sanitization for safe streaming.
- **Fixed summary bar** (`SummaryBar`): Live-updating segments (activity spinner, task counts, ESC hint) at bottom.
- **Full-screen streaming** (`StreamingDisplay`): Rich.Live for responses + batch tool progress (truncates to 20 lines).
- **Coordination** (`DisplayManager`): Printer + summary + tasks + cancellation token.
- **Consistency**: Shared `Console`, customizable `Theme`.
- Supports activity states (IDLE, WAITING, THINKING, etc.) and ESC cancellation.

Separates scrolling content from fixed UI to coexist without conflicts. Streaming mode optional for full Live.

## Modules & Key Exports

From [`__init__.py`](__init__.py):

**Console**: `get_console()`, `set_console()`
**Manager**: `DisplayManager`
**Printer**: `InlinePrinter`
**Streaming**: `StreamingDisplay`
**Summary**: `SummaryBar`
**Segments**: `ActivitySegment`, `CancelHintSegment`, `SummarySegment` (protocol), `TaskCountSegment`
**Theme**: `Activity`, `Status`, `Theme`, `load_theme()`

### File Overview

| File | Size | Modified | Description |
|------|------|----------|-------------|
| [`__init__.py`](__init__.py) | 953B | 2026-01-07 | Exports |
| [`console.py`](console.py) | 968B | 2026-01-09 | Shared Console singleton |
| [`manager.py`](manager.py) | 5.8K | 2026-01-07 | `DisplayManager`: Orchestrates all |
| [`printer.py`](printer.py) | 4.0K | 2026-01-16 | `InlinePrinter`: Scrolling + gumballs + ANSI sanitization |
| [`segments.py`](segments.py) | 3.3K | 2026-01-07 | Segments: Activity, Tasks, CancelHint |
| [`streaming.py`](streaming.py) | 13.8K | 2026-01-12 | `StreamingDisplay`: Live streaming + tools |
| [`summary.py`](summary.py) | 3.6K | 2026-01-07 | `SummaryBar`: Composes Live segments |
| [`theme.py`](theme.py) | 1.9K | 2026-01-07 | Enums, `Theme` dataclass |

## Key Classes & Functions

### Enums (`theme.py`)
- **`Status`**: ACTIVE, PENDING, COMPLETE, ERROR, CANCELLED (gumballs).
- **`Activity`**: IDLE, WAITING, THINKING, RESPONDING, TOOL_CALLING.
- **`ToolState` (streaming)**: PENDING, ACTIVE, SUCCESS, ERROR, HALTED, CANCELLED.

### `Theme` (`theme.py`)
Configures gumballs (e.g., `[cyan]●[/]`), styles, spinners. `load_theme()`.

### `DisplayManager` (`manager.py`) - Central Hub
```python
display = DisplayManager()  # Auto console/theme/segments
async with display.live_session():  # Starts summary Live + token
    display.set_activity(Activity.THINKING)
    display.add_task()  # Updates TaskCountSegment
    display.print_gumball(Status.ACTIVE, "Task starting")
    if display.is_cancelled: break
display.stop_live()  # Before raw streaming
display.print_streaming(chunk)  # Raw stdout
```

Methods: `print*()`, `set_activity()`, task tracking, `cancel_token`.

### `InlinePrinter` (`printer.py`)
Gumball-prefixed scrolling: `print_gumball()`, `print_task_start/end()`, `print_thinking()`, `print_streaming_chunk()` (raw, sanitized).

### `SummaryBar` (`summary.py`) + Segments (`segments.py`)
Pluggable: `register_segment(ActivitySegment(theme))`. `with bar.live():`.

### `StreamingDisplay` (`streaming.py`)
```python
display = StreamingDisplay(theme)
with Live(display):  # Auto-refreshes
    display.add_chunk(chunk)
    display.start_batch([("read_file", "id1", "path.py")])
    display.set_tool_active("id1")
```

Tracks tool batches, thinking duration, errors, timers.

## Dependencies
- **rich**: Console, Live, Text, Group.
- **nexus3.core.cancel**: `CancellationToken`.
- Python stdlib: `time`, `dataclasses`, `enum`, `contextlib`, `collections.abc`, `sys`, `re`.

## Usage Examples

### 1. Standard Workflow (`DisplayManager`)
```python
from nexus3.display import DisplayManager, Activity

async def process():
    dm = DisplayManager()
    async with dm.live_session():
        dm.set_activity(Activity.WAITING)
        dm.stop_live()  # Safe for streaming
        async for chunk in api.stream():
            if dm.is_cancelled: break
            dm.print_streaming(chunk)
        dm.finish_streaming()
        dm.set_activity(Activity.IDLE)
```

### 2. Custom Summary Bar
```python
from nexus3.display import SummaryBar, get_console, load_theme, ActivitySegment, TaskCountSegment

bar = SummaryBar(get_console(), load_theme())
bar.register_segment(ActivitySegment(load_theme()))
bar.register_segment(TaskCountSegment(load_theme()))
with bar.live():
    # Update segments...
    bar.refresh()
```

### 3. Streaming + Tools
```python
from rich.live import Live
from nexus3.display.streaming import StreamingDisplay, load_theme

sd = StreamingDisplay(load_theme())
with Live(sd, refresh_per_second=10):
    sd.set_activity(Activity.TOOL_CALLING)
    sd.start_batch([("glob", "t1", "*.py"), ("read_file", "t2", "file.py")])
    sd.set_tool_active("t1")
    sd.set_tool_complete("t1", True)
    sd.add_chunk("Response text...")
```

## Architecture Summary
- **Layers**: Theme → Console → Printer/SummaryBar/StreamingDisplay → Manager.
- **Live Management**: Only `SummaryBar` uses Rich.Live (8Hz); streaming raw or full Live.
- **State Tracking**: Activities, tasks (pending/active/done/failed), tools (per-batch), thinking time, errors.
- **Cancellation**: ESC → `Manager.cancel()` → token + UI updates.
- **Conflicts Avoided**: `stop_live()` before raw print_streaming.
- **Extensible**: Add segments; theme overrides; StreamingDisplay for complex UIs.
- **Performance**: Truncates streaming (20 lines); efficient renders.

Exports everything for `from nexus3.display import *`.
