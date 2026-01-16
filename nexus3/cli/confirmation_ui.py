"""Tool confirmation UI for NEXUS3 REPL.

This module contains the confirmation dialog for destructive tool actions.
IMPORTANT: This is REPL-only code and must NOT be imported into RPC code paths.

The `confirm_tool_action` function provides interactive confirmation prompts
for tools that require user approval based on permission level (TRUSTED mode).
"""

import asyncio
from contextvars import ContextVar
from pathlib import Path

from rich.live import Live

from nexus3.core.permissions import ConfirmationResult
from nexus3.core.types import ToolCall
from nexus3.display import get_console


# Context variable to store the current Live display for pausing during confirmation
_current_live: ContextVar[Live | None] = ContextVar("_current_live", default=None)


def format_tool_params(arguments: dict, max_length: int = 70) -> str:
    """Format tool arguments as a truncated string for display.

    Prioritizes path/file arguments (shown first, not truncated individually).
    Other arguments are truncated if needed.

    Args:
        arguments: Tool call arguments dictionary.
        max_length: Maximum length of output string (default 70).

    Returns:
        Formatted string like 'path=/foo/bar, content="hello..."' truncated to max_length.
    """
    if not arguments:
        return ""

    # Priority keys shown first and not individually truncated
    priority_keys = ("path", "file", "file_path", "directory", "dir", "cwd", "agent_id")
    parts = []

    # Add priority arguments first (full value)
    for key in priority_keys:
        if key in arguments and arguments[key]:
            value = str(arguments[key])
            parts.append(f"{key}={value}")

    # Add remaining arguments (truncated if needed)
    for key, value in arguments.items():
        if key in priority_keys or value is None:
            continue
        str_val = str(value)
        # Truncate long non-priority values
        if len(str_val) > 30:
            str_val = str_val[:27] + "..."
        # Quote strings that contain spaces
        if isinstance(value, str) and " " in str_val:
            str_val = f'"{str_val}"'
        parts.append(f"{key}={str_val}")

    result = ", ".join(parts)

    # Truncate overall result (but this should rarely happen with priority keys first)
    if len(result) > max_length:
        result = result[: max_length - 3] + "..."

    return result


async def confirm_tool_action(
    tool_call: ToolCall,
    target_path: Path | None,
    agent_cwd: Path,
    pause_event: asyncio.Event,
) -> ConfirmationResult:
    """Prompt user for confirmation of destructive action with allow once/always options.

    This callback is invoked by Session when a tool requires user confirmation
    (based on permission level). It shows different options based on tool type:

    For write operations (write_file, edit_file):
        [1] Allow once
        [2] Allow always for this file
        [3] Allow always in this directory
        [4] Deny

    For execution operations (bash, run_python):
        [1] Allow once
        [2] Allow always in current directory
        [3] Allow always (global)
        [4] Deny

    Args:
        tool_call: The tool call requiring confirmation.
        target_path: The path being accessed (for write ops) or None.
        agent_cwd: The agent's working directory (for accurate preview display).
        pause_event: asyncio.Event to signal KeyMonitor to pause during confirmation.

    Returns:
        ConfirmationResult indicating user's decision.
    """
    console = get_console()
    tool_name = tool_call.name

    # Determine tool type for appropriate prompting
    is_exec_tool = tool_name in ("bash_safe", "shell_UNSAFE", "run_python")
    is_shell_unsafe = tool_name == "shell_UNSAFE"  # Always requires per-use approval
    is_nexus_tool = tool_name.startswith("nexus_")
    is_mcp_tool = tool_name.startswith("mcp_")

    # Pause the Live display during confirmation to prevent visual conflicts
    live = _current_live.get()
    if live is not None:
        live.stop()

    # Pause KeyMonitor so it stops consuming stdin and restores terminal mode
    pause_event.set()
    # Give KeyMonitor time to pause and restore terminal
    await asyncio.sleep(0.15)

    try:
        # Build description based on tool type
        if is_mcp_tool:
            # Extract server name from mcp_{server}_{tool} format
            parts = tool_name.split("_", 2)
            server_name = parts[1] if len(parts) > 1 else "unknown"
            args_preview = str(tool_call.arguments)[:60]
            if len(str(tool_call.arguments)) > 60:
                args_preview += "..."
            console.print(f"\n[yellow]Allow MCP tool '{tool_name}'?[/]")
            console.print(f"  [dim]Server:[/] {server_name}")
            console.print(f"  [dim]Arguments:[/] {args_preview}")
        elif is_exec_tool:
            # Use agent's cwd as default, not process cwd
            cwd = tool_call.arguments.get("cwd", str(agent_cwd))
            command = tool_call.arguments.get("command", tool_call.arguments.get("code", ""))
            preview = command[:50] + "..." if len(command) > 50 else command
            console.print(f"\n[yellow]Execute {tool_name}?[/]")
            console.print(f"  [dim]Command:[/] {preview}")
            console.print(f"  [dim]Directory:[/] {cwd}")
        elif is_nexus_tool:
            # Nexus tools use agent_id instead of path
            agent_id = tool_call.arguments.get("agent_id", "unknown")
            console.print(f"\n[yellow]Allow {tool_name}?[/]")
            console.print(f"  [dim]Agent:[/] {agent_id}")
        else:
            path_str = str(target_path) if target_path else tool_call.arguments.get("path", "unknown")
            console.print(f"\n[yellow]Allow {tool_name}?[/]")
            console.print(f"  [dim]Path:[/] {path_str}")

        # Show options based on tool type
        console.print()
        if is_mcp_tool:
            console.print("  [cyan][1][/] Allow once")
            console.print("  [cyan][2][/] Allow this tool always (this session)")
            console.print("  [cyan][3][/] Allow all tools from this server (this session)")
            console.print("  [cyan][4][/] Deny")
        elif is_shell_unsafe:
            # shell_UNSAFE always requires per-use approval - no "allow always" options
            console.print("  [cyan][1][/] Allow once")
            console.print("  [cyan][2][/] Deny")
            console.print("  [dim](shell_UNSAFE requires approval each time)[/]")
        elif is_exec_tool:
            # bash_safe and run_python allow directory scope but not global
            console.print("  [cyan][1][/] Allow once")
            console.print("  [cyan][2][/] Allow always in this directory")
            console.print("  [cyan][3][/] Deny")
        else:
            console.print("  [cyan][1][/] Allow once")
            console.print("  [cyan][2][/] Allow always for this file")
            console.print("  [cyan][3][/] Allow always in this directory")
            console.print("  [cyan][4][/] Deny")

        # Use asyncio.to_thread for blocking input to allow event loop to continue
        def get_input() -> str:
            try:
                if is_shell_unsafe:
                    prompt = "\n[dim]Choice [1-2]:[/] "
                elif is_exec_tool:
                    prompt = "\n[dim]Choice [1-3]:[/] "
                else:
                    prompt = "\n[dim]Choice [1-4]:[/] "
                return console.input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                return ""

        response = await asyncio.to_thread(get_input)

        # shell_UNSAFE only has 2 options: 1=allow once, 2=deny
        if is_shell_unsafe:
            if response == "1":
                return ConfirmationResult.ALLOW_ONCE
            else:
                return ConfirmationResult.DENY

        # bash_safe and run_python have 3 options: 1=allow once, 2=allow directory, 3=deny
        if is_exec_tool:
            if response == "1":
                return ConfirmationResult.ALLOW_ONCE
            elif response == "2":
                return ConfirmationResult.ALLOW_EXEC_CWD
            else:
                return ConfirmationResult.DENY

        if response == "1":
            return ConfirmationResult.ALLOW_ONCE
        elif response == "2":
            if is_mcp_tool:
                # "Allow this tool always" - we use ALLOW_FILE to signal tool-level
                return ConfirmationResult.ALLOW_FILE
            else:
                return ConfirmationResult.ALLOW_FILE
        elif response == "3":
            if is_mcp_tool:
                # "Allow all tools from this server"
                return ConfirmationResult.ALLOW_EXEC_GLOBAL
            else:
                return ConfirmationResult.ALLOW_WRITE_DIRECTORY
        else:
            return ConfirmationResult.DENY

    finally:
        # Resume KeyMonitor (restores cbreak mode)
        pause_event.clear()

        # Resume Live display after confirmation
        if live is not None:
            live.start()
