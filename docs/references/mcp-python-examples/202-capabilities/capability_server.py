#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "2025-11-25"
CUSTOMER_SCHEMA_PATH = Path("customer_table.md")


def load_runtime_config() -> dict[str, Any]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--customer-count", type=int, default=128)
    parsed, _ = parser.parse_known_args()

    return {
        "customer_count": parsed.customer_count,
        "example_mode": os.environ.get("CAPABILITY_EXAMPLE_MODE", "demo"),
        "environment": os.environ.get("CAPABILITY_ENVIRONMENT", "development"),
        "cwd": str(Path.cwd()),
    }


RUNTIME_CONFIG = load_runtime_config()

TOOLS = [
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
    {
        "name": "get_customer_count",
        "description": "Return the current customer count from server state.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]

RESOURCES = [
    {
        "uri": "config://app/settings",
        "name": "Application Settings",
        "description": "Current application configuration",
        "mimeType": "application/json",
    },
    {
        "uri": "docs://customer-table",
        "name": "Customer Table Schema",
        "description": "Schema notes for the customer table",
        "mimeType": "text/markdown",
    },
]

RESOURCE_CONTENTS = {
    "config://app/settings": {
        "mimeType": "application/json",
    },
    "docs://customer-table": {
        "mimeType": "text/markdown",
    },
}

PROMPTS = [
    {
        "name": "customer_summary",
        "description": "Create a concise customer-facing status summary.",
        "arguments": [
            {
                "name": "customer_name",
                "description": "Customer name",
                "required": True,
            },
            {
                "name": "status",
                "description": "Current status",
                "required": True,
            },
        ],
    },
    {
        "name": "schema_explainer",
        "description": "Explain a schema to a junior engineer.",
        "arguments": [
            {
                "name": "resource_uri",
                "description": "URI of the schema resource",
                "required": True,
            }
        ],
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
    if name == "add":
        return tool_text(str(arguments["a"] + arguments["b"]))
    if name == "get_customer_count":
        return tool_text(f"Current customer count: {RUNTIME_CONFIG['customer_count']}")
    raise ValueError(f"Unknown tool: {name}")


def handle_resources_read(uri: str) -> dict[str, Any]:
    if uri == "config://app/settings":
        settings_text = json.dumps(
            {
                "environment": RUNTIME_CONFIG["environment"],
                "mode": RUNTIME_CONFIG["example_mode"],
                "customer_count": RUNTIME_CONFIG["customer_count"],
                "cwd": RUNTIME_CONFIG["cwd"],
                "feature_flags": {
                    "new_checkout": True,
                    "beta_dashboard": False,
                },
            },
            indent=2,
        )
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": RESOURCE_CONTENTS[uri]["mimeType"],
                    "text": settings_text,
                }
            ]
        }

    if uri == "docs://customer-table":
        schema_text = CUSTOMER_SCHEMA_PATH.read_text(encoding="utf-8")
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": RESOURCE_CONTENTS[uri]["mimeType"],
                    "text": schema_text,
                }
            ]
        }

    raise ValueError(f"Resource not found: {uri}")


def handle_prompts_get(
    name: str,
    arguments: dict[str, Any] | None,
) -> dict[str, Any]:
    args = arguments or {}

    if name == "customer_summary":
        customer_name = args["customer_name"]
        status = args["status"]
        text = (
            f"Write a concise customer-facing update for {customer_name}. "
            f"The current status is: {status}. "
            f"This example is running in the {RUNTIME_CONFIG['environment']} environment."
        )
    elif name == "schema_explainer":
        resource_uri = args["resource_uri"]
        text = (
            f"Explain the schema in resource {resource_uri} "
            "to a junior engineer in plain language."
        )
    else:
        raise ValueError(f"Prompt not found: {name}")

    return {
        "description": f"Generated prompt for {name}",
        "messages": [
            {
                "role": "user",
                "content": {"type": "text", "text": text},
            }
        ],
    }


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
                    "capabilities": {
                        "tools": {},
                        "resources": {"subscribe": False, "listChanged": False},
                        "prompts": {"listChanged": False},
                    },
                    "serverInfo": {
                        "name": "capability-server",
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

        if method == "resources/list":
            return ok(request_id, {"resources": RESOURCES})

        if method == "resources/read":
            result = handle_resources_read(params.get("uri", ""))
            return ok(request_id, result)

        if method == "prompts/list":
            return ok(request_id, {"prompts": PROMPTS})

        if method == "prompts/get":
            result = handle_prompts_get(
                params.get("name", ""),
                params.get("arguments"),
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
        "capability MCP server started "
        f"(customer_count={RUNTIME_CONFIG['customer_count']}, "
        f"environment={RUNTIME_CONFIG['environment']!r}, "
        f"mode={RUNTIME_CONFIG['example_mode']!r}, "
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
