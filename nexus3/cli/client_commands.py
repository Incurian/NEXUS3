"""CLI commands for controlling remote Nexus agents via JSON-RPC.

These commands are thin wrappers around NexusClient, designed to be called
from __main__.py. Each function prints JSON to stdout and returns an exit code.
"""

import json
import sys
from typing import Any

from nexus3.client import ClientError, NexusClient


def _print_json(data: Any) -> None:
    """Print data as formatted JSON to stdout."""
    print(json.dumps(data, indent=2))


def _print_error(message: str) -> None:
    """Print error message to stderr."""
    print(f"Error: {message}", file=sys.stderr)


async def cmd_send(url: str, content: str, request_id: str | None = None) -> int:
    """Send a message to a Nexus agent.

    Args:
        url: Base URL of the JSON-RPC server.
        content: Message content to send.
        request_id: Optional request ID (unused, for interface compatibility).

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    try:
        async with NexusClient(url) as client:
            result = await client.send(content)
            _print_json(result)
            return 0
    except ClientError as e:
        _print_error(str(e))
        return 1


async def cmd_cancel(url: str, request_id: str) -> int:
    """Cancel an in-progress request.

    Args:
        url: Base URL of the JSON-RPC server.
        request_id: The request ID to cancel (converted to int).

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    try:
        rid = int(request_id)
    except ValueError:
        _print_error(f"Invalid request_id: {request_id} (must be an integer)")
        return 1

    try:
        async with NexusClient(url) as client:
            result = await client.cancel(rid)
            _print_json(result)
            return 0
    except ClientError as e:
        _print_error(str(e))
        return 1


async def cmd_status(url: str) -> int:
    """Get status (tokens + context) from agent.

    Args:
        url: Base URL of the JSON-RPC server.

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    try:
        async with NexusClient(url) as client:
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


async def cmd_shutdown(url: str) -> int:
    """Request graceful shutdown from agent.

    Args:
        url: Base URL of the JSON-RPC server.

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    try:
        async with NexusClient(url) as client:
            result = await client.shutdown()
            _print_json(result)
            return 0
    except ClientError as e:
        _print_error(str(e))
        return 1
