# Plan: Prompt Caching (Multi-Provider)

## OPEN QUESTIONS - RESOLVED

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| **Q1** | Track cumulative cache savings? | **A) Per-request** | Simpler, no session state needed |
| **Q2** | Enable by default? | **B) On by default** | OpenAI/Azure automatic anyway, Anthropic benefits immediately |
| **Q3** | Show cache metrics? | **A) Logs only** | Avoid console clutter, use `-v` to see |
| **Q4** | Cache tool definitions? | **A) System only** | Simpler, tools change more often |

---

## Validation Notes (2026-02-01)

All code locations verified by explorer agents:

| Component | Plan Line | Actual Line | Status |
|-----------|-----------|-------------|--------|
| Anthropic `_build_request_body()` | ~136-153 | 119-158 | ✅ Verified |
| Anthropic `_parse_response()` | (not specified) | 271-312 | ✅ Verified |
| Anthropic streaming | (not specified) | 314-448 | ✅ `message_start` needs adding |
| OpenAI-compat `_parse_response()` | ~158-169 | 191-222 | ✅ Verified |
| OpenAI-compat `_build_request_body()` | ~96 | 96-125 | ✅ Verified |
| ProviderConfig | ~140 | 95-154 | ✅ Add after line 137 |

**Backwards Compatibility**: Confirmed safe - all response parsing uses `.get()` with defaults.

**User Impact**: Zero action required - Pydantic defaults handle missing config field.

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

**File:** `nexus3/config/schema.py` (add to ProviderConfig class after line 137, before SSL settings)

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

**Update `_build_request_body()` (lines 119-158, system assignment at 152-153):**

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

**Update `_parse_response()` (lines 271-312) to log cache metrics:**

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

**Update streaming handler `_parse_stream()` (lines 314-448) - add `message_start` event handler:**

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

OpenAI caching is automatic - just parse the response metrics.

**Update `_parse_response()` (lines 191-222) - insert before return:**

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

For OpenRouter routing to Anthropic models, add cache_control.

**Add `_is_openrouter_anthropic()` method (after `_message_to_dict()` ~line 159):**

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
- [x] **P1.1** Add `prompt_caching: bool = True` to ProviderConfig

### Phase 2: Anthropic
- [x] **P2.1** Add cache_control to system prompt in `_build_request_body()`
- [x] **P2.2** Parse `cache_creation_input_tokens` and `cache_read_input_tokens`
- [x] **P2.3** Log cache metrics at DEBUG level when non-zero
- [x] **P2.4** Handle streaming (`message_start` event has usage)

### Phase 3: OpenAI/Azure
- [x] **P3.1** Parse `prompt_tokens_details.cached_tokens` from response
- [x] **P3.2** Log cache metrics at DEBUG level when non-zero

### Phase 4: OpenRouter
- [x] **P4.1** Add `_is_openrouter_anthropic()` using `config.type` (NOT URL)
- [x] **P4.2** Add cache_control for Anthropic models via OpenRouter
- [x] **P4.3** Let OpenAI models use automatic caching

### Phase 5: Testing
- [x] **P5.1** Unit test: Anthropic cache_control injection when enabled
- [x] **P5.2** Unit test: Anthropic cache_control NOT injected when disabled
- [x] **P5.3** Unit test: OpenAI cached_tokens parsing (present)
- [x] **P5.4** Unit test: OpenAI cached_tokens parsing (missing - backwards compat)
- [x] **P5.5** Unit test: OpenRouter Anthropic detection (positive)
- [x] **P5.6** Unit test: OpenRouter Anthropic detection (negative - OpenAI model)
- [x] **P5.7** Live test: Anthropic native with caching
- [x] **P5.8** Live test: OpenRouter to Anthropic

### Phase 6: Documentation
- [x] **P6.1** Update CLAUDE.md Provider Configuration section
- [x] **P6.2** Document provider-specific caching behavior

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
