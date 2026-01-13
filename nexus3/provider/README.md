# Provider Module

LLM provider implementations for NEXUS3. Supports multiple backends via a unified `AsyncProvider` interface.

## Supported Providers

| Type | Description | Auth Method | Endpoint |
|------|-------------|-------------|----------|
| `openrouter` | OpenRouter.ai (default) | Bearer | `/v1/chat/completions` |
| `openai` | Direct OpenAI API | Bearer | `/v1/chat/completions` |
| `azure` | Azure OpenAI Service | api-key header | `/openai/deployments/{dep}/chat/completions` |
| `anthropic` | Anthropic Claude API | x-api-key header | `/v1/messages` |
| `ollama` | Local Ollama server | None | `/v1/chat/completions` |
| `vllm` | vLLM server | None | `/v1/chat/completions` |

## Files

| File | Description |
|------|-------------|
| `__init__.py` | Factory function, exports |
| `base.py` | `BaseProvider` with shared retry/HTTP logic |
| `openai_compat.py` | OpenAI-compatible (openrouter, openai, ollama, vllm) |
| `azure.py` | Azure OpenAI Service |
| `anthropic.py` | Anthropic Claude API |

## Quick Start

```python
from nexus3.provider import create_provider
from nexus3.config.schema import ProviderConfig

# OpenRouter (default)
config = ProviderConfig()
provider = create_provider(config)

# Anthropic
config = ProviderConfig(
    type="anthropic",
    api_key_env="ANTHROPIC_API_KEY",
    model="claude-sonnet-4-20250514",
)
provider = create_provider(config)

# Use the provider
response = await provider.complete(messages, tools)
async for event in provider.stream(messages, tools):
    ...
```

## Configuration Examples

### OpenRouter (default)

```json
{
  "provider": {
    "type": "openrouter",
    "api_key_env": "OPENROUTER_API_KEY",
    "model": "anthropic/claude-sonnet-4"
  }
}
```

### OpenAI Direct

```json
{
  "provider": {
    "type": "openai",
    "api_key_env": "OPENAI_API_KEY",
    "model": "gpt-4o",
    "base_url": "https://api.openai.com/v1"
  }
}
```

### Azure OpenAI

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

### Anthropic Native

```json
{
  "provider": {
    "type": "anthropic",
    "api_key_env": "ANTHROPIC_API_KEY",
    "model": "claude-sonnet-4-20250514",
    "base_url": "https://api.anthropic.com"
  }
}
```

### Ollama (local)

```json
{
  "provider": {
    "type": "ollama",
    "base_url": "http://localhost:11434/v1",
    "model": "llama3.2"
  }
}
```

### vLLM (local/remote)

```json
{
  "provider": {
    "type": "vllm",
    "base_url": "http://localhost:8000/v1",
    "model": "meta-llama/Llama-3.2-8B-Instruct"
  }
}
```

## ProviderConfig Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | str | `"openrouter"` | Provider type (see supported list) |
| `api_key_env` | str | `"OPENROUTER_API_KEY"` | Env var for API key |
| `model` | str | `"x-ai/grok-code-fast-1"` | Model ID |
| `base_url` | str | varies by type | API base URL |
| `context_window` | int | `131072` | Token limit for truncation |
| `reasoning` | bool | `False` | Enable extended thinking |
| `auth_method` | AuthMethod | `BEARER` | How to send API key |
| `extra_headers` | dict | `{}` | Additional HTTP headers |
| `api_version` | str\|None | `None` | API version (Azure) |
| `deployment` | str\|None | `None` | Deployment name (Azure) |

### AuthMethod Values

| Value | Header Format |
|-------|---------------|
| `bearer` | `Authorization: Bearer <key>` |
| `api-key` | `api-key: <key>` |
| `x-api-key` | `x-api-key: <key>` |
| `none` | No auth header |

## Streaming Events

All providers yield the same `StreamEvent` types:

| Event | Fields | Description |
|-------|--------|-------------|
| `ContentDelta` | `text: str` | Text content chunk |
| `ReasoningDelta` | `text: str` | Extended thinking (Grok/Claude) |
| `ToolCallStarted` | `index`, `id`, `name` | Tool call detected |
| `StreamComplete` | `message: Message` | Final message with all content + tool_calls |

```python
async for event in provider.stream(messages, tools):
    match event:
        case ContentDelta(text=t):
            print(t, end="")
        case ToolCallStarted(name=n):
            print(f"\n[Calling: {n}]")
        case StreamComplete(message=m):
            # m.tool_calls contains parsed ToolCall objects
            pass
```

## Tool Calling

Tools use OpenAI function format (converted automatically for Anthropic):

```python
tools = [{
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a file",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
            "required": ["path"]
        }
    }
}]

response = await provider.complete(messages, tools)
for tc in response.tool_calls:
    # tc.id, tc.name, tc.arguments (parsed dict)
    result = execute_tool(tc.name, tc.arguments)
    messages.append(Message(
        role=Role.TOOL,
        content=json.dumps(result),
        tool_call_id=tc.id,
    ))
```

## Retry Logic

All providers share retry behavior:

| Condition | Action |
|-----------|--------|
| 429, 500, 502, 503, 504 | Retry with backoff (max 3 attempts) |
| Connect/timeout error | Retry with backoff |
| 401, 403, 404, other 4xx | Fail immediately |

Backoff: `min(2^attempt + random(0,1), 10s)`

## Adding a New Provider

1. **Create provider file** (`nexus3/provider/my_provider.py`)

2. **Inherit from appropriate base:**
   - `OpenAICompatProvider` for OpenAI-compatible APIs
   - `BaseProvider` for different API formats

3. **Implement abstract methods:**
   ```python
   def _build_endpoint(self, stream: bool = False) -> str:
       """Return full API URL."""
       ...

   def _build_request_body(self, messages, tools, stream) -> dict:
       """Convert messages to provider format."""
       ...

   def _parse_response(self, data: dict) -> Message:
       """Parse response to Message."""
       ...

   async def _parse_stream(self, response) -> AsyncIterator[StreamEvent]:
       """Parse SSE stream to events."""
       ...
   ```

4. **Register in factory** (`__init__.py`):
   ```python
   if provider_type == "my_provider":
       from nexus3.provider.my_provider import MyProvider
       return MyProvider(config, raw_log)
   ```

5. **Add to PROVIDER_DEFAULTS:**
   ```python
   "my_provider": {
       "base_url": "https://api.example.com",
       "api_key_env": "MY_API_KEY",
       "auth_method": AuthMethod.BEARER,
   },
   ```

6. **Update this README** with configuration example

### Example: Custom OpenAI-Compatible Server

```python
# nexus3/provider/custom.py
from nexus3.provider.openai_compat import OpenAICompatProvider

class CustomProvider(OpenAICompatProvider):
    """Custom server with special endpoint."""

    def _build_endpoint(self, stream: bool = False) -> str:
        return f"{self._base_url}/custom/chat"

    def _build_headers(self) -> dict[str, str]:
        headers = super()._build_headers()
        headers["X-Custom-Header"] = "value"
        return headers
```

## Raw Logging

All providers support raw API logging via callback:

```python
class MyLogger:
    def on_request(self, endpoint: str, payload: dict) -> None:
        print(f"REQ: {endpoint}")

    def on_response(self, status: int, body: dict) -> None:
        print(f"RES: {status}")

    def on_chunk(self, chunk: dict) -> None:
        print(f"CHUNK: {chunk}")

provider = create_provider(config, raw_log=MyLogger())
# Or set later:
provider.set_raw_log_callback(MyLogger())
```

## Dependencies

**External:** `httpx`

**Internal:** `nexus3.config.schema.ProviderConfig`, `nexus3.core.types.*`, `nexus3.core.errors.ProviderError`
