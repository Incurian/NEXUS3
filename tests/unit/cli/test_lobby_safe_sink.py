"""Focused tests for SafeSink-backed lobby rendering."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from nexus3.cli.lobby import LobbyChoice, show_lobby, show_session_list


class _FakeConsole:
    def __init__(self, responses: list[str]) -> None:
        self._responses = iter(responses)
        self.print_calls: list[str] = []
        self.input_prompts: list[str] = []

    def print(self, content: str = "", **_kwargs: object) -> None:
        self.print_calls.append(content)

    def input(self, prompt: str) -> str:
        self.input_prompts.append(prompt)
        return next(self._responses)


class _StubSessionManager:
    def __init__(
        self,
        *,
        last_session_info: tuple[object, str] | None = None,
        sessions: list[object] | None = None,
    ) -> None:
        self._last_session_info = last_session_info
        self._sessions = sessions or []

    def load_last_session(self):
        return self._last_session_info

    def list_sessions(self):
        return self._sessions


@pytest.mark.asyncio
async def test_show_lobby_sanitizes_resume_session_name_and_preserves_choice() -> None:
    malicious_name = "[cyan]proj[/cyan]\x1b]8;;https://example.com\x07x\x1b]8;;\x07"
    session = SimpleNamespace(
        modified_at=datetime.now(),
        messages=[{"role": "user", "content": "hello"}],
    )
    manager = _StubSessionManager(last_session_info=(session, malicious_name))
    console = _FakeConsole(responses=["1"])

    result = await show_lobby(manager, console)  # type: ignore[arg-type]

    assert result.choice == LobbyChoice.RESUME
    assert result.session_name == malicious_name

    all_lines = "\n".join(console.print_calls)
    assert "Resume: [cyan]\\[cyan]proj\\[/cyan]x[/]" in all_lines
    assert "\x1b" not in all_lines


@pytest.mark.asyncio
async def test_show_session_list_sanitizes_saved_name_and_count() -> None:
    malicious_name = "[red]saved[/red]\x1b[31m"
    summary = SimpleNamespace(
        name=malicious_name,
        modified_at=datetime.now(),
        message_count="[bold]9[/bold]",
    )
    manager = _StubSessionManager(sessions=[summary])
    console = _FakeConsole(responses=["1"])

    result = await show_session_list(manager, console)  # type: ignore[arg-type]

    assert result == malicious_name

    all_lines = "\n".join(console.print_calls)
    assert "[cyan]\\[red]saved\\[/red][/]" in all_lines
    assert "\\[bold]9\\[/bold] messages" in all_lines
    assert "\x1b" not in all_lines
