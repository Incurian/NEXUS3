# nexus3.skill - NEXUS3 Skill (Tool) System

**Updated: 2026-01-21**

The skill module provides the complete infrastructure for defining, registering, and executing skills (tools) that extend NEXUS3 agent capabilities. Skills are the fundamental unit of capability in NEXUS3 - they provide actions like file reading, command execution, agent management, and other operations the agent can perform.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Skill Protocol](#skill-protocol)
4. [Base Classes](#base-classes)
5. [ServiceContainer](#servicecontainer)
6. [SkillRegistry](#skillregistry)
7. [Built-in Skills](#built-in-skills)
8. [Creating New Skills](#creating-new-skills)
9. [Security Model](#security-model)
10. [Errors](#errors)
11. [Module Exports](#module-exports)
12. [Dependencies](#dependencies)

---

## Overview

Skills are the tool system in NEXUS3. Each skill provides a single, well-defined action that an agent can invoke. The system features:

- **Protocol-based design**: Skills implement a simple protocol with `name`, `description`, `parameters`, and `execute()`
- **Factory-based instantiation**: Skills are registered as factories for lazy creation with dependency injection
- **Base class hierarchy**: Specialized base classes handle common patterns (file operations, subprocess execution, server communication)
- **Permission integration**: Per-tool path restrictions and permission-level filtering
- **JSON Schema validation**: Automatic parameter validation before execution
- **Security hardening**: Path validation, symlink resolution, sandbox enforcement, environment sanitization

---

## Architecture

```
nexus3/skill/
├── __init__.py           # Public API exports
├── base.py               # Skill protocol and base classes
├── registry.py           # SkillRegistry for managing skills
├── services.py           # ServiceContainer for dependency injection
├── errors.py             # Skill-specific error classes
└── builtin/              # Built-in skill implementations
    ├── __init__.py       # Builtin exports
    ├── registration.py   # register_builtin_skills() function
    ├── env.py            # Environment sanitization helpers
    ├── read_file.py      # File reading skill
    ├── write_file.py     # File writing skill
    ├── edit_file.py      # File editing skill
    ├── append_file.py    # File appending skill
    ├── tail.py           # Read last N lines
    ├── file_info.py      # File metadata skill
    ├── list_directory.py # Directory listing skill
    ├── copy_file.py      # File copying skill
    ├── mkdir.py          # Directory creation skill
    ├── rename.py         # File/directory renaming skill
    ├── glob_search.py    # Glob pattern file search
    ├── grep.py           # Regex content search
    ├── regex_replace.py  # Regex find/replace
    ├── bash.py           # Shell execution (safe + unsafe)
    ├── run_python.py     # Python code execution
    ├── git.py            # Git version control
    ├── nexus_create.py   # Create agent
    ├── nexus_destroy.py  # Destroy agent
    ├── nexus_send.py     # Send message to agent
    ├── nexus_status.py   # Get agent status
    ├── nexus_cancel.py   # Cancel agent request
    ├── nexus_shutdown.py # Shutdown server
    ├── sleep.py          # Testing utility
    └── echo.py           # Testing utility
```

---

## Skill Protocol

All skills must implement the `Skill` protocol:

```python
from typing import Any, Protocol, runtime_checkable
from nexus3.core.types import ToolResult

@runtime_checkable
class Skill(Protocol):
    @property
    def name(self) -> str:
        """Unique skill name (used in tool calls, snake_case)."""
        ...

    @property
    def description(self) -> str:
        """Human-readable description for LLM."""
        ...

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for parameters."""
        ...

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the skill with given arguments."""
        ...
```

### ToolResult

Skills return `ToolResult` from `nexus3.core.types`:

```python
@dataclass(frozen=True)
class ToolResult:
    output: str = ""      # Success output (mutually exclusive with error)
    error: str = ""       # Error message (mutually exclusive with output)

    @property
    def success(self) -> bool:
        return not self.error
```

### JSON Schema Parameters

The `parameters` property returns a JSON Schema object:

```python
@property
def parameters(self) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to read"
            },
            "offset": {
                "type": "integer",
                "description": "Line number to start from (1-indexed)",
                "minimum": 1,
                "default": 1
            }
        },
        "required": ["path"]
    }
```

---

## Base Classes

The module provides specialized base classes that handle common patterns:

### BaseSkill

Minimal abstract base for simple skills. Stores name/description/parameters as instance attributes:

```python
from nexus3.skill.base import BaseSkill, base_skill_factory
from nexus3.core.types import ToolResult

@base_skill_factory
class MySimpleSkill(BaseSkill):
    def __init__(self):
        super().__init__(
            name="my_skill",
            description="Does something useful",
            parameters={
                "type": "object",
                "properties": {
                    "input": {"type": "string", "description": "Input value"}
                },
                "required": ["input"]
            }
        )

    async def execute(self, input: str = "", **kwargs: Any) -> ToolResult:
        return ToolResult(output=f"Processed: {input}")
```

### FileSkill

For skills that operate on files. Provides unified path validation with sandbox enforcement:

```python
from nexus3.skill.base import FileSkill, file_skill_factory
from nexus3.core.types import ToolResult

@file_skill_factory
class MyFileSkill(FileSkill):
    # FileSkill.__init__ takes ServiceContainer automatically

    @property
    def name(self) -> str:
        return "my_file_skill"

    @property
    def description(self) -> str:
        return "Operates on a file"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"}
            },
            "required": ["path"]
        }

    async def execute(self, path: str = "", **kwargs: Any) -> ToolResult:
        try:
            # _validate_path resolves symlinks, checks allowed_paths
            validated_path = self._validate_path(path)
            content = validated_path.read_text()
            return ToolResult(output=content)
        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))
```

**Key features:**
- `_validate_path(path)` - Validates and resolves path against allowed_paths
- `_allowed_paths` property - Access to effective allowed paths for this tool
- Symlink resolution prevents sandbox escape
- Per-tool path overrides via ServiceContainer

### NexusSkill

For skills that communicate with Nexus server:

```python
from nexus3.skill.base import NexusSkill, nexus_skill_factory
from nexus3.core.types import ToolResult

@nexus_skill_factory
class MyNexusSkill(NexusSkill):
    @property
    def name(self) -> str:
        return "my_nexus_skill"

    @property
    def description(self) -> str:
        return "Communicates with Nexus server"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Target agent"},
                "port": {"type": "integer", "description": "Server port"}
            },
            "required": ["agent_id"]
        }

    async def execute(
        self, agent_id: str = "", port: int | None = None, **kwargs: Any
    ) -> ToolResult:
        # Validate agent_id
        if error := self._validate_agent_id(agent_id):
            return error

        # Use _execute_with_client for automatic HTTP/DirectAPI handling
        return await self._execute_with_client(
            port=port,
            agent_id=agent_id,
            operation=lambda client: client.some_method()
        )
```

**Key features:**
- `_execute_with_client()` - Handles HTTP vs DirectAgentAPI routing
- `_validate_agent_id()` - Common agent_id validation
- `_get_port()` / `_get_api_key()` - Port and auth discovery
- `_build_url()` - URL construction
- `_can_use_direct_api()` - Check for in-process optimization

### ExecutionSkill

For skills that run subprocesses:

```python
from nexus3.skill.base import ExecutionSkill, execution_skill_factory
from nexus3.core.types import ToolResult
import asyncio

@execution_skill_factory
class MyExecSkill(ExecutionSkill):
    MAX_TIMEOUT = 300   # Override class defaults
    DEFAULT_TIMEOUT = 30

    def __init__(self, services):
        super().__init__(services)
        self._command: str = ""

    @property
    def name(self) -> str:
        return "my_exec_skill"

    @property
    def description(self) -> str:
        return "Executes a command"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "default": 30},
                "cwd": {"type": "string"}
            },
            "required": ["command"]
        }

    async def _create_process(self, work_dir: str | None) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_exec(
            "my_program", self._command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
            start_new_session=True  # For clean process group kills
        )

    async def execute(
        self, command: str = "", timeout: int = 30, cwd: str | None = None, **kwargs
    ) -> ToolResult:
        if not command:
            return ToolResult(error="Command required")

        self._command = command
        return await self._execute_subprocess(
            timeout=timeout,
            cwd=cwd,
            timeout_message="Timed out after {timeout}s"
        )
```

**Key features:**
- `_execute_subprocess()` - Common subprocess execution with timeout
- `_create_process()` - Abstract method for subprocess creation
- `_enforce_timeout()` - Clamp timeout to valid range
- `_resolve_working_directory()` - Validate cwd against sandbox
- `_format_output()` - Format stdout/stderr for return
- Process group kills on timeout (SIGKILL to pgid)

### FilteredCommandSkill

For skills with permission-based command filtering (e.g., git, docker):

```python
from nexus3.skill.base import FilteredCommandSkill, filtered_command_skill_factory
from nexus3.core.types import ToolResult

@filtered_command_skill_factory
class MyFilteredSkill(FilteredCommandSkill):
    @property
    def name(self) -> str:
        return "my_filtered"

    @property
    def description(self) -> str:
        return "Filtered command execution"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"}
            },
            "required": ["command"]
        }

    def get_read_only_commands(self) -> frozenset[str]:
        """Commands allowed in SANDBOXED mode."""
        return frozenset({"status", "list", "info"})

    def get_blocked_patterns(self) -> list[tuple[str, str]]:
        """Regex patterns blocked in TRUSTED mode."""
        return [
            (r"delete.*--force", "Force delete is blocked"),
            (r"drop\s+database", "Database drops blocked"),
        ]

    async def execute(self, command: str = "", cwd: str = ".", **kwargs) -> ToolResult:
        # Check if command is allowed
        allowed, error = self._is_command_allowed(command)
        if not allowed:
            return ToolResult(error=error)

        # Validate working directory
        work_dir, error = self._validate_cwd(cwd)
        if error:
            return ToolResult(error=error)

        # Execute command...
```

**Key features:**
- `get_read_only_commands()` - Commands allowed in SANDBOXED mode
- `get_blocked_patterns()` - Regex patterns blocked in TRUSTED mode
- `_is_command_allowed()` - Check command against permission level
- `_validate_cwd()` - Working directory validation
- `_permission_level` property - Access current permission level

### Filtering Model

| Permission Level | Behavior |
|------------------|----------|
| YOLO | All commands allowed |
| TRUSTED | Commands not matching blocked patterns allowed |
| SANDBOXED | Only whitelisted read-only commands allowed |

---

## ServiceContainer

A simple dependency injection container for skills:

```python
from nexus3.skill.services import ServiceContainer

services = ServiceContainer()

# Basic operations
services.register("name", value)
services.get("name")           # Returns value or None
services.require("name")       # Returns value or raises KeyError
services.has("name")           # Returns bool
services.unregister("name")    # Removes and returns value
services.clear()               # Remove all services
services.names()               # List registered names
```

### Typed Accessors

ServiceContainer provides typed accessors for common services:

```python
# Permission-related
services.get_permissions()           # AgentPermissions | None
services.get_permission_level()      # PermissionLevel | None
services.get_tool_allowed_paths(tool_name)  # list[Path] | None
services.get_blocked_paths()         # list[Path]

# Agent-related
services.get_cwd()                   # Path (defaults to process cwd)
services.get_agent_api()             # DirectAgentAPI | None
services.get_child_agent_ids()       # set[str] | None
services.get_mcp_registry()          # MCPServerRegistry | None
```

### Common Services

| Service Name | Type | Description |
|--------------|------|-------------|
| `permissions` | `AgentPermissions` | Agent's full permission config |
| `permission_level` | `PermissionLevel` | Shortcut to level only |
| `cwd` | `Path` | Agent's working directory |
| `allowed_paths` | `list[Path]` | Paths agent can access |
| `blocked_paths` | `list[Path]` | Paths agent cannot access |
| `agent_api` | `DirectAgentAPI` | In-process agent communication |
| `agent_id` | `str` | Current agent's ID |
| `port` | `int` | Server port |
| `api_key` | `str` | RPC authentication token |
| `child_agent_ids` | `set[str]` | IDs of child agents |
| `mcp_registry` | `MCPServerRegistry` | MCP server registry |

### Per-Tool Path Resolution

The `get_tool_allowed_paths()` method resolves per-tool path overrides:

1. Check `permissions.tool_permissions[tool_name].allowed_paths`
2. If None, fall back to `permissions.effective_policy.allowed_paths`
3. If no permissions registered, fall back to `allowed_paths` service (for tests)

This enables different tools to have different path restrictions:

```python
# Example: read_file can read anywhere, write_file restricted to output/
permissions.tool_permissions = {
    "read_file": ToolPermission(allowed_paths=None),  # Unrestricted
    "write_file": ToolPermission(allowed_paths=[Path("/project/output")]),
}
```

---

## SkillRegistry

Manages skill registration and instantiation:

```python
from nexus3.skill import SkillRegistry, ServiceContainer

# Create registry with service container
services = ServiceContainer()
services.register("permissions", agent_permissions)
services.register("cwd", Path("/sandbox"))

registry = SkillRegistry(services)
```

### Registration

```python
# Register with factory function
def my_skill_factory(services: ServiceContainer) -> MySkill:
    return MySkill(services)

registry.register("my_skill", my_skill_factory)

# Register with optional metadata (avoids instantiation for get_definitions)
registry.register(
    "my_skill",
    my_skill_factory,
    description="Does something useful",
    parameters={"type": "object", "properties": {...}}
)
```

### Retrieval

```python
# Get skill instance (lazy instantiation)
skill = registry.get("my_skill")
if skill:
    result = await skill.execute(param="value")

# List registered names
names = registry.names  # ["my_skill", "read_file", ...]

# Access service container
services = registry.services
```

### Tool Definitions

Generate OpenAI-format tool definitions for LLM:

```python
# All registered skills
definitions = registry.get_definitions()

# Filtered by permissions (disabled tools excluded)
definitions = registry.get_definitions_for_permissions(agent_permissions)
```

Returns list of:
```python
{
    "type": "function",
    "function": {
        "name": "skill_name",
        "description": "skill description",
        "parameters": {...json_schema...}
    }
}
```

### SkillSpec

Internal metadata storage for skills:

```python
@dataclass(frozen=True)
class SkillSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    factory: SkillFactory
```

---

## Built-in Skills

NEXUS3 includes 24 built-in skills organized by category:

### File Operations (Read-Only)

| Skill | Description | Key Parameters |
|-------|-------------|----------------|
| `read_file` | Read file contents | `path`, `offset?`, `limit?` |
| `tail` | Read last N lines | `path`, `lines?` (default: 10) |
| `file_info` | Get file/directory metadata | `path` |
| `list_directory` | List directory contents | `path`, `all?`, `long?` |
| `glob` | Find files by glob pattern | `pattern`, `path?`, `max_results?`, `exclude?` |
| `grep` | Search file contents (regex) | `pattern`, `path`, `recursive?`, `include?`, `context?` |

### File Operations (Destructive)

| Skill | Description | Key Parameters |
|-------|-------------|----------------|
| `write_file` | Write/create file | `path`, `content` |
| `edit_file` | String/line replacement | `path`, `old_string`, `new_string`, `replace_all?` |
| `append_file` | Append to file | `path`, `content`, `newline?` |
| `regex_replace` | Pattern-based replace | `path`, `pattern`, `replacement`, `count?` |
| `copy_file` | Copy file | `source`, `destination`, `overwrite?` |
| `mkdir` | Create directory | `path` |
| `rename` | Rename/move file or directory | `source`, `destination`, `overwrite?` |

### Execution

| Skill | Description | Key Parameters |
|-------|-------------|----------------|
| `bash_safe` | Safe command execution (no shell) | `command`, `timeout?`, `cwd?` |
| `shell_UNSAFE` | Full shell execution | `command`, `timeout?`, `cwd?` |
| `run_python` | Execute Python code | `code`, `timeout?`, `cwd?` |

### Version Control

| Skill | Description | Key Parameters |
|-------|-------------|----------------|
| `git` | Git operations (filtered) | `command`, `cwd?` |

### Agent Management

| Skill | Description | Key Parameters |
|-------|-------------|----------------|
| `nexus_create` | Create new agent | `agent_id`, `preset?`, `cwd?`, `model?`, `initial_message?` |
| `nexus_destroy` | Destroy agent | `agent_id`, `port?` |
| `nexus_send` | Send message to agent | `agent_id`, `content`, `port?` |
| `nexus_status` | Get agent status | `agent_id`, `port?` |
| `nexus_cancel` | Cancel agent request | `agent_id`, `request_id`, `port?` |
| `nexus_shutdown` | Shutdown server | `port?` |

### Utility

| Skill | Description | Key Parameters |
|-------|-------------|----------------|
| `sleep` | Pause execution | `seconds`, `label?` |
| `echo` | Echo input (testing) | `message` |

### Registration

```python
from nexus3.skill.builtin.registration import register_builtin_skills

registry = SkillRegistry(services)
register_builtin_skills(registry)  # Registers all 24 skills
```

---

## Creating New Skills

### Step 1: Choose Base Class

| Use Case | Base Class |
|----------|------------|
| Simple utility | `BaseSkill` or `@base_skill_factory` |
| File operations | `FileSkill` + `@file_skill_factory` |
| Server communication | `NexusSkill` + `@nexus_skill_factory` |
| Subprocess execution | `ExecutionSkill` + `@execution_skill_factory` |
| Permission-filtered commands | `FilteredCommandSkill` + `@filtered_command_skill_factory` |

### Step 2: Implement the Skill

```python
# Example: A FileSkill for counting lines

from typing import Any
from nexus3.skill.base import FileSkill, file_skill_factory
from nexus3.core.types import ToolResult
from nexus3.core.errors import PathSecurityError


@file_skill_factory
class LineCountSkill(FileSkill):
    """Count lines in a file."""

    @property
    def name(self) -> str:
        return "line_count"

    @property
    def description(self) -> str:
        return "Count the number of lines in a file"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file"
                }
            },
            "required": ["path"]
        }

    async def execute(self, path: str = "", **kwargs: Any) -> ToolResult:
        if not path:
            return ToolResult(error="No path provided")

        try:
            validated = self._validate_path(path)
            content = validated.read_text(encoding="utf-8", errors="replace")
            count = len(content.splitlines())
            return ToolResult(output=f"{count} lines")
        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))
        except FileNotFoundError:
            return ToolResult(error=f"File not found: {path}")
        except PermissionError:
            return ToolResult(error=f"Permission denied: {path}")
        except Exception as e:
            return ToolResult(error=f"Error: {e}")


# Factory is attached by decorator
line_count_factory = LineCountSkill.factory
```

### Step 3: Register the Skill

```python
# Option 1: Direct registration
registry.register("line_count", line_count_factory)

# Option 2: Add to register_builtin_skills() in registration.py
def register_builtin_skills(registry: SkillRegistry) -> None:
    # ... existing skills ...
    registry.register("line_count", line_count_factory)
```

### Best Practices

1. **Use appropriate base class** - Don't reinvent path validation or subprocess handling
2. **Validate early** - Check required parameters at start of execute()
3. **Return ToolResult** - Never raise exceptions; always return ToolResult(error=...)
4. **Single responsibility** - One skill = one action
5. **Use `asyncio.to_thread`** - For blocking I/O operations
6. **Handle all errors** - Catch and convert to ToolResult errors
7. **Document parameters** - Include descriptions in JSON schema

---

## Security Model

### Path Validation

All FileSkill operations go through `_validate_path()`:

1. Resolve relative paths against agent's cwd
2. Follow symlinks and check real path
3. Validate against `allowed_paths` (if set)
4. Check against `blocked_paths` (always enforced)

```python
# Sandbox escape via symlink is prevented:
# /sandbox/link -> /etc/passwd
# _validate_path("/sandbox/link") -> raises PathSecurityError
```

### Per-Tool Path Restrictions

Different tools can have different path restrictions:

```python
# write_file restricted to output/, read_file unrestricted
tool_permissions = {
    "write_file": ToolPermission(allowed_paths=[Path("/project/output")]),
    "read_file": ToolPermission(allowed_paths=None),  # Unrestricted
}
```

### Permission Levels

| Level | Behavior |
|-------|----------|
| YOLO | Everything allowed, no confirmations |
| TRUSTED | Destructive actions may require confirmation |
| SANDBOXED | Limited to cwd, many tools disabled |

### Defense-in-Depth

Execution skills (`bash_safe`, `shell_UNSAFE`, `run_python`) internally check permission level:

```python
# In execute():
if self._services.get_permission_level() == PermissionLevel.SANDBOXED:
    return ToolResult(
        error=f"{self.name} is disabled in SANDBOXED mode. "
        "This is a defense-in-depth check."
    )
```

### Environment Sanitization

Subprocess execution uses sanitized environments:

```python
from nexus3.skill.builtin.env import get_safe_env

# Only passes safe variables (PATH, HOME, LANG, etc.)
# Blocks API keys, tokens, credentials
env = get_safe_env(cwd="/some/path")
```

### Git Command Filtering

Git commands are filtered by permission level:

- **SANDBOXED**: Only read-only commands (status, diff, log, etc.)
- **TRUSTED**: Read + write, but dangerous flags blocked (--force, --hard)
- **YOLO**: All commands allowed

---

## Errors

The module defines skill-specific errors:

```python
from nexus3.skill.errors import SkillError, SkillNotFoundError, SkillExecutionError

class SkillError(NexusError):
    """Base class for skill errors."""

class SkillNotFoundError(SkillError):
    """Raised when skill not in registry."""
    def __init__(self, skill_name: str): ...

class SkillExecutionError(SkillError):
    """Raised when skill execution fails."""
    def __init__(self, skill_name: str, reason: str): ...
```

---

## Module Exports

### From `nexus3.skill`

```python
__all__ = [
    # Protocol and base classes
    "Skill",
    "BaseSkill",
    "FileSkill",
    "NexusSkill",
    "ExecutionSkill",
    "FilteredCommandSkill",
    # Factory decorators
    "file_skill_factory",
    "nexus_skill_factory",
    "execution_skill_factory",
    "filtered_command_skill_factory",
    # Registry
    "SkillRegistry",
    "SkillFactory",
    "SkillSpec",
    # Services
    "ServiceContainer",
    # Errors
    "SkillError",
    "SkillNotFoundError",
    "SkillExecutionError",
]
```

### From `nexus3.skill.builtin`

```python
__all__ = [
    "register_builtin_skills",
    "nexus_send_factory",
    "nexus_cancel_factory",
    "nexus_status_factory",
    "nexus_shutdown_factory",
]
```

---

## Dependencies

### Internal Dependencies

| Module | Used For |
|--------|----------|
| `nexus3.core.types` | `ToolResult` |
| `nexus3.core.errors` | `NexusError`, `PathSecurityError` |
| `nexus3.core.paths` | `validate_path()`, `atomic_write_text()` |
| `nexus3.core.resolver` | `PathResolver` for path resolution |
| `nexus3.core.permissions` | `PermissionLevel`, `AgentPermissions` |
| `nexus3.core.validation` | Parameter validation, agent ID validation |
| `nexus3.core.identifiers` | `validate_tool_name()` |
| `nexus3.core.constants` | File size limits |
| `nexus3.core.url_validator` | URL validation for NexusSkill |
| `nexus3.client` | `NexusClient` for HTTP communication |
| `nexus3.rpc.auth` | `discover_rpc_token()` |
| `nexus3.rpc.agent_api` | `DirectAgentAPI`, `ClientAdapter` |

### External Dependencies

| Package | Used For |
|---------|----------|
| `jsonschema` | Parameter validation |
| `asyncio` | Async execution |
| `pathlib` | Path handling |
| `shlex` | Safe command parsing |
| `subprocess` | Git command execution |

---

## Usage Example

Complete example of setting up and using the skill system:

```python
import asyncio
from pathlib import Path
from nexus3.skill import SkillRegistry, ServiceContainer
from nexus3.skill.builtin.registration import register_builtin_skills
from nexus3.core.permissions import resolve_preset

async def main():
    # Set up service container
    services = ServiceContainer()
    services.register("cwd", Path.cwd())
    services.register("permissions", resolve_preset("sandboxed", cwd=Path.cwd()))

    # Create registry and register skills
    registry = SkillRegistry(services)
    register_builtin_skills(registry)

    # Get tool definitions for LLM
    definitions = registry.get_definitions()
    print(f"Registered {len(definitions)} skills")

    # Use a skill
    read_skill = registry.get("read_file")
    if read_skill:
        result = await read_skill.execute(path="README.md")
        if result.success:
            print(f"Read {len(result.output)} chars")
        else:
            print(f"Error: {result.error}")

if __name__ == "__main__":
    asyncio.run(main())
```
