# NEXUS3 RPC Module

JSON-RPC 2.0 protocol implementation for NEXUS3 headless mode. Enables programmatic control of NEXUS3 via HTTP for automation, testing, and integration with external tools.

## Purpose

This module provides the protocol layer for `nexus3 --serve` mode. Instead of interactive REPL input/output, it runs an HTTP server that accepts JSON-RPC 2.0 requests and returns responses. This enables:

- Automated testing without human interaction
- Integration with external AI orchestrators (e.g., Claude Code)
- Multi-agent scenarios with dynamic agent creation/destruction
- Subagent communication (parent/child agents)
- Scripted automation pipelines
- Multi-turn conversations with persistent context per agent
- Permission-controlled agent hierarchies with ceiling inheritance

## Architecture

```
                                    +-----------------+
                                    |  GlobalDispatcher |
                                    |  (create/destroy |
                                    |   list/shutdown) |
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
                  |                  |   .get(id)      |
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
|             | <---------------------------------- | destroy_agent    |
|             |                                     | list_agents      |
+-------------+                                     | shutdown_server  |
      |                                             +-----------------+
      |         POST /agent/{id}                    +-----------------+
      | ------------------------------------------> |     Agent       |
      | <------------------------------------------ |   Dispatcher    |
      |                                             |  send/cancel/   |
      |                                             |  get_tokens/... |
                                                    +-----------------+
```

## Module Files

| File | Purpose |
|------|---------|
| `types.py` | JSON-RPC 2.0 Request and Response dataclasses |
| `protocol.py` | Parsing, serialization, error codes |
| `auth.py` | API key generation, validation, and storage |
| `detection.py` | Server detection and wait utilities |
| `dispatcher.py` | Per-agent method dispatcher (send/cancel/shutdown) |
| `global_dispatcher.py` | Global method dispatcher (create/destroy/list agents) |
| `pool.py` | AgentPool, Agent, SharedComponents, AgentConfig |
| `http.py` | HTTP server with path-based routing |
| `__init__.py` | Public exports |

---

## Key Types

### `Request` (types.py)

JSON-RPC 2.0 request object.

| Field | Type | Description |
|-------|------|-------------|
| `jsonrpc` | `str` | Protocol version, must be `"2.0"` |
| `method` | `str` | Method name to invoke |
| `params` | `dict | None` | Named parameters (positional arrays not supported) |
| `id` | `str | int | None` | Request ID. `None` = notification (no response) |

### `Response` (types.py)

JSON-RPC 2.0 response object.

| Field | Type | Description |
|-------|------|-------------|
| `jsonrpc` | `str` | Always `"2.0"` |
| `id` | `str | int | None` | Echoed from request |
| `result` | `Any | None` | Success result (mutually exclusive with `error`) |
| `error` | `dict | None` | Error object (mutually exclusive with `result`) |

### `HttpRequest` (http.py)

Parsed HTTP request.

| Field | Type | Description |
|-------|------|-------------|
| `method` | `str` | HTTP method (e.g., `"POST"`) |
| `path` | `str` | Request path (e.g., `"/"`, `"/agent/worker-1"`) |
| `headers` | `dict[str, str]` | HTTP headers (keys are lowercase) |
| `body` | `str` | Request body (decoded UTF-8) |

---

## Authentication (auth.py)

API key authentication for securing the HTTP server.

### Key Format

Keys use the format: `nxk_` + 32 bytes URL-safe Base64 (approximately 47 characters total).

Example: `nxk_7Ks9XmN2pLqR4Tv8YbHcWdFgJkLmNpQrStUvWxYz`

### Key Storage

Keys are stored in `~/.nexus3/`:

| File | Description |
|------|-------------|
| `server.key` | Default key (port 8765) |
| `server-{port}.key` | Port-specific key |

### Functions

| Function | Description |
|----------|-------------|
| `generate_api_key()` | Generate a new API key with `nxk_` prefix |
| `validate_api_key(provided, expected)` | Constant-time comparison (timing-attack safe) |
| `discover_api_key(port)` | Find API key from env var or key files |

### ServerKeyManager

Manages server API key lifecycle:

```python
class ServerKeyManager:
    def __init__(self, port: int = 8765, nexus_dir: Path | None = None): ...

    @property
    def key_path(self) -> Path: ...

    def generate_and_save(self) -> str: ...  # Creates key with 0o600 permissions
    def load(self) -> str | None: ...
    def delete(self) -> None: ...
```

### Key Discovery Order

The `discover_api_key()` function checks:
1. `NEXUS3_API_KEY` environment variable
2. `~/.nexus3/server-{port}.key` (port-specific)
3. `~/.nexus3/server.key` (default)

---

## Server Detection (detection.py)

Utilities for detecting running NEXUS3 servers.

### DetectionResult Enum

| Value | Description |
|-------|-------------|
| `NO_SERVER` | Port is free (connection refused) |
| `NEXUS_SERVER` | Valid NEXUS3 server detected |
| `OTHER_SERVICE` | Something else is running (not NEXUS3) |
| `TIMEOUT` | Connection attempt timed out |
| `ERROR` | Unexpected error occurred |

### Functions

```python
async def detect_server(
    port: int,
    host: str = "127.0.0.1",
    timeout: float = 2.0,
) -> DetectionResult: ...

async def wait_for_server(
    port: int,
    host: str = "127.0.0.1",
    timeout: float = 30.0,
    poll_interval: float = 0.1,
) -> bool: ...
```

### Detection Strategy

Sends a `list_agents` JSON-RPC request to fingerprint the server:
- Valid JSON-RPC response with `agents` list -> `NEXUS_SERVER`
- HTTP 401/403 (auth error) -> `NEXUS_SERVER` (auth-protected)
- Connection refused -> `NO_SERVER`
- Invalid/non-JSON-RPC response -> `OTHER_SERVICE`

---

## Agent Pool (pool.py)

The `AgentPool` manages multiple agent instances, each with isolated context, skills, and logging.

### SharedComponents

Immutable resources shared across all agents in a pool:

```python
@dataclass(frozen=True)
class SharedComponents:
    config: Config              # Global NEXUS3 configuration
    provider: AsyncProvider     # LLM provider (shared for connection pooling)
    prompt_loader: PromptLoader # Loader for system prompts
    base_log_dir: Path          # Base directory for agent logs
    log_streams: LogStream = LogStream.ALL  # Enabled log streams
    custom_presets: dict[str, PermissionPreset] = field(default_factory=dict)
```

### AgentConfig

Per-agent creation options:

```python
@dataclass
class AgentConfig:
    agent_id: str | None = None           # Unique ID (auto-generated if None)
    system_prompt: str | None = None      # Override default system prompt
    preset: str | None = None             # Permission preset name
    delta: PermissionDelta | None = None  # Permission modifications
    parent_permissions: AgentPermissions | None = None  # Parent's permissions (ceiling)
    parent_agent_id: str | None = None    # Parent agent ID for lineage tracking
```

### Agent

A single agent instance with all its components:

```python
@dataclass
class Agent:
    agent_id: str              # Unique identifier
    logger: SessionLogger      # Session logger for this agent
    context: ContextManager    # Agent's conversation history
    services: ServiceContainer # Service container for DI
    registry: SkillRegistry    # Skill registry with tools
    session: Session           # Session coordinator for LLM
    dispatcher: Dispatcher     # JSON-RPC dispatcher
    created_at: datetime       # Creation timestamp
```

### AgentPool

Manager for creating, destroying, and accessing agents:

```python
class AgentPool:
    def __init__(self, shared: SharedComponents) -> None: ...

    async def create(
        self,
        agent_id: str | None = None,
        config: AgentConfig | None = None,
    ) -> Agent: ...

    async def create_temp(self, config: AgentConfig | None = None) -> Agent: ...

    async def restore_from_saved(self, saved: SavedSession) -> Agent: ...

    async def destroy(self, agent_id: str) -> bool: ...

    def get(self, agent_id: str) -> Agent | None: ...

    def list(self) -> list[dict[str, Any]]: ...

    def is_temp(self, agent_id: str) -> bool: ...

    @property
    def should_shutdown(self) -> bool: ...

    def __len__(self) -> int: ...

    def __contains__(self, agent_id: str) -> bool: ...
```

### Temp Agent Naming

Agents with IDs starting with `.` (e.g., `.1`, `.2`) are temporary:
- Don't appear in saved sessions list
- Can be promoted to named via `/save` command
- Useful for one-off tasks

Helper functions:
```python
def is_temp_agent(agent_id: str) -> bool: ...
def generate_temp_id(existing_ids: set[str]) -> str: ...  # Returns ".1", ".2", etc.
```

### Agent List Info

The `list()` method returns:

```python
[
    {
        "agent_id": "worker-1",
        "is_temp": False,
        "created_at": "2024-01-15T10:30:00",
        "message_count": 5,
        "should_shutdown": False
    },
    ...
]
```

### Permission Enforcement

When creating agents, the pool:
1. Resolves the permission preset (from config or built-in)
2. Checks parent ceiling (if `parent_permissions` provided)
3. Applies delta modifications
4. Validates result against ceiling
5. Sets depth counter (max depth: 5)

```python
MAX_AGENT_DEPTH = 5  # Maximum nesting depth for agent creation
```

---

## Global Dispatcher (global_dispatcher.py)

Handles agent lifecycle management (non-agent-specific methods).

### Constructor

```python
GlobalDispatcher(pool: AgentPool)
```

### Properties

```python
@property
def shutdown_requested(self) -> bool: ...  # True if shutdown_server was called
```

### Methods

```python
def handles(self, method: str) -> bool: ...
async def dispatch(self, request: Request) -> Response | None: ...
```

### Available RPC Methods

| Method | Params | Returns | Description |
|--------|--------|---------|-------------|
| `create_agent` | `{"agent_id?", "system_prompt?", "preset?", "disable_tools?", "parent_agent_id?"}` | `{"agent_id", "url"}` | Create a new agent |
| `destroy_agent` | `{"agent_id"}` | `{"success", "agent_id"}` | Destroy an existing agent |
| `list_agents` | (none) | `{"agents": [...]}` | List all active agents |
| `shutdown_server` | (none) | `{"success", "message"}` | Signal server shutdown |

#### `create_agent` Details

Parameters:
- `agent_id`: Optional string. Auto-generated 8-char hex ID if omitted. Validated for path safety.
- `system_prompt`: Optional string. Override the default system prompt.
- `preset`: Optional string. One of `"yolo"`, `"trusted"`, `"sandboxed"`, `"worker"`.
- `disable_tools`: Optional list of strings. Tools to disable for this agent.
- `parent_agent_id`: Optional string. ID of parent agent for permission ceiling enforcement.

Returns `agent_id` and `url` for subsequent agent-specific calls.

Security:
- Validates `agent_id` format to prevent path traversal
- Looks up parent permissions from pool (not from RPC data) for ceiling enforcement
- Enforces permission ceiling inheritance

#### `destroy_agent` Details

- `agent_id`: Required. The ID of the agent to destroy.
- Cancels all in-progress requests before cleanup
- Cleans up resources (closes logger, removes from pool)
- Returns `success: true` if found and destroyed, `false` if not found

#### `list_agents` Details

Returns list of all active agents with:
- `agent_id`: Agent's unique identifier
- `is_temp`: True if temp agent (starts with `.`)
- `created_at`: ISO 8601 timestamp
- `message_count`: Number of messages in context
- `should_shutdown`: Whether agent wants shutdown

#### `shutdown_server` Details

- Sets `shutdown_requested` flag
- HTTP server checks this flag in its main loop
- Initiates graceful shutdown

---

## Dispatcher (dispatcher.py)

Routes JSON-RPC requests to handler methods for a specific agent. Manages session state and handles errors.

### Type Alias

```python
Handler = Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]
```

### Constructor

```python
Dispatcher(session: Session, context: ContextManager | None = None)
```

- `session`: Required. The Session instance for LLM interactions.
- `context`: Optional. Enables `get_tokens` and `get_context` methods if provided.

### Properties

```python
@property
def should_shutdown(self) -> bool: ...

def request_shutdown(self) -> None: ...
```

### Methods

```python
async def dispatch(request: Request) -> Response | None: ...
async def cancel_all_requests(self) -> dict[str, bool]: ...  # Cancel all in-progress requests
```

### Available RPC Methods

| Method | Params | Returns | Description |
|--------|--------|---------|-------------|
| `send` | `{"content", "request_id?"}` | `{"content", "request_id"}` | Send message to LLM |
| `cancel` | `{"request_id"}` | `{"cancelled", ...}` | Cancel in-progress request |
| `shutdown` | (none) | `{"success": true}` | Signal graceful shutdown |
| `get_tokens` | (none) | Token usage dict | Get context token breakdown |
| `get_context` | (none) | `{"message_count", ...}` | Get context info |

**Note:** `get_tokens` and `get_context` are only available if `context` was provided to the constructor.

#### `send` Parameter Validation

- `content` is required and must be a string
- `request_id` is optional; if not provided, a unique ID is auto-generated
- Response includes `request_id` for use with `cancel`
- If cancelled, returns `{"cancelled": true, "request_id": "..."}`

#### `cancel` Parameter Validation

- `request_id` is required and must be a string
- Returns `{"cancelled": true, ...}` if request was found and cancelled
- Returns `{"cancelled": false, "reason": "not_found_or_completed", ...}` if not found

### Error Handling

The dispatcher catches exceptions and converts them to appropriate error responses:

- `InvalidParamsError` -> `INVALID_PARAMS` (-32602)
- `NexusError` -> `INTERNAL_ERROR` (-32603) with message
- Other exceptions -> `INTERNAL_ERROR` (-32603) with type and message

Notifications (requests without `id`) never receive error responses.

### InvalidParamsError

```python
class InvalidParamsError(NexusError):
    """Raised when method parameters are invalid."""
```

---

## HTTP Server (http.py)

Pure asyncio HTTP server implementation with path-based routing (~490 LOC, no external dependencies except httpx for client operations).

### Key Exports

| Export | Type | Description |
|--------|------|-------------|
| `run_http_server` | `async function` | Main server entry point |
| `DEFAULT_PORT` | `int` | Default port: `8765` |
| `BIND_HOST` | `str` | Bind address: `"127.0.0.1"` (localhost only) |
| `handle_connection` | `async function` | Handles single client connection |
| `read_http_request` | `async function` | Parses HTTP request from stream |
| `send_http_response` | `async function` | Writes HTTP response to stream |
| `HttpRequest` | `dataclass` | Parsed HTTP request |
| `HttpParseError` | `Exception` | HTTP parsing error |
| `MAX_BODY_SIZE` | `int` | Maximum request body size (1MB) |

### Path-Based Routing

| Path | Method | Handler | Description |
|------|--------|---------|-------------|
| `POST /` | GlobalDispatcher | Agent management methods |
| `POST /rpc` | GlobalDispatcher | Alias for `/` |
| `POST /agent/{agent_id}` | Agent's Dispatcher | Agent-specific methods |

Other methods or paths return 404/405 errors.

### Cross-Session Auto-Restore

When a request targets an `agent_id` that is not in the active pool but exists as a saved session (via `SessionManager`), the server automatically restores the session before processing the request.

### Function Signatures

```python
async def run_http_server(
    pool: AgentPool,
    global_dispatcher: GlobalDispatcher,
    port: int = DEFAULT_PORT,
    host: str = BIND_HOST,
    api_key: str | None = None,
    session_manager: SessionManager | None = None,
) -> None: ...

async def handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    pool: AgentPool,
    global_dispatcher: GlobalDispatcher,
    api_key: str | None = None,
    session_manager: SessionManager | None = None,
) -> None: ...

async def read_http_request(reader: asyncio.StreamReader) -> HttpRequest: ...

async def send_http_response(
    writer: asyncio.StreamWriter,
    status: int,
    body: str,
    content_type: str = "application/json",
) -> None: ...
```

### Security

- **Localhost only**: Server binds to `127.0.0.1`, `localhost`, or `::1` only. Attempting to bind to any other address raises `ValueError`.
- **API key authentication**: When `api_key` is provided, all requests must include `Authorization: Bearer <key>` header.
- **Request size limit**: Body limited to 1MB (`MAX_BODY_SIZE`) to prevent DoS.
- **Timeouts**: 30-second timeout on request reading (request line, headers, and body).
- **Agent ID validation**: Agent IDs in paths are validated to prevent path traversal.

### HTTP Response Codes

| Code | Meaning |
|------|---------|
| 200 | OK |
| 400 | Bad Request (malformed HTTP or JSON-RPC) |
| 401 | Unauthorized (missing Authorization header) |
| 403 | Forbidden (invalid API key) |
| 404 | Not Found (unknown path or agent) |
| 405 | Method Not Allowed (not POST) |
| 500 | Internal Server Error |

---

## Protocol Functions (protocol.py)

### Server-Side Functions

| Function | Description |
|----------|-------------|
| `parse_request(line)` | Parse JSON line into `Request`. Raises `ParseError` on failure. |
| `serialize_response(response)` | Serialize `Response` to compact JSON line (no trailing newline). |
| `make_success_response(id, result)` | Create success response with result. |
| `make_error_response(id, code, message, data=None)` | Create error response. |

### Client-Side Functions

| Function | Description |
|----------|-------------|
| `serialize_request(request)` | Serialize `Request` to compact JSON string for sending to the server. |
| `parse_response(line)` | Parse JSON line into `Response`. Raises `ParseError` on failure. |

### Request Validation (`parse_request`)

The parser validates:
1. Valid JSON (raises `ParseError` on `JSONDecodeError`)
2. Must be a JSON object (not array or primitive)
3. `jsonrpc` must be exactly `"2.0"`
4. `method` must be a string
5. `params` must be object or array (if present); positional arrays are rejected
6. `id` must be string, number, or null (if present)

### Error Codes

Standard JSON-RPC 2.0 error codes:

| Code | Constant | Meaning |
|------|----------|---------|
| -32700 | `PARSE_ERROR` | Invalid JSON |
| -32600 | `INVALID_REQUEST` | Not a valid request object |
| -32601 | `METHOD_NOT_FOUND` | Method does not exist |
| -32602 | `INVALID_PARAMS` | Invalid method parameters |
| -32603 | `INTERNAL_ERROR` | Internal server error |
| -32000 | `SERVER_ERROR` | Server error (application-specific) |

---

## Data Flow

### Single-Agent Request

```
1. HTTP POST request to localhost:8765/agent/{id}
        |
        v
2. read_http_request() parses HTTP headers and body
        |
        v
3. API key validation (if configured)
        |
        v
4. Path router extracts agent_id, looks up Agent in pool
        |
        v
5. (Optional) Auto-restore from saved session if not in pool
        |
        v
6. parse_request() validates JSON and creates Request
        |
        v
7. Agent.dispatcher.dispatch() looks up handler
        |
        v
8. Handler executes (e.g., _handle_send calls Session.send)
        |
        v
9. Result wrapped in Response via make_success_response()
        |
        v
10. serialize_response() creates JSON body
        |
        v
11. send_http_response() writes HTTP response
```

### Multi-Agent Lifecycle

```
1. POST / with create_agent (+ preset, disable_tools)
        |
        v
2. GlobalDispatcher validates params and permissions
        |
        v
3. AgentPool creates Agent with permission enforcement
        |
        v
4. Returns agent_id and URL (/agent/{id})
        |
        v
5. Client uses URL for subsequent requests
        |
        v
6. POST /agent/{id} with send/cancel/etc.
        |
        v
7. Agent's Dispatcher handles request
        |
        v
8. POST / with destroy_agent to clean up
        |
        v
9. All in-progress requests cancelled, resources cleaned up
```

---

## Dependencies

### Internal (from other NEXUS3 modules)

| Import | Module | Purpose |
|--------|--------|---------|
| `NexusError` | `nexus3.core.errors` | Base exception class |
| `CancellationToken` | `nexus3.core.cancel` | Request cancellation |
| `is_valid_agent_id`, `validate_agent_id`, `ValidationError` | `nexus3.core.validation` | Agent ID validation |
| `AgentPermissions`, `PermissionDelta`, `PermissionPreset` | `nexus3.core.permissions` | Permission types |
| `resolve_preset`, `load_custom_presets_from_config` | `nexus3.core.permissions` | Preset resolution |
| `Session` | `nexus3.session` | LLM session for `send` method |
| `SessionLogger`, `LogConfig`, `LogStream` | `nexus3.session` | Per-agent logging |
| `SavedSession`, `deserialize_messages` | `nexus3.session.persistence` | Session restoration |
| `ContextManager`, `ContextConfig` | `nexus3.context` | Per-agent context |
| `ServiceContainer`, `SkillRegistry` | `nexus3.skill` | Per-agent skills |
| `PromptLoader` | `nexus3.context.prompt_loader` | System prompt loading |
| `Config` | `nexus3.config.schema` | Global configuration |
| `AsyncProvider` | `nexus3.core.interfaces` | LLM provider protocol |

### External

| Module | Purpose |
|--------|---------|
| `asyncio` | Async server and I/O |
| `json` | JSON parsing/serialization |
| `dataclasses` | Type definitions |
| `typing` | Type hints |
| `collections.abc` | Handler type alias |
| `secrets` | Request ID and API key generation |
| `datetime` | Agent creation timestamps |
| `pathlib` | Log directory and key file paths |
| `uuid` | Agent ID generation |
| `hmac` | Constant-time key comparison |
| `os`, `stat` | Key file permissions |
| `httpx` | HTTP client for server detection |

---

## Usage Examples

### Create an Agent

```bash
curl -X POST http://localhost:8765/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer nxk_..." \
  -d '{"jsonrpc":"2.0","method":"create_agent","params":{"agent_id":"worker-1"},"id":1}'
```

Response:
```json
{"jsonrpc":"2.0","id":1,"result":{"agent_id":"worker-1","url":"/agent/worker-1"}}
```

### Create Agent with Permission Preset

```bash
curl -X POST http://localhost:8765/ \
  -H "Authorization: Bearer nxk_..." \
  -d '{"jsonrpc":"2.0","method":"create_agent","params":{"agent_id":"sandbox","preset":"sandboxed"},"id":1}'
```

### Create Agent with Disabled Tools

```bash
curl -X POST http://localhost:8765/ \
  -H "Authorization: Bearer nxk_..." \
  -d '{"jsonrpc":"2.0","method":"create_agent","params":{"agent_id":"readonly","preset":"trusted","disable_tools":["write_file"]},"id":1}'
```

### Create Subagent with Parent Ceiling

```bash
# Parent agent "coordinator" creates a child with restricted permissions
curl -X POST http://localhost:8765/ \
  -H "Authorization: Bearer nxk_..." \
  -d '{"jsonrpc":"2.0","method":"create_agent","params":{"agent_id":"worker","preset":"sandboxed","parent_agent_id":"coordinator"},"id":1}'
```

### Send Message to Agent

```bash
curl -X POST http://localhost:8765/agent/worker-1 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer nxk_..." \
  -d '{"jsonrpc":"2.0","method":"send","params":{"content":"Hello"},"id":2}'
```

Response:
```json
{"jsonrpc":"2.0","id":2,"result":{"content":"Hello! How can I help you?","request_id":"a1b2c3d4"}}
```

### List All Agents

```bash
curl -X POST http://localhost:8765/ \
  -H "Authorization: Bearer nxk_..." \
  -d '{"jsonrpc":"2.0","method":"list_agents","id":3}'
```

Response:
```json
{"jsonrpc":"2.0","id":3,"result":{"agents":[{"agent_id":"worker-1","is_temp":false,"created_at":"2024-01-15T10:30:00","message_count":2,"should_shutdown":false}]}}
```

### Destroy an Agent

```bash
curl -X POST http://localhost:8765/ \
  -H "Authorization: Bearer nxk_..." \
  -d '{"jsonrpc":"2.0","method":"destroy_agent","params":{"agent_id":"worker-1"},"id":4}'
```

Response:
```json
{"jsonrpc":"2.0","id":4,"result":{"success":true,"agent_id":"worker-1"}}
```

### Shutdown the Server

```bash
curl -X POST http://localhost:8765/ \
  -H "Authorization: Bearer nxk_..." \
  -d '{"jsonrpc":"2.0","method":"shutdown_server","id":5}'
```

Response:
```json
{"jsonrpc":"2.0","id":5,"result":{"success":true,"message":"Server shutting down"}}
```

### Multi-Turn Conversation

```bash
# Create agent
curl -X POST http://localhost:8765/ \
  -H "Authorization: Bearer nxk_..." \
  -d '{"jsonrpc":"2.0","method":"create_agent","params":{"agent_id":"chat"},"id":1}'

# First message
curl -X POST http://localhost:8765/agent/chat \
  -H "Authorization: Bearer nxk_..." \
  -d '{"jsonrpc":"2.0","method":"send","params":{"content":"My name is Alice"},"id":2}'
# Response: {"jsonrpc":"2.0","id":2,"result":{"content":"Nice to meet you, Alice!","request_id":"..."}}

# Second message (agent remembers context)
curl -X POST http://localhost:8765/agent/chat \
  -H "Authorization: Bearer nxk_..." \
  -d '{"jsonrpc":"2.0","method":"send","params":{"content":"What is my name?"},"id":3}'
# Response: {"jsonrpc":"2.0","id":3,"result":{"content":"Your name is Alice.","request_id":"..."}}

# Clean up
curl -X POST http://localhost:8765/ \
  -H "Authorization: Bearer nxk_..." \
  -d '{"jsonrpc":"2.0","method":"destroy_agent","params":{"agent_id":"chat"},"id":4}'
```

### Cancel a Request

**Terminal 1 - Start a long-running request:**
```bash
curl -X POST http://localhost:8765/agent/worker-1 \
  -H "Authorization: Bearer nxk_..." \
  -d '{"jsonrpc":"2.0","method":"send","params":{"content":"Write a long essay","request_id":"req-1"},"id":1}'
```

**Terminal 2 - Cancel the request:**
```bash
curl -X POST http://localhost:8765/agent/worker-1 \
  -H "Authorization: Bearer nxk_..." \
  -d '{"jsonrpc":"2.0","method":"cancel","params":{"request_id":"req-1"},"id":2}'
```

Response:
```json
{"jsonrpc":"2.0","id":2,"result":{"cancelled":true,"request_id":"req-1"}}
```

### Get Token Usage

```bash
curl -X POST http://localhost:8765/agent/worker-1 \
  -H "Authorization: Bearer nxk_..." \
  -d '{"jsonrpc":"2.0","method":"get_tokens","id":5}'
```

Response:
```json
{"jsonrpc":"2.0","id":5,"result":{"system":150,"tools":0,"messages":42,"total":192,"budget":8000,"available":6000}}
```

### Error Responses

**Missing authorization:**
```bash
curl -X POST http://localhost:8765/ \
  -d '{"jsonrpc":"2.0","method":"list_agents","id":1}'
```

Response (HTTP 401):
```json
{"error": "Authorization header required"}
```

**Invalid API key:**
```bash
curl -X POST http://localhost:8765/ \
  -H "Authorization: Bearer wrong_key" \
  -d '{"jsonrpc":"2.0","method":"list_agents","id":1}'
```

Response (HTTP 403):
```json
{"error": "Invalid API key"}
```

**Agent not found:**
```bash
curl -X POST http://localhost:8765/agent/nonexistent \
  -H "Authorization: Bearer nxk_..." \
  -d '{"jsonrpc":"2.0","method":"send","params":{"content":"Hi"},"id":1}'
```

Response (HTTP 404):
```json
{"error": "Agent not found: nonexistent"}
```

**Method not found:**
```bash
curl -X POST http://localhost:8765/agent/worker-1 \
  -H "Authorization: Bearer nxk_..." \
  -d '{"jsonrpc":"2.0","method":"unknown","id":1}'
```

Response:
```json
{"jsonrpc":"2.0","id":1,"error":{"code":-32601,"message":"Method not found: unknown"}}
```

**Permission ceiling exceeded:**
```bash
curl -X POST http://localhost:8765/ \
  -H "Authorization: Bearer nxk_..." \
  -d '{"jsonrpc":"2.0","method":"create_agent","params":{"agent_id":"worker","preset":"yolo","parent_agent_id":"sandboxed-parent"},"id":1}'
```

Response:
```json
{"jsonrpc":"2.0","id":1,"error":{"code":-32603,"message":"Internal error: PermissionError: Requested preset 'yolo' exceeds parent ceiling"}}
```

---

## Command Line Usage

```bash
# Start HTTP server on default port (8765)
nexus --serve

# Start HTTP server on custom port
nexus --serve 9000
```

---

## Python Client (`nexus3.client`)

For Python applications, the `NexusClient` class provides a convenient async interface to communicate with a running NEXUS3 server. Located in `nexus3/client.py` (separate from the `rpc` module).

### Basic Usage

```python
from nexus3.client import NexusClient

async with NexusClient(api_key="nxk_...") as client:
    result = await client.send("Hello!")
    print(result["content"])
```

### Constructor

```python
NexusClient(url: str = "http://127.0.0.1:8765", timeout: float = 60.0, api_key: str | None = None)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | `str` | `"http://127.0.0.1:8765"` | Base URL of the JSON-RPC server |
| `timeout` | `float` | `60.0` | Request timeout in seconds |
| `api_key` | `str \| None` | `None` | API key for authentication |

### Methods

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `send(content)` | `content: str`, `request_id: str \| None` | `dict[str, Any]` | Send message, get response |
| `cancel(request_id)` | `request_id: str` | `dict[str, Any]` | Cancel an in-progress request |
| `get_tokens()` | (none) | `dict[str, Any]` | Get token usage breakdown |
| `get_context()` | (none) | `dict[str, Any]` | Get context state |
| `shutdown()` | (none) | `dict[str, Any]` | Request server shutdown |

### Error Handling

All methods raise `ClientError` (a `NexusError` subclass) on:
- Connection failures
- Request timeouts
- RPC errors (method not found, invalid params, etc.)

```python
from nexus3.client import NexusClient, ClientError

async with NexusClient(api_key="nxk_...") as client:
    try:
        result = await client.send("Hello")
    except ClientError as e:
        print(f"Error: {e}")
```

---

## Module Exports

From `__init__.py`:

```python
# Types
Request, Response, HttpRequest

# Protocol functions (server-side)
parse_request, serialize_response, make_error_response, make_success_response

# Protocol functions (client-side)
serialize_request, parse_response

# HTTP server
run_http_server, handle_connection, read_http_request, send_http_response
DEFAULT_PORT, MAX_BODY_SIZE, BIND_HOST

# Error codes
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR, SERVER_ERROR

# Dispatcher
Dispatcher

# Agent Pool
Agent, AgentConfig, AgentPool, SharedComponents

# Exceptions
ParseError, InvalidParamsError, HttpParseError

# Authentication
API_KEY_PREFIX, generate_api_key, validate_api_key, ServerKeyManager, discover_api_key

# Detection
DetectionResult, detect_server, wait_for_server
```

---

## Summary of RPC Methods

### Global Methods (POST / or /rpc)

| Method | Description |
|--------|-------------|
| `create_agent` | Create a new agent instance (with optional preset and permissions) |
| `destroy_agent` | Destroy an agent and clean up |
| `list_agents` | List all active agents |
| `shutdown_server` | Signal server to shut down |

### Agent Methods (POST /agent/{id})

| Method | Description |
|--------|-------------|
| `send` | Send message to LLM, get response |
| `cancel` | Cancel in-progress request |
| `shutdown` | Signal agent shutdown |
| `get_tokens` | Get token usage (if context available) |
| `get_context` | Get context info (if context available) |
