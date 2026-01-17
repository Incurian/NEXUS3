# nexus3/core

Foundational types, interfaces, and utilities for the NEXUS3 framework. This module has zero dependencies on other nexus3 modules and serves as the base layer for the entire system.

## Purpose

The `core` module provides:
- Immutable data structures for messages and tool interactions (`types.py`)
- Streaming event types for real-time tool call detection (`types.py`)
- Protocol definitions for pluggable components (providers, loggers) (`interfaces.py`)
- A typed exception hierarchy (`errors.py`)
- UTF-8 encoding utilities for cross-platform consistency (`encoding.py`)
- Cooperative cancellation support for async operations (`cancel.py`)
- Path normalization, sandbox validation, and unified resolution (`paths.py`, `resolver.py`, `path_decision.py`)
- URL validation for SSRF protection (`url_validator.py`)
- Permission system with presets, per-tool configuration, and ceiling inheritance (`permissions.py`, `policy.py`, `presets.py`, `allowances.py`)
- Input validation for agent IDs and tool arguments (`validation.py`, `identifiers.py`)
- Core constants and shared utilities (`constants.py`, `utils.py`)
- Secure I/O and redaction utilities (`secure_io.py`, `redaction.py`)

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
    validate_path, validate_sandbox, get_default_sandbox, PathResolver,
    # URL validation
    validate_url,
    # Permissions
    PermissionLevel, PermissionPolicy, ToolPermission,
    PermissionPreset, PermissionDelta, AgentPermissions,
    get_builtin_presets, resolve_preset,
)
```

## Key Modules Overview

### `types.py` - Data Structures and Streaming Events
- **Core Types**: `Role` (enum), `Message`, `ToolCall`, `ToolResult`
- **Streaming**: `StreamEvent` (base), `ContentDelta`, `ReasoningDelta`, `ToolCallStarted`, `StreamComplete`

### `interfaces.py` - Protocols
- `AsyncProvider`: LLM completion and streaming interface
- `RawLogCallback`: Raw API logging protocol

### `errors.py` - Exception Hierarchy
- `NexusError` (base), `ConfigError`, `ProviderError`, `PathSecurityError`

### `cancel.py` - CancellationToken
Cooperative cancellation with `is_cancelled`, `cancel()`, `raise_if_cancelled()`

### `encoding.py` - UTF-8 Utilities
`ENCODING = "utf-8"`, `ENCODING_ERRORS = "replace"`, `configure_stdio()`

### `paths.py` & `path_decision.py` - Path Handling
- `validate_path()`: Universal validation with allowed/blocked paths
- `validate_sandbox()`, `get_default_sandbox()`, `normalize_path()`, `display_path()`
- `atomic_write_text()`: Atomic file writes
- Internal decision engine for consistent path checks

### `resolver.py` - PathResolver
Unified path resolution relative to agent CWD, with per-tool allowed_paths.

### `url_validator.py` - SSRF Protection
- `validate_url(url, allow_localhost=False)`: Blocks private IPs, metadata endpoints
- `UrlSecurityError`

### `permissions.py` - Agent Permissions (Aggregator)
Re-exports from `policy.py`, `allowances.py`, `presets.py`:
- `PermissionLevel` (YOLO, TRUSTED, SANDBOXED)
- `PermissionPolicy`, `AgentPermissions`, `resolve_preset()`
- `SessionAllowances` for dynamic TRUSTED allowances
- Ceiling inheritance prevents privilege escalation

### `policy.py` - Permission Primitives
- `DESTRUCTIVE_ACTIONS`, `SAFE_ACTIONS`, `NETWORK_ACTIONS`
- `PermissionPolicy` path/action checks, `requires_confirmation()`

### `allowances.py` - Dynamic Allowances
- `SessionAllowances`: Per-session write/exec allowances for TRUSTED mode

### `presets.py` - Permission Presets
- `PermissionPreset`, `ToolPermission`, `get_builtin_presets()`

### `validation.py` - Input Validation
- `validate_agent_id()`, `validate_tool_arguments()` with jsonschema

### `constants.py` - Global Paths
- `get_nexus_dir()` → `~/.nexus3`
- `get_sessions_dir()`, etc.

### `utils.py` - Shared Utilities
- `deep_merge()`: Recursive dict merge

### `identifiers.py`, `secure_io.py`, `redaction.py`
Internal utilities for IDs, secure I/O, and content redaction.

## Dependencies

**Stdlib**: asyncio, dataclasses, enum, ipaddress, pathlib, etc.

**PyPI**: jsonschema (validation)

**Internal**: None

## Data Flow

```
User → Message(USER) → Provider.stream() → StreamEvent(s) → ToolCall(s) → ToolResult → Message(TOOL)
                      ↓
               ContentDelta / ToolCallStarted / StreamComplete(Message(ASSISTANT))
```

## Usage Examples

### Messages and Tool Calls
```python
from nexus3.core import Message, Role, ToolCall, ToolResult

msg = Message(role=Role.USER, content="Analyze this file.")
tool_call = ToolCall(id="tc_1", name="read_file", arguments={"path": "data.txt"})
result = ToolResult(tool_call_id="tc_1", content="File content here...")
```

### Streaming Events
```python
from nexus3.core import StreamEvent, ContentDelta, ToolCallStarted

for event in provider.stream(messages, stream=True):
    match event:
        case ContentDelta(content):
            print(content, end="", flush=True)
        case ToolCallStarted(call):
            print(f"Tool call started: {call.name}")
        case StreamComplete(content):
            print("Stream complete")
```

### Permissions
```python
from nexus3.core import resolve_preset, PermissionLevel

perms = resolve_preset("trusted", cwd=Path("/project"))
if perms.effective_policy.requires_confirmation("write_file", path=Path("output.txt")):
    # Prompt user for confirmation
    response = get_user_confirmation(perms, "write_file", path)
    if response == "allow_file":
        perms.add_file_allowance(path)
```

### Path Validation
```python
from nexus3.core import validate_path, get_default_sandbox

sandbox = get_default_sandbox()
safe_path = validate_path("../data.txt", allowed_paths=sandbox)
```

### Provider Interface
```python
from nexus3.core.interfaces import AsyncProvider
from nexus3.core.types import Message

class MyProvider(AsyncProvider):
    async def stream(self, messages: list[Message], **kwargs):
        # Implement streaming logic
        yield StreamComplete(Message(role=Role.ASSISTANT, content="Hello!"))
```

## Architecture Summary
- **Immutability**: Frozen dataclasses
- **Protocols**: Structural typing
- **Security**: Sandboxing, SSRF protection, permission ceilings
- **Streaming**: Structured events
- **Permissions**: Multi-level, dynamic allowances, RPC-serializable

**allowed_paths Semantics**:
- `None`: Unrestricted
- `[]`: Deny all
- `[Path(...)]`: Restricted to listed dirs
