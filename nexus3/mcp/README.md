# nexus3/mcp

MCP (Model Context Protocol) client implementation for NEXUS3.

This module provides client-side support for connecting NEXUS3 agents to external MCP servers and using their tools as native skills.

**MCP Spec**: [2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25)

## Features

- Full MCP protocol support (initialize, tools/list, tools/call)
- StdioTransport: Launch local servers as subprocesses
- HTTPTransport: Connect to remote HTTP MCP servers
- MCPServerRegistry: Manage multiple servers (shared/private)
- MCPSkillAdapter: Integrate MCP tools as NEXUS3 skills (prefixed `mcp_{server}_{tool}`)
- Permissions: TRUSTED/YOLO agents only; confirmation prompts

## Quick Start

```python
from nexus3.mcp import MCPClient, StdioTransport

# Connect to test server
transport = StdioTransport([&quot;python&quot;, &quot;-m&quot;, &quot;nexus3.mcp.test_server&quot;])
async with MCPClient(transport) as client:
    tools = await client.list_tools()
    result = await client.call_tool(&quot;echo&quot;, {&quot;message&quot;: &quot;hello&quot;})
    print(result.to_text())  # &quot;hello&quot;
```

## Components

### `MCPClient`

Core client for MCP lifecycle.

- `async with MCPClient(transport) as client:`
- `await client.list_tools() → list[MCPTool]`
- `await client.call_tool(name, arguments) → MCPToolResult`
- Properties: `server_info`, `tools`, `is_initialized`

Raises `MCPError` on protocol/server errors.

### Transports (`MCPTransport`)

Abstract base for send/receive JSON-RPC over various protocols.

- **`StdioTransport(command, env=None, cwd=None)`**
  - Launches subprocess, communicates via stdin/stdout (newline-delimited JSON).
  - Auto-handles graceful shutdown.

- **`HTTPTransport(url, headers=None, timeout=30)`**
  - POST JSON-RPC to HTTP endpoint.
  - Requires `httpx`: `pip install httpx`.

Both support context manager (`async with transport:`).

### `MCPServerRegistry`

Manages persistent connections to multiple servers.

```python
registry = MCPServerRegistry()

config = MCPServerConfig(
    name=&quot;test&quot;,
    command=[&quot;python&quot;, &quot;-m&quot;, &quot;nexus3.mcp.test_server&quot;]
)
server = await registry.connect(config, owner_agent_id=&quot;main&quot;, shared=False)

# Get skills for agent
skills = registry.get_all_skills(&quot;main&quot;)

await registry.close_all()
```

- `get_all_skills(agent_id)`: Visible skills only
- `get(name, agent_id)`: Server if visible
- `check_connections()`: Remove dead stdio servers
- `ConnectedServer`: Holds `client`, `skills`, visibility flags

### `MCPSkillAdapter`

Wraps `MCPTool` as `nexus3.skill.base.BaseSkill`.

```python
adapter = MCPSkillAdapter(client, tool, server_name=&quot;test&quot;)
# name = &quot;mcp_test_echo&quot;, description/tool schema preserved
```

`execute(**kwargs) → ToolResult(output|error)`.

### Permissions

Utility functions for agent permission checks:

- `can_use_mcp(permissions) → bool`: `True` for YOLO/TRUSTED/None
- `requires_mcp_confirmation(permissions, server_name, session_allowances) → bool`
  - Prompts TRUSTED agents for new servers (`mcp:{server_name}`)

## Test Servers

For development/testing:

```bash
# Stdio (subprocess-compatible)
python -m nexus3.mcp.test_server

# HTTP
python -m nexus3.mcp.test_server.http_server --port 9000
```

**Tools**: `echo` (string), `get_time` (datetime), `add` (numbers).

## API Reference

Public API (from `__init__.py`):

```python
from nexus3.mcp import (
    MCPClient, MCPError,
    MCPServerConfig, MCPServerRegistry, ConnectedServer,
    MCPSkillAdapter,
    HTTPTransport, StdioTransport,
    MCPTool, MCPToolResult, MCPServerInfo
)
```

Full types/docs in source. Protocol version: `2025-11-25`.

## Integration

Skills auto-discovered/registered via registry in NEXUS3 agents.
Permissions enforced before connecting/calling.

---
*Part of NEXUS3 agent framework.*
