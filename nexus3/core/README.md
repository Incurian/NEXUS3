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
- Path normalization and sandbox validation for cross-platform file handling
- URL validation for SSRF protection
- Permission system with presets, per-tool configuration, and ceiling inheritance
- Input validation for agent IDs and tool arguments

## Public API

All public exports are defined in `__init__.py`:

```python
from nexus3.core import (
    # Data types
    Message, Role, ToolCall, ToolResult,
    # Streaming events
    StreamEvent, ContentDelta, ReasoningDelta, ToolCallStarted, StreamComplete,
    # Protocols
    AsyncProvider,
    # Errors
    NexusError, ConfigError, ProviderError, PathSecurityError, UrlSecurityError,
    # Cancellation
    CancellationToken,
    # Encoding
    ENCODING, ENCODING_ERRORS, configure_stdio,
    # Path sandbox
    validate_sandbox, get_default_sandbox,
    # URL validation
    validate_url,
    # Permissions
    PermissionLevel, PermissionPolicy, ToolPermission,
    PermissionPreset, PermissionDelta, AgentPermissions,
    get_builtin_presets, resolve_preset,
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
| `ReasoningDelta(text)` | Reasoning/thinking content from the model (displayed muted or hidden) |
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

Note: `stream()` is a regular method (not `async def`) that returns an `AsyncIterator`. The caller uses `async for` to consume the iterator. This pattern avoids requiring `async with` on the generator.

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
├── ConfigError       # Configuration issues (missing file, invalid JSON, validation)
├── ProviderError     # LLM API errors (network, auth, rate limits)
└── PathSecurityError # Path violates sandbox constraints (path, reason attributes)
```

All exceptions store the message in a `.message` attribute.

`PathSecurityError` additionally has `path` and `reason` attributes for detailed error information.

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

### `paths.py` - Path Normalization and Sandbox Validation

Cross-platform path handling utilities:

| Function | Description | Exported |
|----------|-------------|----------|
| `normalize_path(path: str) -> Path` | Normalize path: Windows backslashes to forward slashes, tilde expansion. Returns empty path as `.` | No |
| `normalize_path_str(path: str) -> str` | Same as above but returns string | No |
| `display_path(path: str \| Path) -> str` | Format path for display (relative if under cwd, or with `~` for home) | No |
| `get_default_sandbox() -> list[Path]` | Returns `[Path.cwd()]` as default sandbox | Yes |
| `validate_sandbox(path, allowed_paths) -> Path` | Validate path is within sandbox. Raises `PathSecurityError` if outside sandbox or contains symlinks | Yes |

The `validate_sandbox()` function:
- Resolves paths to absolute form
- Blocks symlinks in any component of the path
- Checks path is within at least one allowed directory
- Returns the resolved absolute path if valid

### `url_validator.py` - SSRF Protection

URL validation to prevent Server-Side Request Forgery attacks:

| Export | Description |
|--------|-------------|
| `UrlSecurityError` | Exception with `url` and `reason` attributes |
| `validate_url(url, allow_localhost=True)` | Validate URL is safe for HTTP requests |

The `validate_url()` function blocks:
- Cloud metadata endpoints (169.254.169.254)
- Private IP ranges (10.x, 172.16.x, 192.168.x)
- Link-local addresses
- IPv6 private/link-local addresses
- Multicast addresses
- Localhost (unless `allow_localhost=True`)

Additionally validates ALL resolved IP addresses (prevents DNS rebinding attacks).

### `validation.py` - Input Validation

Input validation utilities for security-sensitive inputs (import directly from `nexus3.core.validation`):

| Export | Description |
|--------|-------------|
| `ValidationError` | Exception with `message` attribute |
| `validate_agent_id(agent_id) -> str` | Validate agent ID format (1-63 chars, alphanumeric/dot/underscore/hyphen) |
| `is_valid_agent_id(agent_id) -> bool` | Check validity without raising exception |
| `validate_tool_arguments(arguments, schema, logger=None)` | Validate tool arguments against JSON schema |
| `AGENT_ID_PATTERN` | Compiled regex for agent ID validation |
| `ALLOWED_INTERNAL_PARAMS` | Set of allowed internal params (e.g., `_parallel`) |

Agent ID rules:
- 1-63 characters
- Alphanumeric, dots, underscores, hyphens only
- Must start with alphanumeric or dot (for temp agents like `.1`)
- Cannot be `.` or `..`
- Cannot contain path separators

### `permissions.py` - Permission System

Comprehensive permission system for controlling agent access. All types are exported via `__init__.py`.

#### Permission Levels

| Level | Description |
|-------|-------------|
| `YOLO` | Full access, no confirmations |
| `TRUSTED` | Confirmations for destructive actions (default) |
| `SANDBOXED` | Limited paths, restricted network |

#### Core Types

| Type | Description |
|------|-------------|
| `PermissionLevel` | Enum: `YOLO`, `TRUSTED`, `SANDBOXED` |
| `PermissionPolicy` | Runtime policy with level, allowed/blocked paths, action checks |
| `ToolPermission` | Per-tool config: enabled, allowed_paths, timeout, requires_confirmation |
| `PermissionPreset` | Named preset: level, description, paths, network_access, tool_permissions |
| `PermissionDelta` | Changes to apply: disable/enable tools, path overrides |
| `AgentPermissions` | Runtime state with `can_grant()` and `apply_delta()` methods |

#### Built-in Presets

| Preset | Level | Description |
|--------|-------|-------------|
| `yolo` | YOLO | Full access, no confirmations |
| `trusted` | TRUSTED | Confirmations for destructive actions (default) |
| `sandboxed` | SANDBOXED | Limited to CWD, no network, nexus tools disabled |
| `worker` | SANDBOXED | Minimal: no write_file, no agent management |

#### Key Functions

| Function | Description |
|----------|-------------|
| `get_builtin_presets()` | Returns dict of built-in presets |
| `resolve_preset(name, custom_presets=None)` | Resolve preset name to `AgentPermissions` |
| `load_custom_presets_from_config(config_presets)` | Convert config dict to `PermissionPreset` objects |

#### Action Categories

```python
DESTRUCTIVE_ACTIONS = {"delete", "remove", "overwrite", "write", "execute",
                       "run_command", "shutdown", "write_file", "nexus_destroy", "nexus_shutdown"}
SAFE_ACTIONS = {"read", "list", "status", "search"}
NETWORK_ACTIONS = {"http_request", "send_message", "connect"}
```

#### PermissionPolicy Methods

| Method | Description |
|--------|-------------|
| `from_level(level)` | Create policy from level string or enum |
| `can_read_path(path)` | Check if reading path is allowed |
| `can_write_path(path)` | Check if writing to path is allowed |
| `can_network()` | Check if network access is allowed |
| `requires_confirmation(action)` | Check if action needs user confirmation |
| `allows_action(action)` | Check if action is allowed at all |
| `to_dict()` / `from_dict(data)` | Serialization for RPC transport |

#### AgentPermissions Methods

| Method | Description |
|--------|-------------|
| `can_grant(requested)` | Check if this agent can grant permissions to subagent |
| `apply_delta(delta)` | Apply delta and return new permissions (does not check ceiling) |
| `to_dict()` / `from_dict(data)` | Serialization for RPC transport |

#### Ceiling Inheritance

Subagent permissions are validated against parent's "ceiling":
- Cannot have more permissive level than parent
- Cannot enable tools parent has disabled
- Cannot access paths parent cannot access

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
- `copy` - for deep copying permission objects
- `dataclasses`
- `enum`
- `ipaddress` - for IP range validation
- `pathlib`
- `re` - for agent ID pattern matching
- `socket` - for DNS resolution in URL validation
- `sys`
- `typing`
- `urllib.parse` - for URL parsing

**External (PyPI):**
- `jsonschema` - for tool argument validation (in `validation.py`)

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
from collections.abc import AsyncIterator
from nexus3.core import AsyncProvider, Message, Role, StreamEvent, ContentDelta, StreamComplete

class MyProvider:
    async def complete(self, messages: list[Message], tools=None) -> Message:
        # Call your LLM API
        response = await self._call_api(messages, tools)
        return Message(role=Role.ASSISTANT, content=response)

    def stream(
        self, messages: list[Message], tools=None
    ) -> AsyncIterator[StreamEvent]:
        # stream() is a regular method that returns an async iterator.
        # The inner async generator does the actual work.
        async def _stream() -> AsyncIterator[StreamEvent]:
            full_content = ""
            async for chunk in self._stream_api(messages, tools):
                full_content += chunk
                yield ContentDelta(text=chunk)
            yield StreamComplete(
                message=Message(role=Role.ASSISTANT, content=full_content)
            )
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
from nexus3.core import NexusError, ConfigError, ProviderError, PathSecurityError, UrlSecurityError

try:
    # ... nexus operations ...
except ConfigError as e:
    print(f"Configuration problem: {e.message}")
except ProviderError as e:
    print(f"LLM API error: {e.message}")
except PathSecurityError as e:
    print(f"Path security error for '{e.path}': {e.reason}")
except UrlSecurityError as e:
    print(f"URL security error for '{e.url}': {e.reason}")
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

### Path Normalization and Sandbox Validation

```python
from nexus3.core.paths import normalize_path, display_path
from nexus3.core import validate_sandbox, get_default_sandbox, PathSecurityError
from pathlib import Path

# Normalize Windows paths
path = normalize_path("C:\\Users\\name\\file.txt")  # Works on all platforms

# Get display-friendly path
display = display_path("/home/user/project/src/main.py")  # Returns "src/main.py" if in project dir

# Validate path is within sandbox
sandbox = get_default_sandbox()  # [Path.cwd()]
try:
    resolved = validate_sandbox("/path/to/file.txt", sandbox)
    print(f"Validated path: {resolved}")
except PathSecurityError as e:
    print(f"Access denied: {e.reason}")
```

### URL Validation

```python
from nexus3.core import validate_url, UrlSecurityError

# Validate URL before making request
try:
    safe_url = validate_url("http://127.0.0.1:8765/agent/main", allow_localhost=True)
    # Safe to make HTTP request
except UrlSecurityError as e:
    print(f"URL blocked: {e.reason}")

# External URLs - localhost not allowed by default
try:
    validate_url("http://169.254.169.254/metadata")  # AWS metadata - blocked!
except UrlSecurityError:
    print("Cloud metadata endpoints always blocked")
```

### Input Validation

```python
from nexus3.core.validation import validate_agent_id, is_valid_agent_id, ValidationError

# Validate agent ID
try:
    agent_id = validate_agent_id("my-worker-1")  # Valid
    agent_id = validate_agent_id(".1")  # Valid (temp agent)
    agent_id = validate_agent_id("../escape")  # Raises ValidationError
except ValidationError as e:
    print(f"Invalid agent ID: {e.message}")

# Check without exception
if is_valid_agent_id(user_input):
    # Safe to use
    pass
```

### Permissions

```python
from nexus3.core import (
    PermissionLevel, PermissionPolicy, AgentPermissions,
    PermissionDelta, resolve_preset, get_builtin_presets
)
from pathlib import Path

# Create policy from level
policy = PermissionPolicy.from_level("trusted")
print(policy.requires_confirmation("write"))  # True
print(policy.can_network())  # True

# Resolve a preset to AgentPermissions
perms = resolve_preset("sandboxed")
print(perms.base_preset)  # "sandboxed"
print(perms.effective_policy.can_network())  # False

# Apply a delta to modify permissions
delta = PermissionDelta(
    disable_tools=["write_file"],
    add_blocked_paths=[Path("/etc")]
)
modified = perms.apply_delta(delta)

# Check ceiling inheritance
parent_perms = resolve_preset("trusted")
child_perms = resolve_preset("yolo")  # More permissive
print(parent_perms.can_grant(child_perms))  # False - child exceeds parent

# List available presets
for name, preset in get_builtin_presets().items():
    print(f"{name}: {preset.description}")
```

## Design Notes

1. **Immutability**: All data classes use `frozen=True` to prevent accidental mutation
2. **Protocols over inheritance**: Uses structural subtyping for flexibility
3. **Fail-fast errors**: Typed exceptions with clear messages in `.message` attribute
4. **Cross-platform encoding**: Explicit UTF-8 everywhere, never rely on system locale
5. **Cooperative cancellation**: No forced thread/process kills, clean shutdown via callbacks
6. **Structured streaming**: `StreamEvent` types instead of raw strings for type-safe event handling
7. **Path portability**: Normalize paths for consistent cross-platform file operations
8. **Defense in depth**: Path sandbox + URL validation for security-sensitive operations
9. **Ceiling inheritance**: Subagents cannot exceed parent permissions, preventing privilege escalation
10. **Serializable permissions**: All permission types have `to_dict()`/`from_dict()` for RPC transport
