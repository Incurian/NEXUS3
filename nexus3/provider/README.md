# NEXUS3 Provider Module

LLM provider implementations for NEXUS3. Unified `AsyncProvider` interface for OpenAI-compatible APIs, Anthropic native, Azure OpenAI, and local servers (Ollama, vLLM). Supports streaming, tools, retries, reasoning, and raw logging.

## Purpose

Abstracts LLM API differences (endpoints, auth, formats) behind `create_provider()` factory and `ProviderRegistry`. Enables seamless switching between providers/models in NEXUS3 agents.

**Supported Providers:**
- `openrouter` (default), `openai`, `ollama`, `vllm`: OpenAI `/v1/chat/completions`
- `azure`: Azure OpenAI deployments
- `anthropic`: Native `/v1/messages` (tools via content blocks)

**Defaults:** `PROVIDER_DEFAULTS` dict with base_url, api_key_env, auth_method.

## Key Classes/Functions

| Component | Description |
|-----------|-------------|
| `create_provider(config, model_id)` | Factory: dispatches by `config.type` |
| `ProviderRegistry(config)` | Lazy multi-provider cache: `get(provider_name, model_id)`, `get_for_model(alias)` |
| `BaseProvider` (ABC) | HTTP (httpx), auth, retries (3x on 429/5xx), `complete()`, `stream()` |
| `OpenAICompatProvider` | OpenAI format: messages, tools, streaming deltas, reasoning |
| `AzureOpenAIProvider` | Extends compat: deployment/api-version |
| `AnthropicProvider` | Native: content blocks, tool_use/result |

## Usage Examples

### 1. Factory
```python
from nexus3.provider import create_provider
from nexus3.config.schema import ProviderConfig
from nexus3.core.types import Message, Role

config = ProviderConfig(type="anthropic")
provider = create_provider(config, "claude-3.5-sonnet-20240620")

msg = await provider.complete([Message(role=Role.USER, content="Hello")])
print(msg.content)
```

### 2. Registry (Multi-Model)
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
        result = await execute_tool(tc)  # impl
        messages.append(Message(role=Role.TOOL, content=str(result), tool_call_id=tc.id))
```

## Config Example (config.json)
```json
{
  "providers": {
    "openrouter": {"type": "openrouter", "api_key_env": "OPENROUTER_API_KEY"},
    "anthropic": {"type": "anthropic", "api_key_env": "ANTHROPIC_API_KEY"}
  },
  "models": {
    "claude-sonnet": {"provider": "anthropic", "model_id": "claude-3.5-sonnet-20240620"}
  }
}
```

## Security/Features
- SSRF protection on `base_url`
- Error body size limits
- Exponential backoff retries + jitter
- Raw logging: `set_raw_log_callback()`

Last updated: 2026-01-17
