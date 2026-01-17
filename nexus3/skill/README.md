# nexus3.skill - NEXUS3 Skill (Tool) System

Updated: 2026-01-17

Tool (skill) system for NEXUS3. Provides infrastructure for defining, registering, and executing skills that extend agent capabilities (file I/O, shell, git, Nexus control, etc.).

Skills are single-purpose `async execute(**kwargs) -> ToolResult(output|error)`.

## Key Components

| Component | Description |
|-----------|-------------|
| **`Skill`** | `@runtime_checkable Protocol`: `name`, `description`, `parameters` (JSON Schema), `async execute` |
| **`BaseSkill`** | `ABC`: Set metadata in `__init__`, implement `execute` |
| **`FileSkill`** | Path validation (`PathResolver`), `@handle_file_errors` |
| **`NexusSkill`** | In-process API or HTTP to Nexus server |
| **`ExecutionSkill`** | Subprocess (1-300s timeout, sandbox cwd) |
| **`FilteredCommandSkill`** | Permission-filtered CLI (YOLO/TRUSTED/SANDBOXED) |
| **`SkillRegistry`** | `register(name, factory)`, `get(name)`, `get_definitions()`, permission filtering |
| **`SkillFactory`** | `Callable[[ServiceContainer], Skill]` |
| **`ServiceContainer`** | DI: permissions, cwd, `allowed_paths`, `agent_api` |
| **`ToolResult`** | `output=str|None, error=str|None` |

**Decorators** (auto-applied): `@validate_skill_parameters()` (JSON Schema).

## Files

**Root**:
| File | Description |
|------|-------------|
| `__init__.py` | Exports public API |
| `base.py` | Protocols, bases, factories, decorators |
| `errors.py` | `SkillError`, `SkillNotFoundError`, `SkillExecutionError` |
| `registry.py` | `SkillRegistry`, `SkillSpec` |
| `services.py` | `ServiceContainer` |

**builtin/** (~25 skills + utils):
- `registration.py`: `register_builtin_skills(registry)`
- Skills: `append_file`, `bash`, `copy_file`, `edit_file`, `env`, `file_info`, `git`, `glob_search` (`glob`), `grep`, `list_directory`, `mkdir`, `nexus_*` (6), `read_file`, `regex_replace`, `rename`, `run_python`, `sleep`, `tail`, `write_file`
- Manual: `echo.py`

## Usage

1. **Setup**:
   ```python
   from nexus3.skill import SkillRegistry, ServiceContainer
   from nexus3.skill.builtin.registration import register_builtin_skills  # or .builtin import *

   services = ServiceContainer()
   services.register(&quot;permissions&quot;, agent_permissions)
   services.register(&quot;cwd&quot;, Path(&quot;/sandbox&quot;))
   registry = SkillRegistry(services)
   register_builtin_skills(registry)
   ```

2. **Tools for LLM**:
   ```python
   tools = registry.get_definitions()  # OpenAI format
   # Or filtered: registry.get_definitions_for_permissions(permissions)
   ```

3. **Execute**:
   ```python
   skill = registry.get(&quot;read_file&quot;)
   result = await skill.execute(path=&quot;foo.txt&quot;)
   ```

## Security Features

- **Sandbox**: Per-tool `allowed_paths` (None=unrestricted, []=deny)
- **Permissions**: Tool disablement, command filters (SANDBOXED=read-only whitelist)
- **Validation**: JSON Schema, path normalize/resolve symlinks, localhost URLs, timeouts
- **Isolation**: Per-agent `ServiceContainer`

## Extending

1. Subclass base (e.g., `FileSkill`).
2. Define `@property name/description/parameters`.
3. Implement `async execute`.
4. `@file_skill_factory` (etc.) → `registry.register(&quot;my_skill&quot;, MySkill.factory)`

**Best Practices**:
- Always return `ToolResult`.
- Validate early, use decorators.
- `asyncio.to_thread` for blocking I/O.
- Single responsibility.

## Dependencies

- `nexus3.core`: `ToolResult`, `PathResolver`, permissions, validation
- `nexus3.client`: `NexusClient`
- `nexus3.rpc`: `DirectAgentAPI`
- `jsonschema`
- Stdlib: `asyncio`, `pathlib`, `subprocess`, etc.
