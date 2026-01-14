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

import os
from typing import TYPE_CHECKING

from nexus3.commands.protocol import CommandContext, CommandOutput
from nexus3.core.permissions import AgentPermissions
from nexus3.rpc.pool import is_temp_agent
from nexus3.session.persistence import serialize_session
from nexus3.session.session_manager import SessionManagerError, SessionNotFoundError

if TYPE_CHECKING:
    pass


async def cmd_list(ctx: CommandContext) -> CommandOutput:
    """List all agents in the pool.

    Returns information about all active agents including their ID,
    type (temp/named), creation time, message count, and child count.

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

            # Build info parts
            info_parts = [f"{agent['message_count']} msgs"]
            if child_count > 0:
                info_parts.append(f"{child_count} children")
            if parent_id:
                info_parts.append(f"parent: {parent_id}")

            lines.append(
                f"  {agent['agent_id']} ({agent_type}, {', '.join(info_parts)})"
            )
        message = "\n".join(lines)

    return CommandOutput.success(
        message=message,
        data={"agents": agents},
    )


async def cmd_create(
    ctx: CommandContext,
    name: str,
    permission: str = "trusted",
) -> CommandOutput:
    """Create a new agent without switching to it.

    Creates a new agent in the pool with the specified name.
    Does not change the current agent.

    Args:
        ctx: Command context with pool and session_manager.
        name: Name for the new agent.
        permission: Permission level ("sandboxed", "trusted", "yolo", "worker").

    Returns:
        CommandOutput with created agent info in data field.
    """
    # Validate permission level
    valid_permissions = {"sandboxed", "trusted", "yolo", "worker"}
    if permission not in valid_permissions:
        return CommandOutput.error(
            f"Invalid permission level: {permission}. "
            f"Must be one of: {', '.join(sorted(valid_permissions))}"
        )

    # Check if agent already exists
    if name in ctx.pool:
        return CommandOutput.error(f"Agent already exists: {name}")

    try:
        agent = await ctx.pool.create(agent_id=name)
        return CommandOutput.success(
            message=f"Created agent: {agent.agent_id}",
            data={
                "agent_id": agent.agent_id,
                "is_temp": is_temp_agent(agent.agent_id),
                "created_at": agent.created_at.isoformat(),
                "permission": permission,
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
) -> CommandOutput:
    """Get agent status information.

    Returns token usage and context information for the agent.

    Args:
        ctx: Command context with pool and session_manager.
        agent_id: Agent to get status for. Uses current agent if None.

    Returns:
        CommandOutput with status info in data field.
    """
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

    # Get parent/child info from services (if available)
    parent_id = None
    children: list[str] = []
    if hasattr(agent, "services") and agent.services:
        permissions: AgentPermissions | None = agent.services.get("permissions")
        parent_id = permissions.parent_agent_id if permissions else None
        child_ids: set[str] | None = agent.services.get("child_agent_ids")
        children = list(child_ids) if child_ids else []

    status_data = {
        "agent_id": effective_id,
        "is_temp": is_temp_agent(effective_id),
        "created_at": agent.created_at.isoformat(),
        "message_count": message_count,
        "tokens": tokens,
        "parent_agent_id": parent_id,
        "children": children,
    }

    # Format message
    lines = [
        f"Agent: {effective_id}",
        f"  Type: {'temp' if is_temp_agent(effective_id) else 'named'}",
        f"  Created: {agent.created_at.isoformat()}",
        f"  Messages: {message_count}",
        f"  Tokens: {tokens.get('total', 0)} total",
    ]
    if parent_id:
        lines.append(f"  Parent: {parent_id}")
    if children:
        lines.append(f"  Children: {', '.join(children)}")
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

    # Get permission data from agent
    permissions: AgentPermissions | None = agent.services.get("permissions")
    if permissions:
        perm_level = permissions.level.value
        perm_preset = permissions.preset_name
        disabled_tools = permissions.disabled_tools
    else:
        perm_level = "trusted"
        perm_preset = None
        disabled_tools = []

    # Create saved session from agent state
    saved = serialize_session(
        agent_id=save_name,
        messages=agent.context.messages,
        system_prompt=agent.context.system_prompt or "",
        system_prompt_path=ctx.pool.system_prompt_path,
        working_directory=os.getcwd(),
        permission_level=perm_level,
        token_usage=agent.context.get_token_usage(),
        provenance="user",
        created_at=agent.created_at,
        permission_preset=perm_preset,
        disabled_tools=disabled_tools,
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
