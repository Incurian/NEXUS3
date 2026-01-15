# nexus3/mcp

## Purpose

The `nexus3.mcp` module provides a complete **client-side implementation** of the **Model Context Protocol (MCP)** for the NEXUS3 agent framework. It enables NEXUS3 agents to connect to external MCP servers (local subprocess or remote HTTP) and use their tools seamlessly as native NEXUS3 skills.

**Key Goals:**
- Secure integration of external tools (permissioned, sandboxed env vars).
- Persistent multi-server management (per-agent visibility).
- Automatic tool discovery and skill adaptation.
- Full support for [MCP Specification 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25).

## Dependencies

**Core (Python stdlib):**
- `asyncio`, `dataclasses`, `json`, `logging`, `os`, `typing`

**External (optional):**
- `httpx` (for `HTTPTransport`)

**NEXUS3 Internal:**
- `nexus3.core.errors` (`NexusError`)
- `nexus3.core.permissions` (`AgentPermissions`, `PermissionLevel`)
- `nexus3.core.types` (`ToolResult`)
- `nexus3.core.validation` (`validate_tool_arguments`)
- `nexus3.skill.base` (`BaseSkill`)

## Key Components

| Module | Key Classes/Functions | Description |
|--------|-----------------------|-------------|
| `client.py` | `MCPClient`, `MCPError` | Core MCP lifecycle: connect, init handshake, `list_tools()`, `call_tool()`. Context manager support. |
| `protocol.py` | `MCPTool`, `MCPToolResult`, `MCPServerInfo`, `MCPClientInfo`, `PROTOCOL_VERSION="2025-11-25"` | Dataclasses for MCP protocol messages/schemas. |
| `permissions.py` | `can_use_mcp()`, `requires_mcp_confirmation()` | Permission checks: YOLO/TRUSTED only; prompts for new servers. |
| `registry.py` | `MCPServerConfig`, `ConnectedServer`, `MCPServerRegistry` | Multi-server registry: connect/disconnect, agent-visible skills, health checks. |
| `skill_adapter.py` | `MCPSkillAdapter` | Wraps `MCPTool` as `BaseSkill` (prefixed: `mcp_{server}_{tool}`). |
| `transport.py` | `MCPTransport` (ABC), `StdioTransport`, `HTTPTransport`, `build_safe_env()` | JSON-RPC transports; secure subprocess env (SAFE_ENV_KEYS). |
| `__init__.py` | All public exports | Convenient imports. |

## Architecture Summary

```
┌─────────────────────┐    ┌─────────────────────┐
│   NEXUS3 Agent      │    │   MCP Server        │
│                     │    │                     │
│  ┌──────────────┐   │◄──►│  (stdio/HTTP)       │
│  │ MCPSkill-    │   │    │                     │
│  │ Adapter      │   │    │  ┌──────────────┐   │
│  │ (BaseSkill)  │   │    │  │ Tools (echo,  │   │
│  └──────┬───────┘   │    │  │ add, etc.)    │   │
│         │            │    │  └──────────────┘   │
│  ┌──────▼──────┐   │    └─────────────────────┘
│  │ MCPServer-  │   │
│  │ Registry    │   │
│  │ (multi-conn)│   │
│  └──────┬───────┘   │
│         │            │
│  ┌──────▼──────┐   │
│  │ MCPClient   │   │
│  │ (per-server)│   │
│  └──────┬───────┘   │
│         │            │
│  ┌──────▼──────┐   │
│  │ MCPTransport│   │  ┌──────────────┐
│  │ (Stdio/HTTP)│   │  │ Permissions  │
│  └──────────────┘   │  │ (YOLO/TRUST) │
└─────────────────────┘  └──────────────┘
```

**Flow:**
1. **Registry** manages `ConnectedServer` instances (shared/private).
2. **Permissions** checked before connect (`requires_mcp_confirmation`).
3. **Transport** handles JSON-RPC (secure env for stdio).
4. **Client** performs init → tool discovery → calls.
5. **Adapters** expose tools as prefixed skills (`mcp_test_echo`).

**Security Highlights:**
- Stdio: Restricted env vars (`SAFE_ENV_KEYS` + explicit/passthrough).
- Visibility: Per-agent (`owner_agent_id`, `shared`).
- Health: `check_connections()` removes dead stdio processes.

## Usage Examples

### 1. Direct Client (Quick Test)
```python
from nexus3.mcp import MCPClient, StdioTransport

transport = StdioTransport(["python", "-m", "nexus3.mcp.test_server"])
async with MCPClient(transport) as client:
    tools = await client.list_tools()
    result = await client.call_tool("echo", {"message": "hello world"})
    print(result.to_text())  # "hello world"
```

### 2. Server Registry (Production)
```python
from nexus3.mcp import MCPServerRegistry, MCPServerConfig

registry = MCPServerRegistry()
config = MCPServerConfig(
    name="test",
    command=["python", "-m", "nexus3.mcp.test_server"],
    # env={"MY_VAR": "value"}, env_passthrough=["API_KEY"]
)
server = await registry.connect(config, owner_agent_id="worker-1", shared=True)
skills = registry.get_all_skills("worker-1")  # List[MCPSkillAdapter]

# Later...
dead_servers = await registry.check_connections()
await registry.close_all()
```

### 3. Permissions Check
```python
from nexus3.mcp.permissions import requires_mcp_confirmation
# Prompt if needed: session_allowances.add("mcp:test")
```

## Test Servers

Local test servers in `./test_server/`:

```bash
# Stdio mode
python -m nexus3.mcp.test_server

# HTTP mode
python -m nexus3.mcp.test_server.http_server --port 9000
```

**Tools provided:** `echo` (string), `get_time` (datetime), `add` (numbers).

HTTP endpoint: `POST http://localhost:9000` (JSON-RPC).

## Public API

From `__init__.py`:
```python
from nexus3.mcp import (
    ConnectedServer, HTTPTransport, MCPClient, MCPError, MCPServerConfig,
    MCPServerInfo, MCPServerRegistry, MCPSkillAdapter, MCPTool,
    MCPToolResult, MCPTransport, StdioTransport
)
```

## Integration Notes

- Register `registry.get_all_skills(agent_id)` in NEXUS3 agent skill loader.
- Skill names prefixed to avoid conflicts.
- `MCPToolResult.to_text()` extracts output.
- Errors: `MCPError` wraps server/protocol issues.

---
*Updated: 2026-01-15 | Part of NEXUS3 agent framework.*
