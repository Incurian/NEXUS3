# nexus3.commands

Unified command infrastructure for NEXUS3.

Provides shared implementations for `nexus-rpc` CLI and `/slash` REPL commands.

## Key Files

- **protocol.py**: Core types (`CommandResult`, `CommandOutput`, `CommandContext`).
- **core.py**: Command functions (`cmd_list`, `cmd_create`, `cmd_destroy`, `cmd_send`, `cmd_status`, `cmd_cancel`, `cmd_save`, `cmd_clone`, `cmd_rename`, `cmd_delete`, `cmd_shutdown`).
- **`__init__.py`**: Re-exports types and commands.

## Usage

Commands take `CommandContext` (with agent pool, session manager) and return `CommandOutput` (structured result with message/data).

Example:
```python
from nexus3.commands import cmd_list, CommandContext

ctx = CommandContext(pool=pool, session_manager=manager)
output = await cmd_list(ctx)
if output.result == CommandResult.SUCCESS:
    print(output.message)
```

See docstrings for details.