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
from nexus3.core.permissions import (
    AgentPermissions,
    ToolPermission,
    get_builtin_presets,
    resolve_preset,
)
from nexus3.rpc.pool import is_temp_agent

if TYPE_CHECKING:
    from nexus3.rpc.pool import Agent, SharedComponents
    from nexus3.mcp.registry import MCPServerRegistry


def _refresh_agent_tools(
    agent: "Agent",
    mcp_registry: "MCPServerRegistry",
    shared: "SharedComponents",
) -> None:
    """Refresh an agent's tool definitions after MCP connection changes.

    Rebuilds the tool definitions list to include/exclude MCP tools
    based on current MCP registry state and agent permissions.
    """
    from nexus3.mcp.permissions import can_use_mcp

    permissions = agent.services.get("permissions")
    if permissions is None:
        return

    # Get base tools from skill registry
    tool_defs = agent.registry.get_definitions_for_permissions(permissions)

    # Add MCP tools if agent has permission
    if can_use_mcp(permissions):
        for mcp_skill in mcp_registry.get_all_skills():
            # Check if MCP tool is disabled in permissions
            tool_perm = permissions.tool_permissions.get(mcp_skill.name)
            if tool_perm is not None and not tool_perm.enabled:
                continue
            tool_defs.append({
                "type": "function",
                "function": {
                    "name": mcp_skill.name,
                    "description": mcp_skill.description,
                    "parameters": mcp_skill.parameters,
                },
            })

    # Update context with new definitions
    agent.context.set_tool_definitions(tool_defs)


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
  /model              Show current model
  /model <name>       Switch to model (alias or full ID)
  /permissions        Show current permissions
  /permissions <preset>  Change to preset (yolo/trusted/sandboxed)
  /permissions --disable <tool>  Disable a tool
  /permissions --enable <tool>   Re-enable a tool
  /permissions --list-tools      List tool enable/disable status
  /prompt [file]      Show or set system prompt
  /compact            Force context compaction/summarization

MCP (External Tools):
  /mcp                List configured and connected MCP servers
  /mcp connect <name> Connect to a configured MCP server
  /mcp disconnect <name>  Disconnect from an MCP server
  /mcp tools [server] List available MCP tools

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
        # Note: "worker" preset was removed; use "sandboxed" with tool deltas instead

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
    args: str | None = None,
) -> CommandOutput:
    """Show or modify permission level for current agent.

    Usage:
        /permissions              Show current permissions
        /permissions trusted      Change to 'trusted' preset
        /permissions --disable write_file  Disable a tool
        /permissions --enable write_file   Re-enable a tool
        /permissions --list-tools          List tool enable/disable status

    Args:
        ctx: Command context with pool access.
        args: Optional arguments string.

    Returns:
        CommandOutput with current/modified permissions.
    """
    if ctx.current_agent_id is None:
        return CommandOutput.error("No current agent")

    agent = ctx.pool.get(ctx.current_agent_id)
    if agent is None:
        return CommandOutput.error(f"Agent not found: {ctx.current_agent_id}")

    # Get current permissions
    perms: AgentPermissions | None = agent.services.get("permissions")

    if not args or not args.strip():
        # Show current permissions
        return _format_permissions(perms, agent)

    parts = args.strip().split()
    cmd = parts[0].lower()

    if cmd == "--list-tools":
        return _list_tool_permissions(perms)
    elif cmd == "--disable" and len(parts) > 1:
        tool_name = parts[1]
        return await _disable_tool(agent, perms, tool_name)
    elif cmd == "--enable" and len(parts) > 1:
        tool_name = parts[1]
        return await _enable_tool(agent, perms, tool_name)
    elif cmd.startswith("--"):
        return CommandOutput.error(f"Unknown flag: {cmd}")
    else:
        # Change preset (pass custom presets from pool if available)
        custom_presets = getattr(getattr(ctx.pool, "_shared", None), "custom_presets", None)
        return await _change_preset(agent, perms, cmd, custom_presets)


def _format_permissions(
    perms: AgentPermissions | None,
    agent: Agent,
) -> CommandOutput:
    """Format current permissions for display."""
    if perms is None:
        return CommandOutput.success(
            message="Permissions: unrestricted (no policy set)",
            data={"preset": None, "level": None},
        )

    lines = [
        f"Preset: {perms.base_preset}",
        f"Level: {perms.effective_policy.level.value}",
    ]

    # Path info
    if perms.effective_policy.allowed_paths is None:
        lines.append("Paths: unrestricted")
    else:
        paths_str = ", ".join(str(p) for p in perms.effective_policy.allowed_paths)
        lines.append(f"Allowed paths: {paths_str}")

    if perms.effective_policy.blocked_paths:
        blocked_str = ", ".join(str(p) for p in perms.effective_policy.blocked_paths)
        lines.append(f"Blocked paths: {blocked_str}")

    # Ceiling info
    if perms.ceiling:
        lines.append(f"Ceiling: {perms.ceiling.base_preset} (from parent)")

    # Disabled tools
    disabled = [name for name, tp in perms.tool_permissions.items() if not tp.enabled]
    if disabled:
        lines.append(f"Disabled tools: {', '.join(disabled)}")

    return CommandOutput.success(
        message="\n".join(lines),
        data={
            "preset": perms.base_preset,
            "level": perms.effective_policy.level.value,
            "disabled_tools": disabled,
        },
    )


def _list_tool_permissions(perms: AgentPermissions | None) -> CommandOutput:
    """List tool permissions status."""
    if perms is None:
        return CommandOutput.success(message="All tools enabled (no restrictions)")

    lines = ["Tool permissions:"]
    for name, tp in sorted(perms.tool_permissions.items()):
        status = "enabled" if tp.enabled else "disabled"
        lines.append(f"  {name}: {status}")

    if not perms.tool_permissions:
        lines.append("  (no tool-specific permissions set)")

    return CommandOutput.success(message="\n".join(lines))


async def _disable_tool(
    agent: Agent,
    perms: AgentPermissions | None,
    tool_name: str,
) -> CommandOutput:
    """Disable a tool for this agent."""
    if perms is None:
        return CommandOutput.error("Cannot modify permissions: no policy set")

    # Check ceiling - can always disable (more restrictive than ceiling)
    # No check needed here, disabling is always allowed

    # Apply change
    if tool_name in perms.tool_permissions:
        perms.tool_permissions[tool_name].enabled = False
    else:
        perms.tool_permissions[tool_name] = ToolPermission(enabled=False)

    # Resync tool definitions so LLM no longer sees disabled tool
    agent.context.set_tool_definitions(
        agent.registry.get_definitions_for_permissions(perms)
    )

    return CommandOutput.success(
        message=f"Disabled tool: {tool_name}",
        data={"tool": tool_name, "enabled": False},
    )


async def _enable_tool(
    agent: Agent,
    perms: AgentPermissions | None,
    tool_name: str,
) -> CommandOutput:
    """Enable a tool for this agent."""
    if perms is None:
        return CommandOutput.error("Cannot modify permissions: no policy set")

    # Check ceiling - can't enable if ceiling disabled it
    if perms.ceiling:
        ceiling_perm = perms.ceiling.tool_permissions.get(tool_name)
        if ceiling_perm and not ceiling_perm.enabled:
            return CommandOutput.error(
                f"Cannot enable '{tool_name}': disabled by parent ceiling"
            )

    # Apply change
    if tool_name in perms.tool_permissions:
        perms.tool_permissions[tool_name].enabled = True
    else:
        perms.tool_permissions[tool_name] = ToolPermission(enabled=True)

    # Resync tool definitions so LLM sees newly enabled tool
    agent.context.set_tool_definitions(
        agent.registry.get_definitions_for_permissions(perms)
    )

    return CommandOutput.success(
        message=f"Enabled tool: {tool_name}",
        data={"tool": tool_name, "enabled": True},
    )


async def _change_preset(
    agent: Agent,
    perms: AgentPermissions | None,
    preset_name: str,
    custom_presets: dict | None = None,
) -> CommandOutput:
    """Change agent to a new preset."""
    from nexus3.core.permissions import PermissionPreset

    # Handle legacy "worker" preset by mapping to sandboxed
    original_preset_name = preset_name
    if preset_name == "worker":
        preset_name = "sandboxed"

    builtin = get_builtin_presets()
    all_presets = dict(builtin)
    if custom_presets:
        all_presets.update(custom_presets)

    if preset_name not in all_presets:
        valid = ", ".join(all_presets.keys())
        return CommandOutput.error(
            f"Unknown preset: {original_preset_name}. Valid: {valid}"
        )

    # Check ceiling
    if perms and perms.ceiling:
        try:
            new_perms = resolve_preset(preset_name, custom_presets)
            if not perms.ceiling.can_grant(new_perms):
                return CommandOutput.error(
                    f"Cannot change to '{preset_name}': exceeds ceiling "
                    f"(parent: {perms.ceiling.base_preset})"
                )
        except ValueError as e:
            return CommandOutput.error(str(e))

    # Apply change
    try:
        new_perms = resolve_preset(preset_name, custom_presets)
        if perms:
            new_perms.ceiling = perms.ceiling
            new_perms.parent_agent_id = perms.parent_agent_id

        agent.services.register("permissions", new_perms)
        agent.services.register("allowed_paths", new_perms.effective_policy.allowed_paths)

        # Resync tool definitions for new preset's permissions
        agent.context.set_tool_definitions(
            agent.registry.get_definitions_for_permissions(new_perms)
        )

        return CommandOutput.success(
            message=f"Changed to preset: {preset_name}",
            data={"preset": preset_name},
        )
    except ValueError as e:
        return CommandOutput.error(str(e))


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


async def cmd_compact(ctx: CommandContext) -> CommandOutput:
    """Force context compaction/summarization.

    Compacts the conversation context by summarizing older messages,
    freeing up token budget for new interactions.

    Args:
        ctx: Command context with pool access.

    Returns:
        CommandOutput with compaction result.
    """
    if ctx.current_agent_id is None:
        return CommandOutput.error("No current agent")

    agent = ctx.pool.get(ctx.current_agent_id)
    if agent is None:
        return CommandOutput.error(f"Agent not found: {ctx.current_agent_id}")

    session = agent.session

    if session.context is None:
        return CommandOutput.error("No context available")

    messages = session.context.messages
    if len(messages) < 2:
        return CommandOutput.success(
            message="Not enough context to compact",
            data={"compacted": False, "reason": "insufficient_messages"},
        )

    try:
        result = await session.compact(force=True)
        if result is None:
            return CommandOutput.success(
                message="Nothing to compact",
                data={"compacted": False, "reason": "nothing_to_compact"},
            )
        else:
            return CommandOutput.success(
                message=f"Compacted: {result.original_token_count} -> {result.new_token_count} tokens",
                data={
                    "compacted": True,
                    "original_tokens": result.original_token_count,
                    "new_tokens": result.new_token_count,
                },
            )
    except Exception as e:
        return CommandOutput.error(f"Compaction failed: {e}")


async def cmd_model(
    ctx: CommandContext,
    name: str | None = None,
) -> CommandOutput:
    """Show or switch the current agent's model.

    If current context exceeds the new model's context window, prompts
    for action: truncate, compact, or cancel.

    Args:
        ctx: Command context with pool access.
        name: Model name/alias, or None to show current model.

    Returns:
        CommandOutput with model info or switch result.
    """
    if ctx.current_agent_id is None:
        return CommandOutput.error("No current agent")

    agent = ctx.pool.get(ctx.current_agent_id)
    if agent is None:
        return CommandOutput.error(f"Agent not found: {ctx.current_agent_id}")

    # Get config for model resolution
    config = getattr(getattr(ctx.pool, "_shared", None), "config", None)
    if config is None:
        return CommandOutput.error("Config not available")

    from nexus3.config.schema import ResolvedModel

    # Get current model from agent services
    current_model: ResolvedModel | None = agent.services.get("model")

    if name is None:
        # Show current model
        if current_model is None:
            return CommandOutput.success(
                message=f"Model: {config.provider.model} (default)",
                data={
                    "model_id": config.provider.model,
                    "context_window": config.provider.context_window,
                    "alias": None,
                },
            )
        else:
            alias_info = f" (alias: {current_model.alias})" if current_model.alias else ""
            return CommandOutput.success(
                message=f"Model: {current_model.model_id}{alias_info}\n"
                        f"Context window: {current_model.context_window:,} tokens\n"
                        f"Reasoning: {'enabled' if current_model.reasoning else 'disabled'}",
                data={
                    "model_id": current_model.model_id,
                    "context_window": current_model.context_window,
                    "reasoning": current_model.reasoning,
                    "alias": current_model.alias,
                },
            )

    # Resolve new model
    try:
        new_model = config.resolve_model(name)
    except Exception as e:
        return CommandOutput.error(f"Failed to resolve model '{name}': {e}")

    # Get current token usage
    usage = agent.context.get_token_usage()
    current_tokens = usage.get("total", 0)

    # Check if context exceeds new model's capacity
    if current_tokens > new_model.context_window:
        # Context too large for new model - return error with guidance
        # (actual prompting for action is handled in REPL)
        return CommandOutput.error(
            f"Current context ({current_tokens:,} tokens) exceeds "
            f"{name}'s capacity ({new_model.context_window:,} tokens).\n"
            f"Use /compact first to reduce context, or start a fresh session.",
            data={
                "action_required": "reduce_context",
                "current_tokens": current_tokens,
                "new_capacity": new_model.context_window,
                "overage": current_tokens - new_model.context_window,
            },
        )

    # Update model in agent services
    agent.services.register("model", new_model)

    # Update context manager's max_tokens
    if hasattr(agent.context, "_config"):
        agent.context._config.max_tokens = new_model.context_window

    alias_info = f" (alias: {new_model.alias})" if new_model.alias else ""
    return CommandOutput.success(
        message=f"Switched to model: {new_model.model_id}{alias_info}\n"
                f"Context window: {new_model.context_window:,} tokens",
        data={
            "model_id": new_model.model_id,
            "context_window": new_model.context_window,
            "reasoning": new_model.reasoning,
            "alias": new_model.alias,
        },
    )


async def _mcp_connection_consent(
    server_name: str,
    tool_names: list[str],
    is_yolo: bool = False,
) -> tuple[bool, bool]:
    """Prompt user for MCP connection consent.

    Args:
        server_name: Name of the MCP server.
        tool_names: List of tool names the server provides.
        is_yolo: If True, skip prompt and allow all.

    Returns:
        Tuple of (proceed: bool, allow_all: bool).
        If proceed is False, the connection should be cancelled.
    """
    import asyncio
    from rich.console import Console

    # YOLO mode skips prompts
    if is_yolo:
        return (True, True)

    console = Console()

    console.print(f"\n[yellow]Connect to MCP server '{server_name}'?[/]")
    console.print(f"  [dim]Tools:[/] {', '.join(tool_names)}")
    console.print()
    console.print("  [cyan][1][/] Allow all tools (this session)")
    console.print("  [cyan][2][/] Require confirmation for each tool")
    console.print("  [cyan][3][/] Deny connection")

    def get_input() -> str:
        try:
            return console.input("\n[dim]Choice [1-3]:[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            return "3"

    response = await asyncio.to_thread(get_input)

    if response == "1":
        return (True, True)  # Proceed, allow all
    elif response == "2":
        return (True, False)  # Proceed, per-tool confirmation
    else:
        return (False, False)  # Don't proceed


async def cmd_mcp(
    ctx: CommandContext,
    args: str | None = None,
) -> CommandOutput:
    """Handle /mcp commands for MCP server management.

    Subcommands:
        /mcp                List configured and connected servers
        /mcp connect <name> Connect to a configured MCP server
        /mcp disconnect <name>  Disconnect from server
        /mcp tools [server] List available MCP tools

    Args:
        ctx: Command context with pool access.
        args: Subcommand and arguments.

    Returns:
        CommandOutput with result.
    """
    from nexus3.mcp.permissions import can_use_mcp
    from nexus3.mcp.registry import MCPServerConfig
    from nexus3.core.permissions import PermissionLevel

    # Check agent permissions for MCP access
    if ctx.current_agent_id is not None:
        agent = ctx.pool.get(ctx.current_agent_id)
        if agent is not None:
            perms = agent.services.get("permissions")
            if not can_use_mcp(perms):
                return CommandOutput.error(
                    "MCP access requires TRUSTED or YOLO permission level"
                )

    # Get shared components
    shared = getattr(ctx.pool, "_shared", None)
    if shared is None:
        return CommandOutput.error("Pool shared components not available")

    config = shared.config
    registry = shared.mcp_registry

    # Parse subcommand
    parts = (args or "").strip().split()

    if len(parts) == 0:
        # List servers
        lines = ["MCP Servers:"]
        lines.append("")

        # Configured servers
        if config.mcp_servers:
            lines.append("Configured:")
            for srv_cfg in config.mcp_servers:
                connected = registry.get(srv_cfg.name) is not None
                status = "[connected]" if connected else "[disconnected]"
                enabled = "" if srv_cfg.enabled else " (disabled)"
                lines.append(f"  {srv_cfg.name} {status}{enabled}")
        else:
            lines.append("Configured: (none)")

        lines.append("")

        # Connected servers
        connected_names = registry.list_servers()
        if connected_names:
            lines.append(f"Connected: {len(connected_names)}")
            for name in connected_names:
                server = registry.get(name)
                if server:
                    tool_count = len(server.skills)
                    allow_mode = "allow-all" if server.allowed_all else "per-tool"
                    lines.append(f"  {name}: {tool_count} tools ({allow_mode})")
        else:
            lines.append("Connected: (none)")

        return CommandOutput.success(message="\n".join(lines))

    subcmd = parts[0].lower()

    if subcmd == "connect":
        if len(parts) < 2:
            return CommandOutput.error("Usage: /mcp connect <name>")

        name = parts[1]

        # Find in config
        srv_cfg = next(
            (c for c in config.mcp_servers if c.name == name),
            None,
        )

        if srv_cfg is None:
            return CommandOutput.error(
                f"MCP server '{name}' not found in config.\n"
                f"Add it to config.json under 'mcp_servers'."
            )

        if not srv_cfg.enabled:
            return CommandOutput.error(f"MCP server '{name}' is disabled in config")

        # Already connected?
        if registry.get(name) is not None:
            return CommandOutput.error(f"Already connected to '{name}'")

        # Convert config schema to registry config
        reg_cfg = MCPServerConfig(
            name=srv_cfg.name,
            command=srv_cfg.command,
            url=srv_cfg.url,
            env=srv_cfg.env,
            enabled=srv_cfg.enabled,
        )

        # Get agent permissions to check if YOLO (skip prompts)
        agent = ctx.pool.get(ctx.current_agent_id) if ctx.current_agent_id else None
        perms = agent.services.get("permissions") if agent else None
        is_yolo = (
            perms is not None and
            perms.effective_policy.level == PermissionLevel.YOLO
        )

        try:
            # Connect initially with allow_all=False to get tool list
            server = await registry.connect(reg_cfg, allow_all=False)
            tool_names = [s.original_name for s in server.skills]

            # Prompt for consent (TRUSTED mode), skip for YOLO
            proceed, allow_all = await _mcp_connection_consent(
                name, tool_names, is_yolo=is_yolo
            )

            if not proceed:
                # User denied - disconnect and return
                await registry.disconnect(name)
                return CommandOutput.error(f"Connection to '{name}' denied by user")

            # Update the server's allowed_all flag
            server.allowed_all = allow_all

            # If allow_all, add to session allowances for persistence
            if allow_all and perms is not None:
                perms.session_allowances.add_mcp_server(name)

            # Refresh tool definitions for current agent
            if agent:
                _refresh_agent_tools(agent, registry, shared)

            mode = "allow-all" if allow_all else "per-tool"
            return CommandOutput.success(
                message=f"Connected to '{name}' ({mode})\n"
                        f"Tools available: {', '.join(tool_names)}",
                data={
                    "server": name,
                    "tools": tool_names,
                    "allow_all": allow_all,
                },
            )
        except Exception as e:
            return CommandOutput.error(f"Failed to connect to '{name}': {e}")

    elif subcmd == "disconnect":
        if len(parts) < 2:
            return CommandOutput.error("Usage: /mcp disconnect <name>")

        name = parts[1]

        if registry.get(name) is None:
            return CommandOutput.error(f"Not connected to '{name}'")

        await registry.disconnect(name)

        # Refresh tool definitions to remove disconnected MCP tools
        if ctx.current_agent_id:
            agent = ctx.pool.get(ctx.current_agent_id)
            if agent:
                _refresh_agent_tools(agent, registry, shared)

        return CommandOutput.success(message=f"Disconnected from '{name}'")

    elif subcmd == "tools":
        server_name = parts[1] if len(parts) > 1 else None

        if server_name:
            server = registry.get(server_name)
            if server is None:
                return CommandOutput.error(f"Not connected to '{server_name}'")
            skills = server.skills
        else:
            skills = registry.get_all_skills()

        if not skills:
            return CommandOutput.success(message="No MCP tools available")

        lines = ["MCP Tools:"]
        for skill in skills:
            lines.append(f"  {skill.name}")
            if skill.description:
                # Truncate long descriptions
                desc = skill.description[:60] + "..." if len(skill.description) > 60 else skill.description
                lines.append(f"    {desc}")

        return CommandOutput.success(
            message="\n".join(lines),
            data={"tools": [s.name for s in skills]},
        )

    else:
        return CommandOutput.error(
            f"Unknown MCP subcommand: {subcmd}\n"
            f"Usage: /mcp [connect|disconnect|tools] [args]"
        )
