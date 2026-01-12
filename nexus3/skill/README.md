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

# Get tool definitions filtered by agent permissions
tools = registry.get_definitions_for_permissions(agent_permissions)

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

### Permission-Filtered Definitions

`get_definitions_for_permissions(permissions)` filters out disabled tools so they are not exposed to the LLM. Sandboxed agents will not see tools like `nexus_create` that they cannot use:

```python
from nexus3.core.permissions import AgentPermissions

# Get tool definitions for agent's permission level
tools = registry.get_definitions_for_permissions(agent.permissions)
# Disabled tools are omitted from the list
```

## ServiceContainer

Simple dependency injection for skills. Skills can access shared services without tight coupling.

```python
from nexus3.skill import ServiceContainer

# Register services at application startup
services = ServiceContainer()
services.register("agent_pool", my_agent_pool)
services.register("allowed_paths", [Path.cwd()])  # For sandbox validation
services.register("api_key", "secret-key")  # For nexus skills

# In skill factory or initialization
pool = services.get("agent_pool")  # Returns None if not registered
paths = services.require("allowed_paths")  # Raises KeyError if not registered

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

### Common Service Names

| Service Name | Type | Used By |
|--------------|------|---------|
| `allowed_paths` | `list[Path] \| None` | `read_file`, `write_file` - sandbox validation |
| `api_key` | `str \| None` | All nexus skills - server authentication |
| `port` | `int \| None` | All nexus skills - server port (default: 8765) |
| `agent_id` | `str \| None` | `nexus_create` - parent agent ID for ceiling enforcement |
| `permissions` | `AgentPermissions \| None` | `nexus_create` - parent permissions for ceiling validation |

## Built-in Skills

Located in `nexus3/skill/builtin/`. Register with `register_builtin_skills()`:

### File Skills

| Skill | Parameters | Description |
|-------|------------|-------------|
| `read_file` | `path` (required) | Read file contents as UTF-8 text |
| `write_file` | `path`, `content` (required) | Write content to file (creates directories) |

**Security Features:**
- **Path sandbox validation**: When `allowed_paths` is registered in ServiceContainer, paths are validated to ensure they are within allowed directories. Raises `PathSecurityError` for violations.
- **Async I/O**: File operations use `asyncio.to_thread()` to avoid blocking the event loop.
- **UTF-8 encoding**: All file operations use explicit `encoding='utf-8'`.

```python
# With sandbox enabled (allowed_paths registered):
# Only paths under allowed directories are permitted
await read_skill.execute(path="/home/user/project/file.txt")  # OK if in allowed_paths
await read_skill.execute(path="/etc/passwd")  # PathSecurityError

# Without sandbox (allowed_paths not registered):
# Any path is allowed (backwards compatible)
await read_skill.execute(path="/etc/passwd")  # OK
```

### Testing Skill

| Skill | Parameters | Description |
|-------|------------|-------------|
| `sleep` | `seconds` (required), `label` (optional) | Sleep for specified duration (max 3600s) |

The `sleep` skill is useful for testing parallel execution and timeout behavior. The optional `label` parameter helps identify which sleep completed in test output.

```python
await sleep_skill.execute(seconds=1.5, label="test-sleep")
# Returns: ToolResult(output="Slept 1.5s (test-sleep)")
```

### Echo Skill (Not Registered by Default)

An `echo` skill class exists in `builtin/echo.py` but is not registered by `register_builtin_skills()`. Use `echo_skill_factory` to register it manually if needed for testing:

```python
from nexus3.skill.builtin.echo import echo_skill_factory
registry.register("echo", echo_skill_factory)
```

### Agent Control Skills (Nexus Skills)

Skills for communicating with Nexus agents running in server mode (`--serve`). These skills use `NexusClient` from `nexus3.client` for HTTP JSON-RPC communication.

| Skill | Parameters | Description |
|-------|------------|-------------|
| `nexus_create` | `agent_id` (required), `preset`?, `disable_tools`?, `port`? | Create a new agent with permissions |
| `nexus_destroy` | `agent_id` (required), `port`? | Destroy an agent (server keeps running) |
| `nexus_send` | `agent_id`, `content` (required), `port`? | Send a message to an agent |
| `nexus_status` | `agent_id` (required), `port`? | Get token usage and context info |
| `nexus_cancel` | `agent_id`, `request_id` (required), `port`? | Cancel an in-progress request |
| `nexus_shutdown` | `port`? | Request graceful shutdown of server |

**Common Parameters:**
- `agent_id`: ID of the target agent (e.g., "worker-1"). Validated for safety.
- `port`: Server port. Defaults to 8765 if not specified. Can also be set via ServiceContainer.
- `preset`: Permission preset for new agents (yolo/trusted/sandboxed/worker).
- `disable_tools`: List of tool names to disable for new agents.

**Security Features:**
- **URL validation**: All nexus skills use `validate_url()` with `allow_localhost=True` to prevent SSRF attacks.
- **API key discovery**: Skills auto-discover API keys from `~/.nexus3/apikeys/{port}.key` or ServiceContainer.
- **Agent ID validation**: Agent IDs are validated to prevent injection attacks.
- **Ceiling inheritance**: `nexus_create` validates that the requested preset does not exceed parent agent's permissions.

**Example usage:**

```python
# Create a new sandboxed worker agent
await nexus_create.execute(
    agent_id="worker-1",
    preset="sandboxed",
    disable_tools=["nexus_shutdown"]
)

# Send message to agent
await nexus_send.execute(agent_id="worker-1", content="Hello, agent!")

# Get token/context status
await nexus_status.execute(agent_id="worker-1")
# Returns: {"tokens": {...}, "context": {...}}

# Cancel a request (requires request_id)
await nexus_cancel.execute(agent_id="worker-1", request_id="123")

# Destroy the agent (server keeps running)
await nexus_destroy.execute(agent_id="worker-1")

# Gracefully shutdown the server (stops all agents)
await nexus_shutdown.execute()
```

### NexusClient

The agent control skills use `NexusClient` (`nexus3/client.py`) internally:

```python
from nexus3.client import NexusClient, ClientError

async with NexusClient("http://localhost:8765", api_key="secret") as client:
    # Create agent
    result = await client.create_agent("worker-1", preset="sandboxed")

    # Send message
    result = await client.send("Hello!")  # {"content": "...", ...}

    # Get token usage
    tokens = await client.get_tokens()

    # Get context info
    context = await client.get_context()

    # Cancel in-progress request
    await client.cancel(request_id=123)

    # Destroy agent
    await client.destroy_agent("worker-1")

    # Request shutdown
    await client.shutdown_server()
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

# Now registry has:
# - read_file, write_file
# - sleep
# - nexus_create, nexus_destroy, nexus_send, nexus_cancel, nexus_status, nexus_shutdown
```

## Multi-Agent Integration

In the multi-agent architecture (`nexus3/rpc/pool.py`), each agent in an `AgentPool` gets its own:

- **ServiceContainer** - For agent-specific service injection
- **SkillRegistry** - With its own skill instance cache

This isolation ensures agents don't share mutable state while still sharing expensive resources (like the LLM provider).

```python
# From AgentPool.create():
services = ServiceContainer()
services.register("allowed_paths", [Path.cwd()])  # Sandbox to CWD
services.register("api_key", api_key)  # For nexus skills
services.register("port", port)
services.register("agent_id", agent_id)  # For ceiling enforcement
services.register("permissions", permissions)  # For nexus_create ceiling checks

registry = SkillRegistry(services)
register_builtin_skills(registry)

# Each Agent dataclass contains:
agent = Agent(
    agent_id="worker-1",
    services=services,      # Per-agent ServiceContainer
    registry=registry,      # Per-agent SkillRegistry
    permissions=permissions,  # Per-agent AgentPermissions
    # ... other components
)
```

This design allows:
- **Service isolation**: Each agent can have different services registered
- **Permission enforcement**: Different agents have different skill sets based on permission level
- **State isolation**: Skill instances are cached per-agent, not globally

## Permission Integration

The skill system integrates with the permission system (Phase 8):

### Tool Filtering

`get_definitions_for_permissions()` filters tools based on `AgentPermissions`:

```python
# Sandboxed agent won't see nexus_create, nexus_shutdown, etc.
tools = registry.get_definitions_for_permissions(agent.permissions)
```

### Ceiling Enforcement

`nexus_create` skill validates that the requested preset doesn't exceed parent permissions:

```python
# Parent is "trusted", cannot create "yolo" child
await nexus_create.execute(agent_id="worker", preset="yolo")
# Returns: ToolResult(error="Cannot create agent with 'yolo' preset: exceeds permission ceiling")
```

### Per-Tool Configuration

The permission system supports per-tool settings like:
- `enabled`: Whether tool is available
- `allowed_paths`: Tool-specific sandbox paths
- `timeout`: Tool-specific execution timeout

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
    api_key = services.get("api_key")
    allowed_paths = services.get("allowed_paths")
    return MySkill(api_key=api_key, allowed_paths=allowed_paths)
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
7. **Use Async I/O**: For blocking operations, use `asyncio.to_thread()` to avoid blocking the event loop
8. **Validate Input**: Check for empty/invalid parameters and return clear error messages

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
+---------------+   +--------+--------+   +------------------------+
| Skill Factory |-->| SkillRegistry   |-->| get_definitions()      |
| (callable)    |   | - _factories{}  |   | get_definitions_for_   |
+---------------+   | - _instances{}  |   |   permissions()        |
                    +--------+--------+   +------------------------+
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
- `normalize_path`, `validate_sandbox` - Path handling and security (used by file skills)
- `validate_url`, `UrlSecurityError` - URL validation (used by nexus skills)
- `validate_agent_id`, `ValidationError` - Input validation (used by nexus skills)
- `PathSecurityError` - Sandbox violation error

**From `nexus3.client`:**
- `NexusClient` - HTTP client for agent control skills
- `ClientError` - Exception for client-side errors

**From `nexus3.core.permissions`:**
- `AgentPermissions` - Permission state for tool filtering
- `get_builtin_presets`, `resolve_preset` - For ceiling validation in nexus_create

**From `nexus3.rpc.auth`:**
- `discover_api_key` - Auto-discover API keys for server authentication

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

**Note:** `nexus_create_factory`, `nexus_destroy_factory`, `read_file_factory`, `write_file_factory`, and `sleep_skill_factory` are used by `register_builtin_skills()` but not exported from the `builtin` module's `__all__`. Import them directly if needed:

```python
from nexus3.skill.builtin.nexus_create import nexus_create_factory
from nexus3.skill.builtin.read_file import read_file_factory
```
