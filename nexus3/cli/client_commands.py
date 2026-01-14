"""CLI commands for controlling remote Nexus agents via JSON-RPC.

These commands are thin wrappers around NexusClient, designed to be called
from repl.py. Each function prints JSON to stdout and returns an exit code.

Commands that require a server will auto-start one if none is running.

All commands are accessed via the `nexus3 rpc` subcommand group:
    nexus3 rpc detect           # Check if server is running
    nexus3 rpc list             # List agents (auto-starts server)
    nexus3 rpc create ID        # Create agent (auto-starts server)
    nexus3 rpc destroy ID       # Remove agent from pool
    nexus3 rpc send AGENT MSG   # Send message to agent
    nexus3 rpc cancel AGENT ID  # Cancel request
    nexus3 rpc status AGENT     # Get agent status
    nexus3 rpc shutdown         # Stop server
"""

import json
import subprocess
import sys
from typing import Any

from nexus3.client import ClientError, NexusClient
from nexus3.rpc.auth import discover_rpc_token
from nexus3.rpc.detection import DetectionResult, detect_server, wait_for_server


def _get_default_port() -> int:
    """Get default port from config, with fallback to 8765."""
    try:
        from nexus3.config.loader import load_config
        config = load_config()
        return config.server.port
    except Exception:
        return 8765


# Default server settings - loaded from config when available
DEFAULT_PORT = _get_default_port()


def _print_json(data: Any) -> None:
    """Print data as formatted JSON to stdout."""
    print(json.dumps(data, indent=2))


def _print_error(message: str) -> None:
    """Print error message to stderr."""
    print(f"Error: {message}", file=sys.stderr)


def _print_info(message: str) -> None:
    """Print info message to stderr (so it doesn't pollute JSON output)."""
    print(message, file=sys.stderr)


async def _ensure_server(port: int = DEFAULT_PORT) -> bool:
    """Ensure a NEXUS3 server is running, starting one if needed.

    Returns True if server is ready, False if failed to start.
    """
    result = await detect_server(port)

    if result == DetectionResult.NEXUS_SERVER:
        return True

    if result == DetectionResult.OTHER_SERVICE:
        _print_error(f"Port {port} is in use by another service")
        return False

    # No server - start one in the background
    _print_info(f"Starting NEXUS3 server on port {port}...")

    # Start server as detached subprocess
    proc = subprocess.Popen(
        [sys.executable, "-m", "nexus3", "--serve", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # Detach from parent
    )

    # Wait for server to be ready
    if await wait_for_server(port, timeout=10.0):
        _print_info(f"Server started (PID: {proc.pid})")
        return True
    else:
        _print_error("Server failed to start within 10 seconds")
        proc.terminate()
        return False


def _get_api_key(port: int, api_key: str | None) -> str | None:
    """Get API key from explicit argument or auto-discover.

    Args:
        port: The server port (used for key discovery).
        api_key: Explicitly provided API key, or None.

    Returns:
        The API key to use, or None if not found.
    """
    if api_key:
        return api_key
    return discover_rpc_token(port=port)


async def cmd_send(
    agent_id: str,
    content: str,
    port: int = DEFAULT_PORT,
    api_key: str | None = None,
    timeout: float = 300.0,
) -> int:
    """Send a message to a Nexus agent.

    Args:
        agent_id: ID of the agent to send to.
        content: Message content to send.
        port: Server port (default 8765).
        api_key: Optional API key. If not provided, auto-discovers from
                 environment or key files.
        timeout: Request timeout in seconds (default 120).

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    # Don't auto-start for send - server must be running
    result = await detect_server(port)
    if result != DetectionResult.NEXUS_SERVER:
        _print_error(f"No NEXUS3 server running on port {port}")
        return 1

    url = f"http://127.0.0.1:{port}/agent/{agent_id}"
    key = _get_api_key(port, api_key)
    try:
        async with NexusClient(url, api_key=key, timeout=timeout) as client:
            result = await client.send(content)
            _print_json(result)
            return 0
    except ClientError as e:
        _print_error(str(e))
        return 1


async def cmd_cancel(
    agent_id: str,
    request_id: str,
    port: int = DEFAULT_PORT,
    api_key: str | None = None,
) -> int:
    """Cancel an in-progress request.

    Args:
        agent_id: ID of the agent.
        request_id: The request ID to cancel (converted to int).
        port: Server port (default 8765).
        api_key: Optional API key. If not provided, auto-discovers from
                 environment or key files.

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    try:
        rid = int(request_id)
    except ValueError:
        _print_error(f"Invalid request_id: {request_id} (must be an integer)")
        return 1

    # Don't auto-start for cancel - server must be running
    result = await detect_server(port)
    if result != DetectionResult.NEXUS_SERVER:
        _print_error(f"No NEXUS3 server running on port {port}")
        return 1

    url = f"http://127.0.0.1:{port}/agent/{agent_id}"
    key = _get_api_key(port, api_key)
    try:
        async with NexusClient(url, api_key=key) as client:
            result = await client.cancel(rid)
            _print_json(result)
            return 0
    except ClientError as e:
        _print_error(str(e))
        return 1


async def cmd_status(
    agent_id: str,
    port: int = DEFAULT_PORT,
    api_key: str | None = None,
) -> int:
    """Get status (tokens + context) from agent.

    Args:
        agent_id: ID of the agent.
        port: Server port (default 8765).
        api_key: Optional API key. If not provided, auto-discovers from
                 environment or key files.

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    # Don't auto-start for status - server must be running
    result = await detect_server(port)
    if result != DetectionResult.NEXUS_SERVER:
        _print_error(f"No NEXUS3 server running on port {port}")
        return 1

    url = f"http://127.0.0.1:{port}/agent/{agent_id}"
    key = _get_api_key(port, api_key)
    try:
        async with NexusClient(url, api_key=key) as client:
            tokens = await client.get_tokens()
            context = await client.get_context()
            result = {
                "tokens": tokens,
                "context": context,
            }
            _print_json(result)
            return 0
    except ClientError as e:
        _print_error(str(e))
        return 1


async def cmd_shutdown(
    port: int = DEFAULT_PORT,
    api_key: str | None = None,
) -> int:
    """Request graceful shutdown of the server.

    Calls the shutdown_server RPC method on the root endpoint to
    stop the entire server.

    Args:
        port: Server port (default 8765).
        api_key: Optional API key. If not provided, auto-discovers from
                 environment or key files.

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    # Don't auto-start for shutdown - server must be running
    result = await detect_server(port)
    if result != DetectionResult.NEXUS_SERVER:
        _print_error(f"No NEXUS3 server running on port {port}")
        return 1

    url = f"http://127.0.0.1:{port}"
    key = _get_api_key(port, api_key)
    try:
        async with NexusClient(url, api_key=key) as client:
            result = await client.shutdown_server()
            _print_json(result)
            return 0
    except ClientError as e:
        _print_error(str(e))
        return 1


# =============================================================================
# Agent Management Commands (with auto-start)
# =============================================================================


async def cmd_list(
    port: int = DEFAULT_PORT,
    api_key: str | None = None,
) -> int:
    """List all agents on the server.

    Auto-starts a server if none is running.

    Args:
        port: Server port (default 8765).
        api_key: Optional API key.

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    if not await _ensure_server(port):
        return 1

    url = f"http://127.0.0.1:{port}"
    key = _get_api_key(port, api_key)
    try:
        async with NexusClient(url, api_key=key) as client:
            agents = await client.list_agents()
            _print_json({"agents": agents})
            return 0
    except ClientError as e:
        _print_error(str(e))
        return 1


async def cmd_detect(
    port: int = DEFAULT_PORT,
) -> int:
    """Detect if a NEXUS3 server is running on the port.

    Args:
        port: Server port (default 8765).

    Returns:
        Exit code: 0 if server is running, 1 otherwise.
    """
    result = await detect_server(port)

    status = {
        "port": port,
        "result": result.value,
        "running": result == DetectionResult.NEXUS_SERVER,
    }
    _print_json(status)

    # Return 0 if server is running, 1 otherwise
    return 0 if result == DetectionResult.NEXUS_SERVER else 1


async def cmd_create(
    agent_id: str,
    port: int = DEFAULT_PORT,
    api_key: str | None = None,
    preset: str = "sandboxed",
    cwd: str | None = None,
    allowed_write_paths: list[str] | None = None,
    model: str | None = None,
    message: str | None = None,
    timeout: float = 300.0,
) -> int:
    """Create a new agent on the server.

    Auto-starts a server if none is running.

    Args:
        agent_id: ID for the new agent.
        port: Server port (default 8765).
        api_key: Optional API key.
        preset: Permission preset (default: sandboxed for RPC mode).
        cwd: Working directory / sandbox root for the agent.
        allowed_write_paths: Paths where write_file/edit_file are allowed.
        model: Model name/alias to use (from config.models or full model ID).
        message: Initial message to send to the agent immediately after creation.
            The agent will process this and the response will be in the result.
        timeout: Request timeout in seconds (default 120, used when message provided).

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    if not await _ensure_server(port):
        return 1

    url = f"http://127.0.0.1:{port}"
    key = _get_api_key(port, api_key)
    # Use longer timeout if initial message provided (agent needs time to respond)
    client_timeout = timeout if message else 30.0
    try:
        async with NexusClient(url, api_key=key, timeout=client_timeout) as client:
            result = await client.create_agent(
                agent_id,
                preset=preset,
                cwd=cwd,
                allowed_write_paths=allowed_write_paths,
                model=model,
                initial_message=message,
            )
            _print_json(result)
            return 0
    except ClientError as e:
        _print_error(str(e))
        return 1


async def cmd_destroy(
    agent_id: str,
    port: int = DEFAULT_PORT,
    api_key: str | None = None,
) -> int:
    """Destroy an agent on the server.

    Args:
        agent_id: ID of the agent to destroy.
        port: Server port (default 8765).
        api_key: Optional API key.

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    # Don't auto-start for destroy - that doesn't make sense
    result = await detect_server(port)
    if result != DetectionResult.NEXUS_SERVER:
        _print_error(f"No NEXUS3 server running on port {port}")
        return 1

    url = f"http://127.0.0.1:{port}"
    key = _get_api_key(port, api_key)
    try:
        async with NexusClient(url, api_key=key) as client:
            result = await client.destroy_agent(agent_id)
            _print_json(result)
            return 0
    except ClientError as e:
        _print_error(str(e))
        return 1
