"""Unified command implementations for NEXUS3.

This module provides command implementations that work for both
`nexus-rpc` CLI and `/slash` REPL commands.

Commands return CommandOutput with structured data rather than
printing directly. This allows the caller (CLI or REPL) to format
the output appropriately.

Example:
    from nexus3.commands import CommandContext, cmd_list

    ctx = CommandContext(pool=pool, session_manager=manager)
    output = await cmd_list(ctx)

    # CLI: print JSON
    if output.data:
        print(json.dumps(output.data))

    # REPL: format nicely
    if output.message:
        console.print(output.message)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus3.commands.protocol import CommandContext, CommandOutput
from nexus3.core.permissions import AgentPermissions
from nexus3.rpc.pool import is_temp_agent
from nexus3.session.persistence import serialize_clipboard_entries, serialize_session
from nexus3.session.session_manager import SessionManagerError, SessionNotFoundError

if TYPE_CHECKING:
    pass


async def cmd_list(ctx: CommandContext) -> CommandOutput:
    """List all agents in the pool.

    Returns information about all active agents including their ID,
    model, permission level, cwd, write paths, message count, child count,
    last action timestamp, and halted status.

    Args:
        ctx: Command context with pool and session_manager.

    Returns:
        CommandOutput with list of agents in data field.
    """
    agents = ctx.pool.list()

    # Format message for display
    if not agents:
        message = "No active agents"
    else:
        lines = ["Active agents:"]
        for agent in agents:
            agent_type = "temp" if agent["is_temp"] else "named"
            child_count = agent.get("child_count", 0)
            parent_id = agent.get("parent_agent_id")
            halted = agent.get("halted_at_iteration_limit", False)
            model = agent.get("model", "?")
            perm_level = agent.get("permission_level", "?")
            cwd = agent.get("cwd", "?")
            write_paths = agent.get("write_paths")
            last_action = agent.get("last_action_at")

            # Format last action time (just HH:MM:SS if today, else date+time)
            if last_action:
                # Just show time portion for readability
                last_action_str = last_action.split("T")[1][:8] if "T" in last_action else last_action
            else:
                last_action_str = "never"

            # Format write paths
            if write_paths is None:
                write_str = "any"
            elif len(write_paths) == 0:
                write_str = "none"
            else:
                # Show just the last component of each path
                write_str = ",".join(p.split("/")[-1] for p in write_paths)

            # Build main line
            status = "HALTED " if halted else ""
            lines.append(
                f"  {status}{agent['agent_id']} ({agent_type})"
            )

            # Build detail line
            details = [
                f"model={model}",
                f"perm={perm_level}",
                f"msgs={agent['message_count']}",
                f"action={last_action_str}",
            ]
            if child_count > 0:
                details.append(f"children={child_count}")
            if parent_id:
                details.append(f"parent={parent_id}")

            lines.append(f"    {', '.join(details)}")
            lines.append(f"    cwd={cwd}, write={write_str}")

        message = "\n".join(lines)

    return CommandOutput.success(
        message=message,
        data={"agents": agents},
    )


async def cmd_create(
    ctx: CommandContext,
    name: str,
    permission: str = "trusted",
    model: str | None = None,
) -> CommandOutput:
    """Create a new agent without switching to it.

    Creates a new agent in the pool with the specified name.
    Does not change the current agent.

    Args:
        ctx: Command context with pool and session_manager.
        name: Name for the new agent.
        permission: Permission level ("sandboxed", "trusted", "yolo").
        model: Model name/alias to use (None for default).

    Returns:
        CommandOutput with created agent info in data field.
    """
    from nexus3.rpc.pool import AgentConfig

    # Validate permission level
    valid_permissions = {"sandboxed", "trusted", "yolo"}
    if permission not in valid_permissions:
        return CommandOutput.error(
            f"Invalid permission level: {permission}. "
            f"Must be one of: {', '.join(sorted(valid_permissions))}"
        )

    # Check if agent already exists
    if name in ctx.pool:
        return CommandOutput.error(f"Agent already exists: {name}")

    try:
        # Create agent with permission preset and optional model
        agent_config = AgentConfig(
            preset=permission,
            model=model,
        )
        agent = await ctx.pool.create(agent_id=name, config=agent_config)
        return CommandOutput.success(
            message=f"Created agent: {agent.agent_id}",
            data={
                "agent_id": agent.agent_id,
                "is_temp": is_temp_agent(agent.agent_id),
                "created_at": agent.created_at.isoformat(),
                "permission": permission,
                "model": model,
            },
        )
    except ValueError as e:
        return CommandOutput.error(str(e))


async def cmd_destroy(ctx: CommandContext, name: str) -> CommandOutput:
    """Remove an agent from the pool.

    Destroys the agent and cleans up its resources.
    Log files are preserved.

    Args:
        ctx: Command context with pool and session_manager.
        name: Name of the agent to destroy.

    Returns:
        CommandOutput indicating success or failure.
    """
    # Check if agent exists
    if name not in ctx.pool:
        return CommandOutput.error(f"Agent not found: {name}")

    # Don't allow destroying current agent in REPL mode
    if ctx.is_repl and ctx.current_agent_id == name:
        return CommandOutput.error(
            "Cannot destroy current agent. Switch to another agent first."
        )

    success = await ctx.pool.destroy(name)
    if success:
        return CommandOutput.success(
            message=f"Destroyed agent: {name}",
            data={"agent_id": name, "destroyed": True},
        )
    else:
        return CommandOutput.error(f"Failed to destroy agent: {name}")


async def cmd_send(
    ctx: CommandContext,
    agent_id: str,
    message: str,
) -> CommandOutput:
    """Send a one-shot message to an agent.

    Sends a message to the specified agent and returns the response.
    This is for quick interactions, not full conversations.

    Args:
        ctx: Command context with pool and session_manager.
        agent_id: ID of the agent to send to.
        message: Message content to send.

    Returns:
        CommandOutput with agent response in data field.
    """
    # Get the agent
    agent = ctx.pool.get(agent_id)
    if agent is None:
        return CommandOutput.error(f"Agent not found: {agent_id}")

    try:
        # Iterate over the send() async generator and collect the response
        response_chunks: list[str] = []
        async for chunk in agent.session.send(message, use_tools=True):
            response_chunks.append(chunk)
        response_content = "".join(response_chunks)

        return CommandOutput.success(
            message=response_content if response_content else "No response",
            data={
                "agent_id": agent_id,
                "content": response_content,
            },
        )
    except Exception as e:
        return CommandOutput.error(f"Error sending to {agent_id}: {e}")


async def cmd_status(
    ctx: CommandContext,
    agent_id: str | None = None,
    show_tools: bool = False,
    show_tokens: bool = False,
) -> CommandOutput:
    """Get agent status information.

    Returns comprehensive status including tokens, model, permissions,
    paths, MCP servers, and optionally full tool list and token breakdown.

    Args:
        ctx: Command context with pool and session_manager.
        agent_id: Agent to get status for. Uses current agent if None.
        show_tools: If True, include full list of available tools.
        show_tokens: If True, include detailed token breakdown.

    Returns:
        CommandOutput with status info in data field.
    """
    from pathlib import Path

    # Resolve agent ID
    effective_id = agent_id or ctx.current_agent_id
    if effective_id is None:
        return CommandOutput.error("No agent specified and no current agent")

    # Get the agent
    agent = ctx.pool.get(effective_id)
    if agent is None:
        return CommandOutput.error(f"Agent not found: {effective_id}")

    # Get token info
    tokens = agent.context.get_token_usage()
    message_count = len(agent.context.messages)

    # Calculate context usage percentage (based on available, not budget, to match is_over_budget())
    total = tokens.get("total", 0)
    budget = tokens.get("budget", 1)
    available = tokens.get("available", budget)
    remaining = tokens.get("remaining", 0)
    context_usage_pct = round((total / available) * 100, 1) if available > 0 else 0

    # Get info from services
    permissions: AgentPermissions | None = None
    model_info: dict | None = None
    cwd: Path | None = None
    allowed_paths: list[Path] | None = None
    mcp_registry = None
    parent_id = None
    children: list[str] = []

    if hasattr(agent, "services") and agent.services:
        permissions = agent.services.get("permissions")
        resolved_model = agent.services.get("model")
        cwd = agent.services.get("cwd")
        allowed_paths = agent.services.get("allowed_paths")
        mcp_registry = agent.services.get("mcp_registry")

        if permissions:
            parent_id = permissions.parent_agent_id
        child_ids: set[str] | None = agent.services.get("child_agent_ids")
        children = list(child_ids) if child_ids else []

        if resolved_model:
            model_info = {
                "model_id": resolved_model.model_id,
                "alias": resolved_model.alias,
                "context_window": resolved_model.context_window,
                "provider": resolved_model.provider_name,
            }

    # Get permission info
    perm_level = None
    preset_name = None
    disabled_tools: list[str] = []
    write_paths: list[str] = []

    if permissions:
        perm_level = permissions.effective_policy.level.name
        preset_name = permissions.base_preset
        # Get disabled tools and write paths from tool permissions
        for tool_name, tool_perm in permissions.tool_permissions.items():
            if not tool_perm.enabled:
                disabled_tools.append(tool_name)
            # Check write tools for per-tool allowed_paths
            if tool_name in ("write_file", "edit_file") and tool_perm.allowed_paths:
                for p in tool_perm.allowed_paths:
                    p_str = str(p)
                    if p_str not in write_paths:
                        write_paths.append(p_str)

    # Get MCP server info
    mcp_servers: list[dict] = []
    if mcp_registry:
        for name in mcp_registry.list_servers(effective_id):
            server = mcp_registry.get(name, effective_id)
            if server:
                mcp_servers.append({
                    "name": name,
                    "tool_count": len(server.skills),
                    "shared": server.shared,
                })

    # Get compaction config from session
    compaction_info: dict | None = None
    if hasattr(agent, "session") and hasattr(agent.session, "_config"):
        comp_cfg = agent.session._config.compaction
        compaction_info = {
            "enabled": comp_cfg.enabled,
            "trigger_threshold": comp_cfg.trigger_threshold,
            "model": comp_cfg.model,
        }

    # Get tool list if requested
    tool_list: list[str] | None = None
    if show_tools and hasattr(agent, "registry"):
        tool_list = sorted(agent.registry.names)

    # Build status data
    status_data = {
        "agent_id": effective_id,
        "is_temp": is_temp_agent(effective_id),
        "created_at": agent.created_at.isoformat(),
        "message_count": message_count,
        "context_usage_pct": context_usage_pct,
        "tokens": tokens if show_tokens else {"total": total, "available": available, "remaining": remaining},
        "model": model_info,
        "permission_level": perm_level,
        "preset": preset_name,
        "cwd": str(cwd) if cwd else None,
        "allowed_paths": [str(p) for p in allowed_paths] if allowed_paths else None,
        "allowed_write_paths": write_paths if write_paths else None,
        "disabled_tools": disabled_tools if disabled_tools else None,
        "mcp_servers": mcp_servers if mcp_servers else None,
        "compaction": compaction_info,
        "parent_agent_id": parent_id,
        "children": children if children else None,
    }

    if tool_list is not None:
        status_data["tools"] = tool_list

    # Format message
    lines = [
        f"Agent: {effective_id}",
        f"  Type: {'temp' if is_temp_agent(effective_id) else 'named'}",
        f"  Created: {agent.created_at.isoformat()}",
    ]

    # Model info
    if model_info:
        alias_str = f" ({model_info['alias']})" if model_info.get("alias") else ""
        provider_str = f" via {model_info['provider']}" if model_info.get("provider") else ""
        lines.append(f"  Model: {model_info['model_id']}{alias_str}{provider_str}")

    # Permission info
    if perm_level:
        preset_str = f" (preset: {preset_name})" if preset_name else ""
        lines.append(f"  Permissions: {perm_level}{preset_str}")

    # Context usage (shows available, not full budget, to match is_over_budget threshold)
    lines.append(f"  Context: {total:,} / {available:,} tokens ({context_usage_pct}%) - {remaining:,} remaining")
    lines.append(f"  Messages: {message_count}")

    # Paths
    if cwd:
        lines.append(f"  CWD: {cwd}")
    if write_paths:
        lines.append(f"  Write paths: {', '.join(write_paths)}")

    # Disabled tools
    if disabled_tools:
        lines.append(f"  Disabled tools: {', '.join(sorted(disabled_tools))}")

    # MCP servers
    if mcp_servers:
        mcp_str = ", ".join(f"{s['name']} ({s['tool_count']} tools)" for s in mcp_servers)
        lines.append(f"  MCP servers: {mcp_str}")

    # Compaction
    if compaction_info and compaction_info["enabled"]:
        lines.append(f"  Compaction: enabled (threshold: {compaction_info['trigger_threshold']})")

    # Hierarchy
    if parent_id:
        lines.append(f"  Parent: {parent_id}")
    if children:
        lines.append(f"  Children: {', '.join(children)}")

    # Detailed token breakdown (if requested)
    if show_tokens:
        lines.append("  Token breakdown:")
        lines.append(f"    System: {tokens.get('system', 0):,}")
        lines.append(f"    Tools: {tokens.get('tools', 0):,}")
        lines.append(f"    Messages: {tokens.get('messages', 0):,}")
        lines.append(f"    Available: {tokens.get('available', 0):,}")

    # Tool list (if requested)
    if tool_list:
        lines.append(f"  Tools ({len(tool_list)}):")
        # Group into rows of 4 for readability
        for i in range(0, len(tool_list), 4):
            chunk = tool_list[i:i+4]
            lines.append(f"    {', '.join(chunk)}")

    message = "\n".join(lines)
    return CommandOutput.success(message=message, data=status_data)


async def cmd_cancel(
    ctx: CommandContext,
    agent_id: str | None = None,
    request_id: str | None = None,
) -> CommandOutput:
    """Cancel an in-progress request.

    Cancels the specified request or the current request if no ID given.

    Args:
        ctx: Command context with pool and session_manager.
        agent_id: Agent to cancel request on. Uses current agent if None.
        request_id: Request ID to cancel. Cancels current if None.

    Returns:
        CommandOutput indicating success or failure.
    """
    # Resolve agent ID
    effective_id = agent_id or ctx.current_agent_id
    if effective_id is None:
        return CommandOutput.error("No agent specified and no current agent")

    # Get the agent
    agent = ctx.pool.get(effective_id)
    if agent is None:
        return CommandOutput.error(f"Agent not found: {effective_id}")

    # Parse request_id if provided
    rid: int | None = None
    if request_id is not None:
        try:
            rid = int(request_id)
        except ValueError:
            return CommandOutput.error(
                f"Invalid request_id: {request_id} (must be an integer)"
            )

    # Cancel via session
    try:
        agent.session.cancel()
        return CommandOutput.success(
            message=f"Cancel requested for agent: {effective_id}",
            data={
                "agent_id": effective_id,
                "request_id": rid,
                "cancelled": True,
            },
        )
    except Exception as e:
        return CommandOutput.error(f"Failed to cancel: {e}")


async def get_permission_data(agent: object) -> tuple[str, str | None, list[str]]:
    """Extract permission info from agent for serialization.

    Returns:
        Tuple of (permission_level, permission_preset, disabled_tools)
    """
    perms = agent.services.get("permissions")  # type: ignore[union-attr]
    if perms:
        level = perms.effective_policy.level.value
        preset = perms.base_preset
        disabled = [
            name for name, tp in perms.tool_permissions.items()
            if not tp.enabled
        ]
    else:
        level = "trusted"
        preset = None
        disabled = []
    return level, preset, disabled


async def cmd_save(
    ctx: CommandContext,
    name: str | None = None,
) -> CommandOutput:
    """Save the current session to disk.

    Saves the current agent's session. If the agent is temp and no name
    is provided, prompts for a name (in REPL mode) or uses the temp ID.

    Args:
        ctx: Command context with pool and session_manager.
        name: Name to save as. Uses current agent ID if None.

    Returns:
        CommandOutput with saved session path in data field.
    """
    # Must have a current agent
    if ctx.current_agent_id is None:
        return CommandOutput.error("No current agent to save")

    # Get the agent
    agent = ctx.pool.get(ctx.current_agent_id)
    if agent is None:
        return CommandOutput.error(f"Agent not found: {ctx.current_agent_id}")

    # Determine save name
    save_name = name or ctx.current_agent_id

    # Don't allow saving with temp names to sessions folder
    if is_temp_agent(save_name):
        return CommandOutput.error(
            f"Cannot save with temp name '{save_name}'. "
            "Provide a name: /save myname"
        )

    # FIXED: Extract permission data correctly
    perm_level, perm_preset, disabled_tools = await get_permission_data(agent)

    # Get model alias for persistence
    try:
        model = agent.services.get("model")
        model_alias = model.alias if model else None
    except Exception:
        model_alias = None

    # Get clipboard entries for persistence
    clipboard_entries: list[dict[str, Any]] = []
    try:
        clipboard_manager = agent.services.get("clipboard_manager")
        if clipboard_manager:
            clipboard_entries = serialize_clipboard_entries(
                clipboard_manager.get_agent_entries()
            )
    except Exception:
        pass

    # Create saved session from agent state
    saved = serialize_session(
        agent_id=save_name,
        messages=agent.context.messages,
        system_prompt=agent.context.system_prompt or "",
        system_prompt_path=ctx.pool.system_prompt_path,
        working_directory=str(agent.services.get_cwd()),
        permission_level=perm_level,
        token_usage=agent.context.get_token_usage(),
        provenance="user",
        created_at=agent.created_at,
        permission_preset=perm_preset,
        disabled_tools=disabled_tools,
        model_alias=model_alias,
        clipboard_agent_entries=clipboard_entries,
    )

    try:
        path = ctx.session_manager.save_session(saved)
        return CommandOutput.success(
            message=f"Saved session: {save_name}",
            data={
                "name": save_name,
                "path": str(path),
                "message_count": len(saved.messages),
            },
        )
    except SessionManagerError as e:
        return CommandOutput.error(f"Failed to save: {e}")


async def cmd_clone(
    ctx: CommandContext,
    src: str,
    dest: str,
) -> CommandOutput:
    """Clone an agent or saved session.

    Clones an active agent to a new active agent, or a saved session
    to a new saved session.

    Args:
        ctx: Command context with pool and session_manager.
        src: Source agent/session name.
        dest: Destination agent/session name.

    Returns:
        CommandOutput with cloned agent/session info.
    """
    # Check if src is an active agent
    src_agent = ctx.pool.get(src)

    if src_agent is not None:
        # Clone active agent to new active agent
        if dest in ctx.pool:
            return CommandOutput.error(f"Agent already exists: {dest}")

        # Create new agent with same system prompt
        try:
            new_agent = await ctx.pool.create(agent_id=dest)

            # Copy context (messages and system prompt)
            for msg in src_agent.context.messages:
                new_agent.context.add_message(msg)
            new_agent.context.set_system_prompt(src_agent.context.system_prompt or "")

            return CommandOutput.success(
                message=f"Cloned agent {src} -> {dest}",
                data={
                    "src": src,
                    "dest": dest,
                    "type": "active",
                    "message_count": len(new_agent.context.messages),
                },
            )
        except ValueError as e:
            return CommandOutput.error(f"Failed to clone agent: {e}")

    # Try to clone saved session
    try:
        path = ctx.session_manager.clone_session(src, dest)
        return CommandOutput.success(
            message=f"Cloned session {src} -> {dest}",
            data={
                "src": src,
                "dest": dest,
                "type": "saved",
                "path": str(path),
            },
        )
    except SessionNotFoundError:
        return CommandOutput.error(f"Agent or session not found: {src}")
    except SessionManagerError as e:
        return CommandOutput.error(f"Failed to clone: {e}")


async def cmd_rename(
    ctx: CommandContext,
    old: str,
    new: str,
) -> CommandOutput:
    """Rename an agent or saved session.

    Renames an active agent in the pool, or a saved session on disk.

    Args:
        ctx: Command context with pool and session_manager.
        old: Current name.
        new: New name.

    Returns:
        CommandOutput indicating success or failure.
    """
    # Check if old is an active agent
    old_agent = ctx.pool.get(old)

    if old_agent is not None:
        # Can't rename to existing name
        if new in ctx.pool:
            return CommandOutput.error(f"Agent already exists: {new}")

        # For active agents, we need to:
        # 1. Create new agent with same state
        # 2. Destroy old agent
        try:
            new_agent = await ctx.pool.create(agent_id=new)

            # Copy state
            for msg in old_agent.context.messages:
                new_agent.context.add_message(msg)
            new_agent.context.set_system_prompt(old_agent.context.system_prompt or "")

            # Destroy old
            await ctx.pool.destroy(old)

            # Update current agent if we renamed it
            new_current = new if ctx.current_agent_id == old else ctx.current_agent_id

            return CommandOutput.success(
                message=f"Renamed agent {old} -> {new}",
                data={
                    "old": old,
                    "new": new,
                    "type": "active",
                    "new_current_agent": new_current,
                },
            )
        except ValueError as e:
            return CommandOutput.error(f"Failed to rename agent: {e}")

    # Try to rename saved session
    try:
        path = ctx.session_manager.rename_session(old, new)
        return CommandOutput.success(
            message=f"Renamed session {old} -> {new}",
            data={
                "old": old,
                "new": new,
                "type": "saved",
                "path": str(path),
            },
        )
    except SessionNotFoundError:
        return CommandOutput.error(f"Agent or session not found: {old}")
    except SessionManagerError as e:
        return CommandOutput.error(f"Failed to rename: {e}")


async def cmd_delete(ctx: CommandContext, name: str) -> CommandOutput:
    """Delete a saved session from disk.

    Removes a saved session file. Does not affect active agents.

    Args:
        ctx: Command context with pool and session_manager.
        name: Name of the session to delete.

    Returns:
        CommandOutput indicating success or failure.
    """
    # Don't allow deleting temp names (they're not saved anyway)
    if is_temp_agent(name):
        return CommandOutput.error(
            f"'{name}' is a temp agent name. "
            "Use /destroy to remove active temp agents."
        )

    deleted = ctx.session_manager.delete_session(name)
    if deleted:
        return CommandOutput.success(
            message=f"Deleted session: {name}",
            data={"name": name, "deleted": True},
        )
    else:
        return CommandOutput.error(f"Session not found: {name}")


async def cmd_shutdown(ctx: CommandContext) -> CommandOutput:
    """Request server shutdown.

    Signals that the server should shut down gracefully.
    All agents will be stopped.

    Args:
        ctx: Command context with pool and session_manager.

    Returns:
        CommandOutput with QUIT result.
    """
    # Mark all agents for shutdown
    for agent_info in ctx.pool.list():
        agent = ctx.pool.get(agent_info["agent_id"])
        if agent:
            agent.dispatcher.request_shutdown()

    return CommandOutput(
        result=CommandOutput.quit().result,
        message="Shutdown requested",
        data={"shutdown": True},
    )
