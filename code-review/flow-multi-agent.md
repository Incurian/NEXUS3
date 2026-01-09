# Multi-Agent Lifecycle Code Review

**Reviewer:** Code Review Agent
**Date:** 2026-01-08
**Files Reviewed:**
- `/home/inc/repos/NEXUS3/nexus3/rpc/pool.py`
- `/home/inc/repos/NEXUS3/nexus3/rpc/global_dispatcher.py`
- `/home/inc/repos/NEXUS3/nexus3/rpc/http.py`
- `/home/inc/repos/NEXUS3/nexus3/cli/serve.py`
- `/home/inc/repos/NEXUS3/nexus3/rpc/dispatcher.py`
- `/home/inc/repos/NEXUS3/nexus3/session/session.py`
- `/home/inc/repos/NEXUS3/nexus3/session/logging.py`
- `/home/inc/repos/NEXUS3/nexus3/session/storage.py`
- `/home/inc/repos/NEXUS3/nexus3/context/manager.py`

---

## Lifecycle Diagram

```
                            CLIENT REQUEST
                                  |
                                  v
                         +----------------+
                         |  HTTP Server   |
                         |   (http.py)    |
                         +----------------+
                                  |
              +-------------------+-------------------+
              |                                       |
        POST / or /rpc                         POST /agent/{id}
              |                                       |
              v                                       v
     +-----------------+                    +------------------+
     | GlobalDispatcher|                    | AgentPool.get()  |
     +-----------------+                    +------------------+
              |                                       |
   +----------+----------+                   404 if not found
   |          |          |                            |
create   destroy     list                             v
   |          |          |                    +----------------+
   v          v          v                    | Agent.dispatcher|
+------+  +------+  +--------+               +----------------+
|Pool  |  |Pool  |  | Return |                        |
|create|  |destroy|  | list  |               send/cancel/shutdown
+------+  +------+  +--------+                        |
   |          |                                       v
   |          |                              +----------------+
   |          +---> logger.close()           |    Session     |
   |                                         +----------------+
   v
+------------------+
| Agent Components |
+------------------+
| - SessionLogger  |
| - ContextManager |
| - ServiceContainer|
| - SkillRegistry  |
| - Session        |
| - Dispatcher     |
+------------------+


SHUTDOWN FLOW:
==============
                    All Dispatchers.should_shutdown == True
                                    |
                                    v
                          pool.should_shutdown == True
                                    |
                                    v
                        HTTP Server polling loop exits
                                    |
                                    v
                          run_serve() finally block
                                    |
                                    v
                       pool.destroy() for each agent
                                    |
                                    v
                          logger.close() called
```

---

## 1. Agent Creation and Initialization

### Flow Analysis

**Entry Point:** `GlobalDispatcher._handle_create_agent()` (line 138-180)

```python
config = AgentConfig(agent_id=agent_id, system_prompt=system_prompt)
agent = await self._pool.create(agent_id=agent_id, config=config)
```

**AgentPool.create()** (pool.py, lines 179-285):
1. Acquires async lock
2. Resolves effective agent_id (config > parameter > auto-generated)
3. Checks for duplicate IDs
4. Creates agent-specific log directory
5. Initializes SessionLogger with LogConfig
6. Wires raw logging callback to provider (if supported)
7. Loads system prompt (custom or from prompt_loader)
8. Creates ContextManager
9. Creates ServiceContainer and SkillRegistry
10. Creates Session with all dependencies
11. Creates Dispatcher with session and context
12. Stores agent in pool dictionary

### Issues Identified

#### CRITICAL: Raw Log Callback Race Condition (pool.py:226-232)

```python
raw_callback = logger.get_raw_log_callback()
if raw_callback is not None:
    provider = self._shared.provider
    if hasattr(provider, "set_raw_log_callback"):
        provider.set_raw_log_callback(raw_callback)
```

**Problem:** The shared provider has its raw log callback overwritten by each newly created agent. This means:
- All agents share one provider instance
- Each agent sets its own callback on the shared provider
- Only the most recently created agent receives raw logging
- Previous agents lose their raw logging silently

**Impact:** High - logging integrity compromised in multi-agent scenarios.

**Recommendation:** Either:
1. Create separate provider instances per agent (expensive)
2. Implement a callback multiplexer that routes to the correct agent
3. Remove raw logging support from multi-agent mode
4. Add agent_id to callback and filter at the provider level

#### MEDIUM: Agent ID from Both Parameter and Config (pool.py:208)

```python
effective_id = effective_config.agent_id or agent_id or uuid4().hex[:8]
```

**Problem:** The `create()` method accepts `agent_id` both as a direct parameter AND inside `config.agent_id`. The code uses config first, which may surprise callers.

```python
# This ignores agent_id="foo", uses "bar" instead
await pool.create(agent_id="foo", config=AgentConfig(agent_id="bar"))
```

**Recommendation:** Either:
1. Remove the direct `agent_id` parameter (breaking change)
2. Document precedence clearly
3. Raise error if both are provided with different values

#### LOW: No Validation on Agent ID Format

**Problem:** Agent IDs can contain any characters including `/`, which could cause routing issues:
```python
# Creates agent with ID "foo/bar"
await pool.create(agent_id="foo/bar")
# URL becomes /agent/foo/bar - ambiguous routing
```

The `_extract_agent_id()` function returns everything after `/agent/`, so `/agent/foo/bar` returns `"foo/bar"` as the agent_id, which happens to work but is fragile.

**Recommendation:** Validate agent IDs against a pattern (alphanumeric + hyphen + underscore).

---

## 2. Resource Sharing vs Isolation

### Shared Components (Correct Design)

| Component | Sharing Status | Notes |
|-----------|----------------|-------|
| `Config` | Shared | Immutable, correct |
| `AsyncProvider` | Shared | Connection pooling benefit |
| `PromptLoader` | Shared | Read-only, correct |
| `base_log_dir` | Shared | Path only, correct |

### Per-Agent Components (Correct Design)

| Component | Isolation | Notes |
|-----------|-----------|-------|
| `SessionLogger` | Isolated | Own log directory |
| `ContextManager` | Isolated | Own conversation history |
| `ServiceContainer` | Isolated | Own service instances |
| `SkillRegistry` | Isolated | Own tool registrations |
| `Session` | Isolated | Own callbacks, pending tools |
| `Dispatcher` | Isolated | Own active requests dict |

### Issues Identified

#### HIGH: Provider Raw Callback Sharing Issue

Already discussed above - the shared provider can only have one raw log callback.

#### MEDIUM: No Resource Limits Per Agent

**Problem:** There are no limits on:
- Number of agents that can be created
- Memory usage per agent
- Context window tokens per agent (uses global config)
- Active requests per agent

**Impact:** A malicious or buggy client could exhaust server resources by creating unlimited agents.

**Recommendation:** Add configurable limits:
```python
@dataclass
class PoolConfig:
    max_agents: int = 100
    max_tokens_per_agent: int = 8000
    max_concurrent_requests_per_agent: int = 5
```

#### LOW: Prompt Loader Called Per Agent

**Problem:** Each agent creation calls `prompt_loader.load()` which reads files from disk:
```python
loaded_prompt = self._shared.prompt_loader.load(is_repl=False)
```

**Impact:** Minor performance issue if creating many agents rapidly.

**Recommendation:** Cache the loaded prompt in `SharedComponents` if system prompts don't change.

---

## 3. Agent Destruction and Cleanup

### Flow Analysis

**Entry Point:** `GlobalDispatcher._handle_destroy_agent()` (lines 182-216)

```python
success = await self._pool.destroy(agent_id)
```

**AgentPool.destroy()** (pool.py, lines 287-310):
```python
async with self._lock:
    agent = self._agents.pop(agent_id, None)
    if agent is None:
        return False
    agent.logger.close()
    return True
```

### Issues Identified

#### CRITICAL: In-Progress Requests Not Cancelled on Destroy

**Problem:** When an agent is destroyed, any in-progress requests continue executing:
```python
# Dispatcher tracks active requests
self._active_requests: dict[str, CancellationToken] = {}

# But destroy() doesn't cancel them
async def destroy(self, agent_id: str) -> bool:
    agent = self._agents.pop(agent_id, None)
    if agent is None:
        return False
    agent.logger.close()  # Only closes logger
    return True
```

**Impact:**
- Orphaned requests continue consuming resources
- Provider calls continue after agent "destroyed"
- Session callbacks may fire on destroyed agent
- Potential crashes if callbacks reference freed objects

**Recommendation:** Add cancellation of active requests:
```python
async def destroy(self, agent_id: str) -> bool:
    async with self._lock:
        agent = self._agents.pop(agent_id, None)
        if agent is None:
            return False

        # Cancel all active requests
        for token in agent.dispatcher._active_requests.values():
            token.cancel()

        agent.logger.close()
        return True
```

#### HIGH: ContextManager Has No Cleanup Method

**Problem:** `ContextManager` has no `close()` method, but holds references to:
- SessionLogger
- Token counter
- Messages list

```python
class ContextManager:
    def __init__(self, ...):
        self._counter = token_counter or get_token_counter()
        self._logger = logger
        self._messages: list[Message] = []
```

**Impact:** Memory not explicitly freed; relies on Python GC.

**Recommendation:** Add `close()` or `clear()` method to ContextManager.

#### MEDIUM: Session Has No Cleanup

**Problem:** `Session` holds callbacks and pending cancelled tools that aren't cleaned up:
```python
class Session:
    def __init__(self, ...):
        self._pending_cancelled_tools: list[tuple[str, str]] = []
```

**Recommendation:** Add cleanup method to Session.

#### LOW: ServiceContainer Contents Not Cleaned

**Problem:** ServiceContainer may hold references to services that need cleanup.

---

## 4. Concurrent Agent Operations

### Thread Safety Analysis

#### Lock Usage (pool.py)

```python
def __init__(self, shared: SharedComponents) -> None:
    self._lock = asyncio.Lock()

async def create(self, ...) -> Agent:
    async with self._lock:
        # ... creation logic

async def destroy(self, agent_id: str) -> bool:
    async with self._lock:
        # ... destruction logic
```

**Good:** Create and destroy are protected by async lock.

### Issues Identified

#### HIGH: `get()` and `list()` Not Lock-Protected

**Problem:** Read operations are not protected:
```python
def get(self, agent_id: str) -> Agent | None:
    return self._agents.get(agent_id)  # No lock!

def list(self) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for agent in self._agents.values():  # No lock!
        result.append({...})
    return result
```

**Impact:** Race conditions possible:
- `get()` during `destroy()` may return agent being destroyed
- `list()` during concurrent modifications may iterate stale data
- `list()` iteration may raise RuntimeError if dict changes

**Scenario:**
```
Task 1: list() starts iterating
Task 2: create() adds new agent
Task 1: may or may not see new agent, dict size changed
```

**Recommendation:** Either:
1. Add lock to read operations (performance cost)
2. Copy dict before iteration in `list()`
3. Use `asyncio.Lock` for writes, accept eventual consistency for reads

#### MEDIUM: should_shutdown Property Races

```python
@property
def should_shutdown(self) -> bool:
    if not self._agents:
        return False
    return all(agent.dispatcher.should_shutdown for agent in self._agents.values())
```

**Problem:** Not lock-protected, iterates over mutable dict.

#### MEDIUM: Dispatcher Active Requests Not Thread-Safe

```python
class Dispatcher:
    async def _handle_send(self, params: dict[str, Any]) -> dict[str, Any]:
        self._active_requests[request_id] = token  # No lock
        try:
            ...
        finally:
            self._active_requests.pop(request_id, None)  # No lock

    async def _handle_cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        token = self._active_requests.get(request_id)  # No lock
```

**Impact:** Concurrent send/cancel operations may have race conditions. Python's GIL helps somewhat, but with async code, this is still risky.

---

## 5. Memory Management

### Memory Lifecycle

| Phase | Memory Allocated | Memory Freed |
|-------|-----------------|--------------|
| Server Start | SharedComponents | Server shutdown |
| Agent Create | Agent + all components | Agent destroy |
| Message Send | Messages, tool calls | Never (context history) |
| Destroy | - | Logger closed, agent removed |

### Issues Identified

#### HIGH: Messages Never Garbage Collected

**Problem:** Context messages accumulate without bound:
```python
class ContextManager:
    def add_user_message(self, content: str) -> None:
        msg = Message(role=Role.USER, content=content)
        self._messages.append(msg)  # Never removed
```

Truncation only affects API calls, not the internal list:
```python
def _get_context_messages(self) -> list[Message]:
    # Returns truncated copy, but self._messages keeps growing
```

**Impact:** Long-running agents will eventually OOM.

**Recommendation:** Add actual message eviction or compaction to ContextManager.

#### MEDIUM: SQLite Database Per Agent

Each agent creates its own SQLite database:
```python
self.storage = SessionStorage(self.info.session_dir / "session.db")
```

**Consideration:** SQLite connections and files accumulate. The `close()` method exists but relies on explicit cleanup.

#### LOW: Tool Definitions Copied Repeatedly

```python
context.set_tool_definitions(registry.get_definitions())
```

Tool definitions are copied to context. If definitions are large and many agents exist, this wastes memory.

---

## 6. Edge Cases

### Duplicate Agent IDs

**Handled Correctly:**
```python
if effective_id in self._agents:
    raise ValueError(f"Agent already exists: {effective_id}")
```

### Missing Agent Lookup

**HTTP Layer (http.py:274-283):**
```python
agent = pool.get(agent_id)
if agent is None:
    await send_http_response(
        writer,
        404,
        f'{{"error": "Agent not found: {agent_id}"}}',
    )
    return
```

**Good:** Returns 404, doesn't crash.

### Destroy Non-Existent Agent

**Handled Correctly:**
```python
async def destroy(self, agent_id: str) -> bool:
    agent = self._agents.pop(agent_id, None)
    if agent is None:
        return False  # Returns False, no error
```

### Empty Pool Shutdown Check

```python
@property
def should_shutdown(self) -> bool:
    if not self._agents:
        return False  # Empty pool doesn't trigger shutdown
```

**Good:** Prevents shutdown when pool is empty.

### Notification Handling

Both dispatchers correctly handle JSON-RPC notifications (no `id`):
```python
if request.id is None:
    return None  # Notifications don't get responses
```

### Issues Identified

#### HIGH: Agent ID with Slashes (Already Mentioned)

Path `/agent/foo/bar` extracts `"foo/bar"` as agent_id, which works but is fragile.

#### MEDIUM: Create Agent with Empty String ID

```python
effective_id = effective_config.agent_id or agent_id or uuid4().hex[:8]
```

Empty string `""` is falsy, so:
```python
await pool.create(agent_id="")  # Gets auto-generated ID
```

This might be unexpected - user explicitly passed empty string.

#### MEDIUM: Concurrent Creates with Same Auto-ID (Unlikely)

```python
effective_id = ... or uuid4().hex[:8]
```

UUID collision is astronomically unlikely in 8 chars, but two concurrent creates could theoretically collide. The lock prevents the race, but both would generate their IDs before acquiring the lock.

**Actually Not an Issue:** The check happens inside the lock:
```python
async with self._lock:
    effective_id = ... or uuid4().hex[:8]
    if effective_id in self._agents:
        raise ValueError(...)
```

Wait, no - ID generation is inside the lock. This is safe.

#### LOW: Destroy During Serve Shutdown

```python
# serve.py
finally:
    for agent_info in pool.list():
        await pool.destroy(agent_info["agent_id"])
```

If an agent is destroyed between `list()` and `destroy()`, the destroy will return False silently. This is harmless but could be logged.

---

## 7. Additional Observations

### Good Practices Found

1. **Frozen SharedComponents:** Using `@dataclass(frozen=True)` prevents accidental mutation.

2. **Security-Conscious Binding:** HTTP server enforces localhost-only binding:
   ```python
   if host not in ("127.0.0.1", "localhost", "::1"):
       raise ValueError("Security: HTTP server must bind to localhost only")
   ```

3. **Graceful HTTP Errors:** All error paths return proper HTTP status codes and JSON error bodies.

4. **Timeout Protection:** HTTP request reading has 30-second timeouts.

5. **Body Size Limit:** `MAX_BODY_SIZE = 1_048_576` prevents DoS via large requests.

6. **Type Validation in Handlers:** Parameters are validated:
   ```python
   if agent_id is not None and not isinstance(agent_id, str):
       raise InvalidParamsError(...)
   ```

### Missing Features

1. **No Agent Timeout/TTL:** Agents live forever until explicitly destroyed.

2. **No Heartbeat/Health Check:** No way to detect if an agent is stuck or unresponsive.

3. **No Metrics/Monitoring:** No exposure of agent count, memory usage, etc.

4. **No Rate Limiting:** Clients can spam create/destroy/send requests.

---

## Summary of Issues by Severity

### Critical (3)

1. **Raw Log Callback Race Condition** - Only last agent gets raw logging
2. **In-Progress Requests Not Cancelled on Destroy** - Orphaned resources
3. **Messages Never Garbage Collected** - Memory leak over time

### High (3)

1. **ContextManager Has No Cleanup** - Memory not explicitly freed
2. **`get()` and `list()` Not Lock-Protected** - Race conditions
3. **Agent ID with Slashes** - Routing ambiguity

### Medium (6)

1. **Agent ID from Both Parameter and Config** - Confusing API
2. **No Resource Limits Per Agent** - DoS potential
3. **`should_shutdown` Property Races** - Read without lock
4. **Dispatcher Active Requests Not Thread-Safe** - Race in cancel
5. **Create Agent with Empty String ID** - Unexpected behavior
6. **Session Has No Cleanup** - Callbacks not cleared

### Low (5)

1. **No Validation on Agent ID Format** - Special characters allowed
2. **Prompt Loader Called Per Agent** - Minor performance
3. **ServiceContainer Contents Not Cleaned** - Relies on GC
4. **Tool Definitions Copied** - Memory inefficiency
5. **Silent Destroy During Shutdown** - No logging

---

## Recommendations Summary

1. **Immediate:** Fix raw log callback sharing - this breaks logging integrity.

2. **High Priority:** Cancel active requests on agent destroy.

3. **High Priority:** Add lock protection to read operations or accept eventual consistency.

4. **Medium Priority:** Add agent ID validation (alphanumeric pattern).

5. **Medium Priority:** Add resource limits (max agents, max tokens).

6. **Medium Priority:** Implement actual context compaction (not just truncation for API).

7. **Low Priority:** Add cleanup methods to ContextManager and Session.

8. **Future:** Consider agent TTL, health checks, and metrics endpoints.

---

## Test Coverage Notes

The test file (`tests/unit/test_pool.py`) covers:
- SharedComponents immutability
- AgentConfig defaults and parameters
- Agent creation with explicit/auto IDs
- Duplicate ID rejection
- Agent lookup and destruction
- List functionality
- Shutdown flag behavior
- GlobalDispatcher RPC methods
- Path extraction helper

**Missing Test Coverage:**
- Concurrent operations (create/destroy/get race conditions)
- Raw logging with multiple agents
- Destroy with active requests
- Memory growth over time
- Large number of agents
- HTTP routing edge cases
