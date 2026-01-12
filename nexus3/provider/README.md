# Provider Module

LLM provider implementations for NEXUS3. This module handles all communication with external AI model APIs.

## Purpose

The provider module abstracts LLM API interactions behind a consistent async interface. All providers implement the `AsyncProvider` protocol, enabling:

- Unified interface for different LLM backends
- Both streaming and non-streaming completions
- Tool/function calling support with bidirectional message conversion
- Streaming with typed events (content, reasoning, tool calls)
- Optional raw API logging for debugging

## Files

| File | Description |
|------|-------------|
| `__init__.py` | Module exports (`OpenRouterProvider`) |
| `openrouter.py` | OpenRouter API implementation with full tool call support |

## Key Types

### OpenRouterProvider

The primary provider implementation. Communicates with OpenRouter's API (OpenAI-compatible format).

```python
from nexus3.provider import OpenRouterProvider
from nexus3.config.schema import ProviderConfig

config = ProviderConfig(
    api_key_env="OPENROUTER_API_KEY",
    model="anthropic/claude-sonnet-4",
    base_url="https://openrouter.ai/api/v1",
)
provider = OpenRouterProvider(config)
```

**Key features:**
- Async HTTP via `httpx` with 30-second default timeout
- SSE stream parsing for real-time responses
- Full tool call support (send tool definitions, receive tool calls, send tool results)
- Streaming with typed `StreamEvent` objects
- Reasoning/thinking delta support (for models like Grok/xAI)
- Automatic retry with exponential backoff for transient errors
- Automatic error handling (401, 403, 404, 429, 5xx, connection errors)
- Optional raw logging callback (can be set after construction)

## AsyncProvider Protocol

Defined in `nexus3/core/interfaces.py`. Any provider must implement:

```python
class AsyncProvider(Protocol):
    async def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> Message:
        """Non-streaming completion. Returns full response."""
        ...

    def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Streaming completion. Yields StreamEvent objects."""
        ...
```

Both methods accept:
- `messages`: Conversation history as `Message` objects
- `tools`: Optional tool definitions in OpenAI function format

## Tool Call Support

The provider fully supports the OpenAI function calling protocol:

### Sending Tool Definitions

Pass tool definitions to `complete()` or `stream()`:

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather for a location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string"}
                },
                "required": ["location"],
            },
        },
    }
]

response = await provider.complete(messages, tools=tools)
```

### Receiving Tool Calls

When the model decides to call tools, the response `Message` includes parsed `ToolCall` objects:

```python
if response.tool_calls:
    for tc in response.tool_calls:
        print(f"Tool: {tc.name}")       # e.g., "get_weather"
        print(f"ID: {tc.id}")           # e.g., "call_abc123"
        print(f"Args: {tc.arguments}")  # e.g., {"location": "NYC"}
```

Tool calls are parsed from the API response with:
- Automatic JSON parsing of arguments
- Fallback to empty dict on parse errors
- Immutable `tuple[ToolCall, ...]` in response

### Sending Tool Results

Include previous assistant tool calls and tool results in the conversation:

```python
# Previous assistant message with tool calls
messages.append(Message(
    role=Role.ASSISTANT,
    content="",  # Often empty when calling tools
    tool_calls=(ToolCall(id="call_123", name="get_weather", arguments={"location": "NYC"}),),
))

# Tool result message
messages.append(Message(
    role=Role.TOOL,
    content='{"temp": 72, "conditions": "sunny"}',
    tool_call_id="call_123",  # Must match the tool call ID
))

# Continue conversation
response = await provider.complete(messages)
```

The provider converts messages to OpenAI format:
- `tool_call_id` is included for tool result messages
- `tool_calls` are serialized with function name and JSON-encoded arguments

## Streaming

The `stream()` method returns an `AsyncIterator[StreamEvent]` that yields typed events:

```python
from nexus3.core.types import ContentDelta, ReasoningDelta, ToolCallStarted, StreamComplete

async for event in provider.stream(messages, tools=tools):
    if isinstance(event, ContentDelta):
        print(event.text, end="", flush=True)
    elif isinstance(event, ReasoningDelta):
        print(f"[thinking: {event.text}]", end="")
    elif isinstance(event, ToolCallStarted):
        print(f"\n[Tool call: {event.name}]")
    elif isinstance(event, StreamComplete):
        # event.message contains the full response with all tool_calls
        if event.message.tool_calls:
            for tc in event.message.tool_calls:
                print(f"Execute: {tc.name}({tc.arguments})")
```

### Stream Event Types

| Event | Description |
|-------|-------------|
| `ContentDelta` | A chunk of content text. Access via `event.text`. |
| `ReasoningDelta` | A chunk of reasoning/thinking content (for models like Grok/xAI). Access via `event.text`. |
| `ToolCallStarted` | Emitted once when a tool call is first detected. Contains `name`, `id`, and `index`. |
| `StreamComplete` | Final event. Contains `event.message` with full content and parsed `tool_calls`. |

All stream events inherit from `StreamEvent` base class (defined in `nexus3/core/types.py`).

### Implementation Details

- Uses Server-Sent Events (SSE) protocol
- `_parse_sse_stream_with_tools()` handles SSE parsing and event accumulation
- `_process_stream_event()` processes each chunk, accumulating tool call deltas by index
- Tool calls are built incrementally from `delta.tool_calls` fields
- `ToolCallStarted` is yielded the first time each tool call index is seen (when both id and name are available)
- `StreamComplete` contains the final `Message` with all accumulated content and tool calls
- Reasoning content (`delta.reasoning`) is yielded as `ReasoningDelta` for models that support it

## Raw Logging

Providers support optional raw API logging via the `RawLogCallback` protocol:

```python
class RawLogCallback(Protocol):
    def on_request(self, endpoint: str, payload: dict[str, Any]) -> None: ...
    def on_response(self, status: int, body: dict[str, Any]) -> None: ...
    def on_chunk(self, chunk: dict[str, Any]) -> None: ...
```

The callback can be passed at construction or set later:

```python
# At construction
provider = OpenRouterProvider(config, raw_log=my_logger)

# Or set later (useful when logger isn't available at construction)
provider.set_raw_log_callback(my_logger)

# Disable logging
provider.set_raw_log_callback(None)
```

Logging points:
- `on_request`: Called before each API request with endpoint URL and request body
- `on_response`: Called after non-streaming responses with status code and parsed body
- `on_chunk`: Called for each parsed SSE chunk during streaming

## Dependencies

**External:**
- `httpx` - Async HTTP client

**Internal (from nexus3):**
- `nexus3.config.schema.ProviderConfig` - Configuration dataclass
- `nexus3.core.types.Message, Role, ToolCall` - Core message types
- `nexus3.core.types.StreamEvent, ContentDelta, ReasoningDelta, ToolCallStarted, StreamComplete` - Stream event types
- `nexus3.core.errors.ProviderError` - Error type for API failures
- `nexus3.core.interfaces.RawLogCallback` - Raw logging protocol

## Usage Examples

### Non-streaming completion

```python
from nexus3.core.types import Message, Role

messages = [
    Message(role=Role.SYSTEM, content="You are helpful."),
    Message(role=Role.USER, content="Hello!"),
]

response = await provider.complete(messages)
print(response.content)
```

### Streaming completion

```python
from nexus3.core.types import ContentDelta, StreamComplete

messages = [Message(role=Role.USER, content="Tell me a story.")]

async for event in provider.stream(messages):
    if isinstance(event, ContentDelta):
        print(event.text, end="")
    elif isinstance(event, StreamComplete):
        pass  # Stream finished
print()  # Final newline
```

### Full tool calling workflow

```python
from nexus3.core.types import Message, Role, ToolCall

# Define tools
tools = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get weather for a location",
        "parameters": {
            "type": "object",
            "properties": {"location": {"type": "string"}},
            "required": ["location"],
        },
    },
}]

# Initial request
messages = [Message(role=Role.USER, content="What's the weather in NYC?")]
response = await provider.complete(messages, tools=tools)

# Check for tool calls
if response.tool_calls:
    # Add assistant's response to history
    messages.append(response)

    # Execute each tool and add results
    for tc in response.tool_calls:
        result = execute_tool(tc.name, tc.arguments)  # Your tool execution
        messages.append(Message(
            role=Role.TOOL,
            content=result,
            tool_call_id=tc.id,
        ))

    # Get final response
    final_response = await provider.complete(messages, tools=tools)
    print(final_response.content)
```

## Error Handling

All API errors raise `ProviderError`:

```python
from nexus3.core.errors import ProviderError

try:
    response = await provider.complete(messages)
except ProviderError as e:
    print(f"API error: {e}")
```

### Retry Logic

The provider automatically retries failed requests with exponential backoff:

| Setting | Value |
|---------|-------|
| Max retries | 3 attempts |
| Max delay | 10 seconds |
| Backoff formula | `2^attempt + random(0-1)` seconds |
| Retryable status codes | 429, 500, 502, 503, 504 |

**Retryable errors:**
- Rate limiting (429)
- Server errors (500, 502, 503, 504)
- Connection errors (`httpx.ConnectError`)
- Timeout errors (`httpx.TimeoutException`)

**Non-retryable errors (fail immediately):**
- Authentication failure (401)
- Access forbidden (403)
- Endpoint not found (404)
- Other client errors (4xx)
- Other HTTP errors

### Error Cases

- Missing API key (checked at construction, raises `ProviderError`)
- Authentication failure (401) - fails immediately
- Access forbidden (403) - fails immediately
- Endpoint not found (404) - fails immediately
- Rate limiting (429) - retries with backoff
- Server errors (5xx) - retries with backoff
- Connection errors (`httpx.ConnectError`) - retries with backoff
- Timeout errors (`httpx.TimeoutException`) - retries with backoff
- Response parsing errors (malformed JSON, missing fields) - fails immediately

## Configuration

Via `ProviderConfig` (Pydantic model):

| Field | Default | Description |
|-------|---------|-------------|
| `type` | `"openrouter"` | Provider type identifier |
| `api_key_env` | `"OPENROUTER_API_KEY"` | Environment variable containing API key |
| `model` | `"x-ai/grok-code-fast-1"` | Model identifier |
| `base_url` | `"https://openrouter.ai/api/v1"` | API base URL |

## Internal Implementation Details

### Constants

The following constants are defined in `openrouter.py`:

| Constant | Value | Description |
|----------|-------|-------------|
| `DEFAULT_TIMEOUT` | 30.0 | HTTP request timeout in seconds |
| `MAX_RETRIES` | 3 | Maximum number of retry attempts |
| `MAX_RETRY_DELAY` | 10.0 | Maximum delay between retries in seconds |
| `RETRYABLE_STATUS_CODES` | {429, 500, 502, 503, 504} | HTTP status codes that trigger retries |

### Retry Helpers

`_calculate_retry_delay(attempt: int) -> float`:
- Calculates delay with exponential backoff: `2^attempt + random(0, 1)`
- Capped at `MAX_RETRY_DELAY` (10 seconds)
- Provides jitter to avoid thundering herd problems

`_is_retryable_error(status_code: int) -> bool`:
- Returns `True` if status code is in `RETRYABLE_STATUS_CODES`
- Used to determine whether to retry or fail immediately

### Message Conversion

`_message_to_dict()` converts `Message` objects to OpenAI format:
- Maps `role` enum to string value
- Includes `tool_call_id` for tool result messages
- Serializes `tool_calls` with JSON-encoded arguments

### Tool Call Parsing

`_parse_tool_calls()` converts API response to `ToolCall` objects:
- Extracts `id`, `name`, and `arguments` from each tool call
- JSON-parses the arguments string
- Returns immutable tuple of `ToolCall` objects
- Falls back to empty dict on JSON parse errors

### SSE Stream Parsing

`_parse_sse_stream_with_tools()` handles Server-Sent Events with tool call detection:
- Buffers incoming text for line-by-line processing
- Skips empty lines and SSE comments
- Parses `data:` prefixed lines as JSON
- Calls `_process_stream_event()` for each parsed chunk
- Accumulates `delta.tool_calls` by index into complete tool calls
- Yields `ToolCallStarted` when a new tool call index is first seen (requires both id and name)
- Yields `ContentDelta` for content chunks
- Yields `ReasoningDelta` for reasoning/thinking chunks (model-dependent)
- Yields `StreamComplete` with final `Message` containing all tool calls
- Handles stream end via `[DONE]` marker or end-of-stream
