# Plan: Prompt Caching (Multi-Provider)

## OPEN QUESTIONS

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| **Q1** | Track cumulative cache savings? | A) No, per-request only B) Yes, session total | **A) Per-request** - simpler |
| **Q2** | Enable by default? | A) Off, opt-in B) On by default | **B) On by default** - OpenAI/Azure are automatic anyway |
| **Q3** | Show cache metrics? | A) Verbose logs only B) Add to /status | **A) Logs only** - avoid clutter |
| **Q4** | Cache tool definitions? | A) System prompt only B) System + tools | **A) System only** - simpler |

---

## Provider Caching Support Summary

| Provider | Status | Config Required | Implementation |
|----------|--------|-----------------|----------------|
| **Anthropic** | Full support | Explicit `cache_control` | Must add blocks |
| **OpenAI** | Full support | None (automatic) | Just parse response |
| **Azure OpenAI** | Full support | None (automatic) | Just parse response |
| **OpenRouter** | Pass-through | Varies by model | Depends on underlying provider |
| **Ollama** | No support | N/A | Local, no caching API |
| **vLLM** | No support | N/A | Self-hosted, no caching |

---

## Overview

Enable prompt caching across providers to reduce costs and latency. System prompt (NEXUS.md) is static across requests and benefits significantly from caching.

**Key insight:** OpenAI/Azure caching is automatic - we just need to parse metrics. Anthropic requires explicit `cache_control` blocks. OpenRouter passes through to underlying provider.

---

## Scope

### Included (v1)
- **Anthropic:** Explicit cache_control on system prompt
- **OpenAI:** Parse `cached_tokens` from response usage
- **Azure:** Same as OpenAI
- **OpenRouter:** Pass-through (Anthropic models get cache_control)
- Config option per-provider
- Log cache metrics

### Deferred
- Tool definition caching (Anthropic supports up to 4 breakpoints)
- Session-level statistics
- Gemini cache object API (different paradigm)

---

## Backwards Compatibility (CRITICAL)

### Safe Patterns for Metric Parsing

All existing provider code uses `.get()` with defaults for optional fields. This pattern is **already safe** for older APIs:

```python
# This is safe - returns empty dict/0 if field missing
usage = data.get("usage", {})
prompt_details = usage.get("prompt_tokens_details", {})
cached_tokens = prompt_details.get("cached_tokens", 0)

if cached_tokens:  # Only log if non-zero
    logger.info("Cache: read=%d tokens", cached_tokens)
```

**No exceptions thrown** when fields are missing. Older API versions simply return 0.

### OpenRouter Detection (FIXED)

**Problem:** Original plan used URL parsing which is fragile:
```python
# BAD - breaks with staging URLs, corporate proxies, domain changes
"openrouter" in self._config.base_url.lower()
```

**Solution:** Use `config.type` which is explicitly set by user:
```python
# GOOD - uses explicit provider type from config
self._config.type == "openrouter"
```

---

## Implementation

### Phase 1: Config Schema

**File:** `nexus3/config/schema.py` (add to ProviderConfig class ~line 140)

```python
class ProviderConfig(BaseModel):
    # ... existing fields ...
    prompt_caching: bool = Field(
        default=True,
        description="Enable prompt caching. Required for Anthropic, automatic for OpenAI/Azure.",
    )
```

### Phase 2: Anthropic Provider

**File:** `nexus3/provider/anthropic.py`

**Update `_build_request_body()` (~line 136-153):**

```python
def _build_request_body(self, messages, tools, stream) -> dict:
    # ... existing code to extract system prompt ...

    if system:
        if self._config.prompt_caching:
            body["system"] = [{
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},  # 5-min TTL
            }]
        else:
            body["system"] = system
```

**Update `_parse_response()` to log cache metrics:**

```python
def _parse_response(self, data: dict[str, Any]) -> Message:
    # ... existing parsing ...

    # Extract cache metrics (safe - uses .get() with defaults)
    usage = data.get("usage", {})
    cache_creation = usage.get("cache_creation_input_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    if cache_creation or cache_read:
        logger.debug("Cache: created=%d, read=%d tokens", cache_creation, cache_read)

    return Message(...)
```

**Update streaming handler for `message_start` event:**

```python
elif event_type == "message_start":
    # Parse usage from message_start event
    message_data = data.get("message", {})
    usage = message_data.get("usage", {})
    cache_creation = usage.get("cache_creation_input_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    if cache_creation or cache_read:
        logger.debug("Cache: created=%d, read=%d tokens", cache_creation, cache_read)
```

### Phase 3: OpenAI-Compatible Provider

**File:** `nexus3/provider/openai_compat.py`

OpenAI caching is automatic - just parse the response metrics:

```python
def _parse_response(self, data: dict[str, Any]) -> Message:
    # ... existing parsing ...

    # Extract cache metrics (backwards compatible - uses .get() with defaults)
    usage = data.get("usage", {})
    prompt_details = usage.get("prompt_tokens_details", {})
    cached_tokens = prompt_details.get("cached_tokens", 0)
    if cached_tokens:
        logger.debug("Cache: read=%d tokens", cached_tokens)

    return Message(...)
```

### Phase 4: OpenRouter Pass-through

**File:** `nexus3/provider/openai_compat.py`

For OpenRouter routing to Anthropic models, add cache_control:

```python
def _is_openrouter_anthropic(self) -> bool:
    """Check if we're on OpenRouter routing to an Anthropic model.

    Uses config.type instead of URL parsing for robustness against
    URL changes, staging environments, and corporate proxies.
    """
    return (
        self._config.type == "openrouter" and
        "anthropic" in self._model.lower()
    )

def _build_request_body(self, messages, tools, stream) -> dict:
    # ... existing code ...

    # OpenRouter + Anthropic model = need cache_control
    if self._is_openrouter_anthropic() and self._config.prompt_caching:
        # Find system message and add cache_control
        for msg in body.get("messages", []):
            if msg.get("role") == "system":
                content = msg.get("content", "")
                if isinstance(content, str):
                    msg["content"] = [{
                        "type": "text",
                        "text": content,
                        "cache_control": {"type": "ephemeral"},
                    }]
                break

    return body
```

---

## Provider-Specific Details

### Anthropic (Native)
- **Format:** `cache_control: {"type": "ephemeral"}` on content blocks
- **TTL:** 5 minutes (ephemeral)
- **Min tokens:** 1024-4096 depending on model
- **Cost:** Write 125%, Read 10%
- **Response:** `cache_creation_input_tokens`, `cache_read_input_tokens`

### OpenAI / Azure
- **Format:** Automatic, no config needed
- **TTL:** 5-10 min (OpenAI), 24h (Azure)
- **Min tokens:** 1024
- **Cost:** Not explicitly disclosed (Azure: 50%+ discount)
- **Response:** `usage.prompt_tokens_details.cached_tokens`

### OpenRouter
- **Anthropic models:** Pass through `cache_control` blocks
- **OpenAI models:** Automatic (transparent)
- **Other models:** Varies by provider

---

## Files to Modify

| File | Change |
|------|--------|
| `nexus3/config/schema.py` | Add `prompt_caching` field (default True) |
| `nexus3/provider/anthropic.py` | Add cache_control to system, parse metrics |
| `nexus3/provider/openai_compat.py` | Parse cached_tokens, OpenRouter Anthropic detection |

---

## Implementation Checklist

### Phase 1: Config
- [ ] **P1.1** Add `prompt_caching: bool = True` to ProviderConfig

### Phase 2: Anthropic
- [ ] **P2.1** Add cache_control to system prompt in `_build_request_body()`
- [ ] **P2.2** Parse `cache_creation_input_tokens` and `cache_read_input_tokens`
- [ ] **P2.3** Log cache metrics at DEBUG level when non-zero
- [ ] **P2.4** Handle streaming (`message_start` event has usage)

### Phase 3: OpenAI/Azure
- [ ] **P3.1** Parse `prompt_tokens_details.cached_tokens` from response
- [ ] **P3.2** Log cache metrics at DEBUG level when non-zero

### Phase 4: OpenRouter
- [ ] **P4.1** Add `_is_openrouter_anthropic()` using `config.type` (NOT URL)
- [ ] **P4.2** Add cache_control for Anthropic models via OpenRouter
- [ ] **P4.3** Let OpenAI models use automatic caching

### Phase 5: Testing
- [ ] **P5.1** Unit test: Anthropic cache_control injection when enabled
- [ ] **P5.2** Unit test: Anthropic cache_control NOT injected when disabled
- [ ] **P5.3** Unit test: OpenAI cached_tokens parsing (present)
- [ ] **P5.4** Unit test: OpenAI cached_tokens parsing (missing - backwards compat)
- [ ] **P5.5** Unit test: OpenRouter Anthropic detection (positive)
- [ ] **P5.6** Unit test: OpenRouter Anthropic detection (negative - OpenAI model)
- [ ] **P5.7** Live test: Anthropic native with caching
- [ ] **P5.8** Live test: OpenRouter to Anthropic

### Phase 6: Documentation
- [ ] **P6.1** Update CLAUDE.md Provider Configuration section
- [ ] **P6.2** Document provider-specific caching behavior

---

## Cost/Benefit Analysis

| Provider | System Prompt Size | Cache Hit Savings |
|----------|-------------------|-------------------|
| Anthropic | 10K tokens | 90% on reads (~$0.027 → $0.003/request) |
| OpenAI | 10K tokens | Not disclosed, but automatic |
| Azure | 10K tokens | 50%+ on cached tokens |

For a typical NEXUS3 session with 10K token system prompt and 50 requests:
- **Without caching:** ~$1.35 (Anthropic Sonnet @ $3/MTok input)
- **With caching:** ~$0.15 (90% savings on 49 cache reads)

---

## Effort Estimate

~2-3 hours implementation, ~1 hour testing.
