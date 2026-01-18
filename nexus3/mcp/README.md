# nexus3/mcp
## Purpose

The `nexus3.mcp` module provides a secure client-side implementation of the **Model Context Protocol (MCP)** for NEXUS3 agents. It enables connections to external MCP servers (stdio/HTTP), tool discovery, invocation, and seamless integration as prefixed NEXUS3 skills (`mcp_{server}_{tool}`) with per-agent permissions.

**Key Features:**
- Secure: TRUSTED/YOLO agents only; safe env vars; response ID validation; notification discarding.
- Multi-server registry with health checks and visibility controls.
- MCP spec: [2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25).

## Exports (`__init__.py`)

```python
__all__ = [
    "ConnectedServer", "HTTPTransport", "MCPClient", "MCPError",
    "MCPServerConfig", "MCPServerInfo", "MCPServerRegistry",
    "MCPSkillAdapter", "MCPTool", "MCPToolResult", "MCPTransport", "StdioTransport"
]
```

## Key Classes/Functions

| Module          | Key Items                          | Purpose |
|-----------------|------------------------------------|---------|
| `client.py`     | `MCPClient`, `MCPError`            | Connect, initialize, list/call tools. |
| `protocol.py`   | `MCPTool`, `MCPToolResult`, `MCPServerInfo`, `MCPClientInfo` | Protocol types. |
| `permissions.py`| `can_use_mcp()`, `requires_mcp_confirmation()` | Agent permission checks (TRUSTED/YOLO only). |
| `registry.py`   | `MCPServerConfig`, `ConnectedServer`, `MCPServerRegistry` | Manage connections, get skills per-agent. |
| `skill_adapter.py` | `MCPSkillAdapter`              | Wrap MCPTool as NEXUS3 `BaseSkill`. |
| `transport.py`  | `StdioTransport`, `HTTPTransport`, `MCPTransport` | JSON-RPC over stdio/HTTP (safe env, line limits). |

## Usage Examples

### 1. Direct Client (Simple)
```python
from nexus3.mcp import MCPClient, StdioTransport

transport = StdioTransport(["python", "-m", "some_mcp_server"])
async with MCPClient(transport) as client:
    tools = await client.list_tools()
    result = await client.call_tool("echo", {"message": "hello"})
    print(result.to_text())
```

### 2. Registry (Recommended)
```python
from nexus3.mcp import MCPServerRegistry, MCPServerConfig

registry = MCPServerRegistry()
config = MCPServerConfig(name="test", command=["python", "-m", "nexus3.mcp.test_server"])
server = await registry.connect(config, owner_agent_id="main")
skills = registry.get_all_skills("main")  # List[MCPSkillAdapter]
await registry.close_all()
```

### 3. Permissions Check
```python
from nexus3.mcp.permissions import can_use_mcp, requires_mcp_confirmation

if can_use_mcp(agent.permissions) and not requires_mcp_confirmation(
    agent.permissions, "test", session_allowances
):
    # Use MCP
    pass
```

*Updated: 2026-01-17*
