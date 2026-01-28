# nexus3/core

Foundational types, interfaces, security utilities, and permission system for NEXUS3. This module provides the core building blocks used throughout the framework with minimal external dependencies (stdlib + jsonschema + rich).

## Purpose

The core module serves as the foundation for NEXUS3, providing:

- **Immutable message types** - Frozen dataclasses for conversation messages, tool calls, and results
- **Streaming event types** - Typed events for real-time LLM response streaming
- **Provider protocol** - Async-first interface for LLM providers
- **Permission system** - Multi-level access control (YOLO/TRUSTED/SANDBOXED) with per-tool overrides
- **Path security** - Sandboxing, symlink defense, and authoritative path decision engine
- **URL validation** - SSRF protection with blocked IP ranges
- **Input validation** - Agent ID, tool name, and argument validation
- **Secret redaction** - Pattern-based detection and removal of sensitive data
- **Secure I/O** - Atomic file operations with proper permissions
- **Text safety** - Terminal escape sequence and Rich markup sanitization

---

## Public API (`__init__.py`)

```python
from nexus3.core import (
    # === Message Types ===
    Message,           # Conversation message (role, content, tool_calls, meta)
    Role,              # Enum: SYSTEM, USER, ASSISTANT, TOOL
    ToolCall,          # Tool invocation request (id, name, arguments)
    ToolResult,        # Tool execution result (output, error)

    # === Streaming Types ===
    StreamEvent,       # Base class for streaming events
    ContentDelta,      # Text content chunk from stream
    ReasoningDelta,    # Reasoning/thinking content chunk
    ToolCallStarted,   # Notification when tool call detected
    StreamComplete,    # Final event with complete Message

    # === Provider Protocol ===
    AsyncProvider,     # Protocol for async LLM providers

    # === Errors ===
    NexusError,        # Base exception for all NEXUS3 errors
    ConfigError,       # Configuration issues
    ProviderError,     # LLM provider issues
    PathSecurityError, # Path sandbox violations
    UrlSecurityError,  # URL/SSRF security violations

    # === Cancellation ===
    CancellationToken, # Cooperative cancellation for async operations

    # === Encoding ===
    ENCODING,          # "utf-8"
    ENCODING_ERRORS,   # "replace"
    configure_stdio,   # Reconfigure stdin/stdout/stderr to UTF-8

    # === Path Validation ===
    validate_path,     # Universal path validation with allowed/blocked lists
    validate_sandbox,  # Convenience wrapper for sandboxed mode
    get_default_sandbox,  # Returns [Path.cwd()]
    PathResolver,      # Unified path resolution with ServiceContainer

    # === URL Validation ===
    validate_url,      # SSRF-protected URL validation

    # === Permission System ===
    PermissionLevel,   # Enum: YOLO, TRUSTED, SANDBOXED
    PermissionPolicy,  # Path and action restrictions
    ToolPermission,    # Per-tool configuration
    PermissionPreset,  # Named preset configuration
    PermissionDelta,   # Changes to apply to a preset
    AgentPermissions,  # Runtime permission state
    get_builtin_presets,  # Get yolo/trusted/sandboxed presets
    resolve_preset,    # Resolve preset name to AgentPermissions
)
```

---

## Module Reference

### types.py - Core Data Types

Frozen dataclasses for immutable conversation data.

| Type | Description |
|------|-------------|
| `Role` | Enum: `SYSTEM`, `USER`, `ASSISTANT`, `TOOL` |
| `ToolCall` | Tool invocation: `id`, `name`, `arguments` |
| `Message` | Conversation message: `role`, `content`, `tool_calls`, `tool_call_id`, `meta` |
| `ToolResult` | Execution result: `output`, `error`, `success` property |

**Streaming Types:**

| Type | Description |
|------|-------------|
| `StreamEvent` | Base class for all streaming events |
| `ContentDelta` | Text content chunk: `text` |
| `ReasoningDelta` | Reasoning/thinking chunk: `text` |
| `ToolCallStarted` | Tool detected: `index`, `id`, `name` |
| `StreamComplete` | Stream ended: `message` (complete Message) |

```python
from nexus3.core import Message, Role, ToolCall, ToolResult

# Create a user message
msg = Message(role=Role.USER, content="Hello")

# Message with tool calls
msg = Message(
    role=Role.ASSISTANT,
    content="",
    tool_calls=(ToolCall(id="tc1", name="read_file", arguments={"path": "x.txt"}),)
)

# Tool result
result = ToolResult(output="file contents")
assert result.success is True

result = ToolResult(error="File not found")
assert result.success is False
```

---

### interfaces.py - Provider Protocol

Protocol definitions for async LLM providers.

| Protocol | Description |
|----------|-------------|
| `AsyncProvider` | LLM provider with `complete()` and `stream()` methods |
| `RawLogCallback` | Callback for raw API logging (request, response, chunk) |

```python
from nexus3.core import AsyncProvider, Message, StreamEvent, ContentDelta

class MyProvider(AsyncProvider):
    async def complete(self, messages: list[Message], tools=None) -> Message:
        # Non-streaming completion
        ...

    def stream(self, messages: list[Message], tools=None) -> AsyncIterator[StreamEvent]:
        # Streaming completion
        yield ContentDelta("Hello")
        yield StreamComplete(Message(role=Role.ASSISTANT, content="Hello"))
```

---

### errors.py - Exception Hierarchy

Typed exception classes with optional error sanitization.

| Exception | Description |
|-----------|-------------|
| `NexusError` | Base class for all NEXUS3 errors |
| `ConfigError` | Configuration issues (missing file, invalid JSON, validation) |
| `ProviderError` | LLM provider issues (API errors, network, auth) |
| `PathSecurityError` | Path sandbox violations (includes `path` and `reason`) |
| `LoadError` | Base for loading errors |
| `ContextLoadError` | Context loading issues (JSON, validation, merging) |
| `MCPConfigError` | MCP server configuration errors |

**Error Sanitization:**

```python
from nexus3.core.errors import sanitize_error_for_agent

# Sanitize errors before showing to agents (removes paths, usernames)
error = "/home/alice/secret/file.txt: permission denied"
safe = sanitize_error_for_agent(error, "write_file")
# Returns: "Permission denied for write_file"
```

---

### permissions.py - Permission System Entry Point

Main entry point for the permission system. Re-exports from `policy.py`, `presets.py`, and `allowances.py`.

| Export | Description |
|--------|-------------|
| `AgentPermissions` | Runtime permission state combining policy, tool perms, and allowances |
| `resolve_preset()` | Resolve preset name to `AgentPermissions` |

```python
from nexus3.core import resolve_preset, PermissionDelta
from pathlib import Path

# Resolve a preset
perms = resolve_preset("trusted", cwd=Path("/project"))

# Check if confirmation is needed
if perms.effective_policy.requires_confirmation("write_file", path=Path("/etc/passwd")):
    print("Confirmation required")

# Apply changes
new_perms = perms.apply_delta(PermissionDelta(disable_tools=["bash_safe"]))

# Check subagent permissions
if perms.can_grant(requested_perms):
    # Create subagent with requested_perms
    pass
```

---

### policy.py - Permission Primitives

Core permission primitives and policy class.

| Export | Description |
|--------|-------------|
| `PermissionLevel` | Enum: `YOLO`, `TRUSTED`, `SANDBOXED` |
| `ConfirmationResult` | User response: `DENY`, `ALLOW_ONCE`, `ALLOW_FILE`, etc. |
| `PermissionPolicy` | Policy with level, paths, and confirmation logic |
| `DESTRUCTIVE_ACTIONS` | Actions requiring confirmation in TRUSTED mode |
| `SAFE_ACTIONS` | Actions always allowed without confirmation |
| `NETWORK_ACTIONS` | Network operations (blocked in SANDBOXED) |
| `SANDBOXED_DISABLED_TOOLS` | Tools completely disabled in SANDBOXED mode |

**Permission Levels:**

| Level | Description |
|-------|-------------|
| `YOLO` | Full access, no confirmations |
| `TRUSTED` | CWD auto-allowed, prompts for other paths |
| `SANDBOXED` | Immutable sandbox, no execution, no agent management |

```python
from nexus3.core.policy import PermissionPolicy, PermissionLevel

# Create from level
policy = PermissionPolicy.from_level("sandboxed")

# Check capabilities
policy.can_read_path(Path("/project/file.txt"))  # True if in sandbox
policy.can_write_path(Path("/etc/passwd"))  # False
policy.can_network()  # False for SANDBOXED
policy.allows_action("bash_safe")  # False for SANDBOXED

# Check confirmation requirement
policy.requires_confirmation(
    "write_file",
    path=Path("/outside/cwd/file.txt"),
    session_allowances=allowances
)
```

---

### presets.py - Permission Presets

Named permission configurations and tool permissions.

| Export | Description |
|--------|-------------|
| `ToolPermission` | Per-tool config: `enabled`, `allowed_paths`, `timeout`, `requires_confirmation` |
| `PermissionPreset` | Named preset: `name`, `level`, `description`, paths, `tool_permissions` |
| `PermissionDelta` | Changes to apply: `disable_tools`, `enable_tools`, `allowed_paths`, etc. |
| `get_builtin_presets()` | Returns dict of yolo/trusted/sandboxed presets |
| `load_custom_presets_from_config()` | Load custom presets from config dict |

**Built-in Presets:**

| Preset | Level | Description |
|--------|-------|-------------|
| `yolo` | YOLO | Full access, no confirmations |
| `trusted` | TRUSTED | CWD auto-allowed, prompts for other paths |
| `sandboxed` | SANDBOXED | No execution, no agent management, sandbox only |

```python
from nexus3.core.presets import get_builtin_presets, ToolPermission

presets = get_builtin_presets()
sandboxed = presets["sandboxed"]

# Sandboxed disables these tools
assert sandboxed.tool_permissions["bash_safe"].enabled is False
assert sandboxed.tool_permissions["nexus_create"].enabled is False
```

---

### allowances.py - Session Allowances

Dynamic allowances for TRUSTED mode user decisions.

| Export | Description |
|--------|-------------|
| `SessionAllowances` | Stores user's "allow always" decisions |
| `WriteAllowances` | Backwards compatibility alias for `SessionAllowances` |

**Allowance Categories:**

- **Write allowances** - Per-file or per-directory for write operations
- **Execution allowances** - Per-directory or global for bash/run_python
- **MCP allowances** - Per-server or per-tool MCP confirmations

```python
from nexus3.core.allowances import SessionAllowances
from pathlib import Path

allowances = SessionAllowances()

# Add write allowances
allowances.add_write_file(Path("/project/output.txt"))
allowances.add_write_directory(Path("/project/build"))

# Check write access
allowances.is_write_allowed(Path("/project/build/index.js"))  # True

# Add execution allowances
allowances.add_exec_directory("run_python", Path("/project"))
allowances.add_exec_global("bash_safe")  # Any directory

# Check execution access
allowances.is_exec_allowed("run_python", cwd=Path("/project/scripts"))  # True
allowances.is_exec_allowed("bash_safe", cwd=Path("/anywhere"))  # True (global)

# MCP allowances
allowances.add_mcp_server("github")
allowances.is_mcp_server_allowed("github")  # True (all tools)
```

---

### paths.py - Path Validation

Universal path validation with sandboxing.

| Export | Description |
|--------|-------------|
| `validate_path()` | Validate path against allowed/blocked lists |
| `validate_sandbox()` | Convenience wrapper for sandboxed validation |
| `normalize_path()` | Normalize path without restrictions |
| `normalize_path_str()` | Normalize and return as string |
| `display_path()` | Format path for display (relative to cwd or ~) |
| `get_default_sandbox()` | Returns `[Path.cwd()]` |
| `atomic_write_text()` | Write file atomically via temp + rename |

**Path Semantics:**

| `allowed_paths` | Meaning |
|-----------------|---------|
| `None` | Unrestricted access (YOLO/TRUSTED mode) |
| `[]` | Deny all paths (nothing allowed) |
| `[Path(...)]` | Only paths within listed directories |

```python
from nexus3.core.paths import validate_path, PathSecurityError
from pathlib import Path

# Unrestricted mode
path = validate_path("/any/path", allowed_paths=None)

# Sandboxed mode
try:
    path = validate_path(
        "/etc/passwd",
        allowed_paths=[Path("/project")],
        blocked_paths=[Path("/project/.env")]
    )
except PathSecurityError as e:
    print(f"Blocked: {e.reason}")
```

---

### path_decision.py - Path Decision Engine

Authoritative, explicit path decision API.

| Export | Description |
|--------|-------------|
| `PathDecisionEngine` | Centralized path access decisions |
| `PathDecision` | Decision result with reasoning |
| `PathDecisionReason` | Enum of decision reasons |

**Decision Reasons:**

| Reason | Description |
|--------|-------------|
| `UNRESTRICTED` | No allowed_paths configured |
| `WITHIN_ALLOWED` | Path is within an allowed directory |
| `CWD_DEFAULT` | Using agent's default cwd |
| `BLOCKED` | Path is in blocked_paths |
| `OUTSIDE_ALLOWED` | Path not in any allowed directory |
| `NO_ALLOWED_PATHS` | Empty allowed_paths list |
| `RESOLUTION_FAILED` | Invalid path or dangling symlink |
| `PATH_NOT_FOUND` | Path doesn't exist (when must_exist=True) |
| `NOT_A_DIRECTORY` | Path isn't a directory (when must_be_dir=True) |

```python
from nexus3.core.path_decision import PathDecisionEngine
from pathlib import Path

engine = PathDecisionEngine(
    allowed_paths=[Path("/home/user/project")],
    blocked_paths=[Path("/home/user/project/.env")],
)

# Check access with explicit decision
decision = engine.check_access("/home/user/project/src/main.py")
if decision.allowed:
    with open(decision.resolved_path) as f:
        content = f.read()
else:
    print(f"Denied: {decision.reason_detail}")

# Convenience: raise if denied
path = engine.check_access("/some/path").raise_if_denied()

# Check cwd for subprocess
cwd_decision = engine.check_cwd("/project/scripts", tool_name="bash")

# From ServiceContainer (per-agent paths)
engine = PathDecisionEngine.from_services(services, tool_name="read_file")
```

---

### resolver.py - Unified Path Resolver

Unified path resolution using ServiceContainer for per-agent configuration.

| Export | Description |
|--------|-------------|
| `PathResolver` | Resolve paths relative to agent's cwd with security |

```python
from nexus3.core.resolver import PathResolver

resolver = PathResolver(services)

# Resolve path (raises PathSecurityError if denied)
safe_path = resolver.resolve("data.txt", tool_name="read_file", must_exist=True)

# Resolve without raising
path, error = resolver.resolve_or_error("data.txt", must_exist=True)
if error:
    print(f"Error: {error}")

# Resolve cwd for subprocess
cwd_str, error = resolver.resolve_cwd("/project/scripts", tool_name="bash")
```

---

### url_validator.py - SSRF Protection

URL validation with IP range blocking.

| Export | Description |
|--------|-------------|
| `validate_url()` | Validate URL against SSRF attacks |
| `UrlSecurityError` | Raised when URL fails validation |

**Blocked Ranges:**

- Cloud metadata endpoints (169.254.169.254)
- Link-local addresses (169.254.0.0/16)
- Private networks (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
- Loopback (127.0.0.0/8, unless allow_localhost=True)
- IPv6 private/link-local (fc00::/7, fe80::/10)
- Multicast addresses

```python
from nexus3.core import validate_url, UrlSecurityError

# Default: block localhost and private
try:
    validate_url("http://169.254.169.254/metadata")  # Always blocked
except UrlSecurityError as e:
    print(f"Blocked: {e.reason}")

# Allow localhost (for local server connections)
validate_url("http://localhost:8765/", allow_localhost=True)

# Allow private networks (for internal deployments)
validate_url("http://192.168.1.100/api", allow_private=True)
```

---

### validation.py - Input Validation

Validation utilities for security-sensitive inputs.

| Export | Description |
|--------|-------------|
| `validate_agent_id()` | Validate agent ID format |
| `is_valid_agent_id()` | Check validity without raising |
| `validate_tool_arguments()` | Validate arguments against JSON schema |
| `ValidationError` | Raised when validation fails |
| `AGENT_ID_PATTERN` | Regex for valid agent IDs |
| `ALLOWED_INTERNAL_PARAMS` | Whitelisted internal parameters |

```python
from nexus3.core.validation import validate_agent_id, validate_tool_arguments

# Agent ID: 1-63 chars, alphanumeric/dot/underscore/hyphen
validate_agent_id("worker-1")  # OK
validate_agent_id(".temp")  # OK (temp agent)
validate_agent_id("../evil")  # Raises ValidationError

# Tool argument validation
args = validate_tool_arguments(
    {"path": "/file.txt", "unknown": "ignored"},
    schema={"type": "object", "properties": {"path": {"type": "string"}}}
)
# Returns: {"path": "/file.txt"}
```

---

### identifiers.py - Tool Name Handling

Canonical tool/skill name validation and normalization.

| Export | Description |
|--------|-------------|
| `validate_tool_name()` | Validate tool name format |
| `is_valid_tool_name()` | Check validity without raising |
| `normalize_tool_name()` | Normalize external name to valid format |
| `build_mcp_skill_name()` | Build MCP skill name from server + tool |
| `parse_mcp_skill_name()` | Parse MCP skill name to (server, tool) |
| `ToolNameError` | Raised when name is invalid |
| `RESERVED_TOOL_NAMES` | Names that cannot be used |

```python
from nexus3.core.identifiers import normalize_tool_name, build_mcp_skill_name

# Normalize external names
normalize_tool_name("My Tool!")  # "my_tool"
normalize_tool_name("123-start")  # "_123_start"
normalize_tool_name("uber-tool")  # "uber_tool"

# Build MCP skill names
build_mcp_skill_name("github", "list-repos")  # "mcp_github_list_repos"
build_mcp_skill_name("evil/../path", "../../etc")  # "mcp_evil_path_etc"
```

---

### process.py - Cross-Platform Process Termination

Provides robust process tree termination that works on both Unix and Windows.

```python
from nexus3.core.process import terminate_process_tree, WINDOWS_CREATIONFLAGS

# Terminates process and all children
await terminate_process_tree(process, graceful_timeout=2.0)
```

**Unix behavior:**
1. Send SIGTERM to process group
2. Wait for graceful timeout
3. Send SIGKILL if still running

**Windows behavior:**
1. Send CTRL_BREAK_EVENT
2. Wait for graceful timeout
3. Use `taskkill /T /F` for process tree termination
4. Fall back to `process.kill()` if needed

**Constants:**
- `GRACEFUL_TIMEOUT`: Default timeout (2.0 seconds)
- `WINDOWS_CREATIONFLAGS`: Subprocess flags for Windows (`CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`)

**Usage with subprocess creation:**
```python
import subprocess
from nexus3.core.process import WINDOWS_CREATIONFLAGS

# Create subprocess without visible window on Windows
process = await asyncio.create_subprocess_exec(
    "git", "status",
    creationflags=WINDOWS_CREATIONFLAGS,  # 0 on Unix, flags on Windows
)
```

---

### cancel.py - Cancellation Support

Cooperative cancellation for async operations.

| Export | Description |
|--------|-------------|
| `CancellationToken` | Token for cancelling async operations |

```python
from nexus3.core import CancellationToken

token = CancellationToken()

async def long_operation():
    for chunk in stream:
        token.raise_if_cancelled()  # Raises CancelledError
        yield chunk

# Register callback
token.on_cancel(lambda: print("Cancelled!"))

# Cancel from elsewhere (e.g., ESC key)
token.cancel()

# Check status
if token.is_cancelled:
    print("Operation was cancelled")

# Reset for reuse
token.reset()
```

---

### encoding.py - UTF-8 Encoding

Encoding constants and stdio configuration.

| Export | Description |
|--------|-------------|
| `ENCODING` | `"utf-8"` |
| `ENCODING_ERRORS` | `"replace"` (preserve data, mark corruption) |
| `configure_stdio()` | Reconfigure stdin/stdout/stderr to UTF-8 |

```python
from nexus3.core import ENCODING, ENCODING_ERRORS, configure_stdio

# Call at application startup
configure_stdio()

# Use constants for file I/O
with open(path, encoding=ENCODING, errors=ENCODING_ERRORS) as f:
    content = f.read()
```

---

### constants.py - Global Constants

Global paths and file I/O limits.

| Constant | Value | Description |
|----------|-------|-------------|
| `NEXUS_DIR_NAME` | `".nexus3"` | Config directory name |
| `MAX_FILE_SIZE_BYTES` | 10 MB | Max file size to read |
| `MAX_OUTPUT_BYTES` | 1 MB | Max tool output size |
| `MAX_READ_LINES` | 10000 | Default max lines to read |
| `MAX_GREP_FILE_SIZE` | 5 MB | Max file size for grep |

| Function | Description |
|----------|-------------|
| `get_nexus_dir()` | Returns `~/.nexus3` |
| `get_defaults_dir()` | Returns package defaults directory |
| `get_sessions_dir()` | Returns `~/.nexus3/sessions` |
| `get_default_config_path()` | Returns `~/.nexus3/config.json` |
| `get_rpc_token_path(port)` | Returns RPC token file path |

---

### redaction.py - Secret Redaction

Pattern-based secret detection and redaction.

| Export | Description |
|--------|-------------|
| `redact_secrets()` | Redact secrets from text string |
| `redact_dict()` | Recursively redact secrets from dict |
| `REDACTED` | Placeholder: `"[REDACTED]"` |
| `SECRET_PATTERNS` | Dict of pattern name -> (regex, replacement) |

**Detected Patterns:**

- OpenAI API keys (`sk-...`)
- Anthropic API keys (`sk-ant-...`)
- GitHub tokens (`ghp_`, `gho_`, etc.)
- AWS keys (access key ID, secret key)
- Bearer tokens in headers
- Generic API keys
- Passwords (in assignments and URLs)
- Private key blocks (RSA, ECDSA, etc.)
- Database connection strings
- JWT tokens
- NEXUS3 RPC tokens (`nxk_...`)

```python
from nexus3.core.redaction import redact_secrets, redact_dict

text = "api_key = sk-abc123456789"
redact_secrets(text)  # "api_key = [REDACTED]"

data = {"password": "secret123", "nested": {"token": "ghp_abc123"}}
redact_dict(data)  # {"password": "[REDACTED]", "nested": {"token": "[REDACTED]"}}
```

---

### secure_io.py - Secure File I/O

Atomic, race-condition-free file operations.

| Export | Description |
|--------|-------------|
| `secure_mkdir()` | Create directory with 0o700 permissions |
| `secure_write_new()` | Atomically create new file with 0o600 |
| `secure_write_atomic()` | Atomically write new or existing file |
| `ensure_secure_file()` | Fix permissions on existing file |
| `ensure_secure_dir()` | Fix permissions on existing directory |
| `secure_append()` | Append content, refusing symlinks |
| `check_no_symlink()` | Raise if path is a symlink |
| `SymlinkError` | Raised for symlink violations |
| `SECURE_DIR_MODE` | `0o700` |
| `SECURE_FILE_MODE` | `0o600` |

```python
from nexus3.core.secure_io import secure_write_new, secure_mkdir, SymlinkError

# Create directory with secure permissions
secure_mkdir(Path("/tmp/session"))

# Atomically create file (fails if exists)
secure_write_new(Path("/tmp/session/token"), "secret")

# Append without following symlinks
try:
    secure_append(Path("/tmp/log"), "entry\n")
except SymlinkError:
    print("Refusing to write through symlink")
```

---

### text_safety.py - Terminal Safety

Text sanitization for safe terminal output.

| Export | Description |
|--------|-------------|
| `strip_terminal_escapes()` | Remove ANSI escapes and control chars |
| `escape_rich_markup()` | Escape Rich `[tag]` markup |
| `sanitize_for_display()` | Full sanitization (both) |

```python
from nexus3.core.text_safety import sanitize_for_display

untrusted = "\x1b[31m[red]malicious[/red]\x1b[0m"
safe = sanitize_for_display(untrusted)
# Returns: "\\[red]malicious\\[/red]" (escapes visible, ANSI stripped)
```

---

### utils.py - Shared Utilities

Common operations used across modules.

| Export | Description |
|--------|-------------|
| `deep_merge()` | Recursively merge dicts (lists REPLACED, not extended) |
| `find_ancestor_config_dirs()` | Find `.nexus3` dirs in parent paths |

```python
from nexus3.core.utils import deep_merge

base = {"a": 1, "b": {"x": 1}, "blocked": ["/etc"]}
override = {"b": {"y": 2}, "blocked": []}  # Empty list replaces

result = deep_merge(base, override)
# {"a": 1, "b": {"x": 1, "y": 2}, "blocked": []}
```

---

## Data Flow

```
User Message
    │
    ▼
AsyncProvider.stream()
    │
    ├──▶ ContentDelta (display text)
    ├──▶ ReasoningDelta (thinking)
    ├──▶ ToolCallStarted (show "calling read_file...")
    │
    ▼
StreamComplete(Message)
    │
    ├── If tool_calls:
    │   │
    │   ▼
    │   Permission Check (AgentPermissions)
    │   │
    │   ├── requires_confirmation() → User Prompt
    │   │   │
    │   │   └── SessionAllowances (store "allow always")
    │   │
    │   ▼
    │   Path Validation (PathDecisionEngine)
    │   │
    │   ▼
    │   Tool Execution → ToolResult
    │   │
    │   └── Loop back to provider with tool results
    │
    └── Final assistant response
```

---

## Dependencies

- **Stdlib**: asyncio, dataclasses, enum, ipaddress, pathlib, re, socket, stat, tempfile, unicodedata
- **PyPI**: jsonschema (validation), rich (markup escaping)

---

## Security Considerations

1. **Path Validation**: Always use `validate_path()` or `PathDecisionEngine` - never raw Path operations
2. **URL Validation**: Always use `validate_url()` before HTTP requests
3. **Input Sanitization**: Use `sanitize_for_display()` for untrusted terminal output
4. **Secret Redaction**: Use `redact_secrets()` before logging or external transmission
5. **Secure I/O**: Use `secure_write_*` functions for sensitive files (tokens, sessions)
6. **Agent IDs**: Always validate with `validate_agent_id()` before use
7. **Tool Names**: Normalize external names with `normalize_tool_name()`
