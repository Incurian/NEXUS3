"""Interactive connect lobby for server/agent selection.

This module provides the connect lobby UI shown when connecting to NEXUS3 servers.
It displays discovered servers and allows users to:

1. Connect to an existing server (select an agent)
2. Start a new embedded server on default port
3. Start a new embedded server on a different port
4. Shutdown an existing server and replace it
5. Scan additional ports
6. Enter a URL manually
7. Quit

Example usage:
    from nexus3.cli.connect_lobby import show_connect_lobby, ConnectResult
    from nexus3.rpc.discovery import discover_servers, parse_port_spec

    servers = await discover_servers(parse_port_spec("8765,9000-9010"))
    result = await show_connect_lobby(console, servers, default_port=8765)

    if result.action == ConnectAction.CONNECT:
        # Connect to result.server_url with result.agent_id
        pass
    elif result.action == ConnectAction.START_DIFFERENT_PORT:
        # Start server on result.port
        pass
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console

    from nexus3.rpc.discovery import DiscoveredServer


class ConnectAction(Enum):
    """Actions available from the connect lobby."""

    CONNECT = "connect"  # Connect to selected server+agent
    START_NEW_SERVER = "start_new"  # Start embedded server
    START_DIFFERENT_PORT = "start_different_port"  # Start on user-specified port
    SHUTDOWN_AND_REPLACE = "shutdown"  # Shutdown selected server then start new
    RESCAN = "rescan"  # Scan more ports
    MANUAL_URL = "manual_url"  # User entered URL manually
    QUIT = "quit"


@dataclass
class ConnectResult:
    """Result from the connect lobby interaction.

    Attributes:
        action: The action the user chose.
        server_url: Base URL of the server (e.g., "http://127.0.0.1:8765").
        agent_id: ID of the agent to connect to.
        port: Port number for starting a new server.
        api_key: API key if user entered one manually.
        scan_spec: Port specification for rescanning (e.g., "9000-9050").
        create_agent: If True, create the agent before connecting.
    """

    action: ConnectAction
    server_url: str | None = None
    agent_id: str | None = None
    port: int | None = None
    api_key: str | None = None
    scan_spec: str | None = None
    create_agent: bool = False


def _format_auth_status(server: DiscoveredServer) -> str:
    """Format authentication status for display.

    Args:
        server: The discovered server.

    Returns:
        A bracketed status string like "[ready]" or "[auth required]".
    """
    from nexus3.rpc.discovery import AuthStatus

    if server.auth is None:
        return "[dim][unknown][/]"

    status_map = {
        AuthStatus.OK: "[green][ready][/]",
        AuthStatus.DISABLED: "[green][no auth][/]",
        AuthStatus.REQUIRED: "[yellow][auth required][/]",
        AuthStatus.INVALID_TOKEN: "[red][token rejected][/]",
    }
    return status_map.get(server.auth, "[dim][unknown][/]")


def _format_agent_count(server: DiscoveredServer) -> str:
    """Format agent count for display.

    Args:
        server: The discovered server.

    Returns:
        A string like "2 agents" or empty string if unknown.
    """
    if server.agents is None:
        return ""

    count = len(server.agents)
    if count == 0:
        return "[dim]no agents[/]"
    elif count == 1:
        return "[dim]1 agent[/]"
    else:
        return f"[dim]{count} agents[/]"


def _get_nexus_servers(servers: list[DiscoveredServer]) -> list[DiscoveredServer]:
    """Filter to only NEXUS3 servers.

    Args:
        servers: List of all discovered servers.

    Returns:
        List of servers that are confirmed NEXUS3 servers.
    """
    from nexus3.rpc.detection import DetectionResult

    return [s for s in servers if s.detection == DetectionResult.NEXUS_SERVER]


async def _show_auth_recovery_menu(
    console: Console,
    server: "DiscoveredServer",
    default_port: int,
) -> ConnectResult | None:
    """Show recovery options when server auth fails.

    Instead of immediately prompting for API key, offer user-friendly options
    that don't require dealing with keys.

    Args:
        console: Rich Console for input/output.
        server: The server with auth issues.
        default_port: Default port for suggesting alternatives.

    Returns:
        ConnectResult with chosen action, or None to go back.
    """
    from nexus3.rpc.discovery import AuthStatus

    console.print()
    console.print(f"[bold]Cannot connect to {server.base_url}[/]")

    # Show diagnostic info - focus on "different server" not "key problem"
    if server.auth == AuthStatus.REQUIRED:
        if server.token_present:
            console.print("[yellow]Credentials don't match the running server.[/]")
        else:
            console.print("[yellow]No credentials found for this server.[/]")
    elif server.auth == AuthStatus.INVALID_TOKEN:
        console.print("[yellow]Credentials don't match the running server.[/]")

    console.print()
    console.print("[dim]This often happens when another process started a server on this port.[/]")
    console.print()

    # Offer recovery options - prioritize actions that don't need keys
    console.print("[dim]Options:[/]")
    console.print("  p) Start a new server on different port (recommended)")
    console.print(f"  r) Replace server on port {server.port} (shutdown and restart)")
    console.print("  k) Enter API key manually (advanced)")
    console.print("  b) Back")
    console.print()

    while True:
        try:
            choice = console.input("Choice: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None

        if choice in ("b", "back"):
            return None

        if choice == "p":
            chosen_port = prompt_for_port(console, default=server.port + 1)
            if chosen_port is not None:
                return ConnectResult(
                    action=ConnectAction.START_DIFFERENT_PORT,
                    port=chosen_port,
                )
            continue

        if choice == "r":
            console.print()
            console.print("[yellow]Note: This requires the server to accept shutdown requests.[/]")
            console.print("[yellow]If the token is invalid, this may fail.[/]")
            try:
                confirm = console.input("Continue anyway? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                continue
            if confirm == "y":
                return ConnectResult(
                    action=ConnectAction.SHUTDOWN_AND_REPLACE,
                    server_url=server.base_url,
                    port=server.port,
                )
            continue

        if choice == "k":
            api_key = prompt_for_api_key(console)
            if api_key is not None:
                return ConnectResult(
                    action=ConnectAction.CONNECT,
                    server_url=server.base_url,
                    api_key=api_key,
                )
            continue

        console.print("[dim]Please enter p, r, k, or b[/]")


async def show_connect_lobby(
    console: Console,
    servers: list[DiscoveredServer],
    default_port: int,
    default_port_in_use: bool = False,
) -> ConnectResult:
    """Show interactive connect lobby for server/agent selection.

    Displays discovered NEXUS3 servers and offers options to:
    - Connect to an existing server (select agent)
    - Start a new embedded server
    - Start embedded server on a different port
    - Scan additional ports
    - Enter a URL manually
    - Quit

    Args:
        console: Rich Console for input/output.
        servers: List of discovered servers from discover_servers().
        default_port: Default port for starting a new server.
        default_port_in_use: Whether the default port already has a server.

    Returns:
        ConnectResult with the user's choice and any associated data.
    """
    from nexus3.rpc.discovery import AuthStatus

    nexus_servers = _get_nexus_servers(servers)

    # Display header
    console.print()
    console.print("[bold]NEXUS3 Connect[/]")
    console.print()

    # Display discovered servers
    if nexus_servers:
        console.print("[dim]Discovered servers:[/]")
        console.print()

        for i, server in enumerate(nexus_servers, 1):
            auth_status = _format_auth_status(server)
            agent_count = _format_agent_count(server)
            parts = [f"  {i}) {server.base_url}", auth_status]
            if agent_count:
                parts.append(agent_count)
            console.print("  ".join(parts))

        console.print()
    else:
        console.print("[dim]No NEXUS3 servers found.[/]")
        console.print()

    # Build menu options
    console.print("[dim]Options:[/]")
    if not default_port_in_use:
        console.print(f"  n) Start embedded server (port {default_port})")
    console.print("  p) Start embedded server on different port...")
    console.print("  s) Scan additional ports...")
    console.print("  u) Connect to URL manually...")
    console.print("  q) Quit")
    console.print()

    # Build valid server choices
    valid_server_nums = set(range(1, len(nexus_servers) + 1))

    while True:
        try:
            choice = console.input("Choice: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return ConnectResult(action=ConnectAction.QUIT)

        # Handle quit
        if choice in ("q", "quit", "exit"):
            return ConnectResult(action=ConnectAction.QUIT)

        # Handle new server on default port (only if port is free)
        if choice == "n" and not default_port_in_use:
            return ConnectResult(
                action=ConnectAction.START_NEW_SERVER,
                port=default_port,
            )

        # Handle new server on different port
        if choice == "p":
            suggested_port = default_port + 1 if default_port_in_use else default_port
            chosen_port = prompt_for_port(console, default=suggested_port)
            if chosen_port is not None:
                return ConnectResult(
                    action=ConnectAction.START_DIFFERENT_PORT,
                    port=chosen_port,
                )
            # User cancelled, re-prompt
            continue

        # Handle scan
        if choice == "s":
            scan_spec = prompt_for_port_spec(console)
            if scan_spec:
                return ConnectResult(
                    action=ConnectAction.RESCAN,
                    scan_spec=scan_spec,
                )
            # User cancelled, re-prompt
            continue

        # Handle manual URL
        if choice == "u":
            url, agent_id = prompt_for_url(console)
            if url:
                return ConnectResult(
                    action=ConnectAction.MANUAL_URL,
                    server_url=url,
                    agent_id=agent_id,
                )
            # User cancelled, re-prompt
            continue

        # Handle server selection by number
        try:
            choice_num = int(choice)
            if choice_num in valid_server_nums:
                server = nexus_servers[choice_num - 1]

                # Check auth status
                if server.auth in (AuthStatus.OK, AuthStatus.DISABLED):
                    # Can proceed to agent selection
                    agent_result = await show_agent_picker(console, server)
                    if agent_result is None:
                        # User went back, re-display menu
                        continue
                    return agent_result

                elif server.auth in (AuthStatus.REQUIRED, AuthStatus.INVALID_TOKEN):
                    # Auth failed - show recovery options instead of prompting for key
                    auth_result = await _show_auth_recovery_menu(
                        console, server, default_port
                    )
                    if auth_result is None:
                        # User went back
                        continue
                    return auth_result
                else:
                    # Unknown auth state, try anyway
                    agent_result = await show_agent_picker(console, server)
                    if agent_result is None:
                        continue
                    return agent_result
        except ValueError:
            pass

        # Invalid input
        if nexus_servers:
            if default_port_in_use:
                console.print(f"[dim]Please enter 1-{len(nexus_servers)}, p, s, u, or q[/]")
            else:
                console.print(f"[dim]Please enter 1-{len(nexus_servers)}, n, p, s, u, or q[/]")
        else:
            if default_port_in_use:
                console.print("[dim]Please enter p, s, u, or q[/]")
            else:
                console.print("[dim]Please enter n, p, s, u, or q[/]")


async def show_agent_picker(
    console: Console,
    server: DiscoveredServer,
) -> ConnectResult | None:
    """Show agent selection menu for a server.

    Displays the list of agents on the server and lets the user pick one,
    create a new agent, or go back.

    Args:
        console: Rich Console for input/output.
        server: The server to select an agent from.

    Returns:
        ConnectResult if user selected/created an agent, or None to go back.
    """
    agents = server.agents or []

    console.print()
    console.print(f"[bold]Agents on {server.base_url}:[/]")
    console.print()

    if agents:
        for i, agent_info in enumerate(agents, 1):
            agent_id = agent_info.get("agent_id", "unknown")
            msg_count = agent_info.get("message_count", 0)
            permission_level = agent_info.get("permission_level", "unknown")
            is_temp = agent_info.get("is_temp", False)

            # Format display
            temp_marker = "[dim](temp)[/] " if is_temp else ""
            console.print(
                f"  {i}) [cyan]{agent_id}[/] {temp_marker}"
                f"[dim]({msg_count} messages, {permission_level})[/]"
            )
    else:
        console.print("  [dim]No agents currently running[/]")

    console.print()
    console.print("  c) Enter agent ID manually")
    console.print("  n) Create new agent")
    console.print(f"  r) Replace server on port {server.port} (shutdown and restart)")
    console.print("  p) Start another server on different port...")
    console.print("  b) Back")
    console.print()

    valid_agent_nums = set(range(1, len(agents) + 1))

    while True:
        try:
            choice = console.input("Choice: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None

        # Handle back
        if choice in ("b", "back"):
            return None

        # Handle manual agent ID
        if choice == "c":
            agent_id = prompt_for_agent_id(console)
            if agent_id:
                return ConnectResult(
                    action=ConnectAction.CONNECT,
                    server_url=server.base_url,
                    agent_id=agent_id,
                )
            continue

        # Handle create new agent
        if choice == "n":
            console.print()
            console.print("[dim]Enter a name for the new agent:[/]")
            agent_id = prompt_for_agent_id(console)
            if agent_id:
                return ConnectResult(
                    action=ConnectAction.CONNECT,
                    server_url=server.base_url,
                    agent_id=agent_id,
                    create_agent=True,  # Tell caller to create before connecting
                )
            # User cancelled, continue loop
            continue

        # Handle restart server (shutdown and replace)
        if choice == "r":
            return ConnectResult(
                action=ConnectAction.SHUTDOWN_AND_REPLACE,
                server_url=server.base_url,
                port=server.port,
            )

        # Handle start another server on different port
        if choice == "p":
            chosen_port = prompt_for_port(console, default=server.port + 1)
            if chosen_port is not None:
                return ConnectResult(
                    action=ConnectAction.START_DIFFERENT_PORT,
                    port=chosen_port,
                )
            # User cancelled, re-prompt
            continue

        # Handle agent selection by number
        try:
            choice_num = int(choice)
            if choice_num in valid_agent_nums:
                agent_info = agents[choice_num - 1]
                agent_id = agent_info.get("agent_id")
                return ConnectResult(
                    action=ConnectAction.CONNECT,
                    server_url=server.base_url,
                    agent_id=agent_id,
                )
        except ValueError:
            pass

        # Invalid input
        if agents:
            console.print(f"[dim]Please enter 1-{len(agents)}, c, n, r, p, or b[/]")
        else:
            console.print("[dim]Please enter c, n, r, p, or b[/]")


def prompt_for_port_spec(console: Console) -> str | None:
    """Prompt user for additional ports to scan.

    Accepts formats like "9000", "9000,9001", or "9000-9050".

    Args:
        console: Rich Console for input/output.

    Returns:
        Port specification string, or None if user cancelled.
    """
    console.print()
    console.print("[dim]Enter ports to scan (e.g., 9000 or 9000-9050 or 8765,9000):[/]")

    try:
        spec = console.input("Ports: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if not spec:
        return None

    # Basic validation - actual parsing happens in discovery
    if not all(c.isdigit() or c in ",-" for c in spec):
        console.print("[red]Invalid port specification[/]")
        return None

    return spec


def prompt_for_port(console: Console, default: int | None = None) -> int | None:
    """Prompt user for a port number.

    Args:
        console: Rich Console for input/output.
        default: Default port to suggest (shown in prompt).

    Returns:
        Port number, or None if user cancelled.
    """
    console.print()
    if default is not None:
        console.print(f"[dim]Enter port number (or press Enter for {default}):[/]")
    else:
        console.print("[dim]Enter port number:[/]")

    try:
        port_str = console.input("Port: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if not port_str:
        return default

    # Validate port number
    try:
        port = int(port_str)
        if 1 <= port <= 65535:
            return port
        else:
            console.print("[red]Port must be between 1 and 65535[/]")
            return None
    except ValueError:
        console.print("[red]Invalid port number[/]")
        return None


def prompt_for_api_key(console: Console) -> str | None:
    """Prompt user for API key.

    Used when connecting to a server that requires authentication.
    Uses getpass to avoid echoing the key to the terminal.

    Args:
        console: Rich Console for input/output.

    Returns:
        API key string, or None if user cancelled.
    """
    import getpass

    console.print()
    console.print("[dim]This server requires authentication.[/]")
    console.print("[dim]Enter the API key (or press Enter to go back):[/]")

    try:
        api_key = getpass.getpass("API Key: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if not api_key:
        return None

    return api_key


def prompt_for_url(console: Console) -> tuple[str | None, str | None]:
    """Prompt for URL and optional agent ID.

    Args:
        console: Rich Console for input/output.

    Returns:
        Tuple of (url, agent_id). Both may be None if user cancelled.
        agent_id may be None even if url is provided (use server default).
    """
    console.print()
    console.print("[dim]Enter server URL (e.g., http://127.0.0.1:8765):[/]")

    try:
        url = console.input("URL: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None, None

    if not url:
        return None, None

    # Normalize URL
    if not url.startswith(("http://", "https://")):
        url = f"http://{url}"

    # Remove trailing slash
    url = url.rstrip("/")

    # Ask for agent ID
    console.print()
    console.print("[dim]Enter agent ID (or press Enter to create new):[/]")

    try:
        agent_id = console.input("Agent ID: ").strip()
    except (EOFError, KeyboardInterrupt):
        return url, None

    return url, agent_id if agent_id else None


def prompt_for_agent_id(console: Console) -> str | None:
    """Prompt for a specific agent ID.

    Args:
        console: Rich Console for input/output.

    Returns:
        Agent ID string, or None if user cancelled.
    """
    console.print()
    console.print("[dim]Enter agent ID:[/]")

    try:
        agent_id = console.input("Agent ID: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if not agent_id:
        return None

    return agent_id
