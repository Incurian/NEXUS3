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
- Path normalization, sandbox validation, and unified resolution (`paths.py`, `resolver.py`)
- URL validation for SSRF protection (`url_validator.py`)
- Permission system with presets, per-tool configuration, and ceiling inheritance (`permissions.py`, `policy.py`, `presets.py`, `allowances.py`)
- Input validation for agent IDs and tool arguments (`validation.py`)
- Core constants and shared utilities (`constants.py`, `utils.py`)

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

### `paths.py` - Path Handling
- `validate_path()`: Universal validation with allowed/blocked paths
- `validate_sandbox()`, `get_default_sandbox()`, `normalize_path()`, `display_path()`
- `atomic_write_text()`: Atomic file writes

### `url_validator.py` - SSRF Protection
- `validate_url(url, allow_localhost=True)`: Blocks private IPs, metadata endpoints
- `UrlSecurityError`

### `permissions.py` - Agent Permissions (Aggregator)
Re-exports from `policy.py`, `allowances.py`, `presets.py`:
- `PermissionLevel` (YOLO, TRUSTED, SANDBOXED)
- `PermissionPolicy`, `AgentPermissions`, `resolve_preset()`
- `SessionAllowances` for dynamic TRUSTED allowances
- Ceiling inheritance prevents privilege escalation

### `resolver.py` - PathResolver
Unified path resolution relative to agent CWD, with per-tool allowed_paths.

### `validation.py` - Input Validation
- `validate_agent_id()`, `is_valid_agent_id()`
- `validate_tool_arguments()` with jsonschema

### `constants.py` - Global Paths
- `get_nexus_dir()` → `~/.nexus3`
- `get_sessions_dir()`, `get_default_config_path()`, `get_rpc_token_path()`

### `utils.py` - Shared Utilities
- `deep_merge()`: Recursive dict merge
- `find_ancestor_config_dirs()`: Locate `.nexus3` in parent dirs

## Dependencies

**Stdlib**:
- `asyncio`, `collections.abc`, `copy`, `dataclasses`, `enum`, `ipaddress`, `pathlib`, `re`, `socket`, `sys`, `typing`, `urllib.parse`

**PyPI**:
- `jsonschema` (validation.py)

**Internal**: None (root module)

## Data Flow

```
User → Message(USER) → Provider.stream() → StreamEvent(s) → ToolCall(s) → ToolResult → Message(TOOL)
                          ↓
                   ContentDelta / ToolCallStarted / StreamComplete(Message(ASSISTANT))
```

## Usage Examples

See existing detailed examples in the original README for:
- Messages/ToolCalls
- Streaming handling
- Provider implementation
- Cancellation
- Path/URL validation
- Permissions/Presets

## Architecture Summary

- **Immutability**: Frozen dataclasses everywhere
- **Protocols**: Structural typing for providers/loggers
- **Security**: Path sandboxing, URL SSRF protection, permission ceilings
- **Cross-platform**: UTF-8, path normalization
- **Streaming**: Structured events over raw text
- **Permissions**: Multi-level (YOLO/TRUSTED/SANDBOXED), dynamic allowances, serializable for RPC

**allowed_paths Semantics**:
- `None`: Unrestricted
- `[]`: Deny all
- `[Path(...)]`: Restricted to listed dirs

