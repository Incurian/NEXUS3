# Tool Call Format Detection Research Plan (2026-04-07)

## Overview

This research task traces the `_raw_arguments` path in NEXUS3, identifies
which upstream tool-call formats can produce it, and outlines what it would
take to automatically detect and support additional tool-call formats without
destabilizing the current session/tool runtime.

Bottom line:

- `_raw_arguments` is **not** a provider wire format.
- It is an **internal sentinel** created by the OpenAI-compatible parser when
  `function.arguments` cannot be decoded as JSON.
- vLLM is a credible trigger, especially in `tool_choice="auto"` mode where
  its own documentation says tool arguments may be malformed and parser-driven.
- Current NEXUS3 parsing is built around one canonical internal contract:
  `ToolCall.arguments` must end up as `dict[str, Any]`.

## Scope

Included:

- audit current tool-call parsing and execution assumptions
- explain the `_raw_arguments` sentinel and where it is created/consumed
- compare current parsing with common external tool-call wire formats
- identify the smallest viable and the cleanest long-term support paths

Deferred:

- implementing any parser changes
- adding new provider types
- redesigning the entire provider abstraction around multiple wire protocols

Excluded:

- changing tool schema emission
- changing permission semantics
- changing session/tool loop control flow unrelated to argument parsing

## Findings

### 1. Current internal contract is dict-only

`ToolCall.arguments` is typed as `dict[str, Any]` in
`nexus3/core/types.py`, and downstream validation assumes a dict-shaped
payload.

Relevant files:

- `nexus3/core/types.py`
- `nexus3/core/validation.py`
- `nexus3/session/single_tool_runtime.py`

### 2. `_raw_arguments` is an internal fallback, not an external format

In the OpenAI-compatible provider, NEXUS3 currently expects
`tool_calls[*].function.arguments` to be a JSON string. If `json.loads(...)`
fails with `JSONDecodeError`, the parser stores:

```python
{"_raw_arguments": "<original text>"}
```

That sentinel is later rejected by the single-tool runtime with a user-facing
retry error.

This behavior exists in both:

- non-streaming parsing in `nexus3/provider/openai_compat.py`
- streaming completion assembly in `nexus3/provider/openai_compat.py`

### 3. Anthropic already uses a different argument shape

Anthropic tool use does not use the OpenAI `function.arguments` JSON-string
pattern. NEXUS3 already supports Anthropic by reading `tool_use` blocks and
taking `input` as an object directly.

That means NEXUS3 already supports multiple external tool-call formats, but
only because provider selection is explicit and parser logic is provider-local.

### 4. Current OpenAI-compatible parsing is narrower than the name implies

The OpenAI-compatible path assumes:

- non-streaming: `function.arguments` is a JSON string
- streaming: `function.arguments` arrives as incrementally concatenated string
  fragments

Two gaps matter:

1. If a provider returns an already-parsed object in `function.arguments`,
   non-streaming parsing will raise `TypeError` instead of falling back.
2. If streaming deltas deliver non-string argument fragments, string
   concatenation will fail before completion assembly.

So the current parser is robust against malformed JSON text, but not against
"OpenAI-ish" providers that use object-shaped arguments.

### 5. vLLM is a plausible source of `_raw_arguments`

vLLM's tool-calling docs explicitly distinguish between constrained modes and
`auto` mode:

- named function calling / `required`: valid JSON conforming to schema
- `auto`: parser extracts tool calls from free-form model output, and arguments
  may be malformed

vLLM also documents multiple parser families that normalize raw model output
into tool calls:

- `xlam`: several JSON/tagged tool-call output styles
- `pythonic`: Python list/call syntax instead of JSON
- model-specific parsers for Hermes, Mistral, Llama, Qwen, FunctionGemma,
  OpenAI OSS, Olmo 3, and others

The `pythonic` family is especially relevant because the model output is not
JSON-shaped tool arguments at all before parser normalization.

### 6. Some other APIs use object arguments, not JSON strings

Relevant comparison points:

- OpenAI Chat Completions tool calls: JSON-string `function.arguments`
- OpenAI Responses API function calls: JSON-string `arguments`
- OpenAI Responses API custom tool calls: raw string `input`
- Anthropic tool use: object `input`
- Gemini function calling: object `args`

This means "support more formats" is not one thing. There are at least three
families:

1. schema JSON string
2. already-parsed object
3. raw text/freeform tool input

Only the first two map cleanly onto today's built-in skill runtime.

## External Format Survey

### OpenAI Chat Completions

Current NEXUS3 outbound/inbound assumptions match this family:

- assistant tool calls live under `tool_calls`
- tool metadata lives under `function`
- arguments are JSON-encoded text

This is the current baseline for `OpenAICompatProvider`.

### OpenAI Responses API

This is a different wire protocol than chat completions even though it still
uses JSON-string arguments for function calls. Supporting it cleanly would
require:

- non-streaming parser for `response.output[*]` items
- streaming parser for Responses API event names and incremental argument
  deltas
- possible handling for non-function tool items like `custom_tool_call`,
  `mcp_approval_request`, and hosted tool outputs

It is not just a small variant of current `/chat/completions` parsing.

### Anthropic

Already supported via a native provider:

- tool calls are `tool_use` content blocks
- arguments are object-shaped `input`
- streaming uses `input_json_delta`

### Gemini

Gemini uses object-shaped function arguments (`args`) plus a function-call ID.
That is closer to Anthropic than to OpenAI chat-completions parsing.

### vLLM

vLLM matters in two distinct ways:

1. In named/`required` modes, it can behave close to OpenAI-compatible JSON.
2. In `auto` mode, the parser may be recovering tool calls from model-specific
   raw text, and malformed arguments are explicitly possible.

This makes vLLM the strongest justification for preserving raw text and
format metadata rather than assuming everything should always decode straight
to a dict.

## Design Decisions And Rationale

### Decision 1: Keep the execution boundary dict-shaped

Built-in skills, permission checks, and argument validation are all optimized
around named parameters in a dict. Extending execution to arbitrary raw text
tool inputs would be a larger runtime contract change than this research task
needs.

Recommendation:

- keep execution-time normalization targeting `dict[str, Any]`
- preserve raw/original payload separately when decoding fails

### Decision 2: Separate wire-format parsing from execution normalization

Today, parsing and normalization are entangled inside providers. A cleaner
design is:

- provider parser reads wire format
- tool-call normalizer converts it to the internal execution contract
- runtime validates/executes only normalized calls

This reduces repeated ad-hoc compatibility shims in provider code.

### Decision 3: Treat vLLM pythonic/freeform formats as opt-in, not blind auto-parse

Parsing Python-like call syntax with heuristics is feasible, but doing it
blindly for every malformed string would risk misclassifying ordinary text or
future provider-specific shapes.

Recommendation:

- auto-detect only clearly structured formats first
- make Pythonic parsing provider-gated or config-gated

## Implementation Details With Concrete File Paths

### Option A: Minimal defensive hardening

Goal: support more "OpenAI-ish" variants without changing core contracts.

Changes:

- `nexus3/provider/openai_compat.py`
  - accept `function.arguments` as `dict` in non-streaming responses
  - catch `TypeError` alongside `JSONDecodeError`
  - streaming: tolerate already-structured argument payloads and mark
    unsupported mixed chunk types explicitly
- tests under `tests/unit/provider/`
  - add cases for object-shaped `function.arguments`
  - add cases for vLLM-style malformed JSON text in `auto` mode

Pros:

- smallest patch
- likely enough for object-shaped arguments from compatible servers

Cons:

- still provider-local and ad hoc
- still no clean support for Responses API or Pythonic/raw-text formats

### Option B: Add a shared tool-call normalizer layer

Goal: support multiple wire formats intentionally.

Add:

- `nexus3/provider/tool_call_formats.py`
  - parsing helpers for:
    - OpenAI chat completions tool calls
    - Anthropic tool-use blocks
    - OpenAI Responses API function-call items
    - object-vs-string argument normalization helpers
- `nexus3/core/types.py`
  - either extend `ToolCall` metadata, or add a new parsed envelope type
- `nexus3/session/single_tool_runtime.py`
  - consume normalized arguments plus raw format metadata for better errors

Likely metadata to preserve:

- source format (`openai_chat`, `anthropic_tool_use`, `openai_responses`,
  `gemini_function_call`, `vllm_pythonic`, `unknown`)
- raw argument text when decode fails
- whether the payload was strict JSON, object input, or freeform text

Pros:

- cleanest long-term base
- makes future format additions predictable

Cons:

- broader refactor
- touches core typing and multiple providers

### Option C: Full protocol expansion

Goal: support additional APIs, not just argument variants.

Add:

- Responses API provider/parser
- possibly Gemini provider/parser
- config for protocol selection beyond provider type

This is the right path if the real requirement is "speak multiple tool-call
wire protocols," not merely "be more forgiving about argument payloads."

## Recommended Path

### Near term

Implement Option A first:

- accept object-shaped arguments in `OpenAICompatProvider`
- catch `TypeError` in non-streaming and streaming decode paths
- improve logging so malformed/raw tool calls record likely source/provider

This is low risk and directly addresses likely vLLM/Ollama/OpenAI-compatible
variants.

### Follow-on

If live usage confirms more than one non-JSON family, implement Option B:

- centralize normalization
- preserve format metadata
- add explicit support for Responses API function-call items
- decide whether Pythonic parsing is provider-gated

## Testing Strategy

### Unit tests

Add provider parser tests for:

- OpenAI-compatible `function.arguments` as valid JSON string
- invalid JSON string producing preserved raw metadata
- object-shaped `function.arguments` accepted directly
- streaming argument chunks as strings
- streaming argument payload unexpectedly arriving as object
- vLLM-like malformed `auto` tool-call payloads

Potential files:

- `tests/unit/provider/test_streaming_tool_calls.py`
- new `tests/unit/provider/test_tool_call_format_detection.py`

### Integration tests

Add session/tool-loop tests proving:

- object-shaped arguments still execute correctly
- malformed/raw arguments still fail closed with actionable error text
- permission checks do not crash when raw metadata is present

Potential files:

- `tests/integration/test_skill_execution.py`
- `tests/integration/test_permission_enforcement.py`

## Implementation Checklist

- [ ] decide whether this slice is parser-hardening only or protocol expansion
- [ ] harden `OpenAICompatProvider` against object-shaped arguments
- [ ] add explicit regression tests for `TypeError` cases
- [ ] decide whether to add shared tool-call format metadata
- [ ] decide whether OpenAI Responses API support is in scope
- [ ] decide whether Pythonic/vLLM parser support is heuristic or config-gated
- [ ] document the supported tool-call formats in provider docs

## Documentation Updates

If implemented, update:

- `nexus3/provider/README.md`
  - supported inbound tool-call formats
  - limits of OpenAI-compatible parsing
  - vLLM `auto` mode caveats
- `AGENTS.md` / `CLAUDE.md`
  - only if this becomes an active tracked implementation slice

## Source Pointers

Local code:

- `nexus3/provider/openai_compat.py`
- `nexus3/provider/anthropic.py`
- `nexus3/session/single_tool_runtime.py`
- `nexus3/core/types.py`
- `nexus3/core/validation.py`

Primary external references consulted on 2026-04-07:

- OpenAI Responses API reference:
  <https://developers.openai.com/api/reference/resources/responses/methods/create>
- Anthropic tool use overview:
  <https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview>
- Gemini function calling guide:
  <https://ai.google.dev/gemini-api/docs/function-calling>
- vLLM tool calling guide:
  <https://docs.vllm.ai/en/latest/features/tool_calling/>
- Ollama tool calling docs:
  <https://docs.ollama.com/capabilities/tool-calling>
