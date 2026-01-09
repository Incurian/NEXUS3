# Error Handling Code Review - NEXUS3

**Date:** 2026-01-08
**Reviewer:** Code Review Agent
**Scope:** Error handling patterns across the NEXUS3 codebase

---

## Executive Summary

NEXUS3 demonstrates a well-structured, intentional approach to error handling that aligns with its "fail-fast" design principle. The codebase uses a typed exception hierarchy with clear boundaries between internal errors, protocol errors, and user-facing errors. However, there are several areas where improvements could enhance consistency and maintainability.

**Overall Grade: B+**

### Strengths
- Clean exception hierarchy rooted in `NexusError`
- Consistent use of `from e` for exception chaining
- Clear separation between skill errors (returned as `ToolResult`) and system errors (raised)
- Good error message quality in most modules

### Areas for Improvement
- Some silent exception swallowing in critical paths
- Inconsistent error types across modules
- Missing custom exceptions for specific failure modes
- HTTP module has its own exception outside the hierarchy

---

## 1. Error Hierarchy Design

### Current Structure

```
NexusError (base)
  |-- ConfigError (config loading failures)
  |-- ProviderError (LLM API issues)
  |-- ClientError (HTTP client errors) [defined in client.py]
  |-- ParseError (JSON-RPC parsing) [defined in rpc/protocol.py]
  |-- InvalidParamsError (RPC parameter validation) [defined in rpc/dispatcher.py, rpc/global_dispatcher.py]

HttpParseError (NOT in hierarchy) [defined in rpc/http.py]
```

**File:** `/home/inc/repos/NEXUS3/nexus3/core/errors.py`
```python
class NexusError(Exception):
    """Base class for all NEXUS3 errors."""
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)

class ConfigError(NexusError):
    """Raised for configuration issues..."""

class ProviderError(NexusError):
    """Raised for LLM provider issues..."""
```

### Analysis

**Positives:**
- Base class stores message in `.message` attribute, providing consistent access
- Docstrings clearly describe what each exception represents
- Simple, minimal hierarchy (avoids over-engineering)

**Issues:**

1. **`HttpParseError` is not part of the hierarchy**
   - File: `/home/inc/repos/NEXUS3/nexus3/rpc/http.py:85`
   ```python
   class HttpParseError(Exception):
       """Raised when HTTP request parsing fails."""
   ```
   - This breaks the principle of all NEXUS errors inheriting from `NexusError`
   - Catching `NexusError` will miss HTTP parsing errors

2. **Duplicate `InvalidParamsError` definitions**
   - Defined in both `rpc/dispatcher.py:234` and `rpc/global_dispatcher.py:36`
   - Both are identical but live in separate files
   - Should be consolidated in `core/errors.py` or `rpc/protocol.py`

3. **`ParseError` and `ClientError` defined outside core/errors.py**
   - `ParseError` in `rpc/protocol.py:10`
   - `ClientError` in `client.py:12`
   - While they inherit from `NexusError`, having them scattered makes the hierarchy harder to understand

### Recommendations

1. Move `HttpParseError` to inherit from `NexusError`:
   ```python
   class HttpParseError(NexusError):
       """Raised when HTTP request parsing fails."""
   ```

2. Consolidate all error types in `core/errors.py` or create `rpc/errors.py` for RPC-specific errors

3. Remove duplicate `InvalidParamsError` - define once and import where needed

---

## 2. Try/Except Pattern Analysis

### Pattern Distribution

| Pattern | Count | Quality |
|---------|-------|---------|
| Specific exception catch with re-raise | 45+ | Good |
| Bare `except Exception` with re-raise | 8 | Acceptable |
| Bare `except:` or `except Exception: pass` | 6 | Problematic |
| Exception caught and converted to result | 15+ | Good (skills) |

### Good Patterns

**Provider module - proper exception chaining:**
File: `/home/inc/repos/NEXUS3/nexus3/provider/openrouter.py:250-255`
```python
except httpx.ConnectError as e:
    raise ProviderError(f"Failed to connect to API: {e}") from e
except httpx.TimeoutException as e:
    raise ProviderError(f"API request timed out: {e}") from e
except httpx.HTTPError as e:
    raise ProviderError(f"HTTP error occurred: {e}") from e
```
- Catches specific exceptions
- Uses `from e` to preserve stack trace
- Provides contextual error messages

**Config loader - granular error handling:**
File: `/home/inc/repos/NEXUS3/nexus3/config/loader.py:61-74`
```python
try:
    content = path.read_text(encoding="utf-8")
except OSError as e:
    raise ConfigError(f"Failed to read config file {path}: {e}") from e

try:
    data = json.loads(content)
except json.JSONDecodeError as e:
    raise ConfigError(f"Invalid JSON in config file {path}: {e}") from e

try:
    return Config.model_validate(data)
except ValidationError as e:
    raise ConfigError(f"Config validation failed for {path}: {e}") from e
```
- Each operation has its own try/except
- Clear error messages identify the failure point
- Exception chaining preserves original error

**Skills - errors as return values:**
File: `/home/inc/repos/NEXUS3/nexus3/skill/builtin/read_file.py:50-63`
```python
try:
    p = normalize_path(path)
    content = p.read_text(encoding="utf-8")
    return ToolResult(output=content)
except FileNotFoundError:
    return ToolResult(error=f"File not found: {path}")
except PermissionError:
    return ToolResult(error=f"Permission denied: {path}")
except IsADirectoryError:
    return ToolResult(error=f"Path is a directory, not a file: {path}")
except UnicodeDecodeError:
    return ToolResult(error=f"File is not valid UTF-8 text: {path}")
except Exception as e:
    return ToolResult(error=f"Error reading file: {e}")
```
- Excellent granularity - catches specific OS exceptions
- Returns errors as values (appropriate for skill protocol)
- Final catch-all ensures the skill never raises

### Problematic Patterns

**Silent exception swallowing in critical path:**
File: `/home/inc/repos/NEXUS3/nexus3/core/cancel.py:40-43`
```python
for callback in self._callbacks:
    try:
        callback()
    except Exception:
        pass  # Don't let callback errors prevent cancellation
```
- While the comment explains the intent, silently swallowing ALL exceptions is risky
- A malformed callback could mask bugs
- **Recommendation:** Log the exception before suppressing:
  ```python
  except Exception as e:
      # Log but don't propagate - cancellation must complete
      logger.warning(f"Cancel callback error: {e}")
  ```

**Silent exception swallowing in HTTP cleanup:**
File: `/home/inc/repos/NEXUS3/nexus3/rpc/http.py:328-336`
```python
except Exception as e:
    # Catch-all for any unexpected errors
    try:
        await send_http_response(...)
    except Exception:
        pass  # Connection may be broken

finally:
    try:
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass  # Connection may already be closed
```
- Three bare `except Exception: pass` in one function
- While cleanup code often needs this, the complete lack of logging makes debugging difficult
- **Recommendation:** At minimum, add debug-level logging

**Silent fallback in token counter:**
File: `/home/inc/repos/NEXUS3/nexus3/context/token_counter.py:151-155`
```python
if use_tiktoken:
    try:
        return TiktokenCounter()
    except ImportError:
        pass  # Fall back to simple counter

return SimpleTokenCounter()
```
- Silent fallback may surprise users expecting accurate counts
- **Recommendation:** Log when falling back:
  ```python
  except ImportError:
      logger.debug("tiktoken not available, using simple counter")
  ```

**Bare pass in prompt loader:**
File: `/home/inc/repos/NEXUS3/nexus3/context/prompt_loader.py:59`
```python
except Exception:
    parts.append(f"Operating system: Linux {release}")
```
- Catches ALL exceptions when reading `/etc/os-release`
- Should at minimum catch `OSError` and `IOError` specifically

---

## 3. Error Message Quality

### Good Examples

**Contextual messages with actionable information:**
```python
# From provider/openrouter.py:99-101
raise ProviderError(
    f"API key not found. Set the {self._config.api_key_env} environment variable."
)

# From config/loader.py:59
raise ConfigError(f"Config file not found: {path}")

# From rpc/protocol.py:53
raise ParseError(f"method must be a string, got: {type(method).__name__}")
```

These messages:
- Explain what went wrong
- Include relevant context (env var name, path, actual type)
- Suggest remediation where appropriate

### Areas for Improvement

**Generic messages lacking context:**
```python
# From session/session.py:358
return ToolResult(error=f"Skill execution error: {e}")
```
- Doesn't include the skill name or arguments
- Better: `f"Skill '{tool_call.name}' failed: {e}"`

**Missing error context in dispatcher:**
```python
# From rpc/dispatcher.py:107
return make_error_response(request.id, INTERNAL_ERROR, e.message)
```
- Loses the exception type information
- Better: Include exception class name for debugging

---

## 4. Error Propagation Chains

### Well-Designed Chains

**Config -> REPL:**
```
ConfigError raised in config/loader.py
    -> Caught in cli/repl.py:131
    -> Displayed to user with e.message
    -> REPL exits gracefully
```

**Provider -> Session -> REPL:**
```
ProviderError raised in provider/openrouter.py
    -> Propagates through session.send()
    -> Caught in cli/repl.py:383
    -> Displayed to user
    -> REPL continues (error marked in display)
```

**RPC Request -> Dispatcher -> HTTP:**
```
InvalidParamsError raised in dispatcher handler
    -> Caught in dispatcher.dispatch()
    -> Converted to JSON-RPC error response
    -> Serialized and sent via HTTP
```

### Analysis

The error propagation is generally clean with clear boundaries:
- Configuration errors stop startup
- Provider errors during streaming are displayed and don't crash
- RPC errors are converted to protocol-compliant error responses
- Skill errors are converted to `ToolResult` and sent back to LLM

---

## 5. User-Facing vs Internal Errors

### Clear Separation

**User-Facing (via REPL):**
- `ConfigError` - printed with red styling, stops REPL
- `ProviderError` - printed, REPL continues
- `ClientError` - printed when in client mode

**User-Facing (via JSON-RPC):**
- All errors converted to JSON-RPC error objects
- Uses standard error codes (-32700 to -32603)
- Error messages included in response

**Internal (not shown to users):**
- `HttpParseError` - converted to HTTP 400 response
- `ParseError` - converted to JSON-RPC PARSE_ERROR
- Raw exceptions in skills - converted to `ToolResult.error`

### Recommendations

1. Consider adding error codes to `NexusError` for programmatic handling:
   ```python
   class NexusError(Exception):
       code: str = "NEXUS_ERROR"
       def __init__(self, message: str) -> None:
           self.message = message
           super().__init__(message)

   class ConfigError(NexusError):
       code = "CONFIG_ERROR"
   ```

2. Document which errors can appear in JSON-RPC responses

---

## 6. Recovery Strategies

### Current Patterns

**Graceful degradation in token counting:**
- Falls back from tiktoken to simple counter
- System continues working, just with less accuracy

**Retry-able operations (none found):**
- No retry logic for transient API errors
- **Recommendation:** Consider adding retry with exponential backoff for:
  - Network timeouts in provider
  - Rate limit errors (with delay)

**Cancellation handling:**
- `CancellationToken` provides clean cancellation
- Cancelled operations return appropriate results
- Context manager ensures cleanup

### Missing Recovery Strategies

1. **No circuit breaker for API failures**
   - Repeated failures continue hitting the API
   - Consider tracking failure count and backing off

2. **No partial result recovery**
   - If streaming fails mid-response, everything is lost
   - Consider caching partial responses

---

## 7. Specific File Reviews

### `/home/inc/repos/NEXUS3/nexus3/rpc/http.py`

**Issue:** `HttpParseError` not in hierarchy
**Issue:** Multiple bare `except Exception: pass`
**Issue:** No logging of suppressed errors

**Severity:** Medium

### `/home/inc/repos/NEXUS3/nexus3/provider/openrouter.py`

**Quality:** Excellent
**Note:** Best error handling in codebase - specific catches, proper chaining, good messages

### `/home/inc/repos/NEXUS3/nexus3/core/cancel.py`

**Issue:** Silent swallowing of callback errors
**Severity:** Low (intentional for reliability)
**Recommendation:** Add logging

### `/home/inc/repos/NEXUS3/nexus3/context/token_counter.py`

**Issue:** Silent ImportError fallback
**Severity:** Low
**Recommendation:** Add debug logging

### `/home/inc/repos/NEXUS3/nexus3/rpc/dispatcher.py` and `global_dispatcher.py`

**Issue:** Duplicate `InvalidParamsError` definition
**Severity:** Low (code duplication)
**Recommendation:** Consolidate

---

## 8. Recommendations Summary

### High Priority

1. **Add `HttpParseError` to `NexusError` hierarchy**
   - Ensures consistent error handling across codebase
   - Prevents missed catches when using `except NexusError`

2. **Add logging for suppressed exceptions**
   - At minimum, debug-level logging in `cancel.py` and `http.py`
   - Aids debugging in production

### Medium Priority

3. **Consolidate error type definitions**
   - Move `ParseError`, `ClientError`, `InvalidParamsError` to central location
   - Either `core/errors.py` or module-specific `errors.py` files

4. **Improve generic error messages**
   - Add context to `"Skill execution error"` and similar
   - Include relevant identifiers (skill name, request ID, etc.)

### Low Priority

5. **Add error codes to exception classes**
   - Enables programmatic error handling
   - Useful for client applications

6. **Consider retry logic for transient failures**
   - API timeouts, rate limits
   - With exponential backoff

7. **Document error handling patterns in README**
   - When to raise vs return errors
   - Expected error propagation paths

---

## 9. Code Samples - Recommended Fixes

### Fix for `HttpParseError` hierarchy

```python
# In nexus3/rpc/http.py

from nexus3.core.errors import NexusError

class HttpParseError(NexusError):
    """Raised when HTTP request parsing fails."""
```

### Fix for duplicate `InvalidParamsError`

```python
# In nexus3/rpc/protocol.py (add here, remove from dispatcher files)

class InvalidParamsError(NexusError):
    """Raised when method parameters are invalid."""

# In nexus3/rpc/dispatcher.py and global_dispatcher.py
from nexus3.rpc.protocol import InvalidParamsError
```

### Fix for silent exception swallowing

```python
# In nexus3/core/cancel.py

import logging
logger = logging.getLogger(__name__)

def cancel(self) -> None:
    if self._cancelled:
        return
    self._cancelled = True
    for callback in self._callbacks:
        try:
            callback()
        except Exception as e:
            logger.debug(f"Cancel callback error (suppressed): {e}")
```

---

## Conclusion

NEXUS3's error handling is thoughtfully designed and largely consistent with its fail-fast philosophy. The main issues are:

1. One exception type outside the hierarchy (`HttpParseError`)
2. Some silent exception swallowing without logging
3. Minor code duplication in exception definitions

These issues are relatively minor and don't indicate fundamental design problems. The codebase demonstrates good practices like exception chaining, specific catches, and clear error messages. Implementing the recommended fixes would further strengthen the error handling and make debugging easier.

**Final Assessment:** The error handling is production-quality with room for polish. The "fail-fast" philosophy is well-implemented, and errors flow through the system in predictable ways.
