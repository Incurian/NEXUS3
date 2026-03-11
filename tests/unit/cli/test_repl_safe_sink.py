"""Focused tests for SafeSink-backed tool trace formatting in repl."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from rich.console import Console

from nexus3.cli.repl import (
    _format_autosave_error_line,
    _format_client_metadata_line,
    _format_connected_tokens_line,
    _format_connecting_line,
    _format_console_codepage_warning_line,
    _format_created_agent_line,
    _format_created_agent_success_line,
    _format_embedded_rpc_listening_line,
    _format_incoming_response_sent_line,
    _format_incoming_started_line,
    _format_invalid_port_spec_line,
    _format_mcp_result_preview_lines,
    _format_plain_message_line,
    _format_port_in_use_by_other_service_line,
    _format_provider_initialization_failed_line,
    _format_red_message_line,
    _format_reload_detected_changes_line,
    _format_reload_starting_line,
    _format_reload_watching_line,
    _format_repl_context_metadata_line,
    _format_repl_error_line,
    _format_repl_startup_metadata_line,
    _format_restored_session_line,
    _format_scanned_ports_line,
    _format_scanning_additional_ports_line,
    _format_server_failed_to_start_line,
    _format_server_log_line,
    _format_shutdown_server_line,
    _format_shutdown_warning_line,
    _format_switched_agent_line,
    _format_thought_duration_line,
    _format_tool_call_trace_line,
    _format_tool_error_trace_line,
    _format_tool_halt_trace_line,
    _format_tool_id_header_line,
    _format_tool_response_trace_line,
    _format_tool_result_trace_line,
    _format_turn_cancelled_status_line,
    _format_turn_completed_status_line,
    _format_unknown_rpc_command_line,
    _format_warning_message_line,
    _format_whisper_mode_line,
    _format_whisper_return_line,
    _sanitize_prompt_html_text,
    _summarize_tool_output,
)
from nexus3.cli.repl_commands import print_yolo_warning
from nexus3.display.safe_sink import SafeSink


def _make_sink() -> SafeSink:
    return SafeSink(MagicMock(spec=Console))


class _CaptureConsole:
    def __init__(self) -> None:
        self.print_calls: list[str] = []

    def print(self, content: str = "", **_kwargs: object) -> None:
        self.print_calls.append(content)


def test_print_yolo_warning_keeps_expected_trusted_lines() -> None:
    console = _CaptureConsole()

    print_yolo_warning(console, on_switch=True)

    assert console.print_calls[0].startswith("[bold red]")
    assert console.print_calls[1] == "[bold red]⚠  Switching to YOLO MODE[/]"
    assert console.print_calls[2] == ""
    assert (
        "Enabled: Shell execution, file writes anywhere, network access"
        in console.print_calls[3]
    )
    assert "To switch: /permissions trusted" in console.print_calls[4]
    assert console.print_calls[5].startswith("[bold red]")


def test_tool_call_trace_line_sanitizes_untrusted_name_and_params() -> None:
    sink = _make_sink()

    line = _format_tool_call_trace_line(
        sink,
        name="[red]exec[/red]\x1b[31m",
        params="path=\\[bold]/tmp/x\\[/bold]\x1b]8;;https://evil\x07x\x1b]8;;\x07",
    )

    assert line == (
        "  [bold bright_cyan]●[/] [bold bright_cyan]\\[red]exec\\[/red][/]: "
        "[cyan]path=\\[bold]/tmp/x\\[/bold]x[/]"
    )
    assert "\x1b" not in line


def test_tool_id_header_line_formats_visible_tool_id() -> None:
    sink = _make_sink()

    line = _format_tool_id_header_line(
        sink,
        tool_id="toolu_abc12345",
    )

    assert line == "  [abc12345]"


def test_tool_id_header_line_supports_custom_indent() -> None:
    sink = _make_sink()

    line = _format_tool_id_header_line(
        sink,
        tool_id="toolu_abc12345",
        indent=6,
    )

    assert line == "      [abc12345]"


def test_tool_call_trace_line_omits_inline_visible_tool_id() -> None:
    sink = _make_sink()

    line = _format_tool_call_trace_line(
        sink,
        name="search_text",
        params="path=README.md",
        tool_id="toolu_abc12345",
    )

    assert (
        line
        == "  [bold bright_cyan]●[/] [bold bright_cyan]search_text[/]: [cyan]path=README.md[/]"
    )


def test_sanitize_prompt_html_text_strips_terminal_escapes_and_escapes_html() -> None:
    sanitized = _sanitize_prompt_html_text("</style><b>x</b>&\x1b[31m")

    assert sanitized == "&lt;/style&gt;&lt;b&gt;x&lt;/b&gt;&amp;"
    assert "\x1b" not in sanitized


def test_tool_result_trace_line_sanitizes_preview_and_preserves_done_fallback() -> None:
    sink = _make_sink()

    preview_line = _format_tool_result_trace_line(
        sink,
        result_preview="[bold]ok[/bold]\x1b[31m",
        duration_str=" (1.2s)",
    )
    done_line = _format_tool_result_trace_line(
        sink,
        result_preview="",
        duration_str="",
    )

    assert preview_line == (
        "      [bold bright_green]→[/] [#2c7a4b]\\[bold]ok\\[/bold][/] (1.2s)"
    )
    assert done_line == "      [bold bright_green]→[/] [#2c7a4b]done[/]"


def test_tool_result_trace_line_omits_inline_visible_tool_id() -> None:
    sink = _make_sink()

    line = _format_tool_result_trace_line(
        sink,
        result_preview="2 lines",
        duration_str="",
        tool_id="toolu_abc12345",
    )

    assert line == "      [bold bright_green]→[/] [#2c7a4b]2 lines[/]"


def test_tool_response_trace_line_sanitizes_preview_with_wrapper_parity() -> None:
    sink = _make_sink()

    line = _format_tool_response_trace_line(
        sink,
        preview="[cyan]reply[/cyan]\x1b[2J",
        ellipsis="...",
    )

    assert (
        line
        == "      [bold bright_green]↳ Response:[/] [#2c7a4b]\\[cyan]reply\\[/cyan]...[/]"
    )
    assert "\x1b" not in line


def test_mcp_result_preview_lines_sanitize_and_truncate_preview_block() -> None:
    sink = _make_sink()

    lines = _format_mcp_result_preview_lines(
        sink,
        output="[cyan]line1[/cyan]\x1b[31m\nline2\nline3",
        max_lines=2,
        max_chars=200,
    )

    assert lines == [
        "      [bold bright_green]↳ MCP result preview:[/]",
        "        [#2c7a4b]\\[cyan]line1\\[/cyan][/]",
        "        [#2c7a4b]line2[/]",
        "      [dim]↳ Preview truncated at 2 lines / 200 chars[/]",
    ]
    assert all("\x1b" not in line for line in lines)


def test_summarize_tool_output_uses_line_count_summary_for_mcp_tools() -> None:
    summary = _summarize_tool_output("mcp_test_echo", "alpha\nbeta\n")

    assert summary == "2 lines"


def test_tool_error_trace_line_truncates_and_sanitizes_error_text() -> None:
    sink = _make_sink()
    error = "[red]boom[/red]" + ("x" * 130) + "\x1b[31m"

    line = _format_tool_error_trace_line(sink, error=error, duration_str=" (0.4s)")

    assert line.startswith("      [red]→[/] [red]\\[red]boom\\[/red]")
    assert line.endswith("...[/] (0.4s)")
    assert "\x1b" not in line


def test_tool_halt_trace_line_sanitizes_dynamic_fields_and_preserves_shapes() -> None:
    sink = _make_sink()

    with_params = _format_tool_halt_trace_line(
        sink,
        name="[i]wait[/i]\x1b[31m",
        params="arg=\\[blue]x\\[/blue]\x1b[2J",
        tool_id="toolu_abc12345",
    )
    without_params = _format_tool_halt_trace_line(
        sink,
        name="[i]wait[/i]\x1b[31m",
        params="",
        tool_id="toolu_abc12345",
    )

    assert with_params == (
        "  [dark_orange]●[/] \\[i]wait\\[/i]: arg=\\[blue]x\\[/blue] [dark_orange](halted)[/]"
    )
    assert without_params == "  [dark_orange]●[/] \\[i]wait\\[/i] [dark_orange](halted)[/]"


def test_incoming_started_line_sanitizes_preview_and_source_agent_route() -> None:
    sink = _make_sink()

    line = _format_incoming_started_line(
        sink,
        source="[magenta]rpc[/magenta]",
        source_agent="[cyan]agent-2[/cyan]\x1b[31m",
        preview="[bold]hello[/bold]\x1b[2J",
    )

    assert (
        line
        == "[bold bright_magenta]▶ INCOMING from \\[cyan]agent-2\\[/cyan]:[/] "
        "[magenta]\\[bold]hello\\[/bold]...[/]"
    )
    assert "\x1b" not in line


def test_incoming_started_line_sanitizes_source_for_non_agent_route() -> None:
    sink = _make_sink()

    line = _format_incoming_started_line(
        sink,
        source="[magenta]rpc[/magenta]\x1b]8;;https://evil\x07x\x1b]8;;\x07",
        source_agent=None,
        preview="preview",
    )

    assert (
        line
        == "[bold bright_magenta]▶ INCOMING (\\[magenta]rpc\\[/magenta]x):[/] "
        "[magenta]preview...[/]"
    )
    assert "\x1b" not in line


def test_incoming_response_sent_line_sanitizes_preview_and_keeps_ellipsis() -> None:
    sink = _make_sink()

    line = _format_incoming_response_sent_line(
        sink,
        preview="[green]sent[/green]\x1b[31m",
        ellipsis="...",
    )

    assert (
        line
        == "[bold bright_green]✓ Response sent:[/] [#2c7a4b]\\[green]sent\\[/green]...[/]"
    )
    assert "\x1b" not in line


def test_turn_cancelled_status_line_sanitizes_cancel_reason() -> None:
    sink = _make_sink()

    line = _format_turn_cancelled_status_line(
        sink,
        cancel_reason="Cancelled: [red]exec[/red]\x1b]8;;https://evil\x07x\x1b]8;;\x07",
    )

    assert line == "[bright_yellow]● Cancelled: \\[red]exec\\[/red]x[/]"
    assert "\x1b" not in line


def test_turn_completed_status_line_formats_duration_with_wrapper_parity() -> None:
    sink = _make_sink()

    line = _format_turn_completed_status_line(sink, turn_duration=1.26)

    assert line == "[dim]Turn completed in 1.3s[/]"


def test_thought_duration_line_sanitizes_dynamic_duration() -> None:
    sink = _make_sink()

    line = _format_thought_duration_line(
        sink,
        duration_seconds="[red]3[/red]\x1b[31m",
    )

    assert (
        line
        == "  [bold bright_magenta]●[/] [dim magenta]Thought for \\[red]3\\[/red]s[/]"
    )
    assert "\x1b" not in line


def test_repl_error_line_sanitizes_dynamic_message() -> None:
    sink = _make_sink()

    line = _format_repl_error_line(sink, message="[red]boom[/red]\x1b[31m")

    assert line == "[red]Error:[/] \\[red]boom\\[/red]"
    assert "\x1b" not in line


def test_autosave_error_line_sanitizes_dynamic_error_text() -> None:
    sink = _make_sink()

    line = _format_autosave_error_line(
        sink,
        error="[magenta]disk full[/magenta]\x1b[2J",
    )

    assert line == "[dim red]Auto-save failed: \\[magenta]disk full\\[/magenta][/]"
    assert "\x1b" not in line


def test_embedded_rpc_listening_line_sanitizes_dynamic_url() -> None:
    sink = _make_sink()

    line = _format_embedded_rpc_listening_line(
        sink,
        server_url="http://127.0.0.1:8765/\x1b]8;;https://evil\x07x\x1b]8;;\x07[red]x[/red]",
    )

    assert line == "[dim]Embedded RPC listening: http://127.0.0.1:8765/x\\[red]x\\[/red][/]"
    assert "\x1b" not in line


def test_server_log_line_sanitizes_dynamic_path() -> None:
    sink = _make_sink()

    line = _format_server_log_line(
        sink,
        server_log_path="/tmp/[bold]server.log[/bold]\x1b[2J",
    )

    assert line == "[dim]Server log: /tmp/\\[bold]server.log\\[/bold][/]"
    assert "\x1b" not in line


def test_repl_startup_metadata_line_sanitizes_dynamic_value() -> None:
    sink = _make_sink()

    line = _format_repl_startup_metadata_line(
        sink,
        label="Agent",
        value="[cyan]main[/cyan]\x1b[31m",
    )

    assert line == "Agent: \\[cyan]main\\[/cyan]"
    assert "\x1b" not in line


def test_repl_context_metadata_line_sanitizes_path_and_layer() -> None:
    sink = _make_sink()

    line = _format_repl_context_metadata_line(
        sink,
        context_path="/tmp/[x]\x1b[31m",
        layer_name="[red]workspace[/red]\x1b[2J",
    )

    assert line == "Context: /tmp/\\[x] (\\[red]workspace\\[/red])"
    assert "\x1b" not in line


def test_created_agent_and_shutdown_lines_sanitize_dynamic_fields() -> None:
    sink = _make_sink()

    created = _format_created_agent_line(
        sink, "[cyan]agent-1[/cyan]\x1b]8;;https://evil\x07x\x1b]8;;\x07"
    )
    shutting_down = _format_shutdown_server_line(
        sink, "http://127.0.0.1:8765/\x1b[31m[red]x[/red]"
    )
    warning = _format_shutdown_warning_line(
        sink, "[yellow]warn[/yellow]\x1b[2J"
    )

    assert created == "[dim]Created agent: \\[cyan]agent-1\\[/cyan]x[/]"
    assert shutting_down == "[dim]Shutting down server at http://127.0.0.1:8765/\\[red]x\\[/red]...[/]"
    assert (
        warning
        == "[yellow]Warning: Server shutdown may have failed: \\[yellow]warn\\[/yellow][/]"
    )


def test_command_result_agent_lines_sanitize_dynamic_fields() -> None:
    sink = _make_sink()

    switched = _format_switched_agent_line(
        sink, "[cyan]agent-2[/cyan]\x1b]8;;https://evil\x07x\x1b]8;;\x07"
    )
    restored = _format_restored_session_line(
        sink,
        "[green]sess[/green]\x1b[31m",
        "[red]3[/red]\x1b[2J",
    )
    created = _format_created_agent_success_line(
        sink, "[magenta]new[/magenta]\x1b[31m"
    )
    whisper_mode = _format_whisper_mode_line(
        sink, "[yellow]target[/yellow]\x1b]8;;https://evil\x07x\x1b]8;;\x07"
    )
    whisper_return = _format_whisper_return_line(
        sink, "[blue]main[/blue]\x1b[31m"
    )

    assert switched == "Switched to: \\[cyan]agent-2\\[/cyan]x"
    assert restored == "Restored session: \\[green]sess\\[/green] (\\[red]3\\[/red] messages)"
    assert created == "Created agent: \\[magenta]new\\[/magenta]"
    assert whisper_mode == (
        "[dim]┌── whisper mode: \\[yellow]target\\[/yellow]x ── /over to return ──┐[/]"
    )
    assert whisper_return == (
        "[dim]└── returned to \\[blue]main\\[/blue] ────────────────────────────────┘[/]"
    )


def test_invalid_port_and_provider_failure_lines_sanitize_dynamic_fields() -> None:
    sink = _make_sink()

    invalid_port = _format_invalid_port_spec_line(
        sink, "[red]bad[/red]\x1b]8;;https://evil\x07x\x1b]8;;\x07"
    )
    provider_failed = _format_provider_initialization_failed_line(
        sink, "[magenta]boom[/magenta]\x1b[31m"
    )

    assert invalid_port == "[red]Invalid port specification:[/] \\[red]bad\\[/red]x"
    assert provider_failed == "[red]Provider initialization failed:[/]\n\\[magenta]boom\\[/magenta]"


def test_scanning_additional_ports_and_failed_start_lines_sanitize_dynamic_fields() -> None:
    sink = _make_sink()

    scanning_line = _format_scanning_additional_ports_line(
        sink,
        count="[red]2[/red]\x1b[31m",
    )
    failed_start_line = _format_server_failed_to_start_line(
        sink,
        port="[red]8765[/red]\x1b[2J",
    )

    assert scanning_line == "[dim]Scanning \\[red]2\\[/red] additional ports...[/]"
    assert failed_start_line == "[red]Error:[/] Server failed to start on port \\[red]8765\\[/red]"
    assert "\x1b" not in scanning_line
    assert "\x1b" not in failed_start_line


def test_port_in_use_line_sanitizes_dynamic_port() -> None:
    sink = _make_sink()

    line = _format_port_in_use_by_other_service_line(
        sink,
        port="[red]8765[/red]\x1b[2J",
    )

    assert line == "[red]Error:[/] Port \\[red]8765\\[/red] is in use by another service"
    assert "\x1b" not in line


def test_console_codepage_warning_line_sanitizes_dynamic_codepage() -> None:
    sink = _make_sink()

    line = _format_console_codepage_warning_line(
        sink,
        codepage="[cyan]1252[/cyan]\x1b]8;;https://evil\x07x\x1b]8;;\x07",
    )

    assert line == "[yellow]Console code page is \\[cyan]1252\\[/cyan]x[/], not UTF-8 (65001)."
    assert "\x1b" not in line


def test_warning_and_red_message_lines_sanitize_dynamic_message() -> None:
    sink = _make_sink()

    yellow_line = _format_warning_message_line(
        sink, "[yellow]heads up[/yellow]\x1b[31m"
    )
    red_line = _format_red_message_line(
        sink, "[red]stop[/red]\x1b]8;;https://evil\x07x\x1b]8;;\x07"
    )

    assert yellow_line == "[yellow]\\[yellow]heads up\\[/yellow][/]"
    assert red_line == "[red]\\[red]stop\\[/red]x[/]"


def test_plain_message_line_sanitizes_dynamic_message() -> None:
    sink = _make_sink()

    line = _format_plain_message_line(
        sink, "[red]notice[/red]\x1b]8;;https://evil\x07x\x1b]8;;\x07"
    )

    assert line == "\\[red]notice\\[/red]x"
    assert "\x1b" not in line


def test_client_connect_and_metadata_lines_sanitize_dynamic_fields() -> None:
    sink = _make_sink()

    connecting = _format_connecting_line(
        sink, "http://127.0.0.1:8765/agent/main\x1b[31m[red]x[/red]"
    )
    connected = _format_connected_tokens_line(
        sink,
        "[red]10[/red]\x1b[31m",
        "[cyan]90[/cyan]\x1b]8;;https://evil\x07x\x1b]8;;\x07",
    )
    metadata = _format_client_metadata_line(
        sink,
        "Context",
        {"k": "[bold]v[/bold]"},
    )
    scanned_ports = _format_scanned_ports_line(sink, [8765, 9000])

    assert connecting == "Connecting to http://127.0.0.1:8765/agent/main\\[red]x\\[/red]..."
    assert connected == "Connected. Tokens: \\[red]10\\[/red]/\\[cyan]90\\[/cyan]x"
    assert metadata == "Context: {'k': '\\[bold]v\\[/bold]'}"
    assert scanned_ports == "[dim]Scanned ports: [8765, 9000][/]"


def test_unknown_rpc_command_line_sanitizes_dynamic_command() -> None:
    sink = _make_sink()

    line = _format_unknown_rpc_command_line(
        sink, "[red]bad[/red]\x1b]8;;https://evil\x07x\x1b]8;;\x07"
    )

    assert line == "Unknown rpc command: \\[red]bad\\[/red]x"
    assert "\x1b" not in line


def test_reload_lines_sanitize_dynamic_watch_path_port_and_changes() -> None:
    sink = _make_sink()

    watch_line = _format_reload_watching_line(
        sink, Path("/tmp/[bold]nexus3[/bold]\x1b[31m")
    )
    start_line = _format_reload_starting_line(
        sink, "[red]8765[/red]\x1b[31m"
    )
    changes_line = _format_reload_detected_changes_line(
        sink, ["[red]x.py[/red]\x1b[31m"]
    )

    assert watch_line == "[reload] Watching /tmp/\\[bold]nexus3\\[/bold] for changes..."
    assert start_line == "[reload] Starting server on port \\[red]8765\\[/red]"
    assert changes_line == "[reload] Detected changes: ['\\[red]x.py\\[/red]\\x1b[31m']"
    assert "\x1b" not in watch_line
    assert "\x1b" not in start_line
    assert "\x1b" not in changes_line
