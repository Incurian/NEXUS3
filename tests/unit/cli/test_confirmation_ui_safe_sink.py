"""Focused tests for SafeSink-backed confirmation UI output."""

from __future__ import annotations

import asyncio
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from nexus3.cli import confirmation_ui
from nexus3.core.permissions import ConfirmationResult
from nexus3.core.types import ToolCall


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


class _FakeStdout:
    def __init__(self) -> None:
        self.writes: list[str] = []

    def write(self, text: str) -> int:
        self.writes.append(text)
        return len(text)

    def flush(self) -> None:
        return None


class _PromptingRichConsole:
    def __init__(self, response: str) -> None:
        self._response = response
        self._buffer = StringIO()
        self._console = Console(file=self._buffer, force_terminal=False, width=120)
        self.input_prompts: list[str] = []

    def print(self, *args: object, **kwargs: object) -> None:
        self._console.print(*args, **kwargs)

    def input(self, prompt: str) -> str:
        self.input_prompts.append(prompt)
        return self._response

    def rendered(self) -> str:
        return self._buffer.getvalue()


async def _to_thread_inline(func, /, *args, **kwargs):
    return func(*args, **kwargs)


@pytest.mark.asyncio
async def test_confirm_tool_action_mcp_sanitizes_untrusted_fields(monkeypatch) -> None:
    fake_console = _FakeConsole(response="4")
    fake_stdout = _FakeStdout()
    monkeypatch.setattr(confirmation_ui, "get_console", lambda: fake_console)
    monkeypatch.setattr(confirmation_ui.asyncio, "to_thread", _to_thread_inline)
    monkeypatch.setattr(confirmation_ui.sys, "stdout", fake_stdout)

    pause_event = asyncio.Event()
    pause_event.set()
    pause_ack_event = asyncio.Event()
    pause_ack_event.set()

    tool_call = ToolCall(
        id="call_1",
        name="mcp_[bold]srv[/bold]\x1b[31m_[red]tool[/red]\x1b]8;;https://example.com\x07x\x1b]8;;\x07",
        arguments={"arg": "[link=https://bad]arg[/link]\x1b[2J"},
    )

    result = await confirmation_ui.confirm_tool_action(
        tool_call=tool_call,
        target_path=None,
        agent_cwd=Path("/tmp"),
        pause_event=pause_event,
        pause_ack_event=pause_ack_event,
    )

    rendered = "\n".join(fake_console.print_calls)

    assert result == ConfirmationResult.DENY
    assert pause_event.is_set()
    assert "[yellow]Allow MCP tool '" in rendered
    assert "  [dim]Server:[/] " in rendered
    assert "\\[bold]srv\\[/bold]" in rendered
    assert "\\[red]tool\\[/red]x" in rendered
    assert "\\[link=https://bad]arg\\[/link]" in rendered
    assert "\x1b" not in rendered


@pytest.mark.asyncio
async def test_confirm_tool_action_exec_choice_parity_with_sanitized_preview(monkeypatch) -> None:
    fake_console = _FakeConsole(response="2")
    fake_stdout = _FakeStdout()
    monkeypatch.setattr(confirmation_ui, "get_console", lambda: fake_console)
    monkeypatch.setattr(confirmation_ui.asyncio, "to_thread", _to_thread_inline)
    monkeypatch.setattr(confirmation_ui.sys, "stdout", fake_stdout)

    pause_event = asyncio.Event()
    pause_event.set()
    pause_ack_event = asyncio.Event()
    pause_ack_event.set()

    tool_call = ToolCall(
        id="call_2",
        name="exec",
        arguments={
            "program": "echo [red]hi[/red]\x1b[2J",
            "args": ["hello", "[blue]x[/blue]\x1b[2J"],
            "cwd": "/tmp/[bold]work[/bold]\x1b[31m",
        },
    )

    result = await confirmation_ui.confirm_tool_action(
        tool_call=tool_call,
        target_path=None,
        agent_cwd=Path("/tmp"),
        pause_event=pause_event,
        pause_ack_event=pause_ack_event,
    )

    rendered = "\n".join(fake_console.print_calls)

    assert result == ConfirmationResult.ALLOW_EXEC_CWD
    assert "[yellow]Execute " in rendered
    assert "  [dim]Program:[/] " in rendered
    assert "  [dim]Args:[/] " in rendered
    assert "  [cyan][2][/] Allow this command in this directory" in rendered
    assert "echo \\[red]hi\\[/red]" in rendered
    assert "hello \\[blue]x\\[/blue]" in rendered
    assert "/tmp/\\[bold]work\\[/bold]" in rendered
    assert "\x1b" not in rendered


@pytest.mark.asyncio
async def test_confirm_tool_action_shell_unsafe_shows_shell_choice(monkeypatch) -> None:
    fake_console = _FakeConsole(response="2")
    fake_stdout = _FakeStdout()
    monkeypatch.setattr(confirmation_ui, "get_console", lambda: fake_console)
    monkeypatch.setattr(confirmation_ui.asyncio, "to_thread", _to_thread_inline)
    monkeypatch.setattr(confirmation_ui.sys, "stdout", fake_stdout)

    pause_event = asyncio.Event()
    pause_event.set()
    pause_ack_event = asyncio.Event()
    pause_ack_event.set()

    tool_call = ToolCall(
        id="call_2b",
        name="shell_UNSAFE",
        arguments={
            "command": "echo [red]hi[/red]\x1b[2J",
            "shell": "pwsh",
            "cwd": "/tmp/[bold]work[/bold]\x1b[31m",
        },
    )

    result = await confirmation_ui.confirm_tool_action(
        tool_call=tool_call,
        target_path=None,
        agent_cwd=Path("/tmp"),
        pause_event=pause_event,
        pause_ack_event=pause_ack_event,
    )

    rendered = "\n".join(fake_console.print_calls)

    assert result == ConfirmationResult.DENY
    assert "  [dim]Shell:[/] " in rendered
    assert "pwsh" in rendered
    assert "\x1b" not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_call", "target_path", "response", "expected_result", "expected_text"),
    [
        (
            ToolCall(id="call_mcp", name="mcp_server_tool", arguments={"arg": "x"}),
            None,
            "4",
            ConfirmationResult.DENY,
            "Allow MCP tool 'mcp_server_tool'?",
        ),
        (
            ToolCall(
                id="call_exec",
                name="exec",
                arguments={"program": "echo", "args": ["hi"], "cwd": "/tmp"},
            ),
            None,
            "3",
            ConfirmationResult.DENY,
            "Execute exec?",
        ),
        (
            ToolCall(id="call_nexus", name="nexus_send", arguments={"agent_id": "worker-1"}),
            None,
            "4",
            ConfirmationResult.DENY,
            "Allow nexus_send?",
        ),
        (
            ToolCall(id="call_file", name="read_file", arguments={"path": "/tmp/example.txt"}),
            Path("/tmp/example.txt"),
            "4",
            ConfirmationResult.DENY,
            "Allow read_file?",
        ),
    ],
    ids=["mcp", "exec", "nexus", "file"],
)
async def test_confirm_tool_action_header_markup_renders_with_real_rich_console(
    monkeypatch,
    tool_call: ToolCall,
    target_path: Path | None,
    response: str,
    expected_result: ConfirmationResult,
    expected_text: str,
) -> None:
    rich_console = _PromptingRichConsole(response=response)
    fake_stdout = _FakeStdout()
    monkeypatch.setattr(confirmation_ui, "get_console", lambda: rich_console)
    monkeypatch.setattr(confirmation_ui.asyncio, "to_thread", _to_thread_inline)
    monkeypatch.setattr(confirmation_ui.sys, "stdout", fake_stdout)

    pause_event = asyncio.Event()
    pause_event.set()
    pause_ack_event = asyncio.Event()
    pause_ack_event.set()

    result = await confirmation_ui.confirm_tool_action(
        tool_call=tool_call,
        target_path=target_path,
        agent_cwd=Path("/tmp"),
        pause_event=pause_event,
        pause_ack_event=pause_ack_event,
    )

    assert result == expected_result
    assert expected_text in rich_console.rendered()


def test_format_tool_params_sanitizes_markup_and_terminal_escapes() -> None:
    rendered = confirmation_ui.format_tool_params(
        {
            "path": "/tmp/[bold]x.py[/bold]\x1b[31m",
            "content": "[red]boom[/red]\x1b]8;;https://evil\x07x\x1b]8;;\x07",
        },
        max_length=200,
    )

    assert "path=/tmp/\\[bold]x.py\\[/bold]" in rendered
    assert "content=\\[red]boom\\[/red]x" in rendered
    assert "\x1b" not in rendered


def test_format_full_tool_details_sanitizes_untrusted_values() -> None:
    tool_call = ToolCall(
        id="call_\x1b[31m1",
        name="exec\x1b]8;;https://evil\x07x\x1b]8;;\x07",
        arguments={
            "program": "echo [red]x[/red]\x1b[2J",
            "path": "/tmp/\x1b[31mbad",
        },
    )
    rendered = confirmation_ui._format_full_tool_details(
        tool_call=tool_call,
        target_path=Path("/tmp/[bold]target[/bold]\x1b[31m"),
        agent_cwd=Path("/repo/\x1b[31mwork"),
    )

    assert "Tool: execx" in rendered
    assert "Call ID: call_1" in rendered
    assert "Target Path: /tmp/[bold]target[/bold]" in rendered
    assert "Working Directory: /repo/work" in rendered
    assert "program: echo [red]x[/red]" in rendered
    assert "path: /tmp/bad" in rendered
    assert "\x1b" not in rendered
