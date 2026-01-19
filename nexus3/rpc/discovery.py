"""Multi-server discovery for NEXUS3 RPC servers.

This module provides utilities to discover and probe multiple NEXUS3 servers
across a range of ports. It supports:

1. Port specification parsing (e.g., "8765", "8765,9000", "9000-9050")
2. Token file discovery across ~/.nexus3/
3. Concurrent server probing with authentication status detection

Example usage:
    from nexus3.rpc.discovery import discover_servers, parse_port_spec

    # Parse port specification
    ports = parse_port_spec("8765,9000-9005")  # [8765, 9000, 9001, ..., 9005]

    # Discover all servers
    servers = await discover_servers(ports)
    for server in servers:
        if server.detection == DetectionResult.NEXUS_SERVER:
            print(f"Found NEXUS3 at {server.base_url}")
            if server.agents:
                print(f"  Agents: {[a['agent_id'] for a in server.agents]}")
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import httpx

from nexus3.core.constants import get_nexus_dir
from nexus3.rpc.auth import check_token_file_permissions
from nexus3.rpc.detection import DetectionResult


class AuthStatus(Enum):
    """Authentication status for a discovered server.

    Attributes:
        OK: Authentication succeeded (200 response with valid token).
        REQUIRED: Server requires authentication but no valid token provided (401).
        INVALID_TOKEN: Token was provided but rejected (403).
        DISABLED: Server does not require authentication.
    """

    OK = "ok"
    REQUIRED = "required"
    INVALID_TOKEN = "invalid_token"
    DISABLED = "disabled"


@dataclass(frozen=True)
class DiscoveredServer:
    """Result of probing a single server.

    Attributes:
        host: The host address (e.g., "127.0.0.1").
        port: The port number (e.g., 8765).
        base_url: The full base URL (e.g., "http://127.0.0.1:8765").
        detection: The detection result (NEXUS_SERVER, NO_SERVER, etc.).
        auth: Authentication status (None if not a NEXUS_SERVER).
        agents: List of agent info dicts from list_agents (None if unavailable).
        token_path: Path to the token file used (if any).
        token_present: Whether a token file exists for this port.
        error: Human-readable error message (None if no error).
    """

    host: str
    port: int
    base_url: str
    detection: DetectionResult
    auth: AuthStatus | None
    agents: list[dict[str, Any]] | None
    token_path: Path | None
    token_present: bool
    error: str | None


def parse_port_spec(spec: str) -> list[int]:
    """Parse a port specification string into a sorted list of unique ports.

    Supports multiple formats:
    - Single port: "8765"
    - Comma-separated: "8765,9000,9001"
    - Range: "9000-9050"
    - Mixed: "8765,9000-9005,10000"

    Args:
        spec: The port specification string to parse.

    Returns:
        A sorted list of unique port numbers.

    Raises:
        ValueError: If the specification contains invalid port numbers or syntax.

    Example:
        >>> parse_port_spec("8765")
        [8765]
        >>> parse_port_spec("8765,9000")
        [8765, 9000]
        >>> parse_port_spec("9000-9005")
        [9000, 9001, 9002, 9003, 9004, 9005]
        >>> parse_port_spec("8765,9000-9002")
        [8765, 9000, 9001, 9002]
    """
    if not spec or not spec.strip():
        raise ValueError("Port specification cannot be empty")

    ports: set[int] = set()
    parts = spec.split(",")

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Check for range (e.g., "9000-9050")
        if "-" in part:
            # Handle potential negative numbers and ranges
            match = re.match(r"^(\d+)-(\d+)$", part)
            if not match:
                raise ValueError(f"Invalid port range: {part!r}")

            start_str, end_str = match.groups()
            start = int(start_str)
            end = int(end_str)

            if start > end:
                raise ValueError(f"Invalid port range (start > end): {part!r}")
            if start < 1 or end > 65535:
                raise ValueError(f"Port numbers must be between 1 and 65535: {part!r}")
            if end - start > 1000:
                raise ValueError(f"Port range too large (max 1000 ports): {part!r}")

            ports.update(range(start, end + 1))
        else:
            # Single port
            try:
                port = int(part)
            except ValueError as e:
                raise ValueError(f"Invalid port number: {part!r}") from e

            if port < 1 or port > 65535:
                raise ValueError(f"Port number must be between 1 and 65535: {port}")

            ports.add(port)

    if not ports:
        raise ValueError("No valid ports in specification")

    return sorted(ports)


def discover_token_ports(nexus_dir: Path | None = None) -> dict[int, Path]:
    """Scan the NEXUS3 directory for token files and map them to ports.

    Token files follow the naming convention:
    - rpc.token -> port 8765 (default)
    - rpc-{port}.token -> specific port

    Args:
        nexus_dir: The NEXUS3 configuration directory. Defaults to ~/.nexus3.

    Returns:
        A dict mapping port numbers to token file paths.
        Only includes files that exist and have secure permissions.

    Example:
        >>> tokens = discover_token_ports()
        >>> tokens  # doctest: +SKIP
        {8765: Path('~/.nexus3/rpc.token'), 9000: Path('~/.nexus3/rpc-9000.token')}
    """
    nexus_dir = nexus_dir or get_nexus_dir()
    result: dict[int, Path] = {}

    if not nexus_dir.is_dir():
        return result

    # Check default token file (rpc.token -> port 8765)
    default_token = nexus_dir / "rpc.token"
    if default_token.is_file():
        try:
            # Check permissions (non-strict - just skip insecure files)
            if check_token_file_permissions(default_token, strict=False):
                result[8765] = default_token
        except OSError:
            pass  # Skip files we can't access

    # Check port-specific token files (rpc-{port}.token)
    for token_file in nexus_dir.glob("rpc-*.token"):
        # Extract port from filename
        match = re.match(r"rpc-(\d+)\.token$", token_file.name)
        if match:
            try:
                port = int(match.group(1))
                if 1 <= port <= 65535:
                    # Check permissions (non-strict - just skip insecure files)
                    if check_token_file_permissions(token_file, strict=False):
                        result[port] = token_file
            except (ValueError, OSError):
                pass  # Skip invalid or inaccessible files

    return result


def _get_token_path_for_port(port: int, nexus_dir: Path) -> Path:
    """Get the expected token file path for a given port.

    Args:
        port: The port number.
        nexus_dir: The NEXUS3 configuration directory.

    Returns:
        Path to the token file (may or may not exist).
    """
    if port == 8765:
        return nexus_dir / "rpc.token"
    else:
        return nexus_dir / f"rpc-{port}.token"


def _read_token(token_path: Path) -> str | None:
    """Read a token from a file, returning None if unavailable or insecure.

    Checks file permissions before reading to avoid using tokens that may
    have been compromised due to insecure permissions.

    Args:
        token_path: Path to the token file.

    Returns:
        The token string, or None if the file doesn't exist, is unreadable,
        or has insecure permissions.
    """
    try:
        if not token_path.is_file():
            return None
        # Check permissions before reading (refuse insecure token files)
        if not check_token_file_permissions(token_path, strict=False):
            return None
        return token_path.read_text(encoding="utf-8").strip() or None
    except OSError:
        pass
    return None


async def probe_server(
    port: int,
    host: str = "127.0.0.1",
    timeout: float = 0.5,
    token_path: Path | None = None,
) -> DiscoveredServer:
    """Probe a single server to determine if it's a NEXUS3 server.

    Sends a `list_agents` JSON-RPC request to the specified host:port.
    Analyzes the response to determine:
    - Whether it's a NEXUS3 server
    - Authentication status
    - List of agents (if accessible)

    Args:
        port: The port to probe.
        host: The host to probe. Defaults to "127.0.0.1".
        timeout: Request timeout in seconds. Defaults to 0.5.
        token_path: Path to a token file to use for authentication.
                    If None, attempts to auto-discover based on port.

    Returns:
        A DiscoveredServer with all available information about the server.

    Example:
        >>> server = await probe_server(8765)
        >>> if server.detection == DetectionResult.NEXUS_SERVER:
        ...     print(f"Found server with {len(server.agents or [])} agents")
    """
    base_url = f"http://{host}:{port}"
    url = f"{base_url}/"
    nexus_dir = get_nexus_dir()

    # Determine token path and read token
    if token_path is None:
        token_path = _get_token_path_for_port(port, nexus_dir)

    token_present = token_path.is_file() if token_path else False
    token = _read_token(token_path) if token_path else None

    # Build headers
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Build JSON-RPC request
    request_body = '{"jsonrpc":"2.0","method":"list_agents","id":1}'

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, content=request_body, headers=headers)

            return _analyze_probe_response(
                response=response,
                host=host,
                port=port,
                base_url=base_url,
                token_path=token_path,
                token_present=token_present,
            )

    except httpx.ConnectError:
        return DiscoveredServer(
            host=host,
            port=port,
            base_url=base_url,
            detection=DetectionResult.NO_SERVER,
            auth=None,
            agents=None,
            token_path=token_path,
            token_present=token_present,
            error=None,
        )

    except httpx.TimeoutException:
        return DiscoveredServer(
            host=host,
            port=port,
            base_url=base_url,
            detection=DetectionResult.TIMEOUT,
            auth=None,
            agents=None,
            token_path=token_path,
            token_present=token_present,
            error="Connection timed out",
        )

    except Exception as e:
        return DiscoveredServer(
            host=host,
            port=port,
            base_url=base_url,
            detection=DetectionResult.ERROR,
            auth=None,
            agents=None,
            token_path=token_path,
            token_present=token_present,
            error=str(e),
        )


def _analyze_probe_response(
    response: httpx.Response,
    host: str,
    port: int,
    base_url: str,
    token_path: Path | None,
    token_present: bool,
) -> DiscoveredServer:
    """Analyze an HTTP response to extract server information.

    Args:
        response: The HTTP response from the probe.
        host: The host that was probed.
        port: The port that was probed.
        base_url: The base URL of the server.
        token_path: The token file path used (if any).
        token_present: Whether a token file exists for this port.

    Returns:
        A DiscoveredServer with detection result and extracted information.
    """
    # Handle authentication errors
    if response.status_code == 401:
        return DiscoveredServer(
            host=host,
            port=port,
            base_url=base_url,
            detection=DetectionResult.NEXUS_SERVER,
            auth=AuthStatus.REQUIRED,
            agents=None,
            token_path=token_path,
            token_present=token_present,
            error="Authentication required",
        )

    if response.status_code == 403:
        return DiscoveredServer(
            host=host,
            port=port,
            base_url=base_url,
            detection=DetectionResult.NEXUS_SERVER,
            auth=AuthStatus.INVALID_TOKEN,
            agents=None,
            token_path=token_path,
            token_present=token_present,
            error="Invalid or expired token",
        )

    # Try to parse JSON response
    try:
        data = response.json()
    except Exception:
        return DiscoveredServer(
            host=host,
            port=port,
            base_url=base_url,
            detection=DetectionResult.OTHER_SERVICE,
            auth=None,
            agents=None,
            token_path=token_path,
            token_present=token_present,
            error="Invalid JSON response",
        )

    # Validate JSON-RPC structure
    if not isinstance(data, dict):
        return DiscoveredServer(
            host=host,
            port=port,
            base_url=base_url,
            detection=DetectionResult.OTHER_SERVICE,
            auth=None,
            agents=None,
            token_path=token_path,
            token_present=token_present,
            error="Response is not a JSON object",
        )

    if data.get("jsonrpc") != "2.0":
        return DiscoveredServer(
            host=host,
            port=port,
            base_url=base_url,
            detection=DetectionResult.OTHER_SERVICE,
            auth=None,
            agents=None,
            token_path=token_path,
            token_present=token_present,
            error="Not a JSON-RPC 2.0 response",
        )

    if "id" not in data:
        return DiscoveredServer(
            host=host,
            port=port,
            base_url=base_url,
            detection=DetectionResult.OTHER_SERVICE,
            auth=None,
            agents=None,
            token_path=token_path,
            token_present=token_present,
            error="Response missing 'id' field",
        )

    # Check for result or error
    has_result = "result" in data
    has_error = "error" in data

    if has_result == has_error:  # Both true or both false
        return DiscoveredServer(
            host=host,
            port=port,
            base_url=base_url,
            detection=DetectionResult.OTHER_SERVICE,
            auth=None,
            agents=None,
            token_path=token_path,
            token_present=token_present,
            error="Invalid JSON-RPC response structure",
        )

    # Handle JSON-RPC error response
    if has_error:
        error = data.get("error", {})
        error_msg = error.get("message", "Unknown error") if isinstance(error, dict) else str(error)
        return DiscoveredServer(
            host=host,
            port=port,
            base_url=base_url,
            detection=DetectionResult.NEXUS_SERVER,
            auth=AuthStatus.DISABLED if not token_present else AuthStatus.OK,
            agents=None,
            token_path=token_path,
            token_present=token_present,
            error=f"JSON-RPC error: {error_msg}",
        )

    # Validate result structure for list_agents
    result = data.get("result")
    if not isinstance(result, dict) or "agents" not in result:
        return DiscoveredServer(
            host=host,
            port=port,
            base_url=base_url,
            detection=DetectionResult.OTHER_SERVICE,
            auth=None,
            agents=None,
            token_path=token_path,
            token_present=token_present,
            error="Response missing 'agents' in result",
        )

    agents = result.get("agents")
    if not isinstance(agents, list):
        return DiscoveredServer(
            host=host,
            port=port,
            base_url=base_url,
            detection=DetectionResult.OTHER_SERVICE,
            auth=None,
            agents=None,
            token_path=token_path,
            token_present=token_present,
            error="'agents' is not a list",
        )

    # Success - valid NEXUS3 server with agents list
    # Determine auth status based on whether we used a token
    auth_status = AuthStatus.DISABLED if not token_present else AuthStatus.OK

    return DiscoveredServer(
        host=host,
        port=port,
        base_url=base_url,
        detection=DetectionResult.NEXUS_SERVER,
        auth=auth_status,
        agents=agents,
        token_path=token_path,
        token_present=token_present,
        error=None,
    )


async def discover_servers(
    ports: list[int],
    host: str = "127.0.0.1",
    timeout: float = 0.5,
    max_concurrency: int = 50,
) -> list[DiscoveredServer]:
    """Discover NEXUS3 servers across multiple ports concurrently.

    Probes all specified ports in parallel (up to max_concurrency at once)
    and returns information about each server found.

    Args:
        ports: List of port numbers to probe.
        host: The host to probe. Defaults to "127.0.0.1".
        timeout: Request timeout per probe in seconds. Defaults to 0.5.
        max_concurrency: Maximum number of concurrent probes. Defaults to 50.

    Returns:
        A list of DiscoveredServer results, one per port, in port order.

    Example:
        >>> ports = parse_port_spec("8765,9000-9010")
        >>> servers = await discover_servers(ports)
        >>> nexus_servers = [s for s in servers if s.detection == DetectionResult.NEXUS_SERVER]
        >>> print(f"Found {len(nexus_servers)} NEXUS3 servers")
    """
    if not ports:
        return []

    # Auto-discover token paths
    nexus_dir = get_nexus_dir()
    token_ports = discover_token_ports(nexus_dir)

    # Create semaphore for concurrency control
    semaphore = asyncio.Semaphore(max_concurrency)

    async def probe_with_semaphore(port: int) -> DiscoveredServer:
        async with semaphore:
            # Use discovered token path if available, otherwise compute expected path
            token_path = token_ports.get(port) or _get_token_path_for_port(port, nexus_dir)
            return await probe_server(
                port=port,
                host=host,
                timeout=timeout,
                token_path=token_path,
            )

    # Probe all ports concurrently
    tasks = [probe_with_semaphore(port) for port in ports]
    results = await asyncio.gather(*tasks)

    # Results are already in port order (same order as input)
    return list(results)
