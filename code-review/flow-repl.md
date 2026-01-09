# REPL Flow Code Review

## Executive Summary

The NEXUS3 REPL flow is well-structured with clear separation of concerns. The data flows from user input through session coordination to provider streaming and back to display. However, there are several issues around cancellation handling, state management, and potential race conditions that warrant attention.

---

## Flow Diagram

```
                                    REPL Flow
                                    =========

User Input
    |
    v
+-------------------+
|  repl.py          |  prompt_toolkit PromptSession
|  run_repl()       |
+-------------------+
    |
    | parse_command() -> handles /quit, /exit, etc.
    |
    v (if not command)
+-------------------+
|  StreamingDisplay |  reset(), clear_error_state()
|  (streaming.py)   |  set_activity(WAITING)
+-------------------+
    |
    v
+-------------------+     +-------------------+
|  KeyMonitor       | --> |  on_cancel()      |
|  (keys.py)        |     |  ESC detection    |
+-------------------+     +-------------------+
    |                           |
    | asyncio.create_task       | task.cancel()
    v                           v
+-------------------+
|  do_stream()      |  session.send(user_input)
+-------------------+
    |
    v
+-------------------+
|  session.py       |  Session.send()
|  Session          |
+-------------------+
    |
    | _flush_cancelled_tools()
    | context.add_user_message()
    |
    v
+-------------------+
|  _execute_tool_   |  Tool execution loop
|  loop_streaming() |  max 10 iterations
+-------------------+
    |
    | context.build_messages()
    |
    v
+-------------------+
|  manager.py       |  ContextManager
|  ContextManager   |  build_messages()
+-------------------+
    |
    | truncation if over budget
    |
    v
+-------------------+
|  openrouter.py    |  provider.stream()
|  OpenRouter       |  SSE parsing
|  Provider         |
+-------------------+
    |
    | yields StreamEvent subclasses:
    | - ReasoningDelta
    | - ContentDelta
    | - ToolCallStarted
    | - StreamComplete
    |
    v
+-------------------+
|  Session          |  Handle events:
|  Event Handler    |  - Yield content chunks
+-------------------+  - Call on_tool_call callback
    |                  - Execute tools on StreamComplete
    |
    v (tool calls present)
+-------------------+
|  Tool Execution   |  Sequential or Parallel
|  _execute_single_ |  Callbacks: on_batch_start,
|  tool()           |  on_tool_active, on_batch_progress
+-------------------+
    |
    | context.add_tool_result()
    |
    v (loop back to provider.stream if more tool calls)
    |
    v (no more tool calls)
+-------------------+
|  StreamingDisplay |  display.add_chunk()
|  Rich.Live        |  Render in Live context
+-------------------+
    |
    v (Live context exits)
+-------------------+
|  Final Output     |  console.print(display.response)
|  To Scrollback    |  Thinking duration
+-------------------+  Tool batch results
```

---

## Detailed Analysis

### 1. Data Flow Clarity and Correctness

**Strengths:**
- Clear separation between REPL (`repl.py`), session (`session.py`), display (`streaming.py`), and provider (`openrouter.py`)
- Well-typed event system with `StreamEvent` hierarchy
- Context management properly builds message history

**Issues:**

#### Issue 1.1: Implicit Tool Mode Selection (Medium)
**Location:** `/home/inc/repos/NEXUS3/nexus3/session/session.py` lines 149-155

```python
# Check if we should use tool mode
has_tools = self.registry and self.registry.get_definitions()
if use_tools or has_tools:
    # Use streaming tool execution loop
    async for chunk in self._execute_tool_loop_streaming(cancel_token):
        yield chunk
    return
```

The `use_tools` parameter defaults to `False`, but if `registry` has tools, it automatically enables the tool loop. This implicit behavior can be confusing. The function signature suggests explicit control, but the implementation overrides it.

**Recommendation:** Either remove the `use_tools` parameter entirely (always use tools when available) or make the behavior explicit and document it clearly.

#### Issue 1.2: Messages Not Built in Tool Loop Context Branch
**Location:** `/home/inc/repos/NEXUS3/nexus3/session/session.py` lines 157-164

When the tool loop is used (lines 151-155), the code returns early. The `messages` and `tools` variables at lines 157-158 are only used when `context` exists but no tools are present. This is technically correct but the flow is confusing.

---

### 2. Error Propagation

**Strengths:**
- Consistent use of `NexusError` hierarchy
- Provider errors are well-typed (`ProviderError` for API issues)
- Tool execution errors are captured in `ToolResult.error`

**Issues:**

#### Issue 2.1: Silent Exception Swallowing in Parallel Tool Execution (High)
**Location:** `/home/inc/repos/NEXUS3/nexus3/session/session.py` lines 376-388

```python
results = await asyncio.gather(
    *[execute_one(tc) for tc in tool_calls],
    return_exceptions=True,
)

# Convert exceptions to ToolResults
final_results: list[ToolResult] = []
for r in results:
    if isinstance(r, Exception):
        final_results.append(ToolResult(error=f"Execution error: {r}"))
    else:
        final_results.append(r)
```

While this pattern is correct for `asyncio.gather`, the error message loses the stack trace. For debugging, the full traceback should be logged before converting to `ToolResult`.

#### Issue 2.2: NexusError Caught but Not Re-raised in REPL
**Location:** `/home/inc/repos/NEXUS3/nexus3/cli/repl.py` lines 383-387

```python
except NexusError as e:
    console.print(f"[red]Error:[/] {e.message}")
    console.print("")  # Visual separation after error
    display.mark_error()
```

This catches `NexusError` inside the `Live` context and prints it, but does not properly propagate it or provide any mechanism for recovery. The loop continues, but the user message was already added to context, potentially leaving context in an inconsistent state.

#### Issue 2.3: JSON Decode Errors Silently Skipped
**Location:** `/home/inc/repos/NEXUS3/nexus3/provider/openrouter.py` lines 398-400, 423-424

```python
except json.JSONDecodeError:
    # Skip malformed JSON in stream
    continue
```

Malformed JSON in the stream is silently ignored. While this may be intentional for robustness, it could mask underlying API issues. At minimum, this should log a warning if verbose mode is enabled.

---

### 3. Cancellation Handling

**Strengths:**
- `KeyMonitor` provides clean ESC key detection
- `CancellationToken` pattern is used
- Tools can be marked as cancelled

**Issues:**

#### Issue 3.1: Cancellation Token Not Passed to REPL Session (High)
**Location:** `/home/inc/repos/NEXUS3/nexus3/cli/repl.py` lines 359-366

```python
async def do_stream(
    d: StreamingDisplay = display,
    inp: str = user_input,
) -> None:
    async for chunk in session.send(inp):
        if d.activity == Activity.WAITING:
            d.set_activity(Activity.RESPONDING)
        d.add_chunk(chunk)
```

The `session.send()` method accepts a `cancel_token` parameter, but it is never passed from the REPL. The cancellation works by `task.cancel()` on the `stream_task`, which is a cruder approach. The `cancel_token` mechanism inside `session.send()` would provide more graceful cancellation.

**Current cancellation flow:**
1. ESC pressed -> `on_cancel()` called
2. `stream_task.cancel()` called
3. `CancelledError` propagates up

**Better approach:**
1. Pass a `CancellationToken` to `session.send()`
2. Check token in the tool loop
3. Gracefully exit without raising exceptions

#### Issue 3.2: Race Condition in Cancel Callback
**Location:** `/home/inc/repos/NEXUS3/nexus3/cli/repl.py` lines 348-357

```python
def on_cancel(
    d: StreamingDisplay = display,
    get_task: object = lambda: stream_task,
) -> None:
    nonlocal was_cancelled
    was_cancelled = True
    d.cancel_all_tools()
    task = get_task()  # type: ignore[operator]
    if task is not None:
        task.cancel()
```

There is a race condition: `stream_task` is assigned on line 372 **after** `KeyMonitor` starts on line 371. If the user presses ESC very quickly, `get_task()` might return `None` because `stream_task` hasn't been assigned yet.

**Recommendation:** Initialize `stream_task` to a dummy/sentinel value or use a lock.

#### Issue 3.3: Cancelled Tools Not Consistently Handled
**Location:** `/home/inc/repos/NEXUS3/nexus3/cli/repl.py` lines 393-403

```python
if was_cancelled and display.get_batch_results():
    cancelled_tools = [
        (tool.tool_id, tool.name)
        for tool in display.get_batch_results()
        if tool.state == ToolState.CANCELLED
    ]
    if cancelled_tools:
        session.add_cancelled_tools(cancelled_tools)

    on_batch_complete()
```

This only handles tools that were tracked in `display`. If cancellation happens during streaming (before tool execution starts), tools detected via `ToolCallStarted` events but not yet in a batch won't be tracked.

---

### 4. State Management

**Strengths:**
- `StreamingDisplay` has clear reset mechanisms
- Context manager maintains message history cleanly
- Session callbacks provide good hooks for state updates

**Issues:**

#### Issue 4.1: Duplicate State Tracking Between REPL and Display (Medium)
**Location:** `/home/inc/repos/NEXUS3/nexus3/cli/repl.py` lines 185-205 and streaming.py

The REPL tracks `thinking_printed` and `toolbar_has_errors` locally, while `StreamingDisplay` also tracks `_had_errors` and `_thinking_duration`. This duplication can lead to inconsistencies.

```python
# In repl.py
thinking_printed = False
toolbar_has_errors = False

# In StreamingDisplay
self._had_errors = False
self._thinking_duration = 0.0
```

**Recommendation:** Centralize all display state in `StreamingDisplay` and let REPL query it.

#### Issue 4.2: DisplayManager Not Used in REPL
**Location:** `/home/inc/repos/NEXUS3/nexus3/display/manager.py`

There is a `DisplayManager` class that appears to be designed for coordinating display, but the REPL uses `StreamingDisplay` directly. This suggests either:
- `DisplayManager` is legacy/unused code
- The REPL should be refactored to use `DisplayManager`

This inconsistency makes the codebase harder to understand.

#### Issue 4.3: Activity State Transitions Not Validated
**Location:** `/home/inc/repos/NEXUS3/nexus3/display/streaming.py` lines 203-210

```python
def set_activity(self, activity: Activity) -> None:
    """Update the current activity state."""
    self.activity = activity
    if activity == Activity.IDLE:
        self._frame = 0
    elif activity in (Activity.WAITING, Activity.RESPONDING, Activity.THINKING, Activity.TOOL_CALLING):
        if self._activity_start_time == 0:
            self._activity_start_time = time.time()
```

Activity transitions are not validated. Invalid transitions (e.g., IDLE -> TOOL_CALLING without WAITING first) are silently accepted. This could lead to confusing timer behavior.

---

### 5. Edge Cases

#### Issue 5.1: Max Iterations Reached Message Not Displayed Properly
**Location:** `/home/inc/repos/NEXUS3/nexus3/session/session.py` line 337

```python
# Max iterations reached
yield "[Max tool iterations reached]"
```

This message is yielded as content but will appear inline with the response. It should be handled specially (e.g., as an error or warning).

#### Issue 5.2: Empty Tool Arguments Parsing
**Location:** `/home/inc/repos/NEXUS3/nexus3/provider/openrouter.py` lines 159-161, 512-514

```python
try:
    arguments = json.loads(arguments_str)
except json.JSONDecodeError:
    arguments = {}
```

Invalid JSON in tool arguments is silently converted to an empty dict. This could cause tools to fail in unexpected ways downstream.

#### Issue 5.3: Terminal Settings Not Restored on Crash
**Location:** `/home/inc/repos/NEXUS3/nexus3/cli/keys.py` lines 36-53

```python
old_settings = termios.tcgetattr(sys.stdin)
try:
    tty.setcbreak(sys.stdin.fileno())
    # ... monitoring loop
finally:
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
```

If the process is killed (SIGKILL) or crashes hard, terminal settings may not be restored. This is a known issue with terminal manipulation but worth noting.

#### Issue 5.4: Truncation Can Break Tool Call Sequences
**Location:** `/home/inc/repos/NEXUS3/nexus3/context/manager.py` lines 245-270

The `_truncate_oldest_first` method removes old messages to fit the token budget. However, if a tool call message is kept but its corresponding tool result is truncated (or vice versa), the API will likely fail.

```python
# This could result in:
# [assistant message with tool_call X]
# [user message]  <- tool result for X was truncated!
```

**Recommendation:** Truncation should preserve tool call/result pairs atomically.

---

### 6. Potential Bugs and Race Conditions

#### Issue 6.1: Live Refresh Loop Race with Task Completion
**Location:** `/home/inc/repos/NEXUS3/nexus3/cli/repl.py` lines 374-381

```python
while not stream_task.done():
    live.refresh()
    await asyncio.sleep(0.1)
# Get any exception from the task
try:
    stream_task.result()
except asyncio.CancelledError:
    pass  # Cancelled by ESC
```

The check `stream_task.done()` and `stream_task.result()` are not atomic. Between checking `done()` and calling `result()`, the task state could theoretically change. In practice this is unlikely with Python's GIL, but it's worth noting.

#### Issue 6.2: Callback Closure Over Mutable State
**Location:** `/home/inc/repos/NEXUS3/nexus3/cli/repl.py` lines 181-206

```python
def on_tool_call(name: str, tool_id: str) -> None:
    display.add_tool_call(name, tool_id)

# Track if we've printed thinking for this turn
thinking_printed = False

def print_thinking_if_needed() -> None:
    nonlocal thinking_printed
    if thinking_printed:
        return
    # ...
```

Multiple callbacks close over `display`, `thinking_printed`, and `console`. If these callbacks are ever called from different threads (unlikely in current code but possible with future changes), race conditions could occur.

#### Issue 6.3: tool_calls_by_index Not Thread-Safe
**Location:** `/home/inc/repos/NEXUS3/nexus3/provider/openrouter.py` lines 350-351, 469-491

The `tool_calls_by_index` dict and `seen_tool_indices` set are modified during async iteration. While Python dicts are thread-safe for simple operations, the compound check-and-update pattern is not:

```python
if index not in tool_calls_by_index:
    tool_calls_by_index[index] = {"id": "", "name": "", "arguments": ""}

acc = tool_calls_by_index[index]
# ... modify acc ...
```

This is currently safe because it all runs in a single async context, but it's fragile.

---

## Summary of Issues by Severity

### High Priority
1. **Issue 3.1:** Cancellation token not passed to session
2. **Issue 3.2:** Race condition in cancel callback
3. **Issue 2.1:** Silent exception swallowing loses stack traces

### Medium Priority
4. **Issue 1.1:** Implicit tool mode selection
5. **Issue 4.1:** Duplicate state tracking
6. **Issue 5.4:** Truncation can break tool call sequences
7. **Issue 4.2:** DisplayManager not used (code smell)

### Low Priority
8. **Issue 2.2:** NexusError caught but not re-raised properly
9. **Issue 2.3:** JSON decode errors silently skipped
10. **Issue 4.3:** Activity state transitions not validated
11. **Issue 5.1:** Max iterations message not handled specially
12. **Issue 5.2:** Empty tool arguments parsing
13. **Issue 5.3:** Terminal settings not restored on crash
14. **Issue 6.1:** Non-atomic task state check
15. **Issue 6.2:** Callbacks close over mutable state
16. **Issue 6.3:** Compound check-and-update not thread-safe

---

## Recommendations

### Immediate Actions
1. Pass `CancellationToken` to `session.send()` from REPL for graceful cancellation
2. Initialize `stream_task` before entering `KeyMonitor` context
3. Add logging for exceptions before converting to `ToolResult`

### Short-term Improvements
1. Refactor state tracking to be centralized in `StreamingDisplay`
2. Validate activity state transitions
3. Implement atomic truncation for tool call/result pairs

### Long-term Considerations
1. Decide on `DisplayManager` vs direct `StreamingDisplay` usage
2. Add comprehensive integration tests for cancellation scenarios
3. Consider using a proper state machine for activity transitions

---

## Files Reviewed

| File | Lines | Purpose |
|------|-------|---------|
| `/home/inc/repos/NEXUS3/nexus3/cli/repl.py` | 615 | REPL entry point, input handling, display coordination |
| `/home/inc/repos/NEXUS3/nexus3/session/session.py` | 390 | Session coordinator, tool execution loop |
| `/home/inc/repos/NEXUS3/nexus3/provider/openrouter.py` | 531 | API calls, SSE parsing, streaming |
| `/home/inc/repos/NEXUS3/nexus3/context/manager.py` | 312 | Context building, token tracking, truncation |
| `/home/inc/repos/NEXUS3/nexus3/display/streaming.py` | 373 | Streaming display with Rich.Live |
| `/home/inc/repos/NEXUS3/nexus3/display/manager.py` | 171 | Display manager (unused in REPL) |
| `/home/inc/repos/NEXUS3/nexus3/cli/keys.py` | 93 | ESC key detection |
| `/home/inc/repos/NEXUS3/nexus3/core/types.py` | 138 | Core type definitions |
| `/home/inc/repos/NEXUS3/nexus3/core/errors.py` | 18 | Error hierarchy |

---

*Review conducted: 2026-01-08*
*Reviewer: Code Review Agent*
