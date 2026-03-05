"""Focused tests for SafeSink-backed tool trace formatting in repl."""

from __future__ import annotations

from unittest.mock import MagicMock

from rich.console import Console

from nexus3.cli.repl import (
    _format_incoming_response_sent_line,
    _format_incoming_started_line,
    _format_tool_call_trace_line,
    _format_tool_error_trace_line,
    _format_tool_halt_trace_line,
    _format_tool_response_trace_line,
    _format_tool_result_trace_line,
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
