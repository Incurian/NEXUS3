#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "2025-11-25"
GREETING_SUFFIX_PATH = Path("greeting_suffix.txt")

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


def load_runtime_config() -> dict[str, str]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--greeting-prefix", default="Hello")
    parsed, _ = parser.parse_known_args()

    greeting_style = "plain"
    suffix = ""

    try:
        import os

        greeting_style = os.environ.get("EXAMPLE_GREETING_STYLE", "plain").strip().lower()
    except Exception:
        greeting_style = "plain"

    try:
        suffix = GREETING_SUFFIX_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        suffix = ""

    return {
        "greeting_prefix": parsed.greeting_prefix,
        "greeting_style": greeting_style or "plain",
        "greeting_suffix": suffix,
    }


RUNTIME_CONFIG = load_runtime_config()


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


def render_greeting(name: str) -> str:
    prefix = RUNTIME_CONFIG["greeting_prefix"]
    style = RUNTIME_CONFIG["greeting_style"]
    suffix = RUNTIME_CONFIG["greeting_suffix"]

    if style == "friendly":
        parts = [f"{prefix}, {name}!"]
        if suffix:
            parts.append(suffix)
        return " ".join(parts)

    if style == "formal":
        if suffix:
            return f"{prefix}, {name}. {suffix}"
        return f"{prefix}, {name}."

    return f"{prefix}, {name}!"


def handle_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "hello":
        return tool_text(render_greeting(arguments["name"]))
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
                        "name": "hello-stdio-server",
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


def main() -> None:
    print(
        "hello stdio MCP server started "
        f"(prefix={RUNTIME_CONFIG['greeting_prefix']!r}, "
        f"style={RUNTIME_CONFIG['greeting_style']!r}, "
        f"cwd={Path.cwd()})",
        file=sys.stderr,
        flush=True,
    )

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response = error(None, -32700, "Parse error")
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()
            continue

        response = handle_message(message)
        if response is None:
            continue

        sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
