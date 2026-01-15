# nexus3.skill - NEXUS3 Skill (Tool) System

Updated: 2026-01-15

Tool (skill) system for NEXUS3. Provides infrastructure for defining, registering, executing skills that extend agent capabilities (file I/O, commands, git, multi-agent, etc.).

## Purpose

Core skill infrastructure:
- **Skill protocol** (`Skill`) & **BaseSkill** (ABC)
- **Specialized bases**: `FileSkill` (sandbox paths), `NexusSkill` (agent control), `ExecutionSkill` (subprocess/timeout), `FilteredCommandSkill` (permission-filtered CLI)
- **SkillRegistry**: Lazy factories, OpenAI tool defs, permission filtering
- **ServiceContainer**: Dependency injection (permissions, cwd, allowed_paths, agent_api)
- **23 built-in skills** (+ manual `echo`) in `builtin/`

Skills: Single-purpose, async `execute(**kwargs) -> ToolResult(output|error)`.

## Key Components

| Component | Description |
|-----------|-------------|
| `Skill` | `@runtime_checkable Protocol`: `name`, `description`, `parameters` (JSON Schema), `async execute` |
| `BaseSkill` | `ABC`: Set metadata in `__init__`, implement `execute` |
| `FileSkill` | Path validation (`PathResolver`, symlinks resolved, per-tool `allowed_paths`) + `@handle_file_errors` |
| `NexusSkill` | Port/API/client mgmt, direct in-process API or HTTP fallback |
| `ExecutionSkill` | Subprocess (1-300s timeout, cwd sandbox, formatted stdout/stderr/exit) |
| `FilteredCommandSkill` | Permission levels: YOLO/TRUSTED/SANDBOXED; read-only whitelist + blocked patterns |
| `SkillRegistry` | `register(name, factory)`, `get(name)` (lazy/cache), `get_definitions()`, `get_definitions_for_permissions()` |
| `SkillFactory` | `Callable[[ServiceContainer], Skill]` |
| `ServiceContainer` | DI: `register/get/require/has`; typed: `get_permissions()`, `get_tool_allowed_paths(tool_name)`, `get_permission_level()` |
| `ToolResult` | `output=str\|None, error=str\|None` |

**Decorators** (auto-applied by factories): `@validate_skill_parameters()` (JSON Schema + filter extras)

## Files

**Root (`nexus3.skill/`)**:
| File | Size | Date | Description |
|------|------|------|-------------|
| `__init__.py` | 1.5K | 2026-01-14 | Exports all public API |
| `base.py` | 40.7K | 2026-01-15 | Protocols, bases, factories, decorators (`handle_file_errors`, `validate_skill_parameters`) |
| `errors.py` | 710B | 2026-01-08 | `SkillError`, `SkillNotFoundError`, `SkillExecutionError` |
| `registry.py` | 7.3K | 2026-01-15 | `SkillRegistry` |
| `services.py` | 6.9K | 2026-01-15 | `ServiceContainer` |
| `README.md` | 14.6K | 2026-01-15 | This file |

**builtin/** (23 skills + utils):
- `registration.py`: `register_builtin_skills(registry)`
- Skills: `append_file.py`, `bash.py`, `copy_file.py`, `edit_file.py`, `file_info.py`, `git.py`, `glob_search.py` (`glob`), `grep.py`, `list_directory.py`, `mkdir.py`, `nexus_*` (6), `read_file.py`, `regex_replace.py`, `rename.py`, `run_python.py`, `sleep.py`, `tail.py`, `write_file.py`
- Manual: `echo.py`

## Architecture Summary

1. **Setup**:
   ```python
   from nexus3.skill import SkillRegistry, ServiceContainer
   from nexus3.skill.builtin import register_builtin_skills
   
   services = ServiceContainer()
   services.register("allowed_paths", [Path.cwd()])  # Sandbox
   services.register("permissions", agent_permissions)
   registry = SkillRegistry(services)
   register_builtin_skills(registry)
   ```

2. **Usage**:
   ```python
   tools = registry.get_definitions()  # -> OpenAI [{"type": "function", "function": {...}}]
   skill = registry.get("read_file")
   result = await skill.execute(path="foo.txt")
   ```

3. **Security**:
   - **Sandbox**: Per-tool `allowed_paths` (None=unrestricted, []=deny)
   - **Permissions**: Tool disable, command filter (SANDBOXED=read-only, TRUSTED=block dangerous, YOLO=all)
   - **Validation**: JSON Schema, path normalize/resolve, URL localhost-only, timeouts
   - **DI Isolation**: Per-agent `ServiceContainer`

4. **Factories**: `@file_skill_factory(cls)` auto-injects `services`, wraps validation

## Dependencies

- `nexus3.core.*`: `ToolResult`, `PathResolver`, `AgentPermissions`, `PermissionLevel`, errors, validation
- `nexus3.client`: `NexusClient`
- `nexus3.rpc.*`: `DirectAgentAPI`, auth
- `jsonschema`: Param validation
- Stdlib: `asyncio`, `pathlib`, `subprocess`, `json`, `re`

## Built-in Skills Overview

**File I/O & Search** (`FileSkill`):
| Skill | Key Params |
|-------|------------|
| `read_file` | `path`, `offset=1`, `limit` |
| `tail` | `path`, `lines=10` |
| `file_info` | `path` |
| `list_directory` | `path=.`, `all`, `long` |
| `glob` (`glob_search`) | `pattern`, `path=.`, `max_results=100`, `exclude` |
| `grep` | `pattern`, `path`, `recursive=true`, `context=0` |

**Destructive File** (`FileSkill`, read first!):
| Skill | Key Params |
|-------|------------|
| `write_file` | `path`, `content` |
| `edit_file` | `path`; string: `old_string`/`new_string`/`replace_all`; line: `start_line`/`end_line`/`new_content` |
| `append_file` | `path`, `content` |
| `regex_replace` | `path`, `pattern`, `replacement` |
| `copy_file`/`rename`/`mkdir` | `source`/`dest`/`path`, `overwrite=false` |

**Execution** (`ExecutionSkill`, TRUSTED+):
| Skill | Key Params |
|-------|------------|
| `bash` | `command`, `timeout=30`, `cwd` |
| `run_python` | `code`, `timeout=30`, `cwd` |

**Git** (`FilteredCommandSkill`):
| Skill | Key Params |
|-------|------------|
| `git` | `command`, `cwd` (filtered: SANDBOXED=read-only, TRUSTED=no force/reset, YOLO=all) |

**Nexus Agent Control** (`NexusSkill`):
| Skill | Key Params |
|-------|------------|
| `nexus_create` | `agent_id`, `port=?`, `preset`/etc. |
| `nexus_send` | `agent_id`, `content`, `port` |
| `nexus_status`/`nexus_cancel`/`nexus_destroy` | `agent_id`, `request_id`/etc. |
| `nexus_shutdown` | `port` |

**Utility**:
| Skill | Key Params |
|-------|------------|
| `sleep` | `seconds` (0-3600) |

## Extending

1. Subclass base (e.g. `FileSkill`)
2. `@file_skill_factory` etc.
3. `registry.register("my_skill", MySkill.factory)`
4. Add to `builtin/registration.py` for auto-reg

**Best Practices**:
- `ToolResult(output|error=...)` always
- Validate early, descriptive errors
- Blocking I/O → `asyncio.to_thread`
- Single responsibility

