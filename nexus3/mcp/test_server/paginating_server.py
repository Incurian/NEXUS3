"""Paginating MCP test server for testing cursor-based pagination.

Implements tools/list with cursor-based pagination to test MCPClient's
pagination handling. Returns tools in pages of configurable size.

Configuration via environment variables:
    MCP_PAGE_SIZE: Number of tools per page (default: 2)
    MCP_TOOL_COUNT: Total number of tools to generate (default: 5)

Usage:
    python -m nexus3.mcp.test_server.paginating_server
    MCP_TOOL_COUNT=10 MCP_PAGE_SIZE=3 python -m nexus3.mcp.test_server.paginating_server
"""

import asyncio
import json
import os
import sys
from typing import Any

# Configuration via environment variables
PAGE_SIZE = int(os.environ.get("MCP_PAGE_SIZE", "2"))
TOOL_COUNT = int(os.environ.get("MCP_TOOL_COUNT", "5"))


def get_all_tools() -> list[dict[str, Any]]:
    """Generate list of test tools."""
    return [
        {
            "name": f"tool_{i}",
            "description": f"Test tool number {i}",
            "inputSchema": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
            },
        }
        for i in range(1, TOOL_COUNT + 1)
    ]


def make_response(request_id: int | str | None, result: Any) -> dict[str, Any]:
    """Create a success response."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }


def make_error(
    request_id: int | str | None,
    code: int,
    message: str,
) -> dict[str, Any]:
    """Create an error response."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


async def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    """Handle incoming MCP request."""
    method = request.get("method", "")
    params = request.get("params", {})
    request_id = request.get("id")

    # Notifications have no id - don't send response
    if request_id is None:
        return None

    if method == "initialize":
        return make_response(
            request_id,
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "nexus3-paginating-test-server",
                    "version": "1.0.0",
                },
            },
        )

    elif method == "tools/list":
        cursor = params.get("cursor") if params else None
        all_tools = get_all_tools()

        # Parse cursor (page offset) or start from 0
        start_idx = int(cursor) if cursor else 0
        end_idx = start_idx + PAGE_SIZE

        page_tools = all_tools[start_idx:end_idx]

        result: dict[str, Any] = {"tools": page_tools}

        # Add nextCursor if more pages exist
        if end_idx < len(all_tools):
            result["nextCursor"] = str(end_idx)

        return make_response(request_id, result)

    elif method == "tools/call":
        tool_name = params.get("name", "")
        args = params.get("arguments", {})
        return make_response(
            request_id,
            {
                "content": [{"type": "text", "text": f"Called {tool_name} with {args}"}],
                "isError": False,
            },
        )

    else:
        return make_error(
            request_id,
            -32601,
            f"Unknown method: {method}",
        )


async def run_server() -> None:
    """Main server loop - read from stdin, write to stdout."""
    while True:
        # Read line from stdin (blocking, run in thread)
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            break

        try:
            request = json.loads(line)
            response = await handle_request(request)
            if response is not None:
                # Write response to stdout
                output = json.dumps(response, separators=(",", ":"))
                print(output, flush=True)
        except json.JSONDecodeError:
            error = make_error(None, -32700, "Parse error")
            print(json.dumps(error, separators=(",", ":")), flush=True)


def main() -> None:
    """Entry point."""
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
