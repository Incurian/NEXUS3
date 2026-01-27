"""MCP error message formatting for user-friendly output."""

from nexus3.mcp.errors import MCPErrorContext


def format_config_validation_error(
    context: MCPErrorContext | None,
    field: str,
    error_msg: str,
    provided_value: str | None = None,
    expected_format: str | None = None,
) -> str:
    """Format config validation error with helpful context."""
    lines = ["", "MCP Configuration Error", "\u2501" * 23, ""]

    if context:
        lines.append(f'Server: "{context.server_name}"')
        if context.source_path:
            layer_desc = f" ({context.source_layer} config)" if context.source_layer else ""
            lines.append(f"Source: {context.source_path}{layer_desc}")
        lines.append("")

    lines.append(f"Problem: {error_msg}")

    if provided_value is not None:
        lines.append(f"  You provided: {provided_value}")
    if expected_format is not None:
        lines.append(f"  Expected:     {expected_format}")

    return "\n".join(lines)


def format_command_not_found(
    context: MCPErrorContext | None,
    command: str,
) -> str:
    """Format command not found error with installation hints."""
    lines = ["", "MCP Server Launch Failed", "\u2501" * 24, ""]

    if context:
        lines.append(f'Server: "{context.server_name}"')
        if context.source_path:
            layer_desc = f" ({context.source_layer} config)" if context.source_layer else ""
            lines.append(f"Source: {context.source_path}{layer_desc}")
        lines.append("")

    lines.append(f"Problem: Command not found: {command}")
    lines.append("")
    lines.append("Likely causes:")

    # Add command-specific hints
    if command in ("npx", "npm", "node"):
        lines.append("  1. Node.js is not installed")
        lines.append("  2. Node.js is not in PATH for the subprocess")
        lines.append("")
        lines.append("Troubleshooting:")
        lines.append(f"  - Check if {command} exists: which {command}")
        lines.append("  - Install Node.js: https://nodejs.org")
    elif command in ("python", "python3", "pip", "pip3"):
        lines.append("  1. Python is not installed")
        lines.append("  2. Python is not in PATH")
        lines.append("")
        lines.append("Troubleshooting:")
        lines.append(f"  - Check if {command} exists: which {command}")
        lines.append("  - Install Python: https://python.org")
    elif command in ("uvx", "uv"):
        lines.append("  1. uv is not installed")
        lines.append("  2. uv is not in PATH")
        lines.append("")
        lines.append("Troubleshooting:")
        lines.append(f"  - Check if {command} exists: which {command}")
        lines.append("  - Install uv: https://docs.astral.sh/uv/")
    elif command in ("docker", "podman"):
        lines.append(f"  1. {command} is not installed")
        lines.append(f"  2. {command} daemon is not running")
        lines.append("")
        lines.append("Troubleshooting:")
        lines.append(f"  - Check if {command} exists: which {command}")
        lines.append(f"  - Check daemon status: {command} info")
    else:
        lines.append(f"  1. {command} is not installed")
        lines.append(f"  2. {command} is not in PATH for the subprocess")
        lines.append("")
        lines.append("Troubleshooting:")
        lines.append(f"  - Check if {command} exists: which {command}")

    lines.append('  - Add to env_passthrough in config: ["PATH"]')

    return "\n".join(lines)


def format_server_crash(
    context: MCPErrorContext | None,
    exit_code: int | None,
    stderr_lines: list[str] | None = None,
) -> str:
    """Format server crash error with stderr context."""
    lines = ["", "MCP Server Crashed", "\u2501" * 18, ""]

    if context:
        lines.append(f'Server: "{context.server_name}"')
        if context.source_path:
            layer_desc = f" ({context.source_layer} config)" if context.source_layer else ""
            lines.append(f"Source: {context.source_path}{layer_desc}")
        if context.command:
            lines.append(f"Command: {context.command}")
        lines.append("")

    if exit_code is not None:
        lines.append(f"Problem: Server exited with code {exit_code}")
    else:
        lines.append("Problem: Server process terminated unexpectedly")

    if stderr_lines:
        lines.append("")
        lines.append("Server stderr (last lines):")
        for line in stderr_lines[-10:]:
            lines.append(f"  {line}")

    lines.append("")
    lines.append("Troubleshooting:")
    lines.append("  - Run the command manually to see full output")
    lines.append("  - Check server logs if available")

    if exit_code == 1:
        lines.append("  - Exit code 1 often indicates a configuration or startup error")
    elif exit_code == 127:
        lines.append("  - Exit code 127 usually means a command was not found")
    elif exit_code == 126:
        lines.append("  - Exit code 126 usually means permission denied")
    elif exit_code is not None and exit_code > 128:
        signal_num = exit_code - 128
        lines.append(f"  - Exit code {exit_code} indicates process killed by signal {signal_num}")

    return "\n".join(lines)


def format_json_error(
    context: MCPErrorContext | None,
    raw_text: str,
    error_msg: str,
    line: int | None = None,
    column: int | None = None,
) -> str:
    """Format JSON parse error with context."""
    lines = ["", "MCP Protocol Error", "\u2501" * 18, ""]

    if context:
        lines.append(f'Server: "{context.server_name}"')
        lines.append("")

    lines.append("Problem: Server sent invalid JSON")

    if line is not None and column is not None:
        lines.append(f"  Error at line {line}, column {column}: {error_msg}")
    else:
        lines.append(f"  {error_msg}")

    # Show snippet of the raw text
    if raw_text:
        preview = raw_text[:200] + "..." if len(raw_text) > 200 else raw_text
        lines.append("")
        lines.append("Raw response (preview):")
        lines.append(f"  {preview!r}")

    lines.append("")
    lines.append("Likely causes:")
    lines.append("  1. Server is outputting debug/log messages to stdout")
    lines.append("  2. Server crashed during response generation")
    lines.append("  3. Protocol version mismatch")
    lines.append("")
    lines.append("Troubleshooting:")
    lines.append("  - Run the server manually and check its stdout")
    lines.append("  - Ensure server only outputs JSON-RPC messages to stdout")

    return "\n".join(lines)


def format_timeout_error(
    context: MCPErrorContext | None,
    timeout: float,
    phase: str = "connection",
) -> str:
    """Format timeout error with troubleshooting hints."""
    lines = ["", "MCP Server Timeout", "\u2501" * 18, ""]

    if context:
        lines.append(f'Server: "{context.server_name}"')
        if context.source_path:
            layer_desc = f" ({context.source_layer} config)" if context.source_layer else ""
            lines.append(f"Source: {context.source_path}{layer_desc}")
        if context.command:
            lines.append(f"Command: {context.command}")
        lines.append("")

    lines.append(f"Problem: {phase.capitalize()} timed out after {timeout}s")

    lines.append("")
    lines.append("Likely causes:")

    if phase == "connection" or phase == "initialization":
        lines.append("  1. Server is taking too long to start")
        lines.append("  2. Server is blocked waiting for input")
        lines.append("  3. Server crashed silently without output")
    elif phase == "tool_call" or phase == "request":
        lines.append("  1. Operation is taking longer than expected")
        lines.append("  2. Server is blocked or deadlocked")
        lines.append("  3. Network request is slow (if server makes external calls)")
    else:
        lines.append(f"  1. {phase.capitalize()} operation exceeded time limit")
        lines.append("  2. Server may be unresponsive")

    lines.append("")
    lines.append("Troubleshooting:")
    lines.append("  - Try running the command manually")
    lines.append("  - Check if the server requires network access")
    lines.append("  - Increase timeout in MCP config if operation is legitimately slow")

    if phase == "connection" or phase == "initialization":
        lines.append("  - Ensure server outputs initialization response to stdout")

    return "\n".join(lines)
