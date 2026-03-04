"""Focused tests for SafeSink-backed stderr printing in client commands."""

from __future__ import annotations

from io import StringIO

from nexus3.cli import client_commands


def test_print_error_sanitizes_terminal_escapes(monkeypatch) -> None:
    fake_stderr = StringIO()
    monkeypatch.setattr(client_commands.sys, "stderr", fake_stderr)

    client_commands._print_error("\x1b[31mboom\x1b[0m")

    assert fake_stderr.getvalue() == "Error: boom\n"


def test_print_info_sanitizes_terminal_escapes(monkeypatch) -> None:
    fake_stderr = StringIO()
    monkeypatch.setattr(client_commands.sys, "stderr", fake_stderr)

    client_commands._print_info("\x1b]8;;https://example.com\x07link\x1b]8;;\x07")

    assert fake_stderr.getvalue() == "link\n"
