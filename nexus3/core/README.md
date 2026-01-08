# nexus3/core

Foundational types, interfaces, and utilities for the NEXUS3 framework. This module has zero dependencies on other nexus3 modules and serves as the base layer for the entire system.

## Purpose

The `core` module provides:
- Immutable data structures for messages and tool interactions
- Streaming event types for real-time tool call detection
- Protocol definitions for pluggable components (providers, loggers)
- A typed exception hierarchy
- UTF-8 encoding utilities for cross-platform consistency
- Cooperative cancellation support for async operations
- Path normalization utilities for cross-platform file handling

## Public API

All public exports are defined in `__init__.py`:

```python
from nexus3.core import (
    # Data types
    Message, Role, ToolCall, ToolResult,
    # Streaming events
    StreamEvent, ContentDelta, ToolCallStarted, StreamComplete,
    # Protocols
    AsyncProvider,
    # Errors
    NexusError, ConfigError, ProviderError,
    # Cancellation
    CancellationToken,
    # Encoding
    ENCODING, ENCODING_ERRORS, configure_stdio,
)
```

## Files

### `types.py` - Data Structures and Streaming Events

#### Core Data Types

| Type | Description |
|------|-------------|
| `Role` | Enum for message roles: `SYSTEM`, `USER`, `ASSISTANT`, `TOOL` |
| `Message` | Immutable message with `role`, `content`, optional `tool_calls` tuple, optional `tool_call_id` |
| `ToolCall` | Request to execute a tool with `id`, `name`, and `arguments` dict |
| `ToolResult` | Tool execution result with `output`/`error` strings and `success` property |

All dataclasses are `frozen=True` for immutability.

#### Streaming Event Types

These types are yielded by `provider.stream()` to communicate content, tool calls, and completion status:

| Type | Description |
|------|-------------|
| `StreamEvent` | Base class for all streaming events |
| `ContentDelta(text)` | Content chunk to display immediately |
| `ReasoningDelta(text)` | Reasoning/thinking content from the model (internal, not exported) |
| `ToolCallStarted(index, id, name)` | Notification when a tool call is detected in the stream |
| `StreamComplete(message)` | Final event containing the complete `Message` |

These replace raw string chunks, allowing the display layer to handle content vs tool calls differently.

### `interfaces.py` - Protocols

#### `AsyncProvider`

Protocol for LLM providers. Implementations must provide:

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

The `stream()` method yields `StreamEvent` objects instead of raw strings.

#### `RawLogCallback`

Protocol for raw API logging (used internally by providers):

```python
class RawLogCallback(Protocol):
    def on_request(self, endpoint: str, payload: dict[str, Any]) -> None: ...
    def on_response(self, status: int, body: dict[str, Any]) -> None: ...
    def on_chunk(self, chunk: dict[str, Any]) -> None: ...
```

### `errors.py` - Exception Hierarchy

```
NexusError (base)
├── ConfigError   # Configuration issues (missing file, invalid JSON, validation)
└── ProviderError # LLM API errors (network, auth, rate limits)
```

All exceptions store the message in a `.message` attribute.

### `cancel.py` - Cancellation Support

`CancellationToken` provides cooperative cancellation for async operations:

| Method/Property | Description |
|-----------------|-------------|
| `is_cancelled` | Property: `True` if cancellation was requested |
| `cancel()` | Request cancellation and invoke registered callbacks |
| `on_cancel(callback)` | Register a callback; invoked immediately if already cancelled |
| `raise_if_cancelled()` | Raise `asyncio.CancelledError` if cancelled |
| `reset()` | Clear cancelled state (keeps callbacks) for token reuse |

### `encoding.py` - UTF-8 Utilities

| Export | Description |
|--------|-------------|
| `ENCODING` | Constant: `"utf-8"` |
| `ENCODING_ERRORS` | Constant: `"replace"` (preserve data, mark corruption) |
| `configure_stdio()` | Reconfigure stdin/stdout/stderr for UTF-8 with replace error handling |

### `paths.py` - Path Normalization

Cross-platform path handling utilities:

| Function | Description |
|----------|-------------|
| `normalize_path(path: str) -> Path` | Normalize path: Windows backslashes to forward slashes, tilde expansion |
| `normalize_path_str(path: str) -> str` | Same as above but returns string |
| `display_path(path: str \| Path) -> str` | Format path for display (relative if under cwd, or with ~ for home) |

## Data Flow

```
User Input
    |
    v
Message(role=USER, content="...")
    |
    v
AsyncProvider.stream() or .complete()
    |
    +---> ContentDelta(text="...") --> display immediately
    |
    +---> ToolCallStarted(id, name) --> update display "calling..."
    |
    +---> StreamComplete(message)
              |
              +---> Message(role=ASSISTANT, content="...", tool_calls=(...))
                        |
                        v
                   ToolCall(id="...", name="read_file", arguments={...})
                        |
                        v
                   ToolResult(output="...", error="")
                        |
                        v
                   Message(role=TOOL, content="...", tool_call_id="...")
```

## Dependencies

**External (stdlib only):**
- `asyncio` - for `CancelledError`
- `collections.abc` - for `AsyncIterator`, `Callable`
- `dataclasses`
- `enum`
- `pathlib`
- `sys`
- `typing`

**Internal:** None. This module is the dependency root.

## Usage Examples

### Creating Messages

```python
from nexus3.core import Message, Role, ToolCall, ToolResult

# User message
user_msg = Message(role=Role.USER, content="Read the config file")

# Assistant with tool call
tool_call = ToolCall(
    id="call_123",
    name="read_file",
    arguments={"path": "/etc/config.json"}
)
assistant_msg = Message(
    role=Role.ASSISTANT,
    content="I'll read that file for you.",
    tool_calls=(tool_call,)
)

# Tool result
result = ToolResult(output='{"key": "value"}')
print(result.success)  # True (no error)

# Tool response message
tool_msg = Message(
    role=Role.TOOL,
    content=result.output,
    tool_call_id="call_123"
)
```

### Handling Streaming Events

```python
from nexus3.core import ContentDelta, ToolCallStarted, StreamComplete

async for event in provider.stream(messages, tools):
    if isinstance(event, ContentDelta):
        print(event.text, end="")  # Display content immediately
    elif isinstance(event, ToolCallStarted):
        print(f"\nCalling {event.name}...")  # Update display
    elif isinstance(event, StreamComplete):
        if event.message.tool_calls:
            for call in event.message.tool_calls:
                result = await execute_tool(call)
                # Add tool result to conversation...
```

### Implementing a Provider

```python
from nexus3.core import AsyncProvider, Message, Role, ContentDelta, StreamComplete

class MyProvider:
    async def complete(self, messages: list[Message], tools=None) -> Message:
        # Call your LLM API
        response = await self._call_api(messages, tools)
        return Message(role=Role.ASSISTANT, content=response)

    def stream(self, messages: list[Message], tools=None):
        # Note: stream() is a regular method returning an async iterator
        async def _stream():
            async for chunk in self._stream_api(messages, tools):
                yield ContentDelta(text=chunk)
            yield StreamComplete(message=Message(role=Role.ASSISTANT, content=...))
        return _stream()
```

### Cancellation

```python
from nexus3.core import CancellationToken

token = CancellationToken()

# Register callback (optional)
token.on_cancel(lambda: print("Cancelled!"))

async def long_operation():
    async for chunk in stream:
        token.raise_if_cancelled()  # Raises CancelledError if cancelled
        yield chunk

# On ESC key press:
token.cancel()

# Reuse for next operation:
token.reset()
```

### Error Handling

```python
from nexus3.core import NexusError, ConfigError, ProviderError

try:
    # ... nexus operations ...
except ConfigError as e:
    print(f"Configuration problem: {e.message}")
except ProviderError as e:
    print(f"LLM API error: {e.message}")
except NexusError as e:
    print(f"Nexus error: {e.message}")
```

### UTF-8 Configuration

```python
from nexus3.core import configure_stdio, ENCODING, ENCODING_ERRORS

# At application startup
configure_stdio()

# For file operations
content = path.read_text(encoding=ENCODING, errors=ENCODING_ERRORS)

# For subprocess
subprocess.run(cmd, text=True, encoding=ENCODING, errors=ENCODING_ERRORS)
```

### Path Normalization

```python
from nexus3.core.paths import normalize_path, display_path

# Normalize Windows paths
path = normalize_path("C:\\Users\\name\\file.txt")  # Works on all platforms

# Get display-friendly path
display = display_path("/home/user/project/src/main.py")  # Returns "src/main.py" if in project dir
```

## Design Notes

1. **Immutability**: All data classes use `frozen=True` to prevent accidental mutation
2. **Protocols over inheritance**: Uses structural subtyping for flexibility
3. **Fail-fast errors**: Typed exceptions with clear messages in `.message` attribute
4. **Cross-platform encoding**: Explicit UTF-8 everywhere, never rely on system locale
5. **Cooperative cancellation**: No forced thread/process kills, clean shutdown via callbacks
6. **Structured streaming**: `StreamEvent` types instead of raw strings for type-safe event handling
7. **Path portability**: Normalize paths for consistent cross-platform file operations
