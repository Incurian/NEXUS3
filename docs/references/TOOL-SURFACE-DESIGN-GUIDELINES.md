# Tool Surface Design Guidelines

This document captures the lessons from the 2026-04 tool-syntax
simplification work. It is intended as durable guidance for future built-in
tool design, prompt/schema updates, and tool-family audits.

The short version:

- weak models do not reliably handle overloaded public tool contracts
- provider tool APIs flatten away some schema structure, so `oneOf`-style
  distinctions are not dependable in practice
- one public tool name per top-level argument shape is the most reliable rule
- compatibility should live at the execution boundary, not in the public schema

## Why This Matters

Several built-in tools had acceptable human ergonomics but poor model
ergonomics. They exposed multiple wrapper shapes, public aliases, or mutually
exclusive top-level parameter sets under one tool name. Weaker models often:

- mixed two legal shapes into one malformed payload
- picked legacy aliases instead of the canonical names
- produced arguments that only made sense if the model had remembered hidden
  runtime invariants
- failed to choose correctly between two competing wrapper styles

These failures were especially common in model-facing surfaces that had to pass
through flat provider tool schemas.

## Core Rules

### 1. One public tool name per top-level argument shape

If two valid calls have meaningfully different wrapper structures, they should
usually be two tools.

Good:

- `edit_file(path, old_string, new_string, replace_all?)`
- `edit_file_batch(path, edits=[...])`

Bad:

- one `edit_file` tool that accepts either single-edit fields or `edits=[...]`

### 2. One canonical public name per concept

Do not publicly teach multiple parameter names for the same idea unless the
compatibility cost is unavoidable and the ambiguity is worth it.

Good:

- `read_file(offset, limit)`
- `outline(parser=...)`

Bad:

- `read_file(offset/limit/start_line/end_line)`
- `outline(parser/file_type/language)`

### 3. Keep compatibility at the execution boundary

Legacy aliases and historical wrapper shapes can still be supported, but they
should be normalized just before tool dispatch, not presented as equal options
in the model-facing schema or prompt docs.

The public surface should stay narrow and canonical. Compatibility is an
implementation detail.

### 4. Prefer explicit splits over schema cleverness

Do not rely on public `oneOf`, `anyOf`, or mutually exclusive optional fields
to explain a complex tool contract. In practice, provider tool normalization
often flattens or weakens these distinctions.

If the tool meaning depends on which optional field is present, that is usually
a sign the surface should be split.

### 5. Positive examples outperform caveat-heavy prose

Prompt and description space should show the correct call shape, not just warn
about mistakes.

Each tricky tool should ideally teach:

- when to choose it
- the exact canonical argument shape
- one short valid example
- the closest sibling tool to use instead when the shape does not fit

### 6. Atomic batch operations deserve explicit names

If a tool can operate on one target or many targets atomically, the batch form
should usually have its own tool name.

This helps the model infer:

- the shape it must emit
- whether the operation is atomic
- whether it is choosing a single-edit or multi-edit workflow

### 7. Conflicting canonical and compatibility fields should fail closed

If runtime compatibility normalization accepts historical aliases, mixed calls
must not be silently guessed.

Good:

- normalize `patch(target=...)` to `patch(path=...)`
- reject a call that provides both `target` and `path` with different values

Bad:

- silently prefer one field and continue

### 8. Public docs, prompt docs, and emitted tool descriptions must agree

A tool contract is not just the implementation. The model sees a combination
of:

- the emitted tool description and parameter schema
- `nexus3/defaults/NEXUS-DEFAULT.md`
- skill docs and top-level docs that humans copy from

If those surfaces disagree, weaker models will learn the wrong thing even if
the implementation is technically correct.

## Acceptable Exceptions

Not every multi-behavior tool needs to be split.

A tool family is usually acceptable as one public tool when all of the
following are true:

- the top-level object shape stays stable
- the behavior switch is explicit, usually via `action` or `mode`
- the parameter names do not alias the same concept in multiple ways
- the model is not choosing between two incompatible wrapper styles

Examples that currently remain acceptable:

- action/mode-dispatched clipboard tools
- GitLab tool families with explicit operation fields

These surfaces may still be complex, but they are less ambiguous than alias-
rich or wrapper-overloaded tools.

## Concrete Changes We Made

### 1. `edit_file` -> `edit_file` + `edit_file_batch`

Previous public problem:

- one tool name exposed both:
  - `path`, `old_string`, `new_string`, `replace_all?`
  - `path`, `edits=[...]`

Why it failed:

- the batch shape partially repeated the single-edit fields
- weaker models often blended the two shapes or serialized the wrong one
- top-level schema combinators were not reliable enough to teach the
  distinction cleanly

What changed:

- `edit_file` now means exactly one literal replacement
- `edit_file_batch` now means atomic multi-edit replacement
- legacy `edit_file(edits=[...])` calls are normalized in the runtime, not
  taught publicly

Why this is better:

- the tool name now implies the full argument shape
- single-edit and batch-edit examples are short and unambiguous
- compatibility remains available without polluting the public contract

### 2. `edit_lines` -> `edit_lines` + `edit_lines_batch`

Previous public problem:

- same overload pattern as the old `edit_file`

What changed:

- `edit_lines` is now single-range only
- `edit_lines_batch` is now the explicit atomic multi-range tool

Why this is better:

- it reuses the successful exact-string-edit rule for line-range edits
- it makes atomic batch semantics visible in the tool name

### 3. `patch` -> `patch` + `patch_from_file`

Previous public problem:

- one tool taught both inline `diff` and file-backed `diff_file`
- it also publicly taught `target` as an alias for `path`

Why it was risky:

- inline diff text and diff-file loading are different wrapper shapes
- the public alias made the canonical path field less stable

What changed:

- `patch` now means inline diff text
- `patch_from_file` now means load diff text from a diff/patch file
- `target` remains compatibility-only and is normalized before execution

Why this is better:

- models no longer need to decide whether the diff is inline or external under
  one overloaded tool name
- `path` remains the one public target field

### 4. `read_file` canonicalized to `offset` / `limit`

Previous public problem:

- `offset` / `limit` and `start_line` / `end_line` were both publicly taught

What changed:

- only `offset` / `limit` remain public
- alias support stays in the runtime helper layer

Why this is better:

- there is one public way to ask for a window
- examples and tool descriptions now reinforce the same shape everywhere

### 5. `outline` canonicalized to `parser`

Previous public problem:

- the same parser-override concept was publicly exposed as `parser`,
  `file_type`, and `language`

What changed:

- only `parser` remains public
- alias support stays runtime-only for compatibility

Why this is better:

- the model no longer has to guess which synonym the tool wants
- docs and emitted schemas now reinforce the same parameter name

## Design Checklist For New Tools

Before adding or expanding a tool, check:

1. Does the public tool have exactly one top-level argument shape?
2. If not, should it be split into multiple tool names?
3. Does each concept have exactly one canonical public parameter name?
4. Are any aliases strictly compatibility-only and hidden from the public
   schema?
5. Would a weaker model know which sibling tool to choose from the name alone?
6. Does the description include a short positive example or clear shape
   guidance?
7. If the tool is write-capable, have path semantics, permissions,
   confirmation, and destructive-tool defaults been updated too?
8. Have the model-facing prompt docs and emitted tool descriptions been kept in
   sync?
9. Are compatibility rewrites tested explicitly?
10. Are conflicting alias/canonical mixes rejected rather than guessed?

## Implementation Pattern

When a public split is needed, the preferred pattern is:

1. Split the public tool names and schemas.
2. Keep shared execution helpers underneath the split.
3. Add a narrow runtime compatibility normalizer in
   `nexus3/session/single_tool_runtime.py`.
4. Fail closed on ambiguous mixed payloads.
5. Update:
   - emitted skill descriptions
   - `nexus3/defaults/NEXUS-DEFAULT.md`
   - skill docs and top-level docs
   - registration/path semantics/permissions/confirmation references
6. Add focused tests for:
   - public schema shape
   - compatibility normalization
   - write-path enforcement for new tool names

## Smells That Usually Mean A Tool Needs Simplification

- "This tool can be called in two different ways."
- "Either field name is fine."
- "Use `A` or `B` depending on whether you are doing the simple or advanced
  form."
- "The schema technically allows both, but the runtime expects them not to be
  mixed."
- "The provider flattens this, but the model should still infer the intended
  branch."

Those are all signs that the model is carrying too much contract logic.

## Default Bias For Future Tool Work

Bias toward:

- narrow public schemas
- obvious tool names
- one canonical parameter name per concept
- explicit batch tools for atomic multi-operation workflows
- runtime compatibility shims that are invisible to the model

Bias away from:

- overloaded wrapper shapes
- public alias teaching
- schema cleverness that depends on provider fidelity
- silent normalization of ambiguous mixed calls
