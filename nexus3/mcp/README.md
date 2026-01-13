# nexus3/mcp

MCP (Model Context Protocol) client implementation for NEXUS3.

This module provides client-side support for connecting NEXUS3 agents to external MCP servers and using their tools as native skills.

**MCP Spec**: [2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25)

## Features

- Full MCP protocol support (initialize, tools/list, tools/call)
- `StdioTransport`: Launch local servers as subprocesses (supports `env`, `cwd`)
- `HTTPTransport`: Connect to remote HTTP MCP servers (requires `httpx`)
- `MCPServerRegistry`: Manage multiple servers with persistent connections (shared/private per-agent visibility)
  - Auto-disconnects existing servers on reconnect
  - Health checks (`check_connections()`)
  - Skill lookup by prefixed name
- `MCPSkillAdapter`: Integrate MCP tools as NEXUS3 skills (prefixed `mcp_{server}_{tool}`)
- Permissions: YOLO/TRUSTED agents only; confirmation prompts for TRUSTED on new servers (`mcp:{server_name}`)

## Quick Start

```python
from nexus3.mcp import MCPClient, StdioTransport

# Connect to test server
transport = StdioTransport(["python", "-m", "nexus3.mcp.test_server"])
async with MCPClient(transport) as client:
    tools = await client.list_tools()
    result = await client.call_tool("echo", {"message": "hello"})
    print(result.to_text())  # "hello"
```

## Components

### `MCPClient`

Core client for MCP lifecycle.

- Context manager: `async with MCPClient(transport) as client:`
- Explicit: `await client.connect()` / `await client.close()`
- `await client.list_tools() → list[MCPTool]` (caches tools)
- `await client.call_tool(name, arguments) → MCPToolResult`
- Properties: `server_info`, `tools`, `is_initialized`

Raises `MCPError` on protocol/server errors.

### Transports (`MCPTransport`)

Abstract base for JSON-RPC over various protocols. Support `async with transport:`.

- **`StdioTransport(command, env=None, cwd=None)`**
  - Launches subprocess via stdin/stdout (newline-delimited JSON).
  - Graceful shutdown with timeout/kill fallback.
  - `is_connected` property.

- **`HTTPTransport(url, headers=None, timeout=30)`**
  - POST JSON-RPC (synchronous request/response).
  - `pip install httpx`.
  - `is_connected` property.

### `MCPServerRegistry`

Singleton-like manager for multiple persistent servers.

```python
registry = MCPServerRegistry()

config = MCPServerConfig(
    name="test",
    command=["python", "-m", "nexus3.mcp.test_server"]  # or url="http://..."
)
server = await registry.connect(config, owner_agent_id="main", shared=False)

# Agent-visible skills
skills = registry.get_all_skills("main")

await registry.close_all()
```

Key methods:
- `connect(config, owner_agent_id="main", shared=False) → ConnectedServer`
- `get(name, agent_id=None) → ConnectedServer | None` (visibility-checked)
- `list_servers(agent_id=None) → list[str]`
- `get_all_skills(agent_id=None) → list[MCPSkillAdapter]`
- `get_server_for_skill(skill_name) → ConnectedServer | None`
- `check_connections() → list[str]` (removes dead stdio servers)
- `disconnect(name) → bool`
- `close_all()`
- `len(registry)`: Connected server count

`ConnectedServer`: `client`, `skills`, `is_visible_to(agent_id)`, `is_alive()`.

### `MCPSkillAdapter`

Wraps `MCPTool` as `nexus3.skill.base.BaseSkill`.

```python
adapter = MCPSkillAdapter(client, tool, server_name="test")
# name = "mcp_test_echo", description/inputSchema preserved
```

`async execute(**kwargs) → ToolResult(output|error)` (uses `to_text()`).

### Permissions (`permissions.py`)

- `can_use_mcp(permissions) → bool`: `YOLO`/`TRUSTED`/None only
- `requires_mcp_confirmation(permissions, server_name, session_allowances) → bool`: Prompts TRUSTED for new servers

## Test Servers

Development/testing servers in `nexus3/mcp/test_server/`:

```bash
# Stdio (subprocess)
python -m nexus3.mcp.test_server

# HTTP
python -m nexus3.mcp.test_server.http_server --port 9000
```

**Tools**: `echo` (string echo), `get_time` (current datetime), `add` (numbers).

Access: `http://localhost:9000` (JSON-RPC POST).

## API Reference

Public API (from `__init__.py`):

```python
from nexus3.mcp import (
    ConnectedServer, HTTPTransport, MCPClient, MCPError,
    MCPServerConfig, MCPServerInfo, MCPServerRegistry, MCPSkillAdapter,
    MCPTool, MCPToolResult, MCPTransport, StdioTransport
)
```

Full types/docs in source files. Protocol: `2025-11-25`.

## Integration

- Skills auto-discovered/registered in NEXUS3 agents via registry.
- Permissions enforced before connect/call.
- Prefixed names prevent native skill conflicts.

---
*Part of NEXUS3 agent framework.*
