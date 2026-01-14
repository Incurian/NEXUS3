# Skill Module

Tool (skill) system for NEXUS3. Provides the infrastructure for defining, registering, and executing skills that extend the agent's capabilities.

## Purpose

This module provides the skill/tool infrastructure for NEXUS3:

- **Skill protocol** (`Skill`) for implementing custom tools
- **BaseSkill** abstract base class for convenience
- **Specialized base classes** (`FileSkill`, `NexusSkill`, `ExecutionSkill`, `FilteredCommandSkill`) for common patterns
- **SkillRegistry** for managing skill factories with lazy instantiation and caching
- **ServiceContainer** for dependency injection into skills
- **23 built-in skills** for file I/O, search, execution, git, agent control, and testing (+ `echo` manual)

Skills are the fundamental unit of capability in NEXUS3. Each skill provides a single, well-defined, async-executable action that the LLM invokes via function calling.

## Key Components

| Component | Description |
|-----------|-------------|
| `Skill` | Runtime-checkable protocol: `name`, `description`, `parameters`, `async execute(**kwargs) -> ToolResult` |
| `BaseSkill` | `ABC` subclass of `Skill`; set metadata in `__init__`, implement `execute` |
| `FileSkill` | Base for file I/O skills; auto-validates paths against `allowed_paths` sandbox |
| `NexusSkill` | Base for agent control skills; handles port/API key/URL/client management |
| `ExecutionSkill` | Base for subprocess skills; timeout enforcement, output formatting |
| `FilteredCommandSkill` | Base for permission-filtered CLI skills; allow/block lists by `PermissionLevel` |
| `SkillRegistry` | Manages factories; lazy `get(name)`, `get_definitions()`, permission-filtered defs |
| `SkillFactory` | `Callable[[ServiceContainer], Skill]` |
| `ServiceContainer` | Dict-like DI: `register/get/require/has/unregister/clear/names` |
| `ToolResult` | Return type: `ToolResult(output=str \| None, error=str \| None)` |

## Files

| File | Description |
|------|-------------|
| `__init__.py` | Exports: `Skill`, `BaseSkill`, specialized bases, factories, errors |
| `base.py` | `Skill` protocol; base classes: `BaseSkill`, `FileSkill`, `NexusSkill`, `ExecutionSkill`, `FilteredCommandSkill`; factory decorators |
| `registry.py` | `SkillRegistry`, `get_definitions_for_permissions(AgentPermissions)` |
| `services.py` | `ServiceContainer` |
| `errors.py` | `SkillError`, `SkillNotFoundError`, `SkillExecutionError` |
| `builtin/__init__.py` | Exports `register_builtin_skills`, nexus factories |
| `builtin/registration.py` | `register_builtin_skills(registry)` registers all 23 |
| `builtin/*.py` | Individual skills: append_file.py, bash.py, copy_file.py, echo.py, edit_file.py, file_info.py, git.py, glob_search.py, grep.py, list_directory.py, mkdir.py, read_file.py, regex_replace.py, rename.py, run_python.py, sleep.py, tail.py, write_file.py, nexus_*.py |

## Skill Protocol

```python
@runtime_checkable
class Skill(Protocol):
    @property def name(self) -> str: ...  # snake_case, unique
    @property def description(self) -> str: ...  # For LLM
    @property def parameters(self) -> dict[str, Any]: ...  # JSON Schema
    async def execute(self, **kwargs: Any) -> ToolResult: ...
```

## BaseSkill

Convenience `ABC`:

```python
class MySkill(BaseSkill):
    def __init__(self):
        super().__init__(
            name="my_skill",
            description="...",
            parameters={  # JSON Schema
                "type": "object",
                "properties": {"foo": {"type": "string"}},
                "required": ["foo"]
            }
        )
    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult: ...
```

## Specialized Base Classes

Four specialized base classes reduce boilerplate for common skill patterns:

### FileSkill

Base for file I/O skills. Injects `allowed_paths` via `@file_skill_factory`. Validates and resolves paths (symlinks resolved, checked against sandbox).

```python
class ReadFileSkill(FileSkill):
    async def execute(self, path: str = "", **kwargs) -> ToolResult:
        validated = self._validate_path(path)  # Returns Path or ToolResult error
        if isinstance(validated, ToolResult):
            return validated
        return ToolResult(output=validated.read_text())

read_file_factory = file_skill_factory(ReadFileSkill)
```

**Used by:** read_file, write_file, edit_file, append_file, tail, file_info, list_directory, mkdir, copy_file, rename, regex_replace, glob, grep

### NexusSkill

Base for `nexus_*` skills. Injects `ServiceContainer` via `@nexus_skill_factory`. Handles port resolution, API key discovery, localhost URL validation, and `NexusClient` error handling.

```python
class NexusSendSkill(NexusSkill):
    async def execute(self, agent_id: str = "", content: str = "", port: int | None = None, **kwargs) -> ToolResult:
        return await self._execute_with_client(
            port=port, agent_id=agent_id,
            operation=lambda client: client.send(content)
        )

nexus_send_factory = nexus_skill_factory(NexusSendSkill)
```

**Used by:** nexus_create, nexus_destroy, nexus_send, nexus_status, nexus_cancel, nexus_shutdown

### ExecutionSkill

Base for subprocess skills. Enforces 1-300s timeouts, validates working directories, formats stdout/stderr/exit code output. Subclasses implement `_create_process(work_dir)`.

```python
class BashSkill(ExecutionSkill):
    _command: str = ""

    async def _create_process(self, work_dir: str | None) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_shell(self._command, ...)

    async def execute(self, command: str = "", timeout: int = 30, cwd: str | None = None, **kwargs) -> ToolResult:
        self._command = command
        return await self._execute_subprocess(timeout=timeout, cwd=cwd, timeout_message="...")

bash_factory = execution_skill_factory(BashSkill)
```

**Used by:** bash, run_python

### FilteredCommandSkill

Base for permission-filtered CLI skills. Injects `allowed_paths`/`permission_level` via `@filtered_command_skill_factory`. Subclasses implement `get_read_only_commands()` and `get_blocked_patterns()`.

**Permission model:**
- YOLO: All commands allowed
- TRUSTED: All commands except blocked patterns
- SANDBOXED: Read-only whitelist only

```python
class GitSkill(FilteredCommandSkill):
    def get_read_only_commands(self) -> frozenset[str]:
        return frozenset({"status", "diff", "log", "show", "branch"})

    def get_blocked_patterns(self) -> list[tuple[str, str]]:
        return [("reset\\s+--hard", "reset --hard discards uncommitted changes")]

git_factory = filtered_command_skill_factory(GitSkill)
```

**Used by:** git

## SkillRegistry

Lazy instantiation/caching via factories:

```python
services = ServiceContainer()
registry = SkillRegistry(services)
registry.register("my_skill", lambda svc: MySkill(svc.get("foo")))

skill = registry.get("my_skill")  # Instantiates if needed, caches
tools = registry.get_definitions()  # OpenAI format list[dict]
tools = registry.get_definitions_for_permissions(agent.permissions)  # Filtered
names = registry.names
container = registry.services
```

**OpenAI Format Example:**
```json
[{"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}]
```

## ServiceContainer

Simple DI:

```python
services = ServiceContainer()
services.register("allowed_paths", [Path.cwd()])
services.register("api_key", "...")
services.register("port", 8765)
services.register("permissions", agent.permissions)

foo = services.get("foo")  # None if missing
foo = services.require("foo")  # Raises KeyError
services.has("foo")
services.names()
```

**Common Services:**
| Name | Type | Used By |
|------|------|---------|
| `allowed_paths` | `list[Path] \| None` | `FileSkill`, `FilteredCommandSkill` (sandbox) |
| `api_key` | `str \| None` | `NexusSkill` (auth) |
| `port` | `int \| None` | `NexusSkill` (default 8765) |
| `agent_id` | `str \| None` | `nexus_create` (ceiling parent) |
| `permissions` | `AgentPermissions \| None` | `nexus_create` (ceiling check), `FilteredCommandSkill` |
| `permission_level` | `PermissionLevel \| None` | `FilteredCommandSkill` (command filtering) |

## Built-in Skills (23 Total, Auto-Registered)

**register_builtin_skills(registry)** registers:

### File I/O & Search (Read-Only)

*All inherit `FileSkill` (sandbox-validated)*

| Skill | Parameters | Description |
|-------|------------|-------------|
| `read_file` | `path` (req), `offset=1`?, `limit`? | Read UTF-8 text with optional line range; sandbox |
| `tail` | `path` (req), `lines=10`? | Read last N lines of a file; sandbox |
| `file_info` | `path` (req) | Get file/dir metadata: size, mtime, permissions, type |
| `list_directory` | `path=?`, `all` (hidden)?, `long` (ls -l)? | List dir; `drwx size date name`; sandbox |
| `glob` | `pattern` (req), `path=?`, `max_results=100`, `exclude`? | `**/*.py`; supports exclusion patterns; sandbox |
| `grep` | `pattern` (req), `path` (req), `recursive=true`, `ignore_case=false`, `max_matches=100`, `include`?, `context=0`? | Regex; file filter; context lines; skips binary; sandbox |

### File I/O (Destructive)

*All inherit `FileSkill` (sandbox-validated)*

| Skill | Parameters | Description |
|-------|------------|-------------|
| `write_file` | `path` (req), `content` (req) | Write UTF-8; `mkdir -p`; sandbox. **Read file first before overwriting.** |
| `edit_file` | `path` (req), **String:** `old_string`, `new_string`, `replace_all=false`<br>**Line:** `start_line`, `end_line=?`, `new_content` | Unique check; sandbox. **Read file first to verify match.** |
| `append_file` | `path` (req), `content` (req), `newline=true`? | Append content with smart newline handling; sandbox. **Read file first.** |
| `regex_replace` | `path` (req), `pattern` (req), `replacement` (req), `count=0`?, `ignore_case`?, `multiline`?, `dotall`? | Pattern-based find/replace; backrefs (\1); max 10000 matches; 5s timeout; sandbox. **Read file first.** |
| `copy_file` | `source` (req), `destination` (req), `overwrite=false`? | Copy file preserving metadata; creates parent dirs; sandbox |
| `mkdir` | `path` (req) | Create directory and parents (`mkdir -p`); sandbox |
| `rename` | `source` (req), `destination` (req), `overwrite=false`? | Rename/move file or directory; creates parent dirs; sandbox |

### Git Operations (Permission-Filtered)

*Inherits `FilteredCommandSkill` (permission-level filtering)*

| Skill | Parameters | Description |
|-------|------------|-------------|
| `git` | `command` (req), `cwd=.`? | Git commands filtered by permission level; 30s timeout; JSON output |

**Permission levels:**
- SANDBOXED: Read-only commands (status, diff, log, show, branch, etc.)
- TRUSTED: Read + write commands (add, commit, push, pull, etc.); blocks dangerous ops
- YOLO: All commands including dangerous (reset --hard, push --force, clean -fd)

### Execution (High-Risk: Disabled in Sandboxed)

*Inherit `ExecutionSkill` (timeout-enforced, output-formatted)*

| Skill | Parameters | Description |
|-------|------------|-------------|
| `bash` | `command` (req), `timeout=30` (1-300s), `cwd`? | Shell; stdout/stderr/exit; timeout; perms only |
| `run_python` | `code` (req), `timeout=30` (1-300s), `cwd`? | `python -c code`; stdout/stderr/exit; perms only |

### Nexus Agent Control

*Inherit `NexusSkill` (localhost-only, auto API key, client management)*

| Skill | Parameters | Description |
|-------|------------|-------------|
| `nexus_create` | `agent_id` (req), `preset`?, `cwd`?, `allowed_write_paths`?, `disable_tools`?, `model`?, `initial_message`?, `port`? | Create agent; if `initial_message` provided, sends it and includes response |
| `nexus_destroy` | `agent_id` (req), `port`? | Remove agent (server continues) |
| `nexus_send` | `agent_id` (req), `content` (req), `port`? | Send msg → full JSON response |
| `nexus_status` | `agent_id` (req), `port`? | `{"tokens":..., "context":...}` |
| `nexus_cancel` | `agent_id` (req), `request_id` (req, int), `port`? | Cancel in-progress req |
| `nexus_shutdown` | `port`? | Graceful server stop |

### Utility

| Skill | Parameters | Description |
|-------|------------|-------------|
| `sleep` | `seconds` (req, 0-3600), `label`? | `asyncio.sleep`; parallel/timeout testing |

**Echo (Testing, Not Auto-Registered):**
`from nexus3.skill.builtin.echo import echo_skill_factory; registry.register("echo", echo_skill_factory)`

## Security & Features

- **Sandbox**: `allowed_paths=None` (unrestricted), `[]` (deny), `[dirs]`
- **Paths**: `normalize_path`: `~`→home, `\`→`/`, rel→abs
- **Async**: `asyncio.to_thread` (I/O, glob, etc.)
- **Errors**: `ToolResult(error=...)`; no exceptions bubble
- **Permissions**: Tool filtering; destructive confirm (TRUSTED); preset ceiling
- **Nexus**: `validate_url(localhost)`, `discover_api_key`, `validate_agent_id`

## Multi-Agent (`AgentPool`)

Per-agent isolation:

```python
services = ServiceContainer(per-agent)
services.register("allowed_paths", [Path.cwd()])  # Sandbox
services.register("api_key", "...", "port", "agent_id", "permissions")
registry = SkillRegistry(services)
register_builtin_skills(registry)
```

## Creating New Skills

1. **Choose base class:**
   - `FileSkill` - file I/O with sandbox validation
   - `NexusSkill` - agent control with server communication
   - `ExecutionSkill` - subprocess execution with timeout
   - `FilteredCommandSkill` - permission-filtered CLI tools
   - `BaseSkill` - generic skills without shared infrastructure
2. Apply factory decorator (`@file_skill_factory`, `@nexus_skill_factory`, etc.)
3. `registry.register("my_skill", my_skill_factory)`
4. Add to `builtin/registration.py` → auto-reg
5. `config.schema.py`: Add to `destructive_tools` if destructive
6. Tests: `tests/unit/test_my_skill.py`

**Practices:**
- Always `return ToolResult(output|error=...)`
- `async def execute(self, **kwargs: Any)`
- Blocking → `asyncio.to_thread`
- Validate params early, descriptive errors
- Single purpose per skill
- Use specialized bases for DI (`allowed_paths`, `permissions`, etc.)

## Error Types

| Error | Description |
|-------|-------------|
| `SkillError` | Base (`NexusError` subclass) |
| `SkillNotFoundError` | `skill_name` attr |
| `SkillExecutionError` | `skill_name`, `reason` attrs |

## Dependencies

- `nexus3.core.*`: `ToolResult`, paths, errors, validation, `AgentPermissions`
- `nexus3.client`: `NexusClient`
- `nexus3.rpc.auth`: `discover_api_key`

## Exports

**`nexus3.skill`:**
- `Skill`, `BaseSkill`, `SkillRegistry`, `SkillFactory`, `ServiceContainer`
- `FileSkill`, `NexusSkill`, `ExecutionSkill`, `FilteredCommandSkill`
- `file_skill_factory`, `nexus_skill_factory`, `execution_skill_factory`, `filtered_command_skill_factory`
- `SkillError`, `SkillNotFoundError`, `SkillExecutionError`

**`nexus3.skill.builtin`:**
- `register_builtin_skills`
- Nexus factories (`nexus_send_factory`, etc.)
