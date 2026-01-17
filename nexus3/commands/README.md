# nexus3.commands

Unified command infrastructure for NEXUS3.

This module provides shared, structured command implementations for both the `nexus-rpc` CLI tool and `/slash` REPL commands. Commands return `CommandOutput` objects for flexible output handling (JSON for CLI, rich text for REPL).

## Purpose
- **Centralized Logic**: Single source for agent/session management commands.
- **Structured Output**: `CommandOutput` with `result`, `message` (human-readable), `data` (structured).
- **Agent/Session Ops**: Create/list/destroy agents, save/clone/rename/delete sessions, send messages, status, cancel, shutdown.
- **Cross-Compatible**: Works in CLI and REPL modes.

## Key Components

### Files
| File | Description | Size |
|------|-------------|------|
| [`__init__.py`](__init__.py) | Re-exports all public APIs. | 1.2K |
| [`protocol.py`](protocol.py) | Core types: `CommandResult`, `CommandOutput`, `CommandContext`. | 3.8K |
| [`core.py`](core.py) | Async command functions. | 23.7K |

### Types (`protocol.py`)
- **`CommandResult` (Enum)**: `SUCCESS`, `ERROR`, `QUIT`, `SWITCH_AGENT`, `ENTER_WHISPER`.
- **`CommandOutput` (dataclass)**: Structured response. Classmethods: `success()`, `error()`, `quit()`, `switch_agent()`, `enter_whisper()`.
- **`CommandContext` (dataclass)**: `pool` (AgentPool), `session_manager`, `current_agent_id`, `is_repl`.

### Commands (`core.py`)
| Command | Args | Description |
|---------|------|-------------|
| `cmd_list` | `(ctx)` | List active agents. |
| `cmd_create` | `(ctx, name, permission="trusted")` | Create named agent ("sandboxed/trusted/yolo/worker"). |
| `cmd_destroy` | `(ctx, name)` | Destroy agent (preserves logs). |
| `cmd_send` | `(ctx, agent_id, message)` | Send one-shot message, get response. |
| `cmd_status` | `(ctx, agent_id=None, show_tools=False, show_tokens=False)` | Detailed status (tokens, model, perms, tools). |
| `cmd_cancel` | `(ctx, agent_id=None, request_id=None)` | Cancel in-progress request. |
| `cmd_save` | `(ctx, name=None)` | Save current session. |
| `cmd_clone` | `(ctx, src, dest)` | Clone agent/session. |
| `cmd_rename` | `(ctx, old, new)` | Rename agent/session. |
| `cmd_delete` | `(ctx, name)` | Delete saved session. |
| `cmd_shutdown` | `(ctx)` | Graceful server shutdown. |

## Dependencies
- **NEXUS3**: `nexus3.core.permissions`, `nexus3.rpc.pool`, `nexus3.session.*`.
- **Stdlib**: `dataclasses`, `enum`, `typing`, `pathlib`.

No third-party deps.

## Usage Examples

### Setup
```python
from nexus3.commands import CommandContext, cmd_list
from nexus3.rpc.pool import AgentPool
from nexus3.session.session_manager import SessionManager

ctx = CommandContext(pool=pool, session_manager=manager)
```

### List Agents
```python
output = await cmd_list(ctx)
if output.result == CommandResult.SUCCESS:
    print(output.message)  # Human-readable list
    print(output.data["agents"])  # JSON data
```

### Create & Interact
```python
create_out = await cmd_create(ctx, "my-agent", "trusted")
send_out = await cmd_send(ctx, "my-agent", "Hello!")
print(send_out.message)  # Response
```

### Status
```python
await cmd_status(ctx, show_tools=True, show_tokens=True)
```

### Sessions
```python
await cmd_save(ctx, "my-session")
await cmd_clone(ctx, "my-session", "backup")
await cmd_shutdown(ctx)
```

CLI: `nexus-rpc list`, etc.  
REPL: `/list`, `/create my-agent`, etc.

## Architecture
```
CLI/REPL → CommandContext → cmd_*() → CommandOutput → Render (JSON/Rich)
                  ↓
       Shared: AgentPool + SessionManager
```

- **Async**: For I/O ops.
- **Safe**: REPL protections (no self-destroy).
- **Extensible**: Add `cmd_*` and export in `__init__.py`.

Generated: 2026-01-17