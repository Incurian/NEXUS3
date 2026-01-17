# nexus3/mcp
## Purpose

The `nexus3.mcp` module is a **complete client-side implementation** of the **Model Context Protocol (MCP)** for the NEXUS3 agent framework. It enables NEXUS3 agents to securely connect to external MCP servers (via stdio subprocess or HTTP) and use their tools as native NEXUS3 skills.

**Key Features:**
- Secure: Permission checks (TRUSTED/YOLO only), safe subprocess env vars, per-agent visibility.
- Persistent multi-server registry with health checks.
- Automatic tool discovery and skill adaptation (prefixed names: `mcp_{server}_{tool}`).
- Full MCP spec support: [2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25).

## Key Classes & Functions

| Module/File | Key Exports | Purpose |
|-------------|-------------|---------|
| `__init__.py` | `MCPClient`, `MCPServerRegistry`, `StdioTransport`, etc. | Public API exports. |
| `client.py` | `MCPClient`, `MCPError` | MCP lifecycle: connect/init/list_tools/call_tool. Context manager. |
| `protocol.py` | `MCPTool`, `MCPToolResult`, `MCPServerInfo`, `PROTOCOL_VERSION` | Protocol dataclasses/schemas. |
| `permissions.py` | `can_use_mcp(permissions)`, `requires_mcp_confirmation(...)` | Agent permission checks. |
| `registry.py` | `MCPServerConfig`, `ConnectedServer`, `MCPServerRegistry` | Multi-server management, agent-visible skills. |
| `skill_adapter.py` | `MCPSkillAdapter` | Adapts `MCPTool` → `BaseSkill`. |
| `transport.py` | `MCPTransport`(ABC), `StdioTransport`, `HTTPTransport`, `build_safe_env` | JSON-RPC transports (secure stdio env). |

## Usage Examples

### 1. Direct Client (Quick Test)
```python
from nexus3.mcp import MCPClient, StdioTransport

transport = StdioTransport(["python", "-m", "nexus3.mcp.test_server"])
async with MCPClient(transport) as client:
    tools = await client.list_tools()
    result = await client.call_tool("echo", {"message": "hello world"})
    print(result.to_text())  # &quot;hello world&quot;
```

### 2. Server Registry (Production)
```python
from nexus3.mcp import MCPServerRegistry, MCPServerConfig

registry = MCPServerRegistry()
config = MCPServerConfig(
    name="test",
    command=["python", "-m", "nexus3.mcp.test_server"]
    # env={&quot;KEY&quot;: &quot;value&quot;}, env_passthrough=[&quot;API_KEY&quot;]
)
server = await registry.connect(config, owner_agent_id="agent1", shared=True)
skills = registry.get_all_skills("agent1")  # [MCPSkillAdapter, ...]

# Cleanup
await registry.close_all()
```

### 3. Permissions
```python
from nexus3.mcp.permissions import can_use_mcp, requires_mcp_confirmation
if can_use_mcp(agent.permissions) and not requires_mcp_confirmation(...):
    # Allow MCP access
    pass
```

## Test Servers
In `./test_server/`:
```bash
python -m nexus3.mcp.test_server  # Stdio
python -m nexus3.mcp.test_server.http_server --port 9000  # HTTP
```
Tools: `echo`, `get_time`, `add`.

## Integration
- Load skills: `registry.get_all_skills(agent_id)` in NEXUS3 agent.
- Errors: Catch `MCPError`.
- Requires `httpx` for HTTP.

---
*Updated: 2026-01-17*
