"""HTTP-based MCP test server for development.

Same tools as the stdio server, but accessible via HTTP POST.
Used for testing HTTPTransport.

Usage:
    python -m nexus3.mcp.test_server.http_server [--port 9000]

    # Or programmatically:
    from nexus3.mcp.test_server.http_server import run_server
    await run_server(port=9000)
"""

import argparse
import asyncio
import json
from datetime import datetime
from typing import Any

# Tool definitions (same as stdio server)
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


def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    """Handle incoming MCP request (synchronous)."""
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
                    "name": "nexus3-http-test-server",
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


async def run_server(host: str = "127.0.0.1", port: int = 9000) -> None:
    """Run HTTP MCP server using asyncio.

    Simple HTTP server that handles POST requests with JSON-RPC bodies.
    """
    from aiohttp import web

    async def handle_post(request: web.Request) -> web.Response:
        """Handle POST request with JSON-RPC body."""
        try:
            body = await request.json()
            response = handle_request(body)

            if response is None:
                # Notification - no response needed
                return web.Response(status=204)

            return web.json_response(response)
        except json.JSONDecodeError:
            error = make_error(None, -32700, "Parse error")
            return web.json_response(error, status=400)

    app = web.Application()
    app.router.add_post("/", handle_post)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    print(f"MCP HTTP test server running on http://{host}:{port}")
    print("Press Ctrl+C to stop")

    # Keep running until cancelled
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await runner.cleanup()


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(description="MCP HTTP test server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=9000, help="Port to listen on")
    args = parser.parse_args()

    try:
        asyncio.run(run_server(host=args.host, port=args.port))
    except KeyboardInterrupt:
        print("\nShutting down...")


if __name__ == "__main__":
    main()
