# NEXUS3 Remediation Plan

**Generated:** 2026-01-08
**Source:** Code review of 21 markdown files in `/code-review/`
**Status:** Planning complete - awaiting execution approval

---

## Executive Summary

This document consolidates detailed implementation plans for addressing all issues identified in the NEXUS3 code review. The remediation is organized into 5 phases with a total estimated effort of 40-50 hours.

### Overall Grades (Current State)

| Category | Grade | Target |
|----------|-------|--------|
| Architecture | A- | A |
| Code Quality | B+ | A- |
| Security | C+ | A- |
| Test Coverage | B- | A |
| Documentation | A | A |

### Phase Overview

| Phase | Focus | Critical Issues | Estimated Hours |
|-------|-------|-----------------|-----------------|
| 5R.1 | Security Hardening | 4 | 8-10 |
| 5R.2 | Data Integrity | 4 | 7-8 |
| 5R.3 | Async/Performance | 4 | 8-10 |
| 5R.4 | Test Coverage | 5 areas | 18-23 |
| 5R.5 | Minor Fixes | 7 | 6-8 |

---

# Phase 5R.1: Security Hardening

**Priority:** CRITICAL - Must complete before production deployment

## Issue 5R.1.1: No Authentication on HTTP Server

### Problem
`rpc/http.py` accepts any request from localhost without authentication. Any local process can control agents.

### Solution
Add API key authentication with Bearer token.

### Files to Create
- `nexus3/rpc/auth.py` - Authentication utilities

```python
"""Authentication utilities for HTTP server."""
import secrets
from dataclasses import dataclass

@dataclass(frozen=True)
class AuthConfig:
    enabled: bool
    api_key: str

def extract_bearer_token(headers: dict[str, str]) -> str | None:
    auth_header = headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None

def verify_token(token: str | None, expected: str) -> bool:
    if token is None:
        return False
    return secrets.compare_digest(token, expected)
```

### Files to Modify

**`config/schema.py`** - Add SecurityConfig:
```python
class SecurityConfig(BaseModel):
    auth_enabled: bool = True
    api_key: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
```

**`rpc/http.py`** - Add auth check after parsing HTTP request:
```python
if auth_config is not None and auth_config.enabled:
    token = extract_bearer_token(http_request.headers)
    if not verify_token(token, auth_config.api_key):
        await send_http_response(writer, 401, json.dumps({"error": "Unauthorized"}))
        return
```

**`cli/serve.py`** - Print API key on startup, pass to server.

### Tests Required
- `tests/unit/test_http_auth.py`
  - `test_extracts_valid_token`
  - `test_rejects_invalid_token`
  - `test_constant_time_comparison`
  - `test_unauthenticated_request_rejected`

---

## Issue 5R.1.2: Path Traversal in File Skills

### Problem
`read_file.py` and `write_file.py` allow reading/writing arbitrary paths including `../../../etc/passwd`.

### Solution
Create path sandboxing with configurable allowed directories.

### Files to Create
- `nexus3/core/sandbox.py` - Path validation module

```python
"""Path sandboxing for secure file operations."""
from pathlib import Path
from dataclasses import dataclass, field

@dataclass
class SandboxConfig:
    allowed_paths: list[Path] = field(default_factory=lambda: [Path.cwd()])
    block_hidden: bool = True
    block_symlinks: bool = True

class PathSecurityError(Exception):
    def __init__(self, path: str, reason: str):
        self.path = path
        self.reason = reason

def validate_path(path: str, config: SandboxConfig) -> Path:
    """Validate path is within sandbox. Raises PathSecurityError if not."""
    # Normalize, resolve, check symlinks, check allowed paths
    ...
```

### Files to Modify

**`skill/builtin/read_file.py`**:
```python
try:
    validated_path = validate_path(path, self._sandbox)
except PathSecurityError as e:
    return ToolResult(error=f"Access denied: {e.reason}")
```

**`skill/builtin/write_file.py`** - Same pattern.

**`config/schema.py`** - Add sandbox config options.

### Tests Required
- `tests/unit/test_sandbox.py`
  - `test_allows_path_in_sandbox`
  - `test_blocks_path_outside_sandbox`
  - `test_blocks_path_traversal`
  - `test_blocks_symlinks`
  - `test_blocks_hidden_files`

---

## Issue 5R.1.3: SSRF in nexus_send

### Problem
`nexus_send` accepts any URL, enabling attacks on internal networks and cloud metadata endpoints.

### Solution
URL validation with allowlist and IP range blocking.

### Files to Create
- `nexus3/core/url_validator.py` - SSRF protection

```python
"""URL validation for SSRF prevention."""
from dataclasses import dataclass, field

CLOUD_METADATA_IPS = {"169.254.169.254", "fd00:ec2::254"}

@dataclass
class UrlValidatorConfig:
    allowed_schemes: list[str] = field(default_factory=lambda: ["http", "https"])
    allowed_hosts: list[str] = field(default_factory=lambda: ["localhost", "127.0.0.1"])
    allowed_ports: tuple[int, int] = (1024, 65535)
    block_private_ips: bool = True
    block_cloud_metadata: bool = True

def validate_url(url: str, config: UrlValidatorConfig) -> str:
    """Validate URL against SSRF protections. Raises UrlSecurityError if blocked."""
    ...
```

### Files to Modify
- `skill/builtin/nexus_send.py` - Add URL validation
- `skill/builtin/nexus_cancel.py` - Same
- `skill/builtin/nexus_status.py` - Same
- `skill/builtin/nexus_shutdown.py` - Same

### Tests Required
- `tests/unit/test_url_validator.py`
  - `test_allows_localhost`
  - `test_blocks_external_hosts`
  - `test_blocks_cloud_metadata`
  - `test_blocks_private_ips`

---

## Issue 5R.1.4: JSON Injection in Error Responses

### Problem
Error messages interpolated into JSON with f-strings can break JSON structure.

### Solution
Use `json.dumps()` for all error responses.

### Files to Modify

**`rpc/http.py`** - Replace all f-string JSON with json.dumps():
```python
# BEFORE:
await send_http_response(writer, 400, f'{{"error": "{e}"}}')

# AFTER:
await send_http_response(writer, 400, json.dumps({"error": str(e)}))
```

### Tests Required
- `tests/unit/test_http_json_safety.py`
  - `test_error_message_with_quotes_escaped`
  - `test_agent_id_with_special_chars_escaped`

---

# Phase 5R.2: Data Integrity Fixes

## Issue 5R.2.1: Tool Call/Result Pair Corruption in Truncation

### Problem
Truncation can separate assistant messages with tool_calls from their corresponding tool results, creating invalid message sequences.

### Solution
Group tool call + results as atomic units during truncation.

### Files to Modify

**`context/manager.py`** - Add grouping logic:

```python
def _identify_message_groups(self) -> list[tuple[int, int]]:
    """Identify atomic message groups (assistant with tool_calls + results)."""
    groups = []
    i = 0
    while i < len(self._messages):
        msg = self._messages[i]
        if msg.role == Role.ASSISTANT and msg.tool_calls:
            tool_ids = {tc.id for tc in msg.tool_calls}
            j = i + 1
            while j < len(self._messages) and tool_ids:
                if self._messages[j].role == Role.TOOL:
                    tool_ids.discard(self._messages[j].tool_call_id)
                j += 1
            groups.append((i, j))
            i = j
        else:
            groups.append((i, i + 1))
            i += 1
    return groups
```

Rewrite `_truncate_oldest_first` and `_truncate_middle_out` to use groups.

### Tests Required
- `tests/unit/test_context_manager.py`
  - `test_truncation_preserves_tool_call_with_result`
  - `test_truncation_removes_orphaned_tool_results`
  - `test_truncation_multiple_tool_calls_same_message`

---

## Issue 5R.2.2: Messages Never Garbage Collected

### Problem
`_messages` list grows unbounded; truncated messages remain in memory.

### Solution
Add pruning after truncation with configurable minimum.

### Files to Modify

**`context/manager.py`**:
```python
# Add to ContextConfig
prune_truncated: bool = True
keep_minimum_messages: int = 10

# Add method
def _prune_messages(self, kept_messages: list[Message]) -> None:
    if not self.config.prune_truncated:
        return
    if len(self._messages) <= self.config.keep_minimum_messages:
        return
    kept_ids = {id(m) for m in kept_messages}
    self._messages = [m for m in self._messages if id(m) in kept_ids]
```

---

## Issue 5R.2.3: In-Progress Requests Not Cancelled on Destroy

### Problem
`AgentPool.destroy()` doesn't cancel active requests, causing resource leaks.

### Solution
Add `cancel_all_requests()` to Dispatcher, call from destroy.

### Files to Modify

**`rpc/dispatcher.py`**:
```python
def cancel_all_requests(self) -> list[str]:
    cancelled_ids = []
    for request_id, token in list(self._active_requests.items()):
        token.cancel()
        cancelled_ids.append(request_id)
    return cancelled_ids
```

**`rpc/pool.py`**:
```python
async def destroy(self, agent_id: str) -> bool:
    # ... existing code ...
    cancelled = agent.dispatcher.cancel_all_requests()
    if cancelled:
        await asyncio.sleep(0.1)  # Allow cleanup
    agent.logger.close()
    return True
```

---

## Issue 5R.2.4: Missing Encoding in File Operations

### Problem
File operations missing `encoding='utf-8', errors='replace'`.

### Files to Modify

**`session/markdown.py`** - Add encoding to all file operations:
```python
# write_text calls
path.write_text(content, encoding="utf-8", errors="replace")

# open calls
with path.open("a", encoding="utf-8", errors="replace") as f:
```

**`config/loader.py`** - Add `errors='replace'`:
```python
content = path.read_text(encoding="utf-8", errors="replace")
```

---

# Phase 5R.3: Async/Performance Fixes

## Issue 5R.3.1: Blocking File I/O in Async Skills

### Problem
`read_file` and `write_file` use blocking `Path.read_text()` / `write_text()`.

### Solution
Use `asyncio.to_thread()` for file operations.

### Files to Modify

**`skill/builtin/read_file.py`**:
```python
import asyncio

async def execute(self, path: str = "", **kwargs: Any) -> ToolResult:
    # ... validation ...
    content = await asyncio.to_thread(p.read_text, encoding="utf-8")
    return ToolResult(output=content)
```

**`skill/builtin/write_file.py`** - Same pattern with helper function.

---

## Issue 5R.3.2: No Skill Execution Timeout

### Problem
Skills can hang indefinitely.

### Solution
Add configurable timeout using `asyncio.wait_for()`.

### Files to Modify

**`config/schema.py`**:
```python
skill_timeout: float = 30.0  # seconds
```

**`session/session.py`**:
```python
try:
    return await asyncio.wait_for(
        skill.execute(**args),
        timeout=self.skill_timeout
    )
except asyncio.TimeoutError:
    return ToolResult(error=f"Skill '{tc.name}' timed out after {self.skill_timeout}s")
```

---

## Issue 5R.3.3: No Concurrency Limit for Parallel Tools

### Problem
Unbounded `asyncio.gather()` can overload system.

### Solution
Use `asyncio.Semaphore` to limit concurrent executions.

### Files to Modify

**`config/schema.py`**:
```python
max_concurrent_tools: int = 10
```

**`session/session.py`**:
```python
self._tool_semaphore = asyncio.Semaphore(max_concurrent_tools)

async def _execute_tools_parallel(self, tool_calls):
    async def execute_with_limit(tc):
        async with self._tool_semaphore:
            return await self._execute_single_tool(tc)

    return await asyncio.gather(*[execute_with_limit(tc) for tc in tool_calls])
```

---

## Issue 5R.3.4: Raw Log Callback Race in Multi-Agent

### Problem
Shared provider's `set_raw_log_callback()` is overwritten per agent.

### Solution
Create log multiplexer using `contextvars`.

### Files to Create

**`nexus3/rpc/log_multiplexer.py`**:
```python
"""Log callback multiplexer for multi-agent scenarios."""
import contextvars

_current_agent_logger = contextvars.ContextVar("current_agent_logger", default=None)

class LogMultiplexer:
    def agent_context(self, callback):
        """Context manager for setting current agent's logger."""
        ...

    def on_request(self, endpoint, payload):
        callback = _current_agent_logger.get()
        if callback:
            callback.on_request(endpoint, payload)

    # Same for on_response, on_chunk
```

### Files to Modify
- `rpc/pool.py` - Add multiplexer to SharedComponents
- `rpc/dispatcher.py` - Wrap session calls with log context

---

# Phase 5R.4: Test Coverage Expansion

## Priority Test Areas

| Area | Current | Target | Files |
|------|---------|--------|-------|
| Provider | 0% | 80% | `tests/unit/test_provider.py` |
| Context Manager | ~30% | 90% | `tests/unit/test_context_manager.py` |
| File Skills Security | 0% | 90% | `tests/unit/test_file_skill_security.py` |
| CLI/REPL | 0% | 60% | `tests/unit/test_cli.py` |
| HTTP Server | ~10% | 80% | `tests/unit/test_http_server.py` |

## 5R.4.1: Provider Unit Tests

**Test Cases:**
- SSE stream parsing (simple content, [DONE] marker, multi-line buffer)
- Tool call streaming (incremental arguments, multiple parallel)
- HTTP error handling (401, 429, 500, timeout)
- Raw log callback integration

**Mocking:** Use `httpx.MockTransport`

---

## 5R.4.2: Context Manager Truncation Tests

**Test Cases:**
- Token counting accuracy
- Truncation strategy correctness
- **CRITICAL:** Tool call/result pair preservation
- Budget calculations

---

## 5R.4.3: File Skill Security Tests

**Test Cases:**
- Path traversal attempts (`../../../etc/passwd`)
- Symlink attacks
- Permission denied handling
- Binary file handling

---

## 5R.4.4: CLI/REPL Tests

**Test Cases:**
- Command parsing (`/quit`, `/search args`)
- Argument parsing (`--serve`, `--connect`)
- Command handling

---

## 5R.4.5: HTTP Server Tests

**Test Cases:**
- Request parsing (valid POST, headers, body size limits)
- Response sending (status codes, Content-Length)
- Path routing (/, /agent/{id}, unknown)
- Security (rejects external bind)

---

# Phase 5R.5: Minor Fixes

## 5R.5.1: Export ReasoningDelta from Core

**File:** `core/__init__.py`
```python
from nexus3.core.types import (
    # ... existing ...
    ReasoningDelta,  # ADD
)
```

---

## 5R.5.2: Add extra="forbid" to Pydantic Models

**File:** `config/schema.py`
```python
class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # ...

class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # ...
```

---

## 5R.5.3: Consolidate Duplicate InvalidParamsError

**File:** `rpc/global_dispatcher.py`
```python
# Remove local class, import from dispatcher
from nexus3.rpc.dispatcher import InvalidParamsError
```

---

## 5R.5.4: Remove Dead Code (cli/output.py)

**Action:** Delete `nexus3/cli/output.py` (no imports found in codebase)

---

## 5R.5.5: Implement verbose/raw_log Parameters

**File:** `cli/repl.py`
```python
streams = LogStream.MARKDOWN
if verbose:
    streams |= LogStream.THINKING
if raw_log:
    streams |= LogStream.RAW
```

---

## 5R.5.6: Add Provider Retry Logic

**File:** `provider/openrouter.py`

```python
MAX_RETRIES = 3
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

async def _retry_request(self, operation, request_func, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await request_func()
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            if attempt == max_retries - 1:
                raise ProviderError(f"{operation} failed after {max_retries} attempts")
            delay = min(2 ** attempt + random.uniform(0, 1), 10)
            await asyncio.sleep(delay)
```

---

## 5R.5.7: Make max_iterations Configurable

**File:** `config/schema.py`
```python
max_tool_iterations: int = 10
```

**File:** `session/session.py`
```python
def __init__(self, ..., max_tool_iterations: int = 10):
    self.max_tool_iterations = max_tool_iterations

async def _execute_tool_loop_streaming(self, ...):
    for _ in range(self.max_tool_iterations):  # Use configurable value
```

---

# Implementation Schedule

## Recommended Order

1. **Phase 5R.5: Minor Fixes** (Low risk, quick wins)
2. **Phase 5R.1: Security Hardening** (Critical blockers)
3. **Phase 5R.2: Data Integrity** (Correctness issues)
4. **Phase 5R.3: Async/Performance** (Performance issues)
5. **Phase 5R.4: Test Coverage** (Can run in parallel)

## File Change Summary

### New Files to Create (8)
- `nexus3/rpc/auth.py`
- `nexus3/core/sandbox.py`
- `nexus3/core/url_validator.py`
- `nexus3/rpc/log_multiplexer.py`
- `tests/unit/test_http_auth.py`
- `tests/unit/test_sandbox.py`
- `tests/unit/test_url_validator.py`
- `tests/unit/test_context_manager.py`

### Files to Modify (15+)
- `nexus3/config/schema.py`
- `nexus3/rpc/http.py`
- `nexus3/rpc/pool.py`
- `nexus3/rpc/dispatcher.py`
- `nexus3/rpc/global_dispatcher.py`
- `nexus3/cli/serve.py`
- `nexus3/cli/repl.py`
- `nexus3/skill/builtin/read_file.py`
- `nexus3/skill/builtin/write_file.py`
- `nexus3/skill/builtin/nexus_send.py`
- `nexus3/context/manager.py`
- `nexus3/session/session.py`
- `nexus3/session/markdown.py`
- `nexus3/provider/openrouter.py`
- `nexus3/core/__init__.py`

### Files to Delete (1)
- `nexus3/cli/output.py`

---

# Risk Assessment

| Change | Risk | Mitigation |
|--------|------|------------|
| HTTP Auth | Low | Disabled by default |
| Path Sandbox | Low | Defaults to CWD (current behavior) |
| URL Validation | Low | Defaults to localhost only |
| Truncation Refactor | Medium | Comprehensive unit tests |
| Async File I/O | Low | Standard Python pattern |
| Log Multiplexer | Medium | contextvars are well-tested |
| Provider Retry | Medium | Test edge cases thoroughly |

---

# Verification Checklist

After implementation, verify:

```bash
# All tests pass
pytest tests/ -v

# No linting errors
ruff check nexus3/

# Type checking passes
mypy nexus3/

# Security tests specifically
pytest tests/unit/test_sandbox.py tests/unit/test_url_validator.py tests/unit/test_http_auth.py -v

# Integration tests
pytest tests/integration/ -v
```

---

*Plan generated by Claude Opus 4.5 from analysis of 21 code review documents.*
