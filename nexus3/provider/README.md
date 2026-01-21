# NEXUS3 Provider Module

LLM provider implementations for NEXUS3 with unified async interface, multi-provider support, streaming, tool calling, retries, and security hardening.

## Overview

This module abstracts LLM API differences behind a common `AsyncProvider` protocol. The `create_provider()` factory instantiates the appropriate provider class based on configuration, while `ProviderRegistry` manages multiple providers with lazy initialization and caching.

## Supported Providers

| Type | API Format | Endpoint | Auth Method | Use Case |
|------|------------|----------|-------------|----------|
| `openrouter` | OpenAI-compatible | `/v1/chat/completions` | Bearer token | Default, access to many models |
| `openai` | OpenAI-compatible | `/v1/chat/completions` | Bearer token | Direct OpenAI API |
| `azure` | OpenAI-compatible | `/openai/deployments/{name}/chat/completions` | api-key header | Azure OpenAI Service |
| `anthropic` | Native Anthropic | `/v1/messages` | x-api-key header | Direct Anthropic Claude API |
| `ollama` | OpenAI-compatible | `/v1/chat/completions` | None | Local Ollama server |
| `vllm` | OpenAI-compatible | `/v1/chat/completions` | None | vLLM OpenAI-compatible server |

## Module Structure

```
nexus3/provider/
├── __init__.py        # Factory, exports, PROVIDER_DEFAULTS
├── base.py            # BaseProvider ABC with HTTP/retry/auth logic
├── registry.py        # ProviderRegistry for multi-provider management
├── openai_compat.py   # OpenAICompatProvider for OpenAI-format APIs
├── anthropic.py       # AnthropicProvider for native Anthropic API
└── azure.py           # AzureOpenAIProvider extending OpenAI-compat
```

## Key Exports

```python
from nexus3.provider import (
    create_provider,      # Factory function
    ProviderRegistry,     # Multi-provider manager
    OpenRouterProvider,   # Alias for OpenAICompatProvider (backward compat)
    PROVIDER_DEFAULTS,    # Default settings per provider type
)
```

---

## AsyncProvider Protocol

Defined in `nexus3/core/interfaces.py`, this is the interface all providers implement:

```python
class AsyncProvider(Protocol):
    async def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> Message:
        """Non-streaming completion. Returns assistant response with optional tool_calls."""
        ...

    def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Streaming completion. Yields ContentDelta, ToolCallStarted, StreamComplete."""
        ...
```

### StreamEvent Types

| Event | Fields | Description |
|-------|--------|-------------|
| `ContentDelta` | `text: str` | Incremental text content |
| `ReasoningDelta` | `text: str` | Extended thinking/reasoning output (Grok/OpenRouter) |
| `ToolCallStarted` | `index: int`, `id: str`, `name: str` | Tool call detected |
| `StreamComplete` | `message: Message` | Final message with all content and tool_calls |

---

## Provider Factory

The `create_provider()` function instantiates providers based on `config.type`:

```python
from nexus3.provider import create_provider
from nexus3.config.schema import ProviderConfig

# Create provider with defaults
config = ProviderConfig(type="anthropic")
provider = create_provider(config, model_id="claude-sonnet-4-20250514")

# With custom settings
config = ProviderConfig(
    type="openai",
    api_key_env="OPENAI_API_KEY",
    request_timeout=180.0,
    max_retries=5,
)
provider = create_provider(config, model_id="gpt-4o")

# With extended thinking/reasoning
provider = create_provider(config, model_id="gpt-4o", reasoning=True)

# With raw logging
provider = create_provider(config, model_id="gpt-4o", raw_log=my_logger)
```

### Provider Defaults

The `PROVIDER_DEFAULTS` dict provides sensible defaults for each provider type:

```python
PROVIDER_DEFAULTS = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "auth_method": AuthMethod.BEARER,
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "auth_method": AuthMethod.BEARER,
    },
    "azure": {
        "api_key_env": "AZURE_OPENAI_KEY",
        "auth_method": AuthMethod.API_KEY,
        "api_version": "2024-02-01",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "api_key_env": "ANTHROPIC_API_KEY",
        "auth_method": AuthMethod.X_API_KEY,
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "auth_method": AuthMethod.NONE,
        "api_key_env": "",
    },
    "vllm": {
        "base_url": "http://localhost:8000/v1",
        "auth_method": AuthMethod.NONE,
        "api_key_env": "",
    },
}
```

---

## ProviderRegistry

The `ProviderRegistry` manages multiple provider instances with lazy initialization and caching. Providers are created on first access to avoid connecting to unused APIs at startup.

```python
from nexus3.provider.registry import ProviderRegistry
from nexus3.config.schema import Config

# Initialize registry with config
config = Config(...)  # Loaded from config.json
registry = ProviderRegistry(config)

# Get provider by name and model (lazy-created, cached)
provider = registry.get("openrouter", "anthropic/claude-haiku-4.5")

# Get provider via model alias (uses config.resolve_model)
provider = registry.get_for_model("haiku")  # Resolves via config models dict
provider = registry.get_for_model()         # Uses default_model from config

# Enable reasoning for a provider
provider = registry.get("openrouter", "x-ai/grok-2", reasoning=True)

# Set raw logging on all providers
registry.set_raw_log_callback(my_logger)

# Check cached providers
print(registry.cached_providers)  # ["openrouter:anthropic/claude-haiku-4.5", ...]

# Clear cache (force recreation on next access)
registry.clear_cache()

# Clean up on shutdown
await registry.aclose()
```

### Cache Key Format

Providers are cached by `provider_name:model_id`, so the same provider can serve multiple models efficiently:
- `openrouter:anthropic/claude-sonnet-4`
- `openrouter:anthropic/claude-haiku-4.5`
- `anthropic:claude-sonnet-4-20250514`

---

## BaseProvider

The abstract base class providing shared functionality for all providers.

### Features

| Feature | Description |
|---------|-------------|
| **API Key Resolution** | Gets key from environment variable per `api_key_env` config |
| **Authentication** | Builds auth headers based on `auth_method` (Bearer, api-key, x-api-key, none) |
| **SSRF Protection** | Validates `base_url` - HTTPS required for non-localhost hosts |
| **Retry Logic** | Exponential backoff with jitter for 429/5xx errors |
| **Timeout Handling** | Configurable request timeout (default 120s) |
| **Error Body Limits** | Caps error response bodies at 10KB to prevent memory exhaustion |
| **Connection Reuse** | Lazy httpx client with persistent connections |
| **Raw Logging** | Callbacks for request/response/chunk logging |

### Abstract Methods (Subclasses Implement)

```python
def _build_endpoint(self, stream: bool = False) -> str:
    """Build the API endpoint URL."""

def _build_request_body(
    self,
    messages: list[Message],
    tools: list[dict[str, Any]] | None,
    stream: bool,
) -> dict[str, Any]:
    """Build request body in provider-specific format."""

def _parse_response(self, data: dict[str, Any]) -> Message:
    """Parse non-streaming response to Message."""

async def _parse_stream(self, response: httpx.Response) -> AsyncIterator[StreamEvent]:
    """Parse SSE stream to StreamEvents."""
```

### Retry Configuration

```python
# Module constants (fallbacks)
DEFAULT_TIMEOUT = 120.0       # seconds
MAX_RETRIES = 3
MAX_RETRY_DELAY = 10.0        # seconds
DEFAULT_RETRY_BACKOFF = 1.5   # exponential multiplier
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Per-provider config overrides
config = ProviderConfig(
    type="openrouter",
    request_timeout=180.0,
    max_retries=5,
    retry_backoff=2.0,
)
```

---

## Provider Implementations

### OpenAICompatProvider

Handles OpenAI-format APIs (OpenRouter, OpenAI, Ollama, vLLM).

**Endpoint:** `{base_url}/chat/completions`

**Message Format:**
```python
{
    "role": "user" | "assistant" | "system" | "tool",
    "content": "text content",
    "tool_calls": [...],      # Assistant messages with tool calls
    "tool_call_id": "...",    # Tool result messages
}
```

**Tool Format (OpenAI function calling):**
```python
{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get current weather",
        "parameters": {
            "type": "object",
            "properties": {"location": {"type": "string"}},
            "required": ["location"]
        }
    }
}
```

**Extended Thinking/Reasoning:**
When `reasoning=True`, adds `{"reasoning": {"effort": "high"}}` to request body (supported by Grok via OpenRouter).

**SSE Stream Format:**
```
data: {"choices": [{"delta": {"content": "Hello"}}]}
data: {"choices": [{"delta": {"tool_calls": [...]}}]}
data: [DONE]
```

### AzureOpenAIProvider

Extends `OpenAICompatProvider` with Azure-specific endpoint format.

**Endpoint:** `{base_url}/openai/deployments/{deployment}/chat/completions?api-version={api_version}`

**Configuration:**
```python
config = ProviderConfig(
    type="azure",
    base_url="https://my-resource.openai.azure.com",
    api_key_env="AZURE_OPENAI_KEY",
    deployment="gpt-4",          # Deployment name
    api_version="2024-02-01",    # API version
    auth_method=AuthMethod.API_KEY,
)
```

### AnthropicProvider

Native Anthropic Messages API (different from OpenAI format).

**Endpoint:** `{base_url}/v1/messages`

**Key Differences from OpenAI:**
- System prompt is separate field, not a message
- Content is array of blocks (`text`, `tool_use`, `tool_result`)
- Tool results go in user message content, not separate tool role
- Different streaming event types

**Message Conversion:**
```python
# NEXUS3 Message with tool_calls
Message(role=Role.ASSISTANT, content="Let me check...", tool_calls=[...])

# Becomes Anthropic format
{
    "role": "assistant",
    "content": [
        {"type": "text", "text": "Let me check..."},
        {"type": "tool_use", "id": "...", "name": "...", "input": {...}}
    ]
}
```

**Tool Format Conversion:**
```python
# OpenAI format (input)
{"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}

# Anthropic format (converted)
{"name": "...", "description": "...", "input_schema": {...}}
```

**SSE Stream Events:**
- `message_start` - Initial metadata
- `content_block_start` - New text or tool_use block
- `content_block_delta` - Incremental content (`text_delta` or `input_json_delta`)
- `content_block_stop` - Block finished
- `message_stop` - Message complete

**Headers:**
- `x-api-key: {api_key}`
- `anthropic-version: 2023-06-01`

---

## Configuration Examples

### config.json - Single Provider

```json
{
    "provider": {
        "type": "anthropic",
        "api_key_env": "ANTHROPIC_API_KEY"
    },
    "default_model": "claude-sonnet-4-20250514"
}
```

### config.json - Multi-Provider

```json
{
    "providers": {
        "openrouter": {
            "type": "openrouter",
            "api_key_env": "OPENROUTER_API_KEY"
        },
        "anthropic": {
            "type": "anthropic",
            "api_key_env": "ANTHROPIC_API_KEY"
        },
        "local": {
            "type": "ollama",
            "base_url": "http://localhost:11434/v1"
        }
    },
    "default_provider": "openrouter",
    "models": {
        "haiku": {
            "id": "anthropic/claude-haiku-4.5",
            "context_window": 200000
        },
        "haiku-native": {
            "id": "claude-haiku-4.5-20250514",
            "provider": "anthropic",
            "context_window": 200000
        },
        "llama": {
            "id": "llama3.2",
            "provider": "local",
            "context_window": 128000
        }
    },
    "default_model": "haiku"
}
```

### Azure Configuration

```json
{
    "provider": {
        "type": "azure",
        "base_url": "https://my-resource.openai.azure.com",
        "api_key_env": "AZURE_OPENAI_KEY",
        "deployment": "gpt-4",
        "api_version": "2024-02-01"
    }
}
```

---

## Usage Examples

### Basic Completion

```python
from nexus3.provider import create_provider
from nexus3.config.schema import ProviderConfig
from nexus3.core.types import Message, Role

config = ProviderConfig(type="anthropic")
provider = create_provider(config, "claude-sonnet-4-20250514")

response = await provider.complete([
    Message(role=Role.USER, content="What is the capital of France?")
])
print(response.content)

# Clean up
await provider.aclose()
```

### Streaming

```python
from nexus3.core.types import ContentDelta, ToolCallStarted, StreamComplete

messages = [Message(role=Role.USER, content="Write a haiku about Python")]

async for event in provider.stream(messages):
    match event:
        case ContentDelta(text=t):
            print(t, end="", flush=True)
        case ToolCallStarted(name=name):
            print(f"\n[Tool: {name}]")
        case StreamComplete(message=msg):
            print(f"\n\nDone. Tool calls: {len(msg.tool_calls)}")
```

### Tool Calling Loop

```python
tools = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get current weather for a location",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City name"}
            },
            "required": ["location"]
        }
    }
}]

messages = [Message(role=Role.USER, content="What's the weather in Paris?")]

while True:
    response = await provider.complete(messages, tools)
    messages.append(response)

    if not response.tool_calls:
        break

    for tc in response.tool_calls:
        # Execute tool
        result = await execute_tool(tc.name, tc.arguments)
        messages.append(Message(
            role=Role.TOOL,
            content=str(result),
            tool_call_id=tc.id
        ))

print(response.content)
```

### Raw API Logging

```python
from nexus3.core.interfaces import RawLogCallback

class MyLogger:
    def on_request(self, endpoint: str, payload: dict) -> None:
        print(f"REQUEST to {endpoint}")
        print(f"  Model: {payload.get('model')}")
        print(f"  Messages: {len(payload.get('messages', []))}")

    def on_response(self, status: int, body: dict) -> None:
        print(f"RESPONSE {status}")
        usage = body.get("usage", {})
        print(f"  Tokens: {usage.get('total_tokens', 'N/A')}")

    def on_chunk(self, chunk: dict) -> None:
        # Called for each SSE chunk during streaming
        pass

logger = MyLogger()
provider = create_provider(config, model_id, raw_log=logger)

# Or set later
provider.set_raw_log_callback(logger)

# Or via registry
registry.set_raw_log_callback(logger)
```

### Multi-Provider with Registry

```python
from nexus3.provider.registry import ProviderRegistry
from nexus3.config.loader import load_config

config = load_config()
registry = ProviderRegistry(config)

# Use default model
provider = registry.get_for_model()

# Use specific model alias
haiku = registry.get_for_model("haiku")

# Use specific provider/model directly
openai = registry.get("openai", "gpt-4o")

# With reasoning enabled
grok = registry.get("openrouter", "x-ai/grok-2", reasoning=True)

# Shutdown
await registry.aclose()
```

---

## Security Features

### SSRF Protection

The `validate_base_url()` function prevents SSRF attacks:

- **HTTPS:** Always allowed
- **HTTP localhost/127.0.0.1/::1:** Allowed (local development)
- **HTTP other hosts:** Rejected unless `allow_insecure_http=True`
- **Other schemes (file://, ftp://):** Always rejected

```python
# This raises ProviderError
config = ProviderConfig(
    type="openai",
    base_url="http://internal-server/v1"  # Non-localhost HTTP blocked
)

# Explicitly allow (NOT recommended for production)
config = ProviderConfig(
    type="openai",
    base_url="http://internal-server/v1",
    allow_insecure_http=True
)
```

### Error Body Size Limits

To prevent memory exhaustion from malicious or buggy providers, error response bodies are capped at 10KB:

```python
MAX_ERROR_BODY_SIZE = 10 * 1024  # 10 KB
```

### API Key Security

- Keys read from environment variables (never stored in config files)
- Keys only sent via appropriate auth header per provider
- Missing required API key raises `ProviderError` at provider creation

---

## Dependencies

| Module | Usage |
|--------|-------|
| `nexus3.core.types` | `Message`, `Role`, `ToolCall`, `StreamEvent` types |
| `nexus3.core.interfaces` | `AsyncProvider`, `RawLogCallback` protocols |
| `nexus3.core.errors` | `ProviderError`, `ConfigError` |
| `nexus3.config.schema` | `ProviderConfig`, `AuthMethod` |
| `httpx` | Async HTTP client |

---

## Adding a New Provider

1. **Create provider class** inheriting from `BaseProvider` or `OpenAICompatProvider`:

```python
# nexus3/provider/my_provider.py
from nexus3.provider.base import BaseProvider

class MyProvider(BaseProvider):
    def _build_endpoint(self, stream: bool = False) -> str:
        return f"{self._base_url}/my/endpoint"

    def _build_request_body(self, messages, tools, stream) -> dict:
        # Convert to provider-specific format
        ...

    def _parse_response(self, data) -> Message:
        # Parse provider response to Message
        ...

    async def _parse_stream(self, response) -> AsyncIterator[StreamEvent]:
        # Parse SSE stream to events
        ...
```

2. **Add to factory** in `__init__.py`:

```python
if provider_type == "myprovider":
    from nexus3.provider.my_provider import MyProvider
    return MyProvider(config, model_id, raw_log, reasoning)
```

3. **Add defaults** to `PROVIDER_DEFAULTS`:

```python
PROVIDER_DEFAULTS["myprovider"] = {
    "base_url": "https://api.myprovider.com/v1",
    "api_key_env": "MYPROVIDER_API_KEY",
    "auth_method": AuthMethod.BEARER,
}
```

4. **Update documentation** (this README, CLAUDE.md).

---

## Error Handling

| Error | Cause | Behavior |
|-------|-------|----------|
| `ProviderError("API key not found...")` | Missing env var | Raised at provider creation |
| `ProviderError("Authentication failed")` | 401 response | Immediate failure |
| `ProviderError("Access forbidden")` | 403 response | Immediate failure |
| `ProviderError("API endpoint not found")` | 404 response | Immediate failure |
| `ProviderError("API request failed (429/5xx)")` | Rate limit/server error | Retry with backoff |
| `ProviderError("Failed to connect")` | Network error | Retry with backoff |
| `ProviderError("Request timed out")` | Timeout | Retry with backoff |
| `ConfigError("Unknown provider type")` | Invalid `type` | Raised by factory |

---

Last updated: 2026-01-21
