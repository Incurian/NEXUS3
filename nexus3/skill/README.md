# Skill Module

Tool (skill) system for NEXUS3. Provides the infrastructure for defining, registering, and executing skills that extend the agent's capabilities.

## Purpose

This module provides the skill/tool infrastructure for NEXUS3:

- **Skill protocol** (`Skill`) for implementing custom tools
- **BaseSkill** abstract base class for convenience
- **SkillRegistry** for managing skill factories with lazy instantiation and caching
- **ServiceContainer** for dependency injection into skills
- **16 built-in skills** for file I/O, search, execution, agent control, and testing (+ `echo` manual)

Skills are the fundamental unit of capability in NEXUS3. Each skill provides a single, well-defined, async-executable action that the LLM invokes via function calling.

## Key Components

| Component | Description |
|-----------|-------------|
| `Skill` | Runtime-checkable protocol: `name`, `description`, `parameters`, `async execute(**kwargs) -> ToolResult` |
| `BaseSkill` | `ABC` subclass of `Skill`; set metadata in `__init__`, implement `execute` |
| `SkillRegistry` | Manages factories; lazy `get(name)`, `get_definitions()`, permission-filtered defs |
| `SkillFactory` | `Callable[[ServiceContainer], Skill]` |
| `ServiceContainer` | Dict-like DI: `register/get/require/has/unregister/clear/names` |
| `ToolResult` | Return type: `ToolResult(output=str \| None, error=str \| None)` |

## Files

| File | Description |
|------|-------------|
| `__init__.py` | Exports: `Skill`, `BaseSkill`, `SkillRegistry`, `ServiceContainer`, errors |
| `base.py` | `Skill` protocol, `BaseSkill(ABC)` |
| `registry.py` | `SkillRegistry`, `get_definitions_for_permissions(AgentPermissions)` |
| `services.py` | `ServiceContainer` |
| `errors.py` | `SkillError`, `SkillNotFoundError`, `SkillExecutionError` |
| `builtin/__init__.py` | Exports `register_builtin_skills`, nexus factories |
| `builtin/registration.py` | `register_builtin_skills(registry)` registers all 16 |
| `builtin/*.py` | Individual skills: bash.py, echo.py, edit_file.py, etc. |

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
| `allowed_paths` | `list[Path] \| None` | File/search skills (sandbox) |
| `api_key` | `str \| None` | Nexus skills (auth) |
| `port` | `int \| None` | Nexus skills (default 8765) |
| `agent_id` | `str \| None` | `nexus_create` (ceiling parent) |
| `permissions` | `AgentPermissions \| None` | `nexus_create` (ceiling check) |

## Built-in Skills (16 Total, Auto-Registered)

**register_builtin_skills(registry)** registers:

### File I/O & Search (Read-Only)

| Skill | Parameters | Description |
|-------|------------|-------------|
| `read_file` | `path` (req) | Read UTF-8 text; sandbox if `allowed_paths` |
| `list_directory` | `path=?`, `all` (hidden)?, `long` (ls -l)? | List dir; `drwx size date name`; sandbox |
| `glob` | `pattern` (req), `path=?`, `max_results=100` | `**/*.py`; relative paths; sandbox |
| `grep` | `pattern` (req), `path` (req), `recursive=true`, `ignore_case=false`, `max_matches=100` | Regex; `file:line: match`; skips binary; sandbox |

### File I/O (Destructive)

| Skill | Parameters | Description |
|-------|------------|-------------|
| `write_file` | `path` (req), `content` (req) | Write UTF-8; `mkdir -p`; sandbox |
| `edit_file` | `path` (req), **String:** `old_string`, `new_string`, `replace_all=false`<br>**Line:** `start_line`, `end_line=?`, `new_content` | Unique check; sandbox |

### Execution (High-Risk: Disabled in Sandboxed)

| Skill | Parameters | Description |
|-------|------------|-------------|
| `bash` | `command` (req), `timeout=30` (1-300s), `cwd`? | Shell; stdout/stderr/exit; timeout; perms only |
| `run_python` | `code` (req), `timeout=30` (1-300s), `cwd`? | `python -c code`; stdout/stderr/exit; perms only |

### Nexus Agent Control

Localhost-only; auto-discovers `api_key`; validates `agent_id`/URL.

| Skill | Parameters | Description |
|-------|------------|-------------|
| `nexus_create` | `agent_id` (req), `preset`? (trusted/sandboxed/worker), `cwd`?, `allowed_write_paths`?, `disable_tools`?, `model`?, `port`? | Ceiling check via parent `permissions` |
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

1. Class impl `Skill`/`BaseSkill`
2. `def factory(services) -> Skill: return Skill(services.get("foo"))`
3. `registry.register("my_skill", factory)`
4. Add to `builtin/registration.py` → auto-reg
5. `config.schema.py`: Add to `destructive_tools` if destructive
6. Tests: `tests/unit/test_my_skill.py`

**Practices:**
- Always `return ToolResult(output|error=...)`
- `async def execute(self, **kwargs: Any)`
- Blocking → `asyncio.to_thread`
- Validate params early, descriptive errors
- Single purpose per skill

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
- `SkillError`, `SkillNotFoundError`, `SkillExecutionError`

**`nexus3.skill.builtin`:**
- `register_builtin_skills`
- Nexus factories (`nexus_send_factory`, etc.)
