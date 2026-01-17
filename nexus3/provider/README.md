# NEXUS3 Provider Module

LLM provider implementations for NEXUS3. Unified `AsyncProvider` interface for OpenAI-compatible APIs (OpenRouter, OpenAI, Ollama, vLLM), Anthropic native, Azure OpenAI. Supports streaming, tools, retries, reasoning, raw logging.

## Purpose

Abstracts LLM API differences behind `create_provider()` factory and `ProviderRegistry`. Enables model/provider switching in NEXUS3 agents.

**Supported:** `openrouter` (default), `openai`, `ollama`, `vllm` (OpenAI `/v1/chat/completions`); `azure` (deployments); `anthropic` (native `/v1/messages`).

**Defaults:** `PROVIDER_DEFAULTS` dict (base_url, api_key_env, auth_method).

## Key Classes/Functions

| Component | Description |
|-----------|-------------|
| `create_provider(config, model_id)` | Factory by `config.type` |
| `ProviderRegistry(config)` | Lazy cache: `get(provider, model)`, `get_for_model(alias)` |
| `BaseProvider` (ABC) | HTTP, auth, retries (3x 429/5xx), `complete()`, `stream()` |
| `OpenAICompatProvider` | OpenAI format (OpenRouter/OpenAI/Ollama/vLLM), reasoning |
| `AzureOpenAIProvider` | Extends compat: deployment/api-version |
| `AnthropicProvider` | Native: content blocks, tool_use/result |
| `OpenRouterProvider` | Alias for `OpenAICompatProvider` |

**Exports:** `create_provider`, `OpenRouterProvider`, `ProviderRegistry`, `PROVIDER_DEFAULTS`.

## Usage Examples

### 1. Factory
```python
from nexus3.provider import create_provider
from nexus3.config.schema import ProviderConfig
from nexus3.core.types import Message, Role

config = ProviderConfig(type="anthropic")
provider = create_provider(config, "claude-sonnet-4-20250514")

msg = await provider.complete([Message(role=Role.USER, content="Hello")])
print(msg.content)
```

### 2. Registry
```python
from nexus3.provider.registry import ProviderRegistry
from nexus3.config.schema import Config

config = Config(...)  # from config.json
registry = ProviderRegistry(config)
provider = registry.get_for_model("claude-sonnet")  # resolves via config
await registry.aclose()
```

### 3. Streaming + Tools
```python
tools = [{"type": "function", "function": {"name": "get_weather", "parameters": {...}}}]

async for event in provider.stream(messages, tools):
    match event:
        case ContentDelta(text=t): print(t, end="")
        case ToolCallStarted(id=id_, name=name): print(f"\nTool: {name}")
        case StreamComplete(msg): print(msg.tool_calls)
```

### 4. Tool Loop
```python
messages = [Message(role=Role.USER, content="Weather in SF?")]
while True:
    msg = await provider.complete(messages, tools)
    messages.append(msg)
    if not msg.tool_calls: break
    for tc in msg.tool_calls:
        result = await execute_tool(tc)
        messages.append(Message(role=Role.TOOL, content=str(result), tool_call_id=tc.id))
```

## Config Example (config.json)
```json
{
  "providers": {
    "openrouter": {"type": "openrouter"},
    "anthropic": {"type": "anthropic"}
  },
  "models": {
    "claude-sonnet": {"provider": "anthropic", "model_id": "claude-sonnet-4-20250514"}
  }
}
```

## Features
- SSRF protection, error body limits
- Exponential backoff retries + jitter
- Raw logging: `set_raw_log_callback()`

Last updated: 2026-01-17 10:01
