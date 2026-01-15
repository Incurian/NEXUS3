# nexus3.commands

Unified command infrastructure for NEXUS3.

This module provides shared, structured command implementations that work seamlessly for both the `nexus-rpc` CLI tool and the `/slash` REPL commands in the NEXUS3 agent interface. Commands return `CommandOutput` objects with structured data and human-readable messages, allowing the caller (CLI or REPL) to handle output formatting appropriately (e.g., JSON for CLI, rich text for REPL).

## Purpose

- **Centralized Command Logic**: Avoid code duplication between CLI and REPL.
- **Structured Output**: Commands produce `CommandOutput` for flexible rendering.
- **Agent Management**: Handle agent lifecycle (create, list, destroy, etc.), sessions (save, clone, rename, delete), and interactions (send, status, cancel).
- **Cross-Context Compatibility**: Works in both non-interactive CLI and interactive REPL modes.

## Key Modules & Components

### Files
| File | Description | Size |
|------|-------------|------|
| [`__init__.py`](__init__.py) | Re-exports all public types and commands for easy imports. | 1.2K |
| [`protocol.py`](protocol.py) | Core types: `CommandResult` (Enum), `CommandOutput` (dataclass), `CommandContext` (dataclass). | 3.8K |
| [`core.py`](core.py) | Async command implementations (23K). | 23.1K |

### Key Classes/Types (`protocol.py`)
- **`CommandResult` (Enum)**: SUCCESS, ERROR, QUIT, SWITCH_AGENT, ENTER_WHISPER.
- **`CommandOutput` (dataclass)**: Structured result with `result`, `message`, `data`, etc. Classmethods: `success()`, `error()`, `quit()`, `switch_agent()`, `enter_whisper()`.
- **`CommandContext` (dataclass)**: Provides `pool` (AgentPool), `session_manager` (SessionManager), `current_agent_id`, `is_repl`.

### Key Functions (`core.py`)
| Command | Description | Args |
|---------|-------------|------|
| `cmd_list(ctx)` | List all active agents with details. | - |
| `cmd_create(ctx, name, permission="trusted")` | Create new named agent. | name, permission (sandboxed/trusted/yolo/worker) |
| `cmd_destroy(ctx, name)` | Destroy agent (preserves logs). | name |
| `cmd_send(ctx, agent_id, message)` | Send one-shot message to agent and get response. | agent_id, message |
| `cmd_status(ctx, agent_id=None, show_tools=False, show_tokens=False)` | Detailed agent status (tokens, model, perms, tools, etc.). | agent_id, flags |
| `cmd_cancel(ctx, agent_id=None, request_id=None)` | Cancel in-progress request. | agent_id, request_id |
| `cmd_save(ctx, name=None)` | Save current agent's session to disk. | name |
| `cmd_clone(ctx, src, dest)` | Clone active agent or saved session. | src, dest |
| `cmd_rename(ctx, old, new)` | Rename active agent or saved session. | old, new |
| `cmd_delete(ctx, name)` | Delete saved session from disk. | name |
| `cmd_shutdown(ctx)` | Request graceful server shutdown. | - |

All exported via `__init__.py` as `__all__`.

## Dependencies

### Runtime (NEXUS3 Internal)
- `nexus3.core.permissions` (AgentPermissions)
- `nexus3.rpc.pool` (AgentPool, is_temp_agent)
- `nexus3.session.persistence` (serialize_session)
- `nexus3.session.session_manager` (SessionManager, errors)
- `pathlib` (Path handling)

### Standard Library
- `dataclasses`, `enum`, `typing`
- `json` (implicit in examples)

No external third-party dependencies.

## Usage Examples

### Basic Setup
```python
from nexus3.commands import CommandContext, CommandOutput, CommandResult, cmd_list
from nexus3.rpc.pool import AgentPool  # Example pool
from nexus3.session.session_manager import SessionManager  # Example manager

ctx = CommandContext(pool=pool, session_manager=manager)
```

### List Agents
```python
output = await cmd_list(ctx)
if output.result == CommandResult.SUCCESS:
    print(output.message)  # Human-readable
    print(output.data["agents"])  # Structured JSON
```

### Create & Send Message
```python
# Create
create_out = await cmd_create(ctx, "my-agent", "trusted")
if create_out.result == CommandResult.SUCCESS:
    # Send one-shot
    send_out = await cmd_send(ctx, "my-agent", "Hello, agent!")
    print(send_out.message)  # Agent response
```

### Status (Rich Output)
```python
status_out = await cmd_status(ctx, show_tools=True, show_tokens=True)
print(status_out.message)  # Formatted multi-line status
```

### Session Management
```python
# Save current
await cmd_save(ctx, "my-session")

# Clone
await cmd_clone(ctx, "src-agent", "my-clone")

# Shutdown
await cmd_shutdown(ctx)
```

CLI Usage (via `nexus-rpc`): Commands map directly (e.g., `nexus-rpc list` → `cmd_list`).
REPL Usage: `/list`, `/create my-agent`, etc.

## Architecture Summary

```
nexus3.commands
├── protocol.py    # Types & contracts (input/output)
├── core.py        # Pure async functions (business logic)
└── __init__.py    # Public API (re-exports)

Caller (CLI/REPL) → CommandContext → cmd_*() → CommandOutput → Render (JSON/Rich)
                  ↑
              Shared Resources (pool, session_manager)
```

- **Stateless Commands**: Functions are pure (side-effect free except via context).
- **Error Handling**: Returns `CommandOutput.error()` with messages.
- **Permissions**: Respects agent permissions (e.g., can't destroy current REPL agent).
- **Flexibility**: Data for machine-readable output, message for human-readable.

## Development Notes
- Commands are async for I/O (agent ops, file saves).
- REPL mode (`ctx.is_repl=True`) affects behaviors (e.g., no self-destroy).
- Extend by adding new `cmd_*` functions and exporting in `__init__.py`.

Generated: 2026-01-15
