# nexus3.mcp.test_server

Local MCP test servers used for development and integration testing.

## Overview

This package provides simple stdio- and HTTP-based MCP servers plus shared
definitions for exercising the NEXUS3 MCP client and adapter layers.

## Package Structure

- [`__main__.py`](/home/inc/repos/NEXUS3/nexus3/mcp/test_server/__main__.py)
  - `python -m nexus3.mcp.test_server` entry point
- [`server.py`](/home/inc/repos/NEXUS3/nexus3/mcp/test_server/server.py)
  - stdio JSON-RPC server used for default local testing
- [`http_server.py`](/home/inc/repos/NEXUS3/nexus3/mcp/test_server/http_server.py)
  - `aiohttp`-based HTTP server for `HTTPTransport`
- [`paginating_server.py`](/home/inc/repos/NEXUS3/nexus3/mcp/test_server/paginating_server.py)
  - cursor-pagination-focused stdio server for client pagination tests
- [`definitions.py`](/home/inc/repos/NEXUS3/nexus3/mcp/test_server/definitions.py)
  - shared tools, resources, prompts, protocol version, and response helpers

## Entry Points

- [`server.py`](/home/inc/repos/NEXUS3/nexus3/mcp/test_server/server.py)
  - stdio JSON-RPC test server
- [`http_server.py`](/home/inc/repos/NEXUS3/nexus3/mcp/test_server/http_server.py)
  - HTTP test server for `HTTPTransport`
- [`paginating_server.py`](/home/inc/repos/NEXUS3/nexus3/mcp/test_server/paginating_server.py)
  - pagination-focused variant for list testing
- [`definitions.py`](/home/inc/repos/NEXUS3/nexus3/mcp/test_server/definitions.py)
  - shared tools, resources, prompts, and response helpers

## Shared Protocol Surface

The stdio and HTTP variants both implement:

- `initialize`
- `ping`
- `tools/list`
- `tools/call`
- `resources/list`
- `resources/read`
- `prompts/list`
- `prompts/get`

Shared test content:

- Tools: `echo`, `get_time`, `add`, `slow_operation`
- Resources: `file:///readme.txt`, `file:///config.json`,
  `file:///data/users.csv`
- Prompts: `greeting`, `code_review`, `summarize`

Behavior notes:

- JSON-RPC notifications are ignored by the stdio and HTTP servers because
  request objects without an `id` do not generate responses
- parse and unknown-method failures are surfaced as JSON-RPC errors
- `slow_operation` is a simple response helper here; it does not implement a
  full progress-notification stream

## Pagination Variant

[`paginating_server.py`](/home/inc/repos/NEXUS3/nexus3/mcp/test_server/paginating_server.py)
is intentionally narrower than the full test server:

- it exposes `initialize`, `tools/list`, and `tools/call`
- `tools/list` returns cursor-based pages
- environment variables control the synthetic tool surface:
  `MCP_PAGE_SIZE` (default `2`) and `MCP_TOOL_COUNT` (default `5`)

## Typical Usage

```bash
python -m nexus3.mcp.test_server
python -m nexus3.mcp.test_server.http_server --port 9000
python -m nexus3.mcp.test_server.paginating_server
```

## Related Docs

- MCP client/runtime documentation:
  [`nexus3/mcp/README.md`](/home/inc/repos/NEXUS3/nexus3/mcp/README.md)
- Beginner Python MCP tutorial:
  [`docs/references/MCP-SERVER-PYTHON-101.md`](/home/inc/repos/NEXUS3/docs/references/MCP-SERVER-PYTHON-101.md)
- Resources/prompts tutorial:
  [`docs/references/MCP-SERVER-PYTHON-202.md`](/home/inc/repos/NEXUS3/docs/references/MCP-SERVER-PYTHON-202.md)
- Runnable example bundle:
  [`docs/references/mcp-python-examples/README.md`](/home/inc/repos/NEXUS3/docs/references/mcp-python-examples/README.md)
