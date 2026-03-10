"""Tests for shell-aware prompt support helpers."""

from __future__ import annotations

from prompt_toolkit.lexers import SimpleLexer
from prompt_toolkit.styles import Style

from nexus3.cli.prompt_support import (
    create_prompt_session,
    get_git_bash_input_warning_lines,
    get_main_repl_command_hint,
)


def test_main_repl_command_hint_uses_escape_when_supported(monkeypatch) -> None:
    monkeypatch.setattr(
        "nexus3.cli.prompt_support.supports_live_escape_cancel",
        lambda: True,
    )

    assert get_main_repl_command_hint() == "Commands: /help | ESC to cancel"


def test_main_repl_command_hint_uses_cancel_when_escape_unsupported(monkeypatch) -> None:
    monkeypatch.setattr(
        "nexus3.cli.prompt_support.supports_live_escape_cancel",
        lambda: False,
    )

    assert get_main_repl_command_hint() == "Commands: /help | /cancel to cancel"


def test_git_bash_input_warning_lines_include_editor_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        "nexus3.cli.prompt_support.has_git_bash_prompt_limitations",
        lambda: True,
    )

    warnings = get_git_bash_input_warning_lines(include_cancel_hint=True)

    assert len(warnings) == 2
    assert "ESC cancel is unavailable" in warnings[0]
    assert "C-X C-E" in warnings[1]


def test_git_bash_input_warning_lines_empty_when_not_needed(monkeypatch) -> None:
    monkeypatch.setattr(
        "nexus3.cli.prompt_support.has_git_bash_prompt_limitations",
        lambda: False,
    )

    assert get_git_bash_input_warning_lines(include_cancel_hint=False) == ()


def test_prompt_session_enables_open_in_editor_for_git_bash(monkeypatch) -> None:
    monkeypatch.setattr(
        "nexus3.cli.prompt_support.has_git_bash_prompt_limitations",
        lambda: True,
    )

    session = create_prompt_session(
        lexer=SimpleLexer("class:input-field"),
        style=Style.from_dict({"input-field": ""}),
    )

    assert session.enable_open_in_editor is True


def test_prompt_session_disables_open_in_editor_by_default(monkeypatch) -> None:
    monkeypatch.setattr(
        "nexus3.cli.prompt_support.has_git_bash_prompt_limitations",
        lambda: False,
    )

    session = create_prompt_session(
        lexer=SimpleLexer("class:input-field"),
        style=Style.from_dict({"input-field": ""}),
    )

    assert session.enable_open_in_editor is False
