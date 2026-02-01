"""Tool confirmation UI for NEXUS3 REPL.

This module contains the confirmation dialog for destructive tool actions.
IMPORTANT: This is REPL-only code and must NOT be imported into RPC code paths.

The `confirm_tool_action` function provides interactive confirmation prompts
for tools that require user approval based on permission level (TRUSTED mode).
"""

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from nexus3.cli.live_state import _current_live
from nexus3.core.permissions import ConfirmationResult
from nexus3.core.text_safety import escape_rich_markup
from nexus3.core.types import ToolCall
from nexus3.display import get_console


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


def format_tool_params(arguments: dict, max_length: int = 140) -> str:
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
            value = str(arguments[key])
            # Use middle truncation for path-like values if very long
            if key in ("path", "file", "file_path", "directory", "dir", "cwd") and len(value) > 60:
                value = smart_truncate(value, max_length=60, preserve_ends=True)
            value = escape_rich_markup(value)
            safe_key = escape_rich_markup(str(key))
            parts.append(f"{safe_key}={value}")

    # Add remaining arguments (truncated if needed, escaped for Rich markup)
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
        # Escape both key and value for Rich markup safety
        safe_key = escape_rich_markup(str(key))
        safe_val = escape_rich_markup(str_val)
        parts.append(f"{safe_key}={safe_val}")

    result = ", ".join(parts)

    # Truncate overall result (but this should rarely happen with priority keys first)
    if len(result) > max_length:
        result = result[: max_length - 3] + "..."

    return result


def _is_wsl() -> bool:
    """Detect if running in Windows Subsystem for Linux."""
    try:
        with open("/proc/version") as f:
            return "microsoft" in f.read().lower()
    except (FileNotFoundError, PermissionError):
        return False


def _get_system_editor() -> list[str]:
    """Get the appropriate editor command for the current platform.

    Returns:
        Command list to open a text file (append filename to use).
    """
    # Check environment variables first (works on all platforms)
    for env in ["VISUAL", "EDITOR"]:
        if editor := os.environ.get(env):
            return [editor]

    # Windows or WSL - use notepad which opens a GUI window
    if sys.platform == "win32" or _is_wsl():
        return ["notepad.exe"]

    # Unix fallbacks
    for cmd in ["less", "more", "cat"]:
        if shutil.which(cmd):
            return [cmd]

    return ["cat"]


def _open_in_editor(content: str, title: str) -> bool:
    """Open content in external editor.

    Args:
        content: Text content to display
        title: Title for the temp file header

    Returns:
        True if successfully opened, False on failure.
    """
    temp_dir = Path.home() / ".nexus3" / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="nexus_tool_", dir=temp_dir)
    try:
        editor_cmd = _get_system_editor()
        is_wsl = _is_wsl()
        is_pager = editor_cmd[0] in ("less", "more", "cat")

        with os.fdopen(fd, "w", encoding="utf-8") as f:
            # Add navigation instructions for terminal pagers
            if is_pager:
                f.write("Navigation: q=quit  Space=next page  b=back  /=search\n")
                f.write("-" * 50 + "\n\n")
            f.write(f"=== {title} ===\n\n{content}\n")

        if sys.platform == "win32":
            # Windows: run in background, no window flash
            subprocess.Popen(
                editor_cmd + [tmp_path],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            # Give notepad time to read the file before we delete it
            time.sleep(0.5)
        elif is_wsl and "notepad" in editor_cmd[0].lower():
            # WSL with notepad: run in background (opens Windows GUI)
            subprocess.Popen(editor_cmd + [tmp_path])
            # Give notepad time to read the file before we delete it
            time.sleep(0.5)
        else:
            # Unix: run in foreground, wait for user to close
            subprocess.run(editor_cmd + [tmp_path])

        return True
    except Exception:
        return False
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


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

    lines.append(f"Tool: {tool_call.name}")
    lines.append(f"Call ID: {tool_call.id}")
    lines.append("")

    if target_path:
        lines.append(f"Target Path: {target_path}")
    lines.append(f"Working Directory: {agent_cwd}")
    lines.append("")
    lines.append("Parameters:")
    lines.append("-" * 40)

    for key, value in tool_call.arguments.items():
        value_str = str(value)
        if len(value_str) > 200 or "\n" in value_str:
            lines.append(f"\n{key}:")
            lines.append("-" * 20)
            lines.append(value_str)
            lines.append("-" * 20)
        else:
            lines.append(f"{key}: {value_str}")

    return "\n".join(lines)


def _show_tool_details(tool_call: ToolCall, target_path: Path | None, agent_cwd: Path) -> bool:
    """Show full tool details in external editor.

    Returns:
        True if viewer opened successfully, False otherwise.
    """
    content = _format_full_tool_details(tool_call, target_path, agent_cwd)
    title = f"Tool: {tool_call.name}"
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

    For execution operations (bash, run_python):
        [1] Allow once
        [2] Allow always in current directory
        [3] Allow always (global)
        [4] Deny

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

        # Escape tool name for Rich markup safety (MCP tools can have crafted names)
        safe_tool_name = escape_rich_markup(tool_name)

        # Build description based on tool type
        if is_mcp_tool:
            # Extract server name from mcp_{server}_{tool} format
            parts = tool_name.split("_", 2)
            server_name = parts[1] if len(parts) > 1 else "unknown"
            safe_server_name = escape_rich_markup(server_name)
            args_preview = str(tool_call.arguments)[:120]
            if len(str(tool_call.arguments)) > 120:
                args_preview += "..."
            safe_args_preview = escape_rich_markup(args_preview)
            console.print(f"\n[yellow]Allow MCP tool '{safe_tool_name}'?[/]")
            console.print(f"  [dim]Server:[/] {safe_server_name}")
            console.print(f"  [dim]Arguments:[/] {safe_args_preview}")
            lines_printed += 4  # empty + header + server + args
        elif is_exec_tool:
            # Use agent's cwd as default, not process cwd
            cwd = tool_call.arguments.get("cwd", str(agent_cwd))
            safe_cwd = escape_rich_markup(str(cwd))
            command = tool_call.arguments.get("command", tool_call.arguments.get("code", ""))
            preview = command[:100] + "..." if len(command) > 100 else command
            safe_preview = escape_rich_markup(preview)
            console.print(f"\n[yellow]Execute {safe_tool_name}?[/]")
            console.print(f"  [dim]Command:[/] {safe_preview}")
            console.print(f"  [dim]Directory:[/] {safe_cwd}")
            lines_printed += 4  # empty + header + command + dir
        elif is_nexus_tool:
            # Nexus tools use agent_id instead of path
            agent_id = tool_call.arguments.get("agent_id", "unknown")
            safe_agent_id = escape_rich_markup(str(agent_id))
            console.print(f"\n[yellow]Allow {safe_tool_name}?[/]")
            console.print(f"  [dim]Agent:[/] {safe_agent_id}")
            lines_printed += 3  # empty + header + agent
        else:
            path_str = str(target_path) if target_path else tool_call.arguments.get(
                "path", "unknown"
            )
            safe_path_str = escape_rich_markup(str(path_str))
            console.print(f"\n[yellow]Allow {safe_tool_name}?[/]")
            console.print(f"  [dim]Path:[/] {safe_path_str}")
            lines_printed += 3  # empty + header + path

            # Add content preview for write/edit operations
            if tool_name in ("write_file", "append_file") and "content" in tool_call.arguments:
                content = str(tool_call.arguments["content"])
                content_preview = content[:150].replace("\n", "\\n")
                if len(content) > 150:
                    content_preview += "..."
                safe_preview = escape_rich_markup(content_preview)
                console.print(f"  [dim]Content:[/] {safe_preview}")
                lines_printed += 1
            elif tool_name == "edit_file" and "old_string" in tool_call.arguments:
                old = str(tool_call.arguments.get("old_string", ""))[:80].replace("\n", "\\n")
                new = str(tool_call.arguments.get("new_string", ""))[:80].replace("\n", "\\n")
                safe_old = escape_rich_markup(old)
                safe_new = escape_rich_markup(new)
                console.print(f'  [dim]Replace:[/] "{safe_old}" -> "{safe_new}"')
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
        elif is_exec_tool:
            # bash_safe and run_python allow directory scope but not global
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
        # Protocol: set pause_event to signal resume
        pause_event.set()

        # Resume Live display after confirmation
        if live is not None:
            live.start()
