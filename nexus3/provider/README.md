# NEXUS3 Provider Module

LLM provider implementations for NEXUS3 with unified async interface, multi-provider support, streaming, tool calling, prompt caching, retries, and security hardening.

## Overview

This module abstracts LLM API differences behind a common `AsyncProvider` protocol. The `create_provider()` factory instantiates the appropriate provider class based on configuration, while `ProviderRegistry` manages multiple providers with lazy initialization and caching.

## Supported Providers

| Type | API Format | Endpoint | Auth Method | Prompt Caching |
|------|------------|----------|-------------|----------------|
| `openrouter` | OpenAI-compatible | `/v1/chat/completions` | Bearer token | Pass-through (Anthropic models) |
| `openai` | OpenAI-compatible | `/v1/chat/completions` | Bearer token | Automatic |
| `azure` | OpenAI-compatible | `/openai/deployments/{name}/chat/completions` | api-key header | Automatic |
| `anthropic` | Native Anthropic | `/v1/messages` | x-api-key header | Full support |
| `ollama` | OpenAI-compatible | `/v1/chat/completions` | None | N/A (local) |
| `vllm` | OpenAI-compatible | `/v1/chat/completions` | None | N/A (local) |

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

# Enable reasoning for a provider (explicit)
provider = registry.get("openrouter", "x-ai/grok-2", reasoning=True)

# get_for_model() auto-resolves reasoning from ModelConfig.reasoning
provider = registry.get_for_model("grok")  # reasoning comes from model config

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
| **Extra Headers** | Supports custom headers via `extra_headers` config |
| **SSRF Protection** | Validates `base_url` - HTTPS required for non-localhost hosts |
| **Retry Logic** | Exponential backoff with jitter for 429/5xx errors |
| **Timeout Handling** | Configurable request timeout (default 120s) |
| **Error Body Limits** | Caps error response bodies at 10KB to prevent memory exhaustion |
| **Connection Reuse** | Lazy httpx client with persistent connections |
| **SSL Configuration** | Custom CA certs and SSL verification control for on-prem deployments |
| **Windows SSL Fallback** | Falls back to system certificate store if certifi bundle is missing/corrupted |
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
    deployment="gpt-4",          # Deployment name (falls back to model if not set)
    api_version="2024-02-01",    # API version (default)
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
- Requires `max_tokens` parameter (default: 4096)

**Prompt Caching:**
When `prompt_caching` is enabled (default), the system prompt is sent with `cache_control`:
```python
# System prompt with caching enabled
{
    "system": [
        {
            "type": "text",
            "text": "<system prompt content>",
            "cache_control": {"type": "ephemeral"}
        }
    ]
}
```

Cache metrics are logged at DEBUG level when present in the response:
```
Cache: created=1500, read=0 tokens
```

**Orphaned Tool Use Handling:**
The provider synthesizes missing `tool_result` blocks for orphaned `tool_use` blocks (e.g., from cancellation or crash):
```python
# Automatically synthesized for tool calls without results
{
    "type": "tool_result",
    "tool_use_id": "<orphaned_id>",
    "content": "[Tool execution was interrupted]"
}
```

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
- `message_start` - Initial metadata (includes cache metrics in `usage`)
- `content_block_start` - New text or tool_use block
- `content_block_delta` - Incremental content (`text_delta` or `input_json_delta`)
- `content_block_stop` - Block finished
- `message_delta` - Message-level updates (stop_reason)
- `message_stop` - Message complete

**Headers:**
- `x-api-key: {api_key}`
- `anthropic-version: 2023-06-01`

---

## Configuration Examples

### config.json - Single Provider

```json
{
    "providers": {
        "anthropic": {
            "type": "anthropic",
            "api_key_env": "ANTHROPIC_API_KEY",
            "models": {
                "sonnet": {
                    "id": "claude-sonnet-4-20250514",
                    "context_window": 200000
                }
            }
        }
    },
    "default_model": "sonnet"
}
```

### config.json - Multi-Provider

Models are nested inside their provider configuration. The `default_model` references a model alias, which must be globally unique across all providers.

```json
{
    "providers": {
        "openrouter": {
            "type": "openrouter",
            "api_key_env": "OPENROUTER_API_KEY",
            "models": {
                "haiku": {
                    "id": "anthropic/claude-haiku-4.5",
                    "context_window": 200000
                }
            }
        },
        "anthropic": {
            "type": "anthropic",
            "api_key_env": "ANTHROPIC_API_KEY",
            "models": {
                "haiku-native": {
                    "id": "claude-haiku-4-5",
                    "context_window": 200000
                }
            }
        },
        "local": {
            "type": "ollama",
            "base_url": "http://localhost:11434/v1",
            "models": {
                "llama": {
                    "id": "llama3.2",
                    "context_window": 128000
                }
            }
        }
    },
    "default_model": "haiku"
}
```

### ModelConfig Fields

Each model entry within a provider's `models` dict supports:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | `str` | (required) | Full model identifier sent to the API |
| `context_window` | `int` | `131072` | Context window size in tokens |
| `reasoning` | `bool` | `false` | Enable extended thinking/reasoning |
| `guidance` | `str \| null` | `null` | Brief usage guidance (shown in model selection UI) |

### Disabling Prompt Caching

Prompt caching is enabled by default. To disable for a specific provider:

```json
{
    "providers": {
        "anthropic": {
            "type": "anthropic",
            "api_key_env": "ANTHROPIC_API_KEY",
            "prompt_caching": false,
            "models": {
                "sonnet": { "id": "claude-sonnet-4-20250514", "context_window": 200000 }
            }
        }
    }
}
```

### Azure Configuration

```json
{
    "providers": {
        "azure": {
            "type": "azure",
            "base_url": "https://my-resource.openai.azure.com",
            "api_key_env": "AZURE_OPENAI_KEY",
            "deployment": "gpt-4",
            "api_version": "2024-02-01",
            "models": {
                "gpt4": {
                    "id": "gpt-4",
                    "context_window": 128000
                }
            }
        }
    },
    "default_model": "gpt4"
}
```

### On-Premise / Corporate SSL Configuration

For deployments with custom CA certificates or self-signed certs:

```json
{
    "providers": {
        "corp": {
            "type": "openai",
            "base_url": "https://internal-llm.corp.example.com/v1",
            "api_key_env": "CORP_LLM_API_KEY",
            "ssl_ca_cert": "/etc/ssl/certs/corp-ca.pem",
            "verify_ssl": true,
            "models": {
                "corp-llm": { "id": "llama-3-70b", "context_window": 8192 }
            }
        }
    }
}
```

To disable SSL verification (not recommended for production):

```json
{
    "providers": {
        "dev": {
            "type": "openai",
            "base_url": "https://dev-server.local/v1",
            "verify_ssl": false,
            "models": {
                "dev-llm": { "id": "llama-3-70b", "context_window": 8192 }
            }
        }
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
from nexus3.core.types import ContentDelta, ReasoningDelta, ToolCallStarted, StreamComplete

messages = [Message(role=Role.USER, content="Write a haiku about Python")]

async for event in provider.stream(messages):
    match event:
        case ContentDelta(text=t):
            print(t, end="", flush=True)
        case ReasoningDelta(text=t):
            print(f"[thinking: {t}]", end="", flush=True)
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

## Prompt Caching

Prompt caching reduces costs by caching static portions of prompts (primarily the system prompt) for reuse across requests. NEXUS3 supports prompt caching across multiple providers.

### Provider Support

| Provider | Status | How It Works |
|----------|--------|--------------|
| Anthropic | Full | `cache_control: {"type": "ephemeral"}` on system prompt |
| OpenAI | Automatic | Built-in caching, no special configuration needed |
| Azure | Automatic | Same as OpenAI |
| OpenRouter | Pass-through | Forwards `cache_control` for Anthropic models |
| Ollama/vLLM | N/A | Local providers, no caching needed |

### Cost Savings

Prompt caching typically provides ~90% cost reduction on cached tokens:
- **Anthropic**: Cache writes at 1.25x input token cost, cache reads at 0.1x
- **OpenAI**: Automatic caching with 50% discount on cached tokens

### Configuration

Caching is **enabled by default**. To disable:

```json
{
    "providers": {
        "anthropic": {
            "type": "anthropic",
            "prompt_caching": false
        }
    }
}
```

### Cache Metrics

Cache hit/miss metrics are logged at DEBUG level (visible with `-v` flag):

```
DEBUG:nexus3.provider.anthropic:Cache: created=1500, read=0 tokens
DEBUG:nexus3.provider.openai_compat:Cache: read=2500 tokens
```

- `created` (Anthropic): Tokens written to cache this request
- `read`: Tokens read from cache (cache hit)

### OpenRouter + Anthropic

When using OpenRouter with Anthropic models (detected via `anthropic` in model name) and `prompt_caching` is enabled (default), NEXUS3 automatically adds `cache_control` to the system prompt. This is passed through to Anthropic's API for caching.

```python
# Automatic detection
if config.type == "openrouter" and "anthropic" in model.lower() and config.prompt_caching:
    # Add cache_control to system message
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
| `nexus3.core.constants` | `get_nexus_dir()` for API key error messages |
| `nexus3.config.schema` | `ProviderConfig`, `AuthMethod`, `Config` |
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

Last updated: 2026-02-10
