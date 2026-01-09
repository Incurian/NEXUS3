# Code Review: Dependency Injection Patterns

**Project:** NEXUS3
**Reviewer:** Code Review Agent
**Date:** 2026-01-08
**Focus:** Dependency injection patterns, service lifecycle, and testability

---

## Executive Summary

NEXUS3 employs a pragmatic, minimalist approach to dependency injection. The system uses three primary DI patterns:

1. **ServiceContainer** - A simple key-value service locator
2. **SkillRegistry** - Factory-based lazy instantiation with DI
3. **SharedComponents** - Immutable frozen dataclass for cross-agent sharing

The implementation prioritizes simplicity over sophistication. While this keeps cognitive overhead low, several opportunities exist for improved type safety, lifecycle management, and testability.

**Overall Assessment:** Good foundation with room for improvement. The patterns are consistent but lack the robustness needed for complex multi-agent scenarios.

---

## 1. DI Pattern Consistency

### Current Patterns

#### Pattern A: ServiceContainer (Service Locator)
Location: `/home/inc/repos/NEXUS3/nexus3/skill/services.py`

```python
@dataclass
class ServiceContainer:
    _services: dict[str, Any] = field(default_factory=dict)

    def get(self, name: str) -> Any:
        return self._services.get(name)

    def require(self, name: str) -> Any:
        if name not in self._services:
            raise KeyError(f"Required service not registered: {name}")
        return self._services[name]
```

#### Pattern B: Factory Functions
Location: `/home/inc/repos/NEXUS3/nexus3/skill/registry.py`

```python
SkillFactory = Callable[[ServiceContainer], Skill]

class SkillRegistry:
    def __init__(self, services: ServiceContainer | None = None) -> None:
        self._services = services or ServiceContainer()
        self._factories: dict[str, SkillFactory] = {}
        self._instances: dict[str, Skill] = {}  # Lazy cache
```

#### Pattern C: SharedComponents (Frozen Dataclass)
Location: `/home/inc/repos/NEXUS3/nexus3/rpc/pool.py`

```python
@dataclass(frozen=True)
class SharedComponents:
    config: Config
    provider: AsyncProvider
    prompt_loader: PromptLoader
    base_log_dir: Path
```

### Consistency Analysis

| Aspect | ServiceContainer | SharedComponents | Direct Constructor |
|--------|------------------|------------------|-------------------|
| Type Safety | Low (Any) | High (typed fields) | High |
| Discovery | String keys | Property access | Constructor signature |
| Used By | Skills | AgentPool | Session, Dispatcher |

**Issue:** The codebase mixes three different dependency provision mechanisms:

1. `ServiceContainer` for skills (string-keyed, runtime resolution)
2. `SharedComponents` for pool (compile-time typed)
3. Direct constructor injection for Session, Dispatcher, ContextManager

This inconsistency creates cognitive overhead. Developers must understand which pattern applies where.

### Recommendation

Adopt a unified approach. Options:

**Option A:** Expand SharedComponents pattern to all major components
```python
@dataclass(frozen=True)
class SkillDependencies:
    agent_pool: AgentPool | None
    sandbox: Sandbox | None
    logger: SessionLogger
```

**Option B:** Add typed accessors to ServiceContainer
```python
class ServiceContainer:
    def get_agent_pool(self) -> AgentPool | None:
        return self._services.get("agent_pool")
```

---

## 2. Service Lifecycle Management

### Current State

**ServiceContainer:** No lifecycle management
```python
def register(self, name: str, service: Any) -> None:
    """Overwrites any existing service with the same name."""
    self._services[name] = service
```

**SkillRegistry:** Lazy instantiation with permanent caching
```python
def get(self, name: str) -> Skill | None:
    if name not in self._instances:
        factory = self._factories.get(name)
        if factory:
            self._instances[name] = factory(self._services)
    return self._instances.get(name)
```

**AgentPool:** Manual cleanup in destroy()
```python
async def destroy(self, agent_id: str) -> bool:
    async with self._lock:
        agent = self._agents.pop(agent_id, None)
        if agent is None:
            return False
        agent.logger.close()  # Manual cleanup
        return True
```

### Problems Identified

1. **No Service Disposal:** `ServiceContainer.clear()` doesn't call cleanup methods on services
   ```python
   def clear(self) -> None:
       """Unregister all services."""
       self._services.clear()  # Services with open connections are leaked
   ```

2. **No Scope Support:** All skills are singletons per registry. No per-request or per-conversation scoping.

3. **Inconsistent Cleanup:** AgentPool manually closes logger, but Session doesn't clean up its dependencies.

4. **Skills are never disposed:** Cached skill instances live forever
   ```python
   # In registry.py - instances are never cleaned up
   self._instances: dict[str, Skill] = {}  # Never cleared
   ```

### Recommendations

**Add Disposable protocol:**
```python
from typing import Protocol

class Disposable(Protocol):
    async def dispose(self) -> None: ...

class ServiceContainer:
    async def clear(self) -> None:
        """Unregister all services, disposing those that support it."""
        for service in self._services.values():
            if isinstance(service, Disposable):
                await service.dispose()
        self._services.clear()
```

**Add scope markers:**
```python
class ServiceScope(Enum):
    SINGLETON = "singleton"
    PER_AGENT = "per_agent"
    TRANSIENT = "transient"
```

---

## 3. Testability Analysis

### Strengths

1. **Factory pattern enables mocking:** Tests can inject custom factories
   ```python
   # From test_skill_execution.py
   registry.register("echo", lambda _: echo_skill)
   ```

2. **Optional dependencies:** Most constructors accept None
   ```python
   def __init__(
       self,
       provider: AsyncProvider,
       context: "ContextManager | None" = None,
       logger: "SessionLogger | None" = None,
       registry: "SkillRegistry | None" = None,
   ) -> None:
   ```

3. **Interface-based design:** AsyncProvider is a Protocol, enabling mock providers
   ```python
   class MockProviderWithTools:
       async def stream(self, messages, tools) -> AsyncIterator[StreamEvent]:
           # ... test implementation
   ```

### Weaknesses

1. **ServiceContainer returns Any:** Tests can't verify type correctness
   ```python
   def get(self, name: str) -> Any:  # No type hints for specific services
   ```

2. **Global state in registration:** `register_builtin_skills()` modifies registry globally
   ```python
   # registration.py
   def register_builtin_skills(registry: SkillRegistry) -> None:
       registry.register("read_file", read_file_factory)
       registry.register("write_file", write_file_factory)
       # ... more
   ```

3. **Hard to isolate AgentPool tests:** `create()` method has 50+ lines of wiring code
   ```python
   async def create(self, ...) -> Agent:
       # 70 lines of direct instantiation
       logger = SessionLogger(log_config)
       context = ContextManager(...)
       services = ServiceContainer()
       registry = SkillRegistry(services)
       register_builtin_skills(registry)  # Side effect
       session = Session(...)
       dispatcher = Dispatcher(...)
       # ...
   ```

### Recommendations

**Extract agent factory:**
```python
class AgentFactory:
    def __init__(self, shared: SharedComponents):
        self._shared = shared

    def create_logger(self, agent_id: str) -> SessionLogger:
        # Mockable
        ...

    def create_registry(self, services: ServiceContainer) -> SkillRegistry:
        # Mockable - can skip builtin registration in tests
        ...
```

**Add type-safe service registration:**
```python
# Using TypeVar for type-safe get
T = TypeVar("T")

class ServiceContainer:
    def get_typed(self, name: str, expected_type: type[T]) -> T | None:
        service = self._services.get(name)
        if service is None or not isinstance(service, expected_type):
            return None
        return service
```

---

## 4. Circular Dependency Prevention

### Current Mechanisms

1. **TYPE_CHECKING imports:** Used consistently throughout
   ```python
   # pool.py
   if TYPE_CHECKING:
       from nexus3.config.schema import Config
       from nexus3.context.prompt_loader import PromptLoader
       from nexus3.core.interfaces import AsyncProvider
   ```

2. **Lazy imports in factories:** Skills avoid importing dependencies until needed
   ```python
   # pool.py line 250-251
   async def create(self, ...):
       # Import here to avoid circular import (skills -> client -> rpc -> pool)
       from nexus3.skill.builtin import register_builtin_skills
   ```

3. **String-based service lookup:** Avoids import-time dependencies
   ```python
   pool = services.get("agent_pool")  # No import of AgentPool needed
   ```

### Issues Identified

1. **Comment-documented cycle:** There's an explicit cycle that's worked around
   ```python
   # pool.py line 250
   # Import here to avoid circular import (skills -> client -> rpc -> pool)
   ```

   This indicates architectural coupling that should be addressed.

2. **Skills depend on NexusClient:** Creates tight coupling
   ```python
   # nexus_send.py
   from nexus3.client import ClientError, NexusClient
   ```

### Recommendations

**Invert the dependency:** Skills should receive a client interface, not import it directly
```python
# Define interface
class AgentCommunicator(Protocol):
    async def send(self, url: str, content: str) -> dict[str, Any]: ...

# Inject via ServiceContainer
class NexusSendSkill:
    def __init__(self, communicator: AgentCommunicator):
        self._communicator = communicator
```

---

## 5. Configuration Injection

### Current Approach

Configuration flows through explicit constructor parameters:

```python
# serve.py
config = load_config()
provider = OpenRouterProvider(config.provider)
shared = SharedComponents(
    config=config,
    provider=provider,
    prompt_loader=prompt_loader,
    base_log_dir=base_log_dir,
)
```

### Strengths

1. **Explicit wiring:** Easy to trace where config comes from
2. **No hidden globals:** Config is passed, not imported
3. **Fail-fast loading:** `load_config()` validates at startup

### Weaknesses

1. **Config not available to skills:** ServiceContainer doesn't include config by default
   ```python
   # pool.py create() method
   services = ServiceContainer()
   registry = SkillRegistry(services)
   # Config is in self._shared but not registered in services
   ```

2. **Skills can't configure themselves:** No mechanism for skill-specific config
   ```python
   # read_file.py - no config access
   def read_file_factory(services: ServiceContainer) -> ReadFileSkill:
       return ReadFileSkill()  # No way to pass config like max_file_size
   ```

### Recommendations

**Register config in ServiceContainer:**
```python
async def create(self, ...) -> Agent:
    services = ServiceContainer()
    services.register("config", self._shared.config)
    services.register("base_log_dir", self._shared.base_log_dir)
    # ...
```

**Support skill-specific config:**
```python
@dataclass
class SkillConfig:
    read_file: ReadFileConfig | None = None
    write_file: WriteFileConfig | None = None
    # ...

# In factory
def read_file_factory(services: ServiceContainer) -> ReadFileSkill:
    skill_config = services.get("skill_config")
    if skill_config and skill_config.read_file:
        return ReadFileSkill(max_size=skill_config.read_file.max_size)
    return ReadFileSkill()
```

---

## 6. Service Discovery Patterns

### Current State

Service discovery is implicit. Skills must know magic strings:

```python
# In a skill factory
pool = services.get("agent_pool")
sandbox = services.get("sandbox")
```

No documentation of what services might be available.

### Problems

1. **No service catalog:** No way to list expected services
2. **No validation:** Misspelled keys fail silently
   ```python
   pool = services.get("agent_pol")  # Returns None, no error
   ```
3. **No dependency declaration:** Skills don't declare what they need

### Recommendations

**Add service keys enum:**
```python
class ServiceKey(str, Enum):
    AGENT_POOL = "agent_pool"
    SANDBOX = "sandbox"
    CONFIG = "config"
    LOGGER = "logger"

class ServiceContainer:
    def get(self, key: ServiceKey | str) -> Any:
        name = key.value if isinstance(key, ServiceKey) else key
        return self._services.get(name)
```

**Skill dependency declaration:**
```python
class Skill(Protocol):
    @property
    def required_services(self) -> list[ServiceKey]:
        """Services this skill requires."""
        return []

    @property
    def optional_services(self) -> list[ServiceKey]:
        """Services this skill can use if available."""
        return []
```

**Registry validation:**
```python
def get(self, name: str) -> Skill | None:
    if name not in self._instances:
        factory = self._factories.get(name)
        if factory:
            skill = factory(self._services)
            # Validate required services
            for key in skill.required_services:
                if not self._services.has(key.value):
                    raise MissingServiceError(name, key)
            self._instances[name] = skill
    return self._instances.get(name)
```

---

## 7. Specific Code Issues

### Issue 1: Unused ServiceContainer parameter
Location: `/home/inc/repos/NEXUS3/nexus3/skill/builtin/read_file.py`

```python
def read_file_factory(services: ServiceContainer) -> ReadFileSkill:
    """Factory function for ReadFileSkill.

    Args:
        services: ServiceContainer (unused, but required by factory protocol)
    """
    return ReadFileSkill()
```

**Problem:** The `services` parameter is documented as unused. This is a code smell - either the factory should use services, or the factory signature should be optional.

**Impact:** Low - Documentation makes intent clear.

### Issue 2: No error handling in unregister
Location: `/home/inc/repos/NEXUS3/nexus3/skill/services.py`

```python
def unregister(self, name: str) -> Any:
    """Unregister a service by name."""
    return self._services.pop(name, None)
```

**Problem:** Returns None for both "service was None" and "service didn't exist".

**Recommendation:**
```python
def unregister(self, name: str) -> Any:
    if name not in self._services:
        raise KeyError(f"Cannot unregister: service not found: {name}")
    return self._services.pop(name)
```

### Issue 3: AgentPool.create() is too long
Location: `/home/inc/repos/NEXUS3/nexus3/rpc/pool.py` lines 179-285

The `create()` method is 106 lines and handles:
- ID generation
- Duplicate checking
- Logger creation
- Raw callback wiring
- System prompt loading
- Context creation
- Service container setup
- Registry creation
- Skill registration
- Tool definition injection
- Session creation
- Dispatcher creation
- Agent instantiation

**Recommendation:** Extract into smaller methods or an AgentBuilder class.

### Issue 4: Callback explosion in Session
Location: `/home/inc/repos/NEXUS3/nexus3/session/session.py`

```python
def __init__(
    self,
    provider: AsyncProvider,
    context: "ContextManager | None" = None,
    logger: "SessionLogger | None" = None,
    registry: "SkillRegistry | None" = None,
    on_tool_call: ToolCallCallback | None = None,
    on_tool_complete: ToolCompleteCallback | None = None,
    on_reasoning: ReasoningCallback | None = None,
    on_batch_start: BatchStartCallback | None = None,
    on_tool_active: ToolActiveCallback | None = None,
    on_batch_progress: BatchProgressCallback | None = None,
    on_batch_halt: BatchHaltCallback | None = None,
    on_batch_complete: BatchCompleteCallback | None = None,
) -> None:
```

**Problem:** 8 callback parameters make the constructor unwieldy and hard to test.

**Recommendation:** Use an observer pattern or event emitter:
```python
class SessionCallbacks:
    on_tool_call: ToolCallCallback | None = None
    on_tool_complete: ToolCompleteCallback | None = None
    # ...

class Session:
    def __init__(
        self,
        provider: AsyncProvider,
        context: ContextManager | None = None,
        logger: SessionLogger | None = None,
        registry: SkillRegistry | None = None,
        callbacks: SessionCallbacks | None = None,
    ) -> None:
```

---

## 8. Testing Impact Assessment

| Component | Current Testability | Issues |
|-----------|---------------------|--------|
| ServiceContainer | High | Returns Any, no validation |
| SkillRegistry | High | Factory pattern works well |
| Session | Medium | Too many constructor params |
| AgentPool | Low | 106-line create() method |
| Dispatcher | High | Clean constructor injection |
| SharedComponents | High | Immutable, typed |

---

## Summary of Recommendations

### High Priority

1. **Add service disposal support** to prevent resource leaks
2. **Extract AgentPool.create() into smaller methods** for testability
3. **Register config in ServiceContainer** so skills can access configuration

### Medium Priority

4. **Add ServiceKey enum** for type-safe service discovery
5. **Consolidate callback parameters** into a SessionCallbacks object
6. **Invert NexusClient dependency** to break the circular import cycle

### Low Priority

7. **Add typed accessors to ServiceContainer** for common services
8. **Add scope support** for per-agent vs singleton services
9. **Document service contracts** (what services are available where)

---

## Conclusion

NEXUS3's dependency injection is pragmatic and largely effective. The minimalist ServiceContainer approach keeps complexity low, and the factory pattern for skills provides good flexibility.

The main areas for improvement are:
- Lifecycle management (disposal, scopes)
- Type safety (avoiding `Any`)
- Large method extraction (AgentPool.create)
- Reducing constructor parameter counts

The codebase successfully avoids common DI pitfalls like hidden globals, service locator anti-pattern abuse, and circular dependencies (mostly). The explicit wiring in `repl.py` and `serve.py` makes the dependency graph traceable.

For Phase 5 (Subagent Spawning), the current DI infrastructure should handle the basics, but lifecycle management will become critical when subagents need cleanup coordination.
