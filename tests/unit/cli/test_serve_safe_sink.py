"""Focused tests for SafeSink-backed formatting helpers in serve mode."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from rich.console import Console

from nexus3.cli.serve import (
    _format_serve_config_error_line,
    _format_serve_connect_hint_line,
    _format_serve_existing_server_line,
    _format_serve_other_service_line,
    _format_serve_server_log_line,
    _format_serve_session_logs_line,
    _format_serve_token_file_line,
    _format_serve_url_line,
)
from nexus3.display.safe_sink import SafeSink


def _make_sink() -> SafeSink:
    return SafeSink(MagicMock(spec=Console))


def test_serve_port_lines_preserve_wording() -> None:
    sink = _make_sink()

    existing = _format_serve_existing_server_line(sink, 8765)
    connect_hint = _format_serve_connect_hint_line(sink, 8765)
    other_service = _format_serve_other_service_line(sink, 8765)
    url_line = _format_serve_url_line(sink, 8765)

    assert existing == "Error: NEXUS3 server already running on port 8765"
    assert connect_hint == "Use 'nexus3 --connect http://localhost:8765' to connect to it"
    assert other_service == "Error: Port 8765 is already in use by another service"
    assert url_line == "Server: http://127.0.0.1:8765"


def test_serve_dynamic_message_and_paths_are_sanitized() -> None:
    sink = _make_sink()

    config_error = _format_serve_config_error_line(
        sink, "[red]bad config[/red]\x1b[31m"
    )
    token_line = _format_serve_token_file_line(
        sink, Path("/tmp/[bold]token[/bold]\x1b[2J")
    )
    server_log_line = _format_serve_server_log_line(
        sink, Path("/tmp/[red]server.log[/red]\x1b[31m")
    )
    session_logs_line = _format_serve_session_logs_line(
        sink, Path("/tmp/[cyan]logs[/cyan]\x1b]8;;https://evil\x07x\x1b]8;;\x07")
    )

    assert config_error == "Configuration error: \\[red]bad config\\[/red]"
    assert token_line == "Token file: /tmp/\\[bold]token\\[/bold]"
    assert server_log_line == "Server log: /tmp/\\[red]server.log\\[/red]"
    assert session_logs_line == "Session logs: /tmp/\\[cyan]logs\\[/cyan]x"
    assert "\x1b" not in config_error
    assert "\x1b" not in token_line
    assert "\x1b" not in server_log_line
    assert "\x1b" not in session_logs_line
