# nexus3.skill - NEXUS3 Skill (Tool) System

**Updated: 2026-01-17**

Core infrastructure for defining, registering, and executing skills (tools) that extend NEXUS3 agent capabilities.

Skills implement the `Skill` protocol: `name`, `description`, `parameters` (JSON Schema), `async execute(**kwargs) -> ToolResult`.

## Exports (`__all__`)

| Category | Exports |
|----------|---------|
| **Protocols/Bases** | `Skill`, `BaseSkill`, `FileSkill`, `NexusSkill`, `ExecutionSkill`, `FilteredCommandSkill` |
| **Factories** | `file_skill_factory`, `nexus_skill_factory`, `execution_skill_factory`, `filtered_command_skill_factory` |
| **Registry** | `SkillRegistry`, `SkillFactory`, `SkillSpec` |
| **Services** | `ServiceContainer` |
| **Errors** | `SkillError`, `SkillNotFoundError`, `SkillExecutionError` |

## Key Components

- **`SkillRegistry`**: Register factories, `get_definitions()` (OpenAI tools), lazy instantiation, permission filtering.
- **`ServiceContainer`**: DI for permissions, cwd, `allowed_paths`, `agent_api`.
- **Bases**: `FileSkill` (path validation), `NexusSkill` (API/HTTP), `ExecutionSkill` (subprocess, timeout), `FilteredCommandSkill` (permission filters).
- **Decorators**: `@validate_skill_parameters()`, `@handle_file_errors()` (auto-applied by factories).

Security: Per-tool `allowed_paths`, command whitelists/blocklists (YOLO/TRUSTED/SANDBOXED).

## Usage

```python
from nexus3.skill import SkillRegistry, ServiceContainer
from nexus3.skill.builtin.registration import register_builtin_skills  # Optional builtins

services = ServiceContainer()
# services.register("permissions", agent_permissions)
# services.register("cwd", Path("/sandbox"))
registry = SkillRegistry(services)
register_builtin_skills(registry)  # ~25 skills: read_file, bash, git, nexus_*, etc.

# LLM tools
tools = registry.get_definitions()  # List[dict] OpenAI format

# Execute
skill = registry.get("read_file")
result = await skill.execute(path="foo.txt")
print(result.output)
```

## Extending

```python
from nexus3.skill import BaseSkill, file_skill_factory
from nexus3.core.types import ToolResult

@file_skill_factory
class MySkill(BaseSkill):
    def __init__(self):
        super().__init__(
            name="my_skill",
            description="Does X",
            parameters={"type": "object", "properties": {...}, "required": [...]}
        )

    async def execute(self, **kwargs) -> ToolResult:
        # Use self._services for DI
        return ToolResult(output="result")

# Register
registry.register("my_skill", MySkill.factory)
```

**Best Practices**:
- Subclass appropriate base.
- Validate early (decorators).
- `ToolResult(output|error)`.
- Single responsibility.
- `asyncio.to_thread` for sync I/O.

**Deps**: `nexus3.core`, `jsonschema`, stdlib (`asyncio`, `pathlib`, etc.).
