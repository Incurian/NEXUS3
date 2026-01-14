"""Server collision detection for NEXUS3.

This module provides utilities to detect if a NEXUS3 server is already running
on a given port before starting a new one. This is essential for:

1. The unified REPL (5R.1.0): Auto-connecting if a server exists, or starting embedded
2. Preventing port conflicts when running `nexus3 --serve`
3. Integration tests waiting for server startup

Detection Strategy:
    Send a `list_agents` JSON-RPC request to the port. This is the NEXUS3 fingerprint:
    - Valid JSON-RPC response with agents list -> NEXUS_SERVER
    - Connection refused -> NO_SERVER
    - Invalid/non-JSON-RPC response -> OTHER_SERVICE
    - Timeout -> TIMEOUT
    - Other error -> ERROR

Example usage:
    from nexus3.rpc.detection import detect_server, DetectionResult

    result = await detect_server(8765)
    if result == DetectionResult.NO_SERVER:
        # Safe to start a new server
        pass
    elif result == DetectionResult.NEXUS_SERVER:
        # Connect to existing server
        pass
"""

import asyncio
from enum import Enum

import httpx

from nexus3.rpc.auth import discover_rpc_token
from nexus3.rpc.protocol import serialize_request
from nexus3.rpc.types import Request


class DetectionResult(Enum):
    """Result of server detection probe.

    Attributes:
        NO_SERVER: Port is free, no service listening.
        NEXUS_SERVER: A NEXUS3 server was detected on the port.
        OTHER_SERVICE: Something else is running on the port (not NEXUS3).
        TIMEOUT: Connection attempt timed out.
        ERROR: An unexpected error occurred during detection.
    """

    NO_SERVER = "no_server"
    NEXUS_SERVER = "nexus_server"
    OTHER_SERVICE = "other_service"
    TIMEOUT = "timeout"
    ERROR = "error"


async def detect_server(
    port: int,
    host: str = "127.0.0.1",
    timeout: float = 2.0,
) -> DetectionResult:
    """Detect if a NEXUS3 server is running on the specified port.

    Attempts to connect to the given host:port and sends a `list_agents`
    JSON-RPC request. This method is the fingerprint for identifying
    NEXUS3 servers, as it's a global method that always exists.

    Args:
        port: The port to probe.
        host: The host to probe. Defaults to localhost.
        timeout: Connection/request timeout in seconds. Defaults to 2.0.

    Returns:
        DetectionResult indicating what was found on the port:
        - NO_SERVER: Port is free (connection refused)
        - NEXUS_SERVER: Valid NEXUS3 server detected
        - OTHER_SERVICE: Something else is running (HTTP but not NEXUS3)
        - TIMEOUT: Connection timed out
        - ERROR: Other error occurred

    Example:
        result = await detect_server(8765)
        if result == DetectionResult.NEXUS_SERVER:
            print("NEXUS3 server already running!")
    """
    url = f"http://{host}:{port}/"

    # Build the list_agents request - this is our NEXUS3 fingerprint
    request = Request(
        jsonrpc="2.0",
        method="list_agents",
        params=None,
        id=1,
    )

    # Try to discover token for authenticated request
    headers: dict[str, str] = {"Content-Type": "application/json"}
    api_key = discover_rpc_token(port=port)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                content=serialize_request(request),
                headers=headers,
            )

            # Got an HTTP response - now determine if it's NEXUS3
            return _analyze_response(response)

    except httpx.ConnectError:
        # Connection refused = no server on this port
        return DetectionResult.NO_SERVER

    except httpx.TimeoutException:
        # Connection or read timed out
        return DetectionResult.TIMEOUT

    except Exception:
        # Any other error (DNS failure, etc.)
        return DetectionResult.ERROR


def _analyze_response(response: httpx.Response) -> DetectionResult:
    """Analyze an HTTP response to determine if it's from a NEXUS3 server.

    A valid NEXUS3 response to list_agents will be JSON-RPC 2.0 with
    a result containing an "agents" key (list of agent info dicts).

    We also treat 401 (Unauthorized) and 403 (Forbidden) as NEXUS_SERVER,
    since that indicates an auth-protected server (likely NEXUS3).

    Args:
        response: The HTTP response to analyze.

    Returns:
        NEXUS_SERVER if the response matches NEXUS3 format or is auth error,
        OTHER_SERVICE otherwise.
    """
    # Auth errors likely mean NEXUS3 server requiring auth
    if response.status_code in (401, 403):
        return DetectionResult.NEXUS_SERVER

    try:
        # Must be valid JSON
        data = response.json()
    except Exception:
        return DetectionResult.OTHER_SERVICE

    # Must be a dict (JSON object)
    if not isinstance(data, dict):
        return DetectionResult.OTHER_SERVICE

    # Must have jsonrpc field = "2.0"
    if data.get("jsonrpc") != "2.0":
        return DetectionResult.OTHER_SERVICE

    # Must have an "id" field (we sent id=1)
    if "id" not in data:
        return DetectionResult.OTHER_SERVICE

    # Must have either "result" or "error" (but not both)
    has_result = "result" in data
    has_error = "error" in data

    if has_result == has_error:  # Both true or both false
        return DetectionResult.OTHER_SERVICE

    # If it has a result, it should be a dict with "agents" key
    if has_result:
        result = data.get("result")
        if not isinstance(result, dict):
            return DetectionResult.OTHER_SERVICE
        if "agents" not in result:
            return DetectionResult.OTHER_SERVICE
        # The "agents" value should be a list
        agents = result.get("agents")
        if not isinstance(agents, list):
            return DetectionResult.OTHER_SERVICE

    # If it has an error, that's still a valid NEXUS3 response
    # (e.g., if list_agents somehow failed, though unlikely)

    return DetectionResult.NEXUS_SERVER


async def wait_for_server(
    port: int,
    host: str = "127.0.0.1",
    timeout: float = 30.0,
    poll_interval: float = 0.1,
) -> bool:
    """Wait for a NEXUS3 server to become available.

    Polls the specified port until a NEXUS3 server is detected or the
    timeout expires. This is useful for:
    - Integration tests waiting for server startup
    - Scripts that spawn a server process and need to wait for it

    Args:
        port: The port to poll.
        host: The host to poll. Defaults to localhost.
        timeout: Maximum time to wait in seconds. Defaults to 30.0.
        poll_interval: Time between polls in seconds. Defaults to 0.1.

    Returns:
        True if a NEXUS3 server was detected within the timeout.
        False if the timeout expired without detecting a server.

    Example:
        # Start server in background
        process = start_server_process()

        # Wait for it to be ready
        if await wait_for_server(8765, timeout=10.0):
            print("Server ready!")
        else:
            print("Server failed to start")
    """
    elapsed = 0.0
    probe_timeout = min(1.0, timeout / 10)  # Short timeout per probe

    while elapsed < timeout:
        result = await detect_server(port, host, timeout=probe_timeout)

        if result == DetectionResult.NEXUS_SERVER:
            return True

        # If we got OTHER_SERVICE, the port is taken but not by NEXUS3
        # Could be a startup race - keep waiting
        # If ERROR, might be transient - keep waiting
        # If NO_SERVER, server hasn't started yet - keep waiting
        # If TIMEOUT, might be overloaded - keep waiting

        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    return False
