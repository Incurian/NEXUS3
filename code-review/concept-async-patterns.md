# Async Patterns Code Review - NEXUS3

**Reviewer:** Claude Opus 4.5
**Date:** 2026-01-08
**Scope:** Async/await patterns, concurrency safety, task lifecycle management

---

## Executive Summary

NEXUS3 demonstrates a generally well-structured async-first architecture. The codebase follows its design principle of "async-first - asyncio throughout, not threading" with consistency. However, there are several areas that warrant attention, ranging from potential blocking calls in async contexts to opportunities for improved cancellation propagation.

**Overall Assessment:** Good async foundation with specific improvements needed.

| Category | Rating | Notes |
|----------|--------|-------|
| Async/Await Consistency | Good | Proper use throughout |
| Resource Cleanup | Good | Proper `async with` patterns |
| Cancellation Handling | Needs Improvement | Incomplete propagation |
| Concurrent Safety | Adequate | Lock usage, but some gaps |
| Blocking Call Avoidance | Needs Attention | Several blocking I/O calls |

---

## 1. Async/Await Usage Patterns

### 1.1 Strengths

The codebase demonstrates consistent async patterns:

```python
# From nexus3/provider/openrouter.py - Good async HTTP handling
async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
    async with client.stream("POST", url, headers=..., json=body) as response:
        async for event in self._parse_sse_stream_with_tools(response):
            yield event
```

The provider properly:
- Uses `async with` for HTTP client lifecycle
- Uses async iteration for streaming responses
- Yields events as an async iterator

```python
# From nexus3/session/session.py - Good async generator pattern
async def send(self, user_input: str, use_tools: bool = False,
               cancel_token: "CancellationToken | None" = None) -> AsyncIterator[str]:
    async for event in self.provider.stream(messages, tools):
        if isinstance(event, ContentDelta):
            yield event.text
```

### 1.2 Areas for Improvement

**Issue 1: Async def methods that could be regular methods**

Several methods are marked `async def` but don't actually perform async operations:

```python
# From nexus3/rpc/dispatcher.py:174-187
async def _handle_get_tokens(self, params: dict[str, Any]) -> dict[str, Any]:
    """Handle the 'get_tokens' method."""
    if not self._context:
        return {"error": "No context manager"}
    return self._context.get_token_usage()  # Synchronous call
```

Similarly:
- `_handle_get_context` (line 189)
- `_handle_shutdown` (line 160)
- `_handle_list_agents` in global_dispatcher.py (line 218)

**Recommendation:** While not incorrect (Python allows awaiting synchronous functions), consider documenting why these are async (handler protocol consistency) or using a sync handler protocol variant.

---

## 2. Async Context Managers

### 2.1 Strengths

Good use of `async with` for resource management:

```python
# From nexus3/client.py:41-50 - Proper async context manager
async def __aenter__(self) -> "NexusClient":
    self._client = httpx.AsyncClient(timeout=self._timeout)
    return self

async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
    if self._client:
        await self._client.aclose()
        self._client = None
```

```python
# From nexus3/cli/keys.py:76-92 - KeyMonitor properly cleans up task
async def __aenter__(self) -> "KeyMonitor":
    self._task = asyncio.create_task(monitor_for_escape(self.on_escape))
    return self

async def __aexit__(self, ...) -> None:
    if self._task:
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
```

### 2.2 Areas for Improvement

**Issue 2: Missing async context manager for provider client**

The `OpenRouterProvider` creates new `httpx.AsyncClient` instances for each request:

```python
# From nexus3/provider/openrouter.py:225 and 305
async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
    response = await client.post(...)
```

This pattern creates connection overhead. Consider:
- Using a shared client instance with proper lifecycle management
- Implementing `__aenter__`/`__aexit__` on the provider

**Issue 3: DisplayManager live_session resource handling**

```python
# From nexus3/display/manager.py:77-95
@asynccontextmanager
async def live_session(self) -> AsyncGenerator[None, None]:
    self._cancel_token = CancellationToken()
    try:
        self.summary.start()
        yield
    finally:
        self.summary.stop()
        self._cancel_token = None
        self._cancel_hint.show = False
```

The `finally` block is synchronous but manipulates state that could be accessed by async code. This is technically safe in single-threaded asyncio, but the pattern is fragile.

---

## 3. Task Cancellation Handling

### 3.1 Strengths

The `CancellationToken` pattern is well-implemented:

```python
# From nexus3/core/cancel.py
class CancellationToken:
    def cancel(self) -> None:
        if self._cancelled:
            return
        self._cancelled = True
        for callback in self._callbacks:
            try:
                callback()
            except Exception:
                pass  # Don't let callback errors prevent cancellation
```

Good cooperative cancellation in session:

```python
# From nexus3/session/session.py:296-298
for i, tc in enumerate(final_message.tool_calls):
    if cancel_token and cancel_token.is_cancelled:
        return
```

### 3.2 Critical Issues

**Issue 4: Cancellation not propagated to skills**

Skills like `nexus_send` make HTTP calls that could take significant time, but cancellation tokens are not passed through:

```python
# From nexus3/skill/builtin/nexus_send.py:43-66
async def execute(self, url: str = "", content: str = "", ...) -> ToolResult:
    async with NexusClient(url) as client:
        result = await client.send(content, ...)  # No cancellation support
```

**Recommendation:** Add `cancel_token` parameter to skill execution protocol:

```python
async def execute(self, cancel_token: CancellationToken | None = None, **kwargs) -> ToolResult:
    if cancel_token and cancel_token.is_cancelled:
        return ToolResult(error="Cancelled")
    # ... proceed with operation
```

**Issue 5: asyncio.gather with return_exceptions=True hides cancellation**

```python
# From nexus3/session/session.py:376-378
results = await asyncio.gather(
    *[execute_one(tc) for tc in tool_calls],
    return_exceptions=True,
)
```

When using `return_exceptions=True`, `CancelledError` is returned as a result rather than propagating. The code does handle exceptions as results (lines 381-387), but cancellation should typically propagate.

**Recommendation:** Consider catching `CancelledError` explicitly before gather, or use `asyncio.TaskGroup` (Python 3.11+) which has better cancellation semantics.

**Issue 6: Incomplete cancellation cleanup in dispatcher**

```python
# From nexus3/rpc/dispatcher.py:147-158
try:
    chunks: list[str] = []
    async for chunk in self._session.send(content, cancel_token=token):
        token.raise_if_cancelled()
        chunks.append(chunk)
    return {"content": "".join(chunks), "request_id": request_id}
except asyncio.CancelledError:
    return {"cancelled": True, "request_id": request_id}
finally:
    self._active_requests.pop(request_id, None)
```

The cancellation returns `{"cancelled": True}` but doesn't inform the session about partially completed tool calls. Compare with `repl.py` which handles this:

```python
# From nexus3/cli/repl.py:394-401
if was_cancelled and display.get_batch_results():
    cancelled_tools = [
        (tool.tool_id, tool.name)
        for tool in display.get_batch_results()
        if tool.state == ToolState.CANCELLED
    ]
    if cancelled_tools:
        session.add_cancelled_tools(cancelled_tools)
```

---

## 4. Concurrent Operation Safety

### 4.1 Strengths

Proper lock usage in AgentPool:

```python
# From nexus3/rpc/pool.py:177, 205, 302
self._lock = asyncio.Lock()

async def create(self, ...) -> Agent:
    async with self._lock:
        # Atomic agent creation
        if effective_id in self._agents:
            raise ValueError(f"Agent already exists: {effective_id}")
        # ... create agent
        self._agents[effective_id] = agent
        return agent

async def destroy(self, agent_id: str) -> bool:
    async with self._lock:
        agent = self._agents.pop(agent_id, None)
        # ...
```

### 4.2 Potential Race Conditions

**Issue 7: Non-atomic read operations on AgentPool**

```python
# From nexus3/rpc/pool.py:312-321
def get(self, agent_id: str) -> Agent | None:
    return self._agents.get(agent_id)  # Not protected by lock

def list(self) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for agent in self._agents.values():  # Not protected by lock
        result.append({...})
    return result
```

While `dict.get()` and iteration are thread-safe in CPython due to the GIL, in an async context with concurrent coroutines, a `destroy()` call could complete between `get()` and subsequent use of the returned agent.

**Recommendation:** Either:
1. Protect read operations with the same lock (could impact performance)
2. Use copy-on-write for `_agents` dict
3. Document the expected usage pattern (callers should handle agent disappearing)

**Issue 8: Shared provider state**

```python
# From nexus3/rpc/pool.py:228-232
raw_callback = logger.get_raw_log_callback()
if raw_callback is not None:
    provider = self._shared.provider
    if hasattr(provider, "set_raw_log_callback"):
        provider.set_raw_log_callback(raw_callback)
```

Each agent sets the callback on the shared provider, overwriting previous agents' callbacks. This means only the last-created agent gets raw logging.

**Recommendation:** Use a callback dispatcher pattern or per-agent provider instances.

**Issue 9: Dispatcher active_requests without lock**

```python
# From nexus3/rpc/dispatcher.py:51, 145, 158
self._active_requests: dict[str, CancellationToken] = {}

# In _handle_send:
self._active_requests[request_id] = token
# ...
finally:
    self._active_requests.pop(request_id, None)

# In _handle_cancel:
token = self._active_requests.get(request_id)
```

Concurrent send and cancel operations could race. While dict operations are atomic in CPython, the logic spanning multiple operations is not.

---

## 5. Event Loop Handling

### 5.1 Strengths

Clean entry points using `asyncio.run()`:

```python
# From nexus3/cli/repl.py:524-566
if args.command == "send":
    exit_code = asyncio.run(cmd_send(args.url, args.content, args.request_id))
# ...
asyncio.run(run_repl(verbose=args.verbose, ...))
```

### 5.2 Areas for Improvement

**Issue 10: No explicit event loop management for nested async**

The codebase doesn't handle the case where it might be called from within an existing event loop (e.g., Jupyter notebooks, other async frameworks).

**Recommendation:** Consider using `asyncio.get_running_loop()` with fallback:

```python
try:
    loop = asyncio.get_running_loop()
    # Already in async context - create task instead
except RuntimeError:
    asyncio.run(main())
```

---

## 6. Blocking Calls in Async Code

### 6.1 Critical Issues

**Issue 11: Blocking file I/O in async skills**

```python
# From nexus3/skill/builtin/read_file.py:50-53
async def execute(self, path: str = "", **kwargs: Any) -> ToolResult:
    # ...
    p = normalize_path(path)
    content = p.read_text(encoding="utf-8")  # BLOCKING I/O
```

```python
# From nexus3/skill/builtin/write_file.py:55-57
async def execute(self, ...) -> ToolResult:
    # ...
    p.write_text(content, encoding="utf-8")  # BLOCKING I/O
```

These blocking calls will freeze the entire event loop for the duration of the I/O operation.

**Recommendation:** Use `asyncio.to_thread()` or `aiofiles`:

```python
# Option 1: Run blocking I/O in thread pool
content = await asyncio.to_thread(p.read_text, encoding="utf-8")

# Option 2: Use async file library
import aiofiles
async with aiofiles.open(p, mode='r', encoding='utf-8') as f:
    content = await f.read()
```

**Issue 12: Blocking stdin read**

```python
# From nexus3/cli/keys.py:45
char = sys.stdin.read(1)  # BLOCKING
```

This is in a loop with `select()` guarding it, which is the correct pattern for Unix. However, the Windows fallback is just a busy-loop:

```python
# From nexus3/cli/keys.py:59-60
while True:
    await asyncio.sleep(check_interval)  # Does nothing on Windows
```

**Recommendation:** On Windows, use `msvcrt.kbhit()` and `msvcrt.getch()` or consider using a cross-platform library like `keyboard` or `pynput`.

**Issue 13: Blocking stdout in async context**

```python
# From nexus3/display/printer.py:94-95
def print_streaming_chunk(self, chunk: str) -> None:
    sys.stdout.write(chunk)  # Blocking
    sys.stdout.flush()       # Blocking
```

While stdout writes are typically fast, they can block if the terminal is slow or the buffer is full.

**Recommendation:** For high-volume streaming, consider batching or using `loop.run_in_executor()`.

---

## 7. Task Lifecycle Management

### 7.1 Strengths

Good task cleanup pattern:

```python
# From nexus3/cli/keys.py:86-92
async def __aexit__(self, ...) -> None:
    if self._task:
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
```

### 7.2 Areas for Improvement

**Issue 14: Unstructured task creation**

```python
# From nexus3/cli/repl.py:372
stream_task = asyncio.create_task(do_stream())
```

The task is created but the error handling relies on external `try/except`:

```python
# Lines 378-381
try:
    stream_task.result()
except asyncio.CancelledError:
    pass  # Cancelled by ESC
```

Other exceptions from `do_stream()` would be silently discarded if not awaited. The code does await the result, but the pattern is fragile.

**Recommendation:** Use `asyncio.TaskGroup` (Python 3.11+) for structured concurrency, or ensure all tasks are properly awaited with exception handling.

**Issue 15: No timeout on agent cleanup**

```python
# From nexus3/cli/serve.py:114-116
finally:
    for agent_info in pool.list():
        await pool.destroy(agent_info["agent_id"])
```

If `pool.destroy()` hangs, the server will never exit.

**Recommendation:** Add timeout:

```python
async with asyncio.timeout(5.0):
    for agent_info in pool.list():
        await pool.destroy(agent_info["agent_id"])
```

---

## 8. Recommendations Summary

### High Priority

1. **Convert blocking file I/O to async** (`read_file`, `write_file` skills)
   - Use `asyncio.to_thread()` or `aiofiles` library

2. **Propagate cancellation tokens to skills**
   - Add `cancel_token` parameter to skill protocol
   - Check cancellation before long operations

3. **Fix shared provider callback issue**
   - Use per-agent logging or callback multiplexer

### Medium Priority

4. **Add timeout to cleanup operations**
   - Prevent hangs during shutdown

5. **Protect AgentPool read operations**
   - Either use locks or document expected behavior

6. **Improve Windows key monitoring**
   - Use `msvcrt` module or cross-platform library

### Low Priority

7. **Consider connection pooling in provider**
   - Reuse `httpx.AsyncClient` across requests

8. **Document async handler protocol rationale**
   - Why some sync operations are in async methods

---

## 9. Code Samples - Recommended Patterns

### Proper Async File I/O

```python
import asyncio
from pathlib import Path

class ReadFileSkill:
    async def execute(self, path: str = "", **kwargs: Any) -> ToolResult:
        if not path:
            return ToolResult(error="No path provided")

        try:
            p = normalize_path(path)
            # Run blocking I/O in thread pool
            content = await asyncio.to_thread(
                p.read_text,
                encoding="utf-8"
            )
            return ToolResult(output=content)
        except FileNotFoundError:
            return ToolResult(error=f"File not found: {path}")
        # ... other exceptions
```

### Cancellable Skill Execution

```python
from nexus3.core.cancel import CancellationToken

class Skill(Protocol):
    async def execute(
        self,
        cancel_token: CancellationToken | None = None,
        **kwargs: Any
    ) -> ToolResult: ...

class NexusSendSkill:
    async def execute(
        self,
        url: str = "",
        content: str = "",
        cancel_token: CancellationToken | None = None,
        **kwargs: Any
    ) -> ToolResult:
        if cancel_token and cancel_token.is_cancelled:
            return ToolResult(error="Cancelled before execution")

        try:
            async with NexusClient(url) as client:
                # Periodically check cancellation for long operations
                result = await client.send(content)

                if cancel_token and cancel_token.is_cancelled:
                    return ToolResult(error="Cancelled during execution")

                return ToolResult(output=json.dumps(result))
        except ClientError as e:
            return ToolResult(error=str(e))
```

### Structured Concurrent Execution

```python
# Python 3.11+ pattern
async def _execute_tools_parallel(
    self,
    tool_calls: tuple[ToolCall, ...],
    cancel_token: CancellationToken | None = None,
) -> list[ToolResult]:
    """Execute tools with proper cancellation and exception handling."""

    results: list[ToolResult] = []

    try:
        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(self._execute_single_tool(tc, cancel_token))
                for tc in tool_calls
            ]
    except* Exception as eg:
        # Handle exception group - some tasks may have succeeded
        for i, exc in enumerate(eg.exceptions):
            results.append(ToolResult(error=f"Execution error: {exc}"))
        return results

    return [task.result() for task in tasks]
```

---

## Conclusion

NEXUS3's async architecture is fundamentally sound, following the stated design principle of async-first development. The main areas requiring attention are:

1. **Blocking I/O in async contexts** - The most impactful issue affecting event loop responsiveness
2. **Incomplete cancellation propagation** - Skills and long operations need cancellation support
3. **Race conditions in shared state** - Minor but worth addressing for robustness

The codebase demonstrates good understanding of async patterns and follows consistent conventions. Addressing the identified issues would elevate the async implementation from "good" to "excellent."
