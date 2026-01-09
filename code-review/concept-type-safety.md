# Type Safety and Protocols Review

**Reviewer:** Code Review Agent
**Date:** 2026-01-08
**Scope:** Type annotations, Protocols, dataclasses, and type safety patterns across NEXUS3

---

## Executive Summary

NEXUS3 demonstrates strong commitment to type safety with well-designed Protocol interfaces and consistent use of modern Python typing patterns. The codebase follows the stated SOP of "Type Everything" reasonably well, though there are several areas where `Any` types could be more precisely typed and where runtime type checking could be strengthened.

**Overall Grade: B+**

| Category | Score | Notes |
|----------|-------|-------|
| Protocol Design | A | Clean, minimal interfaces |
| Type Completeness | B+ | Good coverage, some `Any` escape hatches |
| Generic Types | B | Limited but appropriate use |
| Runtime Checking | B | Present where needed |
| Mypy Compatibility | A- | Should pass strict mode |

---

## 1. Protocol Design Analysis

### 1.1 Core Protocols

**Location:** `/home/inc/repos/NEXUS3/nexus3/core/interfaces.py`

The codebase defines two core protocols that are well-designed:

#### AsyncProvider Protocol

```python
class AsyncProvider(Protocol):
    async def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> Message: ...

    def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]: ...
```

**Strengths:**
- Clear, minimal interface with only two methods
- Proper async typing with `AsyncIterator`
- Good docstrings with usage examples

**Issues:**
1. **`tools` parameter uses `dict[str, Any]`** - This is the OpenAI function calling format, but could benefit from a `ToolDefinition` type alias or TypedDict:

```python
# Recommendation: Add to core/types.py
class ToolFunction(TypedDict):
    name: str
    description: str
    parameters: dict[str, Any]

class ToolDefinition(TypedDict):
    type: Literal["function"]
    function: ToolFunction
```

2. **Stream method is not `async def`** - The `stream` method returns `AsyncIterator` but is not declared async. This is technically correct (it returns an async iterator synchronously), but the inconsistency with `complete` may confuse readers.

#### RawLogCallback Protocol

```python
class RawLogCallback(Protocol):
    def on_request(self, endpoint: str, payload: dict[str, Any]) -> None: ...
    def on_response(self, status: int, body: dict[str, Any]) -> None: ...
    def on_chunk(self, chunk: dict[str, Any]) -> None: ...
```

**Assessment:** Well-designed callback protocol. The `dict[str, Any]` usage is acceptable here since it represents arbitrary JSON from the API.

### 1.2 Skill Protocol

**Location:** `/home/inc/repos/NEXUS3/nexus3/skill/base.py`

```python
@runtime_checkable
class Skill(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def description(self) -> str: ...
    @property
    def parameters(self) -> dict[str, Any]: ...
    async def execute(self, **kwargs: Any) -> ToolResult: ...
```

**Strengths:**
- `@runtime_checkable` enables `isinstance()` checks - good for validation
- Properties are read-only, enforcing immutability

**Issues:**
1. **`**kwargs: Any` in execute()** - This is a fundamental type hole. The skill's parameters are typed as JSON Schema at runtime but not statically. This is largely unavoidable given the dynamic nature of tool arguments.

2. **`parameters` returns `dict[str, Any]`** - Could use a TypedDict for JSON Schema:

```python
# Recommendation
class JSONSchemaObject(TypedDict, total=False):
    type: Literal["object"]
    properties: dict[str, dict[str, Any]]
    required: list[str]
```

### 1.3 TokenCounter Protocol

**Location:** `/home/inc/repos/NEXUS3/nexus3/context/token_counter.py`

```python
class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...
    def count_messages(self, messages: list["Message"]) -> int: ...
```

**Assessment:** Excellent minimal protocol. The forward reference to `Message` using string literal is correct. The factory pattern (`get_token_counter()`) with graceful degradation is well-designed.

### 1.4 PromptSource Protocol

**Location:** `/home/inc/repos/NEXUS3/nexus3/context/prompt_loader.py`

```python
class PromptSource(Protocol):
    def load(self) -> str | None: ...
    @property
    def path(self) -> Path | None: ...
```

**Assessment:** Good protocol design. Using `| None` for optional returns is preferred over `Optional[X]`.

---

## 2. Type Annotation Completeness

### 2.1 Dataclass Usage

The codebase consistently uses frozen dataclasses for immutable data structures:

**Location:** `/home/inc/repos/NEXUS3/nexus3/core/types.py`

```python
@dataclass(frozen=True)
class Message:
    role: Role
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None

@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]  # Issue: Any escape hatch

@dataclass(frozen=True)
class ToolResult:
    output: str = ""
    error: str = ""
```

**Strengths:**
- `frozen=True` enforces immutability
- `tuple[ToolCall, ...]` instead of `list` for immutable collections
- Union syntax `str | None` (Python 3.10+) instead of `Optional[str]`

**Issues:**
1. **`ToolCall.arguments: dict[str, Any]`** - This is where JSON from LLM gets stored. The `Any` is necessary because argument types are runtime-determined.

2. **Streaming types inheritance** - `StreamEvent` is a base class, not a Protocol:

```python
@dataclass(frozen=True)
class StreamEvent:
    pass  # Empty base class

@dataclass(frozen=True)
class ContentDelta(StreamEvent):
    text: str
```

This works but could benefit from making `StreamEvent` a Protocol or using `@typing.final` on subclasses to indicate the type hierarchy is closed.

### 2.2 Any Types Audit

Grep results show `Any` appears in these contexts:

| Location | Usage | Justification | Recommendation |
|----------|-------|---------------|----------------|
| `core/types.py:34` | `ToolCall.arguments: dict[str, Any]` | Dynamic JSON from LLM | Acceptable |
| `core/interfaces.py:88` | `tools: list[dict[str, Any]]` | OpenAI format | Add TypedDict |
| `skill/base.py:97` | `**kwargs: Any` | Dynamic tool args | Acceptable |
| `skill/services.py:54-86` | `get/register: Any` | DI container | Consider generics |
| `rpc/types.py:37` | `result: Any` | JSON-RPC spec | Acceptable |
| `client.py:46` | `exc_type: Any` | Context manager | Should be `type[BaseException] | None` |

### 2.3 ServiceContainer Type Safety Issue

**Location:** `/home/inc/repos/NEXUS3/nexus3/skill/services.py`

```python
@dataclass
class ServiceContainer:
    _services: dict[str, Any] = field(default_factory=dict)

    def get(self, name: str) -> Any: ...
    def require(self, name: str) -> Any: ...
    def register(self, name: str, service: Any) -> None: ...
```

**Critical Issue:** This is the largest type safety hole. The container stores services by string name and returns `Any`, losing all type information.

**Recommendation:** Use a generic approach or TypeVar:

```python
from typing import TypeVar, overload

T = TypeVar("T")

class ServiceContainer:
    _services: dict[str, object] = field(default_factory=dict)

    @overload
    def get(self, name: str, type_: type[T]) -> T | None: ...
    @overload
    def get(self, name: str) -> object | None: ...

    def get(self, name: str, type_: type[T] | None = None) -> T | object | None:
        service = self._services.get(name)
        if type_ is not None and service is not None:
            if not isinstance(service, type_):
                raise TypeError(f"Service {name} is not of type {type_}")
        return service
```

---

## 3. Generic Types Usage

### 3.1 Current Generic Usage

The codebase has minimal generic type usage:

- `AsyncIterator[StreamEvent]` - Used correctly in provider
- `Callable[[...], ...]` - Used for callbacks
- `dict[str, T]` patterns - Used for collections

### 3.2 Missing Generic Opportunities

**Callback Types in Session**

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/session.py`

```python
ToolCallCallback = Callable[[str, str], None]
ToolCompleteCallback = Callable[[str, str, bool], None]
BatchStartCallback = Callable[["tuple[ToolCall, ...]"], None]
```

These type aliases are good but could benefit from `ParamSpec` for more flexible callback typing.

**Handler Type in Dispatcher**

**Location:** `/home/inc/repos/NEXUS3/nexus3/rpc/dispatcher.py`

```python
Handler = Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]
```

The `Coroutine[Any, Any, dict[str, Any]]` could be simplified to `Awaitable[dict[str, Any]]` since the coroutine details don't matter.

---

## 4. Runtime Type Checking

### 4.1 isinstance() Patterns

The codebase properly uses `isinstance()` for runtime type checking:

**Stream Event Handling:**

```python
# session/session.py:169-177
if isinstance(event, ContentDelta):
    yield event.text
elif isinstance(event, ToolCallStarted):
    if self.on_tool_call:
        self.on_tool_call(event.name, event.id)
elif isinstance(event, StreamComplete):
    final_message = event.message
```

**JSON-RPC Validation:**

```python
# rpc/protocol.py:42-67
if not isinstance(data, dict):
    raise ParseError("Request must be a JSON object")
if not isinstance(method, str):
    raise ParseError(f"method must be a string, got: {type(method).__name__}")
```

**Assessment:** Good use of runtime validation at API boundaries.

### 4.2 runtime_checkable Protocol

The `Skill` protocol is `@runtime_checkable`, enabling:

```python
if isinstance(obj, Skill):
    # Type narrowed to Skill
```

**Recommendation:** Consider adding `@runtime_checkable` to `TokenCounter` and `PromptSource` for defensive programming.

---

## 5. Mypy Compatibility

### 5.1 TYPE_CHECKING Guards

The codebase correctly uses `TYPE_CHECKING` to avoid circular imports:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nexus3.context.manager import ContextManager
    from nexus3.session.logging import SessionLogger
```

### 5.2 Forward References

Forward references are handled correctly:

```python
class StreamComplete(StreamEvent):
    message: "Message"  # Quoted for forward reference

def count_messages(self, messages: list["Message"]) -> int:
    ...
```

### 5.3 Potential Mypy Issues

1. **`pass` in Protocol methods** - Using `...` (ellipsis) is more conventional:
   ```python
   # Current
   class StreamEvent:
       pass

   # Preferred
   class StreamEvent:
       ...
   ```

2. **hasattr checks** - The provider callback wiring uses duck typing:
   ```python
   if hasattr(provider, "set_raw_log_callback"):
       provider.set_raw_log_callback(raw_callback)
   ```
   This works but mypy won't track the narrowing. Consider a protocol:
   ```python
   class RawLogConfigurable(Protocol):
       def set_raw_log_callback(self, callback: RawLogCallback | None) -> None: ...
   ```

---

## 6. Type Narrowing Patterns

### 6.1 Good Narrowing Examples

**Enum Pattern:**

```python
class Role(Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
```

Using enums instead of literal strings provides good type narrowing.

**Optional Handling:**

```python
# context/manager.py:182-188
def get_tool_definitions(self) -> list[dict[str, Any]] | None:
    return self._tool_definitions if self._tool_definitions else None
```

### 6.2 Type Narrowing Issues

**Tool Execution Return Type:**

```python
# session/session.py:355-358
try:
    return await skill.execute(**args)
except Exception as e:
    return ToolResult(error=f"Skill execution error: {e}")
```

The broad `Exception` catch means any exception becomes a `ToolResult`. Consider narrowing to expected exceptions.

---

## 7. Recommendations Summary

### High Priority

1. **Create TypedDict for tool definitions** - Replace `dict[str, Any]` in `AsyncProvider` and `SkillRegistry` with a proper TypedDict.

2. **Improve ServiceContainer typing** - Add generic support or type-safe getters to avoid `Any` returns.

3. **Fix `__aexit__` signature** in `NexusClient`:
   ```python
   async def __aexit__(
       self,
       exc_type: type[BaseException] | None,
       exc_val: BaseException | None,
       exc_tb: TracebackType | None,
   ) -> None:
   ```

### Medium Priority

4. **Add `@runtime_checkable` to more protocols** - `TokenCounter`, `PromptSource`.

5. **Use `Awaitable` instead of `Coroutine`** in the `Handler` type alias.

6. **Document `Any` usages** - Add comments explaining why `Any` is necessary in places like `ToolCall.arguments`.

### Low Priority

7. **Consider using `@typing.final`** on stream event subclasses to indicate closed hierarchy.

8. **Replace `pass` with `...`** in Protocol method stubs for consistency.

9. **Add Protocol for raw log configurable providers** instead of `hasattr` checks.

---

## 8. Code Examples

### TypedDict for Tool Definitions

```python
# Add to nexus3/core/types.py

from typing import TypedDict, Literal, Any

class ToolFunctionParameters(TypedDict, total=False):
    type: Literal["object"]
    properties: dict[str, dict[str, Any]]
    required: list[str]

class ToolFunction(TypedDict):
    name: str
    description: str
    parameters: ToolFunctionParameters

class ToolDefinition(TypedDict):
    type: Literal["function"]
    function: ToolFunction
```

### Typed ServiceContainer

```python
from typing import TypeVar, overload, cast

T = TypeVar("T")

@dataclass
class ServiceContainer:
    _services: dict[str, object] = field(default_factory=dict)

    def get(self, name: str, type_: type[T]) -> T | None:
        """Get a service by name with type safety."""
        service = self._services.get(name)
        if service is None:
            return None
        return cast(T, service)  # Caller asserts the type

    def require(self, name: str, type_: type[T]) -> T:
        """Get a required service with type safety."""
        service = self.get(name, type_)
        if service is None:
            raise KeyError(f"Required service not registered: {name}")
        return service
```

---

## 9. Conclusion

NEXUS3's type safety implementation is solid, with well-designed Protocols and consistent use of modern Python typing features. The main areas for improvement are:

1. **Stronger typing for JSON structures** - Tool definitions and arguments could benefit from TypedDicts
2. **ServiceContainer generics** - The DI container loses type information
3. **Minor cleanup** - `__aexit__` signatures, Protocol conventions

The `Any` usages are generally justified by the dynamic nature of LLM interactions (tool arguments, JSON-RPC results). The codebase should pass mypy in strict mode with minimal configuration.

**Final Assessment:** The type system is well-suited for a project of this nature. The Protocol-first design enables clean interfaces without inheritance complexity, and the consistent use of frozen dataclasses provides good immutability guarantees.
