"""Tool confirmation UI for NEXUS3 REPL.

This module contains the confirmation dialog for destructive tool actions.
IMPORTANT: This is REPL-only code and must NOT be imported into RPC code paths.

The `confirm_tool_action` function provides interactive confirmation prompts
for tools that require user approval based on permission level (TRUSTED mode).
"""

import asyncio
import sys
from pathlib import Path
from typing import Any

from nexus3.cli.editor_preview import open_in_editor
from nexus3.cli.live_state import _current_live
from nexus3.core.permissions import ConfirmationResult
from nexus3.core.types import ToolCall
from nexus3.display import get_console
from nexus3.display.safe_sink import SafeSink


def _sanitize_details_text(value: object) -> str:
    """Sanitize untrusted detail text for plain editor/pager rendering."""
    return SafeSink.sanitize_stream_content(str(value))


def smart_truncate(value: str, max_length: int, preserve_ends: bool = False) -> str:
    """Truncate string, optionally preserving start and end (good for paths).

    Args:
        value: String to truncate
        max_length: Maximum length of result
        preserve_ends: If True, use middle truncation (/home/.../file.py)

    Returns:
        Truncated string, or original if within limit
    """
    if len(value) <= max_length:
        return value
    if preserve_ends and max_length >= 15:
        available = max_length - 5  # Reserve for "/.../"
        start_len = available // 2
        end_len = available - start_len
        return f"{value[:start_len]}/.../{value[-end_len:]}"
    return value[:max_length - 3] + "..."


def format_tool_params(arguments: dict[str, Any], max_length: int = 140) -> str:
    """Format tool arguments as a truncated string for display.

    Prioritizes path/file arguments (shown first, not truncated individually).
    Other arguments are truncated if needed.

    All values are escaped to prevent Rich markup injection attacks.

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

    # Add priority arguments first (full value, escaped for Rich markup)
    for key in priority_keys:
        if key in arguments and arguments[key]:
            value = SafeSink.sanitize_print_value(arguments[key])
            # Use middle truncation for path-like values if very long
            if key in ("path", "file", "file_path", "directory", "dir", "cwd") and len(value) > 60:
                value = smart_truncate(value, max_length=60, preserve_ends=True)
            safe_key = SafeSink.sanitize_print_value(key)
            parts.append(f"{safe_key}={value}")

    # Add remaining arguments (truncated if needed, escaped for Rich markup)
    for key, value in arguments.items():
        if key in priority_keys or value is None:
            continue
        str_val = SafeSink.sanitize_print_value(value)
        # Truncate long non-priority values
        if len(str_val) > 30:
            str_val = str_val[:27] + "..."
        # Quote strings that contain spaces
        if isinstance(value, str) and " " in str_val:
            str_val = f'"{str_val}"'
        # Escape both key and value for Rich markup safety
        safe_key = SafeSink.sanitize_print_value(key)
        safe_val = str_val
        parts.append(f"{safe_key}={safe_val}")

    result = ", ".join(parts)

    # Truncate overall result (but this should rarely happen with priority keys first)
    if len(result) > max_length:
        result = result[: max_length - 3] + "..."

    return result


def _open_in_editor(content: str, title: str) -> bool:
    """Open content in external editor.

    Args:
        content: Text content to display
        title: Title for the temp file header

    Returns:
        True if successfully opened, False on failure.
    """
    return open_in_editor(content, title)


def _format_full_tool_details(
    tool_call: ToolCall,
    target_path: Path | None,
    agent_cwd: Path,
) -> str:
    """Format complete tool details for popup display.

    Returns:
        Human-readable text with all tool parameters.
    """
    lines = []

    lines.append(f"Tool: {_sanitize_details_text(tool_call.name)}")
    lines.append(f"Call ID: {_sanitize_details_text(tool_call.id)}")
    lines.append("")

    if target_path:
        lines.append(f"Target Path: {_sanitize_details_text(target_path)}")
    lines.append(f"Working Directory: {_sanitize_details_text(agent_cwd)}")
    lines.append("")
    lines.append("Parameters:")
    lines.append("-" * 40)

    for key, value in tool_call.arguments.items():
        safe_key = _sanitize_details_text(key)
        value_str = _sanitize_details_text(value)
        if len(value_str) > 200 or "\n" in value_str:
            lines.append(f"\n{safe_key}:")
            lines.append("-" * 20)
            lines.append(value_str)
            lines.append("-" * 20)
        else:
            lines.append(f"{safe_key}: {value_str}")

    return "\n".join(lines)


def _show_tool_details(tool_call: ToolCall, target_path: Path | None, agent_cwd: Path) -> bool:
    """Show full tool details in external editor.

    Returns:
        True if viewer opened successfully, False otherwise.
    """
    content = _format_full_tool_details(tool_call, target_path, agent_cwd)
    title = f"Tool: {_sanitize_details_text(tool_call.name)}"
    return _open_in_editor(content, title)


async def confirm_tool_action(
    tool_call: ToolCall,
    target_path: Path | None,
    agent_cwd: Path,
    pause_event: asyncio.Event,
    pause_ack_event: asyncio.Event,
) -> ConfirmationResult:
    """Prompt user for confirmation of destructive action with allow once/always options.

    This callback is invoked by Session when a tool requires user confirmation
    (based on permission level). It shows different options based on tool type:

    For write operations (write_file, edit_file):
        [1] Allow once
        [2] Allow always for this file
        [3] Allow always in this directory
        [4] Deny

    For execution operations (`exec`, `run_python`):
        [1] Allow once
        [2] Allow always in current directory
        [3] Deny

    Args:
        tool_call: The tool call requiring confirmation.
        target_path: The path being accessed (for write ops) or None.
        agent_cwd: The agent's working directory (for accurate preview display).
        pause_event: asyncio.Event - cleared to request pause, set to resume.
        pause_ack_event: asyncio.Event - set by KeyMonitor when paused.

    Returns:
        ConfirmationResult indicating user's decision.
    """
    console = get_console()
    sink = SafeSink(console)
    tool_name = tool_call.name

    # Determine tool type for appropriate prompting
    is_exec_tool = tool_name in ("exec", "shell_UNSAFE", "run_python")
    is_shell_unsafe = tool_name == "shell_UNSAFE"  # Always requires per-use approval
    is_direct_exec = tool_name == "exec"
    is_run_python = tool_name == "run_python"
    is_nexus_tool = tool_name.startswith("nexus_")
    is_mcp_tool = tool_name.startswith("mcp_")

    # Pause the Live display during confirmation to prevent visual conflicts
    live = _current_live.get()
    if live is not None:
        live.stop()

    # Pause KeyMonitor so it stops consuming stdin and restores terminal mode
    # Protocol: clear pause_event to signal pause, wait for pause_ack_event
    pause_event.clear()
    try:
        # Wait for KeyMonitor to acknowledge pause (with timeout to prevent deadlock)
        await asyncio.wait_for(pause_ack_event.wait(), timeout=0.5)
    except TimeoutError:
        # KeyMonitor may not be running (e.g., Windows fallback) - proceed anyway
        pass

    try:
        # Track lines printed so we can clear the prompt after selection
        lines_printed = 0

        # Build description based on tool type
        if is_mcp_tool:
            # Extract server name from mcp_{server}_{tool} format
            parts = tool_name.split("_", 2)
            server_name = parts[1] if len(parts) > 1 else "unknown"
            args_preview = str(tool_call.arguments)[:120]
            if len(str(tool_call.arguments)) > 120:
                args_preview += "..."
            sink.print_trusted("\n[yellow]Allow MCP tool '[/]", end="")
            sink.print_untrusted(tool_name, end="")
            sink.print_trusted("[yellow]'?[/]")
            sink.print_trusted("  [dim]Server:[/] ", end="")
            sink.print_untrusted(server_name)
            sink.print_trusted("  [dim]Arguments:[/] ", end="")
            sink.print_untrusted(args_preview)
            lines_printed += 4  # empty + header + server + args
        elif is_exec_tool:
            # Use agent's cwd as default, not process cwd
            cwd = tool_call.arguments.get("cwd", str(agent_cwd))
            if is_direct_exec:
                program = str(tool_call.arguments.get("program", ""))
                raw_args = tool_call.arguments.get("args", [])
                if isinstance(raw_args, list):
                    args_preview = " ".join(str(arg) for arg in raw_args)
                else:
                    args_preview = str(raw_args)
                if len(args_preview) > 100:
                    args_preview = args_preview[:100] + "..."
                sink.print_trusted("\n[yellow]Execute [/]", end="")
                sink.print_untrusted(tool_name, end="")
                sink.print_trusted("[yellow]?[/]")
                sink.print_trusted("  [dim]Program:[/] ", end="")
                sink.print_untrusted(program)
                sink.print_trusted("  [dim]Args:[/] ", end="")
                sink.print_untrusted(args_preview or "[]")
                sink.print_trusted("  [dim]Directory:[/] ", end="")
                sink.print_untrusted(str(cwd))
                lines_printed += 5  # empty + header + program + args + dir
            else:
                command = tool_call.arguments.get("command", tool_call.arguments.get("code", ""))
                preview = command[:100] + "..." if len(command) > 100 else command
                sink.print_trusted("\n[yellow]Execute [/]", end="")
                sink.print_untrusted(tool_name, end="")
                sink.print_trusted("[yellow]?[/]")
                if is_shell_unsafe:
                    shell_name = str(tool_call.arguments.get("shell", "auto"))
                    sink.print_trusted("  [dim]Shell:[/] ", end="")
                    sink.print_untrusted(shell_name)
                    lines_printed += 1
                sink.print_trusted("  [dim]Command:[/] ", end="")
                sink.print_untrusted(preview)
                sink.print_trusted("  [dim]Directory:[/] ", end="")
                sink.print_untrusted(str(cwd))
                lines_printed += 4  # empty + header + command + dir
        elif is_nexus_tool:
            # Nexus tools use agent_id instead of path
            agent_id = tool_call.arguments.get("agent_id", "unknown")
            sink.print_trusted("\n[yellow]Allow [/]", end="")
            sink.print_untrusted(tool_name, end="")
            sink.print_trusted("[yellow]?[/]")
            sink.print_trusted("  [dim]Agent:[/] ", end="")
            sink.print_untrusted(str(agent_id))
            lines_printed += 3  # empty + header + agent
        elif tool_name == "kill_process":
            pid = tool_call.arguments.get("pid", "unknown")
            tree = bool(tool_call.arguments.get("tree", True))
            force = bool(tool_call.arguments.get("force", False))
            sink.print_trusted("\n[yellow]Allow [/]", end="")
            sink.print_untrusted(tool_name, end="")
            sink.print_trusted("[yellow]?[/]")
            sink.print_trusted("  [dim]PID:[/] ", end="")
            sink.print_untrusted(str(pid))
            sink.print_trusted("  [dim]Tree:[/] ", end="")
            sink.print_untrusted("yes" if tree else "no")
            sink.print_trusted("  [dim]Force:[/] ", end="")
            sink.print_untrusted("yes" if force else "no")
            lines_printed += 5  # empty + header + pid + tree + force
        else:
            path_str = str(target_path) if target_path else tool_call.arguments.get(
                "path", "unknown"
            )
            sink.print_trusted("\n[yellow]Allow [/]", end="")
            sink.print_untrusted(tool_name, end="")
            sink.print_trusted("[yellow]?[/]")
            sink.print_trusted("  [dim]Path:[/] ", end="")
            sink.print_untrusted(str(path_str))
            lines_printed += 3  # empty + header + path

            # Add content preview for write/edit operations
            if tool_name in ("write_file", "append_file") and "content" in tool_call.arguments:
                content = str(tool_call.arguments["content"])
                content_preview = content[:150].replace("\n", "\\n")
                if len(content) > 150:
                    content_preview += "..."
                sink.print_trusted("  [dim]Content:[/] ", end="")
                sink.print_untrusted(content_preview)
                lines_printed += 1
            elif tool_name == "edit_file" and "old_string" in tool_call.arguments:
                old = str(tool_call.arguments.get("old_string", ""))[:80].replace("\n", "\\n")
                new = str(tool_call.arguments.get("new_string", ""))[:80].replace("\n", "\\n")
                sink.print_trusted('  [dim]Replace:[/] "', end="")
                sink.print_untrusted(old, end="")
                sink.print_trusted('" -> "', end="")
                sink.print_untrusted(new, end="")
                sink.print_trusted('"')
                lines_printed += 1

        # Show options based on tool type
        console.print()
        lines_printed += 1  # empty line
        if is_mcp_tool:
            console.print("  [cyan][1][/] Allow once")
            console.print("  [cyan][2][/] Allow this tool always (this session)")
            console.print("  [cyan][3][/] Allow all tools from this server (this session)")
            console.print("  [cyan][4][/] Deny")
            # NOTE: When adding new tool types, add this popup option to their menu too
            console.print("  [cyan]\\[p][/] [dim]View full details[/]")
            lines_printed += 5
        elif is_shell_unsafe:
            # shell_UNSAFE always requires per-use approval - no "allow always" options
            console.print("  [cyan][1][/] Allow once")
            console.print("  [cyan][2][/] Deny")
            console.print("  [dim](shell_UNSAFE requires approval each time)[/]")
            console.print("  [cyan]\\[p][/] [dim]View full details[/]")
            lines_printed += 4
        elif is_direct_exec:
            console.print("  [cyan][1][/] Allow once")
            console.print("  [cyan][2][/] Allow this command in this directory")
            console.print("  [cyan][3][/] Deny")
            console.print("  [cyan]\\[p][/] [dim]View full details[/]")
            lines_printed += 4
        elif is_run_python:
            console.print("  [cyan][1][/] Allow once")
            console.print("  [cyan][2][/] Allow always in this directory")
            console.print("  [cyan][3][/] Deny")
            console.print("  [cyan]\\[p][/] [dim]View full details[/]")
            lines_printed += 4
        else:
            console.print("  [cyan][1][/] Allow once")
            console.print("  [cyan][2][/] Allow always for this file")
            console.print("  [cyan][3][/] Allow always in this directory")
            console.print("  [cyan][4][/] Deny")
            console.print("  [cyan]\\[p][/] [dim]View full details[/]")
            lines_printed += 5

        # Use asyncio.to_thread for blocking input to allow event loop to continue
        def get_input() -> str:
            try:
                if is_shell_unsafe:
                    prompt = "\n[dim]Choice [1-2, p]:[/] "
                elif is_exec_tool:
                    prompt = "\n[dim]Choice [1-3, p]:[/] "
                else:
                    prompt = "\n[dim]Choice [1-4, p]:[/] "
                return console.input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                return ""

        # Track lines for prompt cycle (may loop if user presses 'p')
        prompt_lines = 0

        while True:
            response = await asyncio.to_thread(get_input)
            prompt_lines += 2  # prompt line + input line
            response_lower = response.lower().strip()

            # Handle popup request
            if response_lower == "p":
                if not _show_tool_details(tool_call, target_path, agent_cwd):
                    console.print("[yellow]Could not open viewer[/]")
                    prompt_lines += 1
                # Re-prompt after viewing details
                continue

            # Valid response, exit loop
            break

        lines_printed += prompt_lines

        # Clear the confirmation prompt from terminal
        # Move cursor up N lines and clear from cursor to end of screen
        sys.stdout.write(f"\033[{lines_printed}F")  # Move to beginning of line N lines up
        sys.stdout.write("\033[J")  # Clear from cursor to end of screen
        sys.stdout.flush()

        # shell_UNSAFE only has 2 options: 1=allow once, 2=deny
        if is_shell_unsafe:
            if response == "1":
                return ConfirmationResult.ALLOW_ONCE
            else:
                return ConfirmationResult.DENY

        # exec and run_python have 3 options: 1=allow once, 2=allow directory, 3=deny
        if is_direct_exec or is_run_python:
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
        # Protocol: set pause_event to signal resume
        pause_event.set()

        # Resume Live display after confirmation
        if live is not None:
            live.start()
