# MCP Server Python 101 For NEXUS3

This guide shows the simplest way to build an MCP server in Python that works
with NEXUS3.

It focuses on **tools** first. Resources and prompts can come later.

## Two Separate Axes: transport vs capabilities

There are two different questions here:

1. **How does NEXUS3 talk to your server?**
   - `stdio`
   - `HTTP`
2. **What does your server expose?**
   - `tools`
   - `resources`
   - `prompts`
   - or any combination of those

So when this guide says **tools-only** or **tools-focused** server, it means:

- the server exposes MCP tool methods
- it does not yet expose resources or prompts

That is separate from whether the transport is stdio or HTTP.

## What NEXUS3 Supports

For practical MCP server integration, NEXUS3 supports two transport styles:

1. **stdio**
   - NEXUS3 launches your server as a subprocess
   - JSON-RPC messages flow over `stdin` / `stdout`
   - best for local tools
2. **HTTP**
   - NEXUS3 sends JSON-RPC requests to an HTTP endpoint with `POST`
   - best for shared or remote services

If you are building your first server, start with **stdio**.

## What Goes In `mcp.json`

For a beginner server, the important `mcp.json` fields are:

- `command` or `url`: choose exactly one
- `args`: extra command-line arguments when `command` is a string
- `cwd`: working directory for a stdio server subprocess
- `env`: explicit environment variables to inject
- `env_passthrough`: selected host environment variables to forward
- `enabled`: turn a server on or off without deleting the entry
- `fail_if_no_tools`: fail the connection if the transport connects but
  `tools/list` still fails

Practical rule:

- stdio servers usually use `command`, optional `args`, optional `cwd`, and
  optional env fields
- HTTP servers usually use `url` and `enabled`

NEXUS accepts both of these command styles:

```json
{"command": ["python3", "hello_stdio_server.py"]}
{"command": "python3", "args": ["hello_stdio_server.py"]}
```

The checked-in stdio example intentionally uses the second form so you can see
`args` in a real config file.

The docs use `python3` as the default because it is the stronger default on
Linux, macOS, and WSL. If your interpreter lives elsewhere, use the absolute
interpreter path that exists on your machine.

Checked-in example projects live under
[docs/references/mcp-python-examples/](/home/inc/repos/NEXUS3/docs/references/mcp-python-examples/README.md):

- [101-stdio](/home/inc/repos/NEXUS3/docs/references/mcp-python-examples/101-stdio/README.md)
- [101-http](/home/inc/repos/NEXUS3/docs/references/mcp-python-examples/101-http/README.md)

## The Smallest Useful MCP Server

For a **tools-only** server, the minimal method surface NEXUS3 needs is:

- `initialize`
- `notifications/initialized`
- `tools/list`
- `tools/call`

Recommended but optional for a 101 server:

- `ping`

You do **not** need `resources/list`, `resources/read`, `prompts/list`, or
`prompts/get` just to expose tools in NEXUS3.

If you later want those capabilities too, the usual next methods are:

- resources:
  - `resources/list`
  - `resources/read`
- prompts:
  - `prompts/list`
  - `prompts/get`

## What NEXUS3 Will Do With Your Tools

If your MCP server is configured in NEXUS3 as:

```json
{
  "servers": {
    "hello_stdio": {
      "command": ["python3", "hello_stdio_server.py"]
    }
  }
}
```

and your MCP server exposes a tool named `hello`, NEXUS3 will expose it to the
agent as:

```text
mcp_hello_stdio_hello
```

You can inspect the raw tool list in the REPL with:

```text
/mcp tools hello_stdio
```

Important:

- MCP **tools** become callable NEXUS tools with an `mcp_<server>_...` prefix
- MCP **resources** and **prompts** do not become callable NEXUS tools
- resources/prompts remain separate MCP surfaces that you inspect with
  `/mcp resources` and `/mcp prompts`

For that next layer, see
[MCP-SERVER-PYTHON-202.md](/home/inc/repos/NEXUS3/docs/references/MCP-SERVER-PYTHON-202.md).

## Example 1: Minimal stdio server

Checked-in files for this example:

- [hello_stdio_server.py](/home/inc/repos/NEXUS3/docs/references/mcp-python-examples/101-stdio/hello_stdio_server.py)
- [mcp.json](/home/inc/repos/NEXUS3/docs/references/mcp-python-examples/101-stdio/.nexus3/mcp.json)

### Step 1: Create `hello_stdio_server.py`

```python
#!/usr/bin/env python3
import json
import sys
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

    # Notifications do not get responses.
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
    # Important: stdout is reserved for JSON-RPC only.
    # If you want logs, write them to stderr.
    print("hello stdio MCP server started", file=sys.stderr, flush=True)

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
```

The checked-in example file adds one practical layer on top of this minimal
version so the `mcp.json` fields are observable:

- `--greeting-prefix` from `args` changes the greeting prefix
- `EXAMPLE_GREETING_STYLE` from `env` changes the greeting style
- `greeting_suffix.txt` is loaded relative to `cwd`

### Step 2: Add it to `.nexus3/mcp.json`

Project-local example:

```json
{
  "servers": {
    "hello_stdio": {
      "command": "python3",
      "args": ["hello_stdio_server.py", "--greeting-prefix", "Howdy"],
      "cwd": ".",
      "env": {
        "EXAMPLE_GREETING_STYLE": "friendly"
      },
      "env_passthrough": ["USER"],
      "enabled": true,
      "fail_if_no_tools": true
    }
  }
}
```

Notes:

- `cwd` is optional, but it is often useful for local stdio servers.
- `env` sets explicit variables for the subprocess.
- `env_passthrough` forwards only the named host variables, not your entire
  shell environment.
- `fail_if_no_tools` is useful when you want startup to fail loudly instead of
  connecting with an empty tool list.
- In the checked-in example, `args`, `env`, and `cwd` visibly affect the
  greeting output.
- In this checked-in example, `cwd: "."` works because the instructions have
  you start NEXUS from the example directory. In reusable project configs,
  prefer an absolute path.
- If `python3` is not on your `PATH`, use an absolute interpreter path.

### Step 3: Start NEXUS3 and connect the server

From the example directory, start a fresh NEXUS session:

```text
nexus3 --fresh
```

Then in the REPL:

```text
/mcp connect hello_stdio --allow-all --private
/mcp tools hello_stdio
```

If you want to walk through the consent and sharing prompts manually, omit
`--allow-all --private`.

You should see tools corresponding to:

- `mcp_hello_stdio_hello`
- `mcp_hello_stdio_add`

### Step 4: Use the tools

Ask the agent something like:

```text
Use the hello tool to greet Alice.
```

In the checked-in example, you should see the configured prefix and suffix in
the reply, for example: `Howdy, Alice! Welcome from the stdio example.`

Or:

```text
Use the add tool to compute 41 + 1.
```

### Step 5: Add another tool

To add a new tool, you do two things:

1. Add its definition to `TOOLS`
2. Add its behavior to `handle_tool_call()`

Example: add `multiply`

```python
TOOLS.append(
    {
        "name": "multiply",
        "description": "Multiply two numbers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"},
            },
            "required": ["a", "b"],
        },
    }
)
```

And in `handle_tool_call()`:

```python
if name == "multiply":
    return tool_text(str(arguments["a"] * arguments["b"]))
```

After changing the server:

- reconnect with `/mcp disconnect hello_stdio` then `/mcp connect hello_stdio`
- or use `/mcp retry hello_stdio` if the server is already connected and you
  only need NEXUS3 to refresh the tool list

### Quick stdio rule that matters

For stdio servers:

- write JSON-RPC responses to **stdout**
- write logs/debugging to **stderr**

If you print logs to stdout, you will corrupt the protocol stream.

## First-failure checklist

- If a stdio server fails immediately, first confirm that the interpreter path
  in `mcp.json` exists on your machine.
- If a stdio server starts but NEXUS cannot speak MCP to it, check for stray
  stdout logging. MCP JSON-RPC belongs on stdout; human logs belong on stderr.
- If an HTTP server fails to connect, keep the server process running and make
  sure the `url` in `mcp.json` still matches the host, port, and path.
- After changing tools or config, reconnect the server or use `/mcp retry` so
  NEXUS refreshes what it sees.

## Example 2: Minimal HTTP server

Checked-in files for this example:

- [hello_http_server.py](/home/inc/repos/NEXUS3/docs/references/mcp-python-examples/101-http/hello_http_server.py)
- [mcp.json](/home/inc/repos/NEXUS3/docs/references/mcp-python-examples/101-http/.nexus3/mcp.json)

This example uses only the Python standard library.

### Step 1: Create `hello_http_server.py`

```python
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

    # Notifications do not get responses.
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
        # Keep logs visible, but send them to stderr rather than mixing them
        # into normal output streams.
        print(fmt % args, file=sys.stderr)


def main() -> None:
    host = "127.0.0.1"
    port = 9876
    server = ThreadingHTTPServer((host, port), MCPHandler)
    print(f"MCP HTTP server listening on http://{host}:{port}/mcp", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()
```

### Step 2: Start the server

In another terminal:

```bash
python3 hello_http_server.py
```

### Step 3: Add it to `.nexus3/mcp.json`

```json
{
  "servers": {
    "hello_http": {
      "url": "http://127.0.0.1:9876/mcp",
      "enabled": true
    }
  }
}
```

For HTTP servers, `url` is the important transport field. `command`, `args`,
`cwd`, `env`, and `env_passthrough` are stdio-oriented settings and usually do
not belong on an HTTP entry.

This example uses port `9876` so it does not collide with NEXUS3's own default
embedded RPC port `8765`.

### Step 4: Connect it from NEXUS3

In the REPL:

```text
/mcp connect hello_http --allow-all --private
/mcp tools hello_http
```

If you want to walk through the consent and sharing prompts manually, omit
`--allow-all --private`.

You should see:

- `mcp_hello_http_hello`
- `mcp_hello_http_add`

### Step 5: Add another tool

It is the same pattern as stdio:

1. add a tool definition to `TOOLS`
2. add the implementation branch in `handle_tool_call()`
3. restart the HTTP server
4. reconnect or run `/mcp retry hello_http`

## Manual tests outside NEXUS3

### Test the stdio server directly

You can send a single MCP request by piping JSON into the process:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"manual-test","version":"1.0.0"}}}' \
  | python3 hello_stdio_server.py
```

### Test the HTTP server directly

```bash
curl \
  -X POST http://127.0.0.1:9876/mcp \
  -H 'Content-Type: application/json' \
  -H 'MCP-Protocol-Version: 2025-11-25' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"manual-test","version":"1.0.0"}}}'
```

## Practical rules for NEXUS3 compatibility

### Use simple JSON Schema

For beginner MCP tools, keep `inputSchema` simple:

- `type: "object"`
- `properties`
- `required`

That is enough for NEXUS3 to expose the tool cleanly.

### Keep tool outputs simple at first

The easiest valid MCP tool result is:

```json
{
  "content": [
    {"type": "text", "text": "hello"}
  ],
  "isError": false
}
```

Start with plain text results. You can add richer MCP features later.

### Ignore notifications cleanly

If a message has no `id`, it is a notification. For a simple tools-only
server, ignore it and do not send a response.

### HTTP can stay simple

For the beginner path, NEXUS3 works fine with a plain JSON-over-HTTP `POST`
server. You do not need SSE or a more complex transport model to get started.

### Use `env` and `env_passthrough` intentionally

If your stdio server needs secrets or custom environment variables, configure
them in `mcp.json`.

Example:

```json
{
  "servers": {
    "my_server": {
      "command": ["python3", "my_server.py"],
      "env_passthrough": ["MY_API_KEY"],
      "env": {"LOG_LEVEL": "debug"}
    }
  }
}
```

NEXUS3 does **not** pass your full host environment through to MCP subprocess
servers by default.

## When to choose stdio vs HTTP

Choose **stdio** when:

- the server is local
- NEXUS3 should manage the server process for you
- you want the simplest deployment

Choose **HTTP** when:

- the server is already a long-running service
- multiple clients may connect to the same service
- you want the server to live outside the NEXUS3 process tree

## Where to look next

After the 101 path, the best repo references are:

- [nexus3/mcp/README.md](/home/inc/repos/NEXUS3/nexus3/mcp/README.md)
- [nexus3/mcp/test_server/server.py](/home/inc/repos/NEXUS3/nexus3/mcp/test_server/server.py)
- [nexus3/mcp/test_server/http_server.py](/home/inc/repos/NEXUS3/nexus3/mcp/test_server/http_server.py)
- [nexus3/mcp/test_server/definitions.py](/home/inc/repos/NEXUS3/nexus3/mcp/test_server/definitions.py)

Those files show the same ideas in the repo's own test harness.
