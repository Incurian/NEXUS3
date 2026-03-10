"""Runtime/client-discovery helpers for the REPL CLI."""

from __future__ import annotations

import argparse

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.lexers import SimpleLexer
from prompt_toolkit.styles import Style

from nexus3.cli.connect_lobby import ConnectAction, ConnectResult, show_connect_lobby
from nexus3.cli.prompt_support import (
    create_prompt_session,
    get_git_bash_input_warning_lines,
)
from nexus3.cli.repl_formatting import (
    _format_client_metadata_line,
    _format_connected_tokens_line,
    _format_connecting_line,
    _format_created_agent_line,
    _format_invalid_port_spec_line,
    _format_repl_error_line,
    _format_scanned_ports_line,
    _format_scanning_additional_ports_line,
)
from nexus3.core.errors import NexusError
from nexus3.display import get_console
from nexus3.display.safe_sink import SafeSink
from nexus3.rpc.detection import DetectionResult
from nexus3.rpc.discovery import discover_servers, discover_token_ports, parse_port_spec


def _resolve_server_url(server_url: str | None, default_port: int) -> str:
    """Resolve a connect-lobby server URL with a local-port fallback."""
    return server_url or f"http://127.0.0.1:{default_port}"


async def _create_agent_if_requested(
    *,
    result: ConnectResult,
    server_url: str,
    api_key: str | None,
    safe_sink: SafeSink,
) -> bool:
    """Create the selected agent before connecting when requested."""
    if not result.create_agent or not result.agent_id:
        return True

    try:
        from nexus3.client import NexusClient

        url = f"{server_url}/"
        if api_key:
            client = NexusClient(url, api_key=api_key)
        else:
            client = NexusClient.with_auto_auth(url)
        async with client:
            await client.create_agent(result.agent_id)
        safe_sink.console.print(_format_created_agent_line(safe_sink, result.agent_id))
        return True
    except Exception as e:
        safe_sink.console.print(_format_repl_error_line(safe_sink, f"Failed to create agent: {e}"))
        return False


async def connect_from_lobby_result(
    *,
    result: ConnectResult,
    default_port: int,
    fallback_api_key: str | None,
    safe_sink: SafeSink,
) -> bool:
    """Create/connect from a connect-lobby selection.

    Returns:
        True when connection flow was started, False when pre-connect setup failed.
    """
    server_url = _resolve_server_url(result.server_url, default_port)
    api_key = result.api_key or fallback_api_key

    created = await _create_agent_if_requested(
        result=result,
        server_url=server_url,
        api_key=api_key,
        safe_sink=safe_sink,
    )
    if not created:
        return False

    await run_repl_client(server_url, result.agent_id or "main", api_key=api_key)
    return True


async def run_repl_client(url: str, agent_id: str, api_key: str | None = None) -> None:
    """Run REPL as client to a remote Nexus server.

    Args:
        url: Base URL of the server (e.g., http://127.0.0.1:8765)
        agent_id: ID of the agent to connect to
        api_key: Optional API key for authentication. If None, uses auto-discovery.
    """
    from nexus3.client import ClientError, NexusClient

    console = get_console()
    safe_sink = SafeSink(console)

    # Build agent URL
    agent_url = f"{url.rstrip('/')}/agent/{agent_id}"

    console.print("[bold]NEXUS3 Client[/]")
    console.print(_format_connecting_line(safe_sink, agent_url))

    # Simple prompt session with styled input (no bottom toolbar for simplicity)
    lexer = SimpleLexer("class:input-field")
    style = Style.from_dict({"prompt": "reverse", "input-field": "reverse"})
    prompt_session: PromptSession[str] = create_prompt_session(
        lexer=lexer,
        style=style,
    )

    # Use provided API key if given, otherwise auto-discover
    try:
        if api_key:
            client_ctx = NexusClient(agent_url, api_key=api_key, timeout=300.0)
        else:
            client_ctx = NexusClient.with_auto_auth(agent_url, timeout=300.0)
    except ValueError as e:
        console.print(_format_repl_error_line(safe_sink, f"Invalid URL: {e}"))
        return

    async with client_ctx as client:
        # Test connection
        try:
            status = await client.get_tokens()
            total = status.get("total", 0)
            avail = status.get("available", status.get("budget", 0))
            console.print(_format_connected_tokens_line(safe_sink, total, avail))
        except ClientError as e:
            console.print(_format_repl_error_line(safe_sink, f"Connection failed: {e}"))
            return

        for line in get_git_bash_input_warning_lines(include_cancel_hint=False):
            console.print(line, style="dim")

        console.print("Commands: /quit | /status")
        console.print("")

        while True:
            try:
                user_input = await prompt_session.prompt_async(
                    HTML("<style class='prompt'>> </style>")
                )

                if not user_input.strip():
                    continue

                # Handle local commands
                if user_input.strip() in ("/quit", "/q", "/exit"):
                    console.print("Disconnecting.", style="dim")
                    break

                if user_input.strip() == "/status":
                    try:
                        tokens = await client.get_tokens()
                        context = await client.get_context()
                        console.print(_format_client_metadata_line(safe_sink, "Tokens", tokens))
                        console.print(_format_client_metadata_line(safe_sink, "Context", context))
                    except ClientError as e:
                        console.print(_format_repl_error_line(safe_sink, str(e)))
                    continue

                # Send message to agent
                console.print("")  # Visual separation
                try:
                    result = await client.send(user_input)
                    if "content" in result:
                        safe_sink.print_untrusted(str(result["content"]))
                    elif "cancelled" in result:
                        console.print("[yellow]Request was cancelled[/]")
                    console.print("")  # Visual separation
                except ClientError as e:
                    console.print(_format_repl_error_line(safe_sink, str(e)))
                    console.print("")

            except KeyboardInterrupt:
                console.print("")
                console.print("Use /quit to exit.", style="dim")
                continue
            except EOFError:
                console.print("")
                console.print("Disconnecting.", style="dim")
                break


async def _run_connect_with_discovery(args: argparse.Namespace) -> None:
    """Run connect mode with server discovery.

    Discovers servers on candidate ports and shows the connect lobby for
    server/agent selection.

    Args:
        args: Parsed command line arguments including scan and api_key.
    """
    from nexus3.config.loader import load_config

    console = get_console()
    safe_sink = SafeSink(console)

    # Load config to get default port
    try:
        config = load_config()
        effective_port = config.server.port
    except NexusError:
        effective_port = 8765

    # Build candidate ports
    candidate_ports: set[int] = {effective_port, 8765}
    candidate_ports.update(discover_token_ports().keys())
    if args.scan:
        try:
            candidate_ports.update(parse_port_spec(args.scan))
        except ValueError as e:
            console.print(_format_invalid_port_spec_line(safe_sink, str(e)))
            return

    # Discovery loop
    while True:
        servers = await discover_servers(sorted(candidate_ports))
        nexus_servers = [s for s in servers if s.detection == DetectionResult.NEXUS_SERVER]

        if not nexus_servers:
            console.print("[dim]No NEXUS3 servers found.[/]")
            console.print(_format_scanned_ports_line(safe_sink, sorted(candidate_ports)))
            return

        # Check if the default port already has a NEXUS server
        default_port_in_use = any(s.port == effective_port for s in nexus_servers)
        result = await show_connect_lobby(
            console, nexus_servers, effective_port, default_port_in_use=default_port_in_use
        )

        if result.action == ConnectAction.CONNECT:
            connected = await connect_from_lobby_result(
                result=result,
                default_port=effective_port,
                fallback_api_key=args.api_key,
                safe_sink=safe_sink,
            )
            if not connected:
                return
            return

        elif result.action == ConnectAction.RESCAN:
            if result.scan_spec:
                try:
                    new_ports = parse_port_spec(result.scan_spec)
                    candidate_ports.update(new_ports)
                    console.print(
                        _format_scanning_additional_ports_line(safe_sink, len(new_ports))
                    )
                except ValueError as e:
                    console.print(_format_invalid_port_spec_line(safe_sink, str(e)))
            continue

        elif result.action == ConnectAction.MANUAL_URL:
            if result.server_url:
                await run_repl_client(
                    result.server_url,
                    result.agent_id or "main",
                    api_key=result.api_key or args.api_key,
                )
                return
            continue

        elif result.action == ConnectAction.QUIT:
            return

        else:
            # START_NEW_SERVER, SHUTDOWN_AND_REPLACE not applicable in pure connect mode
            console.print("[dim]This option is not available in connect mode.[/]")
            console.print("[dim]Use 'nexus3' without --connect to start a server.[/]")
            continue


__all__ = [
    "_run_connect_with_discovery",
    "connect_from_lobby_result",
    "run_repl_client",
]
