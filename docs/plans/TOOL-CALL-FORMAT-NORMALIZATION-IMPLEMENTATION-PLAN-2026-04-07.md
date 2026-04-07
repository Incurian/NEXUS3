# Tool Call Format Normalization Implementation Plan (2026-04-07)

## Overview

This plan covers implementation of broad inbound tool-call normalization for
NEXUS3 on branch `tool-call-format-autodetect`.

Goal:

- accept a wider range of provider/server tool-call payloads automatically
- normalize them at the provider boundary into NEXUS3's internal tool-call
  contract
- preserve source-format and raw-payload metadata for diagnostics
- fail closed only when the payload is genuinely ambiguous or cannot be
  converted into named arguments safely

This is intentionally more expansive than the current implementation, but it
will still keep a hard boundary: built-in skill execution remains
dict-argument-based.

## Scope

Included:

- shared parsing/normalization helpers for multiple inbound tool-call formats
- OpenAI-compatible non-streaming and streaming auto-detection
- Anthropic non-streaming and streaming hardening onto the same normalization
  helpers
- metadata preservation for malformed/raw/non-object argument payloads
- focused runtime changes so malformed/raw payloads fail closed cleanly
- unit and integration coverage for the new formats

Deferred:

- outbound request-shape changes beyond what is needed for compatibility
- adding brand new provider classes for Gemini or other vendors
- executing raw-text tool inputs directly in the skill runtime
- provider-specific config knobs unless heuristics prove too risky in tests

Excluded:

- changing permission semantics
- changing MCP tool schema generation
- redesigning the entire provider abstraction beyond inbound normalization

## Why Not Blindly Parse Everything

There are real reasons not to accept literally any raw tool-call text:

1. Ambiguous free-form text can be mistaken for structured arguments.
2. Current tool execution, permissions, and schema validation are designed for
   named arguments in a dict, not arbitrary raw input strings.
3. Over-aggressive heuristics could silently transform payloads in
   security-sensitive tools such as file writes, process execution, or agent
   messaging.
4. Streaming protocols differ materially across chat completions, Responses
   API, and Anthropic SSE, so "one parser for everything" still needs
   protocol-aware event handling.

Implementation consequence:

- parse and normalize broadly for known structured families
- preserve raw text and source metadata when normalization is unsafe
- fail closed on ambiguous free-form payloads rather than guessing

## Chosen Design

### 1. Add a shared normalization layer

Introduce a provider-local normalization module that takes provider payload
fragments and returns internal `ToolCall` objects plus metadata.

Planned new file:

- `nexus3/provider/tool_call_formats.py`

Responsibilities:

- normalize object-vs-string-vs-raw argument payloads
- parse known tool-call item shapes
- preserve source format and raw payload metadata
- provide small streaming accumulator helpers for different protocols

### 2. Widen the internal `ToolCall` envelope safely

Extend `ToolCall` with optional metadata rather than encoding everything into
fake argument keys.

Planned file changes:

- `nexus3/core/types.py`
- `nexus3/session/persistence.py`
- `nexus3/session/logging.py`

Planned metadata fields:

- `source_format`
- `argument_format`
- `raw_arguments`
- `normalization_error`

Compatibility rule:

- keep legacy `_raw_arguments` handling readable for restored or historical
  sessions
- prefer new metadata fields for all new parses

### 3. Keep execution dict-shaped

The runtime will continue to execute only `dict[str, Any]` tool arguments.

Normalization rules:

- object payload -> accept directly
- JSON-string payload that decodes to object -> accept
- Python dict literal / kwargs / matching call-expression -> accept only when
  parsing is explicit and lossless
- raw text / JSON scalar / JSON array / ambiguous expression -> preserve raw
  payload and fail closed before execution

### 4. Auto-detect by payload family, not by provider name

Non-streaming and streaming parsers should inspect the incoming payload shape.

Known families to support:

- OpenAI chat completions `tool_calls[*].function`
- OpenAI Responses API `output[*]` function-call items
- Anthropic `content[*].tool_use`
- object-shaped argument variants from OpenAI-compatible servers
- Pythonic argument variants commonly associated with vLLM parser outputs

## Format Support Matrix

### Accept and normalize

- JSON object string
- already-parsed object/dict
- Python dict literal string like `{'path': 'x'}`
- Python kwargs expression like `path='x', limit=5`
- Python call expression matching the known tool name like
  `read_file(path='x', limit=5)`

### Preserve raw and fail closed

- arbitrary natural-language raw text
- JSON arrays or scalars
- multi-call bundles stuffed into one argument field
- Python expressions with side-effect-capable syntax or unsupported AST forms
- custom/raw tool-call inputs that do not map to named arguments

## Implementation Details With Concrete File Paths

### Phase 1. Internal type and persistence support

Files:

- `nexus3/core/types.py`
- `nexus3/session/persistence.py`
- `nexus3/session/logging.py`
- `nexus3/session/single_tool_runtime.py`

Changes:

- add `meta: dict[str, Any] = field(default_factory=dict)` to `ToolCall`
- add helper properties on `ToolCall` for:
  - raw argument text
  - source format
  - invalid/unresolved argument state
- persist and restore `ToolCall.meta`
- update runtime malformed/raw-argument checks to use `ToolCall.meta` first,
  then fall back to legacy `_raw_arguments`
- move malformed/raw-argument rejection ahead of permission-specific argument
  inspection when safe to do so

Rationale:

- avoids polluting valid tool arguments with internal parser markers
- keeps diagnostics and future format support extensible

### Phase 2. Shared non-streaming normalization helpers

Files:

- `nexus3/provider/tool_call_formats.py` (new)
- `nexus3/provider/openai_compat.py`
- `nexus3/provider/anthropic.py`

New helper surface:

- `normalize_tool_arguments(...)`
- `parse_openai_chat_tool_calls(...)`
- `parse_responses_output_items(...)`
- `parse_anthropic_tool_use_blocks(...)`
- `parse_pythonic_argument_string(...)`

Normalization algorithm:

1. If payload is `dict`, accept as-is.
2. If payload is empty string or `None`, treat as `{}`.
3. If payload is string:
   - try strict JSON object parse
   - if that fails, try Python dict literal parse
   - if that fails, try Python kwargs parse
   - if that fails, try matching call-expression parse using the known tool
     name
   - otherwise preserve raw text in metadata and mark unresolved
4. If payload is list/scalar/non-object JSON, preserve raw payload and mark
   unresolved

Safety constraints for Pythonic parsing:

- use `ast.parse` / `ast.literal_eval` only
- accept only literals, dicts, lists/tuples used as literal values, booleans,
  `None`, and keyword arguments
- reject names, attribute access, comprehensions, lambdas, calls inside
  values, operators, and any non-literal AST forms

### Phase 3. OpenAI-compatible non-streaming auto-detection

Files:

- `nexus3/provider/openai_compat.py`

Changes:

- broaden `_parse_response()` to detect:
  - chat completions payloads with `choices[0].message`
  - Responses API payloads with `output`
  - Anthropic-like content-block fallback if encountered through a proxy
- replace the local `_parse_tool_calls()` logic with the shared normalizer
- catch `TypeError` and non-string argument variants cleanly
- preserve reasoning/debug logging behavior

Planned detection order:

1. `choices` -> chat completions
2. `output` -> Responses API
3. `content` list -> content-block parser fallback
4. otherwise raise provider error

### Phase 4. OpenAI-compatible streaming auto-detection

Files:

- `nexus3/provider/openai_compat.py`
- `nexus3/provider/tool_call_formats.py`

Changes:

- replace the current string-only tool-call accumulator with a richer
  accumulator object
- support:
  - standard chat-completions `delta.tool_calls`
  - object-shaped argument payloads if emitted whole
  - Responses API event families for text and function-call argument deltas
- preserve partial raw text when a stream ends mid-arguments

Responses API event support target:

- output item added/done for function calls
- function-call argument delta/done
- text delta for assistant content
- completion event

Fallback rule:

- if an event family is recognized but arguments remain unresolved, create a
  `ToolCall` with metadata marking unresolved/raw payload rather than dropping
  the call silently

### Phase 5. Anthropic hardening

Files:

- `nexus3/provider/anthropic.py`
- `nexus3/provider/tool_call_formats.py`

Changes:

- use the shared content-block normalizer for non-streaming `tool_use`
- in streaming, preserve malformed `input_json_delta` payloads as raw metadata
  instead of converting them silently to `{}`
- optionally detect fallback OpenAI-like payloads if seen through gateways

### Phase 6. Runtime and UX behavior

Files:

- `nexus3/session/single_tool_runtime.py`
- `nexus3/cli/confirmation_ui.py`
- `nexus3/context/manager.py` if needed for formatting helpers only

Changes:

- malformed/unresolved arguments produce actionable error text including:
  - tool name
  - source format when known
  - truncated raw payload preview
- confirmation UI and formatting helpers remain driven by normalized arguments
  only; unresolved tool calls should not reach confirmation flows

Open question to settle during implementation:

- whether to reject unresolved/raw tool calls before or after unknown-skill
  resolution. Current preference: resolve skill name first, then fail on
  unresolved arguments before permissions/confirmation checks.

### Phase 7. Documentation refresh

Files:

- `nexus3/provider/README.md`
- `docs/plans/README.md`
- optionally `AGENTS.md` / `CLAUDE.md` handoff if this becomes the active
  implementation slice

Changes:

- document supported inbound tool-call families
- document unresolved/raw fail-closed behavior
- document vLLM `auto` / Pythonic caveats

## Testing Strategy

### Unit tests

Add new focused unit coverage for normalization helpers.

Planned files:

- `tests/unit/provider/test_tool_call_formats.py` (new)
- `tests/unit/provider/test_streaming_tool_calls.py`
- `tests/unit/test_persistence.py`
- `tests/unit/test_types.py`

Target cases:

- OpenAI JSON-string arguments
- object-shaped `function.arguments`
- malformed JSON preserving raw metadata
- JSON array/scalar preserving raw metadata
- Python dict literal parsing
- Python kwargs parsing
- call-expression parsing when the function name matches
- call-expression rejected when the function name mismatches
- Responses API non-streaming function-call items
- Responses API streaming argument deltas
- Anthropic malformed `input_json_delta` preserved as raw metadata
- persistence round-trip of `ToolCall.meta`

### Integration tests

Planned files:

- `tests/integration/test_skill_execution.py`
- `tests/integration/test_permission_enforcement.py`

Target cases:

- object-shaped arguments execute normally
- pythonic-but-lossless arguments execute normally after normalization
- unresolved/raw payloads fail closed with stable error messages
- no permission crash/regression when metadata is present

### Validation commands

Per repo guidance, use virtualenv executables only:

```bash
.venv/bin/pytest tests/unit/provider/test_tool_call_formats.py -q
.venv/bin/pytest tests/unit/provider/test_streaming_tool_calls.py -q
.venv/bin/pytest tests/unit/test_persistence.py tests/unit/test_types.py -q
.venv/bin/pytest tests/integration/test_skill_execution.py tests/integration/test_permission_enforcement.py -q
.venv/bin/ruff check nexus3/provider nexus3/session nexus3/core tests/unit/provider tests/integration
.venv/bin/mypy nexus3/provider nexus3/session nexus3/core
```

If provider/runtime touch points get broader than expected, expand to:

```bash
.venv/bin/pytest tests/ -v
```

## Risks And Mitigations

### Risk 1. Over-parsing ambiguous raw text

Mitigation:

- restrict Pythonic parsing to literal-only AST forms
- require known tool-name match for call-expression parsing
- preserve raw payload and fail closed when uncertain

### Risk 2. Silent permission behavior changes

Mitigation:

- reject unresolved arguments before permission-specific argument reads
- keep normalized `arguments` dict semantics unchanged for successful cases
- run permission integration coverage

### Risk 3. Streaming regressions

Mitigation:

- keep existing chat-completions stream tests intact
- add dedicated Responses API streaming tests before refactor completion
- preserve existing `ToolCallStarted` emission timing as closely as possible

### Risk 4. Metadata persistence drift

Mitigation:

- explicit round-trip tests through session persistence and context reload

## Implementation Checklist

### Phase 1: Internal envelope
- [x] Add `ToolCall.meta` and helper properties in `nexus3/core/types.py`
- [x] Persist/restore `ToolCall.meta` in `nexus3/session/persistence.py`
- [x] Preserve `ToolCall.meta` in session logging/context reload paths
- [x] Refactor malformed/raw handling in `nexus3/session/single_tool_runtime.py`

### Phase 2: Shared normalization helpers
- [x] Create `nexus3/provider/tool_call_formats.py`
- [x] Implement strict JSON-object normalization
- [x] Implement Python dict-literal normalization
- [x] Implement Python kwargs normalization
- [x] Implement call-expression normalization with tool-name matching
- [x] Implement unresolved/raw metadata preservation

### Phase 3: Provider adoption
- [x] Migrate `nexus3/provider/openai_compat.py` non-streaming parsing
- [x] Add Responses API non-streaming support
- [x] Refactor `nexus3/provider/openai_compat.py` streaming accumulators
- [x] Add Responses API streaming support
- [x] Migrate `nexus3/provider/anthropic.py` non-streaming parsing
- [x] Preserve malformed Anthropic stream input as raw metadata

### Phase 4: Tests
- [x] Add `tests/unit/provider/test_tool_call_formats.py`
- [x] Extend `tests/unit/provider/test_streaming_tool_calls.py`
- [x] Update persistence/type tests for `ToolCall.meta`
- [x] Add integration coverage for normalized vs unresolved arguments

### Phase 5: Documentation
- [x] Update `nexus3/provider/README.md`
- [x] Update `docs/plans/README.md`
- [ ] Update active handoff docs if implementation begins in earnest

## Implementation Status (2026-04-07)

Implemented on branch `tool-call-format-autodetect`:

- shared inbound normalization in `nexus3/provider/tool_call_formats.py`
- `ToolCall.meta` plus helper accessors for raw/source/format metadata
- OpenAI-compatible non-streaming auto-detection for:
  - chat completions
  - content-block payload fallbacks
  - Responses API `output` arrays
- OpenAI-compatible streaming support for:
  - classic `delta.tool_calls`
  - object-shaped argument fragments
  - Responses API `response.output_item.*`
  - Responses API `response.function_call_arguments.*`
  - Responses API `response.output_text.*`
- Anthropic non-streaming/streaming normalization hardening
- runtime fail-closed handling for unresolved/raw argument payloads before
  permission/confirmation reads
- provider/type/persistence/integration regression coverage

Focused validation passed:

- `.venv/bin/pytest -q tests/unit/provider/test_tool_call_formats.py`
- `.venv/bin/pytest -q tests/unit/provider/test_streaming_tool_calls.py tests/unit/provider/test_empty_stream.py tests/unit/provider/test_tool_call_formats.py`
- `.venv/bin/pytest -q tests/unit/session/test_session_permission_kernelization.py tests/unit/session/test_enforcer.py tests/unit/test_types.py tests/unit/test_persistence.py`
- `.venv/bin/pytest -q tests/integration/test_skill_execution.py tests/integration/test_permission_enforcement.py`
- `.venv/bin/ruff check nexus3/core/types.py nexus3/provider/openai_compat.py nexus3/provider/anthropic.py nexus3/provider/tool_call_formats.py nexus3/session/persistence.py nexus3/session/logging.py nexus3/session/single_tool_runtime.py tests/unit/provider/test_streaming_tool_calls.py tests/unit/provider/test_tool_call_formats.py tests/unit/test_types.py tests/unit/test_persistence.py`
- `.venv/bin/mypy nexus3/core/types.py nexus3/provider/openai_compat.py nexus3/provider/anthropic.py nexus3/provider/tool_call_formats.py nexus3/session/persistence.py nexus3/session/logging.py nexus3/session/single_tool_runtime.py`

Deliberately not updated in this slice:

- `AGENTS.md` / `CLAUDE.md` current handoff blocks, because the repo handoff is
  tracking a different active workstream and this feature was implemented on a
  branch-local slice rather than as the canonical handoff target.

## Go / No-Go Decision

Go if:

- we agree to normalize broadly but still fail closed on ambiguous raw text
- we accept modest internal envelope expansion via `ToolCall.meta`
- we accept that Responses API support is part of this slice

No-go / re-scope if:

- the requirement changes to executing arbitrary raw-text tool inputs
- the user wants zero heuristics and only exact provider-native parsers
- streaming Responses API support proves much larger than the rest of the
  slice and should be split into a follow-on
