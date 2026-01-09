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

## Architecture

```
                                    +-----------------+
                                    |  GlobalDispatcher |
                                    |  (create/destroy |
                                    |   list agents)   |
                                    +-----------------+
                                           ^
                                           | POST / or /rpc
                                           |
HTTP POST --> read_http_request() --> Path Router --> dispatch()
                                           |
                                           | POST /agent/{id}
                                           v
                                    +-----------------+
                                    |   AgentPool     |
                                    |   .get(id)      |
                                    +-----------------+
                                           |
                                           v
                                    +-----------------+
                                    |   Agent         |
                                    |   .dispatcher   |
                                    +-----------------+
                                           |
                                           v
                                    +-----------------+
                                    |   Dispatcher    |
                                    |   (send/cancel/ |
                                    |    shutdown)    |
                                    +-----------------+
```

### Multi-Agent Architecture

```
+-------------+                                     +-----------------+
|   Caller    |  POST /                             |  GlobalDispatcher|
| (any tool)  | ----------------------------------> | create_agent     |
|             | <---------------------------------- | destroy_agent    |
|             |                                     | list_agents      |
+-------------+                                     +-----------------+
      |
      |         POST /agent/{id}                    +-----------------+
      | ------------------------------------------> |     Agent       |
      | <------------------------------------------ |   Dispatcher    |
      |                                             |  send/cancel/   |
      |                                             |  get_tokens/... |
                                                    +-----------------+
```

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
```

### AgentConfig

Per-agent creation options:

```python
@dataclass
class AgentConfig:
    agent_id: str | None = None       # Unique ID (auto-generated if None)
    system_prompt: str | None = None  # Override default system prompt
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

    async def destroy(self, agent_id: str) -> bool: ...

    def get(self, agent_id: str) -> Agent | None: ...

    def list(self) -> list[dict[str, Any]]: ...

    @property
    def should_shutdown(self) -> bool: ...

    def __len__(self) -> int: ...

    def __contains__(self, agent_id: str) -> bool: ...
```

#### Methods

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `create` | `agent_id?`, `config?` | `Agent` | Create new agent with isolated state |
| `destroy` | `agent_id` | `bool` | Destroy agent, clean up resources |
| `get` | `agent_id` | `Agent | None` | Get agent by ID |
| `list` | (none) | `list[dict]` | List all agents with info |
| `should_shutdown` | (property) | `bool` | True if all agents want shutdown |

#### Agent List Info

The `list()` method returns:

```python
[
    {
        "agent_id": "worker-1",
        "created_at": "2024-01-15T10:30:00",
        "message_count": 5,
        "should_shutdown": False
    },
    ...
]
```

---

## Global Dispatcher (global_dispatcher.py)

Handles agent lifecycle management (non-agent-specific methods).

### Constructor

```python
GlobalDispatcher(pool: AgentPool)
```

### Methods

```python
def handles(self, method: str) -> bool: ...
async def dispatch(self, request: Request) -> Response | None: ...
```

### Available RPC Methods

| Method | Params | Returns | Description |
|--------|--------|---------|-------------|
| `create_agent` | `{"agent_id?": "...", "system_prompt?": "..."}` | `{"agent_id": "...", "url": "/agent/..."}` | Create a new agent |
| `destroy_agent` | `{"agent_id": "..."}` | `{"success": true/false, "agent_id": "..."}` | Destroy an existing agent |
| `list_agents` | (none) | `{"agents": [...]}` | List all active agents |

#### `create_agent` Details

- `agent_id`: Optional. Auto-generated 8-char hex ID if omitted
- `system_prompt`: Optional. Override the default system prompt
- Returns the `agent_id` and `url` for subsequent agent-specific calls
- Raises `InvalidParamsError` if `agent_id` already exists

#### `destroy_agent` Details

- `agent_id`: Required. The ID of the agent to destroy
- Cleans up resources (closes logger, removes from pool)
- Returns `success: true` if found and destroyed, `false` if not found

#### `list_agents` Details

- Returns list of all active agents with:
  - `agent_id`: Agent's unique identifier
  - `created_at`: ISO 8601 timestamp
  - `message_count`: Number of messages in context
  - `should_shutdown`: Whether agent wants shutdown

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
def should_shutdown(self) -> bool
```

Returns `True` when `shutdown` method has been called.

### Methods

```python
async def dispatch(request: Request) -> Response | None
```

Routes request to appropriate handler. Returns `None` for notifications.

### Available RPC Methods

| Method | Params | Returns | Description |
|--------|--------|---------|-------------|
| `send` | `{"content": "...", "request_id?": "..."}` | `{"content": "...", "request_id": "..."}` | Send message to LLM |
| `cancel` | `{"request_id": "..."}` | `{"cancelled": true/false, ...}` | Cancel in-progress request |
| `shutdown` | (none) | `{"success": true}` | Signal graceful shutdown |
| `get_tokens` | (none) | Token usage dict | Get context token breakdown |
| `get_context` | (none) | `{"message_count": N, ...}` | Get context info |

**Note:** `get_tokens` and `get_context` are only available if `context` was provided to the constructor.

#### `send` Parameter Validation

- `content` is required and must be a string
- `request_id` is optional; if not provided, a unique ID is auto-generated
- Response includes `request_id` for use with `cancel`

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

---

## HTTP Server (http.py)

Pure asyncio HTTP server implementation with path-based routing (~390 LOC, no external dependencies).

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

### Function Signatures

```python
async def run_http_server(
    pool: AgentPool,
    global_dispatcher: GlobalDispatcher,
    port: int = DEFAULT_PORT,
    host: str = BIND_HOST,
) -> None: ...

async def handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    pool: AgentPool,
    global_dispatcher: GlobalDispatcher,
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

- Server binds to localhost only (enforced): `127.0.0.1`, `localhost`, or `::1`
- Attempting to bind to any other address (e.g., `0.0.0.0`) raises `ValueError`
- Not exposed to network by default
- Request body size limited to 1MB (`MAX_BODY_SIZE`) to prevent DoS
- 30-second timeout on request reading (request line, headers, and body)

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

### Single-Agent Request (Legacy Pattern)

```
1. HTTP POST request to localhost:8765/agent/{id}
        |
        v
2. read_http_request() parses HTTP headers and body
        |
        v
3. Path router extracts agent_id, looks up Agent in pool
        |
        v
4. parse_request() validates JSON and creates Request
        |
        v
5. Agent.dispatcher.dispatch() looks up handler
        |
        v
6. Handler executes (e.g., _handle_send calls Session.send)
        |
        v
7. Result wrapped in Response via make_success_response()
        |
        v
8. serialize_response() creates JSON body
        |
        v
9. send_http_response() writes HTTP response
```

### Multi-Agent Lifecycle

```
1. POST / with create_agent
        |
        v
2. GlobalDispatcher creates Agent via AgentPool
        |
        v
3. Returns agent_id and URL (/agent/{id})
        |
        v
4. Client uses URL for subsequent requests
        |
        v
5. POST /agent/{id} with send/cancel/etc.
        |
        v
6. Agent's Dispatcher handles request
        |
        v
7. POST / with destroy_agent to clean up
```

---

## Dependencies

### Internal (from other NEXUS3 modules)

| Import | Module | Purpose |
|--------|--------|---------|
| `NexusError` | `nexus3.core.errors` | Base exception class |
| `CancellationToken` | `nexus3.core.cancel` | Request cancellation |
| `Session` | `nexus3.session` | LLM session for `send` method |
| `SessionLogger`, `LogConfig`, `LogStream` | `nexus3.session` | Per-agent logging |
| `ContextManager`, `ContextConfig` | `nexus3.context` | Per-agent context |
| `ServiceContainer`, `SkillRegistry` | `nexus3.skill` | Per-agent skills |
| `PromptLoader` | `nexus3.context.prompt_loader` | System prompt loading |
| `Config` | `nexus3.config.schema` | Global configuration |
| `AsyncProvider` | `nexus3.core.interfaces` | LLM provider protocol |

### External (stdlib only)

| Module | Purpose |
|--------|---------|
| `asyncio` | Async server and I/O |
| `json` | JSON parsing/serialization |
| `dataclasses` | Type definitions |
| `typing` | Type hints |
| `collections.abc` | Handler type alias |
| `secrets` | Request ID generation |
| `datetime` | Agent creation timestamps |
| `pathlib` | Log directory paths |
| `uuid` | Agent ID generation |

---

## Usage Examples

### Create an Agent

```bash
curl -X POST http://localhost:8765/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"create_agent","params":{"agent_id":"worker-1"},"id":1}'
```

Response:
```json
{"jsonrpc":"2.0","id":1,"result":{"agent_id":"worker-1","url":"/agent/worker-1"}}
```

### Create Agent with Custom System Prompt

```bash
curl -X POST http://localhost:8765/ \
  -d '{"jsonrpc":"2.0","method":"create_agent","params":{"agent_id":"coder","system_prompt":"You are a coding assistant."},"id":1}'
```

### Send Message to Agent

```bash
curl -X POST http://localhost:8765/agent/worker-1 \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"send","params":{"content":"Hello"},"id":2}'
```

Response:
```json
{"jsonrpc":"2.0","id":2,"result":{"content":"Hello! How can I help you?","request_id":"a1b2c3d4"}}
```

### List All Agents

```bash
curl -X POST http://localhost:8765/ \
  -d '{"jsonrpc":"2.0","method":"list_agents","id":3}'
```

Response:
```json
{"jsonrpc":"2.0","id":3,"result":{"agents":[{"agent_id":"worker-1","created_at":"2024-01-15T10:30:00","message_count":2,"should_shutdown":false}]}}
```

### Destroy an Agent

```bash
curl -X POST http://localhost:8765/ \
  -d '{"jsonrpc":"2.0","method":"destroy_agent","params":{"agent_id":"worker-1"},"id":4}'
```

Response:
```json
{"jsonrpc":"2.0","id":4,"result":{"success":true,"agent_id":"worker-1"}}
```

### Multi-Turn Conversation

```bash
# Create agent
curl -X POST http://localhost:8765/ \
  -d '{"jsonrpc":"2.0","method":"create_agent","params":{"agent_id":"chat"},"id":1}'

# First message
curl -X POST http://localhost:8765/agent/chat \
  -d '{"jsonrpc":"2.0","method":"send","params":{"content":"My name is Alice"},"id":2}'
# Response: {"jsonrpc":"2.0","id":2,"result":{"content":"Nice to meet you, Alice!","request_id":"..."}}

# Second message (agent remembers context)
curl -X POST http://localhost:8765/agent/chat \
  -d '{"jsonrpc":"2.0","method":"send","params":{"content":"What is my name?"},"id":3}'
# Response: {"jsonrpc":"2.0","id":3,"result":{"content":"Your name is Alice.","request_id":"..."}}

# Clean up
curl -X POST http://localhost:8765/ \
  -d '{"jsonrpc":"2.0","method":"destroy_agent","params":{"agent_id":"chat"},"id":4}'
```

### Cancel a Request

**Terminal 1 - Start a long-running request:**
```bash
curl -X POST http://localhost:8765/agent/worker-1 \
  -d '{"jsonrpc":"2.0","method":"send","params":{"content":"Write a long essay","request_id":"req-1"},"id":1}'
```

**Terminal 2 - Cancel the request:**
```bash
curl -X POST http://localhost:8765/agent/worker-1 \
  -d '{"jsonrpc":"2.0","method":"cancel","params":{"request_id":"req-1"},"id":2}'
```

Response:
```json
{"jsonrpc":"2.0","id":2,"result":{"cancelled":true,"request_id":"req-1"}}
```

### Get Token Usage

```bash
curl -X POST http://localhost:8765/agent/worker-1 \
  -d '{"jsonrpc":"2.0","method":"get_tokens","id":5}'
```

Response:
```json
{"jsonrpc":"2.0","id":5,"result":{"system":150,"tools":0,"messages":42,"total":192,"budget":8000,"available":6000}}
```

### Shutdown an Agent

```bash
curl -X POST http://localhost:8765/agent/worker-1 \
  -d '{"jsonrpc":"2.0","method":"shutdown","id":6}'
```

Response:
```json
{"jsonrpc":"2.0","id":6,"result":{"success":true}}
```

### Error Responses

**Agent not found:**
```bash
curl -X POST http://localhost:8765/agent/nonexistent \
  -d '{"jsonrpc":"2.0","method":"send","params":{"content":"Hi"},"id":1}'
```

Response (HTTP 404):
```json
{"error": "Agent not found: nonexistent"}
```

**Method not found:**
```bash
curl -X POST http://localhost:8765/agent/worker-1 \
  -d '{"jsonrpc":"2.0","method":"unknown","id":1}'
```

Response:
```json
{"jsonrpc":"2.0","id":1,"error":{"code":-32601,"message":"Method not found: unknown"}}
```

**Invalid params:**
```bash
curl -X POST http://localhost:8765/agent/worker-1 \
  -d '{"jsonrpc":"2.0","method":"send","params":{},"id":1}'
```

Response:
```json
{"jsonrpc":"2.0","id":1,"error":{"code":-32602,"message":"Missing required parameter: content"}}
```

---

## Command Line Usage

```bash
# Start HTTP server on default port (8765)
python -m nexus3 --serve

# Start HTTP server on custom port
python -m nexus3 --serve 9000

# With auto-reload on code changes
python -m nexus3 --serve --reload
```

---

## Python Client (`nexus3.client`)

For Python applications, the `NexusClient` class provides a convenient async interface to communicate with a running NEXUS3 server. Located in `nexus3/client.py` (separate from the `rpc` module).

### Basic Usage

```python
from nexus3.client import NexusClient

async with NexusClient() as client:
    result = await client.send("Hello!")
    print(result["content"])
```

### Constructor

```python
NexusClient(url: str = "http://127.0.0.1:8765", timeout: float = 60.0)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | `str` | `"http://127.0.0.1:8765"` | Base URL of the JSON-RPC server |
| `timeout` | `float` | `60.0` | Request timeout in seconds |

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

async with NexusClient() as client:
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
```

---

## Summary of RPC Methods

### Global Methods (POST / or /rpc)

| Method | Description |
|--------|-------------|
| `create_agent` | Create a new agent instance |
| `destroy_agent` | Destroy an agent and clean up |
| `list_agents` | List all active agents |

### Agent Methods (POST /agent/{id})

| Method | Description |
|--------|-------------|
| `send` | Send message to LLM, get response |
| `cancel` | Cancel in-progress request |
| `shutdown` | Signal agent shutdown |
| `get_tokens` | Get token usage (if context available) |
| `get_context` | Get context info (if context available) |
