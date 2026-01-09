# Skill Module

Tool (skill) system for NEXUS3. Provides the infrastructure for defining, registering, and executing skills that extend the agent's capabilities.

## Purpose

This module provides the skill/tool infrastructure for NEXUS3:

- **Skill protocol** for implementing custom tools
- **SkillRegistry** for managing available skills with lazy instantiation
- **ServiceContainer** for dependency injection
- **Built-in skills** for common operations (file I/O, testing, agent control)

Skills are the fundamental unit of capability in NEXUS3. Each skill provides a single, well-defined action that the LLM can invoke via function calling.

## Key Types

| Type | Description |
|------|-------------|
| `Skill` | Protocol defining the skill interface (name, description, parameters, execute) |
| `BaseSkill` | Abstract base class with common implementation patterns |
| `SkillRegistry` | Registry for skill factories with lazy instantiation and caching |
| `SkillFactory` | Callable type: `(ServiceContainer) -> Skill` |
| `ServiceContainer` | Simple dependency injection container |

## Files

| File | Description |
|------|-------------|
| `base.py` | `Skill` protocol and `BaseSkill` abstract class |
| `registry.py` | `SkillRegistry` with factory-based instantiation |
| `services.py` | `ServiceContainer` for dependency injection |
| `errors.py` | Skill-specific error classes |
| `builtin/` | Built-in skill implementations |

## Skill Protocol

All skills must implement the `Skill` protocol (runtime checkable):

```python
@runtime_checkable
class Skill(Protocol):
    @property
    def name(self) -> str:
        """Unique skill name (snake_case, used in tool calls)."""
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

## BaseSkill

Optional convenience base class that stores metadata as instance attributes. Subclasses only need to implement `execute()`:

```python
class MySkill(BaseSkill):
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

## SkillRegistry

Manages skill factories with lazy instantiation and caching. Skills are only created when first requested via `get()`.

```python
from nexus3.skill import SkillRegistry, ServiceContainer

# Create registry with optional service container
services = ServiceContainer()
registry = SkillRegistry(services)

# Register skill factory
registry.register("my_skill", my_skill_factory)

# Get skill instance (created on first access, cached thereafter)
skill = registry.get("my_skill")
if skill:
    result = await skill.execute(input="hello")

# Get OpenAI-format tool definitions for LLM
tools = registry.get_definitions()

# List registered skill names
names = registry.names  # ["my_skill", ...]

# Access the service container
container = registry.services
```

### Tool Definitions

`get_definitions()` returns OpenAI function calling format:

```python
[
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "The path to the file to read"}
                },
                "required": ["path"]
            }
        }
    },
    # ... more skills
]
```

## ServiceContainer

Simple dependency injection for skills. Skills can access shared services without tight coupling.

```python
from nexus3.skill import ServiceContainer

# Register services at application startup
services = ServiceContainer()
services.register("agent_pool", my_agent_pool)
services.register("sandbox", my_sandbox)

# In skill factory or initialization
pool = services.get("agent_pool")  # Returns None if not registered
sandbox = services.require("sandbox")  # Raises KeyError if not registered

# Check if service exists
if services.has("agent_pool"):
    ...

# List all registered services
service_names = services.names()

# Unregister a service
old_service = services.unregister("agent_pool")

# Clear all services
services.clear()
```

## Built-in Skills

Located in `nexus3/skill/builtin/`. Register with `register_builtin_skills()`:

### Core Skills

| Skill | Description | Parameters |
|-------|-------------|------------|
| `read_file` | Reads file contents as UTF-8 text | `path` (required) |
| `write_file` | Writes content to file (creates directories) | `path`, `content` (required) |
| `sleep` | Sleeps for specified duration (testing) | `seconds` (required), `label` (optional) |

**Note**: An `echo` skill class exists in `builtin/echo.py` but is not registered by default. Use `echo_skill_factory` to register it manually if needed.

### Agent Control Skills

Skills for communicating with Nexus agents running in server mode (`--serve`). These skills use `NexusClient` from `nexus3.client` for HTTP JSON-RPC communication.

| Skill | Description | Parameters |
|-------|-------------|------------|
| `nexus_send` | Send a message to a Nexus agent and receive response | `url` (required), `content` (required), `request_id` (optional) |
| `nexus_cancel` | Cancel an in-progress request on a Nexus agent | `url` (required), `request_id` (required) |
| `nexus_status` | Get token usage and context info from an agent | `url` (required) |
| `nexus_shutdown` | Request graceful shutdown of a Nexus agent | `url` (required) |

**Example usage:**

```python
# Send message to agent at localhost:8765
await nexus_send.execute(url="http://localhost:8765", content="Hello, agent!")

# Get token/context status
await nexus_status.execute(url="http://localhost:8765")

# Cancel a request (requires request_id from nexus_send)
await nexus_cancel.execute(url="http://localhost:8765", request_id="123")

# Gracefully shutdown the agent
await nexus_shutdown.execute(url="http://localhost:8765")
```

### NexusClient

The agent control skills use `NexusClient` (`nexus3/client.py`) internally:

```python
from nexus3.client import NexusClient, ClientError

async with NexusClient("http://localhost:8765") as client:
    # Send message
    result = await client.send("Hello!")  # {"content": "...", ...}

    # Get token usage
    tokens = await client.get_tokens()

    # Get context info
    context = await client.get_context()

    # Cancel in-progress request
    await client.cancel(request_id=123)

    # Request shutdown
    await client.shutdown()
```

The client uses `httpx` for HTTP communication and raises `ClientError` on connection failures, timeouts, or RPC errors.

### Cross-Platform Path Handling

The `read_file` and `write_file` skills use `normalize_path()` from `nexus3.core.paths` for cross-platform compatibility:

- **Backslash normalization**: Windows-style paths (`C:\Users\foo`) converted to forward slashes
- **Home directory expansion**: Paths starting with `~` expanded via `Path.expanduser()`
- **Absolute resolution**: Relative paths resolved to absolute

```python
# All of these work on any platform:
await read_skill.execute(path="~/config.json")
await read_skill.execute(path="C:\\Users\\alice\\file.txt")  # Windows backslashes
await read_skill.execute(path="./relative/path.txt")
```

### Registering Built-in Skills

```python
from nexus3.skill import SkillRegistry, ServiceContainer
from nexus3.skill.builtin import register_builtin_skills

services = ServiceContainer()
registry = SkillRegistry(services)
register_builtin_skills(registry)

# Now registry has: read_file, write_file, sleep, nexus_send, nexus_cancel, nexus_status, nexus_shutdown
```

## Multi-Agent Integration

In the multi-agent architecture (`nexus3/rpc/pool.py`), each agent in an `AgentPool` gets its own:

- **ServiceContainer** - For agent-specific service injection
- **SkillRegistry** - With its own skill instance cache

This isolation ensures agents don't share mutable state while still sharing expensive resources (like the LLM provider).

```python
# From AgentPool.create():
services = ServiceContainer()
registry = SkillRegistry(services)
register_builtin_skills(registry)

# Each Agent dataclass contains:
agent = Agent(
    agent_id="worker-1",
    services=services,      # Per-agent ServiceContainer
    registry=registry,      # Per-agent SkillRegistry
    # ... other components
)
```

This design allows:
- **Service isolation**: Each agent can have different services registered
- **Future permissions**: Different agents could have different skill sets based on permission level
- **State isolation**: Skill instances are cached per-agent, not globally

## Execution Modes

Skills support two execution modes when multiple tool calls are made in a single LLM response:

### Sequential (Default)

Tools execute one at a time, in order. Use for dependent operations where one step needs the result of another.

```json
{"name": "read_file", "arguments": {"path": "config.json"}}
{"name": "write_file", "arguments": {"path": "output.txt", "content": "..."}}
```

### Parallel

Add `"_parallel": true` to any tool call's arguments to run all tools in the current batch concurrently.

```json
{"name": "read_file", "arguments": {"path": "file1.py", "_parallel": true}}
{"name": "read_file", "arguments": {"path": "file2.py", "_parallel": true}}
```

Use parallel mode for independent operations like reading multiple files simultaneously.

## Creating New Skills

### 1. Implement the Skill

Either implement `Skill` protocol directly or extend `BaseSkill`:

```python
# Option A: Direct protocol implementation (no inheritance needed)
class MySkill:
    @property
    def name(self) -> str:
        return "my_skill"

    @property
    def description(self) -> str:
        return "Does something useful"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "Input value"}
            },
            "required": ["input"]
        }

    async def execute(self, input: str = "", **kwargs: Any) -> ToolResult:
        return ToolResult(output=f"Result: {input}")

# Option B: Using BaseSkill (less boilerplate)
class MySkill(BaseSkill):
    def __init__(self):
        super().__init__(
            name="my_skill",
            description="Does something useful",
            parameters={...}
        )

    async def execute(self, input: str = "", **kwargs: Any) -> ToolResult:
        return ToolResult(output=f"Result: {input}")
```

### 2. Create a Factory Function

Factories receive `ServiceContainer` for dependency injection:

```python
def my_skill_factory(services: ServiceContainer) -> MySkill:
    # Access services if needed
    pool = services.get("agent_pool")
    return MySkill(pool)
```

### 3. Register with Registry

```python
registry.register("my_skill", my_skill_factory)
```

### Skill Best Practices

1. **Return ToolResult**: Always return `ToolResult(output=...)` on success or `ToolResult(error=...)` on failure
2. **Handle Errors Gracefully**: Catch exceptions and return error results rather than raising
3. **Document Parameters**: Include clear descriptions in the JSON Schema for LLM understanding
4. **Use snake_case Names**: Skill names should be lowercase with underscores
5. **Keep Skills Focused**: Each skill should do one thing well
6. **Accept `**kwargs`**: Always accept `**kwargs` in `execute()` for forward compatibility

## Error Types

| Error | Description |
|-------|-------------|
| `SkillError` | Base class for all skill-related errors |
| `SkillNotFoundError` | Raised when a skill is not in the registry (has `skill_name` attribute) |
| `SkillExecutionError` | Raised when skill execution fails (has `skill_name` and `reason` attributes) |

```python
from nexus3.skill import SkillNotFoundError, SkillExecutionError

try:
    skill = registry.get("unknown_skill")
    if skill is None:
        raise SkillNotFoundError("unknown_skill")
except SkillNotFoundError as e:
    print(f"Skill not found: {e.skill_name}")
```

## Data Flow

```
                    +------------------+
                    | ServiceContainer |
                    | (shared services)|
                    +--------+---------+
                             |
                             v
+---------------+   +--------+--------+   +------------------+
| Skill Factory |-->| SkillRegistry   |-->| get_definitions()|
| (callable)    |   | - _factories{}  |   | (OpenAI format)  |
+---------------+   | - _instances{}  |   +------------------+
                    +--------+--------+
                             |
                             v
                    +--------+--------+
                    | Skill.execute() |
                    | returns         |
                    | ToolResult      |
                    +-----------------+
```

## Dependencies

**From `nexus3.core`:**
- `ToolResult` - Return type for skill execution
- `NexusError` - Base exception class
- `normalize_path` - Cross-platform path handling (used by file skills)

**From `nexus3.client`:**
- `NexusClient` - HTTP client for agent control skills
- `ClientError` - Exception for client-side errors

## Module Exports

From `nexus3.skill`:

```python
# Protocol and base
Skill, BaseSkill

# Registry
SkillRegistry, SkillFactory

# Services
ServiceContainer

# Errors
SkillError, SkillNotFoundError, SkillExecutionError
```

From `nexus3.skill.builtin`:

```python
# Registration helper
register_builtin_skills

# Individual factories (for custom registration)
nexus_send_factory
nexus_cancel_factory
nexus_status_factory
nexus_shutdown_factory
```
