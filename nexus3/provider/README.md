# NEXUS3 Provider Module

LLM provider implementations for NEXUS3. This module provides a unified `AsyncProvider` interface
for interacting with various LLM APIs (OpenAI-compatible, Anthropic native, Azure, local servers).
Supports streaming, tool calling, retries, and raw logging.

## Purpose

Enables NEXUS3 agents to use any supported LLM backend via a single factory function (`create_provider`)
or registry (`ProviderRegistry`). Abstracts API differences in endpoints, auth, message formats,
tool calling, and streaming events.

Key features:
- Unified message format (`Message` from `nexus3.core.types`)
- Tool calling (OpenAI format, auto-converted for Anthropic)
- Streaming with `StreamEvent` types (`ContentDelta`, `ToolCallStarted`, `StreamComplete`)
- Automatic retries with exponential backoff
- Lazy provider creation via registry
- Raw API logging callbacks

## Supported Providers

| Type       | Service/Base                  | Auth Header     | Endpoint Path                  | Local? |
|------------|-------------------------------|-----------------|-------------------------------|--------|
| `openrouter` | OpenRouter.ai (default)     | `Bearer`        | `/v1/chat/completions`         | No     |
| `openai`     | OpenAI API                   | `Bearer`        | `/v1/chat/completions`         | No     |
| `azure`      | Azure OpenAI                 | `api-key`       | `/openai/deployments/{dep}/chat/completions` | No |
| `anthropic`  | Anthropic Claude             | `x-api-key`     | `/v1/messages`                 | No     |
| `ollama`     | Ollama local server          | None            | `/v1/chat/completions`         | Yes    |
| `vllm`       | vLLM OpenAI-compatible       | None            | `/v1/chat/completions`         | Yes    |

**Defaults** (from `PROVIDER_DEFAULTS`):
```python
{
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY", "auth_method": "bearer"},
    "openai":     {"base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY", "auth_method": "bearer"},
    "azure":      {"api_key_env": "AZURE_OPENAI_KEY", "auth_method": "api-key", "api_version": "2024-02-01"},
    "anthropic":  {"base_url": "https://api.anthropic.com", "api_key_env": "ANTHROPIC_API_KEY", "auth_method": "x-api-key"},
    "ollama":     {"base_url": "http://localhost:11434/v1", "auth_method": "none"},
    "vllm":       {"base_url": "http://localhost:8000/v1", "auth_method": "none"},
}
```

## Key Classes, Functions & Modules

| Module/File       | Key Components |
|-------------------|----------------|
| `__init__.py`     | `create_provider(config: ProviderConfig, model_id: str, ...) -> AsyncProvider`<br>`PROVIDER_DEFAULTS`<br>Exports: `OpenRouterProvider`, `ProviderRegistry` |
| `base.py`         | `BaseProvider` (ABC): Shared HTTP client, auth, retries, `_make_request`, `complete()`, `stream()` |
| `openai_compat.py`| `OpenAICompatProvider`: OpenAI `/chat/completions` format, tool calls, reasoning deltas |
| `azure.py`        | `AzureOpenAIProvider(OpenAICompatProvider)`: Azure endpoint/deployment formatting |
| `anthropic.py`    | `AnthropicProvider(BaseProvider)`: Native Messages API, content blocks, tool_use/tool_result |
| `registry.py`     | `ProviderRegistry`: Lazy multi-provider cache by `provider_name:model_id` |

## Architecture Summary

```
Config → create_provider(type) ─┐
                               ├─ BaseProvider (HTTP, retries, logging)
                               ├─ OpenAICompatProvider → openrouter/openai/ollama/vllm
                               ├─ AzureOpenAIProvider ─→ azure
                               └─ AnthropicProvider ───→ anthropic

ProviderRegistry(config) ─→ get(provider_name, model_id) → cached providers
```

1. **BaseProvider**: Abstracts HTTP (httpx), auth (`AuthMethod`), retries (429/5xx, backoff), timeouts.
2. **Specific Providers**: Override `_build_endpoint()`, `_build_request_body()`, `_parse_response()`, `_parse_stream()`.
3. **Factory (`__init__.py`)**: Dispatches by `config.type`, applies defaults.
4. **Registry**: Lazy init/cache for multi-model setups (e.g., `config.providers["openrouter"]`, `config.providers["anthropic"]`).
5. **Unified Interface**: `await provider.complete(messages, tools)` or `await provider.stream(...)`.

## Dependencies

**External:**
- `httpx` (async HTTP client)

**Internal:**
- `nexus3.config.schema` (`ProviderConfig`, `AuthMethod`)
- `nexus3.core.types` (`Message`, `StreamEvent`, `ToolCall`, etc.)
- `nexus3.core.errors` (`ProviderError`, `ConfigError`)
- `nexus3.core.interfaces` (`AsyncProvider`, `RawLogCallback`)

## Usage Examples

### 1. Factory (Single Provider)

```python
from nexus3.provider import create_provider
from nexus3.config.schema import ProviderConfig
from nexus3.core.types import Message, Role

config = ProviderConfig(type="openrouter")  # Default model via config.model
provider = create_provider(config, model_id="anthropic/claude-3.5-sonnet@20240620")

msg = await provider.complete([Message(role=Role.USER, content="Hello!")])
print(msg.content)
```

### 2. Streaming

```python
async for event in provider.stream([Message(role=Role.USER, content="Write code")], tools=[...]):
    match event:
        case ContentDelta(text=t): print(t, end="")
        case ToolCallStarted(index=i, id=tc_id, name=tc_name):
            print(f"\n[Tool: {tc_name}]")
        case StreamComplete(message=m):
            print("\nDone:", m.tool_calls)
```

### 3. ProviderRegistry (Multi-Model)

```python
from nexus3.provider.registry import ProviderRegistry
from nexus3.config.schema import Config  # Full config with providers/models

config = Config(...)  # Loaded from config.json
registry = ProviderRegistry(config)

# Default model
provider = registry.get_for_model()
response = await provider.complete(...)

# Specific model (resolves via config.resolve_model("haiku"))
provider = registry.get_for_model("haiku")
```

### 4. Tool Calling Loop

```python
tools = [{"type": "function", "function": {"name": "calc", "parameters": {...}}}]
messages = [Message(role=Role.USER, content="What is 2+2?")]

while True:
    msg = await provider.complete(messages, tools)
    messages.append(msg)
    if not msg.tool_calls:
        break
    for tc in msg.tool_calls:
        result = await execute_tool(tc.name, tc.arguments)  # Your impl
        messages.append(Message(role=Role.TOOL, content=str(result), tool_call_id=tc.id))
```

### 5. Raw Logging

```python
class Logger:
    def on_request(self, url: str, body: dict) -> None: print(f"→ {url}")
    def on_response(self, status: int, data: dict) -> None: print(f"← {status}")
    def on_chunk(self, chunk: dict) -> None: pass

provider = create_provider(config, raw_log=Logger())
# Or: registry.set_raw_log_callback(Logger())
```

## Configuration

See `ProviderConfig` fields in `nexus3.config.schema`. Key fields:
- `type: str` (required)
- `model: str` (passed separately to factory)
- `api_key_env: str`
- `base_url: str`
- `auth_method: AuthMethod`
- `request_timeout: float = 120.0`
- `max_retries: int = 3`
- `retry_backoff: float = 1.5`
- `extra_headers: dict`
- `deployment, api_version` (Azure-only)

**Full config.json example:**
```json
{
  "default_model": "claude-sonnet",
  "providers": {
    "openrouter": {"type": "openrouter", "api_key_env": "OPENROUTER_API_KEY"},
    "anthropic": {"type": "anthropic", "api_key_env": "ANTHROPIC_API_KEY"}
  },
  "models": {
    "claude-sonnet": {"provider": "openrouter", "model_id": "anthropic/claude-3.5-sonnet@20240620"}
  }
}
```

## Adding New Providers

1. Subclass `BaseProvider` or `OpenAICompatProvider`.
2. Implement 4 abstract methods.
3. Add to `create_provider()` if-block in `__init__.py`.
4. Add defaults to `PROVIDER_DEFAULTS`.
5. Document in README.

## Error Handling & Retries

- **Retries**: 3 attempts on 429/5xx, connect/timeout. Backoff: `(backoff^attempt) + jitter`, max 10s.
- **Immediate Fail**: 4xx (401 auth, 403 perms, 404 endpoint, 400 bad req).
- **Custom Errors**: `ProviderError` wraps API details.

Last updated: 2026-01-15
