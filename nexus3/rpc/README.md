# NEXUS3 RPC Module

JSON-RPC 2.0 protocol implementation for NEXUS3 headless mode. Enables programmatic control of NEXUS3 via HTTP for automation, testing, and integration with external tools.

## Purpose

This module provides the protocol layer for `nexus3 --serve` mode. Instead of interactive REPL input/output, it runs an HTTP server that accepts JSON-RPC 2.0 requests and returns responses. This enables:

- Automated testing without human interaction
- Integration with external AI orchestrators (e.g., Claude Code)
- Multi-agent scenarios with dynamic agent creation/destruction
- Subagent communication (parent/child agents with permission ceilings)
- Scripted automation pipelines
- Multi-turn conversations with persistent context per agent
- Cross-session auto-restoration from saved sessions
- Permission-controlled agent hierarchies (max depth 5)

## Architecture

```
                                    +-----------------+
                                    |  GlobalDispatcher |
                                    |  (create/destroy/ |
                                    |   list/shutdown)  |
                                    +-----------------+
                                           ^
                                           | POST / or /rpc
                                           |
HTTP POST --> read_http_request() --> Path Router --> dispatch()
                  |                        |
                  | API Key Auth           | POST /agent/{id}
                  |                        v
                  |                  +-----------------+
                  |                  |   AgentPool     |
                  |                  |   .get(id) or   |
                  |                  |   .restore()    |
                  |                  +-----------------+
                  |                        |
                  |                        v
                  |                  +-----------------+
                  |                  |   Agent         |
                  |                  |   .dispatcher   |
                  |                  +-----------------+
                  |                        |
                  |                        v
                  |                  +-----------------+
                  |                  |   Dispatcher    |
                  |                  |   (send/cancel/ |
                  |                  |    shutdown)    |
                  |                  +-----------------+
```

### Multi-Agent Architecture

```
+-------------+                                     +-----------------+
|   Caller    |  POST /                             |  GlobalDispatcher|
| (any tool)  | ----------------------------------> | create_agent     |
|             | <---------------------------------- | (cwd, model,     |
|             |                                     |  write_paths)    |
+-------------+                                     +-----------------+
      |                                             +-----------------+
      |         POST /agent/{id}                    |     AgentPool    |
      | ------------------------------------------> |  (permissions,   |
      | <------------------------------------------ |   MCP tools)     |
      |                                             +-----------------+
      |                                             +-----------------+
      |                                             |     Agent       |
      |                                             |   Dispatcher    |
      |                                             |  send/cancel/   |
      |                                             |  get_tokens/... |
                                                    +-----------------+
```

## Module Files

| File | Purpose |
|------|---------|
| `types.py` | JSON-RPC 2.0 Request/Response dataclasses |
| `protocol.py` | Parsing, serialization, error codes |
| `auth.py` | API key generation/validation/storage |
| `detection.py` | Server detection/wait utilities |
| `dispatcher.py` | Per-agent method dispatcher (send/cancel/shutdown/get_tokens) |
| `global_dispatcher.py` | Global methods (create/destroy/list/shutdown agents) |
| `log_multiplexer.py` | Contextvars-based multi-agent log routing |
| `pool.py` | AgentPool, Agent, SharedComponents, AgentConfig (cwd/model support) |
| `http.py` | HTTP server with path routing + auto-session restore |
| `__init__.py` | Public exports |

## Key Types

### `Request` / `Response` (types.py)

Unchanged from previous.

### `HttpRequest` (http.py)

Unchanged.

### `Agent` (pool.py)

```python
@dataclass
class Agent:
    agent_id: str
    logger: SessionLogger
    context: ContextManager
    services: ServiceContainer  # Includes permissions, model, mcp_registry
    registry: SkillRegistry
    session: Session
    dispatcher: Dispatcher
    created_at: datetime
```

### `AgentConfig` (pool.py)

Per-agent options:

| Field | Type | Description |
|-------|------|-------------|
| `agent_id` | `str \| None` | Auto-gen if None |
| `system_prompt` | `str \| None` | Override default |
| `preset` | `str \| None` | e.g. "sandboxed" |
| `cwd` | `Path \| None` | Sandbox root |
| `delta` | `PermissionDelta \| None` | Tool overrides |
| `parent_permissions` | `AgentPermissions \| None` | Ceiling |
| `parent_agent_id` | `str \| None` | Lineage tracking |
| `model` | `str \| None` | Model alias/ID |

### `SharedComponents` (pool.py)

Immutable shared resources:

| Field | Description |
|-------|-------------|
| `config` | Global Config |
| `provider` | AsyncProvider (shared) |
| `prompt_loader` | System prompts |
| `base_log_dir` | Agent subdirs |
| `log_streams` | Enabled streams |
| `custom_presets` | From config |
| `mcp_registry` | MCP servers |

## Authentication (auth.py)

Unchanged. Keys: `nxk_` + b64. Storage: `~/.nexus3/server.key`.

## Server Detection (detection.py)

Unchanged.

## Log Multiplexer (log_multiplexer.py)

Unchanged.

## Agent Pool (pool.py)

Manages lifecycle, permissions (depth <=5), MCP tools (TRUSTED+).

### Key Methods

| Method | Description |
|--------|-------------|
| `create(agent_id?, config?)` | Full agent init w/ permissions/MCP |
| `create_temp(config?)` | Temp ID (`.1`, `.2`) |
| `restore_from_saved(saved)` | Auto-restore w/ history |
| `destroy(id)` | Cancel requests, cleanup |
| `get(id)` / `list()` | Access/list |
| `get_children(id)` | Child IDs |
| `should_shutdown` | All agents shutdown? |

`list()` returns:

```python
[{"agent_id", "is_temp", "created_at", "message_count", "should_shutdown",
  "parent_agent_id", "child_count"}, ...]
```

Temp agents: ID starts w/ `.`, excluded from saves.

## Global Dispatcher

Agent lifecycle.

### Methods

| Method | Params | Returns | Notes |
|--------|--------|---------|-------|
| `create_agent` | `agent_id?`, `system_prompt?`, `preset?`, `disable_tools?`, `parent_agent_id?`, `cwd?`, `allowed_write_paths?`, `model?` | `{"agent_id", "url"}` | Sandbox write logic |
| `destroy_agent` | `{"agent_id"}` | `{"success", "agent_id"}` | Cancels requests |
| `list_agents` | - | `{"agents": [...]}` | w/ parent/child info |
| `shutdown_server` | - | `{"success", "message"}` | Graceful exit |

**create_agent** sandboxing (`sandboxed`/`worker` presets):
- `allowed_write_paths?`: explicit write dirs (else read-only)
- `cwd?`: must be in parent paths
- `disable_tools` → `PermissionDelta`

Defaults `preset="sandboxed"` for tool overrides.

## Dispatcher (per-agent)

| Method | Params | Returns | Notes |
|--------|--------|---------|-------|
| `send` | `{"content", "request_id?"}` | `{"content", "request_id"}` | Non-streaming |
| `cancel` | `{"request_id"}` | `{"cancelled", "request_id?", "reason?"}` | Cooperative |
| `shutdown` | - | `{"success"}` | Agent flag |
| `get_tokens` | - | Token breakdown | If context |
| `get_context` | - | `{"message_count", "system_prompt"}` | If context |

## HTTP Server (http.py)

Pure asyncio, localhost-only.

**Routing**:
- `POST /`, `/rpc` → Global
- `POST /agent/{id}` → Agent (auto-restore if saved)

**Security**:
- Localhost bind
- API key (Bearer)
- 1MB body limit, 30s timeouts
- Agent ID validation (no traversal)

**Auto-Restore**: If `session_manager` provided, inactive saved agents auto-restored on request.

## Protocol / Errors

Unchanged.

## Data Flow

Updated for auto-restore, cancel.

## Dependencies

Add `nexus3.mcp.*` for MCP tools.

## Usage Examples

### Create Sandboxed Agent w/ Writes

```bash
curl -X POST http://localhost:8765/ \\
  -H "Authorization: Bearer nxk_..." \\
  -d '{\"jsonrpc\":\"2.0\",\"method\":\"create_agent\",\"params\":{\"agent_id\":\"worker\",\"preset\":\"sandboxed\",\"cwd\":\"/tmp/sandbox\",\"allowed_write_paths\":[\"/tmp/sandbox\"] },\"id\":1}'
```

### Create w/ Model + Disable Tool

```bash
curl ... -d '{\"params\":{\"agent_id\":\"coder\",\"model\":\"gpt-4o-mini\",\"disable_tools\":[\"write_file\"]}}'
```

### List w/ Hierarchy

```bash
curl ... -d '{\"method\":\"list_agents\",\"id\":2}'
# [{"agent_id":"coordinator","parent_agent_id":null,"child_count":1}, {"agent_id":"worker","parent_agent_id":"coordinator","child_count":0}]
```

### Cancel Request

```bash
# T1: send w/ request_id
curl .../agent/worker -d '{\"method\":\"send\",\"params\":{\"content\":\"Long task\",\"request_id\":\"req1\"}}'

# T2: cancel
curl .../agent/worker -d '{\"method\":\"cancel\",\"params\":{\"request_id\":\"req1\"}}'
```

More examples unchanged.

## Command Line / Client

Unchanged.

## Summary of RPC Methods

**Global**:
- `create_agent` (enhanced)
- `destroy_agent`
- `list_agents` (hierarchy)
- `shutdown_server`

**Agent**:
- `send`
- `cancel` (new)
- `shutdown`
- `get_tokens`
- `get_context`
