# NEXUS3 RPC Module

JSON-RPC 2.0 over HTTP (port 8765) for `nexus3 --serve`. Enables multi-agent automation, testing, orchestration.

## Purpose
- **Multi-Agent**: Create/destroy isolated agents with independent context/logs/permissions.
- **Hierarchies**: Parent/child agents (max depth 5); subagents inherit permission ceilings.
- **Sandboxing**: Default `sandboxed` preset (read-only in `cwd`); enable writes via `allowed_write_paths`.
- **Persistence**: Auto-restore inactive agents from saved sessions.
- **In-Process API**: `DirectAgentAPI` bypasses HTTP (~10x faster).
- **Secure**: Localhost-only, `nxk_` API keys (~/.nexus3/rpc.token), 1MB limits.

**Use Cases**: Pipelines, swarms, external orchestrators (e.g., Claude), testing.

## Permissions
RPC agents default to `sandboxed` (read-only in `cwd`, no writes/tools).  
- `preset: "trusted"`: Full read/write.  
- `allowed_write_paths`: Enable writes (must be in `cwd`).  
- Subagents ≤ parent perms; no `yolo` via RPC.

```bash
nexus-rpc create reader --cwd /tmp/project  # Read-only
nexus-rpc create writer --cwd /tmp/project --allowed-write-paths /tmp/project/output
nexus-rpc create coord --preset trusted
```

## Architecture
```
Client → HTTP (http.py) → Auth → Route (/rpc → GlobalDispatcher | /agent/{id} → AgentPool.get/restore)
                          ↓
                    Dispatcher → Session → Provider
```
- **pool.py**: `AgentPool` manages lifecycle; `SharedComponents` (config/providers).
- **dispatchers**: `GlobalDispatcher` (lifecycle); `Dispatcher` (send/cancel/tokens).
- **log_multiplexer.py**: Contextvars routes provider logs per-agent.
- **agent_api.py**: In-process `DirectAgentAPI`/`AgentScopedAPI`.

## Exports (__init__.py)
```python
from nexus3.rpc import (
    # Types/Protocol
    Request, Response, parse_request, serialize_response, make_error_response,
    # HTTP
    run_http_server, DEFAULT_PORT=8765,
    # Core
    AgentPool, Agent, SharedComponents, AgentConfig, Dispatcher, GlobalDispatcher,
    # In-Process API
    DirectAgentAPI, AgentScopedAPI,
    # Auth/Detection
    discover_rpc_token, detect_server, wait_for_server,
    # Bootstrap
    bootstrap_server_components,
    # Utils
    LogMultiplexer
)
```

## RPC Methods

### Global (POST /rpc)
| Method | Params | Result |
|--------|--------|--------|
| `create_agent` | `{agent_id?, preset?, cwd?, allowed_write_paths?, model?, ...}` | `{"agent_id": "...", "url": "/agent/..."}` |
| `destroy_agent` | `{"agent_id": "..."}` | `{"success": true}` |
| `list_agents` | `{}` | `{"agents": [...]}` |
| `shutdown_server` | `{}` | `{"success": true}` |

### Per-Agent (POST /agent/{id})
| Method | Params | Result |
|--------|--------|--------|
| `send` | `{"content": "..."}` | `{"content": "..."}` (accumulates chunks) |
| `cancel` | `{"request_id": "..."}` | `{"cancelled": bool}` |
| `get_tokens` | `{}` | Token usage |
| `get_context` | `{}` | `{"message_count": N, ...}` |
| `shutdown` | `{}` | `{"success": true}` |
| `compact` | `{force?: true}` | Compaction stats |

## Usage Examples

### CLI
```bash
nexus3 --serve  # Starts server, prints token
token=$(cat ~/.nexus3/rpc.token)

curl -X POST http://localhost:8765/rpc \
  -H "Authorization: Bearer $token" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"create_agent","params":{"agent_id":"worker"},"id":1}'
```

### Python
```python
import httpx
from nexus3.rpc import discover_rpc_token, Request, serialize_request, detect_server
from nexus3.rpc.bootstrap import bootstrap_server_components  # Server-side

token = discover_rpc_token()
if detect_server() == "nexus_server":
    async with httpx.AsyncClient() as client:
        req = Request(method="list_agents", id=1)
        resp = await client.post("http://localhost:8765/rpc", 
                                 json=req.dict(), 
                                 headers={"Authorization": f"Bearer {token}"})
```

### Server Bootstrap
```python
from nexus3.rpc.bootstrap import bootstrap_server_components
from nexus3.rpc.http import run_http_server
from nexus3.config.schema import Config

config = Config.load()  # Or from CLI
pool, global_dispatcher, shared = await bootstrap_server_components(config, Path(".nexus3/logs"))
await run_http_server(pool, global_dispatcher)
```

### In-Process (Skills)
```python
# In NexusSkill.services
api = services.get("agent_api")  # DirectAgentAPI
resp = await api.create_agent("sub-worker")
scoped = api.for_agent("sub-worker")
result = await scoped.send("Task...")
```

## Dependencies
- **Internal**: nexus3.core/session/skill/context/provider/config/mcp.
- **External**: httpx (detection).

Updated: 2026-01-17 from source analysis.