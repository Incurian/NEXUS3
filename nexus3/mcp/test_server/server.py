"""Simple MCP test server for development.

Implements a minimal MCP server with three test tools:
- echo: Echo back a message
- get_time: Get current date/time
- add: Add two numbers

Communicates via stdin/stdout using newline-delimited JSON-RPC 2.0.
"""

import asyncio
import json
import sys
from datetime import datetime
from typing import Any


# Tool definitions
TOOLS = [
    {
        "name": "echo",
        "description": "Echo back the input message",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Message to echo",
                }
            },
            "required": ["message"],
        },
    },
    {
        "name": "get_time",
        "description": "Get current date and time",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "add",
        "description": "Add two numbers",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {
                    "type": "number",
                    "description": "First number",
                },
                "b": {
                    "type": "number",
                    "description": "Second number",
                },
            },
            "required": ["a", "b"],
        },
    },
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


def make_tool_result(text: str, is_error: bool = False) -> dict[str, Any]:
    """Create a tool result."""
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
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
                    "name": "nexus3-test-server",
                    "version": "1.0.0",
                },
            },
        )

    elif method == "tools/list":
        return make_response(request_id, {"tools": TOOLS})

    elif method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})

        if tool_name == "echo":
            message = args.get("message", "")
            return make_response(
                request_id,
                make_tool_result(message),
            )

        elif tool_name == "get_time":
            return make_response(
                request_id,
                make_tool_result(datetime.now().isoformat()),
            )

        elif tool_name == "add":
            a = args.get("a", 0)
            b = args.get("b", 0)
            return make_response(
                request_id,
                make_tool_result(str(a + b)),
            )

        else:
            return make_error(
                request_id,
                -32601,
                f"Unknown tool: {tool_name}",
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
