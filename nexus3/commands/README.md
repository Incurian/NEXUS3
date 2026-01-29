# nexus3.commands

Unified command infrastructure for NEXUS3 CLI and REPL.

This module provides a centralized, structured command system that works identically for both the `nexus3 rpc` CLI tool and `/slash` commands in the interactive REPL. Commands return structured `CommandOutput` objects, allowing callers to format output appropriately for their context (JSON for CLI, rich text for REPL).

---

## Overview

### Why This Module Exists

Before this module, command logic was duplicated between the CLI (`nexus3 rpc`) and REPL (`/commands`). This led to:
- Inconsistent behavior between interfaces
- Duplicated validation and error handling
- Maintenance burden when adding new commands

The unified command system solves this by:
1. **Single source of truth**: One implementation per command
2. **Structured output**: Commands return data, callers decide presentation
3. **Context-aware**: Commands adapt behavior based on CLI vs REPL context
4. **Type-safe**: Full typing with dataclasses and enums

---

## Architecture

```
nexus3/commands/
├── __init__.py     # Public API exports
├── protocol.py     # Core types (CommandResult, CommandOutput, CommandContext)
└── core.py         # Command implementations
```

### Data Flow

```
User Input (CLI or REPL)
         │
         ▼
┌─────────────────┐
│ CommandContext  │  ← pool, session_manager, current_agent_id, is_repl
└─────────────────┘
         │
         ▼
┌─────────────────┐
│ cmd_* function  │  ← async command implementation
└─────────────────┘
         │
         ▼
┌─────────────────┐
│ CommandOutput   │  ← result, message, data, special fields
└─────────────────┘
         │
         ├──► CLI: JSON serialization of data
         └──► REPL: Rich console print of message
```

---

## Core Types (`protocol.py`)

### CommandResult (Enum)

Indicates the outcome of a command execution.

| Value | Description |
|-------|-------------|
| `SUCCESS` | Command completed successfully |
| `ERROR` | Command failed with an error |
| `QUIT` | User/command requested REPL exit |
| `SWITCH_AGENT` | Command requests switching to a different agent |
| `ENTER_WHISPER` | Command requests entering whisper mode to another agent |

```python
from nexus3.commands import CommandResult

if output.result == CommandResult.SUCCESS:
    # Handle success
elif output.result == CommandResult.SWITCH_AGENT:
    # Switch to output.new_agent_id
```

### CommandOutput (dataclass)

Structured output from command execution. Commands never print directly; they return this object.

**Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `result` | `CommandResult` | The outcome status |
| `message` | `str \| None` | Human-readable message for display |
| `data` | `dict[str, Any] \| None` | Structured data for JSON/programmatic use |
| `new_agent_id` | `str \| None` | Target agent for `SWITCH_AGENT` result |
| `whisper_target` | `str \| None` | Target agent for `ENTER_WHISPER` result |

**Factory Methods:**

```python
from nexus3.commands import CommandOutput

# Success with message and data
output = CommandOutput.success(
    message="Created agent: worker-1",
    data={"agent_id": "worker-1", "created_at": "..."}
)

# Error
output = CommandOutput.error("Agent not found: foo")

# Quit signal
output = CommandOutput.quit()

# Request agent switch (REPL)
output = CommandOutput.switch_agent("worker-1")

# Request whisper mode (REPL)
output = CommandOutput.enter_whisper("worker-1")
```

### CommandContext (dataclass)

Provides commands with access to shared resources and execution context.

**Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `pool` | `AgentPool` | Agent pool for managing agents |
| `session_manager` | `SessionManager` | Session persistence manager |
| `current_agent_id` | `str \| None` | Currently active agent (if any) |
| `is_repl` | `bool` | `True` if running in REPL mode |

**Usage:**

```python
from nexus3.commands import CommandContext

# CLI context (no current agent)
ctx = CommandContext(
    pool=pool,
    session_manager=session_manager,
    is_repl=False
)

# REPL context (with current agent)
ctx = CommandContext(
    pool=pool,
    session_manager=session_manager,
    current_agent_id="main",
    is_repl=True
)
```

The `is_repl` flag affects command behavior:
- **REPL mode**: Cannot destroy current agent, temp saves require name
- **CLI mode**: All operations allowed, uses agent IDs directly

---

## Commands (`core.py`)

All commands are async functions that take `CommandContext` as their first argument and return `CommandOutput`.

### Agent Management

#### `cmd_list(ctx) -> CommandOutput`

List all active agents in the pool.

**Returns** in `data`:
```python
{
    "agents": [
        {
            "agent_id": "main",
            "is_temp": False,
            "message_count": 42,
            "model": "anthropic/claude-sonnet-4",
            "permission_level": "trusted",
            "cwd": "/home/user/project",
            "write_paths": None,  # None = any, [] = none, [...] = specific
            "child_count": 2,
            "parent_agent_id": None,
            "halted_at_iteration_limit": False,
            "last_action_at": "2026-01-21T14:30:00"
        },
        ...
    ]
}
```

#### `cmd_create(ctx, name, permission="trusted", model=None) -> CommandOutput`

Create a new agent without switching to it.

**Parameters:**
- `name`: Agent ID (must not exist)
- `permission`: One of `"sandboxed"`, `"trusted"`, `"yolo"`
- `model`: Optional model alias or ID (None for default)

**Returns** in `data`:
```python
{
    "agent_id": "worker-1",
    "is_temp": False,
    "created_at": "2026-01-21T14:30:00",
    "permission": "trusted",
    "model": None
}
```

**Errors:**
- Invalid permission level
- Agent already exists

#### `cmd_destroy(ctx, name) -> CommandOutput`

Remove an agent from the pool. Log files are preserved.

**Parameters:**
- `name`: Agent ID to destroy

**REPL behavior:** Cannot destroy current agent (must switch first).

**Returns** in `data`:
```python
{"agent_id": "worker-1", "destroyed": True}
```

#### `cmd_status(ctx, agent_id=None, show_tools=False, show_tokens=False) -> CommandOutput`

Get comprehensive agent status.

**Parameters:**
- `agent_id`: Target agent (defaults to current)
- `show_tools`: Include full tool list
- `show_tokens`: Include detailed token breakdown

**Returns** in `data`:
```python
{
    "agent_id": "main",
    "is_temp": False,
    "created_at": "2026-01-21T14:00:00",
    "message_count": 42,
    "context_usage_pct": 35.2,
    "tokens": {
        "total": 35200,
        "available": 64800,
        "remaining": 29600,
        # If show_tokens=True, also includes:
        "budget": 100000,
        "system": 5000,
        "tools": 8000,
        "messages": 22200
    },
    "model": {
        "model_id": "anthropic/claude-sonnet-4",
        "alias": "sonnet",
        "context_window": 200000,
        "provider": "openrouter"
    },
    "permission_level": "TRUSTED",
    "preset": "trusted",
    "cwd": "/home/user/project",
    "allowed_paths": ["/home/user/project"],
    "allowed_write_paths": ["/home/user/project/output"],
    "disabled_tools": ["shell_UNSAFE"],
    "mcp_servers": [
        {"name": "filesystem", "tool_count": 5, "shared": True}
    ],
    "compaction": {
        "enabled": True,
        "trigger_threshold": 0.9,
        "model": "anthropic/claude-haiku"
    },
    "parent_agent_id": None,
    "children": ["worker-1", "worker-2"],
    "tools": ["read_file", "write_file", ...]  # If show_tools=True
}
```

### Message Operations

#### `cmd_send(ctx, agent_id, message) -> CommandOutput`

Send a one-shot message to an agent and get the response.

**Parameters:**
- `agent_id`: Target agent
- `message`: Message content

**Returns** in `data`:
```python
{
    "agent_id": "worker-1",
    "content": "The agent's response text..."
}
```

**Note:** This is for quick interactions. For full conversations, use the REPL or attach to the agent.

#### `cmd_cancel(ctx, agent_id=None, request_id=None) -> CommandOutput`

Cancel an in-progress request.

**Parameters:**
- `agent_id`: Target agent (defaults to current)
- `request_id`: Specific request to cancel (defaults to current)

**Returns** in `data`:
```python
{
    "agent_id": "worker-1",
    "request_id": 12345,
    "cancelled": True
}
```

### Session Persistence

#### `cmd_save(ctx, name=None) -> CommandOutput`

Save the current agent's session to disk.

**Parameters:**
- `name`: Save name (defaults to current agent ID)

**Behavior:**
- Cannot save with temp agent names (e.g., `temp-abc123`)
- Saves messages, system prompt, permissions, token usage, and metadata

**Returns** in `data`:
```python
{
    "name": "my-session",
    "path": "/home/user/.nexus3/sessions/my-session.json",
    "message_count": 42
}
```

#### `cmd_clone(ctx, src, dest) -> CommandOutput`

Clone an agent or saved session.

**Parameters:**
- `src`: Source agent ID or session name
- `dest`: Destination name

**Behavior:**
1. If `src` is an active agent: Creates new agent with copied context
2. If `src` is a saved session: Copies session file

**Returns** in `data`:
```python
{
    "src": "main",
    "dest": "main-backup",
    "type": "active",  # or "saved"
    "message_count": 42,  # for active
    "path": "..."  # for saved
}
```

#### `cmd_rename(ctx, old, new) -> CommandOutput`

Rename an agent or saved session.

**Parameters:**
- `old`: Current name
- `new`: New name

**Behavior:**
- For active agents: Creates new agent, copies state, destroys old
- For saved sessions: Renames file on disk
- Updates `current_agent_id` if renaming current agent

**Returns** in `data`:
```python
{
    "old": "temp-abc123",
    "new": "my-agent",
    "type": "active",  # or "saved"
    "new_current_agent": "my-agent",  # if current was renamed
    "path": "..."  # for saved
}
```

#### `cmd_delete(ctx, name) -> CommandOutput`

Delete a saved session from disk.

**Parameters:**
- `name`: Session name to delete

**Note:** Only deletes saved sessions, not active agents. Use `cmd_destroy` for active agents.

**Returns** in `data`:
```python
{"name": "old-session", "deleted": True}
```

### Server Control

#### `cmd_shutdown(ctx) -> CommandOutput`

Request graceful server shutdown.

**Behavior:**
- Signals all agents to stop
- Returns `QUIT` result

**Returns** in `data`:
```python
{"shutdown": True}
```

---

## Dependencies

### Internal (NEXUS3)

| Module | Usage |
|--------|-------|
| `nexus3.core.permissions` | `AgentPermissions` for status extraction |
| `nexus3.rpc.pool` | `AgentPool`, `is_temp_agent()` |
| `nexus3.session.persistence` | `serialize_session()` for saving |
| `nexus3.session.session_manager` | `SessionManager`, exception types |

### Standard Library

- `dataclasses`: `CommandOutput`, `CommandContext`
- `enum`: `CommandResult`
- `typing`: Type annotations
- `pathlib`: Path handling in `cmd_status`

**No third-party dependencies.**

---

## Usage Examples

### CLI Integration

```python
from nexus3.commands import CommandContext, CommandResult, cmd_list, cmd_status
import json

async def handle_rpc_list(pool, session_manager):
    ctx = CommandContext(pool=pool, session_manager=session_manager)
    output = await cmd_list(ctx)

    if output.result == CommandResult.SUCCESS:
        print(json.dumps(output.data, indent=2))
        return 0
    else:
        print(f"Error: {output.message}", file=sys.stderr)
        return 1
```

### REPL Integration

```python
from nexus3.commands import CommandContext, CommandResult, cmd_status
from rich.console import Console

console = Console()

async def handle_slash_status(pool, session_manager, current_agent):
    ctx = CommandContext(
        pool=pool,
        session_manager=session_manager,
        current_agent_id=current_agent,
        is_repl=True
    )
    output = await cmd_status(ctx, show_tools=True)

    if output.result == CommandResult.SUCCESS:
        console.print(output.message)
    elif output.result == CommandResult.SWITCH_AGENT:
        # Handle agent switch
        return output.new_agent_id
    else:
        console.print(f"[red]Error:[/red] {output.message}")
```

### Creating New Commands

To add a new command:

1. **Add function to `core.py`:**

```python
async def cmd_my_command(
    ctx: CommandContext,
    required_arg: str,
    optional_arg: int = 10,
) -> CommandOutput:
    """Description of what this command does.

    Args:
        ctx: Command context with pool and session_manager.
        required_arg: What this argument is for.
        optional_arg: What this optional argument controls.

    Returns:
        CommandOutput with relevant data.
    """
    # Validate inputs
    if not required_arg:
        return CommandOutput.error("required_arg cannot be empty")

    # Access pool/session_manager via context
    agent = ctx.pool.get(ctx.current_agent_id)
    if agent is None:
        return CommandOutput.error("No current agent")

    # Do the work
    result = await some_operation(agent, required_arg, optional_arg)

    # Return structured output
    return CommandOutput.success(
        message=f"Operation completed: {result}",
        data={
            "agent_id": ctx.current_agent_id,
            "result": result,
            "optional_arg_used": optional_arg,
        }
    )
```

2. **Export from `__init__.py`:**

```python
from nexus3.commands.core import (
    # ... existing imports ...
    cmd_my_command,
)

__all__ = [
    # ... existing exports ...
    "cmd_my_command",
]
```

3. **Wire up in CLI and REPL:**
   - CLI: Add to `nexus3/cli/rpc_commands.py`
   - REPL: Add to slash command handlers in `nexus3/cli/repl.py`

### Error Handling Patterns

Commands should handle errors gracefully and return `CommandOutput.error()`:

```python
async def cmd_example(ctx: CommandContext, agent_id: str) -> CommandOutput:
    # Check existence
    if agent_id not in ctx.pool:
        return CommandOutput.error(f"Agent not found: {agent_id}")

    # Check permissions/state
    if ctx.is_repl and agent_id == ctx.current_agent_id:
        return CommandOutput.error("Cannot operate on current agent")

    try:
        # Attempt operation
        result = await risky_operation()
        return CommandOutput.success(message="Done", data={"result": result})
    except SpecificError as e:
        return CommandOutput.error(f"Operation failed: {e}")
```

---

## Exports (`__init__.py`)

```python
__all__ = [
    # Protocol types
    "CommandContext",
    "CommandOutput",
    "CommandResult",

    # Commands
    "cmd_cancel",
    "cmd_clone",
    "cmd_create",
    "cmd_delete",
    "cmd_destroy",
    "cmd_list",
    "cmd_rename",
    "cmd_save",
    "cmd_send",
    "cmd_shutdown",
    "cmd_status",
]
```

---

## Design Decisions

### Why Structured Output?

Commands return `CommandOutput` instead of printing because:
1. **Testability**: Easy to assert on return values
2. **Flexibility**: CLI uses JSON, REPL uses Rich formatting
3. **Composability**: Commands can be chained programmatically
4. **Consistency**: Same logic produces same results everywhere

### Why Async?

All commands are async because:
1. Agent operations involve I/O (network, disk)
2. Pool operations may await locks
3. Session saves involve file I/O
4. Consistent with NEXUS3's async-first architecture

### Why Context Object?

`CommandContext` bundles dependencies because:
1. Commands need access to shared resources
2. Avoids passing many parameters to each command
3. Context can be extended without changing signatures
4. Makes testing easier (mock one object)

---

Updated: 2026-01-28
