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

from pathlib import Path
from typing import TYPE_CHECKING, Any

from nexus3.cli.whisper import WhisperMode
from nexus3.commands.protocol import CommandContext, CommandOutput, CommandResult
from nexus3.core.secure_io import SymlinkError, check_no_symlink
from nexus3.core.permissions import (
    AgentPermissions,
    ToolPermission,
    get_builtin_presets,
    resolve_preset,
)
from nexus3.core.validation import ValidationError, validate_agent_id
from nexus3.display import get_console
from nexus3.rpc.pool import is_temp_agent

if TYPE_CHECKING:
    from nexus3.mcp.registry import MCPServerRegistry
    from nexus3.rpc.pool import Agent, AgentPool, SharedComponents


async def _refresh_agent_tools(
    agent: Agent,
    mcp_registry: MCPServerRegistry,
    shared: SharedComponents,
) -> None:
    """Refresh an agent's tool definitions after MCP connection changes.

    Rebuilds the tool definitions list to include/exclude MCP tools
    based on current MCP registry state and agent permissions.
    Only includes MCP tools from servers visible to this agent.
    """
    from nexus3.mcp.permissions import can_use_mcp

    permissions = agent.services.get("permissions")
    if permissions is None:
        return

    # Get base tools from skill registry
    tool_defs = agent.registry.get_definitions_for_permissions(permissions)

    # Add MCP tools if agent has permission (only from visible servers)
    if can_use_mcp(permissions):
        for mcp_skill in await mcp_registry.get_all_skills(agent_id=agent.agent_id):
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


async def _refresh_all_other_agents_tools(
    current_agent_id: str,
    pool: AgentPool,
    mcp_registry: MCPServerRegistry,
    shared: SharedComponents,
) -> None:
    """Refresh tool definitions for all agents except the current one.

    Called after a shared MCP connection is made/removed so other agents
    pick up the new tools.
    """
    for agent in pool._agents.values():
        if agent.agent_id != current_agent_id:
            await _refresh_agent_tools(agent, mcp_registry, shared)


# Help text for REPL commands
HELP_TEXT = """
NEXUS3 REPL Commands
====================

Agent Management:
  /agent              Show current agent's detailed status (model, tokens, etc.)
  /agent <name>       Switch to agent (prompts to create if doesn't exist)
  /agent <name> --yolo|--trusted|--sandboxed
                      Create agent with permission level and switch to it
  /agent <name> --model <alias>
                      Create agent with specific model (use with preset flags)

  /whisper <agent>    Enter whisper mode - redirect all input to target agent
  /over               Exit whisper mode, return to original agent

  /list               List all active agents
  /create <name> [--preset] [--model <alias>]
                      Create agent without switching
  /destroy <name>     Remove active agent from pool
  /send <agent> <msg> One-shot message to another agent
  /status [agent] [--tools] [--tokens] [-a]  Get agent status (-a: all details)
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
  /mcp connect <name> [--allow-all|--per-tool] [--shared|--private]
                      Connect to a configured MCP server
  /mcp disconnect <name>  Disconnect from an MCP server
  /mcp tools [server] List available MCP tools
  /mcp resources [server]  List available resources
  /mcp prompts [server]    List available prompts
  /mcp retry <name>   Retry listing tools from a server

Initialization:
  /init               Create .nexus3/ in current directory with templates
  /init --force       Overwrite existing config files
  /init --global      Initialize ~/.nexus3/ instead of local

REPL Control:
  /help               Show this help message
  /clear              Clear the display (preserves context)
  /quit, /exit, /q    Exit the REPL

Keyboard Shortcuts:
  ESC                 Cancel in-progress request
  Ctrl+C              Interrupt current input
  Ctrl+D              Exit REPL

Detailed help: /help <command> or /<command> --help
""".strip()


# Per-command detailed help text
# Both /help <cmd> and /<cmd> --help read from this dict
COMMAND_HELP: dict[str, str] = {
    "agent": """/agent [name] [--yolo|-y] [--trusted|-t] [--sandboxed|-s] [--model|-m <alias>]

Show current agent status, switch to another agent, or create and switch to a new agent.

Arguments:
  name        Optional. Agent name to switch to or create.

Flags:
  --yolo, -y       Create with YOLO permission level (no confirmations)
  --trusted, -t    Create with TRUSTED permission level (confirms destructive)
  --sandboxed, -s  Create with SANDBOXED permission level (restricted to CWD)
  --model, -m      Specify model alias or ID for new agent

Behavior:
  /agent                Show current agent's detailed status
  /agent foo            Switch to "foo" (prompts to create if doesn't exist)
  /agent foo --trusted  Create with preset and switch

Examples:
  /agent                          # Show current agent status
  /agent analyzer                 # Switch to "analyzer"
  /agent worker --sandboxed       # Create sandboxed agent and switch
  /agent researcher -t -m gpt     # Create trusted agent with GPT model""",

    "whisper": """/whisper <agent>

Enter whisper mode - redirect all subsequent input to the target agent until /over.

Arguments:
  agent       Required. Agent ID to whisper to. Must exist in the pool.

Examples:
  /whisper worker-1               # Start whispering to worker-1

After entering whisper mode:
  worker-1> analyze this code     # Goes to worker-1
  worker-1> /over                 # Exit whisper mode""",

    "over": """/over

Exit whisper mode and return to the original agent.

Arguments: None

Examples:
  worker-1> /over                 # Exit whisper mode, back to original agent""",

    "list": """/list

List all active agents in the pool with summary information.

Arguments: None

Output includes:
  - Agent ID and type (temp vs named)
  - Model being used
  - Permission level
  - Message count
  - Working directory

Examples:
  /list                           # Show all active agents""",

    "create": """/create <name> [--yolo|-y] [--trusted|-t] [--sandboxed|-s] [--model|-m <alias>]

Create a new agent without switching to it.

Arguments:
  name        Required. Unique agent ID. Cannot already exist.

Flags:
  --yolo, -y       YOLO permission level
  --trusted, -t    TRUSTED permission level (default)
  --sandboxed, -s  SANDBOXED permission level
  --model, -m      Model alias or ID

Examples:
  /create worker-1                # Create with default (trusted) preset
  /create analyzer --sandboxed    # Create sandboxed agent
  /create helper --model haiku    # Create with specific model""",

    "destroy": """/destroy <name>

Remove an agent from the pool. Log files are preserved on disk.

Arguments:
  name        Required. Agent ID to destroy.

Examples:
  /destroy worker-1               # Remove worker-1 from pool

Notes:
  - Cannot destroy your current agent (switch to another first)
  - Log files in .nexus3/logs/<agent_id>/ are preserved
  - Saved sessions are NOT affected""",

    "send": """/send <agent> <message>

Send a one-shot message to another agent and display the response.

Arguments:
  agent       Required. Target agent ID.
  message     Required. Message content to send.

Examples:
  /send worker-1 summarize the file you just read
  /send analyzer what patterns did you find?

Notes:
  - Synchronous - waits for the full response
  - For ongoing conversations, use /whisper or /agent""",

    "status": """/status [agent] [--tools] [--tokens] [-a|--all]

Get comprehensive status information about an agent.

Arguments:
  agent       Optional. Agent ID to check. Defaults to current agent.

Flags:
  --tools     Include full list of available tools
  --tokens    Include detailed token breakdown
  -a, --all   Include both tools and tokens

Examples:
  /status                         # Current agent, basic info
  /status worker-1                # Check another agent
  /status --tokens                # Current agent with token breakdown
  /status -a                      # Everything""",

    "cancel": """/cancel [agent]

Cancel an in-progress request. Also works via ESC key during streaming.

Arguments:
  agent       Optional. Agent ID. Defaults to current agent.

Examples:
  /cancel                         # Cancel current agent's request
  /cancel worker-1                # Cancel another agent's request""",

    "save": """/save [name]

Save the current agent's session to disk for later restoration.

Arguments:
  name        Optional. Name to save as. Defaults to current agent ID.

What gets saved:
  - Full message history
  - System prompt content and path
  - Working directory
  - Permission preset and disabled tools
  - Model alias
  - Token usage snapshot

Examples:
  /save                           # Save with current agent name
  /save my-project                # Save as "my-project"

Notes:
  - Cannot save temp names (.1, .2) - must provide a real name
  - Saves to ~/.nexus3/sessions/{name}.json
  - Session is auto-saved on exit for --resume""",

    "clone": """/clone <src> <dest>

Clone an active agent or saved session to a new name.

Arguments:
  src         Required. Source agent ID or saved session name.
  dest        Required. Destination name. Must not already exist.

Examples:
  /clone main backup              # Clone active agent "main" to "backup"
  /clone my-project experiment    # Clone saved session""",

    "rename": """/rename <old> <new>

Rename an active agent or saved session.

Arguments:
  old         Required. Current name.
  new         Required. New name. Must not already exist.

Examples:
  /rename .1 my-project           # Give a temp session a real name
  /rename old-name new-name       # Rename a saved session""",

    "delete": """/delete <name>

Delete a saved session from disk. Does NOT affect active agents.

Arguments:
  name        Required. Saved session name to delete.

Examples:
  /delete old-project             # Remove saved session

Notes:
  - Only deletes from ~/.nexus3/sessions/, not active agents
  - Use /destroy to remove active agents
  - No confirmation prompt - deletion is immediate""",

    "cwd": """/cwd [path]

Show or change the working directory for the current agent.

Arguments:
  path        Optional. New working directory. If omitted, shows current.

Examples:
  /cwd                            # Show current working directory
  /cwd /home/user/project         # Change to absolute path
  /cwd ~/repos/myapp              # Tilde expansion supported
  /cwd ../other-project           # Relative paths work too

Notes:
  - Each agent has its own CWD (not shared)
  - Sandboxed agents can only change within allowed paths""",

    "model": """/model [name]

Show current model or switch to a different model.

Arguments:
  name        Optional. Model alias or full ID. If omitted, shows current.

Examples:
  /model                          # Show current model info
  /model haiku                    # Switch to haiku (by alias)
  /model gpt                      # Switch to GPT (by alias)

Notes:
  - Model aliases are defined in config.json
  - If context exceeds new model's limit, /compact first
  - Model choice is persisted when you /save""",

    "permissions": """/permissions [preset] [--disable <tool>] [--enable <tool>] [--list-tools]

Show or modify permission level for the current agent.

Arguments:
  preset      Optional. Change to this preset (yolo/trusted/sandboxed).

Flags:
  --disable <tool>   Disable a specific tool
  --enable <tool>    Re-enable a previously disabled tool
  --list-tools       Show all tools with enabled/disabled status

Presets:
  yolo        Full access, no confirmations (REPL-only)
  trusted     Confirmations for destructive actions
  sandboxed   Restricted to CWD, no network, no agent management

Examples:
  /permissions                    # Show current permissions
  /permissions trusted            # Switch to trusted preset
  /permissions --disable shell_UNSAFE
  /permissions --list-tools""",

    "prompt": """/prompt [file]

Show or set the system prompt for the current agent.

Arguments:
  file        Optional. Path to prompt file. If omitted, shows preview.

Examples:
  /prompt                         # Show current system prompt (preview)
  /prompt ~/prompts/coding.md     # Load prompt from file
  /prompt ./NEXUS.md              # Load project-specific prompt""",

    "compact": """/compact

Force context compaction, summarizing older messages to reclaim token space.

Arguments: None

Examples:
  /compact                        # Force compaction now

Output:
  Compacted: 85,000 -> 25,000 tokens

Notes:
  - Uses a cheaper/faster model for summarization
  - Preserves recent messages verbatim
  - Automatic compaction triggers at 90% capacity
  - System prompt reloads during compaction (picks up NEXUS.md changes)""",

    "mcp": """/mcp
/mcp connect <name> [--allow-all|--per-tool] [--shared|--private]
/mcp disconnect <name>
/mcp tools [server]
/mcp resources [server]
/mcp prompts [server]
/mcp retry <name>

Manage Model Context Protocol (MCP) server connections for external tools.

Subcommands:
  /mcp                    List configured and connected servers
  /mcp connect <name>     Connect to a configured MCP server
  /mcp disconnect <name>  Disconnect from server
  /mcp tools [server]     List available MCP tools
  /mcp resources [server] List available resources
  /mcp prompts [server]   List available prompts
  /mcp retry <name>       Retry listing tools from a server

Connect flags:
  --allow-all   Skip consent prompt, allow all tools
  --per-tool    Skip consent prompt, require per-tool confirmation
  --shared      Skip sharing prompt, share with all agents
  --private     Skip sharing prompt, keep private to this agent

Examples:
  /mcp                                    # List servers
  /mcp connect filesystem                 # Interactive prompts
  /mcp connect github --allow-all --shared
  /mcp disconnect filesystem
  /mcp tools                              # List all MCP tools
  /mcp resources                          # List all resources
  /mcp prompts filesystem                 # List prompts from filesystem server
  /mcp retry filesystem                   # Retry failed server""",

    "init": """/init [--force|-f] [--global|-g]

Initialize NEXUS3 configuration directory with templates.

Flags:
  --force, -f   Overwrite existing configuration files
  --global, -g  Initialize ~/.nexus3/ instead of local ./.nexus3/

Examples:
  /init                           # Create ./.nexus3/ with templates
  /init --force                   # Overwrite existing local config
  /init --global                  # Initialize ~/.nexus3/

Created files (local):
  ./.nexus3/
  ├── NEXUS.md       # Project-specific system prompt
  ├── config.json    # Project configuration
  └── mcp.json       # Project MCP servers""",

    "help": """/help [command]

Display help information.

Arguments:
  command     Optional. Specific command to get help for.

Examples:
  /help                           # Show all commands overview
  /help save                      # Detailed help for /save
  /save --help                    # Same as /help save""",

    "clear": """/clear

Clear the terminal display. Conversation context is preserved.

Arguments: None

Examples:
  /clear                          # Clear screen""",

    "quit": """/quit
/exit
/q

Exit the REPL. All three forms are equivalent.

Arguments: None

Notes:
  - Current session is auto-saved to ~/.nexus3/last-session.json
  - Active agents are destroyed (but saved sessions persist)
  - Ctrl+D also exits""",
}

# Aliases map to canonical command names
COMMAND_ALIASES: dict[str, str] = {
    "exit": "quit",
    "q": "quit",
}


def get_command_help(cmd_name: str) -> str | None:
    """Get detailed help text for a command.

    Args:
        cmd_name: Command name (with or without leading /).

    Returns:
        Help text for the command, or None if command unknown.
    """
    # Strip leading slash if present
    name = cmd_name.lstrip("/").lower()

    # Resolve aliases
    canonical = COMMAND_ALIASES.get(name, name)

    return COMMAND_HELP.get(canonical)


async def cmd_agent(
    ctx: CommandContext,
    args: str | None = None,
) -> CommandOutput:
    """Handle /agent command - show status, switch, or create+switch.

    Behavior:
    - /agent           Show current agent detailed status
    - /agent foo       Switch to foo, prompt to create if doesn't exist
    - /agent foo --yolo Create with permission level and switch
    - /agent foo --model gemini  Create with specific model

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
    try:
        agent_name = validate_agent_id(parts[0])
    except ValidationError as e:
        return CommandOutput.error(f"Invalid agent name: {e}")

    # Parse flags - strict validation (reject unknown flags)
    permission: str | None = None
    model: str | None = None
    valid_flags = {
        "--yolo", "-y", "--trusted", "-t", "--sandboxed", "-s",
        "--model", "-m",
    }
    i = 1
    while i < len(parts):
        part = parts[i]
        part_lower = part.lower()

        if part_lower in ("--yolo", "-y"):
            permission = "yolo"
        elif part_lower in ("--trusted", "-t"):
            permission = "trusted"
        elif part_lower in ("--sandboxed", "-s"):
            permission = "sandboxed"
        elif part_lower in ("--model", "-m"):
            if i + 1 >= len(parts):
                return CommandOutput.error(
                    f"Flag {part} requires a value.\n"
                    f"Usage: /agent <name> --model <model_alias>"
                )
            model = parts[i + 1]
            i += 1  # Skip the model value
        elif part_lower.startswith("--model="):
            model = part.split("=", 1)[1]
            if not model:
                return CommandOutput.error(
                    "Flag --model= requires a value.\n"
                    "Usage: /agent <name> --model=<model_alias>"
                )
        elif part_lower.startswith("-m="):
            model = part.split("=", 1)[1]
            if not model:
                return CommandOutput.error(
                    "Flag -m= requires a value.\n"
                    "Usage: /agent <name> -m=<model_alias>"
                )
        elif part.startswith("-"):
            # Unknown flag - reject with helpful error
            return CommandOutput.error(
                f"Unknown flag: {part}\n"
                f"Valid flags: --yolo/-y, --trusted/-t, --sandboxed/-s, --model/-m <alias>\n"
                f"Usage: /agent <name> [--preset] [--model <alias>]"
            )
        else:
            # Unknown positional argument after agent name
            return CommandOutput.error(
                f"Unexpected argument: {part}\n"
                f"Usage: /agent <name> [--yolo|--trusted|--sandboxed] [--model <alias>]"
            )
        i += 1

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
    flags = []
    if permission:
        flags.append(f"--{permission}")
    if model:
        flags.append(f"--model {model}")
    flags_str = f" with {' '.join(flags)}" if flags else ""
    return CommandOutput(
        result=CommandResult.ERROR,
        message=f"Agent '{agent_name}' doesn't exist. Create it{flags_str}? (y/n)",
        data={
            "action": "prompt_create",
            "agent_name": agent_name,
            "permission": permission or "trusted",
            "model": model,
        },
    )


async def _show_agent_status(ctx: CommandContext) -> CommandOutput:
    """Show detailed status of current agent.

    Args:
        ctx: Command context with pool access.

    Returns:
        CommandOutput with agent status information.
    """
    from nexus3.config.schema import ResolvedModel

    if ctx.current_agent_id is None:
        return CommandOutput.error("No current agent")

    agent = ctx.pool.get(ctx.current_agent_id)
    if agent is None:
        return CommandOutput.error(f"Agent not found: {ctx.current_agent_id}")

    # Gather detailed status info
    tokens = agent.context.get_token_usage()
    message_count = len(agent.context.messages)
    agent_type = "temp" if is_temp_agent(agent.agent_id) else "named"

    # Get model info
    current_model: ResolvedModel | None = agent.services.get("model")
    if current_model:
        model_display = current_model.alias or current_model.model_id
        model_id = current_model.model_id
        context_window = current_model.context_window
    else:
        # Fall back to config default
        config = getattr(getattr(ctx.pool, "_shared", None), "config", None)
        if config:
            default_model = config.resolve_model()
            model_display = f"{default_model.alias or default_model.model_id} (default)"
            model_id = default_model.model_id
            context_window = default_model.context_window
        else:
            model_display = "unknown"
            model_id = "unknown"
            context_window = tokens.get("budget", 0)

    # Format detailed output
    lines = [
        f"Agent: {agent.agent_id}",
        f"  Type: {agent_type}",
        f"  Model: {model_display}",
        f"    ID: {model_id}",
        f"    Context: {context_window:,} tokens",
        f"  Created: {agent.created_at.isoformat()}",
        f"  Messages: {message_count}",
        "  Tokens:",
        f"    Total: {tokens.get('total', 0):,}",
        f"    Available: {tokens.get('available', 0):,}",
        f"    Remaining: {tokens.get('remaining', 0):,}",
        f"  System Prompt: {len(agent.context.system_prompt or ''):,} chars",
    ]

    return CommandOutput.success(
        message="\n".join(lines),
        data={
            "agent_id": agent.agent_id,
            "type": agent_type,
            "model_alias": current_model.alias if current_model else None,
            "model_id": model_id,
            "context_window": context_window,
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

    The working directory is stored per-agent, not globally.
    This ensures agent isolation in multi-agent scenarios.

    Args:
        ctx: Command context with pool access.
        path: New working directory path, or None to show current.

    Returns:
        CommandOutput with current/new working directory.
    """
    if ctx.current_agent_id is None:
        return CommandOutput.error("No current agent")

    agent = ctx.pool.get(ctx.current_agent_id)
    if agent is None:
        return CommandOutput.error(f"Agent not found: {ctx.current_agent_id}")

    if path is None:
        # Show current working directory for THIS agent
        cwd = agent.services.get_cwd()
        return CommandOutput.success(
            message=f"Working directory: {cwd}",
            data={"cwd": str(cwd)},
        )

    # Set new working directory for THIS agent only
    try:
        expanded_path = Path(path).expanduser()

        # Check for symlink attack before resolving
        try:
            check_no_symlink(expanded_path)
        except SymlinkError:
            return CommandOutput.error(f"Path is a symlink: {expanded_path}")

        new_path = expanded_path.resolve()
        if not new_path.exists():
            return CommandOutput.error(f"Directory does not exist: {path}")
        if not new_path.is_dir():
            return CommandOutput.error(f"Not a directory: {path}")

        # Validate against agent's allowed_paths if sandboxed
        permissions: AgentPermissions | None = agent.services.get("permissions")
        if permissions and permissions.effective_policy.allowed_paths:
            from nexus3.core.paths import validate_path
            from nexus3.core.errors import PathSecurityError
            try:
                validate_path(new_path, allowed_paths=permissions.effective_policy.allowed_paths)
            except PathSecurityError as e:
                return CommandOutput.error(f"Directory outside sandbox: {e}")

        # Update ONLY this agent's cwd
        agent.services.register("cwd", new_path)

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

    builtin = get_builtin_presets()
    all_presets = dict(builtin)
    if custom_presets:
        all_presets.update(custom_presets)

    if preset_name not in all_presets:
        valid = ", ".join(all_presets.keys())
        return CommandOutput.error(
            f"Unknown preset: {preset_name}. Valid: {valid}"
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
        expanded_path = Path(file).expanduser()

        # Check for symlink attack before resolving
        try:
            check_no_symlink(expanded_path)
        except SymlinkError:
            return CommandOutput.error(f"Path is a symlink: {expanded_path}")

        prompt_path = expanded_path.resolve()
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


async def cmd_help(ctx: CommandContext, args: str | None = None) -> CommandOutput:
    """Display help text for REPL commands.

    If a command name is provided, shows detailed help for that command.
    Otherwise shows the main help overview.

    Args:
        ctx: Command context (unused but consistent with other commands).
        args: Optional command name to get detailed help for.

    Returns:
        CommandOutput with help text.
    """
    if args and args.strip():
        # Get help for specific command
        cmd_name = args.strip().lstrip("/")
        help_text = get_command_help(cmd_name)
        if help_text:
            return CommandOutput.success(message=help_text)
        return CommandOutput.error(
            f"Unknown command: /{cmd_name}\n"
            f"Use /help for available commands."
        )
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
            # Provide informative message about why nothing was compacted
            usage = session.context.get_token_usage()
            msg_tokens = usage.get("messages", 0)
            available = usage.get("available", 0)

            # Get preserve ratio from config
            config = getattr(session, "_config", None)
            if config and config.compaction:
                preserve_ratio = config.compaction.recent_preserve_ratio
                preserve_budget = int(available * preserve_ratio)
                return CommandOutput.success(
                    message=f"Nothing to compact - all {len(messages)} messages "
                            f"({msg_tokens:,} tokens) fit within preserve budget "
                            f"({preserve_budget:,} tokens, {int(preserve_ratio*100)}% of available)",
                    data={
                        "compacted": False,
                        "reason": "within_preserve_budget",
                        "message_tokens": msg_tokens,
                        "preserve_budget": preserve_budget,
                    },
                )
            else:
                return CommandOutput.success(
                    message="Nothing to compact (no compaction config)",
                    data={"compacted": False, "reason": "no_config"},
                )
        else:
            return CommandOutput.success(
                message=f"Compacted: {result.original_token_count:,} -> {result.new_token_count:,} tokens",
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

    If current context exceeds the new model's context window, returns
    an error with guidance to use /compact first.

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
            # No model set - show default from config
            default_model = config.resolve_model()
            return CommandOutput.success(
                message=f"Model: {default_model.model_id} (default)\n"
                        f"Context window: {default_model.context_window:,} tokens\n"
                        f"Provider: {default_model.provider_name}",
                data={
                    "model_id": default_model.model_id,
                    "context_window": default_model.context_window,
                    "alias": default_model.alias,
                    "provider": default_model.provider_name,
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

    # Update session's provider to use the new model
    # The provider is cached by provider_name:model_id, so this gets or creates
    # the appropriate provider for the new model
    provider_registry = getattr(ctx.pool, "_shared", None)
    if provider_registry is not None:
        provider_registry = getattr(provider_registry, "provider_registry", None)
    if provider_registry is not None:
        new_provider = provider_registry.get(
            new_model.provider_name, new_model.model_id, new_model.reasoning
        )
        agent.session.provider = new_provider

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

    # YOLO mode skips prompts
    if is_yolo:
        return (True, True)

    console = get_console()

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


async def _mcp_sharing_prompt(
    server_name: str,
    is_yolo: bool = False,
) -> bool:
    """Prompt user for MCP connection sharing preference.

    Args:
        server_name: Name of the MCP server.
        is_yolo: If True, skip prompt and default to private.

    Returns:
        True if connection should be shared with all agents, False for private.
    """
    import asyncio

    # YOLO mode defaults to private (no sharing)
    if is_yolo:
        return False

    console = get_console()

    console.print("\n[yellow]Share this connection with other agents?[/]")
    console.print("  [dim](Other agents will still need to approve their own permissions)[/]")
    console.print()
    console.print("  [cyan][1][/] Yes - all agents can use this connection")
    console.print("  [cyan][2][/] No - only this agent (default)")

    def get_input() -> str:
        try:
            return console.input("\n[dim]Choice [1-2]:[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            return "2"

    response = await asyncio.to_thread(get_input)

    return response == "1"


def _parse_mcp_flags(parts: list[str]) -> tuple[list[str], dict[str, bool]]:
    """Parse MCP command flags.

    Args:
        parts: Command parts to parse.

    Returns:
        Tuple of (remaining_parts, flags_dict).
        Flags: allow_all, per_tool, shared, private
    """
    flags = {
        "allow_all": False,
        "per_tool": False,
        "shared": False,
        "private": False,
    }
    remaining = []

    for part in parts:
        if part == "--allow-all":
            flags["allow_all"] = True
        elif part == "--per-tool":
            flags["per_tool"] = True
        elif part == "--shared":
            flags["shared"] = True
        elif part == "--private":
            flags["private"] = True
        else:
            remaining.append(part)

    return remaining, flags


async def cmd_mcp(
    ctx: CommandContext,
    args: str | None = None,
) -> CommandOutput:
    """Handle /mcp commands for MCP server management.

    Subcommands:
        /mcp                List configured and connected servers
        /mcp connect <name> [flags]  Connect to a configured MCP server
        /mcp disconnect <name>  Disconnect from server
        /mcp tools [server] List available MCP tools
        /mcp retry <server> Retry listing tools from a server

    Connect flags:
        --allow-all   Skip consent prompt, allow all tools
        --per-tool    Skip consent prompt, require per-tool confirmation
        --shared      Skip sharing prompt, share with all agents
        --private     Skip sharing prompt, keep private to this agent

    Args:
        ctx: Command context with pool access.
        args: Subcommand and arguments.

    Returns:
        CommandOutput with result.
    """
    from nexus3.core.permissions import PermissionLevel
    from nexus3.mcp.permissions import can_use_mcp
    from nexus3.mcp.registry import MCPServerConfig

    # Get current agent info
    current_agent_id = ctx.current_agent_id or "main"
    agent = ctx.pool.get(current_agent_id) if ctx.current_agent_id else None
    perms = agent.services.get("permissions") if agent else None

    # Check agent permissions for MCP access
    if perms is not None and not can_use_mcp(perms):
        return CommandOutput.error(
            "MCP access requires TRUSTED or YOLO permission level"
        )

    # Get shared components
    shared = getattr(ctx.pool, "_shared", None)
    if shared is None:
        return CommandOutput.error("Pool shared components not available")

    config = shared.config
    registry = shared.mcp_registry

    # Parse subcommand and flags
    all_parts = (args or "").strip().split()
    parts, flags = _parse_mcp_flags(all_parts)

    if len(parts) == 0:
        # List servers - first check for dead connections
        dead = await registry.check_connections()
        if dead:
            # Refresh tools for all agents since we don't track which were shared
            if agent:
                await _refresh_agent_tools(agent, registry, shared)
            await _refresh_all_other_agents_tools(current_agent_id, ctx.pool, registry, shared)

        lines = ["MCP Servers:"]
        lines.append("")

        # Configured servers
        if config.mcp_servers:
            lines.append("Configured:")
            for srv_cfg in config.mcp_servers:
                # Check if connected AND visible to this agent
                server = registry.get(srv_cfg.name, agent_id=current_agent_id)
                if server is not None:
                    status = "[connected]"
                elif registry.get(srv_cfg.name) is not None:
                    # Connected but not visible to this agent
                    status = "[connected, not visible]"
                else:
                    status = "[disconnected]"
                enabled = "" if srv_cfg.enabled else " (disabled)"
                lines.append(f"  {srv_cfg.name} {status}{enabled}")
        else:
            lines.append("Configured: (none)")

        lines.append("")

        # Connected servers visible to this agent
        visible_servers = registry.list_servers(agent_id=current_agent_id)
        if visible_servers:
            lines.append(f"Connected (visible to you): {len(visible_servers)}")
            for name in visible_servers:
                server = registry.get(name, agent_id=current_agent_id)
                if server:
                    tool_count = len(server.skills)
                    sharing = "shared" if server.shared else f"owner: {server.owner_agent_id}"
                    lines.append(f"  {name}: {tool_count} tools ({sharing})")
        else:
            lines.append("Connected (visible to you): (none)")

        return CommandOutput.success(message="\n".join(lines))

    subcmd = parts[0].lower()

    if subcmd == "connect":
        if len(parts) < 2:
            return CommandOutput.error(
                "Usage: /mcp connect <name> [--allow-all|--per-tool] [--shared|--private]"
            )

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

        # Check if already connected (by anyone)
        existing = registry.get(name)
        if existing is not None:
            if existing.is_visible_to(current_agent_id):
                return CommandOutput.error(f"Already connected to '{name}'")
            else:
                return CommandOutput.error(
                    f"Server '{name}' is connected by another agent (owner: {existing.owner_agent_id})"
                )

        # Convert config schema to registry config
        reg_cfg = MCPServerConfig(
            name=srv_cfg.name,
            command=srv_cfg.command,
            url=srv_cfg.url,
            env=srv_cfg.env,
            env_passthrough=srv_cfg.env_passthrough,
            cwd=srv_cfg.cwd,
            enabled=srv_cfg.enabled,
        )

        # Check if YOLO (skip all prompts)
        is_yolo = (
            perms is not None and
            perms.effective_policy.level == PermissionLevel.YOLO
        )

        try:
            # Connect initially to get tool list
            server = await registry.connect(
                reg_cfg,
                owner_agent_id=current_agent_id,
                shared=False,  # Will update after prompts
            )
            tool_names = [s.original_name for s in server.skills]

            # Determine allow_all from flags or prompt
            if flags["allow_all"]:
                allow_all = True
                proceed = True
            elif flags["per_tool"]:
                allow_all = False
                proceed = True
            else:
                # Prompt for consent (TRUSTED mode), skip for YOLO
                proceed, allow_all = await _mcp_connection_consent(
                    name, tool_names, is_yolo=is_yolo
                )

            if not proceed:
                # User denied - disconnect and return
                await registry.disconnect(name)
                return CommandOutput.error(f"Connection to '{name}' denied by user")

            # Determine sharing from flags or prompt
            if flags["shared"]:
                share = True
            elif flags["private"]:
                share = False
            else:
                # Prompt for sharing preference
                share = await _mcp_sharing_prompt(name, is_yolo=is_yolo)

            # Update server with final settings
            server.shared = share

            # If allow_all, add to session allowances
            if allow_all and perms is not None:
                perms.session_allowances.add_mcp_server(name)

            # Refresh tool definitions for current agent
            if agent:
                await _refresh_agent_tools(agent, registry, shared)

            # If shared, also refresh all other agents so they see the new tools
            if share:
                await _refresh_all_other_agents_tools(current_agent_id, ctx.pool, registry, shared)

            sharing_str = "shared" if share else "private"
            mode_str = "allow-all" if allow_all else "per-tool"
            return CommandOutput.success(
                message=f"Connected to '{name}' ({mode_str}, {sharing_str})\n"
                        f"Tools available: {', '.join(tool_names)}",
                data={
                    "server": name,
                    "tools": tool_names,
                    "allow_all": allow_all,
                    "shared": share,
                },
            )
        except Exception as e:
            return CommandOutput.error(f"Failed to connect to '{name}': {e}")

    elif subcmd == "disconnect":
        if len(parts) < 2:
            return CommandOutput.error("Usage: /mcp disconnect <name>")

        name = parts[1]

        # Check if connected and visible/owned by this agent
        server = registry.get(name)
        if server is None:
            return CommandOutput.error(f"Not connected to '{name}'")

        # Only owner can disconnect (shared connections still have an owner)
        if server.owner_agent_id != current_agent_id:
            return CommandOutput.error(
                f"Cannot disconnect '{name}' - owned by agent '{server.owner_agent_id}'"
            )

        # Remember if it was shared before disconnecting
        was_shared = server.shared

        await registry.disconnect(name)

        # Reset MCP allowances for this server (for current agent)
        if perms:
            # Remove server from allowed servers
            perms.session_allowances.mcp_servers.discard(name)
            # Remove tools from this server (prefix is mcp_{name}_)
            prefix = f"mcp_{name}_"
            perms.session_allowances.mcp_tools = {
                t for t in perms.session_allowances.mcp_tools
                if not t.startswith(prefix)
            }

        # Refresh tool definitions to remove disconnected MCP tools
        if agent:
            await _refresh_agent_tools(agent, registry, shared)

        # If it was shared, also refresh all other agents
        if was_shared:
            await _refresh_all_other_agents_tools(current_agent_id, ctx.pool, registry, shared)

        return CommandOutput.success(message=f"Disconnected from '{name}'")

    elif subcmd == "tools":
        server_name = parts[1] if len(parts) > 1 else None

        if server_name:
            # Check visibility
            server = registry.get(server_name, agent_id=current_agent_id)
            if server is None:
                # Check if it exists but isn't visible
                if registry.get(server_name) is not None:
                    return CommandOutput.error(
                        f"Server '{server_name}' is not visible to this agent"
                    )
                return CommandOutput.error(f"Not connected to '{server_name}'")
            skills = server.skills
        else:
            # Get all skills visible to this agent
            skills = await registry.get_all_skills(agent_id=current_agent_id)

        if not skills:
            return CommandOutput.success(message="No MCP tools available (for this agent)")

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

    elif subcmd == "retry":
        # /mcp retry <server> - Retry listing tools from a server
        if len(parts) < 2:
            return CommandOutput.error("Usage: /mcp retry <server>")

        server_name = parts[1]

        # Check if server exists and is visible
        server = registry.get(server_name, agent_id=current_agent_id)
        if server is None:
            if registry.get(server_name) is not None:
                return CommandOutput.error(
                    f"Server '{server_name}' is not visible to this agent"
                )
            return CommandOutput.error(f"Not connected to '{server_name}'")

        try:
            tool_count = await registry.retry_tools(server_name)
            if tool_count > 0:
                # Refresh tool definitions for this agent
                if agent:
                    await _refresh_agent_tools(agent, registry, shared)
                # If shared, refresh other agents too
                if server.shared:
                    await _refresh_all_other_agents_tools(current_agent_id, ctx.pool, registry, shared)
                return CommandOutput.success(
                    message=f"Successfully listed {tool_count} tools from '{server_name}'"
                )
            else:
                return CommandOutput.error(
                    f"Tool listing still failing for '{server_name}'. Check server logs."
                )
        except Exception as e:
            return CommandOutput.error(f"Retry failed: {e}")

    elif subcmd == "resources":
        # /mcp resources [server] - list resources
        server_name = parts[1] if len(parts) > 1 else None

        if server_name:
            # List resources from specific server
            server = registry.get(server_name, agent_id=current_agent_id)
            if server is None:
                if registry.get(server_name) is not None:
                    return CommandOutput.error(
                        f"Server '{server_name}' is not visible to this agent"
                    )
                return CommandOutput.error(f"Not connected to '{server_name}'")

            try:
                resources = await server.client.list_resources()
                if not resources:
                    return CommandOutput.success(
                        message=f"No resources from {server_name}",
                        data={"server": server_name, "resources": []},
                    )

                lines = [f"Resources from {server_name}:"]
                for r in resources:
                    lines.append(f"  {r.uri}")
                    lines.append(f"    Name: {r.name}")
                    if r.description:
                        lines.append(f"    Description: {r.description}")
                    lines.append(f"    Type: {r.mime_type}")

                return CommandOutput.success(
                    message="\n".join(lines),
                    data={
                        "server": server_name,
                        "resources": [{"uri": r.uri, "name": r.name} for r in resources],
                    },
                )
            except Exception as e:
                return CommandOutput.error(f"Failed to list resources: {e}")
        else:
            # List resources from all visible servers
            visible_servers = registry.list_servers(agent_id=current_agent_id)
            if not visible_servers:
                return CommandOutput.success(
                    message="No MCP servers connected",
                    data={"resources": []},
                )

            lines: list[str] = []
            all_resources: list[dict[str, Any]] = []
            for name in visible_servers:
                server = registry.get(name, agent_id=current_agent_id)
                if server:
                    try:
                        resources = await server.client.list_resources()
                        if resources:
                            lines.append(f"\n{name}:")
                            for r in resources:
                                lines.append(f"  {r.uri} - {r.name}")
                                all_resources.append({
                                    "server": name,
                                    "uri": r.uri,
                                    "name": r.name,
                                })
                    except Exception as e:
                        lines.append(f"\n{name}: Error - {e}")

            if not lines:
                return CommandOutput.success(
                    message="No resources available",
                    data={"resources": []},
                )

            return CommandOutput.success(
                message="MCP Resources:" + "".join(lines),
                data={"resources": all_resources},
            )

    elif subcmd == "prompts":
        # /mcp prompts [server] - list prompts
        server_name = parts[1] if len(parts) > 1 else None

        if server_name:
            # List prompts from specific server
            server = registry.get(server_name, agent_id=current_agent_id)
            if server is None:
                if registry.get(server_name) is not None:
                    return CommandOutput.error(
                        f"Server '{server_name}' is not visible to this agent"
                    )
                return CommandOutput.error(f"Not connected to '{server_name}'")

            try:
                prompts = await server.client.list_prompts()
                if not prompts:
                    return CommandOutput.success(
                        message=f"No prompts from {server_name}",
                        data={"server": server_name, "prompts": []},
                    )

                lines = [f"Prompts from {server_name}:"]
                for p in prompts:
                    lines.append(f"  {p.name}")
                    if p.description:
                        lines.append(f"    {p.description}")
                    if p.arguments:
                        args_str = ", ".join(
                            f"{a.name}{'*' if a.required else ''}"
                            for a in p.arguments
                        )
                        lines.append(f"    Args: {args_str}")

                return CommandOutput.success(
                    message="\n".join(lines),
                    data={
                        "server": server_name,
                        "prompts": [{"name": p.name, "description": p.description} for p in prompts],
                    },
                )
            except Exception as e:
                return CommandOutput.error(f"Failed to list prompts: {e}")
        else:
            # List prompts from all visible servers
            visible_servers = registry.list_servers(agent_id=current_agent_id)
            if not visible_servers:
                return CommandOutput.success(
                    message="No MCP servers connected",
                    data={"prompts": []},
                )

            lines: list[str] = []
            all_prompts: list[dict[str, Any]] = []
            for name in visible_servers:
                server = registry.get(name, agent_id=current_agent_id)
                if server:
                    try:
                        prompts = await server.client.list_prompts()
                        if prompts:
                            lines.append(f"\n{name}:")
                            for p in prompts:
                                args_str = ""
                                if p.arguments:
                                    args_str = f" ({len(p.arguments)} args)"
                                desc = f" - {p.description}" if p.description else ""
                                lines.append(f"  {p.name}{args_str}{desc}")
                                all_prompts.append({
                                    "server": name,
                                    "name": p.name,
                                    "description": p.description,
                                })
                    except Exception as e:
                        lines.append(f"\n{name}: Error - {e}")

            if not lines:
                return CommandOutput.success(
                    message="No prompts available",
                    data={"prompts": []},
                )

            return CommandOutput.success(
                message="MCP Prompts:" + "".join(lines),
                data={"prompts": all_prompts},
            )

    else:
        return CommandOutput.error(
            f"Unknown MCP subcommand: {subcmd}\n"
            f"Usage: /mcp [connect|disconnect|tools|resources|prompts|retry] [args]"
        )


async def cmd_init(ctx: CommandContext, args: str | None) -> CommandOutput:
    """Initialize project configuration directory.

    Usage:
        /init           - Create .nexus3/ in current directory
        /init --force   - Overwrite existing files
        /init --global  - Initialize ~/.nexus3/ instead
    """
    from nexus3.cli.init_commands import init_global, init_local

    parts = (args or "").split()
    force = "--force" in parts or "-f" in parts
    global_mode = "--global" in parts or "-g" in parts

    if global_mode:
        success, message = init_global(force=force)
    else:
        success, message = init_local(force=force)

    if success:
        return CommandOutput.success(message=message)
    else:
        return CommandOutput.error(message)
