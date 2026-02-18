# Plan: Empty Stream Response Fix + Diagnostic Logging

## Context

User encountered blank responses and cascading 400 errors on a corporate OpenAI-compatible endpoint (`devstral-small` via `api.ai.us.lmco.com`). Root cause: the server returned 200 OK with SSE headers but an empty stream body (no content events, no `[DONE]` marker). The client saved `Message(content="")` to history, and the next API call was rejected with 400 because empty assistant messages are invalid.

The `GeneratorExit` in the httpcore logs is a cleanup artifact — httpcore's internal body-reading generator gets GC'd when the response closes after the empty `aiter_text()` loop finishes. Not the root cause, but there's zero logging in the streaming path so it was impossible to tell.

**Three problems to fix:**
1. No diagnostic logging in the streaming path — impossible to debug
2. No guard against empty assistant messages — cascading failure
3. Additional vectors for the same bug (non-streaming, session restore, message serialization)

## Validation Notes

Plan validated by 3 subagents. Key corrections applied:
- **LogMultiplexer** (`rpc/log_multiplexer.py`) also implements `RawLogCallback` — must add `on_stream_complete()` there too
- **Non-streaming path** (`_parse_response()` in both providers) has the same empty-content vulnerability
- **Session restore** (`persistence.py:deserialize_message()`) loads empty messages without validation — resuming a bugged session re-triggers the 400
- **Anthropic `_convert_messages()`** — empty assistant message becomes `{"role": "assistant", "content": []}` which Anthropic API rejects
- `context/manager.py` has **no logger** — needs `import logging` + `logger = logging.getLogger(__name__)`
- `finish_reason` / `stop_reason` is present in streaming chunks but never extracted or logged

## Files to Modify

| File | Change |
|------|--------|
| `nexus3/provider/openai_compat.py` | Logging + raw summary in `_parse_stream()` (lines 260-348) |
| `nexus3/provider/anthropic.py` | Same treatment in `_parse_stream()` (lines 332-479) |
| `nexus3/context/manager.py` | Guard in `add_assistant_message()` (line 380) |
| `nexus3/session/session.py` | User-visible warning at 3 call sites (lines 305, 381, 624) |
| `nexus3/session/persistence.py` | Filter empty assistant messages on restore (line 201) |
| `nexus3/core/interfaces.py` | Add `on_stream_complete()` to `RawLogCallback` (line 14) |
| `nexus3/session/markdown.py` | Add `write_stream_complete()` to `RawWriter` (line 232) |
| `nexus3/session/logging.py` | Adapter + SessionLogger plumbing (line 392) |
| `nexus3/rpc/log_multiplexer.py` | Add `on_stream_complete()` forwarding (line 140) |

## Phase 1: Diagnostic Logging in `_parse_stream()`

**Both `openai_compat.py:260-348` and `anthropic.py:332-479` get the same treatment.**

Add to `_parse_stream()`:
- `event_count = 0` counter, incremented on each parsed SSE data event
- `received_done = False` flag (or `received_message_stop` for Anthropic)
- `finish_reason: str | None = None` — extracted from the last streaming chunk
- `stream_start = time.monotonic()` for duration tracking
- On normal completion (`[DONE]`/`message_stop`): `logger.debug()` with event count, content length, tool call count, finish_reason, duration_ms
- On fallthrough (no end marker): same debug log noting "ended without [DONE]", finish_reason=None
- When content AND tool calls are both empty: `logger.warning("Empty stream response: ...")`
- Call `self._raw_log.on_stream_complete(summary_dict)` if raw logging active (writes `type: stream_complete` entry to `raw.jsonl`)

Summary dict includes: `http_status`, `event_count`, `content_length`, `tool_call_count`, `received_done`, `finish_reason`, `duration_ms`. The `http_status` is available from `response.status_code` in `_parse_stream()`'s scope.

### finish_reason extraction

**OpenAI-compatible** (`_process_stream_event`, line 367): `choices[0].finish_reason` is present on every chunk but only non-null on the final one. Typical values: `"stop"`, `"tool_calls"`, `"length"`, `"content_filter"`. Extract in the existing `_process_stream_event()` method and store on an accumulator variable passed in, or return it alongside events. Simplest approach: extract directly in `_parse_stream()` after calling `_process_stream_event()`:
```python
# After processing events from the chunk
fr = choices[0].get("finish_reason")
if fr:
    finish_reason = fr
```

**Anthropic** (line 386+): `stop_reason` arrives in the `message_delta` event (`data.delta.stop_reason`). This event type is currently documented in the docstring (line 342) but **not handled** in the code. Add a handler:
```python
elif event_type == "message_delta":
    delta = data.get("delta", {})
    sr = delta.get("stop_reason")
    if sr:
        finish_reason = sr
```

Typical Anthropic values: `"end_turn"`, `"tool_use"`, `"max_tokens"`, `"stop_sequence"`.

Both files already have `logger = logging.getLogger(__name__)`.

## Phase 2: Empty Response Guard (Defense in Depth)

### 2a: Context layer — `context/manager.py:380`

`add_assistant_message()` — add at top of method:
```python
if not content and not tool_calls:
    logger.warning("Skipping empty assistant message (no content, no tool calls)")
    return
```

Need to add `import logging` and `logger = logging.getLogger(__name__)` to this file (currently missing).

Tool-only responses (`content=""` + tool_calls present) remain valid.

### 2b: Session restore — `persistence.py:deserialize_message()` (line 201)

When deserializing messages, log a warning and skip any assistant message with empty content and no tool calls. This prevents a bugged session from re-triggering the 400 on resume.

Change return type to `Message | None`:
```python
def deserialize_message(data: dict[str, Any]) -> Message | None:
    ...
    if role == Role.ASSISTANT and not content and not tool_calls:
        logger.warning("Skipping empty assistant message during session restore")
        return None
    ...
```

Update `deserialize_messages()` (line 241) to filter:
```python
def deserialize_messages(data: list[dict[str, Any]]) -> list[Message]:
    return [m for m in (deserialize_message(d) for d in data) if m is not None]
```

No other direct callers of `deserialize_message()` exist outside `deserialize_messages()`.

## Phase 3: Raw Log Streaming Summary

Plumb `on_stream_complete()` through the logging stack so `raw.jsonl` gets a response-side entry for streaming calls:

1. **`core/interfaces.py:14`** — Add `on_stream_complete(summary: dict)` to `RawLogCallback` Protocol
2. **`session/markdown.py:232`** — Add `write_stream_complete()` to `RawWriter` (writes `type: stream_complete` entry)
3. **`session/logging.py:392`** — Add `log_raw_stream_complete()` to `SessionLogger`, add `on_stream_complete()` to `RawLogCallbackAdapter`
4. **`rpc/log_multiplexer.py:140`** — Add `on_stream_complete()` forwarding (same pattern as `on_chunk()`)
5. **Both providers** — Call `self._raw_log.on_stream_complete(...)` at both exit paths of `_parse_stream()`

## Phase 4: User-Visible Warning

**`session/session.py`** — 3 locations where a final response with no tool calls is saved:

1. **`send()` line 305**: If empty response, yield `"[Provider returned an empty response]"` instead of saving
2. **`run_turn()` line 381**: Same, yield `ContentChunk(text="[Provider returned an empty response]")`
3. **`_execute_tool_loop_events()` line 624**: Same treatment in the no-tool-calls else branch

Note: line 470 is the tool_calls branch — if tool calls are present, the message is valid even with empty content. No change needed there.

In all cases, skip the `add_assistant_message()` call (the context guard would catch it anyway, but explicit is better).

### 4b: Consecutive empty response bail-out in `_execute_tool_loop_events()`

If the provider keeps returning empty responses, the tool loop (line 404: `for iteration_num in range(self.max_tool_iterations)`) would iterate up to 10 times, each time yielding the warning and calling the API again. Add a counter:
```python
consecutive_empty = 0  # before the loop
# ... inside the loop, when empty response detected:
consecutive_empty += 1
if consecutive_empty >= 2:
    yield ContentChunk(text="[Stopping: provider returned multiple empty responses in a row]")
    yield SessionCompleted(halted_at_limit=False)
    return
```
Reset the counter to 0 whenever a non-empty response is received.

## Phase 5: Tests

| Test File | What |
|-----------|------|
| `tests/unit/provider/test_empty_stream.py` | Empty stream parsing for both providers, event counting, duration logging |
| `tests/unit/context/test_empty_assistant_guard.py` | Guard blocks empty, allows content-only and tool-only |
| `tests/unit/session/test_empty_response_feedback.py` | Warning yielded to user, not saved to context |
| `tests/unit/session/test_raw_stream_complete.py` | Raw log summary written correctly |
| `tests/unit/session/test_persistence_empty_guard.py` | Empty messages filtered on deserialize |

Then full suite: `.venv/bin/pytest tests/ -v` + `.venv/bin/ruff check nexus3/`

## Implementation Checklist

### Phase 1: Diagnostic Logging (P1a and P1b can parallel)
- [ ] **P1a** Add event counting, timing, debug/warning logging to `openai_compat.py:_parse_stream()` (lines 260-348)
- [ ] **P1b** Add event counting, timing, debug/warning logging to `anthropic.py:_parse_stream()` (lines 332-479)

### Phase 2: Empty Response Guard
- [ ] **P2.1** Add `import logging` + logger + guard to `context/manager.py:add_assistant_message()` (line 380)
- [ ] **P2.2** Change `persistence.py:deserialize_message()` return type to `Message | None`, add filter (line 201)
- [ ] **P2.3** Update `persistence.py:deserialize_messages()` to filter None results (line 241)

### Phase 3: Raw Log Streaming Summary (after P1)
- [ ] **P3.1** Add `on_stream_complete()` to `RawLogCallback` Protocol in `core/interfaces.py`
- [ ] **P3.2** Add `write_stream_complete()` to `RawWriter` in `session/markdown.py`
- [ ] **P3.3** Add `log_raw_stream_complete()` to `SessionLogger` + `on_stream_complete()` to `RawLogCallbackAdapter` in `session/logging.py`
- [ ] **P3.4** Add `on_stream_complete()` to `LogMultiplexer` in `rpc/log_multiplexer.py`
- [ ] **P3.5** Call `on_stream_complete()` in `openai_compat.py` at both exit paths
- [ ] **P3.6** Call `on_stream_complete()` in `anthropic.py` at both exit paths

### Phase 4: User-Visible Warning (after P2)
- [ ] **P4.1** Guard + warning in `session.py:send()` (line 305)
- [ ] **P4.2** Guard + warning in `session.py:run_turn()` (line 381)
- [ ] **P4.3** Guard + warning in `session.py:_execute_tool_loop_events()` (line 624)
- [ ] **P4.4** Consecutive empty response bail-out counter in `_execute_tool_loop_events()` (line 404 loop)

### Phase 5: Tests (after P1-P4)
- [ ] **P5.1** `tests/unit/provider/test_empty_stream.py`
- [ ] **P5.2** `tests/unit/context/test_empty_assistant_guard.py`
- [ ] **P5.3** `tests/unit/session/test_empty_response_feedback.py`
- [ ] **P5.4** `tests/unit/session/test_raw_stream_complete.py`
- [ ] **P5.5** `tests/unit/session/test_persistence_empty_guard.py`
- [ ] **P5.6** Full test suite + lints pass

### Phase 6: Documentation
- [ ] **P6.1** Update `CLAUDE.md` Known Bugs / Deferred Work sections as appropriate

## Deferred (Out of Scope)

These were identified during validation but are separate concerns:

| Item | Rationale for deferral |
|------|----------------------|
| Extract token usage (`prompt_tokens`, `completion_tokens`) from API responses | Only cache metrics extracted today; separate enhancement |
| Route provider `logger.debug()` to verbose.md | Provider DEBUG logs use Python logging, not SessionLogger; architectural change |
| Filter empty assistant messages in `_convert_messages()` (Anthropic/OpenAI) | The context guard (P2.1) prevents them from being stored; converting bad messages is a symptom, not root cause |
| Retry on empty stream response | Would need new retry semantics (HTTP was 200 OK); the guard + warning is sufficient for now |
| Validate tool call id/name in `_build_stream_complete()` | Truncated streams could produce ToolCall(id="", name=""); separate from empty response bug. Phase 2.1 guard only checks content+tool_calls presence, not tool_call validity |
| Non-streaming `_parse_response()` empty content validation | Phase 2.1 guard catches downstream; explicit validation in `_parse_response()` would be defense-in-depth but is a separate fix |
