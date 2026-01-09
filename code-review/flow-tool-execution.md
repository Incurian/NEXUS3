# Tool Execution Flow - Code Review

**Reviewed:** 2026-01-08
**Files Analyzed:**
- `/home/inc/repos/NEXUS3/nexus3/session/session.py`
- `/home/inc/repos/NEXUS3/nexus3/skill/registry.py`
- `/home/inc/repos/NEXUS3/nexus3/skill/base.py`
- `/home/inc/repos/NEXUS3/nexus3/skill/builtin/*.py`
- `/home/inc/repos/NEXUS3/nexus3/context/manager.py`
- `/home/inc/repos/NEXUS3/nexus3/core/types.py`

---

## Executive Summary

The tool execution system is well-designed with clear separation of concerns. The architecture follows async-first principles and provides good abstractions through protocols and dependency injection. However, there are several areas that need attention, particularly around error handling edge cases, argument validation, and parallel execution behavior.

**Overall Assessment:** Good foundation with room for hardening.

---

## Flow Diagram

```
User Input
    |
    v
+-------------------+
|  Session.send()   |
+-------------------+
    |
    +-- flush cancelled tools (if any pending)
    |
    +-- add user message to context
    |
    v
+-----------------------------------+
|  _execute_tool_loop_streaming()  |
|  (max 10 iterations)              |
+-----------------------------------+
    |
    +-- build messages from context
    |
    +-- get tool definitions from registry
    |
    v
+------------------------+
|  Provider.stream()     |  <-- Yields: ContentDelta, ReasoningDelta,
+------------------------+              ToolCallStarted, StreamComplete
    |
    +-- yield content chunks to caller
    |
    +-- accumulate final_message
    |
    v
[Has tool_calls?] --No--> Add assistant message, return
    |
   Yes
    |
    v
+-------------------------------+
|  Add assistant msg to context |
|  (with tool_calls)            |
+-------------------------------+
    |
    v
[Check _parallel flag] --Yes--> _execute_tools_parallel()
    |                               |
   No                               +-- asyncio.gather() all tools
    |                               |
    v                               v
+----------------------------+  +----------------------------+
| Sequential Execution       |  | Parallel Execution         |
|----------------------------|  |----------------------------|
| for each tool_call:        |  | Execute all simultaneously |
|   - check cancellation     |  | - No halt-on-error         |
|   - execute skill          |  | - All results collected    |
|   - add result to context  |  +----------------------------+
|   - if error: halt batch   |
+----------------------------+
    |
    v
[Loop continues] --> Back to Provider.stream()
    |
    (after 10 iterations)
    |
    v
Yield "[Max tool iterations reached]"
```

---

## Detailed Analysis

### 1. Tool Call Detection and Parsing

**Location:** `session.py` lines 219-248

**Flow:**
1. `StreamComplete` event contains the final `Message` with `tool_calls` tuple
2. `ToolCallStarted` events are emitted during streaming for UI updates
3. Tool calls are detected by checking `final_message.tool_calls`

**Strengths:**
- Clean event-based streaming architecture
- Immediate notification via `ToolCallStarted` for responsive UI
- Immutable dataclasses prevent accidental mutation

**Issues:**

| Severity | Issue | Location |
|----------|-------|----------|
| LOW | No validation that `tool_calls` contains valid tool names before execution | Line 254 |
| LOW | `ToolCall.arguments` is typed as `dict[str, Any]` - no schema validation | `types.py:34` |

---

### 2. Skill Lookup (Registry)

**Location:** `registry.py` lines 87-103

**Flow:**
1. `registry.get(name)` checks `_instances` cache first
2. If not cached, calls factory with `ServiceContainer`
3. Caches result for future calls
4. Returns `None` for unknown skills

**Strengths:**
- Lazy instantiation reduces startup cost
- Factory pattern enables dependency injection
- Instance caching prevents redundant creation
- Re-registration clears cache correctly

**Issues:**

| Severity | Issue | Location |
|----------|-------|----------|
| MEDIUM | `get()` returns `None` silently - caller must always check | Line 103 |
| LOW | No mechanism to unregister a skill | Missing method |
| LOW | `get_definitions()` instantiates ALL skills just to get definitions | Lines 125-126 |

**Recommendation:** Consider storing definition metadata separately from skill instances to avoid unnecessary instantiation when getting definitions.

---

### 3. Skill Execution and Error Handling

**Location:** `session.py` lines 339-358

**Flow:**
1. Look up skill via `registry.get(tool_call.name)`
2. If not found, return `ToolResult(error="Unknown skill: ...")`
3. Strip internal arguments (prefixed with `_`)
4. Call `skill.execute(**args)`
5. Wrap any exception in `ToolResult(error=...)`

**Strengths:**
- Unknown skills handled gracefully
- Internal arguments (`_parallel`) properly stripped
- Exceptions caught and converted to error results
- Consistent `ToolResult` return type

**Issues:**

| Severity | Issue | Location |
|----------|-------|----------|
| HIGH | No timeout for skill execution - malicious/buggy skill can hang forever | Line 356 |
| MEDIUM | Exception message may leak sensitive info in error string | Line 358 |
| MEDIUM | No argument type validation before passing to skill | Line 356 |
| LOW | Generic `Exception` catch is broad - could hide bugs | Line 357 |

**Code:**
```python
# session.py:355-358
try:
    return await skill.execute(**args)
except Exception as e:
    return ToolResult(error=f"Skill execution error: {e}")
```

**Recommendation:** Add timeout wrapper:
```python
try:
    return await asyncio.wait_for(skill.execute(**args), timeout=300)
except asyncio.TimeoutError:
    return ToolResult(error=f"Skill {tool_call.name} timed out after 300s")
except Exception as e:
    return ToolResult(error=f"Skill execution error: {type(e).__name__}")
```

---

### 4. Result Formatting and Context Updates

**Location:** `context/manager.py` lines 132-153

**Flow:**
1. `add_tool_result()` creates a `Message` with `role=TOOL`
2. Content is either `result.error` (if present) or `result.output`
3. Message includes `tool_call_id` for proper API matching
4. Logger notified if configured

**Strengths:**
- Correct OpenAI message format for tool results
- Error content takes precedence (fail-fast principle)
- Logging integration for debugging

**Issues:**

| Severity | Issue | Location |
|----------|-------|----------|
| LOW | Tool name passed but not stored in Message | Line 146 |
| LOW | No size limit on result content - huge outputs could blow token budget | Line 145 |

**Recommendation:** Consider truncating very large tool outputs before adding to context to prevent token budget explosion.

---

### 5. Infinite Loop Prevention

**Location:** `session.py` line 214

**Implementation:**
```python
max_iterations = 10  # Prevent infinite loops

for _ in range(max_iterations):
    # ... tool loop ...

# Max iterations reached
yield "[Max tool iterations reached]"
```

**Strengths:**
- Hard limit prevents runaway tool loops
- Clear message when limit reached
- Reasonable default (10 iterations)

**Issues:**

| Severity | Issue | Location |
|----------|-------|----------|
| MEDIUM | `max_iterations` is hardcoded, not configurable | Line 214 |
| LOW | No logging/callback when max iterations reached | Line 337 |
| LOW | Message is yielded as content, may confuse LLM in future turns | Line 337 |

**Recommendation:** Make configurable and add callback for monitoring.

---

### 6. Parallel vs Sequential Execution

**Location:** `session.py` lines 264-327

**Detection:**
```python
parallel = any(
    tc.arguments.get("_parallel", False)
    for tc in final_message.tool_calls
)
```

**Sequential Behavior (Default):**
- Tools execute one at a time
- First error halts batch
- Remaining tools get "halted" result added to context

**Parallel Behavior:**
- All tools execute via `asyncio.gather(return_exceptions=True)`
- No halt-on-error (all complete)
- Exceptions converted to `ToolResult` errors

**Issues:**

| Severity | Issue | Location |
|----------|-------|----------|
| HIGH | Parallel execution has no concurrency limit - 100 tools = 100 concurrent tasks | Line 376 |
| MEDIUM | `_parallel` is checked on ANY tool - one tool can force parallel for all | Line 265-267 |
| MEDIUM | No individual tool timeout in parallel mode | Line 376 |
| LOW | Sequential mode adds "halted" messages even for tools that weren't attempted | Lines 320-326 |

**Parallel Code:**
```python
# session.py:376-378
results = await asyncio.gather(
    *[execute_one(tc) for tc in tool_calls],
    return_exceptions=True,
)
```

**Recommendation:** Add semaphore for concurrency limiting:
```python
MAX_CONCURRENT_TOOLS = 5
semaphore = asyncio.Semaphore(MAX_CONCURRENT_TOOLS)

async def execute_one_limited(tc):
    async with semaphore:
        return await self._execute_single_tool(tc)
```

---

### 7. Cancellation Handling

**Location:** `session.py` lines 97-120, 274-298

**Implementation:**
- `CancellationToken` checked before each tool execution
- Cancelled tools stored in `_pending_cancelled_tools`
- Flushed as error results on next `send()` call

**Strengths:**
- Cooperative cancellation model
- Cancelled tools properly reported to LLM
- State preserved across calls

**Issues:**

| Severity | Issue | Location |
|----------|-------|----------|
| MEDIUM | Cancellation during parallel execution abandons in-flight tools | Line 275 |
| LOW | Cancellation token not passed to skill - skill cannot check | Line 356 |
| LOW | No cancellation between streaming chunks in parallel mode | Lines 277-290 |

**Recommendation:** Consider passing cancellation token to skills that need cooperative cancellation.

---

### 8. Built-in Skill Implementation Review

**Files:** `/home/inc/repos/NEXUS3/nexus3/skill/builtin/*.py`

| Skill | Error Handling | Issues |
|-------|---------------|--------|
| `read_file` | Comprehensive | Catches specific exceptions, no path traversal check |
| `write_file` | Comprehensive | Creates parent dirs, no path traversal check |
| `echo` | Minimal | No validation needed |
| `sleep` | Minimal | No max duration limit |
| `nexus_send` | Good | Uses ClientError, no timeout |
| `nexus_cancel` | Good | Uses ClientError |
| `nexus_status` | Good | Uses ClientError |
| `nexus_shutdown` | Good | Uses ClientError |

**Common Issues:**

| Severity | Issue | Skills Affected |
|----------|-------|-----------------|
| HIGH | No path sanitization/traversal protection | read_file, write_file |
| MEDIUM | No timeout on network operations | nexus_send, nexus_cancel, nexus_status, nexus_shutdown |
| LOW | `sleep` has no max duration | sleep |

**Example - read_file.py:**
```python
async def execute(self, path: str = "", **kwargs: Any) -> ToolResult:
    if not path:
        return ToolResult(error="No path provided")

    try:
        p = normalize_path(path)  # What does this do? Path traversal protection?
        content = p.read_text(encoding="utf-8")
        return ToolResult(output=content)
```

**Recommendation:** Review `normalize_path()` to ensure it prevents `../../../etc/passwd` style attacks.

---

## Edge Cases and Error Paths

### Identified Edge Cases

| Edge Case | Current Behavior | Risk |
|-----------|------------------|------|
| Empty tool_calls tuple | Treated as final response | OK |
| Tool returns both output and error | Error takes precedence in context | OK |
| Skill raises during execute | Caught, converted to error result | OK |
| Factory raises during get() | Exception propagates - crash | MEDIUM |
| Empty registry with use_tools=True | Enters tool loop, exits immediately | OK |
| Tool arguments missing required fields | Passed to skill, skill must handle | LOW |
| Tool arguments with wrong types | Passed to skill, skill must handle | LOW |
| Concurrent modification of registry | No locking, potential race | LOW |

### Missing Test Coverage

Based on analysis of `tests/integration/test_skill_execution.py`:

1. Factory exception during skill instantiation
2. Cancellation during parallel execution
3. Tool result exceeding token budget
4. Network timeout in nexus_* skills
5. Path traversal attempts in file skills

---

## Summary of Issues by Severity

### HIGH (3)
1. No timeout for skill execution
2. No concurrency limit for parallel execution
3. No path sanitization in file skills

### MEDIUM (6)
1. `registry.get()` returns None silently
2. Exception messages may leak sensitive info
3. No argument type validation
4. `max_iterations` hardcoded
5. `_parallel` flag affects entire batch
6. Cancellation abandons in-flight parallel tools

### LOW (11)
1. No tool name validation before execution
2. `ToolCall.arguments` has no schema validation
3. No skill unregister mechanism
4. `get_definitions()` instantiates all skills
5. Generic Exception catch
6. Tool name not stored in Message
7. No size limit on result content
8. No logging at max iterations
9. Max iterations message may confuse LLM
10. Sequential halted messages for unattempted tools
11. Cancellation token not passed to skills

---

## Recommendations Summary

1. **Add skill execution timeout** - Prevent hangs from buggy/malicious skills
2. **Limit parallel concurrency** - Use semaphore to prevent resource exhaustion
3. **Review path normalization** - Ensure file skills are protected from traversal
4. **Make max_iterations configurable** - Allow tuning per use case
5. **Add argument validation** - Validate against JSON schema before execution
6. **Truncate large outputs** - Prevent token budget explosion
7. **Consider skill-level cancellation** - Pass token to skills that need it
8. **Add factory exception handling** - Prevent crash on bad factory

---

## Positive Observations

1. **Clean architecture** - Clear separation between Session, Registry, Skills, and Context
2. **Protocol-based design** - `Skill` protocol enables flexible implementations
3. **Dependency injection** - `ServiceContainer` provides good DI without complexity
4. **Immutable types** - Frozen dataclasses prevent accidental mutation
5. **Comprehensive callbacks** - 8 callbacks enable rich UI integration
6. **Good test coverage** - Integration tests cover main execution paths
7. **Async-first** - Properly async throughout, no blocking calls
8. **Fail-fast principle** - Errors surface rather than being swallowed
