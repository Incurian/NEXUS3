# NEXUS3 RPC Module

JSON-RPC 2.0 protocol implementation for NEXUS3 HTTP server mode. Enables programmatic control of NEXUS3 via HTTP for automation, multi-agent workflows, testing, and integration.

## Purpose

The RPC module powers `nexus3 --serve` (HTTP server on port 8765), transforming the interactive REPL into a headless JSON-RPC 2.0 API server. Key capabilities:
- **Multi-Agent Management**: Dynamic creation/destruction of isolated agents with independent context, logs, and permissions.
- **Permission Hierarchies**: Parent/child agents with permission ceilings (max depth 5), sandboxing via `cwd`/`allowed_write_paths`.
- **Cross-Session Persistence**: Auto-restore inactive agents from saved sessions on incoming requests.
- **In-Process Optimization**: `DirectAgentAPI` bypasses HTTP for same-process calls (~10x faster).
- **Secure & Local**: Localhost-only binding, API key auth (`nxk_` tokens), 1MB body limits.
- **Observability**: Per-agent logging (files/DB), token/context queries, cancellation support.

Use cases: scripted pipelines, external orchestrators (e.g., Claude), multi-turn agent swarms, integration testing.

## Architecture Summary

```
External Client (curl/Python) ──POST──> HTTP Server (localhost:8765)
                                    │
                                    ├─ Auth (Bearer nxk_...) ── OK ── Path Router
                                    │                                 │
                                    │                                 ├─ /, /rpc ──> GlobalDispatcher
                                    │                                 │             ├── create_agent(preset=sandboxed, cwd, model)
                                    │                                 │             ├── destroy_agent(id)
                                    │                                 │             ├── list_agents() ──> [{"agent_id", "parent_id", "child_count"}]
                                    │                                 │             └── shutdown_server()
                                    │                                 │
                                    │                                 └─ /agent/{id} ──> AgentPool.get(id) or restore() ──> Agent.dispatcher
                                    │                                                           │
                                    └─ Error (401/404/500)              └── send(content), cancel(req_id), get_tokens(), shutdown()
```

**Core Layers**:
1. **HTTP (http.py)**: Pure asyncio server, path routing, auto-session restore.
2. **Pool (pool.py)**: `AgentPool` manages `Agent` lifecycle (create/temp/restore/destroy).
3. **Dispatchers**:
   - `GlobalDispatcher`: Agent lifecycle.
   - `Dispatcher`: Per-agent RPC (send/cancel/get_tokens).
4. **Shared (pool.py)**: `SharedComponents` (config/providers/logs/MCP).
5. **Logging (log_multiplexer.py)**: Contextvars routes API logs to correct agent.
6. **Auth/Detection (auth.py/detection.py)**: Tokens, server probing.

**Data Flow (create_agent → send)**:
```
create_agent(preset=worker, cwd=/tmp/sandbox, allowed_write_paths=[...])
  ↓ AgentPool.create() ──> permissions.resolve() ──> services (permissions, cwd, model)
  ↓ Session/Context/Skills (tools filtered by perms + MCP)
  ↓ /agent/worker ──> send("Analyze code") ──> accumulate chunks ──> {"content": response}
```

## Key Modules & Classes

| Module/File | Key Classes/Functions | Role |
|-------------|-----------------------|------|
| `__init__.py` | All exports | Public API |
| `types.py` | `Request`, `Response` | JSON-RPC dataclasses |
| `protocol.py` | `parse_request()`, `make_error_response()` | Serialization/parsing |
| `auth.py` | `ServerTokenManager`, `discover_rpc_token()` | `nxk_` tokens (~/.nexus3/rpc.token) |
| `detection.py` | `detect_server()`, `wait_for_server()` | Port probing (list_agents fingerprint) |
| `dispatcher.py` | `Dispatcher` | Per-agent: `send`, `cancel`, `get_tokens`, `shutdown` |
| `global_dispatcher.py` | `GlobalDispatcher` | Global: `create_agent`, `destroy_agent`, `list_agents` |
| `http.py` | `run_http_server()`, `handle_connection()` | Asyncio HTTP/1.1, routing, auto-restore |
| `log_multiplexer.py` | `LogMultiplexer` | Routes provider logs via contextvars |
| `pool.py` | `AgentPool`, `Agent`, `AgentConfig`, `SharedComponents` | Lifecycle, isolation, MCP integration |
| `agent_api.py` | `DirectAgentAPI`, `AgentScopedAPI`, `ClientAdapter` | In-process API (bypasses HTTP) |

**Agent Structure** (`pool.py`):
```python
@dataclass
class Agent:
    agent_id: str                  # e.g., "worker-1" or ".1" (temp)
    logger: SessionLogger          # Per-agent logs
    context: ContextManager        # History/tokens
    services: ServiceContainer     # perms, cwd, model, agent_api
    registry: SkillRegistry        # Tools (filtered)
    session: Session               # LLM coord
    dispatcher: Dispatcher         # RPC handler
    created_at: datetime
```

## Dependencies

**Internal** (nexus3.*):
- `nexus3.core.*`: Errors, paths, permissions, validation.
- `nexus3.session.*`: Session/Context/Logger.
- `nexus3.skill.*`: Skills/Tools/Services.
- `nexus3.context.*`: ContextManager/Loader.
- `nexus3.mcp.*`: MCP tool integration (TRUSTED+).
- `nexus3.provider.*`: LLM providers.
- `nexus3.config.*`: Config/Models.

**External**:
- `httpx` (detection.py).
- Stdlib: `asyncio`, `json`, `pathlib`, `secrets`, `hmac`.

## RPC Methods

### Global (`POST /` or `/rpc`)
| Method | Params | Returns | Notes |
|--------|--------|---------|-------|
| `create_agent` | `{agent_id?, preset?, disable_tools?, parent_agent_id?, cwd?, allowed_write_paths?, model?, initial_message?}` | `{"agent_id": "...", "url": "/agent/..."}` | Sandboxing: read-only unless `allowed_write_paths`; inherits parent perms |
| `destroy_agent` | `{"agent_id": "..."}` | `{"success": true, "agent_id": "..."}` | Cancels requests |
| `list_agents` | `{}` | `{"agents": [{"agent_id", "is_temp", "created_at", "message_count", "should_shutdown", "parent_agent_id", "child_count"}]}` | Hierarchy info |
| `shutdown_server` | `{}` | `{"success": true, "message": "..."}` | Graceful exit |

**Presets**: `trusted`/`sandboxed`/`worker` (RPC-only; no `yolo`).

### Per-Agent (`POST /agent/{id}`)
| Method | Params | Returns | Notes |
|--------|--------|---------|-------|
| `send` | `{"content": "...", "request_id?": "..."}` | `{"content": "...", "request_id": "..."}` | Non-streaming (accumulates chunks) |
| `cancel` | `{"request_id": "..."}` | `{"cancelled": bool, "request_id": "...", "reason?": "..."}` | Cooperative via tokens |
| `get_tokens` | `{}` | Token usage dict | Prompt/completion/total |
| `get_context` | `{}` | `{"message_count": N, "system_prompt": bool}` | Context state |
| `shutdown` | `{}` | `{"success": true}` | Sets agent flag |

## Usage Examples

### 1. Start Server
```bash
nexus3 --serve  # Generates ~/.nexus3/rpc.token
token=$(nexus3 rpc token)  # Or cat ~/.nexus3/rpc.token
```

### 2. Create Sandboxed Worker
```bash
curl -X POST http://localhost:8765/rpc \
  -H "Authorization: Bearer $token" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "create_agent",
    "params": {
      "agent_id": "worker",
      "preset": "sandboxed",
      "cwd": "/tmp/sandbox",
      "allowed_write_paths": ["/tmp/sandbox"],
      "model": "gpt-4o-mini",
      "initial_message": "You are a code analyst."
    },
    "id": 1
  }'
# {"jsonrpc":"2.0","id":1,"result":{"agent_id":"worker","url":"/agent/worker"}}
```

### 3. Send Message & List
```bash
curl -X POST http://localhost:8765/rpc/agent/worker ... -d '{
  "jsonrpc": "2.0", "method": "send", "params": {"content": "Analyze this Python code..."}, "id": 2
}'
curl ... -d '{"jsonrpc":"2.0","method":"list_agents","id":3}'
```

### 4. Tokens/Context/Cancel
```bash
curl .../agent/worker -d '{"method":"get_tokens","id":4}'  # Token breakdown
curl .../agent/worker -d '{"method":"cancel","params":{"request_id":"abc123"},"id":5}'
```

### 5. Python Client
```python
import httpx
from nexus3.rpc.detection import discover_rpc_token, detect_server
from nexus3.rpc.protocol import serialize_request
from nexus3.rpc.types import Request

token = discover_rpc_token()
if detect_server() == "nexus_server":
    async with httpx.AsyncClient() as client:
        req = Request(method="list_agents", id=1)
        resp = await client.post("http://localhost:8765/rpc", json=req.dict(), headers={"Authorization": f"Bearer {token}"})
```

### 6. Multi-Agent Hierarchy
```bash
# Coordinator (trusted)
curl ... -d '{"method":"create_agent","params":{"agent_id":"coord","preset":"trusted"},"id":1}'
# Worker (inherits coord perms)
curl ... -d '{"method":"create_agent","params":{"agent_id":"worker","parent_agent_id":"coord","preset":"sandboxed"},"id":2}'
```

## Authentication

- **Tokens**: `nxk_` + 32B b64 (`generate_api_key()`).
- **Storage**: `~/.nexus3/rpc.token` (0o600 perms).
- **Discovery**: `discover_rpc_token()` checks ENV/file.
- **Validation**: Constant-time `hmac.compare_digest()`.

## Temp Agents

- IDs: `.1`, `.2` (auto-increment, excluded from saves).
- `pool.create_temp()` for quick tasks.

## In-Process Direct API (agent_api.py)

Skills use `DirectAgentAPI` via `services.get("agent_api")`:
```python
api = DirectAgentAPI(pool, global_dispatcher)
scoped = api.for_agent("worker-1")
resp = await scoped.send("Hello")  # Direct dispatcher.dispatch()
```
`ClientAdapter` matches `NexusClient` interface (HTTP fallback).

## Security Features

- **Localhost-only** bind (`127.0.0.1`).
- **Path validation**: `is_valid_agent_id()` prevents traversal.
- **Permission ceilings**: Subagents can't exceed parent perms.
- **Sandboxing**: `cwd`/write_paths; tools filtered at init.
- **Cooperative cancel**: No hard kills.
- **Rate limits**: Semaphore (32 concurrent).

## Server Lifecycle

- **Startup**: `run_http_server(pool, global_dispatcher, api_key)`.
- **Shutdown**: `shutdown_server()` or all agents `shutdown` + idle timeout.
- **Detection**: `wait_for_server(8765)` for scripts/tests.

Generated/updated: 2026-01-15 from source code analysis.
