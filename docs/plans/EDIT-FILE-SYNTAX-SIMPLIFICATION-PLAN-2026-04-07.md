# Edit File Syntax Simplification Plan (2026-04-07)

## Overview

This slice investigates why weaker models perform poorly with `edit_file` and
implements the smallest contract change that materially improves success
without reducing editing capability.

The root problem is not just wording. `edit_file` currently exposes two
competing top-level call shapes under one tool name:

- single edit via `path`, `old_string`, `new_string`, `replace_all?`
- batch edit via `path`, `edits=[...]`

That dual-mode design is difficult for weaker models to serialize correctly,
especially because the batch shape partially repeats the single-edit field
names. Provider tool-schema normalization also strips top-level combinators
like `oneOf`, so the contract cannot be made reliably self-describing through
schema tricks alone.

## Scope

### Included

- Deep-audit `edit_file` tool metadata, implementation, and prompt guidance in
  `nexus3/defaults/NEXUS-DEFAULT.md`.
- Split the public exact-string edit surface into:
  - `edit_file` for one literal replacement
  - `edit_file_batch` for atomic multi-replacement batches
- Keep runtime compatibility for legacy `edit_file(edits=[...])` calls at the
  session execution boundary.
- Rewrite prompt/docs guidance to show positive examples and the new decision
  rules.
- Update permissions, path semantics, confirmation, and registration surfaces
  so the new tool behaves like the existing write/edit family.
- Add focused tests for the new public contract and the compatibility path.

### Deferred

- Splitting `edit_lines` into separate single/batch tools in the same slice.
- Redesigning the broader file-edit family into one generic unified edit tool.
- Provider-side heuristics that try to repair malformed `edit_file` payloads.

### Excluded

- Changing `regex_replace` or `patch` semantics.
- Removing all backwards compatibility for historical `edit_file(edits=[...])`
  calls.

## Design Decisions And Rationale

### 1. Prefer one public tool name per top-level call shape

Weak models do better when the tool name implies the full argument shape.
`edit_file` should mean one literal replacement, not "one replacement or a
batch depending on which fields appear."

### 2. Keep compatibility at the execution boundary, not in the public schema

Compatibility placeholders and legacy aliases should not remain visible in the
tool schema presented to the model. They should be normalized just before tool
dispatch so old calls keep working without continuing to teach the model the
wrong surface.

### 3. Use prompt space for positive examples, not just caveats

The current prompt explains many legitimate sharp edges, but it gives little
concrete help on what a correct `edit_file` call looks like. The updated
guidance should show:

- the exact single-edit shape
- the exact batch-edit shape
- when to choose each tool
- what not to mix

### 4. Capture the general lesson for future tool audits

This investigation likely generalizes beyond `edit_file`:

- avoid multi-mode top-level schemas where providers flatten combinators
- prefer explicit tool splits over overloaded runtime-only invariants
- keep compatibility shims invisible to the model

## Implementation Details

### Tooling and runtime

Files:

- `nexus3/skill/builtin/edit_file.py`
- `nexus3/skill/builtin/registration.py`
- `nexus3/session/single_tool_runtime.py`
- `nexus3/session/path_semantics.py`
- `nexus3/session/enforcer.py`
- `nexus3/core/policy.py`
- `nexus3/context/git_context.py`
- `nexus3/rpc/global_dispatcher.py`
- `nexus3/config/schema.py`

Work:

- Refactor shared exact-string edit logic so single and batch skills reuse the
  same file-reading, line-ending, and replacement behavior.
- Make `edit_file` expose only the single-edit schema.
- Add `edit_file_batch` with required `path` + `edits`.
- Add a narrow execution-time compatibility normalizer that maps legacy
  `edit_file(edits=[...])` calls onto `edit_file_batch`, while stripping only
  harmless legacy placeholder fields.

### Prompt and documentation

Files:

- `nexus3/defaults/NEXUS-DEFAULT.md`
- `README.md`
- `nexus3/skill/README.md`
- `nexus3/skill/builtin/README.md`
- `AGENTS_NEXUS3SKILLSCAT.md`
- `docs/plans/README.md`

Work:

- Replace `edit_file + edits` guidance with explicit `edit_file_batch`.
- Add short valid examples for both tools.
- Tighten the selection flow so tool choice is based on shape, not vague
  "power level" wording.
- Update built-in skill counts if the public surface grows by one tool.

## Testing Strategy

- Focused unit tests for:
  - `edit_file` single-edit schema/behavior
  - `edit_file_batch` schema/behavior
  - legacy `edit_file(edits=[...])` compatibility execution
  - permission/path semantics registration
- Focused integration tests for exact-string editing flows.
- Focused lint/type checks on touched files.
- Full `tests/ -v` run after the contract change because it touches session,
  permissions, and built-in registration.

## Implementation Checklist

- [x] Audit `edit_file`, prompt guidance, and existing failure patterns.
- [x] Record findings and implementation direction in a plan doc.
- [x] Split `edit_file` public contract into single-edit and batch-edit tools.
- [x] Add session-level compatibility mapping for legacy batch calls.
- [x] Update prompt/docs to reflect the new public surface.
- [x] Run targeted validation.
- [x] Run full validation.
- [x] Update `AGENTS.md` current handoff.

## Documentation Updates

- Keep `NEXUS-DEFAULT.md` as the primary model-facing contract reference.
- Mirror the public skill table changes in `README.md`,
  `nexus3/skill/README.md`, and `AGENTS_NEXUS3SKILLSCAT.md`.
- Record the broader lesson for later tool-family audits: tool splits are often
  more reliable than overloaded schemas when provider tool APIs flatten away
  structural distinctions.
