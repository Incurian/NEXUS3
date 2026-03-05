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
    _format_created_agent_line,
    _format_embedded_rpc_listening_line,
    _format_incoming_response_sent_line,
    _format_incoming_started_line,
    _format_invalid_port_spec_line,
    _format_plain_message_line,
    _format_provider_initialization_failed_line,
    _format_red_message_line,
    _format_reload_detected_changes_line,
    _format_reload_starting_line,
    _format_reload_watching_line,
    _format_repl_context_metadata_line,
    _format_repl_error_line,
    _format_repl_startup_metadata_line,
    _format_scanned_ports_line,
    _format_server_log_line,
    _format_shutdown_server_line,
    _format_shutdown_warning_line,
    _format_tool_call_trace_line,
    _format_tool_error_trace_line,
    _format_tool_halt_trace_line,
    _format_tool_response_trace_line,
    _format_tool_result_trace_line,
    _format_turn_cancelled_status_line,
    _format_turn_completed_status_line,
    _format_unknown_rpc_command_line,
    _format_warning_message_line,
)
from nexus3.display.safe_sink import SafeSink


def _make_sink() -> SafeSink:
    return SafeSink(MagicMock(spec=Console))


def test_tool_call_trace_line_sanitizes_untrusted_name_and_params() -> None:
    sink = _make_sink()

    line = _format_tool_call_trace_line(
        sink,
        name="[red]exec[/red]\x1b[31m",
        params="path=\\[bold]/tmp/x\\[/bold]\x1b]8;;https://evil\x07x\x1b]8;;\x07",
    )

    assert line == "  [cyan]●[/] \\[red]exec\\[/red]: path=\\[bold]/tmp/x\\[/bold]x"
    assert "\x1b" not in line


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

    assert preview_line == "      [green]→[/] \\[bold]ok\\[/bold] (1.2s)"
    assert done_line == "      [green]→[/] done"


def test_tool_response_trace_line_sanitizes_preview_with_wrapper_parity() -> None:
    sink = _make_sink()

    line = _format_tool_response_trace_line(
        sink,
        preview="[cyan]reply[/cyan]\x1b[2J",
        ellipsis="...",
    )

    assert line == "      [dim cyan]↳ Response: \\[cyan]reply\\[/cyan]...[/]"
    assert "\x1b" not in line


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
    )
    without_params = _format_tool_halt_trace_line(
        sink,
        name="[i]wait[/i]\x1b[31m",
        params="",
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

    assert line == (
        "[bold cyan]▶ INCOMING from \\[cyan]agent-2\\[/cyan]:[/] \\[bold]hello\\[/bold]..."
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

    assert line == "[bold cyan]▶ INCOMING (\\[magenta]rpc\\[/magenta]x):[/] preview..."
    assert "\x1b" not in line


def test_incoming_response_sent_line_sanitizes_preview_and_keeps_ellipsis() -> None:
    sink = _make_sink()

    line = _format_incoming_response_sent_line(
        sink,
        preview="[green]sent[/green]\x1b[31m",
        ellipsis="...",
    )

    assert line == "[bold green]✓ Response sent:[/] \\[green]sent\\[/green]..."
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
