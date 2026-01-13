# Provider Module

LLM provider implementations for NEXUS3. This module handles communication with external AI model APIs via the `AsyncProvider` protocol (defined in `nexus3/core/interfaces.py`).

## Files

| File | Description |
|------|-------------|
| `__init__.py` | Exports `OpenRouterProvider` |
| `openrouter.py` | [OpenRouter](https://openrouter.ai) API provider (OpenAI-compatible) |

## OpenRouterProvider

**Primary provider.** Supports streaming, full tool calling, reasoning deltas (for supported models), retries.

### Initialization

```python
from nexus3.provider import OpenRouterProvider
from nexus3.config.schema import ProviderConfig

config = ProviderConfig(
    type="openrouter",
    api_key_env="OPENROUTER_API_KEY",
    model="anthropic/claude-3.5-sonnet",  # Required; any OpenRouter model
    base_url="https://openrouter.ai/api/v1",
    reasoning=False,  # Optional: enables `reasoning: {"effort": "high"}` for Grok/xAI etc.
)
provider = OpenRouterProvider(config)  # Raises ProviderError if API key missing
```

- `set_raw_log_callback(logger: RawLogCallback | None)`: Enable/disable raw API logging post-init.

### Core Methods

Both accept `messages: list[Message]`, optional `tools: list[dict]` (OpenAI format).

- `complete(...) -> Message`: Non-streaming. `Message` may have `tool_calls: tuple[ToolCall, ...]`.
- `stream(...) -> AsyncIterator[StreamEvent]`: Yields `ContentDelta`, `ReasoningDelta`, `ToolCallStarted`, `StreamComplete(message: Message)`.

### Streaming Events

| Event | Fields | Usage |
|-------|--------|-------|
| `ContentDelta` | `text: str` | Print content chunks |
| `ReasoningDelta` | `text: str` | Model thinking (e.g., Grok) |
| `ToolCallStarted` | `index: int`, `id: str`, `name: str` | Tool detected |
| `StreamComplete` | `message: Message` | Final `content` + `tool_calls` |

**Example:**
```python
async for event in provider.stream(messages, tools):
    if isinstance(event, (ContentDelta, ReasoningDelta)):
        print(event.text, end="")
    elif isinstance(event, ToolCallStarted):
        print(f"\n[Tool: {event.name}]")
    elif isinstance(event, StreamComplete):
        # event.message.tool_calls
        pass
```

### Tool Calling

1. Pass `tools` → model may return `tool_calls`.
2. `ToolCall(id, name, arguments: dict)` parsed automatically (JSON args, fallback `{}`).
3. Append `Message(role=Role.ASSISTANT, content="", tool_calls=...)`.
4. Append `Message(role=Role.TOOL, content=json.dumps(result), tool_call_id=id)` per call.
5. Repeat.

Provider converts `Message` ↔ OpenAI dict (handles `tool_calls`, `tool_call_id`).

### Retry Logic

**Automatic** (3 max attempts):

| Trigger | Backoff | Max Delay |
|---------|---------|-----------|
| 429, 500/502/503/504, connect/timeout | `min(2^attempt + rand(0,1), 10s)` | 10s |

**Immediate fail:** 401/403/404/4xx, parse errors.

All raise `ProviderError`.

### Raw Logging (`RawLogCallback` protocol)

```python
def on_request(self, endpoint: str, payload: dict): ...
def on_response(self, status: int, body: dict): ...
def on_chunk(self, chunk: dict): ...
```

Called for req/res/chunks (stream).

### Dependencies

**External:** `httpx`

**Internal:** `nexus3.config.schema.ProviderConfig`, `nexus3.core.types.*`, `nexus3.core.errors.ProviderError`, `nexus3.core.interfaces.RawLogCallback`.

### Implementation Notes

- 30s HTTP timeout.
- SSE parsing buffers/accumulates tool deltas by `index`.
- `_parse_tool_calls()`: JSON args with fallback.
- No model defaults in code (from `config.model`).
