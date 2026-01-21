# NEXUS3 RPC Module

JSON-RPC 2.0 over HTTP for programmatic control of NEXUS3 agents. Enables multi-agent automation, orchestration, testing pipelines, and external tool integration.

## Overview

The RPC module provides:

- **Multi-Agent Management**: Create, destroy, and manage isolated agent instances
- **Agent Hierarchies**: Parent/child relationships with permission ceiling enforcement
- **Session Persistence**: Auto-restore inactive agents from saved sessions
- **In-Process API**: Direct dispatcher calls for same-process communication (~10x faster than HTTP)
- **Security**: Localhost-only binding, token-based authentication, strict input validation

## Architecture

```
HTTP Client
    │
    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        HTTP Server (http.py)                        │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────────────┐│
│  │ Parse HTTP  │→ │   Authenticate   │→ │          Route           ││
│  │  Request    │  │  (Bearer token)  │  │  / or /rpc → Global     ││
│  └─────────────┘  └─────────────┘  │  /agent/{id} → Agent    ││
│                                      └──────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────┘
                                  │
          ┌───────────────────────┴───────────────────────┐
          ▼                                               ▼
┌─────────────────────────┐                   ┌─────────────────────────┐
│   GlobalDispatcher      │                   │      AgentPool          │
│  (global_dispatcher.py) │                   │       (pool.py)         │
├─────────────────────────┤                   ├─────────────────────────┤
│ create_agent            │                   │ get(agent_id) → Agent   │
│ destroy_agent           │                   │ get_or_restore()        │
│ list_agents             │◄─────────────────►│ create() / destroy()    │
│ shutdown_server         │                   │ list() / create_temp()  │
└─────────────────────────┘                   └───────────┬─────────────┘
                                                          │
                                                          ▼
                                              ┌─────────────────────────┐
                                              │         Agent           │
                                              ├─────────────────────────┤
                                              │ agent_id                │
                                              │ context: ContextManager │
                                              │ session: Session        │
                                              │ services: ServiceContainer
                                              │ dispatcher: Dispatcher  │
                                              └───────────┬─────────────┘
                                                          │
                                                          ▼
                                              ┌─────────────────────────┐
                                              │      Dispatcher         │
                                              │    (dispatcher.py)      │
                                              ├─────────────────────────┤
                                              │ send                    │
                                              │ cancel                  │
                                              │ get_tokens              │
                                              │ get_context             │
                                              │ get_messages            │
                                              │ compact                 │
                                              │ shutdown                │
                                              └─────────────────────────┘
```

## Module Files

| File | Purpose |
|------|---------|
| `__init__.py` | Public exports and module documentation |
| `types.py` | JSON-RPC 2.0 `Request` and `Response` dataclasses |
| `protocol.py` | JSON-RPC parsing, serialization, error codes |
| `http.py` | Pure asyncio HTTP server with path-based routing |
| `dispatcher.py` | Per-agent JSON-RPC method handler |
| `global_dispatcher.py` | Global methods (create/destroy/list agents) |
| `dispatch_core.py` | Shared dispatch infrastructure |
| `pool.py` | `AgentPool`, `Agent`, `SharedComponents`, `AgentConfig` |
| `agent_api.py` | In-process API (`DirectAgentAPI`, `AgentScopedAPI`) |
| `auth.py` | Token generation, validation, secure storage |
| `detection.py` | Server detection and probing |
| `discovery.py` | Multi-server discovery across ports |
| `log_multiplexer.py` | Routes provider logs to correct agent via contextvars |
| `bootstrap.py` | Server component wiring and initialization |

---

## JSON-RPC 2.0 Protocol

### Types (`types.py`)

```python
@dataclass
class Request:
    jsonrpc: str           # Must be "2.0"
    method: str            # Method name to invoke
    params: dict | None    # Named parameters (positional not supported)
    id: str | int | None   # Request ID (None = notification)

@dataclass
class Response:
    jsonrpc: str           # Always "2.0"
    id: str | int | None   # Echoed from request
    result: Any | None     # Success result (mutually exclusive with error)
    error: dict | None     # Error object {code, message, data?}
```

### Error Codes (`protocol.py`)

| Code | Constant | Meaning |
|------|----------|---------|
| -32700 | `PARSE_ERROR` | Invalid JSON |
| -32600 | `INVALID_REQUEST` | Not a valid JSON-RPC request |
| -32601 | `METHOD_NOT_FOUND` | Method does not exist |
| -32602 | `INVALID_PARAMS` | Invalid method parameters |
| -32603 | `INTERNAL_ERROR` | Internal server error |
| -32000 | `SERVER_ERROR` | Server error range start |

### Protocol Functions

```python
# Server-side
parse_request(json_line: str) -> Request
serialize_response(response: Response) -> str
make_error_response(id, code, message, data=None) -> Response
make_success_response(id, result) -> Response

# Client-side
serialize_request(request: Request) -> str
parse_response(json_line: str) -> Response
```

---

## HTTP Server (`http.py`)

Pure asyncio HTTP server with no external dependencies (except stdlib).

### Security

- **Localhost-only**: Binds to `127.0.0.1` only, never `0.0.0.0`
- **Request limits**: 1MB body, 32KB headers, 128 headers max
- **Rate limiting**: Semaphore limits concurrent connections (default 32)
- **Token auth**: Bearer token required when `api_key` is configured

### Routing

| Path | Handler |
|------|---------|
| `POST /` | GlobalDispatcher |
| `POST /rpc` | GlobalDispatcher |
| `POST /agent/{agent_id}` | Agent's Dispatcher |

### HTTP Pipeline

1. Parse HTTP request
2. Validate method (POST only)
3. Authenticate (Bearer token)
4. Route to dispatcher
5. Auto-restore agent if needed
6. Parse JSON-RPC request
7. Dispatch to handler
8. Send response

### Server Function

```python
async def run_http_server(
    pool: AgentPool,
    global_dispatcher: GlobalDispatcher,
    port: int = 8765,
    host: str = "127.0.0.1",
    api_key: str | None = None,
    session_manager: SessionManager | None = None,
    max_concurrent: int = 32,
    idle_timeout: float | None = None,
    started_event: asyncio.Event | None = None,
) -> None
```

### Constants

```python
DEFAULT_PORT = 8765
MAX_BODY_SIZE = 1_048_576  # 1MB
BIND_HOST = "127.0.0.1"
```

---

## Dispatchers

### GlobalDispatcher (`global_dispatcher.py`)

Handles agent lifecycle management at the pool level.

#### Methods

| Method | Parameters | Result |
|--------|------------|--------|
| `create_agent` | `agent_id?`, `preset?`, `cwd?`, `allowed_write_paths?`, `model?`, `disable_tools?`, `parent_agent_id?`, `initial_message?`, `wait_for_initial_response?` | `{agent_id, url, initial_request_id?, response?}` |
| `destroy_agent` | `agent_id` | `{success, agent_id}` |
| `list_agents` | (none) | `{agents: [...]}` |
| `shutdown_server` | (none) | `{success, message}` |

#### Authorization

- `destroy_agent` checks authorization via `X-Nexus-Agent` header
- Self-destruction is allowed
- Parent can destroy children
- External clients (no header) treated as admin

### Dispatcher (`dispatcher.py`)

Handles per-agent operations.

#### Methods

| Method | Parameters | Result |
|--------|------------|--------|
| `send` | `content`, `request_id?`, `source?`, `source_agent_id?` | `{content, request_id, halted_at_iteration_limit}` |
| `cancel` | `request_id` | `{cancelled, request_id, reason?}` |
| `get_tokens` | (none) | Token usage breakdown |
| `get_context` | (none) | `{message_count, system_prompt, halted_at_iteration_limit, ...}` |
| `get_messages` | `offset?`, `limit?` | `{agent_id, total, offset, limit, messages}` |
| `compact` | `force?` | `{compacted, tokens_before?, tokens_after?, tokens_saved?}` |
| `shutdown` | (none) | `{success}` |

#### Features

- Turn locking (one request at a time per agent)
- Cancellation tokens for cooperative cancellation
- Source attribution for message provenance
- REPL notifications via `on_incoming_turn` hook

### Shared Infrastructure (`dispatch_core.py`)

```python
async def dispatch_request(
    request: Request,
    handlers: dict[str, Handler],
    log_context: str,
) -> Response | None
```

Handles:
- Handler lookup
- Exception handling with proper error codes
- Notification handling (no response for `id=None`)

---

## Agent Pool (`pool.py`)

### SharedComponents

Immutable configuration shared across all agents:

```python
@dataclass(frozen=True)
class SharedComponents:
    config: Config                    # Global NEXUS3 configuration
    provider_registry: ProviderRegistry  # LLM provider management
    base_log_dir: Path                # Base directory for logs
    base_context: LoadedContext       # System prompt from NEXUS.md
    context_loader: ContextLoader     # For reloading during compaction
    log_streams: LogStream            # Which logs to capture
    custom_presets: dict[str, PermissionPreset]  # From config
    mcp_registry: MCPServerRegistry   # MCP server registry
```

### AgentConfig

Per-agent creation options:

```python
@dataclass
class AgentConfig:
    agent_id: str | None = None       # Auto-generated if None
    system_prompt: str | None = None  # Override default prompt
    preset: str | None = None         # Permission preset name
    cwd: Path | None = None           # Working directory / sandbox root
    delta: PermissionDelta | None = None  # Permission modifications
    parent_permissions: AgentPermissions | None = None  # Ceiling
    parent_agent_id: str | None = None  # For lineage tracking
    model: str | None = None          # Model name/alias
```

### Agent

A single agent instance:

```python
@dataclass
class Agent:
    agent_id: str
    logger: SessionLogger
    context: ContextManager
    services: ServiceContainer
    registry: SkillRegistry
    session: Session
    dispatcher: Dispatcher
    created_at: datetime
```

### AgentPool

Manager for multiple agents:

```python
class AgentPool:
    async def create(agent_id=None, config=None) -> Agent
    async def create_temp(config=None) -> Agent
    async def destroy(agent_id, requester_id=None, admin_override=False) -> bool
    async def get_or_restore(agent_id, session_manager=None) -> Agent | None
    async def restore_from_saved(saved: SavedSession) -> Agent
    def get(agent_id) -> Agent | None
    def get_children(agent_id) -> list[str]
    def list() -> list[dict]
    @property
    def should_shutdown(self) -> bool
```

### Agent Naming

```python
# Temp agents: start with '.', don't appear in saved sessions
is_temp_agent(agent_id) -> bool  # ".1" -> True, "worker-1" -> False
generate_temp_id(existing_ids) -> str  # Returns ".1", ".2", etc.

# Validation (security)
validate_agent_id(agent_id)  # Raises ValueError on path traversal
```

### Security

- Agent ID validation prevents path traversal (`..`, `/`, `\`)
- Max agent depth: 5 (prevents infinite recursion)
- Lock-protected operations (thread-safe)
- Permission ceiling enforcement

---

## In-Process API (`agent_api.py`)

Bypasses HTTP for same-process agent communication.

### DirectAgentAPI

Global operations (create, destroy, list):

```python
class DirectAgentAPI:
    def __init__(pool, global_dispatcher, requester_id=None)
    def for_agent(agent_id) -> AgentScopedAPI
    async def create_agent(agent_id, preset=None, ...) -> dict
    async def destroy_agent(agent_id) -> dict
    async def list_agents() -> list[str]
    async def shutdown_server() -> dict
```

### AgentScopedAPI

Per-agent operations:

```python
class AgentScopedAPI:
    def __init__(pool, agent_id)
    async def send(content, request_id=None, source=None, source_agent_id=None) -> dict
    async def cancel(request_id=None) -> dict
    async def get_tokens() -> dict
    async def get_context() -> dict
    async def shutdown() -> dict
```

### ClientAdapter

Makes DirectAgentAPI look like NexusClient:

```python
class ClientAdapter:
    def __init__(global_api, agent_api=None)
    # Provides both global and agent-scoped methods
```

### Usage in Skills

```python
# In a NexusSkill
if self._services.has("agent_api"):
    api = self._services.get("agent_api")  # DirectAgentAPI
    result = await api.create_agent("sub-worker", preset="sandboxed")
    scoped = api.for_agent("sub-worker")
    response = await scoped.send("Hello!")
```

---

## Authentication (`auth.py`)

### Token Format

```
nxk_ + 32 bytes URL-safe Base64
Example: nxk_7Ks9XmN2pLqR4Tv8YbHcWdEfGhIjKlMnOpQrSt...
```

### Token Storage

```
~/.nexus3/
├── rpc.token           # Default port (8765)
└── rpc-{port}.token    # Port-specific
```

### ServerTokenManager

Server-side token lifecycle:

```python
class ServerTokenManager:
    def __init__(port=8765, nexus_dir=None, strict_permissions=True)
    @property
    def token_path(self) -> Path
    def generate_fresh(self) -> str  # Delete stale + generate new
    def save(token, overwrite=True) -> None
    def load(self) -> str | None
    def delete(self) -> None
```

### Token Discovery

Client-side token lookup:

```python
def discover_rpc_token(port=8765, nexus_dir=None, strict_permissions=True) -> str | None
```

Checks in order:
1. `NEXUS3_API_KEY` environment variable
2. `~/.nexus3/rpc-{port}.token` (port-specific)
3. `~/.nexus3/rpc.token` (default)

### Security Features

- File permissions: `0600` (owner read/write only)
- Permission checks before reading
- Constant-time comparison (prevents timing attacks)
- Fresh token on each server start

---

## Server Detection (`detection.py`)

Detect if a NEXUS3 server is running on a port.

```python
class DetectionResult(Enum):
    NO_SERVER = "no_server"       # Port is free
    NEXUS_SERVER = "nexus_server" # NEXUS3 detected
    OTHER_SERVICE = "other_service"  # Something else
    TIMEOUT = "timeout"           # Connection timed out
    ERROR = "error"               # Unexpected error

async def detect_server(port=8765, host="127.0.0.1", timeout=2.0) -> DetectionResult
async def wait_for_server(port=8765, host="127.0.0.1", timeout=30.0, poll_interval=0.1) -> bool
```

---

## Multi-Server Discovery (`discovery.py`)

Discover servers across multiple ports.

```python
class AuthStatus(Enum):
    OK = "ok"                   # Token accepted
    REQUIRED = "required"       # 401 - needs token
    INVALID_TOKEN = "invalid_token"  # 403 - bad token
    DISABLED = "disabled"       # No auth required

@dataclass
class DiscoveredServer:
    host: str
    port: int
    base_url: str
    detection: DetectionResult
    auth: AuthStatus | None
    agents: list[dict] | None
    token_path: Path | None
    token_present: bool
    error: str | None

# Parse port specifications
parse_port_spec("8765,9000-9005") -> [8765, 9000, 9001, 9002, 9003, 9004, 9005]

# Find token files
discover_token_ports(nexus_dir=None) -> dict[int, Path]

# Probe single server
async def probe_server(port, host="127.0.0.1", timeout=0.5, token_path=None) -> DiscoveredServer

# Discover all servers
async def discover_servers(ports, host="127.0.0.1", timeout=0.5, max_concurrency=50) -> list[DiscoveredServer]
```

---

## Log Multiplexer (`log_multiplexer.py`)

Routes raw API logs to the correct agent using contextvars.

### Problem

Multiple agents share a single provider, but each has its own logger. Without multiplexing, logs go to the wrong agent.

### Solution

```python
class LogMultiplexer:
    def register(agent_id, callback)
    def unregister(agent_id)

    @contextmanager
    def agent_context(agent_id):
        """Set current agent for log routing."""
        ...

    # RawLogCallback protocol
    def on_request(endpoint, payload)
    def on_response(status, body)
    def on_chunk(chunk)
```

### Usage

```python
# In AgentPool initialization
multiplexer = LogMultiplexer()
provider_registry.set_raw_log_callback(multiplexer)

# In dispatcher (when handling request)
with multiplexer.agent_context(agent_id):
    async for chunk in session.send(content):
        ...  # Logs routed to correct agent
```

---

## Bootstrap (`bootstrap.py`)

Server component wiring and initialization.

### configure_server_logging

Full logging setup (replaces existing handlers):

```python
def configure_server_logging(log_dir, level=INFO, console_level=WARNING) -> Path
```

### configure_server_file_logging

Non-destructive file logging (for REPL mode):

```python
def configure_server_file_logging(log_dir, level=INFO) -> Path
```

### bootstrap_server_components

Main entry point for server initialization:

```python
async def bootstrap_server_components(
    config: Config,
    base_log_dir: Path,
    log_streams: LogStream,
    is_repl: bool = False,
) -> tuple[AgentPool, GlobalDispatcher, SharedComponents]
```

Handles circular dependency between AgentPool and GlobalDispatcher:

1. Create provider registry
2. Load context from NEXUS.md files
3. Load custom permission presets
4. Create SharedComponents
5. Create AgentPool (without dispatcher)
6. Create GlobalDispatcher (requires pool)
7. Wire circular dependency
8. Validate wiring

---

## Permissions

### RPC Default Behavior

- Default preset: `sandboxed` (NOT `trusted`)
- Sandboxed agents can only read within their `cwd`
- Write tools are disabled by default
- `yolo` preset is NOT available via RPC

### Enabling Writes

```bash
# CLI
nexus3 rpc create writer --cwd /tmp/project --write-path /tmp/project/output

# JSON-RPC
{
    "method": "create_agent",
    "params": {
        "agent_id": "writer",
        "cwd": "/tmp/project",
        "allowed_write_paths": ["/tmp/project/output"]
    }
}
```

### Presets via RPC

| Preset | Capabilities |
|--------|--------------|
| `sandboxed` | Read-only in cwd, no network, no agent management |
| `worker` | Minimal: sandboxed minus write_file |
| `trusted` | Full read/write, agent management allowed |

### Ceiling Enforcement

- Subagents cannot exceed parent permissions
- Trusted agents can only create sandboxed subagents
- Sandboxed agents cannot create agents at all
- Max nesting depth: 5

---

## Usage Examples

### CLI

```bash
# Start server (requires NEXUS_DEV=1 for headless mode)
NEXUS_DEV=1 nexus3 --serve

# Or use REPL with embedded server
nexus3

# RPC commands
nexus3 rpc list
nexus3 rpc create worker-1 --preset trusted
nexus3 rpc send worker-1 "Hello!"
nexus3 rpc status worker-1
nexus3 rpc destroy worker-1
nexus3 rpc shutdown
```

### curl

```bash
token=$(cat ~/.nexus3/rpc.token)

# Create agent
curl -X POST http://localhost:8765/rpc \
  -H "Authorization: Bearer $token" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"create_agent","params":{"agent_id":"worker"},"id":1}'

# Send message
curl -X POST http://localhost:8765/agent/worker \
  -H "Authorization: Bearer $token" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"send","params":{"content":"Hello"},"id":1}'

# List agents
curl -X POST http://localhost:8765/rpc \
  -H "Authorization: Bearer $token" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"list_agents","id":1}'
```

### Python Client

```python
import httpx
from nexus3.rpc import (
    discover_rpc_token,
    detect_server,
    DetectionResult,
    Request,
    serialize_request,
    parse_response,
)

async def example():
    # Check if server is running
    result = await detect_server(8765)
    if result != DetectionResult.NEXUS_SERVER:
        print("Server not running")
        return

    # Discover token
    token = discover_rpc_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    async with httpx.AsyncClient() as client:
        # Create agent
        req = Request(
            jsonrpc="2.0",
            method="create_agent",
            params={"agent_id": "worker", "preset": "trusted"},
            id=1,
        )
        resp = await client.post(
            "http://localhost:8765/rpc",
            content=serialize_request(req),
            headers=headers,
        )
        result = parse_response(resp.text)
        print(f"Created: {result.result}")
```

### Server Bootstrap

```python
from pathlib import Path
from nexus3.config import load_config
from nexus3.rpc.bootstrap import bootstrap_server_components, configure_server_logging
from nexus3.rpc.http import run_http_server
from nexus3.rpc.auth import ServerTokenManager
from nexus3.session import LogStream

async def start_server():
    config = load_config()
    log_dir = Path(".nexus3/logs")

    # Configure logging
    configure_server_logging(log_dir)

    # Bootstrap components
    pool, global_dispatcher, shared = await bootstrap_server_components(
        config=config,
        base_log_dir=log_dir,
        log_streams=LogStream.CONTEXT | LogStream.VERBOSE,
    )

    # Generate token
    token_manager = ServerTokenManager(port=8765)
    api_key = token_manager.generate_fresh()
    print(f"Token: {api_key}")

    # Run server
    await run_http_server(
        pool=pool,
        global_dispatcher=global_dispatcher,
        api_key=api_key,
        idle_timeout=1800,  # 30 min
    )
```

---

## Public Exports

```python
from nexus3.rpc import (
    # Types
    Request,
    Response,
    HttpRequest,

    # Protocol functions (server-side)
    parse_request,
    serialize_response,
    make_error_response,
    make_success_response,

    # Protocol functions (client-side)
    serialize_request,
    parse_response,

    # HTTP server
    run_http_server,
    handle_connection,
    read_http_request,
    send_http_response,
    DEFAULT_PORT,
    MAX_BODY_SIZE,
    BIND_HOST,

    # Dispatchers
    Dispatcher,
    # GlobalDispatcher via: from nexus3.rpc.global_dispatcher import GlobalDispatcher

    # Error codes
    PARSE_ERROR,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    INVALID_PARAMS,
    INTERNAL_ERROR,
    SERVER_ERROR,

    # Exceptions
    ParseError,
    InvalidParamsError,
    HttpParseError,

    # Agent Pool
    Agent,
    AgentConfig,
    AgentPool,
    SharedComponents,

    # In-Process API
    DirectAgentAPI,
    AgentScopedAPI,
    ClientAdapter,

    # Log Multiplexer
    LogMultiplexer,

    # Server Logging
    configure_server_logging,

    # Authentication
    API_KEY_PREFIX,
    generate_api_key,
    validate_api_key,
    ServerTokenManager,
    discover_rpc_token,

    # Detection
    DetectionResult,
    detect_server,
    wait_for_server,
)

# Additional imports from submodules
from nexus3.rpc.global_dispatcher import GlobalDispatcher
from nexus3.rpc.bootstrap import bootstrap_server_components, configure_server_file_logging
from nexus3.rpc.discovery import (
    AuthStatus,
    DiscoveredServer,
    parse_port_spec,
    discover_token_ports,
    probe_server,
    discover_servers,
)
from nexus3.rpc.pool import AuthorizationError, validate_agent_id, is_temp_agent, generate_temp_id
```

---

## Dependencies

### Internal

- `nexus3.core`: Types, errors, paths, validation, permissions
- `nexus3.config`: Configuration schema
- `nexus3.provider`: LLM provider registry
- `nexus3.context`: Context management, loading
- `nexus3.session`: Session coordination, logging
- `nexus3.skill`: Skill registry, service container
- `nexus3.mcp`: MCP server registry

### External

- `httpx`: HTTP client for detection/discovery
- Python stdlib: `asyncio`, `json`, `secrets`, `hmac`, `logging`

---

Updated: 2026-01-21 from comprehensive source analysis.
