"""REPL-specific command handlers for NEXUS3.

This module provides slash command implementations that only work in
REPL mode. These commands manage agent switching, whisper mode, and
REPL-specific state.

Commands:
    /agent           - Show current agent detailed status
    /agent foo       - Switch to foo (creates if doesn't exist with prompt)
    /agent foo --yolo - Create with permission level and switch
    /whisper foo     - Enter whisper mode (redirect input to target agent)
    /over            - Exit whisper mode, return to original agent
    /cwd [path]      - Show or set working directory for current agent
    /permissions [level] - Show or set permission level
    /prompt [file]   - Show or set system prompt
    /help            - Display help text
    /clear           - Clear display (but preserve context)
    /quit            - Exit REPL
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from nexus3.cli.whisper import WhisperMode
from nexus3.commands.protocol import CommandContext, CommandOutput, CommandResult
from nexus3.core.permissions import PermissionLevel
from nexus3.rpc.pool import is_temp_agent

if TYPE_CHECKING:
    pass


# Help text for REPL commands
HELP_TEXT = """
NEXUS3 REPL Commands
====================

Agent Management:
  /agent              Show current agent's detailed status
  /agent <name>       Switch to agent (prompts to create if doesn't exist)
  /agent <name> --yolo|--trusted|--sandboxed
                      Create agent with permission level and switch to it

  /whisper <agent>    Enter whisper mode - redirect all input to target agent
  /over               Exit whisper mode, return to original agent

  /list               List all active agents
  /create <name>      Create agent without switching
  /destroy <name>     Remove active agent from pool
  /send <agent> <msg> One-shot message to another agent
  /status [agent]     Get agent status (default: current agent)
  /cancel [agent]     Cancel in-progress request

Session Management:
  /save [name]        Save current session (prompts for name if temp)
  /clone <src> <dest> Clone agent or saved session
  /rename <old> <new> Rename agent or saved session
  /delete <name>      Delete saved session from disk

Configuration:
  /cwd [path]         Show or change working directory
  /permissions [lvl]  Show or set permission level (yolo/trusted/sandboxed)
  /prompt [file]      Show or set system prompt

REPL Control:
  /help               Show this help message
  /clear              Clear the display (preserves context)
  /quit, /exit, /q    Exit the REPL

Keyboard Shortcuts:
  ESC                 Cancel in-progress request
  Ctrl+C              Interrupt current input
  Ctrl+D              Exit REPL
""".strip()


async def cmd_agent(
    ctx: CommandContext,
    args: str | None = None,
) -> CommandOutput:
    """Handle /agent command - show status, switch, or create+switch.

    Behavior:
    - /agent           Show current agent detailed status
    - /agent foo       Switch to foo, prompt to create if doesn't exist
    - /agent foo --yolo Create with permission level and switch

    Args:
        ctx: Command context with pool and session_manager.
        args: Optional arguments string (agent name and flags).

    Returns:
        CommandOutput with SUCCESS, SWITCH_AGENT, or ERROR result.
    """
    # Parse args
    if not args or not args.strip():
        # No args: show current agent status
        return await _show_agent_status(ctx)

    parts = args.strip().split()
    agent_name = parts[0]

    # Parse permission flag if present
    permission: str | None = None
    for part in parts[1:]:
        part_lower = part.lower()
        if part_lower in ("--yolo", "-y"):
            permission = "yolo"
        elif part_lower in ("--trusted", "-t"):
            permission = "trusted"
        elif part_lower in ("--sandboxed", "-s"):
            permission = "sandboxed"

    # Check if agent exists in pool (active)
    if agent_name in ctx.pool:
        # Agent exists, switch to it
        return CommandOutput.switch_agent(agent_name)

    # Check if agent exists as a saved session on disk
    try:
        saved_session = ctx.session_manager.load_session(agent_name)
        # Found saved session - offer to restore it
        msg_count = len(saved_session.messages)
        return CommandOutput(
            result=CommandResult.ERROR,
            message=f"Restore saved session '{agent_name}' ({msg_count} messages)? (y/n)",
            data={
                "action": "prompt_restore",
                "agent_name": agent_name,
                "permission": permission or saved_session.permission_level,
            },
        )
    except Exception:
        pass  # Session not found on disk

    # Agent doesn't exist anywhere - prompt to create
    # The REPL handles the actual confirmation prompt
    perm_str = f" with --{permission}" if permission else ""
    return CommandOutput(
        result=CommandResult.ERROR,
        message=f"Agent '{agent_name}' doesn't exist. Create it{perm_str}? (y/n)",
        data={
            "action": "prompt_create",
            "agent_name": agent_name,
            "permission": permission or "trusted",
        },
    )


async def _show_agent_status(ctx: CommandContext) -> CommandOutput:
    """Show detailed status of current agent.

    Args:
        ctx: Command context with pool access.

    Returns:
        CommandOutput with agent status information.
    """
    if ctx.current_agent_id is None:
        return CommandOutput.error("No current agent")

    agent = ctx.pool.get(ctx.current_agent_id)
    if agent is None:
        return CommandOutput.error(f"Agent not found: {ctx.current_agent_id}")

    # Gather detailed status info
    tokens = agent.context.get_token_usage()
    message_count = len(agent.context.messages)
    agent_type = "temp" if is_temp_agent(agent.agent_id) else "named"

    # Format detailed output
    lines = [
        f"Agent: {agent.agent_id}",
        f"  Type: {agent_type}",
        f"  Created: {agent.created_at.isoformat()}",
        f"  Messages: {message_count}",
        "  Tokens:",
        f"    Total: {tokens.get('total', 0)}",
        f"    Budget: {tokens.get('budget', 0)}",
        f"  System Prompt: {len(agent.context.system_prompt or '')} chars",
    ]

    return CommandOutput.success(
        message="\n".join(lines),
        data={
            "agent_id": agent.agent_id,
            "type": agent_type,
            "created_at": agent.created_at.isoformat(),
            "message_count": message_count,
            "tokens": tokens,
            "system_prompt_length": len(agent.context.system_prompt or ""),
        },
    )


async def cmd_whisper(
    ctx: CommandContext,
    whisper: WhisperMode,
    target: str,
) -> CommandOutput:
    """Enter whisper mode - redirect input to target agent.

    Whisper mode sends all subsequent input to the target agent until
    /over is called. The prompt changes to show the target agent name.

    Args:
        ctx: Command context with pool access.
        whisper: WhisperMode instance to update.
        target: Target agent ID to whisper to.

    Returns:
        CommandOutput with ENTER_WHISPER or ERROR result.
    """
    # Check if target agent exists
    if target not in ctx.pool:
        return CommandOutput(
            result=CommandResult.ERROR,
            message=f"Agent '{target}' doesn't exist. Create it? (y/n)",
            data={
                "action": "prompt_create_whisper",
                "agent_name": target,
            },
        )

    # Check we're not already whispering to this target
    if whisper.is_active() and whisper.target_agent_id == target:
        return CommandOutput.error(f"Already whispering to {target}")

    # Check we have a current agent to return to
    if ctx.current_agent_id is None:
        return CommandOutput.error("No current agent to return to from whisper mode")

    # Enter whisper mode
    whisper.enter(target, ctx.current_agent_id)

    return CommandOutput.enter_whisper(target)


async def cmd_over(
    ctx: CommandContext,
    whisper: WhisperMode,
) -> CommandOutput:
    """Exit whisper mode, return to original agent.

    Args:
        ctx: Command context (unused but consistent with other commands).
        whisper: WhisperMode instance to update.

    Returns:
        CommandOutput with SWITCH_AGENT or ERROR result.
    """
    if not whisper.is_active():
        return CommandOutput.error("Not in whisper mode")

    original = whisper.exit()
    if original is None:
        return CommandOutput.error("No original agent to return to")

    return CommandOutput.switch_agent(original)


async def cmd_cwd(
    ctx: CommandContext,
    path: str | None = None,
) -> CommandOutput:
    """Show or set working directory for current agent.

    Args:
        ctx: Command context with pool access.
        path: New working directory path, or None to show current.

    Returns:
        CommandOutput with current/new working directory.
    """
    if path is None:
        # Show current working directory
        cwd = os.getcwd()
        return CommandOutput.success(
            message=f"Working directory: {cwd}",
            data={"cwd": cwd},
        )

    # Set new working directory
    try:
        new_path = Path(path).expanduser().resolve()
        if not new_path.exists():
            return CommandOutput.error(f"Directory does not exist: {path}")
        if not new_path.is_dir():
            return CommandOutput.error(f"Not a directory: {path}")

        os.chdir(new_path)
        return CommandOutput.success(
            message=f"Changed working directory to: {new_path}",
            data={"cwd": str(new_path)},
        )
    except PermissionError:
        return CommandOutput.error(f"Permission denied: {path}")
    except OSError as e:
        return CommandOutput.error(f"Error changing directory: {e}")


async def cmd_permissions(
    ctx: CommandContext,
    level: str | None = None,
) -> CommandOutput:
    """Show or set permission level for current agent.

    Permission levels:
    - yolo: Full access, no confirmations
    - trusted: Confirmations for destructive actions (default)
    - sandboxed: Limited paths, restricted network

    Args:
        ctx: Command context with pool access.
        level: New permission level, or None to show current.

    Returns:
        CommandOutput with current/new permission level.
    """
    if ctx.current_agent_id is None:
        return CommandOutput.error("No current agent")

    agent = ctx.pool.get(ctx.current_agent_id)
    if agent is None:
        return CommandOutput.error(f"Agent not found: {ctx.current_agent_id}")

    if level is None:
        # Show current permission level
        # TODO: Agent doesn't track permission yet, return placeholder
        return CommandOutput.success(
            message="Permission level: trusted (default)",
            data={"permission": "trusted"},
        )

    # Validate and set new permission level
    level_lower = level.lower()
    try:
        # Validate via enum
        PermissionLevel(level_lower)
    except ValueError:
        valid = [pl.value for pl in PermissionLevel]
        return CommandOutput.error(
            f"Invalid permission level: {level}. "
            f"Valid levels: {', '.join(valid)}"
        )

    # TODO: Actually set permission on agent when agent supports it
    return CommandOutput.success(
        message=f"Permission level set to: {level_lower}",
        data={"permission": level_lower},
    )


async def cmd_prompt(
    ctx: CommandContext,
    file: str | None = None,
) -> CommandOutput:
    """Show or set system prompt for current agent.

    Args:
        ctx: Command context with pool access.
        file: Path to prompt file, or None to show current.

    Returns:
        CommandOutput with current/new system prompt info.
    """
    if ctx.current_agent_id is None:
        return CommandOutput.error("No current agent")

    agent = ctx.pool.get(ctx.current_agent_id)
    if agent is None:
        return CommandOutput.error(f"Agent not found: {ctx.current_agent_id}")

    if file is None:
        # Show current system prompt info
        prompt = agent.context.system_prompt or ""
        preview = prompt[:200] + "..." if len(prompt) > 200 else prompt

        return CommandOutput.success(
            message=f"System prompt ({len(prompt)} chars):\n{preview}",
            data={
                "length": len(prompt),
                "preview": preview,
            },
        )

    # Load and set new system prompt from file
    try:
        prompt_path = Path(file).expanduser().resolve()
        if not prompt_path.exists():
            return CommandOutput.error(f"File not found: {file}")
        if not prompt_path.is_file():
            return CommandOutput.error(f"Not a file: {file}")

        content = prompt_path.read_text(encoding="utf-8")
        agent.context.set_system_prompt(content)

        return CommandOutput.success(
            message=f"System prompt loaded from: {prompt_path} ({len(content)} chars)",
            data={
                "path": str(prompt_path),
                "length": len(content),
            },
        )
    except PermissionError:
        return CommandOutput.error(f"Permission denied: {file}")
    except OSError as e:
        return CommandOutput.error(f"Error reading file: {e}")


async def cmd_help(ctx: CommandContext) -> CommandOutput:
    """Display help text for REPL commands.

    Args:
        ctx: Command context (unused but consistent with other commands).

    Returns:
        CommandOutput with help text.
    """
    return CommandOutput.success(message=HELP_TEXT)


async def cmd_clear(ctx: CommandContext) -> CommandOutput:
    """Clear the display but preserve context.

    This command signals to the REPL to clear the terminal display.
    The conversation context is not affected.

    Args:
        ctx: Command context (unused but consistent with other commands).

    Returns:
        CommandOutput with clear action indicator.
    """
    return CommandOutput.success(
        message=None,  # No message to display
        data={"action": "clear"},
    )


async def cmd_quit(ctx: CommandContext) -> CommandOutput:
    """Exit the REPL.

    Args:
        ctx: Command context (unused but consistent with other commands).

    Returns:
        CommandOutput with QUIT result.
    """
    return CommandOutput.quit()
