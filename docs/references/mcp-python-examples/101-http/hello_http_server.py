#!/usr/bin/env python3
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

PROTOCOL_VERSION = "2025-11-25"

TOOLS = [
    {
        "name": "hello",
        "description": "Return a friendly greeting.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name to greet",
                }
            },
            "required": ["name"],
        },
    },
    {
        "name": "add",
        "description": "Add two numbers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "First number"},
                "b": {"type": "number", "description": "Second number"},
            },
            "required": ["a", "b"],
        },
    },
]


def ok(request_id: int | str | None, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error(request_id: int | str | None, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def tool_text(text: str, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


def handle_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "hello":
        return tool_text(f"Hello, {arguments['name']}!")
    if name == "add":
        total = arguments["a"] + arguments["b"]
        return tool_text(str(total))
    raise ValueError(f"Unknown tool: {name}")


def handle_message(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    params = message.get("params", {})
    request_id = message.get("id")

    if request_id is None:
        return None

    try:
        if method == "initialize":
            return ok(
                request_id,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "hello-http-server",
                        "version": "1.0.0",
                    },
                },
            )

        if method == "ping":
            return ok(request_id, {})

        if method == "tools/list":
            return ok(request_id, {"tools": TOOLS})

        if method == "tools/call":
            result = handle_tool_call(
                params.get("name", ""),
                params.get("arguments", {}),
            )
            return ok(request_id, result)

        return error(request_id, -32601, f"Unknown method: {method}")

    except KeyError as exc:
        return error(request_id, -32602, f"Missing required field: {exc}")
    except ValueError as exc:
        return error(request_id, -32602, str(exc))
    except Exception as exc:
        return error(request_id, -32603, f"Internal error: {exc}")


class MCPHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != "/mcp":
            self.send_error(404)
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)

        try:
            message = json.loads(raw_body)
        except json.JSONDecodeError:
            response = error(None, -32700, "Parse error")
            self._send_json(response, status=400)
            return

        response = handle_message(message)
        if response is None:
            self.send_response(204)
            self.end_headers()
            return

        self._send_json(response, status=200)

    def _send_json(self, payload: dict[str, Any], status: int) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(fmt % args, file=sys.stderr)


def main() -> None:
    host = "127.0.0.1"
    port = 9876
    server = ThreadingHTTPServer((host, port), MCPHandler)
    print(f"MCP HTTP server listening on http://{host}:{port}/mcp", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()
