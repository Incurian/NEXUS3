# HTTP/RPC Flow Code Review

**Date:** 2026-01-08
**Reviewer:** Claude Code Review
**Scope:** `nexus3/rpc/http.py`, `nexus3/rpc/protocol.py`, `nexus3/rpc/dispatcher.py`, `nexus3/rpc/global_dispatcher.py`, `nexus3/session/session.py`

---

## Flow Diagram

```
                                   HTTP Request
                                        |
                                        v
                    +-----------------------------------+
                    |     run_http_server()             |
                    |     (asyncio TCP server)          |
                    +-----------------------------------+
                                        |
                                        v
                    +-----------------------------------+
                    |     handle_connection()           |
                    |  - read_http_request()            |
                    |  - Method validation (POST only)  |
                    |  - Path-based routing             |
                    +-----------------------------------+
                          |              |             |
                          v              v             v
                   [/ or /rpc]    [/agent/{id}]   [404 Not Found]
                          |              |
                          v              v
            +-----------------+   +------------------+
            | GlobalDispatcher|   | pool.get(id)     |
            |  - create_agent |   | -> Agent         |
            |  - destroy_agent|   | -> dispatcher    |
            |  - list_agents  |   +------------------+
            +-----------------+            |
                          |                |
                          v                v
                    +-----------------------------------+
                    |       parse_request()             |
                    |   (JSON-RPC 2.0 validation)       |
                    +-----------------------------------+
                                        |
                                        v
                    +-----------------------------------+
                    |       dispatcher.dispatch()       |
                    |  - Handler lookup                 |
                    |  - Parameter extraction           |
                    |  - Handler execution              |
                    +-----------------------------------+
                                        |
                          +-------------+--------------+
                          |                            |
                          v                            v
                    [Agent Dispatcher]          [GlobalDispatcher]
                     - send -> Session.send()    - create_agent
                     - cancel                    - destroy_agent
                     - shutdown                  - list_agents
                     - get_tokens
                     - get_context
                          |
                          v
                    +-----------------------------------+
                    |       Session.send()              |
                    |  - Tool execution loop            |
                    |  - Streaming responses            |
                    +-----------------------------------+
                                        |
                                        v
                    +-----------------------------------+
                    |       make_*_response()           |
                    |       serialize_response()        |
                    +-----------------------------------+
                                        |
                                        v
                    +-----------------------------------+
                    |       send_http_response()        |
                    |  - HTTP 200/400/404/405/500       |
                    |  - Connection: close              |
                    +-----------------------------------+
```

---

## 1. Request/Response Lifecycle Analysis

### Strengths

1. **Clear separation of concerns**: HTTP parsing, JSON-RPC protocol, and business logic are cleanly separated into distinct modules.

2. **Consistent response handling**: All paths lead to `send_http_response()` ensuring uniform HTTP response formatting.

3. **Proper resource cleanup**: The `finally` block in `handle_connection()` ensures writer is always closed.

### Issues

#### Issue 1.1: Inconsistent error response format (Medium)

**Location:** `http.py:258`, `http.py:266`, `http.py:280`, `http.py:288`

**Problem:** HTTP-level errors return plain JSON objects, while JSON-RPC errors return proper JSON-RPC error responses. This creates inconsistency for clients.

```python
# HTTP-level error (non-standard)
await send_http_response(writer, 400, f'{{"error": "{e}"}}')

# JSON-RPC error (standard)
error_response = make_error_response(None, PARSE_ERROR, str(e))
```

**Impact:** Clients must handle two different error formats depending on where the error occurred.

**Recommendation:** Consider wrapping all errors in JSON-RPC format, even HTTP-level ones, or document the distinction clearly in API documentation.

#### Issue 1.2: Notification responses return empty body (Low)

**Location:** `http.py:316-318`

```python
if rpc_response is not None:
    await send_http_response(writer, 200, serialize_response(rpc_response))
else:
    # Notification - no response body, but still need HTTP response
    await send_http_response(writer, 200, "")
```

**Analysis:** This is technically correct per JSON-RPC 2.0 spec (notifications don't expect responses), but the empty HTTP 200 response could be confusing. A 204 No Content would be more semantically correct.

---

## 2. Error Handling Analysis

### Strengths

1. **Fail-fast philosophy**: The codebase doesn't swallow exceptions silently. Errors bubble up with context.

2. **Typed error hierarchy**: `NexusError` -> `InvalidParamsError`, `ParseError` provides clear error categorization.

3. **Standard error codes**: Uses JSON-RPC 2.0 defined error codes correctly.

### Issues

#### Issue 2.1: Information leakage in error messages (Medium-High)

**Location:** `dispatcher.py:112-116`, `global_dispatcher.py:131-136`

```python
except Exception as e:
    return make_error_response(
        request.id,
        INTERNAL_ERROR,
        f"Internal error: {type(e).__name__}: {e}",
    )
```

**Problem:** Exception type names and messages are exposed to clients. This can leak implementation details (stack traces, internal paths, library versions).

**Recommendation:** In production, return generic "Internal server error" messages. Log full details server-side. Add a debug mode flag to control verbosity.

#### Issue 2.2: HTTP parse error can include exception details (Medium)

**Location:** `http.py:258`

```python
except HttpParseError as e:
    await send_http_response(writer, 400, f'{{"error": "{e}"}}')
```

**Problem:** The error message `e` may contain internal details about parsing failures that could aid attackers in crafting malformed requests.

#### Issue 2.3: Silent exception handling in catch-all (Low)

**Location:** `http.py:320-329`

```python
except Exception as e:
    try:
        await send_http_response(...)
    except Exception:
        pass  # Connection may be broken
```

**Analysis:** While the comment justifies this (connection may be broken), this pattern silently swallows what could be important errors. Consider at minimum logging the error before discarding.

#### Issue 2.4: Inconsistent NexusError handling (Low)

**Location:** `dispatcher.py:104-107`

```python
except NexusError as e:
    ...
    return make_error_response(request.id, INTERNAL_ERROR, e.message)
```

**Problem:** All `NexusError` subclasses are treated as `INTERNAL_ERROR`, but some (like `InvalidParamsError`) should map to different codes. This is already handled separately for `InvalidParamsError`, but future `NexusError` subclasses need clear guidelines.

---

## 3. HTTP Protocol Correctness

### Strengths

1. **Proper Content-Length handling**: Uses `readexactly(content_length)` which is correct.

2. **Encoding consistency**: UTF-8 everywhere with explicit charset in Content-Type.

3. **Connection: close semantics**: Correctly closes connection after each request (simple, avoids keep-alive complexity).

### Issues

#### Issue 3.1: No HTTP version validation (Low)

**Location:** `http.py:119`

```python
method, path, _version = parts
```

**Problem:** The HTTP version is extracted but ignored. The server should at minimum reject HTTP/0.9 and potentially warn on non-HTTP/1.1 versions.

#### Issue 3.2: Malformed header silently skipped (Low)

**Location:** `http.py:142-143`

```python
if ":" not in header_str:
    continue  # Skip malformed headers
```

**Analysis:** Silently skipping malformed headers could hide issues. Per HTTP spec, headers without colons are invalid and could indicate a malformed request. Consider rejecting the request or at least logging.

#### Issue 3.3: No Host header validation (Low)

**Problem:** HTTP/1.1 requires a Host header. The server doesn't validate its presence or value. While not critical for localhost-only operation, it's technically non-compliant.

#### Issue 3.4: Missing CORS headers (Informational)

**Problem:** If this server is ever accessed from a browser context (unlikely but possible for debugging tools), CORS headers would be needed. Consider adding an optional flag for this.

#### Issue 3.5: No request timeout for long-running handlers (Medium)

**Location:** `http.py:301-311`

```python
try:
    rpc_response = await dispatcher.dispatch(rpc_request)
except Exception as e:
    ...
```

**Problem:** There's no timeout on `dispatcher.dispatch()`. A malicious or buggy handler could hang indefinitely, consuming server resources.

**Recommendation:** Add `asyncio.wait_for(dispatcher.dispatch(...), timeout=...)` with configurable timeout.

---

## 4. JSON-RPC 2.0 Compliance

### Strengths

1. **Version validation**: Correctly validates `jsonrpc: "2.0"`.

2. **ID handling**: Properly handles string, number, and null IDs.

3. **Notification support**: Correctly returns `None` for notifications (no ID).

4. **Error structure**: Error responses correctly include `code` and `message`.

### Issues

#### Issue 4.1: Positional parameters rejected (Low)

**Location:** `protocol.py:61-62`

```python
if isinstance(params, list):
    raise ParseError("Positional params (array) not supported, use named params (object)")
```

**Analysis:** JSON-RPC 2.0 allows positional parameters (arrays). Rejecting them is a valid design choice but reduces interoperability. Document this limitation.

#### Issue 4.2: Batch requests not supported (Medium)

**Problem:** JSON-RPC 2.0 defines batch requests as arrays of request objects. The parser rejects arrays:

```python
if not isinstance(data, dict):
    raise ParseError("Request must be a JSON object")
```

**Impact:** Clients cannot batch multiple operations in a single HTTP request, which can impact performance for high-frequency operations.

**Recommendation:** Document this limitation. Consider future support if needed.

#### Issue 4.3: ID type validation incomplete (Low)

**Location:** `protocol.py:65-67`

```python
if request_id is not None and not isinstance(request_id, (str, int)):
    raise ParseError(...)
```

**Problem:** JSON-RPC 2.0 allows fractional numbers as IDs, but Python's `int` check would reject `1.0`. Additionally, the spec technically allows `null` as an ID (distinct from absent), which is handled but worth documenting.

#### Issue 4.4: Response serialization allows invalid state (Low)

**Location:** `protocol.py:86-95`

```python
if response.error is not None:
    data["error"] = response.error
else:
    data["result"] = response.result
```

**Problem:** If both `error` and `result` are `None`, this produces `{"jsonrpc": "2.0", "id": ..., "result": null}` which is valid, but the Response dataclass doesn't enforce mutual exclusivity at construction time.

---

## 5. Security Considerations

### Strengths

1. **Localhost binding enforced**: `BIND_HOST = "127.0.0.1"` with validation prevents accidental public exposure.

2. **Body size limits**: `MAX_BODY_SIZE = 1_048_576` prevents memory exhaustion attacks.

3. **Timeouts on reads**: 30-second timeouts prevent slowloris attacks.

4. **No shell injection vectors**: Clean path parsing without shell evaluation.

### Issues

#### Issue 5.1: Agent ID injection potential (Medium)

**Location:** `http.py:280`

```python
await send_http_response(
    writer,
    404,
    f'{{"error": "Agent not found: {agent_id}"}}',
)
```

**Problem:** `agent_id` comes directly from the URL path and is interpolated into JSON without escaping. A crafted agent ID like `foo", "injected": "value` could produce malformed or misleading JSON.

**Recommendation:** Use `json.dumps()` to properly escape the agent_id:

```python
import json
await send_http_response(
    writer,
    404,
    json.dumps({"error": f"Agent not found: {agent_id}"}),
)
```

#### Issue 5.2: Path traversal not considered (Low)

**Location:** `http.py:229`

```python
agent_id = path[7:]  # len("/agent/") == 7
```

**Analysis:** While the agent_id is only used as a dictionary key (not file paths), values like `../` or URL-encoded characters could cause unexpected behavior if the agent ID is later used in file operations (e.g., log paths in pool.py:215).

**Current mitigation:** The `AgentPool` uses the ID directly in path construction (`base_log_dir / effective_id`), but Python's pathlib should handle this safely.

**Recommendation:** Add explicit validation for agent IDs (alphanumeric + limited special chars).

#### Issue 5.3: No authentication/authorization (Medium-High)

**Problem:** Any process on localhost can:
- Create unlimited agents (resource exhaustion)
- Destroy any agent
- Send arbitrary messages
- Trigger shutdown

**Analysis:** For a localhost-only development tool, this is acceptable. For production or multi-user systems, it's a significant gap.

**Recommendation:** Document the trust model explicitly. Consider optional authentication for production deployments.

#### Issue 5.4: CancellationToken callback exception swallowing (Low)

**Location:** `cancel.py:40-43`

```python
for callback in self._callbacks:
    try:
        callback()
    except Exception:
        pass  # Don't let callback errors prevent cancellation
```

**Analysis:** Swallowing exceptions here is intentional to ensure cancellation completes, but completely silent failure could hide bugs. Consider at minimum debug logging.

---

## 6. Edge Cases and Error Paths

### Issue 6.1: Empty request body handling (Low)

**Location:** `http.py:149-150`

```python
content_length_str = headers.get("content-length", "0")
```

**Analysis:** If Content-Length is missing, defaults to 0, which means empty body. For JSON-RPC, this produces `parse_request("")` which will fail with "Invalid JSON". This is correct behavior.

### Issue 6.2: Race condition in cancellation (Low)

**Location:** `dispatcher.py:145-158`

```python
token = CancellationToken()
self._active_requests[request_id] = token
try:
    # ... long operation ...
finally:
    self._active_requests.pop(request_id, None)
```

**Problem:** There's a tiny window between when `request_id` is added to `_active_requests` and when the operation actually starts. A cancel request during this window would succeed but have no effect.

**Impact:** Minimal in practice - the operation would complete normally.

### Issue 6.3: Concurrent create_agent with same ID (Low)

**Location:** `pool.py:205-212`

```python
async with self._lock:
    if effective_id in self._agents:
        raise ValueError(f"Agent already exists: {effective_id}")
```

**Analysis:** The lock correctly prevents race conditions for agent creation. Good design.

### Issue 6.4: Context absence not uniformly handled (Low)

**Location:** `dispatcher.py:185-187`, `dispatcher.py:200-201`

```python
if not self._context:
    return {"error": "No context manager"}
```

**Problem:** Methods that require context return a success response with an error field rather than an actual error response. Clients need to check for this nested error.

**Recommendation:** Either always inject context (making it non-optional) or throw `InvalidParamsError` when context is required but missing.

### Issue 6.5: Session tool execution loop limits (Informational)

**Location:** `session.py:214`

```python
max_iterations = 10  # Prevent infinite loops
```

**Analysis:** Good defensive programming. The limit is hardcoded; consider making it configurable for complex workflows.

---

## 7. Summary of Issues by Severity

### High Severity
- None identified

### Medium-High Severity
- **Issue 2.1**: Information leakage in error messages
- **Issue 5.3**: No authentication/authorization (acceptable for localhost dev tool)

### Medium Severity
- **Issue 1.1**: Inconsistent error response format
- **Issue 3.5**: No request timeout for long-running handlers
- **Issue 4.2**: Batch requests not supported
- **Issue 5.1**: Agent ID injection in JSON response

### Low Severity
- **Issue 1.2**: Notification returns empty body instead of 204
- **Issue 2.2**: HTTP parse error can include exception details
- **Issue 2.3**: Silent exception handling in catch-all
- **Issue 2.4**: Inconsistent NexusError handling
- **Issue 3.1**: No HTTP version validation
- **Issue 3.2**: Malformed header silently skipped
- **Issue 3.3**: No Host header validation
- **Issue 4.1**: Positional parameters rejected
- **Issue 4.3**: ID type validation incomplete
- **Issue 4.4**: Response serialization allows invalid state
- **Issue 5.2**: Path traversal not considered
- **Issue 5.4**: CancellationToken callback exception swallowing
- **Issue 6.1**: Empty request body handling
- **Issue 6.2**: Race condition in cancellation
- **Issue 6.4**: Context absence not uniformly handled

### Informational
- **Issue 3.4**: Missing CORS headers
- **Issue 6.5**: Session tool execution loop limits

---

## 8. Recommendations

### Immediate (Before Next Release)

1. **Fix JSON injection in agent ID error messages** (Issue 5.1)
   - Use `json.dumps()` for all JSON construction
   - Audit all f-string JSON patterns

2. **Add dispatch timeout** (Issue 3.5)
   - Prevent resource exhaustion from hanging handlers
   - Configure via server settings

### Short-term

3. **Sanitize error messages for production** (Issue 2.1)
   - Add debug/production mode flag
   - Log full errors server-side, return generic messages to clients

4. **Validate agent IDs** (Issue 5.2)
   - Restrict to safe character set
   - Prevent path traversal patterns

5. **Unify error response format** (Issue 1.1)
   - Document or standardize error format across all layers

### Long-term

6. **Consider batch request support** (Issue 4.2)
   - Would improve performance for high-frequency clients

7. **Add optional authentication** (Issue 5.3)
   - For production or multi-user deployments

---

## 9. Positive Observations

1. **Clean architecture**: The separation between HTTP layer, protocol layer, and business logic is exemplary.

2. **Type safety**: Extensive use of type hints and `TYPE_CHECKING` imports improves maintainability.

3. **Documentation**: Module and function docstrings are comprehensive and accurate.

4. **Security-by-default**: Localhost binding is enforced, not just default.

5. **Asyncio-native**: No blocking operations, proper use of async/await throughout.

6. **Defensive programming**: Body size limits, timeouts, iteration limits all demonstrate security awareness.

7. **Protocol correctness**: JSON-RPC 2.0 implementation is largely correct and well-structured.

---

*End of Review*
