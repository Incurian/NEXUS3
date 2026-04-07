# nexus3.mcp.test_server

Local MCP test servers used for development and integration testing.

## Overview

This package provides simple stdio- and HTTP-based MCP servers plus shared
definitions for exercising the NEXUS3 MCP client and adapter layers.

Available entry points:

- [`server.py`](/home/inc/repos/NEXUS3/nexus3/mcp/test_server/server.py)
  - stdio JSON-RPC test server
- [`http_server.py`](/home/inc/repos/NEXUS3/nexus3/mcp/test_server/http_server.py)
  - HTTP test server for `HTTPTransport`
- [`paginating_server.py`](/home/inc/repos/NEXUS3/nexus3/mcp/test_server/paginating_server.py)
  - pagination-focused variant for list testing
- [`definitions.py`](/home/inc/repos/NEXUS3/nexus3/mcp/test_server/definitions.py)
  - shared tools, resources, prompts, and response helpers

Shared test surface:

- Tools: `echo`, `get_time`, `add`, `slow_operation`
- Resources: `file:///readme.txt`, `file:///config.json`,
  `file:///data/users.csv`
- Prompts: `greeting`, `code_review`, `summarize`

Typical usage:

```bash
python -m nexus3.mcp.test_server
python -m nexus3.mcp.test_server.http_server --port 9000
python -m nexus3.mcp.test_server.paginating_server
```

For MCP client/runtime documentation, see
[`nexus3/mcp/README.md`](/home/inc/repos/NEXUS3/nexus3/mcp/README.md).
For a beginner write-your-own-server tutorial, see
[`docs/references/MCP-SERVER-PYTHON-101.md`](/home/inc/repos/NEXUS3/docs/references/MCP-SERVER-PYTHON-101.md).
For resources/prompts and the broader MCP capability surface, see
[`docs/references/MCP-SERVER-PYTHON-202.md`](/home/inc/repos/NEXUS3/docs/references/MCP-SERVER-PYTHON-202.md).
For checked-in runnable example folders, see
[`docs/references/mcp-python-examples/`](/home/inc/repos/NEXUS3/docs/references/mcp-python-examples/README.md).
