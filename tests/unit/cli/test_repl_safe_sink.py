"""Focused tests for SafeSink-backed tool trace formatting in repl."""

from __future__ import annotations

from unittest.mock import MagicMock

from rich.console import Console

from nexus3.cli.repl import (
    _format_autosave_error_line,
    _format_embedded_rpc_listening_line,
    _format_incoming_response_sent_line,
    _format_incoming_started_line,
    _format_repl_context_metadata_line,
    _format_repl_error_line,
    _format_repl_startup_metadata_line,
    _format_server_log_line,
    _format_tool_call_trace_line,
    _format_tool_error_trace_line,
    _format_tool_halt_trace_line,
    _format_tool_response_trace_line,
    _format_tool_result_trace_line,
    _format_turn_cancelled_status_line,
    _format_turn_completed_status_line,
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
