# MCP Server Python 202 For NEXUS3

This guide picks up where
[MCP-SERVER-PYTHON-101.md](./MCP-SERVER-PYTHON-101.md)
leaves off.

The 101 guide taught:

- the two transport options NEXUS3 supports here: `stdio` and `HTTP`
- the minimal tools-only MCP server

This 202 guide covers the next layer:

- **resources**
- **prompts**
- how NEXUS3 treats each MCP capability

## What Changes After Tools?

In MCP, a server can expose more than executable tools.

### Tools

Executable operations.

Example:

- `add(a, b)`
- `run_query(sql)`
- `deploy(environment)`

In NEXUS3:

- MCP tools are adapted into callable NEXUS tools
- they show up with names like `mcp_<server>_<tool>`

### Resources

URI-addressable content exposed by the server.

Examples:

- `file:///schema.sql`
- `docs://api/authentication`
- `db://customers/table-definition`
- `config://app/settings`

In NEXUS3:

- resources are **not** automatically adapted into callable tools
- you can inspect them with `/mcp resources`
- the MCP client can read them with `resources/read`

### Prompts

Reusable prompt templates or prompt-generating endpoints exposed by the server.

Examples:

- `code_review`
- `incident_summary`
- `query_explainer`

In NEXUS3:

- prompts are **not** automatically adapted into callable tools
- you can inspect them with `/mcp prompts`
- the MCP client can fetch them with `prompts/get`

## Important NEXUS Design Consequence

If you want the agent to directly **call** something during normal tool use,
that surface should be a **tool**.

Resources and prompts are still useful, but they are better for:

- discovery
- structured context
- reusable templates
- server-side metadata or content browsing

If you want an agent to actively fetch a resource or instantiate a prompt as
part of normal tool calling, the most practical approach is often:

- expose the resource/prompt for inspection
- also expose a tool that wraps the specific operation the agent should invoke

## Capability Method Map

If your server exposes all three surfaces, the usual MCP methods are:

- tools:
  - `tools/list`
  - `tools/call`
- resources:
  - `resources/list`
  - `resources/read`
- prompts:
  - `prompts/list`
  - `prompts/get`

You still also need:

- `initialize`
- `notifications/initialized`

Optional but useful:

- `ping`

As in the 101 guide, `notifications/initialized` does not need a dedicated
branch in these toy servers. A generic "ignore messages without an `id`"
branch is enough unless your server wants to react to that notification.

## `mcp.json` In Practice

The 101 guide showed the smallest working config. Here is the fuller surface
you will usually care about when you move beyond a toy server:

| Field | Applies to | What it does |
|---|---|---|
| `command` | stdio | Launches a local MCP subprocess |
| `args` | stdio | Extra argv entries when `command` is a string |
| `cwd` | stdio | Sets the subprocess working directory |
| `env` | stdio | Injects explicit environment variables |
| `env_passthrough` | stdio | Copies selected host env vars into the subprocess |
| `url` | HTTP | Points NEXUS at an HTTP MCP endpoint |
| `enabled` | both | Lets you disable an entry without deleting it |
| `fail_if_no_tools` | both | Turns tool-discovery failure into a hard connect failure |

Practical guidance:

- Use `env` for values you want to set explicitly in config.
- Use `env_passthrough` only for specific host variables you intentionally want
  to forward.
- Use `cwd` when the server depends on relative imports, data files, or local
  project layout.
- Use `fail_if_no_tools: true` when an empty tool list should be treated as a
  broken server, not a degraded one.

Merge behavior matters too:

- `~/.nexus3/mcp.json` is the global layer.
- ancestor `.nexus3/mcp.json` files can contribute shared project/team config.
- the current directory's `.nexus3/mcp.json` is the local override.
- later layers override earlier ones by server name.
- both `servers` and `mcpServers` are accepted.
- if both keys exist in the same file and `mcpServers` is non-empty, NEXUS uses
  `mcpServers`.

## Full Example: One Python server with tools, resources, and prompts

This example uses **stdio** because it keeps the capability example focused.
If you want HTTP, reuse the same `handle_message()` function with the HTTP
server shell from the 101 guide.

Checked-in files for this example:

- [capability_server.py](./202-capabilities/capability_server.py)
- [inspect_capabilities.py](./202-capabilities/inspect_capabilities.py)
- [mcp.json](./202-capabilities/.nexus3/mcp.json)

### Step 1: Create `capability_server.py`

```python
#!/usr/bin/env python3
import json
import sys
from typing import Any

PROTOCOL_VERSION = "2025-11-25"

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
        "text": json.dumps(
            {
                "environment": "development",
                "feature_flags": {
                    "new_checkout": True,
                    "beta_dashboard": False,
                },
            },
            indent=2,
        ),
    },
    "docs://customer-table": {
        "mimeType": "text/markdown",
        "text": (
            "# customer table\n\n"
            "- id: integer primary key\n"
            "- email: unique text\n"
            "- created_at: timestamp\n"
        ),
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
        return tool_text("Current customer count: 128")
    raise ValueError(f"Unknown tool: {name}")


def handle_resources_read(uri: str) -> dict[str, Any]:
    item = RESOURCE_CONTENTS.get(uri)
    if item is None:
        raise ValueError(f"Resource not found: {uri}")

    return {
        "contents": [
            {
                "uri": uri,
                "mimeType": item["mimeType"],
                "text": item["text"],
            }
        ]
    }


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
            f"The current status is: {status}."
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
    print("capability MCP server started", file=sys.stderr, flush=True)

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

The checked-in example file expands this minimal version so the `mcp.json`
fields are actually visible in behavior:

- `--customer-count` from `args` drives the customer count tool
- `CAPABILITY_EXAMPLE_MODE` and `CAPABILITY_ENVIRONMENT` from `env` show up in
  the settings resource
- `customer_table.md` is loaded relative to `cwd`

### Step 2: Add it to `.nexus3/mcp.json`

```json
{
  "servers": {
    "capability_demo": {
      "command": "python3",
      "args": ["capability_server.py", "--customer-count", "128"],
      "cwd": ".",
      "env": {
        "CAPABILITY_EXAMPLE_MODE": "demo",
        "CAPABILITY_ENVIRONMENT": "development"
      },
      "env_passthrough": ["USER"],
      "enabled": true,
      "fail_if_no_tools": true
    }
  }
}
```

Why these fields are here:

- `command` + `args` shows the split form that many MCP configs use.
- `cwd` keeps the subprocess rooted in the example project.
- `env` and `env_passthrough` show the two ways to shape the subprocess
  environment.
- `enabled` and `fail_if_no_tools` are operational toggles you will often want
  in real projects.
- In the checked-in example, those values are observable through the tool
  output and resource contents, not just stored in config.
- `env_passthrough` is included for realism, but the tutorial keeps outputs
  deterministic instead of echoing host-specific values like `USER`.
- If `python3` is not on your `PATH`, use the absolute interpreter path
  available in your environment.

### Step 3: Connect it from NEXUS3

From the example directory, start a fresh NEXUS session:

```text
nexus3 --fresh
```

If `nexus3` is not on your `PATH` and you are working from the NEXUS3 source
tree, activate that virtualenv first or use:

```text
../../../../.venv/bin/nexus3 --fresh
```

If you run `/mcp` first and see additional configured servers, that is normal.
NEXUS merges global, ancestor, and local MCP config layers; this walkthrough
only depends on `capability_demo`.

In the REPL:

```text
/mcp connect capability_demo --allow-all --private
/mcp tools capability_demo
/mcp resources capability_demo
/mcp prompts capability_demo
```

If you want to see the normal consent and sharing prompts, omit
`--allow-all --private`.

What you should see:

- tools:
  - `mcp_capability_demo_add`
  - `mcp_capability_demo_get_customer_count`
- resources:
  - `config://app/settings`
  - `docs://customer-table`
- prompts:
  - `customer_summary`
  - `schema_explainer`

## What NEXUS will actually expose to the agent

Only the MCP **tools** become normal callable NEXUS tools.

In this example, the agent can directly call:

- `mcp_capability_demo_add`
- `mcp_capability_demo_get_customer_count`

The resources and prompts are available in the MCP connection, but they are
not automatically turned into callable NEXUS tools.

That means:

- `/mcp resources capability_demo` works
- `/mcp prompts capability_demo` works
- the MCP client layer can read those resources and prompts
- but the agent does not automatically get a tool named after each resource or
  prompt

Today that distinction is also visible in the REPL surface:

- the REPL has discovery commands for resources and prompts
- it does not currently add a dedicated `/mcp read-resource` or `/mcp get-prompt`
  command
- direct reads and prompt fetches still happen through the MCP client layer
  with `resources/read` and `prompts/get`

## Optional: exercise `resources/read` and `prompts/get` directly

If you want to go beyond REPL discovery and verify the underlying capability
calls through NEXUS's own Python MCP client, the checked-in example bundle
includes a helper script:

```text
python ./inspect_capabilities.py
```

Run that from the `202-capabilities/` example directory. If you are using the
NEXUS3 source tree without an activated virtualenv, use:

```text
../../../../.venv/bin/python ./inspect_capabilities.py
```

The helper discovers the NEXUS3 source tree from its own file location,
launches the stdio server through the same transport/client layer NEXUS uses,
and demonstrates:

- `tools/list`
- `resources/list`
- `prompts/list`
- `resources/read`
- `prompts/get`

If you already activated the source-tree virtualenv, plain `python ...` is
fine. The helper does not require a specific working directory.

The core pattern is:

```python
async with MCPClient(transport) as client:
    settings = await client.read_resource("config://app/settings")
    prompt = await client.get_prompt(
        "customer_summary",
        {"customer_name": "Acme", "status": "green"},
    )
```

That is the NEXUS-specific bridge between "the REPL can list this surface" and
"the underlying MCP client can fetch it."

## When resources are the right design

Use resources when the server is publishing content that should be:

- named by URI
- readable rather than executable
- stable enough to browse or fetch on demand

Good examples:

- database schemas
- configuration snapshots
- generated reports
- docs pages

## When prompts are the right design

Use prompts when the server is publishing reusable prompt templates or
server-generated prompt messages.

Good examples:

- a code review template
- an incident update template
- a product-summary template

Prompts are especially useful when the server owns domain-specific prompt
construction logic and wants to expose it in a reusable way.

## When to wrap a resource or prompt with a tool

If you expect an agent to use the surface directly during normal tool calling,
prefer adding a tool wrapper.

Examples:

- instead of only exposing `config://app/settings`, also expose a tool like
  `get_settings_summary`
- instead of only exposing `customer_summary` as a prompt, also expose a tool
  like `render_customer_summary`

Why:

- tools are the MCP surface NEXUS adapts into callable agent tools
- resources and prompts are discoverable/readable, but not automatic tool calls

## Adding more resources

To add another resource:

1. Add an entry to `RESOURCES`
2. Add its content to `RESOURCE_CONTENTS`
3. Make sure `handle_resources_read()` can return it

Example:

```python
RESOURCES.append(
    {
        "uri": "docs://billing-api",
        "name": "Billing API Docs",
        "description": "High-level billing API notes",
        "mimeType": "text/markdown",
    }
)

RESOURCE_CONTENTS["docs://billing-api"] = {
    "mimeType": "text/markdown",
    "text": "# Billing API\n\n- GET /invoices\n- POST /payments\n",
}
```

## Adding more prompts

To add another prompt:

1. Add an entry to `PROMPTS`
2. Add a branch in `handle_prompts_get()`

Example:

```python
PROMPTS.append(
    {
        "name": "release_note_writer",
        "description": "Generate release-note instructions.",
        "arguments": [
            {
                "name": "version",
                "description": "Release version",
                "required": True,
            }
        ],
    }
)
```

And in `handle_prompts_get()`:

```python
elif name == "release_note_writer":
    version = args["version"]
    text = f"Write release notes for version {version}."
```

## HTTP note

Resources and prompts are transport-independent. If you want the same server
over HTTP:

- keep the same `handle_message()` logic
- use the HTTP server shell from the 101 guide
- continue responding to the same MCP methods

## Recommended progression

1. Start with the 101 tools-only server.
2. Add resources when you have content to publish.
3. Add prompts when you have reusable prompt-construction logic.
4. Add tool wrappers around those surfaces when you want normal agent tool
   calling behavior in NEXUS.

## Related docs

- [MCP-SERVER-PYTHON-101.md](./MCP-SERVER-PYTHON-101.md)
- [README.md](../../../nexus3/mcp/README.md)
- [server.py](../../../nexus3/mcp/test_server/server.py)
- [http_server.py](../../../nexus3/mcp/test_server/http_server.py)
- [definitions.py](../../../nexus3/mcp/test_server/definitions.py)
