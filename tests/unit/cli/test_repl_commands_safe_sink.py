"""Focused tests for SafeSink-backed MCP consent prompts in repl commands."""

from __future__ import annotations

import asyncio

import pytest

from nexus3.cli import repl_commands


class _FakeConsole:
    def __init__(self, response: str) -> None:
        self._response = response
        self.print_calls: list[str] = []
        self.input_prompts: list[str] = []

    def print(self, content: str = "", **_kwargs: object) -> None:
        self.print_calls.append(content)

    def input(self, prompt: str) -> str:
        self.input_prompts.append(prompt)
        return self._response


async def _to_thread_inline(func, /, *args, **kwargs):
    return func(*args, **kwargs)


@pytest.mark.asyncio
async def test_mcp_connection_consent_sanitizes_server_and_tool_names(monkeypatch) -> None:
    fake_console = _FakeConsole(response="3")
    monkeypatch.setattr(repl_commands, "get_console", lambda: fake_console)
    monkeypatch.setattr(asyncio, "to_thread", _to_thread_inline)

    proceed, allow_all = await repl_commands._mcp_connection_consent(
        server_name="[bold]srv[/bold]\x1b[31m",
        tool_names=[
            "safe_tool",
            "[red]tool[/red]\x1b]8;;https://example.com\x07x\x1b]8;;\x07",
        ],
    )

    assert (proceed, allow_all) == (False, False)
    assert fake_console.input_prompts == ["\n[dim]Choice [1-3]:[/] "]

    first_line = fake_console.print_calls[0]
    second_line = fake_console.print_calls[1]
    all_lines = "\n".join(fake_console.print_calls)

    assert "Connect to MCP server '\\[bold]srv\\[/bold]'?" in first_line
    assert "safe_tool, \\[red]tool\\[/red]x" in second_line
    assert "\x1b" not in all_lines


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("1", (True, True)),
        ("2", (True, False)),
        ("3", (False, False)),
    ],
)
async def test_mcp_connection_consent_choice_behavior_preserved(
    monkeypatch, response: str, expected: tuple[bool, bool]
) -> None:
    fake_console = _FakeConsole(response=response)
    monkeypatch.setattr(repl_commands, "get_console", lambda: fake_console)
    monkeypatch.setattr(asyncio, "to_thread", _to_thread_inline)

    result = await repl_commands._mcp_connection_consent(
        server_name="trusted-name",
        tool_names=["a", "b"],
    )

    assert result == expected
