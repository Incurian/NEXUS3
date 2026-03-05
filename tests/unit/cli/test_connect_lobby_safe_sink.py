"""Focused tests for SafeSink-backed connect lobby rendering."""

from __future__ import annotations

import pytest

from nexus3.cli.connect_lobby import (
    ConnectAction,
    _format_agent_picker_invalid_choice_line,
    _format_connect_lobby_invalid_choice_line,
    _format_default_port_option_line,
    _format_port_prompt_line,
    _format_replace_server_option_line,
    show_agent_picker,
    show_connect_lobby,
)
from nexus3.rpc.detection import DetectionResult
from nexus3.rpc.discovery import AuthStatus, DiscoveredServer


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


def _server(
    *,
    base_url: str,
    port: int = 8765,
    agents: list[dict[str, object]] | None = None,
    auth: AuthStatus = AuthStatus.OK,
) -> DiscoveredServer:
    return DiscoveredServer(
        host="127.0.0.1",
        port=port,
        base_url=base_url,
        detection=DetectionResult.NEXUS_SERVER,
        auth=auth,
        agents=agents,
        token_path=None,
        token_present=False,
        error=None,
    )


async def _show_connect_lobby(console: _FakeConsole, servers: list[DiscoveredServer]):
    return await show_connect_lobby(
        console=console,
        servers=servers,
        default_port=8765,
        default_port_in_use=False,
    )


async def _show_connect_lobby_with_port(
    console: _FakeConsole,
    servers: list[DiscoveredServer],
    default_port: int,
):
    return await show_connect_lobby(
        console=console,
        servers=servers,
        default_port=default_port,
        default_port_in_use=False,
    )


async def _show_agent_picker(console: _FakeConsole, server: DiscoveredServer):
    return await show_agent_picker(console=console, server=server, occupied_ports={8765})


@pytest.mark.asyncio
async def test_show_connect_lobby_sanitizes_discovered_server_base_url() -> None:
    console = _FakeConsole(responses=["q"])
    malicious_url = "[bold]srv[/bold]\x1b]8;;https://example.com\x07x\x1b]8;;\x07"

    result = await _show_connect_lobby(console, [_server(base_url=malicious_url)])

    assert result.action == ConnectAction.QUIT
    all_lines = "\n".join(console.print_calls)
    assert "  1) \\[bold]srv\\[/bold]x" in all_lines
    assert "[dim]Discovered servers:[/]" in all_lines
    assert "\x1b" not in all_lines


@pytest.mark.asyncio
async def test_show_connect_lobby_sanitizes_default_port_option_line() -> None:
    class _MaliciousPort(int):
        def __str__(self) -> str:
            return "[bold]8765[/bold]\x1b]8;;https://example.com\x07x\x1b]8;;\x07"

    console = _FakeConsole(responses=["q"])
    result = await _show_connect_lobby_with_port(console, [], _MaliciousPort(8765))

    assert result.action == ConnectAction.QUIT
    all_lines = "\n".join(console.print_calls)
    assert r"n) Start embedded server (port \[bold]8765\[/bold]x)" in all_lines
    assert "\x1b" not in all_lines


def test_connect_lobby_option_helpers_sanitize_dynamic_values() -> None:
    class _MaliciousPort(int):
        def __str__(self) -> str:
            return "[bold]8765[/bold]\x1b]8;;https://example.com\x07x\x1b]8;;\x07"

    assert _format_default_port_option_line(_MaliciousPort(8765)) == (
        r"  n) Start embedded server (port \[bold]8765\[/bold]x)"
    )
    assert _format_replace_server_option_line(_MaliciousPort(8765)) == (
        r"  r) Replace server on port \[bold]8765\[/bold]x (shutdown and restart)"
    )
    assert _format_port_prompt_line(_MaliciousPort(8765)) == (
        r"[dim]Enter port number (or press Enter for \[bold]8765\[/bold]x):[/]"
    )


def test_connect_lobby_invalid_choice_helpers_sanitize_dynamic_values() -> None:
    class _MaliciousCount(int):
        def __str__(self) -> str:
            return "2[/]\x1b]8;;https://example.com\x07x\x1b]8;;\x07"

    with_default = _format_connect_lobby_invalid_choice_line(
        _MaliciousCount(2), include_default_port_option=True
    )
    without_default = _format_connect_lobby_invalid_choice_line(
        _MaliciousCount(2), include_default_port_option=False
    )
    picker = _format_agent_picker_invalid_choice_line(_MaliciousCount(2))

    assert with_default == r"[dim]Please enter 1-2\[/]x, n, p, s, u, or q[/]"
    assert without_default == r"[dim]Please enter 1-2\[/]x, p, s, u, or q[/]"
    assert picker == r"[dim]Please enter 1-2\[/]x, c, n, r, p, or b[/]"
    assert "\x1b" not in with_default
    assert "\x1b" not in without_default
    assert "\x1b" not in picker


@pytest.mark.asyncio
async def test_show_agent_picker_sanitizes_dynamic_fields_and_keeps_selection_behavior() -> None:
    console = _FakeConsole(responses=["1"])
    malicious_agent_id = "[bold]agent[/bold]\x1b]8;;https://example.com\x07x\x1b]8;;\x07"
    server = _server(
        base_url="http://127.0.0.1:8765",
        agents=[
            {
                "agent_id": malicious_agent_id,
                "message_count": "7[/]msg",
                "permission_level": "[red]admin[/red]\x1b[31m",
                "is_temp": False,
            }
        ],
    )

    result = await _show_agent_picker(console, server)

    assert result is not None
    assert result.action == ConnectAction.CONNECT
    assert result.agent_id == malicious_agent_id

    all_lines = "\n".join(console.print_calls)
    assert "[cyan]\\[bold]agent\\[/bold]x[/]" in all_lines
    assert "7\\[/]msg messages, \\[red]admin\\[/red]" in all_lines
    assert "\x1b" not in all_lines
