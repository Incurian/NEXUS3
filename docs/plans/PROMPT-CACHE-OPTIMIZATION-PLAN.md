# Plan: Prompt Cache Optimization — Separate Dynamic Context from System Prompt

## Context

NEXUS3 injects dynamic content (datetime, git status, clipboard entries) INTO the system prompt string before every API call. The system prompt gets `cache_control: ephemeral` as a single block. Since the datetime changes every request, **the entire system prompt cache (~10-15K tokens) is invalidated on every API call**. This also invalidates caching for all conversation messages (Anthropic caching is prefix-based).

**Fix:** Make the system prompt purely static (always cacheable). Move dynamic content to the last user-facing message, where it naturally lives at the "edge" of the cached prefix.

## Design

### Before
```
[SYSTEM: static+datetime+git+clipboard, cache_control]  ← cache MISS (datetime changed)
[USER1, ASSISTANT1, USER2, ASSISTANT2, ...]              ← also uncached (prefix broken)
[USERN]                                                   ← new
```

### After
```
[SYSTEM: static only, cache_control: ephemeral]           ← cache HIT (never changes)
[USER1, ASSISTANT1, ..., USERN-1, cache_control]          ← cache HIT (prefix stable)
[USERN + <session-context>datetime/git/clipboard</session-context>]  ← new turn (small)
```

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| Dynamic context passed as `dynamic_context: str` through provider interface | Providers own format knowledge (Anthropic blocks vs OpenAI strings). Keeps ContextManager format-agnostic. |
| Injected as text block appended to last user message content | Works for both normal user messages and tool-result-bearing user messages. No extra messages that could break role alternation. |
| `<session-context>` XML wrapper | Clear boundary. Follows Claude Code's `<system-reminder>` precedent. |
| Second cache breakpoint on penultimate user message (Anthropic) | Caches the entire conversation history up to the previous turn. Anthropic supports up to 4 breakpoints. |
| New `"dynamic"` key in token usage dict | Clean accounting. Total tokens unchanged. |

## Files to Modify

| File | Changes |
|------|---------|
| `nexus3/context/manager.py` | Add `build_dynamic_context()`. Update `build_messages()` to use static prompt. Update `get_token_usage()` and both truncation methods to account for dynamic tokens separately. Remove `inject_datetime_into_prompt()` calls from main path. |
| `nexus3/core/interfaces.py` | Add `dynamic_context: str \| None = None` to `AsyncProvider.complete()` and `.stream()` |
| `nexus3/provider/base.py` | Add `dynamic_context` param to abstract `_build_request_body()`, `complete()`, `stream()` |
| `nexus3/provider/anthropic.py` | Add `_inject_dynamic_context()` and `_add_conversation_cache_breakpoint()`. Update `_build_request_body()`. |
| `nexus3/provider/openai_compat.py` | Add `_inject_dynamic_context()`. Update `_build_request_body()`. |
| `nexus3/session/session.py` | Pass `dynamic_context` at 3 `provider.stream()` call sites (lines 293, 376, 446) |
| Tests | Update context manager tests, add provider caching tests |

## Implementation Details

### `ContextManager.build_dynamic_context()` (new method)

```python
def build_dynamic_context(self) -> str | None:
    """Build volatile session context for injection at the conversation edge.

    Returns XML-wrapped string with datetime, git status, clipboard, or None.
    """
    parts: list[str] = []
    parts.append(get_current_datetime_str())
    if self._git_context:
        parts.append(self._git_context)
    if self._clipboard_manager and self._clipboard_config.inject_into_context:
        section = format_clipboard_context(...)
        if section:
            parts.append(section)
    return "<session-context>\n" + "\n\n".join(parts) + "\n</session-context>"
```

### Anthropic `_inject_dynamic_context()`

Searches backwards for last `role: user` message in converted Anthropic messages, appends a text block. Handles both list and string content. Falls back to creating a new user message if none found (edge case).

### Anthropic `_add_conversation_cache_breakpoint()`

Finds the second-to-last user message, adds `cache_control: ephemeral` to the last content block. This caches the entire conversation prefix through the previous turn. Skips if < 2 user messages.

### OpenAI-compat `_inject_dynamic_context()`

Searches backwards for last `role: user` message. If content is a string, appends `\n\n` + dynamic context. If content is a list (OpenRouter Anthropic passthrough), appends a text block. Falls back to adding a new user message.

### `get_token_usage()` update

```python
dynamic = self.build_dynamic_context()
dynamic_tokens = self._counter.count(dynamic) if dynamic else 0
# total = system + tools + messages + dynamic
# New "dynamic" key in returned dict
```

### Truncation updates (lines 693, 734)

Replace `self._build_system_prompt_for_api_call()` with static `self._system_prompt`. Subtract dynamic tokens from message budget alongside system and tools tokens.

## Checklist

### Phase 1: ContextManager (foundation)
- [ ] **P1.1** Add `build_dynamic_context()` method
- [ ] **P1.2** Update `build_messages()` — static system prompt only
- [ ] **P1.3** Update `get_token_usage()` — add "dynamic" key, use static prompt
- [ ] **P1.4** Update `_truncate_oldest_first()` and `_truncate_middle_out()` — static prompt + dynamic budget
- [ ] **P1.5** Clean up: remove `inject_datetime_into_prompt()` call from main path

### Phase 2: Provider interface
- [ ] **P2.1** `interfaces.py` — add `dynamic_context` to protocol
- [ ] **P2.2** `base.py` — add `dynamic_context` to abstract method + `complete()`/`stream()`

### Phase 3: Provider implementations (P3.1 and P3.2 can parallel)
- [ ] **P3.1** `anthropic.py` — `_inject_dynamic_context()`, `_add_conversation_cache_breakpoint()`, update `_build_request_body()`
- [ ] **P3.2** `openai_compat.py` — `_inject_dynamic_context()`, update `_build_request_body()`

### Phase 4: Session integration
- [ ] **P4.1** Update 3 `provider.stream()` call sites in `session.py` to pass `dynamic_context`

### Phase 5: Tests & verification
- [ ] **P5.1** Update existing context manager tests
- [ ] **P5.2** Add provider caching tests (dynamic injection, cache breakpoints)
- [ ] **P5.3** Full test suite + ruff + mypy
- [ ] **P5.4** Live test: verify cache metrics with `-v`, datetime accuracy, git/clipboard context

### Phase 6: Documentation
- [ ] **P6.1** Update prompt caching sections in `CLAUDE.md` and `nexus3/provider/README.md`
