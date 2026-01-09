"""Unified command infrastructure for NEXUS3.

This module provides shared command implementations that work for both
`nexus-rpc` CLI and `/slash` REPL commands.

Architecture:
    - protocol.py: Types for command system (CommandResult, CommandOutput, CommandContext)
    - core.py: Unified command implementations that return structured output

Example:
    from nexus3.commands import CommandContext, CommandResult, cmd_list

    ctx = CommandContext(pool=pool, session_manager=manager)
    output = await cmd_list(ctx)
    if output.result == CommandResult.SUCCESS:
        print(output.data)
"""

from nexus3.commands.core import (
    cmd_cancel,
    cmd_clone,
    cmd_create,
    cmd_delete,
    cmd_destroy,
    cmd_list,
    cmd_rename,
    cmd_save,
    cmd_send,
    cmd_shutdown,
    cmd_status,
)
from nexus3.commands.protocol import (
    CommandContext,
    CommandOutput,
    CommandResult,
)

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
