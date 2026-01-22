# NEXUS3 Display System Simplification Plan

## Intent

Simplify the REPL display system by removing dynamic content areas and replacing with a single pinned spinner. All content (text, tool calls, results) prints directly to scrollback.

---

## Design Decisions

### During Agent Turn
- **Single dynamic element**: Spinner pinned to bottom (agent-turn-only Live footer, not "replacing" a static terminal line)
- **Everything else**: Prints via `spinner.print()` which delegates to `live.console.print()` to appear above the spinner

### Text Streaming
- **CRITICAL**: Cannot mix raw `sys.stdout.write` with active `Rich.Live` - will corrupt display
- Stream via `spinner.print(chunk, end="")` or `spinner.print_streaming(chunk)` which routes through Live console
- Sanitize with `strip_terminal_escapes()` before printing
- Use `markup=False, highlight=False` to prevent Rich markup interpretation of model output

### Tool Display
- **Line 1**: Tool call with params (prints when tool starts via `spinner.print()`)
- **Line 2**: Tool result with duration (prints when tool completes)
- Both lines are permanent scrollback, printed above the spinner

### Thinking Display
- While thinking: Spinner shows "Thinking..."
- Track duration manually: `_thinking_start = time.monotonic()` on start, accumulate on end
- When complete: Print `● Thinking (5s)` to scrollback BEFORE tool calls

### Cancellation
- Print what was cancelled: `● Cancelled: <tool_name>` or `● Cancelled: streaming`
- **CRITICAL**: Must preserve `Session.add_cancelled_tools()` bookkeeping
- Track active tools in `_active_tools: dict[str, str]` (tool_id → tool_name)

### Timers
- Per-tool: Track `_tool_start_times[tool_id] = time.monotonic()` in `on_tool_active`
- Compute duration in `on_batch_progress` when tool completes
- Turn total: Print at end `Turn completed in 12s`

### Keep As-Is
- Token usage in prompt_toolkit bottom toolbar
- Permission prompts (pause spinner via `spinner.live.stop()`, show prompt, resume via `spinner.live.start()`)
- Interactive menus (lobby, connect)
- Whisper box drawing
- Error state tracking for prompt toolbar (`● ready (some tasks incomplete)`)

---

## Architecture

### Remove
- `StreamingDisplay` class (418 lines) - no more dynamic content area
- `SummaryBar` class (115 lines) - replaced by simple spinner
- `DisplayManager` task counting - not needed
- `segments.py` (123 lines) - no more pluggable segments
- Experimental files: `state.py`, `reducer.py`, `render.py`, `bridge.py`

**Test Impact**: Deleting these modules breaks existing tests:
- `tests/unit/display/test_state.py`
- `tests/unit/display/test_reducer.py`
- `tests/unit/display/test_render.py`
- `tests/unit/test_display.py`

Must either rewrite tests or accept breaking changes and update all imports/tests in one PR.

### New Components

#### `Spinner` (simple)
```python
class Spinner:
    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, console: Console):
        self.console = console
        self.text = ""
        self._live: Live | None = None

    def show(self, text: str = ""):
        """Show spinner with optional text."""
        self.text = text
        # Start Rich.Live with:
        # - transient=True (don't leave in scrollback)
        # - redirect_stdout=True, redirect_stderr=True (route output above)
        # - Single-line render (no_wrap=True, overflow="crop")

    def update(self, text: str):
        """Update spinner text."""
        self.text = text

    def hide(self):
        """Hide spinner."""
        # Stop Rich.Live

    def print(self, *args, **kwargs):
        """Print above spinner via live.console.print()."""
        if self._live:
            self._live.console.print(*args, **kwargs)
        else:
            self.console.print(*args, **kwargs)

    def print_streaming(self, chunk: str):
        """Print streaming chunk (sanitized, no markup)."""
        sanitized = strip_terminal_escapes(chunk)
        if sanitized:
            self.print(sanitized, end="", markup=False, highlight=False)
            self.console.file.flush()  # Immediate display

    @property
    def live(self) -> Live | None:
        """For permission prompt pause/resume."""
        return self._live
```

#### Display Flow

```
User Turn:
  [scrollback content]
  ● ready                    ← prompt_toolkit bottom_toolbar (not terminal content)

Agent Turn:
  [scrollback content]
  [streaming text via spinner.print_streaming()]
  ⠋ Thinking... (5s)         ← spinner (Rich.Live, single line, transient)

Tool Execution:
  [scrollback content]
  ● read_file: src/main.py   ← printed via spinner.print() when tool starts
  ⠋ Running: read_file (3s)  ← spinner updates

Tool Complete:
  [scrollback content]
  ● read_file: src/main.py
      → 42 lines (0.3s)      ← printed via spinner.print() when tool completes
  ⠋ Running tools...         ← spinner continues or hides

Turn Complete:
  [scrollback content]
  [full response text]
  ● Thinking (2s)            ← if thinking occurred
  ● read_file: src/main.py
      → 42 lines (0.3s)
  Turn completed in 5s
  ● ready                    ← back to prompt_toolkit toolbar
```

---

## Implementation Steps

### Phase 1: Core Simplification
1. Create new `Spinner` class with:
   - `redirect_stdout=True, redirect_stderr=True` on Live
   - `no_wrap=True, overflow="crop"` on render
   - `print()` method routing through `live.console.print()`
   - `print_streaming()` with sanitization and `markup=False`
2. Expose `spinner.live` property for permission prompt integration

### Phase 2: REPL Integration
3. Replace `StreamingDisplay` with `Spinner` in imports
4. Add turn state tracking:
   - `_tool_start_times: dict[str, float]` - for duration calculation
   - `_active_tools: dict[str, str]` - for cancellation bookkeeping
   - `_pending_tools: dict[str, tuple[str, str]]` - for halt display
   - `_thinking_start: float | None` and `_thinking_total: float`
   - `_had_errors: bool` - for toolbar state
5. Modify streaming loop:
   - Show spinner when turn starts
   - Stream text via `spinner.print_streaming(chunk)`
   - Update spinner text for activity changes
   - Hide spinner when turn ends
6. Modify tool callbacks:
   - `on_batch_start`: Print thinking if needed, track tools as pending
   - `on_tool_active`: Print tool call line, record start time, track in active
   - `on_batch_progress`: Print result line with duration, remove from active
   - `on_batch_halt`: Print halted line for remaining pending tools
7. Add turn timer, print at end

### Phase 3: Edge Cases
8. Cancellation: Collect `(tool_id, tool_name)` from `_active_tools` and call `session.add_cancelled_tools()`
9. Permission prompt integration: `confirmation_ui.py` uses `spinner.live.stop()` / `spinner.live.start()`
10. Incoming RPC: Refactor `_run_incoming_spinner()` to use `Spinner` class
11. Error state: Track `_had_errors` for prompt toolbar

### Phase 4: Cleanup
12. Remove unused components (StreamingDisplay, SummaryBar, segments)
13. Remove experimental files (state.py, reducer.py, render.py, bridge.py)
14. Update/rewrite tests

---

## Files to Modify

| File | Change |
|------|--------|
| `nexus3/display/spinner.py` | NEW - Simple spinner component |
| `nexus3/display/__init__.py` | Update exports (add Spinner) |
| `nexus3/cli/repl.py` | New streaming loop, callback changes, state tracking |
| `nexus3/cli/confirmation_ui.py` | Use `spinner.live` for pause/resume |

## Files to Delete

- `nexus3/display/streaming.py`
- `nexus3/display/summary.py`
- `nexus3/display/segments.py`
- `nexus3/display/state.py`
- `nexus3/display/reducer.py`
- `nexus3/display/render.py`
- `nexus3/display/bridge.py`

---

## Security Requirements

- **ANSI escape stripping**: Use `strip_terminal_escapes()` on all streamed model output
- **Rich markup escaping**: Use `escape_rich_markup()` for any text interpolated inside markup strings (e.g., tool error previews in `[red]...[/]`)

---

## Special Handling

### nexus_send Response Preview
Keep special formatting for `nexus_send` results:
```python
if name == "nexus_send" and output:
    parsed = json.loads(output)
    content = parsed.get("content", "")
    preview = " ".join(content.split())[:100]
    spinner.print(f"      [dim cyan]↳ Response: {preview}...[/]")
```

---

## Verification

1. **Manual test**: Start REPL, send message, verify:
   - Spinner shows during response
   - Text streams to scrollback (not blank!)
   - Tool calls show call + result lines (correct order!)
   - No spinner artifacts in scrollback

2. **Permission test**: Trigger a permission prompt, verify:
   - Spinner pauses
   - Prompt displays correctly
   - Spinner resumes after response

3. **Cancellation test**: Press ESC during:
   - Streaming → "Cancelled: streaming"
   - Tool execution → "Cancelled: tool_name"
   - Verify `session.add_cancelled_tools()` called

4. **Incoming RPC test**: Send message from another agent, verify display

5. **Error state test**: Cause a tool error, verify toolbar shows "(some tasks incomplete)"

6. **Run existing tests**: Update and run `pytest tests/unit/display/`
