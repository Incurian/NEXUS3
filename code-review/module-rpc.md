# Code Review: nexus3/rpc/ Module

**Reviewer:** Claude (Opus 4.5)
**Date:** 2026-01-08
**Module:** `nexus3/rpc/`
**Files Reviewed:** 8 (excluding `__pycache__`)

---

## Executive Summary

The `nexus3/rpc/` module provides a well-architected JSON-RPC 2.0 implementation for multi-agent server mode. The code demonstrates strong design principles: clean separation of concerns, proper async patterns, and comprehensive documentation. However, there are several areas where improvements could enhance robustness, maintainability, and security.

**Overall Assessment:** Good quality with room for improvement.

| Aspect | Rating | Notes |
|--------|--------|-------|
| Code Quality | B+ | Clean, well-typed, but some duplication |
| Architecture | A- | Excellent separation of concerns |
| Security | B | Good localhost binding, but some gaps |
| Documentation | A | Comprehensive README, good docstrings |
| Error Handling | B | Solid base, but inconsistencies |
| Testing Support | B- | Testable design, but some tight coupling |

---

## 1. Code Quality and Organization

### Strengths

1. **Clean module structure** (`__init__.py:1-82`): Explicit `__all__` export list with logical groupings (Types, Protocol functions, HTTP server, Error codes, etc.).

2. **Consistent typing**: All files use modern Python type hints with `dict[str, Any]`, union types (`str | int | None`), and Protocol classes.

3. **Minimal dependencies**: The module uses only stdlib (`asyncio`, `json`, `dataclasses`, etc.) for the HTTP server - no external HTTP framework required.

### Issues

#### Issue 1.1: Duplicated InvalidParamsError Definition

**Location:** `dispatcher.py:234-235` and `global_dispatcher.py:36-37`

```python
# dispatcher.py:234-235
class InvalidParamsError(NexusError):
    """Raised when method parameters are invalid."""

# global_dispatcher.py:36-37
class InvalidParamsError(NexusError):
    """Raised when method parameters are invalid."""
```

**Problem:** The same exception class is defined twice in separate files. This violates DRY and could cause confusion when catching exceptions (which `InvalidParamsError` is which?).

**Recommendation:** Define `InvalidParamsError` once in `nexus3/rpc/protocol.py` alongside other protocol-related errors, then import it where needed.

---

#### Issue 1.2: Unused Import in __init__.py

**Location:** `__init__.py:14`

```python
from nexus3.rpc.dispatcher import Dispatcher, InvalidParamsError
```

The `InvalidParamsError` from `dispatcher.py` is exported, but `global_dispatcher.py` has its own copy. This is inconsistent.

---

#### Issue 1.3: Handler Type Alias Duplication

**Location:** `dispatcher.py:24` and `global_dispatcher.py:33`

```python
# Both files define the same type alias
Handler = Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]
```

**Recommendation:** Define once in `types.py` and import.

---

## 2. JSON-RPC Protocol Implementation

### Strengths

1. **Proper spec compliance** (`protocol.py`): Implements JSON-RPC 2.0 correctly with proper error codes, request/response validation, and notification support.

2. **Comprehensive validation** (`protocol.py:23-74`): The `parse_request` function validates all required fields with clear error messages.

3. **Client-side functions** (`protocol.py:147-229`): Nice separation of server-side and client-side protocol functions.

### Issues

#### Issue 2.1: Positional Parameters Not Supported

**Location:** `protocol.py:61-62`

```python
if isinstance(params, list):
    raise ParseError("Positional params (array) not supported, use named params (object)")
```

**Assessment:** This is a deliberate design decision documented in the code. While JSON-RPC 2.0 allows positional parameters, rejecting them simplifies the dispatcher implementation. The error message is clear and actionable.

**Status:** Acceptable limitation, properly documented.

---

#### Issue 2.2: No Batch Request Support

**Location:** `protocol.py:42-43`

```python
if not isinstance(data, dict):
    raise ParseError("Request must be a JSON object")
```

**Problem:** JSON-RPC 2.0 supports batch requests (array of request objects). Currently, these are rejected.

**Impact:** Low - batch requests are rarely needed for this use case.

**Recommendation:** Document this limitation in the README. Consider adding batch support in a future iteration if needed.

---

#### Issue 2.3: Response Serialization Always Includes Either result or error

**Location:** `protocol.py:91-94`

```python
if response.error is not None:
    data["error"] = response.error
else:
    data["result"] = response.result
```

**Issue:** If `response.result` is `None` and `response.error` is also `None`, this will serialize `{"result": null}`. Per JSON-RPC 2.0 spec, a successful response MUST have `result`, but this edge case seems intentional since `make_success_response` always sets `result`.

**Status:** Not a bug, but worth noting for maintainability.

---

## 3. HTTP Server Implementation

### Strengths

1. **Pure asyncio** (`http.py`): No external dependencies, uses stdlib only. Clean implementation at ~390 LOC.

2. **Comprehensive timeouts** (`http.py:103-106, 127-130, 163-166`): All read operations have 30-second timeouts preventing hung connections.

3. **Body size limit** (`http.py:64, 156-159`): 1MB limit prevents DoS attacks.

4. **Proper HTTP response formatting** (`http.py:185-220`): Correct status messages, Content-Type, Content-Length, Connection: close.

### Issues

#### Issue 3.1: Error Response JSON Not Properly Escaped

**Location:** `http.py:258, 280-281`

```python
await send_http_response(writer, 400, f'{{"error": "{e}"}}')
# and
await send_http_response(
    writer,
    404,
    f'{{"error": "Agent not found: {agent_id}"}}',
)
```

**Problem:** If `e` or `agent_id` contains characters like `"` or `\`, this produces invalid JSON.

**Example:** If `agent_id = 'test"bad'`, the response becomes:
```json
{"error": "Agent not found: test"bad"}
```

**Recommendation:** Use `json.dumps()` for error responses:
```python
import json
await send_http_response(writer, 404, json.dumps({"error": f"Agent not found: {agent_id}"}))
```

---

#### Issue 3.2: Connection: close on Every Response

**Location:** `http.py:214`

```python
"Connection: close",
```

**Assessment:** This forces a new TCP connection per request, adding latency for clients making multiple requests. However, for this use case (agent control), request frequency is low enough that this is acceptable.

**Recommendation:** Consider supporting HTTP keep-alive in a future iteration for performance-sensitive use cases.

---

#### Issue 3.3: No CORS Headers

**Location:** `http.py:209-216`

**Problem:** If the server needs to be accessed from a web browser (e.g., a web-based agent management UI), CORS headers would be required.

**Impact:** Low for CLI-focused usage. Would block browser-based clients.

**Recommendation:** Add optional CORS support or document the limitation.

---

#### Issue 3.4: Protocol Type Mismatch

**Location:** `http.py:52`

```python
def get_agent(self, agent_id: str) -> "Agent | None": ...
```

But in `pool.py:312`:
```python
def get(self, agent_id: str) -> Agent | None:
```

**Problem:** The Protocol in `http.py` expects `get_agent()` but the actual `AgentPool` has `get()`. The code at `http.py:275` uses `pool.get(agent_id)`, which is correct, but the Protocol definition is wrong.

**Recommendation:** Fix the Protocol in `http.py:52`:
```python
def get(self, agent_id: str) -> "Agent | None": ...
```

---

#### Issue 3.5: Hardcoded Timeout Value

**Location:** `http.py:103-106, 127-130, 163-166`

```python
timeout=30.0,
```

The 30-second timeout is hardcoded in three places.

**Recommendation:** Define a constant `REQUEST_TIMEOUT = 30.0` at module level.

---

## 4. Dispatcher Patterns

### Strengths

1. **Clean handler registration** (`dispatcher.py:52-56, 59-61`): Handlers are registered in `__init__` with clear method names.

2. **Request tracking for cancellation** (`dispatcher.py:51, 143-145, 157-158`): Active requests are tracked with `CancellationToken` for cancellation support.

3. **Proper exception handling** (`dispatcher.py:99-116`): Different exception types map to appropriate JSON-RPC error codes.

### Issues

#### Issue 4.1: Inconsistent Error Handling Between Dispatchers

**Location:** `dispatcher.py:99-116` vs `global_dispatcher.py:119-136`

The error handling code is nearly identical but duplicated. Both handle:
- `InvalidParamsError` -> `INVALID_PARAMS`
- `NexusError` -> `INTERNAL_ERROR`
- Generic `Exception` -> `INTERNAL_ERROR`

**Recommendation:** Extract to a common helper function:
```python
def handle_dispatch_error(error: Exception, request_id: Any) -> Response | None:
    """Convert exception to JSON-RPC error response."""
    if request_id is None:
        return None
    # ... error handling logic
```

---

#### Issue 4.2: _handle_get_tokens Returns Dict with "error" Key on Failure

**Location:** `dispatcher.py:185-187`

```python
if not self._context:
    return {"error": "No context manager"}
return self._context.get_token_usage()
```

**Problem:** This returns a success response with an `"error"` key in the result, rather than a proper JSON-RPC error response. Clients expecting token data would need to check for both RPC errors and result.error.

**Recommendation:** Raise an exception instead:
```python
if not self._context:
    raise InvalidParamsError("Context manager not available")
```

Same issue at `dispatcher.py:200-201` for `_handle_get_context`.

---

#### Issue 4.3: Missing Validation for request_id in cancel

**Location:** `dispatcher.py:223-225`

```python
request_id = params.get("request_id")
if not request_id:
    raise InvalidParamsError("Missing required parameter: request_id")
```

**Problem:** `if not request_id` is truthy check, which rejects `request_id=0` or `request_id=""`. While these are unlikely values, using `is None` is more precise:

```python
if request_id is None:
    raise InvalidParamsError("Missing required parameter: request_id")
```

---

#### Issue 4.4: Race Condition in Cancellation

**Location:** `dispatcher.py:144-158`

```python
token = CancellationToken()
self._active_requests[request_id] = token

try:
    # ... processing ...
finally:
    self._active_requests.pop(request_id, None)
```

And in `_handle_cancel` (`dispatcher.py:227-231`):
```python
token = self._active_requests.get(request_id)
if token:
    token.cancel()
```

**Potential Race:** If `_handle_cancel` is called between the token being removed from `_active_requests` and the response being sent, cancellation appears to fail even though the request may still be processing.

**Assessment:** This is a minor issue in practice because:
1. The request is likely complete if the token is removed
2. The client gets `cancelled: false` with `reason: not_found_or_completed`

**Status:** Low priority, but worth documenting the behavior.

---

## 5. AgentPool and GlobalDispatcher

### Strengths

1. **Excellent documentation** (`pool.py:1-32`): Clear module docstring with architecture overview and example usage.

2. **Proper resource isolation** (`pool.py:243-266`): Each agent gets its own `SessionLogger`, `ContextManager`, `ServiceContainer`, `SkillRegistry`.

3. **Shared expensive resources** (`pool.py:54-72`): `Config`, `Provider`, `PromptLoader` are shared across agents.

4. **Thread-safe operations** (`pool.py:177, 205, 302`): `asyncio.Lock` protects create/destroy operations.

### Issues

#### Issue 5.1: Redundant agent_id Parameter

**Location:** `pool.py:179-183`

```python
async def create(
    self,
    agent_id: str | None = None,
    config: AgentConfig | None = None,
) -> Agent:
```

And `global_dispatcher.py:174-175`:
```python
config = AgentConfig(agent_id=agent_id, system_prompt=system_prompt)
agent = await self._pool.create(agent_id=agent_id, config=config)
```

**Problem:** `agent_id` is passed both directly and inside `config`, creating redundancy and potential confusion. The resolution logic at `pool.py:207-208` handles this, but it's unnecessarily complex.

**Recommendation:** Remove the standalone `agent_id` parameter and always use `config`:
```python
async def create(self, config: AgentConfig | None = None) -> Agent:
    effective_config = config or AgentConfig()
    effective_id = effective_config.agent_id or uuid4().hex[:8]
```

---

#### Issue 5.2: ValueError for Duplicate Agent

**Location:** `pool.py:211-212`

```python
if effective_id in self._agents:
    raise ValueError(f"Agent already exists: {effective_id}")
```

**Problem:** `ValueError` is a generic Python exception. Clients catching `NexusError` subclasses won't catch this.

**Recommendation:** Create a specific exception:
```python
class AgentExistsError(NexusError):
    """Raised when attempting to create an agent with a duplicate ID."""
```

---

#### Issue 5.3: GlobalDispatcher Not Exported

**Location:** `__init__.py:43-82`

`GlobalDispatcher` is not in `__all__`, though it's a key component.

**Recommendation:** Add to exports:
```python
from nexus3.rpc.global_dispatcher import GlobalDispatcher
# and in __all__:
"GlobalDispatcher",
```

---

#### Issue 5.4: Circular Import Workaround

**Location:** `pool.py:250-251`

```python
# Import here to avoid circular import (skills -> client -> rpc -> pool)
from nexus3.skill.builtin import register_builtin_skills
```

**Assessment:** Delayed import is a valid workaround, but indicates architectural coupling. The comment explains the reason, which is good.

**Status:** Acceptable workaround, but worth monitoring for complexity growth.

---

#### Issue 5.5: Raw Log Callback Setup is Fragile

**Location:** `pool.py:225-232`

```python
raw_callback = logger.get_raw_log_callback()
if raw_callback is not None:
    provider = self._shared.provider
    if hasattr(provider, "set_raw_log_callback"):
        provider.set_raw_log_callback(raw_callback)
```

**Problem:** Using `hasattr()` for duck typing breaks if the provider is wrapped or proxied. Also, setting a callback on a shared provider from individual agents could cause conflicts.

**Recommendation:**
1. Add `set_raw_log_callback` to the `AsyncProvider` protocol if it's expected behavior
2. Or use per-agent provider instances if raw logging is agent-specific

---

## 6. Path-Based Routing

### Strengths

1. **Simple and effective** (`http.py:223-232`): Clean extraction of agent_id from path.

2. **Clear routing logic** (`http.py:271-290`): Well-documented routing with proper error responses.

3. **Alias support** (`http.py:272`): Both `/` and `/rpc` route to GlobalDispatcher.

### Issues

#### Issue 6.1: Path Not Normalized

**Location:** `http.py:274`

```python
elif (agent_id := _extract_agent_id(http_request.path)) is not None:
```

**Problem:** The path is used as-is from the HTTP request. Paths like `/agent/worker-1/` (trailing slash) or `/agent//worker-1` would not match correctly.

**Recommendation:** Normalize the path:
```python
path = http_request.path.rstrip('/').replace('//', '/')
```

---

#### Issue 6.2: No URL Decoding

**Location:** `http.py:228-231`

```python
if path.startswith("/agent/"):
    agent_id = path[7:]  # len("/agent/") == 7
    if agent_id:
        return agent_id
```

**Problem:** URL-encoded characters in agent_id (e.g., `/agent/test%20agent`) are not decoded.

**Recommendation:** Use `urllib.parse.unquote()`:
```python
from urllib.parse import unquote
agent_id = unquote(path[7:])
```

---

## 7. Documentation Quality

### Strengths

1. **Exceptional README** (`README.md`): 800+ lines of comprehensive documentation including:
   - Architecture diagrams
   - API reference tables
   - Code examples with curl commands
   - Multi-turn conversation examples
   - Error response examples

2. **Good docstrings**: All public functions and classes have docstrings with Args, Returns, and Raises sections.

3. **Type annotations**: Consistent throughout all files.

### Issues

#### Issue 7.1: README References Non-Existent --reload Flag

**Location:** `README.md:695`

```bash
# With auto-reload on code changes
python -m nexus3 --serve --reload
```

This flag may not exist (would need to verify against CLI implementation).

**Recommendation:** Verify flag exists or remove from documentation.

---

#### Issue 7.2: Code Example Shows HTTP 404 for Agent Not Found

**Location:** `README.md:651-659`

The example shows HTTP 404 with plain JSON error, but per `http.py:276-281`, this is correct behavior. However, it's inconsistent with JSON-RPC error responses used elsewhere.

**Assessment:** This is a design decision - HTTP-level errors (agent not found) use HTTP status codes, while RPC-level errors use JSON-RPC error format. The documentation accurately reflects the implementation.

---

## 8. Potential Security Improvements

### Current Security Measures

1. **Localhost-only binding** (`http.py:65, 361-365`): Enforced with explicit check.
2. **Body size limit** (`http.py:64`): 1MB prevents memory exhaustion.
3. **Timeouts** (`http.py`): 30-second timeouts prevent slowloris attacks.

### Recommendations

#### Security 8.1: Rate Limiting

**Location:** N/A (not implemented)

There's no rate limiting on requests. A client could flood the server with requests.

**Recommendation:** Consider adding basic rate limiting, especially for `create_agent`.

---

#### Security 8.2: Agent ID Validation

**Location:** `pool.py:207-212`

Agent IDs can be any string. Malicious IDs like `../../../etc/passwd` could potentially cause path traversal in log directories.

**Current Mitigation:** The log directory is created at `agent_log_dir = self._shared.base_log_dir / effective_id` which should handle this via `pathlib`, but explicit validation would be safer.

**Recommendation:** Validate agent_id format:
```python
import re
if not re.match(r'^[a-zA-Z0-9_-]+$', effective_id):
    raise InvalidParamsError(f"Invalid agent_id format: {effective_id}")
```

---

#### Security 8.3: Error Message Information Disclosure

**Location:** `http.py:308, 326` and `dispatcher.py:114-116`

```python
f"Internal error: {type(e).__name__}: {e}",
```

**Problem:** Full exception details are returned to the client, potentially exposing implementation details.

**Recommendation:** Log the full error server-side, return generic message to client:
```python
logger.exception(f"Internal error: {e}")
return make_error_response(request_id, INTERNAL_ERROR, "Internal server error")
```

---

## 9. Performance Considerations

### Current Implementation

1. **Connection: close** on every response forces new TCP connections.
2. **Synchronous JSON parsing** could block the event loop for large payloads.
3. **Lock contention** in AgentPool for every create/destroy.

### Recommendations

1. **HTTP Keep-Alive**: Consider supporting persistent connections for chatty clients.

2. **JSON Streaming**: For very large responses, consider streaming JSON serialization.

3. **Read-Write Lock**: Replace `asyncio.Lock` with a read-write lock pattern if read operations (get, list) significantly outnumber writes (create, destroy).

---

## 10. Summary of Recommendations

### High Priority

1. **Fix duplicated `InvalidParamsError`** - Consolidate to single definition in `protocol.py`
2. **Fix JSON escaping in HTTP error responses** - Use `json.dumps()` instead of f-strings
3. **Fix Protocol type mismatch** - `get_agent` -> `get` in `http.py:52`
4. **Add agent_id validation** - Prevent path traversal and invalid characters

### Medium Priority

5. **Extract common dispatch error handling** - Reduce duplication between dispatchers
6. **Change `_handle_get_tokens` error handling** - Raise exception instead of returning error dict
7. **Add `GlobalDispatcher` to exports** - Missing from `__all__`
8. **Create `AgentExistsError` exception** - Replace generic `ValueError`
9. **Normalize URL paths** - Handle trailing slashes and URL encoding

### Low Priority

10. **Extract hardcoded timeout constant** - Define `REQUEST_TIMEOUT = 30.0`
11. **Remove redundant `agent_id` parameter** - Use only `config` in `AgentPool.create()`
12. **Consider rate limiting** - Especially for `create_agent`
13. **Reduce information disclosure in errors** - Generic messages to clients, detailed logs server-side

---

## Conclusion

The `nexus3/rpc/` module is well-designed with excellent documentation and proper async patterns. The main areas for improvement are:

1. **Code deduplication** (InvalidParamsError, Handler type, error handling)
2. **Edge case handling** (JSON escaping, path normalization)
3. **API consistency** (error responses, exception types)

The architecture is sound and follows the project's design principles (async-first, fail-fast, minimal interfaces). With the recommended improvements, this module would be production-ready.
