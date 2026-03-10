# File-Edit Tool Contract Harmonization Plan (2026-03-10)

## Overview

The file-edit tool family is materially better aligned than it was before the
`edit_lines(edits=[...])` fix, but the remaining inconsistencies now fall into
three buckets:

- intentional semantic differences between distinct edit models
- non-obvious but legitimate behavior that needs stronger reminders
- harmful contract drift that should be standardized

This plan implements the approved harmonization work without forcing unrelated
edit models into one generic schema.

## Scope

### Included

- Harden the file-edit family to reject unknown arguments consistently.
- Make `path` the canonical single-target argument across file-edit tools while
  preserving compatibility aliases only where needed.
- Centralize empty-string placeholder normalization for optional file-edit tool
  arguments instead of continuing one-off per-tool fixes.
- Keep the shared batch convention (`edits=[...]`) for file-edit tools that
  support atomic batching, and align docs around that rule.
- Strengthen user-facing guidance for the legitimate sharp edges that remain:
  - `read_file` numbered-by-default output
  - `edit_file` batch independence requirements
  - `edit_lines` original-line-number batch semantics
  - UTF-8-only text-edit boundaries vs `patch`

### Deferred

- Retiring `patch(target=...)` in the same slice; the plan will de-emphasize it
  and make `path` canonical first.
- Converting unrelated file tools to batched forms without evidence of repeated
  misuse.
- A global skill-framework change for every tool family in the same pass.

### Excluded

- Unifying semantically distinct parameter names such as `content`,
  `new_content`, `new_string`, or `replacement`.
- Replacing `source` / `destination` naming for two-path operations.
- Redesigning `patch` into a non-diff editing tool.

## Approved Contract Decisions

### Keep As-Is

These differences reflect real semantic boundaries and should not be flattened:

- `write_file.content`
- `append_file.content`
- `edit_lines.new_content`
- `edit_file.old_string` / `new_string`
- `regex_replace.pattern` / `replacement`
- `copy_file.source` / `destination`
- `rename.source` / `destination`
- `patch.diff` / `diff_file` / `mode` / `dry_run`
- `edit_file.replace_all`

### Keep, But Emphasize In Docs/Prompts

These are legitimate behaviors, but they are easy for agents to misuse:

- `read_file` is numbered by default; exact-match edits should usually use
  `line_numbers=false`
- `edit_file(edits=[...])` batch items must be independent; later edits cannot
  rely on earlier ones to create or reshape their target matches
- `edit_lines(edits=[...])` interprets line numbers against the original file
  and applies bottom-to-top automatically
- text-edit tools are UTF-8-only; byte-sensitive or non-UTF8 edits belong to
  `patch`

### Harmonize

These are the highest-value remaining inconsistencies:

- unknown arguments should be rejected consistently across the file-edit family
- single-target destructive edit tools should use `path` as the canonical name
- batch-capable edit tools should continue to use top-level `edits=[...]`
- empty optional placeholder normalization should live in shared tooling rather
  than scattered one-off logic

## Design Decisions And Rationale

### 1. Standardize the outer contract, not the inner edit model

Agents benefit most from consistent top-level shapes and validation behavior.
They do not benefit from collapsing meaningful parameter names into a generic
API that obscures what each tool actually does.

### 2. Prefer explicit schema rejection over silent argument dropping

Silent filtering of unexpected args makes tool failures harder to diagnose and
encourages false confidence in malformed calls. The file-edit family should fail
fast instead.

### 3. Treat `path` as canonical, aliases as compatibility shims

`patch(target=...)` exists for compatibility, but it should not remain an equal
first-class public shape in docs and prompts. Canonical naming should converge
on `path` for single-target file-edit tools.

### 4. Consolidate placeholder normalization at the boundary

Several recent bugfixes addressed callers that sent omitted optional params as
empty strings. That behavior should be normalized once in a shared helper for
relevant tools, rather than patched case-by-case forever.

## Implementation Details

### Phase 1: Strict Unknown-Argument Rejection

Files:

- `nexus3/skill/builtin/read_file.py`
- `nexus3/skill/builtin/write_file.py`
- `nexus3/skill/builtin/edit_file.py`
- `nexus3/skill/builtin/edit_lines.py`
- `nexus3/skill/builtin/append_file.py`
- `nexus3/skill/builtin/regex_replace.py`
- `nexus3/skill/builtin/patch.py`
- `nexus3/skill/builtin/copy_file.py`
- `nexus3/skill/builtin/rename.py`
- `nexus3/skill/builtin/mkdir.py`
- tests under `tests/unit/skill/`, `tests/unit/test_skill_validation.py`, and
  `tests/integration/test_file_editing_skills.py`

Work:

- Add `additionalProperties: false` to the file-edit family schemas.
- Add focused regressions proving unknown args are rejected clearly.
- Keep internal framework params such as `_parallel` unaffected.

### Phase 2: Canonical Path Naming Cleanup

Files:

- `nexus3/skill/builtin/patch.py`
- `nexus3/session/path_semantics.py`
- `nexus3/session/enforcer.py`
- relevant tests and docs

Work:

- Keep `patch.target` as a compatibility alias.
- Continue to prefer and document `path` everywhere user-facing.
- Consider whether to emit a compatibility hint or telemetry when `target` is
  used, but do not hard-remove it in this slice.

### Phase 3: Shared Placeholder Normalization

Files:

- likely `nexus3/skill/base.py` or a new shared helper module in
  `nexus3/skill/` or `nexus3/core/`
- affected file-edit tools:
  - `edit_file`
  - `edit_lines`
  - `patch`
  - any other file-edit tool with optional free-form string params that treat
    `""` as omitted

Work:

- Create a narrow shared normalization helper for omitted optional placeholders.
- Apply it only where the runtime contract explicitly treats blank optional
  values as omission, not as meaningful content.
- Remove duplicated one-off normalization branches where feasible.

### Phase 4: Docs And Prompt Alignment

Files:

- `nexus3/defaults/NEXUS-DEFAULT.md`
- `AGENTS_NEXUS3SKILLSCAT.md`
- `nexus3/skill/README.md`
- `README.md`
- `CLAUDE.md`
- `AGENTS.md`

Work:

- Make the canonical contract rules explicit:
  - `path` for single-target file-edit tools
  - `edits=[...]` for batch-capable edit tools
  - unknown args fail closed
- Keep the legitimate tool-specific notes prominent instead of hiding them in
  long prose.

## Testing Strategy

- Focused `ruff check` on touched skill, base, and test files.
- Focused unit coverage for per-tool schema behavior and normalization.
- Focused integration coverage for file-edit tool flows where argument-shape
  compatibility matters.
- `git diff --check` before commit.

## Implementation Checklist

- [x] Record approved keep/note/harmonize decisions.
- [x] Add plan index entry.
- [x] Phase 1: reject unknown args consistently across the file-edit family.
- [x] Phase 2: complete canonical `path` cleanup for `patch` docs/semantics.
- [ ] Phase 3: add shared placeholder-normalization helper and remove duplicate
      one-off branches where appropriate.
- [ ] Phase 4: sync prompts/docs/status files.
- [ ] Run focused validation and record results in `AGENTS.md`.

## Documentation Updates

- Keep a concise “contract rules” block in the default prompt docs for the
  file-edit family.
- Explicitly distinguish:
  - semantic parameter differences that are intentional
  - outer-contract differences that are being standardized
- Record the next adjacent follow-up: run a similar contract audit for other
  tool families after the file-edit slice is complete.
