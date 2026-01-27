"""HTTP-based MCP test server for development.

Implements a full-featured MCP server for testing via HTTP:
- Tools: echo, get_time, add, slow_operation
- Resources: readme.txt, config.json, users.csv
- Prompts: greeting, code_review, summarize
- Utilities: ping

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
from typing import Any

from nexus3.mcp.test_server.definitions import (
    PROMPTS,
    PROTOCOL_VERSION,
    RESOURCES,
    TOOLS,
    get_capabilities,
    get_server_info,
    handle_prompts_get,
    handle_resources_read,
    handle_tools_call,
    make_error,
    make_response,
)


def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    """Handle incoming MCP request (synchronous)."""
    method = request.get("method", "")
    params = request.get("params", {})
    request_id = request.get("id")

    # Notifications have no id - don't send response
    if request_id is None:
        return None

    try:
        if method == "initialize":
            return make_response(
                request_id,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": get_capabilities(),
                    "serverInfo": get_server_info("nexus3-http-test-server"),
                },
            )

        elif method == "ping":
            return make_response(request_id, {})

        # Tools
        elif method == "tools/list":
            return make_response(request_id, {"tools": TOOLS})

        elif method == "tools/call":
            result = handle_tools_call(
                params.get("name", ""), params.get("arguments", {})
            )
            return make_response(request_id, result)

        # Resources
        elif method == "resources/list":
            return make_response(request_id, {"resources": RESOURCES})

        elif method == "resources/read":
            result = handle_resources_read(params.get("uri", ""))
            return make_response(request_id, result)

        # Prompts
        elif method == "prompts/list":
            return make_response(request_id, {"prompts": PROMPTS})

        elif method == "prompts/get":
            result = handle_prompts_get(params.get("name", ""), params.get("arguments"))
            return make_response(request_id, result)

        else:
            return make_error(request_id, -32601, f"Unknown method: {method}")

    except ValueError as e:
        return make_error(request_id, -32602, str(e))
    except Exception as e:
        return make_error(request_id, -32603, f"Internal error: {e}")


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
