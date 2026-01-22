# NEXUS3 Display System - Comprehensive Research

## Module Structure (`nexus3/display/`)

| File | Purpose | Lines |
|------|---------|-------|
| `console.py` | Shared Rich Console singleton | 32 |
| `theme.py` | Status/Activity enums, Theme dataclass | 71 |
| `manager.py` | DisplayManager - not used by REPL currently | 170 |
| `printer.py` | InlinePrinter - scrolling output with gumballs | 103 |
| `summary.py` | SummaryBar - Rich.Live bottom status bar | 114 |
| `streaming.py` | StreamingDisplay - Live display with tool tracking | 417 |
| `segments.py` | SummaryBar segments (Activity, TaskCount, CancelHint) | 122 |
| **Event-driven (implemented, tested, not wired to REPL):** | | |
| `state.py` | DisplayState - event-driven state model | 221 |
| `reducer.py` | Event handlers for SessionEvents | 496 |
| `render.py` | Rich rendering pipeline | 1019 |
| `bridge.py` | Callback adapter for compatibility | 210 |

**Note:** `nexus3/cli/repl.py` is ~1864 lines (not 1661 as previously stated).

---

## Component Roles

### StreamingDisplay (`streaming.py`) - ACTUAL REPL DISPLAY

**The REPL uses StreamingDisplay directly**, not DisplayManager:
```python
from nexus3.display import Activity, StreamingDisplay, get_console
from nexus3.display.streaming import ToolState
```

The REPL uses `Rich.Live(display, ..., transient=False)` during the agent turn.

**DisplayManager, SummaryBar, and InlinePrinter are NOT used** by `repl.py` for the main turn streaming path.

**Responsibilities:**
- Accumulate response text (truncated to last 20 lines in `__rich__()`)
- Track tool batch state
- Render spinner + activity timer
- Show tool timers (>3s)

**IMPORTANT:** The truncation happens during rendering. With `transient=False`, the final on-screen render persists, but it is still the **truncated** view. The REPL does NOT print the full response to scrollback after Live exits.

**Tool States:**
```
PENDING (○ dim)     → Not yet executing
ACTIVE (● cyan)     → Currently running
SUCCESS (● green)   → Completed successfully
ERROR (● red)       → Failed
HALTED (● orange)   → Skipped (sequential batch halted)
CANCELLED (● yellow)→ User cancelled
```

**Rendered Output:**
```
[Response content, last 20 lines]

  ● read_file: src/main.py
  ● grep: pattern (5s elapsed)
      → Error: not found

⠋ Running: grep | 1 complete, 2 pending
⠋ ● active | ESC cancel
```

---

### DisplayManager (`manager.py`) - NOT USED BY REPL

Central coordinator for display output, but **not currently used by the REPL**.

**Owns:**
- InlinePrinter (scrolling output)
- SummaryBar (bottom status)
- CancellationToken (ESC handling)

**Key Methods:**
- `live_session()` - Context manager, starts/stops summary bar
- `set_activity(activity)` - Update activity state
- `add_task()`, `start_task()`, `complete_task()` - Task counting
- `print()`, `print_gumball()` - Delegate to InlinePrinter

---

### InlinePrinter (`printer.py`)

Handles scrolling content output with gumball status indicators.

**Methods:**
- `print(content, style)` - Rich Console print
- `print_gumball(status, message)` - Colored status indicator
- `print_streaming_chunk(chunk)` - Raw stdout (avoids Live conflicts)
- `print_thinking(content)` - Collapsed or expanded thinking

**Usage:** Called AFTER Rich.Live exits for final tool results.

---

### SummaryBar (`summary.py`)

Bottom-anchored status bar using Rich.Live.

**Features:**
- 8Hz auto-refresh (smooth spinner animation)
- Pluggable segments via protocol
- `transient=True` - No artifacts

---

### Theme System (`theme.py`)

**Status Enum (Gumballs):**
| Status | Color | Symbol |
|--------|-------|--------|
| ACTIVE | cyan | ● |
| PENDING | dim | ○ |
| COMPLETE | green | ● |
| ERROR | red | ● |
| CANCELLED | yellow | ● |

**Theme Dataclass:**
- `gumballs` - Status → Rich markup mapping
- `spinner_frames` - `"⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"`
- `thinking`, `response`, `error` styles

---

## Display Flows

### 1. User Input
**Library:** prompt_toolkit PromptSession

```python
prompt_session = PromptSession(
    lexer=lexer,
    bottom_toolbar=get_toolbar,  # Token usage display
    style=style,
)
user_input = await prompt_session.prompt_async(...)
```

- Bottom toolbar shows: `{used:,} / {budget:,}` tokens
- The green `● ready` gumball is rendered by **prompt_toolkit's bottom_toolbar**, not as normal terminal content
- During agent turns (when prompt_toolkit is not running), that toolbar is not "sitting there" as terminal content
- Happens AFTER Rich.Live exits (no conflict)

---

### 2. Chat Message Streaming

```
User sends message
  ├─ REPL creates StreamingDisplay
  ├─ Rich.Live(StreamingDisplay, transient=False) starts
  │
  │  [Stream loop]
  │  ├─ Session.send() yields ContentDelta chunks
  │  ├─ StreamingDisplay.add_chunk() accumulates
  │  ├─ Live.refresh() at 10Hz
  │  └─ Spinner animates, content shows (truncated to 20 lines)
  │
  ├─ Turn ends
  ├─ Live exits (final TRUNCATED render persists)
  └─ Full content NOT printed to scrollback
```

**Content Truncation:**
- `MAX_DISPLAY_LINES = 20`
- Shows last 20 lines during streaming
- **IMPORTANT:** Full content is NOT available in scrollback after - only the truncated view persists

---

### 3. Tool Status (Gumballs)

**Callback Flow:**
```
ToolBatchStarted → display.start_batch([tools])
  └─ All tools set to PENDING

ToolStarted → display.set_tool_active(tool_id)
  └─ Tool set to ACTIVE

ToolCompleted → display.set_tool_complete(tool_id, success, error)
  └─ Tool set to SUCCESS or ERROR

ToolBatchHalted → display.halt_remaining_tools()
  └─ All PENDING tools → HALTED
```

**After Live Exits:**
A helper `print_tools_to_scrollback()` exists in repl.py, but **it is never called**. The REPL does NOT print tool call/result lines to scrollback after the Live block.

---

### 4. Slash Commands

**Not through Live display** - Direct console output.

```python
if user_input.startswith("/"):
    result = await handle_slash_command(user_input)
    if result.message:
        console.print(result.message)
```

**Styles:**
- Errors: `[red]...[/]`
- Status: `[dim]...[/]`
- Whisper mode: Box drawing characters `┌──`, `└──` (implemented in REPL loop)

---

### 5. Interactive Menus (Lobby)

**Library:** Rich Console

```python
async def show_lobby(session_manager, console):
    console.print("[bold]NEXUS3 REPL[/]")

    # Options like "  1) ..." and prompts with "[1/2/3/q]:"
    for i, (label, _) in enumerate(options):
        console.print(f"  {i+1}) {label}")

    choice = console.input("Enter choice: ")
```

- Blocking operation before REPL loop
- Direct console I/O, no Live display

---

### 6. Permission Prompts

**Pause/Resume Protocol:**

```python
# In confirmation_ui.py
live = _current_live.get()  # Get Live from ContextVar
if live:
    live.stop()  # Pause Live display

# Show permission prompt
console.print(f"[yellow]Allow {tool_name}?[/]")
console.print("  [1] Allow once")
console.print("  [2] Allow always")
# ...
response = await asyncio.to_thread(get_input)

if live:
    live.start()  # Resume Live display
```

**ContextVar for Live Reference:**
```python
# In live_state.py
_current_live: ContextVar[Live | None] = ContextVar("current_live", default=None)

# In repl.py
with Live(display, ...) as live:
    token = _current_live.set(live)
    try:
        # ... streaming ...
    finally:
        _current_live.reset(token)
```

---

### 7. Spinner/Progress

**Animation Frames:** `"⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"` (Braille)

**Timing:**
- Activity timer shows after 1+ second
- Tool timers show after 3+ seconds

---

### 8. Incoming RPC Messages

**Flow:**
```
Dispatcher._notify_incoming({"phase": "started", ...})
  ├─ Interrupt prompt: prompt_session.app.exit(SENTINEL)
  ├─ Print: "▶ INCOMING from worker-1: ..."
  ├─ Start spinner (separate StreamingDisplay, transient=True)
  └─ Wait for processing

Dispatcher._notify_incoming({"phase": "ended", ...})
  ├─ Stop spinner
  └─ Print: "✓ Response sent: ..."
```

---

## Event System

### SessionEvents (`nexus3/session/events.py`)

| Event | Data | Display Action |
|-------|------|----------------|
| `ContentChunk` | text | Append to response |
| `ReasoningStarted` | - | Set activity THINKING |
| `ReasoningEnded` | - | Set activity RESPONDING |
| `ToolDetected` | name, tool_id | Early detection (optional) |
| `ToolBatchStarted` | tool_calls, parallel | Initialize batch PENDING |
| `ToolStarted` | name, tool_id | Set tool ACTIVE |
| `ToolCompleted` | name, tool_id, success, error, output | Set tool SUCCESS/ERROR |
| `ToolBatchHalted` | - | Mark pending as HALTED |
| `ToolBatchCompleted` | - | Batch finished |
| `IterationCompleted` | - | Loop iteration done |
| `SessionCompleted` | halted_at_limit | Turn complete |
| `SessionCancelled` | - | User cancelled |

### Event Flow

```
Provider.stream()
    ↓ StreamEvent (ContentDelta, ToolCallStarted, etc.)

Session.run_turn()  # Note: run_turn(), not run_turn_events()
    ↓ SessionEvent (ContentChunk, ToolBatchStarted, etc.)

Session callbacks (backward compat)
    ↓ on_batch_start(), on_tool_active(), on_batch_progress()

REPL display callbacks
    ↓ Update StreamingDisplay state

Rich.Live.refresh()
    ↓ Call StreamingDisplay.__rich__()

Terminal output
```

**Note:** The REPL currently uses `Session.send()` (yields `str` chunks) plus legacy callbacks, not the event-based `Session.run_turn()` API directly.

---

## Callback Wiring (`repl.py`)

### Attachment Pattern

```python
def _attach_repl_callbacks(sess):
    sess.on_tool_call = on_tool_call
    sess.on_reasoning = on_reasoning
    sess.on_batch_start = on_batch_start
    sess.on_tool_active = on_tool_active
    sess.on_batch_progress = on_batch_progress
    sess.on_batch_halt = on_batch_halt
    sess.on_batch_complete = on_batch_complete

def _detach_repl_callbacks(sess):
    sess.on_tool_call = None
    sess.on_reasoning = None
    # ... etc

def _set_display_session(new_sess):
    """Switch display callbacks to new session."""
    if _callback_session is not None:
        _detach_repl_callbacks(_callback_session)
    _attach_repl_callbacks(new_sess)
    _callback_session = new_sess
```

**Prevents callback leakage** when switching agents.

---

## State Variables (`repl.py`)

```python
# Display
display = StreamingDisplay(theme)
thinking_printed = False

# Session
current_agent_id: str
session: Session
_callback_session: Session | None

# Whisper
whisper = WhisperMode()

# Incoming RPC
_incoming_turn_active: bool
_incoming_turn_done: asyncio.Event | None
_incoming_spinner_task: Task | None

# Cancellation
was_cancelled: bool

# UI
toolbar_has_errors: bool
_current_live: ContextVar[Live | None]

# Tool results
_nexus_send_results: dict[str, dict]
```

---

## Known Issues

### 1. StreamingDisplay Does Too Much
- Content accumulation
- Tool batch tracking
- Footer rendering
- Activity state
- Timer management

**Result:** Complex `__rich__()` method, hard to modify.

### 2. Truncation Without Full Scrollback
- `MAX_DISPLAY_LINES = 20` truncates during rendering
- With `transient=False`, truncated view persists
- Full response never printed to scrollback

### 3. Tools Not Printed to Scrollback
- `print_tools_to_scrollback()` exists but is never called
- Tool results only visible in Live render, not permanent

### 4. Scattered State
- Activity in DisplayManager (unused)
- Tools in StreamingDisplay
- Segments in SummaryBar (unused)
- Callbacks in REPL closures

### 5. Event-driven Redesign Not Integrated
`state.py`, `reducer.py`, `render.py`, `bridge.py` are:
- Implemented and tested
- NOT wired into `repl.py`
- Had issues (footer padding bug, content teleportation)

---

## Safety Pipeline

### What's Safe
- Streaming content displayed via `StreamingDisplay` is rendered as `Text(...)` (not markup)
- ANSI escapes are stripped via `strip_terminal_escapes()`

### What Needs Attention
- Some REPL `console.print(f"... [red dim]{error_preview}[/]")` paths include **unescaped** interpolated text inside Rich markup
- If interpolated string contains `[` / `]` sequences, can cause **Rich markup injection** (formatting corruption, potentially clickable links)
- Tool params are escaped via `format_tool_params()` (good)
- Error previews are NOT consistently escaped (risk)

**Recommendation:** Use `escape_rich_markup()` for any text interpolated inside markup strings.

---

## What Works Well

1. **Gumball State Machine** - Clean transitions, clear visual feedback
2. **Escape Stripping** - Terminal escape removal works
3. **Callback Protocol** - Simple function pointers, easy to wire
4. **Permission Pause/Resume** - ContextVar approach works
5. **Theme System** - Centralized styling

---

## Files in REPL Display Integration

| File | Role |
|------|------|
| `nexus3/cli/repl.py` | Main REPL loop, callback wiring, streaming orchestration (~1864 lines) |
| `nexus3/cli/repl_commands.py` | Slash command implementations |
| `nexus3/cli/lobby.py` | Session selection menu |
| `nexus3/cli/connect_lobby.py` | Server/agent selection |
| `nexus3/cli/confirmation_ui.py` | Permission prompt UI |
| `nexus3/cli/keys.py` | KeyMonitor for ESC handling |
| `nexus3/cli/live_state.py` | ContextVar for Live reference |
| `nexus3/display/*.py` | Display components |
| `nexus3/session/events.py` | SessionEvent types |
| `nexus3/session/session.py` | Event emission, callback invocation |
