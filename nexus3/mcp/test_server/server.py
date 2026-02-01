"""MCP test server (stdio transport).

Implements a full-featured MCP server for testing:
- Tools: echo, get_time, add, slow_operation
- Resources: readme.txt, config.json, users.csv
- Prompts: greeting, code_review, summarize
- Utilities: ping

Communicates via stdin/stdout using newline-delimited JSON-RPC 2.0.
"""

import asyncio
import json
import sys
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


async def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    """Handle incoming MCP request."""
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
                    "serverInfo": get_server_info("nexus3-test-server"),
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
