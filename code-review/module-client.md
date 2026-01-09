# Code Review: nexus3/client.py

**File:** `/home/inc/repos/NEXUS3/nexus3/client.py`
**Lines:** 163
**Reviewer:** Claude Code Review
**Date:** 2026-01-08

---

## Summary

The `NexusClient` class is a well-structured async HTTP client for communicating with NEXUS3 JSON-RPC servers. It provides a clean API for agent communication while following good async patterns. However, there are several issues ranging from unused parameters to missing functionality for multi-agent support.

**Overall Assessment:** Good foundation with room for improvement.

---

## 1. Code Quality

### Strengths

- **Clear structure:** The class follows a logical organization with initialization, context manager methods, internal helpers, and public API methods.
- **Consistent naming:** Methods follow Python naming conventions (`_call`, `_check`, `_next_id`).
- **Type hints throughout:** All methods have proper type annotations.

### Issues

#### 1.1 Unused Parameter in `send()` (line 110-122)

```python
async def send(self, content: str, request_id: int | None = None) -> dict[str, Any]:
    """Send a message to the agent.

    Args:
        content: The message content.
        request_id: Optional request ID (auto-generated if not provided).
    ...
    """
    params: dict[str, Any] = {"content": content}
    response = await self._call("send", params)
    return cast(dict[str, Any], self._check(response))
```

The `request_id` parameter is documented but **never used**. It should either:
1. Be included in the `params` dict if the server expects it
2. Be removed from the signature

Looking at `nexus3/skill/builtin/nexus_send.py:63`, the skill actually passes the request_id:
```python
result = await client.send(content, int(request_id) if request_id else None)
```

But the client ignores it. This is a **bug**.

**Severity:** High - Silent data loss, callers believe request_id is being sent.

#### 1.2 Excessive `cast()` Usage (lines 122, 135, 144, 153, 162)

Every public method uses `cast(dict[str, Any], ...)`. This suggests the return type from `_check()` should be better typed. The `_check()` method returns `Any`, forcing casts everywhere.

Consider:
- Making `_check()` generic with `TypeVar`
- Or simply return `dict[str, Any]` from `_check()` since that's what all callers expect

---

## 2. HTTP Client Implementation

### Strengths

- **Uses httpx correctly:** AsyncClient with proper timeout configuration.
- **Clean request building:** Uses the RPC protocol functions for serialization.
- **Proper resource cleanup:** Client is closed in `__aexit__`.

### Issues

#### 2.1 Missing HTTP Error Handling (lines 80-91)

Only `ConnectError` and `TimeoutException` are caught:

```python
try:
    response = await self._client.post(...)
    return parse_response(response.text)
except httpx.ConnectError as e:
    raise ClientError(f"Connection failed: {e}") from e
except httpx.TimeoutException as e:
    raise ClientError(f"Request timed out: {e}") from e
```

Missing handlers for:
- `httpx.HTTPStatusError` - If server returns 4xx/5xx
- `httpx.RequestError` - Base class for other network errors
- Non-200 status codes are silently ignored

The server can return HTTP 404 for unknown agents (`/agent/nonexistent`), but this code would try to parse the error body as JSON-RPC and fail confusingly.

**Severity:** Medium - Poor error messages for common failure cases.

#### 2.2 No Response Status Code Validation (line 86)

```python
response = await self._client.post(...)
return parse_response(response.text)
```

The code never checks `response.status_code`. A 404 or 500 response will be passed to `parse_response()`, which may:
- Raise `ParseError` with a confusing message if the body isn't JSON
- Or parse successfully but return unexpected data

#### 2.3 Missing ParseError Handling (line 86)

`parse_response()` can raise `ParseError` (from `nexus3/rpc/protocol.py:173`), but this exception is not caught in `_call()`. It will propagate as-is, not wrapped in `ClientError`.

This breaks the error handling contract documented in the class:
> "Raises: ClientError: On connection error, timeout, or protocol error."

**Severity:** Medium - Breaks documented contract.

---

## 3. Async Context Manager Usage

### Strengths

- **Clean implementation:** `__aenter__` and `__aexit__` are properly implemented.
- **Defensive cleanup:** Checks `if self._client` before closing.
- **Sets client to None after close:** Prevents use-after-close issues.

### Issues

#### 3.1 Missing Reentrance Guard (line 43)

```python
async def __aenter__(self) -> "NexusClient":
    """Enter async context, create httpx client."""
    self._client = httpx.AsyncClient(timeout=self._timeout)
    return self
```

If the context manager is entered twice without exiting, the first client is silently replaced and leaked:

```python
async with client:
    async with client:  # First httpx.AsyncClient is leaked
        ...
```

Consider raising an error if `self._client` is already set.

**Severity:** Low - Unusual usage pattern, but could cause resource leaks.

#### 3.2 No Exception Suppression in `__aexit__` (line 46)

```python
async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
```

The method signature accepts exception info but doesn't return a boolean. This is correct behavior (not suppressing exceptions), but the parameters are typed as `Any` instead of the proper types.

Better typing:
```python
async def __aexit__(
    self,
    exc_type: type[BaseException] | None,
    exc_val: BaseException | None,
    exc_tb: TracebackType | None,
) -> None:
```

**Severity:** Very Low - Style only.

---

## 4. Error Handling

### Strengths

- **Custom exception class:** `ClientError` extends `NexusError` for proper hierarchy.
- **Error chaining:** Uses `from e` to preserve original exceptions.
- **Extracts RPC error details:** The `_check()` method properly extracts code and message.

### Issues

#### 4.1 Error Message Could Include More Context (line 107)

```python
if response.error:
    code = response.error.get("code", -1)
    message = response.error.get("message", "Unknown error")
    raise ClientError(f"RPC error {code}: {message}")
```

The error response may include a `data` field with additional context (per JSON-RPC 2.0 spec). This is silently discarded.

Consider:
```python
data = response.error.get("data")
if data:
    raise ClientError(f"RPC error {code}: {message} (data: {data})")
```

**Severity:** Low - Loss of debugging information.

#### 4.2 No Logging

The client has no logging. For debugging distributed systems, it would be helpful to log:
- Request method and params (at DEBUG level)
- Response status/errors (at WARNING level)
- Connection establishment (at INFO level)

**Severity:** Low - Makes debugging harder.

---

## 5. API Design

### Strengths

- **Simple, focused API:** Five methods covering all agent operations.
- **Sensible defaults:** Default URL and timeout are reasonable.
- **Context manager pattern:** Forces proper resource cleanup.

### Issues

#### 5.1 No Multi-Agent Support (Critical Gap)

The client only supports single-endpoint communication. Per the RPC README, the server supports:
- Global methods at `POST /`
- Agent methods at `POST /agent/{agent_id}`

But `NexusClient` always posts to `self._url` (line 81). There's no way to:
1. Create agents (`create_agent`)
2. List agents (`list_agents`)
3. Destroy agents (`destroy_agent`)
4. Target specific agents by ID

This is documented in `nexus3/rpc/README.md` as the primary use case, but the client doesn't support it.

**Suggested additions:**
```python
async def create_agent(self, agent_id: str | None = None, system_prompt: str | None = None) -> dict[str, Any]: ...
async def list_agents(self) -> list[dict[str, Any]]: ...
async def destroy_agent(self, agent_id: str) -> dict[str, Any]: ...

# And a way to target specific agents:
def for_agent(self, agent_id: str) -> "NexusClient":
    """Return a new client targeting a specific agent."""
    return NexusClient(url=f"{self._url}/agent/{agent_id}", timeout=self._timeout)
```

**Severity:** High - Client cannot use documented server features.

#### 5.2 Type Mismatch Between `send()` and `cancel()` for request_id

In `send()` (line 110): `request_id: int | None`
In `cancel()` (line 124): `request_id: int | None`

But in the skills:
- `nexus_send.py:63` converts string to int: `int(request_id) if request_id else None`
- `nexus_cancel.py` likely does similar

The JSON-RPC spec and server documentation show `request_id` as strings in examples. This type inconsistency may cause issues.

**Severity:** Medium - Type confusion.

#### 5.3 Return Type Could Be More Specific

All public methods return `dict[str, Any]`. For better IDE support and type safety, consider:
- Using `TypedDict` for known response shapes
- Or at minimum, documenting the expected keys

---

## 6. Documentation Quality

### Strengths

- **Module docstring:** Clear one-liner description.
- **Class docstring with example:** Shows basic usage pattern.
- **Method docstrings:** All public methods documented with Args, Returns, Raises.

### Issues

#### 6.1 Docstrings Don't Match Implementation

`send()` docstring says `request_id` is "auto-generated if not provided", but the implementation ignores it entirely.

#### 6.2 Missing Docstring for `ClientError`

```python
class ClientError(NexusError):
    """Exception for client-side errors (connection, timeout, protocol)."""
```

This is adequate but could list the specific scenarios:
- Connection refused
- Timeout exceeded
- RPC error response
- Parse error (if that were caught)

#### 6.3 No Module-Level Documentation of Multi-Agent API

The module docstring doesn't mention that this client only works with single agents and doesn't support the global dispatcher methods.

---

## 7. Potential Issues and Improvements

### 7.1 Thread Safety

The `_request_id` counter (line 54) is not thread-safe:
```python
def _next_id(self) -> int:
    self._request_id += 1
    return self._request_id
```

While async code typically runs in a single thread, this could be an issue if the client is used with threading. Consider using `itertools.count()` or `asyncio.Lock` if this is a concern.

### 7.2 Connection Pooling

Each method creates a new HTTP connection because the client creates a new `AsyncClient` per context manager entry. For repeated calls, keeping the client alive longer would be more efficient.

Current usage forces:
```python
async with NexusClient() as client:
    await client.send("A")
    await client.send("B")  # Same connection
```

But:
```python
async with NexusClient() as client:
    await client.send("A")
# Connection closed

async with NexusClient() as client:
    await client.send("B")
# New connection
```

This is fine for typical usage but worth documenting.

### 7.3 No Retry Logic

Network errors immediately raise exceptions. For robustness, consider:
- Exponential backoff for connection errors
- Configurable retry count
- Distinguishing transient vs. permanent errors

**Severity:** Low - May be intentional to keep client simple.

---

## 8. Test Coverage Assessment

The test file (`/home/inc/repos/NEXUS3/tests/unit/test_client.py`) has good coverage:

- Context manager requirement (line 109-117)
- Successful send (line 119-140)
- Connection error handling (line 142-157)
- RPC error handling (line 159-181)
- get_tokens (line 183-205)
- shutdown (line 207-223)
- Request ID incrementing (line 225-245)

### Missing Tests

1. **Timeout handling** - No test for `TimeoutException`
2. **`cancel()` method** - Not tested
3. **`get_context()` method** - Not tested
4. **Non-200 HTTP status codes** - Not tested
5. **`ParseError` propagation** - Not tested
6. **Context manager reentrance** - Not tested
7. **Invalid response JSON** - Covered by protocol tests but not client integration

---

## Recommendations

### High Priority

1. **Fix `request_id` handling in `send()`** - Either use it or remove it.
2. **Add HTTP status code validation** - Check for 200 before parsing.
3. **Wrap `ParseError` in `ClientError`** - Honor the documented contract.
4. **Add multi-agent support** - `create_agent`, `list_agents`, `destroy_agent`, agent targeting.

### Medium Priority

5. **Improve return type specificity** - Consider TypedDict for responses.
6. **Add missing exception handlers** - HTTPStatusError, RequestError.
7. **Fix request_id type** - Align with server expectations (int vs str).

### Low Priority

8. **Add logging** - DEBUG level for requests, WARNING for errors.
9. **Include error `data` field** - More context in ClientError messages.
10. **Improve `__aexit__` typing** - Use proper exception types.
11. **Add reentrance guard** - Prevent double-entry resource leak.

---

## Code Snippets for Key Fixes

### Fix 1: Use request_id in send()

```python
async def send(self, content: str, request_id: int | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"content": content}
    if request_id is not None:
        params["request_id"] = request_id
    response = await self._call("send", params)
    return cast(dict[str, Any], self._check(response))
```

### Fix 2: Validate HTTP status and wrap ParseError

```python
async def _call(self, method: str, params: dict[str, Any] | None = None) -> Response:
    if self._client is None:
        raise ClientError("Client not initialized. Use 'async with' context manager.")

    request = Request(
        jsonrpc="2.0",
        method=method,
        params=params,
        id=self._next_id(),
    )

    try:
        response = await self._client.post(
            self._url,
            content=serialize_request(request),
            headers={"Content-Type": "application/json"},
        )

        if response.status_code != 200:
            raise ClientError(f"HTTP {response.status_code}: {response.text[:200]}")

        return parse_response(response.text)
    except httpx.ConnectError as e:
        raise ClientError(f"Connection failed: {e}") from e
    except httpx.TimeoutException as e:
        raise ClientError(f"Request timed out: {e}") from e
    except httpx.RequestError as e:
        raise ClientError(f"Request failed: {e}") from e
    except ParseError as e:
        raise ClientError(f"Invalid response: {e}") from e
```

### Fix 3: Add multi-agent methods

```python
async def create_agent(
    self, agent_id: str | None = None, system_prompt: str | None = None
) -> dict[str, Any]:
    """Create a new agent on the server."""
    params: dict[str, Any] = {}
    if agent_id:
        params["agent_id"] = agent_id
    if system_prompt:
        params["system_prompt"] = system_prompt
    response = await self._call("create_agent", params)
    return cast(dict[str, Any], self._check(response))

async def list_agents(self) -> list[dict[str, Any]]:
    """List all agents on the server."""
    response = await self._call("list_agents")
    result = self._check(response)
    return cast(list[dict[str, Any]], result.get("agents", []))

async def destroy_agent(self, agent_id: str) -> dict[str, Any]:
    """Destroy an agent on the server."""
    response = await self._call("destroy_agent", {"agent_id": agent_id})
    return cast(dict[str, Any], self._check(response))
```

---

## Conclusion

The `NexusClient` is a clean, well-structured async HTTP client that follows good Python patterns. The main issues are:

1. **Broken functionality** - `request_id` parameter is ignored
2. **Incomplete error handling** - Missing HTTP status checks and ParseError wrapping
3. **Missing features** - No support for multi-agent server architecture

The code quality is high and the test coverage is reasonable. With the recommended fixes, particularly around error handling and multi-agent support, this would be a robust client implementation.
