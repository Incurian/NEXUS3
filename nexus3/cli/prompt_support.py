"""Prompt-session helpers for shell-specific input limitations."""

from __future__ import annotations

from typing import Any

from prompt_toolkit import PromptSession

from nexus3.core.shell_detection import (
    has_git_bash_prompt_limitations,
    supports_live_escape_cancel,
)


def create_prompt_session(**kwargs: Any) -> PromptSession[str]:
    """Create a prompt session with shell-appropriate editor fallback settings."""
    return PromptSession(
        enable_open_in_editor=has_git_bash_prompt_limitations(),
        **kwargs,
    )


def get_main_repl_command_hint() -> str:
    """Return the main REPL command hint for the current input backend."""
    if supports_live_escape_cancel():
        return "Commands: /help | ESC to cancel"
    return "Commands: /help | /cancel to cancel"


def get_git_bash_input_warning_lines(*, include_cancel_hint: bool) -> tuple[str, ...]:
    """Return startup warnings for Git Bash standalone input limitations."""
    if not has_git_bash_prompt_limitations():
        return ()

    if include_cancel_hint:
        return (
            "[yellow]Detected Git Bash standalone[/] - ESC cancel is unavailable here.",
            "[dim]Multiline paste may submit the first line; prefer Windows "
            "Terminal/PowerShell or use C-X C-E to compose in an editor.[/]",
        )

    return (
        "[yellow]Detected Git Bash standalone[/] - multiline paste may submit the first line.",
        "[dim]Prefer Windows Terminal/PowerShell or use C-X C-E to compose in an editor.[/]",
    )
