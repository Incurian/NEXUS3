# NEXUS3 Display Module

Terminal display system for NEXUS3: inline printing with gumballs, configurable animated summary bar, streaming display for responses/tools, centralized coordination, consistent theming, ESC cancellation.

## Purpose

Unified terminal UI:
- **Inline scrolling** (`InlinePrinter`): Gumballs ●○, tasks, thinking traces, sanitized streaming (Rich.Console + raw stdout).
- **Live summary bar** (`SummaryBar`): Segments for activity spinner, task counts, ESC hint (Rich.Live, 8Hz).
- **Full streaming** (`StreamingDisplay`): Response + tool batch progress (Rich.Live, truncates to 20 lines).
- **Coordination** (`DisplayManager`): Printer + bar + tasks + `CancellationToken`.
- **Theming**: `Theme` for colors/styles.

Supports `Activity` (IDLE, THINKING, TOOL_CALLING) and `Status` states.

## Exports (`__init__.py`)

```
get_console(), set_console()
DisplayManager, InlinePrinter
StreamingDisplay
SummaryBar
ActivitySegment, CancelHintSegment, SummarySegment (protocol), TaskCountSegment
Activity, Status, Theme, load_theme()
```

## Key Classes/Functions

### DisplayManager (manager.py)
Central hub.

```python
display = DisplayManager()
async with display.live_session():  # Starts Live + token
    display.set_activity(Activity.THINKING)
    display.add_task()
    display.print_gumball(Status.ACTIVE, "read_file: foo.py")
    if display.is_cancelled: break
display.stop_live()  # Before streaming
display.print_streaming(chunk)
display.finish_streaming()
```

Methods: `print*()`, task tracking (`add_task()`, `complete_task()`), `set_activity()`.

### InlinePrinter (printer.py)
Scrolling output: `print_gumball()`, `print_task_start/end()`, `print_thinking()`, `print_streaming_chunk()` (raw, sanitized).

### SummaryBar + Segments (summary.py, segments.py)
```python
bar = SummaryBar(console, theme)
bar.register_segment(ActivitySegment(theme))
bar.register_segment(TaskCountSegment(theme))
with bar.live():
    bar.refresh()  # Updates spinners
```

### StreamingDisplay (streaming.py)
Tool batches + response.

```python
display = StreamingDisplay(theme)
with Live(display, refresh_per_second=10):
    display.add_chunk(chunk)
    display.start_batch([("read_file", "id1", "path.py")])
    display.set_tool_active("id1")
```

Tracks `ToolState` (PENDING→ACTIVE→SUCCESS/ERROR), timers, thinking duration.

### Theme (theme.py)
```python
theme = load_theme()  # Customizable gumballs/styles
```

## Files

| File          | Size  | Modified         | Description                  |
|---------------|-------|------------------|------------------------------|
| `__init__.py` | 953B  | 2026-01-07 14:41 | Exports                     |
| `console.py`  | 968B  | 2026-01-09 13:18 | Shared Console              |
| `manager.py`  | 5.8K  | 2026-01-07 14:35 | DisplayManager              |
| `printer.py`  | 3.6K  | 2026-01-17 06:50 | InlinePrinter               |
| `segments.py` | 3.3K  | 2026-01-07 14:00 | Segments                    |
| `streaming.py`| 14K   | 2026-01-17 06:50 | StreamingDisplay + tools    |
| `summary.py`  | 3.6K  | 2026-01-07 14:35 | SummaryBar                  |
| `theme.py`    | 1.9K  | 2026-01-07 14:48 | Enums, Theme                |

## Notes
- Avoid Live conflicts: `stop_live()` before raw streaming.
- Dependencies: `rich`; `nexus3.core` (cancel, text_safety).
- Extensible: Add segments; theme overrides.