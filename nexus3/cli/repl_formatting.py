"""SafeSink-backed formatting and sanitization helpers for REPL output."""

from __future__ import annotations

from html import escape as html_escape
from pathlib import Path

from nexus3.cli.trace_palette import trace_body_style, trace_header_style
from nexus3.core.text_safety import strip_terminal_escapes
from nexus3.display.safe_sink import SafeSink
from nexus3.session.trace import tool_display_id

_ASSISTANT_HEADER_STYLE = trace_header_style("assistant")
_ASSISTANT_BODY_STYLE = trace_body_style("assistant") or "magenta"
_TOOL_CALL_HEADER_STYLE = trace_header_style("tool_call")
_TOOL_CALL_BODY_STYLE = trace_body_style("tool_call") or "cyan"
_TOOL_RESULT_HEADER_STYLE = trace_header_style("tool_result")
_TOOL_RESULT_BODY_STYLE = trace_body_style("tool_result") or "green"


def _sanitize_tool_trace_text(
    safe_sink: SafeSink, value: str, *, markup_already_escaped: bool = False
) -> str:
    """Sanitize tool trace text before interpolation into Rich wrappers."""
    if markup_already_escaped:
        return safe_sink.sanitize_terminal_content(value)
    return safe_sink.sanitize_print_content(value)


def _sanitize_prompt_html_text(value: object) -> str:
    """Sanitize untrusted text before interpolation into prompt-toolkit HTML."""
    return html_escape(strip_terminal_escapes(str(value)), quote=False)


def _format_tool_id_header_line(
    safe_sink: SafeSink,
    tool_id: str,
    *,
    indent: int = 2,
) -> str:
    """Format the visible tool-id header line for REPL tool blocks."""
    safe_tool_id = _sanitize_tool_trace_text(safe_sink, tool_display_id(tool_id))
    return f"{' ' * indent}[{safe_tool_id}]"


def _format_tool_call_trace_line(
    safe_sink: SafeSink, name: str, params: str, tool_id: str | None = None
) -> str:
    """Format a tool call line while preserving trusted Rich wrapper markup."""
    safe_name = _sanitize_tool_trace_text(safe_sink, name)
    if params:
        safe_params = _sanitize_tool_trace_text(
            safe_sink, params, markup_already_escaped=True
        )
        return (
            f"  [{_TOOL_CALL_HEADER_STYLE}]●[/] "
            f"[{_TOOL_CALL_HEADER_STYLE}]{safe_name}[/]: "
            f"[{_TOOL_CALL_BODY_STYLE}]{safe_params}[/]"
        )
    return f"  [{_TOOL_CALL_HEADER_STYLE}]●[/] [{_TOOL_CALL_HEADER_STYLE}]{safe_name}[/]"


def _format_tool_result_trace_line(
    safe_sink: SafeSink, result_preview: str, duration_str: str, tool_id: str | None = None
) -> str:
    """Format a tool success line while preserving trusted Rich wrapper markup."""
    if result_preview:
        safe_preview = _sanitize_tool_trace_text(safe_sink, result_preview)
        return (
            f"      [{_TOOL_RESULT_HEADER_STYLE}]→[/] "
            f"[{_TOOL_RESULT_BODY_STYLE}]{safe_preview}[/]{duration_str}"
        )
    return (
        f"      [{_TOOL_RESULT_HEADER_STYLE}]→[/] "
        f"[{_TOOL_RESULT_BODY_STYLE}]done[/]{duration_str}"
    )


def _format_tool_result_preview_lines(
    safe_sink: SafeSink,
    output: str,
    *,
    label: str = "Result preview",
    max_lines: int,
    max_chars: int,
) -> list[str]:
    """Format a bounded inline tool result preview block."""
    trimmed = output.strip("\n")
    if not trimmed:
        return []

    clipped = trimmed[:max_chars]
    lines = clipped.splitlines()
    truncated = len(trimmed) > max_chars

    if len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True

    safe_label = _sanitize_tool_trace_text(safe_sink, label)
    formatted = [f"      [{_TOOL_RESULT_HEADER_STYLE}]↳ {safe_label}:[/]"]
    for line in lines:
        safe_line = _sanitize_tool_trace_text(safe_sink, line)
        formatted.append(f"        [{_TOOL_RESULT_BODY_STYLE}]{safe_line}[/]")

    if truncated:
        formatted.append(
            f"      [dim]↳ Preview truncated at {max_lines} lines / {max_chars} chars[/]"
        )

    return formatted


def _format_tool_error_trace_line(
    safe_sink: SafeSink, error: str, duration_str: str, tool_id: str | None = None
) -> str:
    """Format a tool error line while preserving trusted Rich wrapper markup."""
    error_preview = error[:120] + ("..." if len(error) > 120 else "")
    safe_error = _sanitize_tool_trace_text(safe_sink, error_preview)
    return f"      [red]→[/] [red]{safe_error}[/]{duration_str}"


def _format_tool_halt_trace_line(
    safe_sink: SafeSink, name: str, params: str, tool_id: str | None = None
) -> str:
    """Format a halted tool line while preserving trusted Rich wrapper markup."""
    safe_name = _sanitize_tool_trace_text(safe_sink, name)
    if params:
        safe_params = _sanitize_tool_trace_text(
            safe_sink, params, markup_already_escaped=True
        )
        return (
            f"  [dark_orange]●[/] {safe_name}: {safe_params} "
            "[dark_orange](halted)[/]"
        )
    return f"  [dark_orange]●[/] {safe_name} [dark_orange](halted)[/]"


def _format_incoming_started_line(
    safe_sink: SafeSink, source: str, source_agent: str | None, preview: str
) -> str:
    """Format incoming-start notification while preserving trusted Rich wrapper markup."""
    safe_preview = _sanitize_tool_trace_text(safe_sink, preview)
    if source_agent:
        safe_source_agent = _sanitize_tool_trace_text(safe_sink, source_agent)
        return (
            f"[{_ASSISTANT_HEADER_STYLE}]▶ INCOMING from {safe_source_agent}:[/] "
            f"[{_ASSISTANT_BODY_STYLE}]{safe_preview}...[/]"
        )
    safe_source = _sanitize_tool_trace_text(safe_sink, source)
    return (
        f"[{_ASSISTANT_HEADER_STYLE}]▶ INCOMING ({safe_source}):[/] "
        f"[{_ASSISTANT_BODY_STYLE}]{safe_preview}...[/]"
    )


def _format_incoming_response_sent_line(
    safe_sink: SafeSink, preview: str, ellipsis: str
) -> str:
    """Format incoming-end success notification with SafeSink sanitization."""
    safe_preview = _sanitize_tool_trace_text(safe_sink, preview)
    return (
        f"[{_TOOL_RESULT_HEADER_STYLE}]✓ Response sent:[/] "
        f"[{_TOOL_RESULT_BODY_STYLE}]{safe_preview}{ellipsis}[/]"
    )


def _format_turn_cancelled_status_line(safe_sink: SafeSink, cancel_reason: str) -> str:
    """Format post-turn cancelled status while preserving trusted Rich wrapper markup."""
    safe_reason = _sanitize_tool_trace_text(safe_sink, cancel_reason)
    return f"[bright_yellow]● {safe_reason}[/]"


def _format_turn_completed_status_line(safe_sink: SafeSink, turn_duration: float) -> str:
    """Format post-turn completion status while preserving trusted Rich wrapper markup."""
    duration_text = f"{turn_duration:.1f}s"
    safe_duration = _sanitize_tool_trace_text(safe_sink, duration_text)
    return f"[dim]Turn completed in {safe_duration}[/]"


def _format_thought_duration_line(safe_sink: SafeSink, duration_seconds: object) -> str:
    """Format reasoning-duration trace line while preserving trusted Rich wrapper markup."""
    safe_duration = _sanitize_tool_trace_text(safe_sink, str(duration_seconds))
    return (
        f"  [{_ASSISTANT_HEADER_STYLE}]●[/] "
        f"[dim {_ASSISTANT_BODY_STYLE}]Thought for {safe_duration}s[/]"
    )


def _format_repl_error_line(safe_sink: SafeSink, message: str) -> str:
    """Format REPL error line while preserving trusted Rich wrapper markup."""
    safe_message = _sanitize_tool_trace_text(safe_sink, message)
    return f"[red]Error:[/] {safe_message}"


def _format_server_failed_to_start_line(safe_sink: SafeSink, port: object) -> str:
    """Format startup-timeout line while preserving trusted Rich wrapper markup."""
    safe_port = _sanitize_tool_trace_text(safe_sink, str(port))
    return f"[red]Error:[/] Server failed to start on port {safe_port}"


def _format_port_in_use_by_other_service_line(safe_sink: SafeSink, port: object) -> str:
    """Format occupied-port line while preserving trusted Rich wrapper markup."""
    safe_port = _sanitize_tool_trace_text(safe_sink, str(port))
    return f"[red]Error:[/] Port {safe_port} is in use by another service"


def _format_console_codepage_warning_line(safe_sink: SafeSink, codepage: object) -> str:
    """Format Windows codepage warning while preserving trusted Rich wrapper markup."""
    safe_codepage = _sanitize_tool_trace_text(safe_sink, str(codepage))
    return f"[yellow]Console code page is {safe_codepage}[/], not UTF-8 (65001)."


def _format_autosave_error_line(safe_sink: SafeSink, error: str) -> str:
    """Format auto-save failure line while preserving trusted Rich wrapper markup."""
    safe_error = _sanitize_tool_trace_text(safe_sink, error)
    return f"[dim red]Auto-save failed: {safe_error}[/]"


def _format_embedded_rpc_listening_line(safe_sink: SafeSink, server_url: str) -> str:
    """Format embedded RPC listening startup line with SafeSink sanitization."""
    safe_server_url = _sanitize_tool_trace_text(safe_sink, server_url)
    return f"[dim]Embedded RPC listening: {safe_server_url}[/]"


def _format_server_log_line(safe_sink: SafeSink, server_log_path: str) -> str:
    """Format server-log startup line with SafeSink sanitization."""
    safe_server_log_path = _sanitize_tool_trace_text(safe_sink, server_log_path)
    return f"[dim]Server log: {safe_server_log_path}[/]"


def _format_repl_startup_metadata_line(safe_sink: SafeSink, label: str, value: str) -> str:
    """Format startup metadata label/value line with SafeSink sanitization."""
    safe_value = _sanitize_tool_trace_text(safe_sink, value)
    return f"{label}: {safe_value}"


def _format_repl_context_metadata_line(
    safe_sink: SafeSink, context_path: str, layer_name: str
) -> str:
    """Format startup context metadata line with SafeSink sanitization."""
    safe_path = _sanitize_tool_trace_text(safe_sink, context_path)
    safe_layer_name = _sanitize_tool_trace_text(safe_sink, layer_name)
    return f"Context: {safe_path} ({safe_layer_name})"


def _format_created_agent_line(safe_sink: SafeSink, agent_id: str) -> str:
    """Format created-agent status line while preserving trusted Rich wrapper markup."""
    safe_agent_id = _sanitize_tool_trace_text(safe_sink, agent_id)
    return f"[dim]Created agent: {safe_agent_id}[/]"


def _format_created_agent_success_line(safe_sink: SafeSink, agent_id: object) -> str:
    """Format created-agent success line for command-result handling."""
    safe_agent_id = _sanitize_tool_trace_text(safe_sink, str(agent_id))
    return f"Created agent: {safe_agent_id}"


def _format_switched_agent_line(safe_sink: SafeSink, agent_id: object) -> str:
    """Format switch-agent status line for command-result handling."""
    safe_agent_id = _sanitize_tool_trace_text(safe_sink, str(agent_id))
    return f"Switched to: {safe_agent_id}"


def _format_restored_session_line(
    safe_sink: SafeSink, agent_id: object, message_count: object
) -> str:
    """Format restored-session status line for command-result handling."""
    safe_agent_id = _sanitize_tool_trace_text(safe_sink, str(agent_id))
    safe_message_count = _sanitize_tool_trace_text(safe_sink, str(message_count))
    return f"Restored session: {safe_agent_id} ({safe_message_count} messages)"


def _format_whisper_mode_line(safe_sink: SafeSink, agent_id: object) -> str:
    """Format whisper-mode entry line while preserving trusted Rich wrapper markup."""
    safe_agent_id = _sanitize_tool_trace_text(safe_sink, str(agent_id))
    return f"[dim]┌── whisper mode: {safe_agent_id} ── /over to return ──┐[/]"


def _format_whisper_return_line(safe_sink: SafeSink, agent_id: object) -> str:
    """Format whisper-mode exit line while preserving trusted Rich wrapper markup."""
    safe_agent_id = _sanitize_tool_trace_text(safe_sink, str(agent_id))
    return f"[dim]└── returned to {safe_agent_id} ────────────────────────────────┘[/]"


def _format_shutdown_server_line(safe_sink: SafeSink, server_url: str) -> str:
    """Format shutdown-start status line while preserving trusted Rich wrapper markup."""
    safe_server_url = _sanitize_tool_trace_text(safe_sink, server_url)
    return f"[dim]Shutting down server at {safe_server_url}...[/]"


def _format_shutdown_warning_line(safe_sink: SafeSink, error: str) -> str:
    """Format shutdown warning line while preserving trusted Rich wrapper markup."""
    safe_error = _sanitize_tool_trace_text(safe_sink, error)
    return f"[yellow]Warning: Server shutdown may have failed: {safe_error}[/]"


def _format_invalid_port_spec_line(safe_sink: SafeSink, error: str) -> str:
    """Format invalid-port-spec line while preserving trusted Rich wrapper markup."""
    safe_error = _sanitize_tool_trace_text(safe_sink, error)
    return f"[red]Invalid port specification:[/] {safe_error}"


def _format_provider_initialization_failed_line(safe_sink: SafeSink, message: str) -> str:
    """Format provider-init failure line while preserving trusted Rich wrapper markup."""
    safe_message = _sanitize_tool_trace_text(safe_sink, message)
    return f"[red]Provider initialization failed:[/]\n{safe_message}"


def _format_warning_message_line(safe_sink: SafeSink, message: str) -> str:
    """Format yellow message line while preserving trusted Rich wrapper markup."""
    safe_message = _sanitize_tool_trace_text(safe_sink, message)
    return f"[yellow]{safe_message}[/]"


def _format_red_message_line(safe_sink: SafeSink, message: str) -> str:
    """Format red message line while preserving trusted Rich wrapper markup."""
    safe_message = _sanitize_tool_trace_text(safe_sink, message)
    return f"[red]{safe_message}[/]"


def _format_plain_message_line(safe_sink: SafeSink, message: str) -> str:
    """Format plain message line with SafeSink sanitization."""
    return _sanitize_tool_trace_text(safe_sink, message)


def _format_connecting_line(safe_sink: SafeSink, agent_url: str) -> str:
    """Format connect-start line while preserving trusted text wrapper."""
    safe_agent_url = _sanitize_tool_trace_text(safe_sink, agent_url)
    return f"Connecting to {safe_agent_url}..."


def _format_connected_tokens_line(safe_sink: SafeSink, total: object, available: object) -> str:
    """Format connected-token status line while preserving trusted text wrapper."""
    safe_total = _sanitize_tool_trace_text(safe_sink, str(total))
    safe_available = _sanitize_tool_trace_text(safe_sink, str(available))
    return f"Connected. Tokens: {safe_total}/{safe_available}"


def _format_client_metadata_line(safe_sink: SafeSink, label: str, value: object) -> str:
    """Format client metadata line while preserving trusted text wrapper."""
    safe_value = _sanitize_tool_trace_text(safe_sink, str(value))
    return f"{label}: {safe_value}"


def _format_scanned_ports_line(safe_sink: SafeSink, ports: list[int]) -> str:
    """Format scanned-ports line while preserving trusted Rich wrapper markup."""
    safe_ports = _sanitize_tool_trace_text(safe_sink, str(ports))
    return f"[dim]Scanned ports: {safe_ports}[/]"


def _format_scanning_additional_ports_line(safe_sink: SafeSink, count: object) -> str:
    """Format add-ports scan status line while preserving trusted Rich wrapper markup."""
    safe_count = _sanitize_tool_trace_text(safe_sink, str(count))
    return f"[dim]Scanning {safe_count} additional ports...[/]"


def _format_unknown_rpc_command_line(safe_sink: SafeSink, rpc_cmd: object) -> str:
    """Format unknown-rpc-command line while preserving trusted text wrapper."""
    safe_rpc_cmd = _sanitize_tool_trace_text(safe_sink, str(rpc_cmd))
    return f"Unknown rpc command: {safe_rpc_cmd}"


def _format_reload_watching_line(safe_sink: SafeSink, watch_path: Path) -> str:
    """Format reload-watch startup line while preserving trusted text wrapper."""
    safe_watch_path = _sanitize_tool_trace_text(safe_sink, str(watch_path))
    return f"[reload] Watching {safe_watch_path} for changes..."


def _format_reload_starting_line(safe_sink: SafeSink, port: object) -> str:
    """Format reload-start startup line while preserving trusted text wrapper."""
    safe_port = _sanitize_tool_trace_text(safe_sink, str(port))
    return f"[reload] Starting server on port {safe_port}"


def _format_reload_detected_changes_line(safe_sink: SafeSink, changes: object) -> str:
    """Format reload-change callback line while preserving trusted text wrapper."""
    safe_changes = _sanitize_tool_trace_text(safe_sink, str(changes))
    return f"[reload] Detected changes: {safe_changes}"
