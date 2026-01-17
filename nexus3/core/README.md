# nexus3/core

Foundational types, interfaces, security utilities, and permission system for NEXUS3. Zero external dependencies (stdlib + jsonschema).

## Purpose

- Immutable message/tool types and structured streaming events
- Async LLM provider protocol
- Path sandboxing, SSRF-protected URL validation, atomic I/O
- Multi-level permissions (YOLO/TRUSTED/SANDBOXED) with per-tool overrides and dynamic allowances
- Cancellation tokens, encoding utils, input validation, secret redaction

## Public API (`__init__.py`)

```python
from nexus3.core import (
    # Types & Streaming
    Message, Role, ToolCall, ToolResult,
    StreamEvent, ContentDelta, ReasoningDelta, ToolCallStarted, StreamComplete,
    # Protocols
    AsyncProvider,
    # Errors
    NexusError, ConfigError, ProviderError, PathSecurityError, UrlSecurityError,
    # Cancellation
    CancellationToken,
    # Encoding
    ENCODING, ENCODING_ERRORS, configure_stdio,
    # Paths
    validate_path, validate_sandbox, get_default_sandbox, PathResolver,
    # URLs
    validate_url,
    # Permissions
    PermissionLevel, PermissionPolicy, ToolPermission, PermissionPreset, PermissionDelta, AgentPermissions,
    get_builtin_presets, resolve_preset,
)
```

## Key Classes/Functions

| Module | Key Exports |
|--------|-------------|
| `types.py` | `Message`, `ToolCall`, `StreamEvent` subclasses |
| `interfaces.py` | `AsyncProvider` (LLM streaming protocol) |
| `permissions.py` | `AgentPermissions`, `resolve_preset("trusted")` |
| `path_decision.py`/`paths.py`/`resolver.py` | `PathDecisionEngine`, `PathResolver`, `validate_path()` |
| `policy.py`/`presets.py`/`allowances.py` | `PermissionPolicy`, `SessionAllowances`, presets |
| `url_validator.py` | `validate_url(url)` |
| `cancel.py` | `CancellationToken` |
| Others (internal/public via init) | Encoding, errors, validation, redaction, secure I/O, text safety |

**Path Semantics**:
- `allowed_paths=None`: Unrestricted (YOLO/TRUSTED)
- `allowed_paths=[]`: Deny all
- `allowed_paths=[dir]`: Sandbox to dir

## Usage Examples

### Streaming Completion
```python
from nexus3.core import AsyncProvider, Message, Role, ContentDelta, ToolCallStarted

class MyProvider(AsyncProvider):
    async def stream(self, messages: list[Message], tools=None):
        yield ContentDelta("Hello")
        yield ToolCallStarted(index=0, id="tc1", name="read_file")
        yield StreamComplete(Message(role=Role.ASSISTANT, content="Done"))

async for event in provider.stream([Message(role=Role.USER, content="Hi")]):
    match event:
        case ContentDelta(text): print(text, end="")
        case ToolCallStarted(name=name): print(f"Calling {name}")
```

### Permissions
```python
from nexus3.core import resolve_preset

perms = resolve_preset("trusted", cwd=Path("/project"))
if perms.effective_policy.requires_confirmation("write_file", path=Path("out.txt")):
    # User prompt → perms.session_allowances.add_write_file(path)
    pass
sub_perms = perms.apply_delta(PermissionDelta(disable_tools=["bash_safe"]))
```

### Path Resolution
```python
from nexus3.core import PathResolver  # Requires ServiceContainer

resolver = PathResolver(services)
safe_path = resolver.resolve("data.txt", tool_name="read_file", must_exist=True)
```

## Data Flow
```
User Message → Provider.stream() → ContentDelta | ToolCallStarted → ToolResult → Assistant Message
                              ↓
                       Permission/Path Checks → Secure Execution
```

## Dependencies
- Stdlib: asyncio, dataclasses, ipaddress, pathlib, etc.
- PyPI: jsonschema (validation only)
