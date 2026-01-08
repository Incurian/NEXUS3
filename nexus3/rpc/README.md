# NEXUS3 RPC Module

JSON-RPC 2.0 protocol implementation for NEXUS3 headless mode. Enables programmatic control of NEXUS3 via HTTP for automation, testing, and integration with external tools.

## Purpose

This module provides the protocol layer for `nexus3 --serve` mode. Instead of interactive REPL input/output, it runs an HTTP server that accepts JSON-RPC 2.0 requests and returns responses. This enables:

- Automated testing without human interaction
- Integration with external AI orchestrators (e.g., Claude Code)
- Subagent communication (parent/child agents)
- Scripted automation pipelines
- Multi-turn conversations with persistent context

## Architecture

```
HTTP POST (JSON body) --> read_http_request() --> parse_request() --> Dispatcher.dispatch()
                                                                            |
                                                                            v
HTTP Response (JSON) <-- send_http_response() <-- serialize_response() <----+
```

```
+-------------+         HTTP POST           +-------------+
|   Caller    | --------------------------> |   Nexus     |
| (any tool)  | <-------------------------- |   Agent     |
+-------------+         JSON-RPC            +-------------+
                    (localhost:8765)
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
| `path` | `str` | Request path (e.g., `"/"`) |
| `headers` | `dict[str, str]` | HTTP headers (keys are lowercase) |
| `body` | `str` | Request body (decoded UTF-8) |

## HTTP Server (http.py)

Pure asyncio HTTP server implementation (~320 LOC, no external dependencies).

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

### Accepted Endpoints

- `POST /` - JSON-RPC endpoint
- `POST /rpc` - JSON-RPC endpoint (alias)

Other methods or paths return 404/405 errors.

### Security

- Server binds to localhost only (enforced): `127.0.0.1`, `localhost`, or `::1`
- Attempting to bind to any other address (e.g., `0.0.0.0`) raises `ValueError`
- Not exposed to network by default
- Request body size limited to 1MB (`MAX_BODY_SIZE`) to prevent DoS
- 30-second timeout on request reading (request line, headers, and body)

## Protocol Functions (protocol.py)

### Server-Side Functions

| Function | Description |
|----------|-------------|
| `parse_request(line)` | Parse JSON line into `Request`. Raises `ParseError` on failure. |
| `serialize_response(response)` | Serialize `Response` to compact JSON line (no trailing newline). |
| `make_success_response(id, result)` | Create success response with result. |
| `make_error_response(id, code, message, data=None)` | Create error response. |

### Client-Side Functions

These functions are for client-side use (e.g., `NexusClient`):

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

## Dispatcher (dispatcher.py)

Routes requests to handler methods. Manages session state and handles errors.

### Type Alias

```python
Handler = Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]
```

Handler functions take a params dict and return a result dict asynchronously.

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

Returns `True` when `shutdown` method has been called. Used by server main loop.

### Methods

```python
async def dispatch(request: Request) -> Response | None
```

Routes request to appropriate handler. Returns `None` for notifications.

### Available RPC Methods

| Method | Params | Returns | Description |
|--------|--------|---------|-------------|
| `send` | `{"content": "...", "request_id": "..."}` | `{"content": "...", "request_id": "..."}` | Send message to LLM, get full response (non-streaming) |
| `cancel` | `{"request_id": "..."}` | `{"cancelled": true/false, "request_id": "..."}` | Cancel an in-progress send request |
| `shutdown` | (none) | `{"success": true}` | Signal graceful shutdown; sets `should_shutdown` flag |
| `get_tokens` | (none) | Token usage dict | Get context token breakdown (requires context) |
| `get_context` | (none) | `{"message_count": N, "system_prompt": bool}` | Get message count and system prompt status (requires context) |

**`send` parameter validation:**
- `content` is required and must be a string
- `request_id` is optional; if not provided, a unique ID is auto-generated
- Missing `content` raises `InvalidParamsError` (-32602)
- Non-string `content` raises `InvalidParamsError` (-32602)
- Response includes `request_id` which can be used with `cancel`

**`cancel` parameter validation:**
- `request_id` is required and must be a string
- Returns `{"cancelled": true, "request_id": "..."}` if the request was found and cancelled
- Returns `{"cancelled": false, "request_id": "..."}` if no matching request was in progress

### Error Handling

The dispatcher catches exceptions and converts them to appropriate error responses:

- `InvalidParamsError` -> `INVALID_PARAMS` (-32602)
- `NexusError` -> `INTERNAL_ERROR` (-32603) with message
- Other exceptions -> `INTERNAL_ERROR` (-32603) with type and message

Notifications (requests without `id`) never receive error responses.

## Data Flow

```
1. HTTP POST request to localhost:8765
        |
        v
2. read_http_request() parses HTTP headers and body
        |
        v
3. parse_request() validates JSON and creates Request
        |
        v
4. Dispatcher.dispatch() looks up handler
        |
        v
5. Handler executes (e.g., _handle_send calls Session.send)
        |
        v
6. Result wrapped in Response via make_success_response()
        |
        v
7. serialize_response() creates JSON body
        |
        v
8. send_http_response() writes HTTP response
```

## Dependencies

### Internal (from other NEXUS3 modules)

| Import | Module | Purpose |
|--------|--------|---------|
| `NexusError` | `nexus3.core.errors` | Base exception class for error handling |
| `Session` | `nexus3.session` | LLM session for `send` method |
| `ContextManager` | `nexus3.context.manager` | Optional, for token/context methods (TYPE_CHECKING import) |

### External (stdlib only)

| Module | Purpose |
|--------|---------|
| `asyncio` | Async server and I/O |
| `json` | JSON parsing/serialization |
| `dataclasses` | Type definitions |
| `typing` | Type hints |
| `collections.abc` | Handler type alias |

## Usage Examples

### Send a message

```bash
curl -X POST http://localhost:8765 \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"send","params":{"content":"Hello"},"id":1}'
```

Response:
```json
{"jsonrpc":"2.0","id":1,"result":{"content":"Hello! How can I help you?","request_id":"req_abc123"}}
```

### Multi-turn conversation

```bash
# First message
curl -X POST http://localhost:8765 \
  -d '{"jsonrpc":"2.0","method":"send","params":{"content":"My name is Alice"},"id":1}'
# Response: {"jsonrpc":"2.0","id":1,"result":{"content":"Nice to meet you, Alice!"}}

# Second message (agent remembers context)
curl -X POST http://localhost:8765 \
  -d '{"jsonrpc":"2.0","method":"send","params":{"content":"What is my name?"},"id":2}'
# Response: {"jsonrpc":"2.0","id":2,"result":{"content":"Your name is Alice."}}
```

### Shutdown

```bash
curl -X POST http://localhost:8765 \
  -d '{"jsonrpc":"2.0","method":"shutdown","id":2}'
```

Response:
```json
{"jsonrpc":"2.0","id":2,"result":{"success":true}}
```

### Get token usage

```bash
curl -X POST http://localhost:8765 \
  -d '{"jsonrpc":"2.0","method":"get_tokens","id":3}'
```

Response:
```json
{"jsonrpc":"2.0","id":3,"result":{"system":150,"tools":0,"messages":42,"total":192,"budget":8000,"available":6000}}
```

### Error response

```bash
curl -X POST http://localhost:8765 \
  -d '{"jsonrpc":"2.0","method":"unknown","id":4}'
```

Response:
```json
{"jsonrpc":"2.0","id":4,"error":{"code":-32601,"message":"Method not found: unknown"}}
```

### Invalid params

```bash
curl -X POST http://localhost:8765 \
  -d '{"jsonrpc":"2.0","method":"send","params":{},"id":5}'
```

Response:
```json
{"jsonrpc":"2.0","id":5,"error":{"code":-32602,"message":"Missing required parameter: content"}}
```

### Cancelling a request

For long-running requests, you can cancel them from another terminal using the `cancel` method. The `send` method accepts an optional `request_id` parameter that you can use to identify the request for cancellation.

**Terminal 1 - Start a long-running request:**
```bash
curl -X POST http://localhost:8765 \
  -d '{"jsonrpc":"2.0","method":"send","params":{"content":"Write a long essay about the history of computing","request_id":"my-req-1"},"id":1}'
```

**Terminal 2 - Cancel the request:**
```bash
curl -X POST http://localhost:8765 \
  -d '{"jsonrpc":"2.0","method":"cancel","params":{"request_id":"my-req-1"},"id":2}'
```

Response (success - request was cancelled):
```json
{"jsonrpc":"2.0","id":2,"result":{"cancelled":true,"request_id":"my-req-1"}}
```

Response (not found - request already completed or never existed):
```json
{"jsonrpc":"2.0","id":2,"result":{"cancelled":false,"request_id":"my-req-1"}}
```

When a request is cancelled, the original `send` request will return with a partial response (whatever content was generated before cancellation).

### Send with auto-generated request_id

If you don't provide a `request_id`, one is automatically generated and returned in the response:

```bash
curl -X POST http://localhost:8765 \
  -d '{"jsonrpc":"2.0","method":"send","params":{"content":"Hello"},"id":1}'
```

Response:
```json
{"jsonrpc":"2.0","id":1,"result":{"content":"Hello! How can I help you?","request_id":"req_abc123"}}
```

## Command Line Usage

```bash
# Start HTTP server on default port (8765)
python -m nexus3 --serve

# Start HTTP server on custom port
python -m nexus3 --serve 9000

# Then send requests via curl, httpie, or any HTTP client
curl -X POST http://localhost:8765 \
  -d '{"jsonrpc":"2.0","method":"send","params":{"content":"Hi"},"id":1}'
```

## Python Client (`nexus3.client`)

For Python applications, the `NexusClient` class provides a convenient async interface to communicate with a running NEXUS3 server. This is located in `nexus3/client.py` (separate from the `rpc` module, but closely related).

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
| `send(content)` | `content: str`, `request_id: int \| None` | `dict[str, Any]` | Send message, get response |
| `cancel(request_id)` | `request_id: int \| None` | `dict[str, Any]` | Cancel an in-progress request |
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

### Multi-turn Example

```python
async with NexusClient() as client:
    # Server maintains conversation context
    await client.send("My name is Alice")
    result = await client.send("What is my name?")
    print(result["content"])  # "Your name is Alice."
```

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

# Exceptions
ParseError, InvalidParamsError, HttpParseError
```
