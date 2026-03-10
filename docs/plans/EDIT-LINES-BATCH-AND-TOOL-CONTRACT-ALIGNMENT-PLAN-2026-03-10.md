# Edit Lines Batch And Tool Contract Alignment Plan (2026-03-10)

## Overview

Manual testing exposed a repeated agent confusion point in the file-edit tool family:

- `edit_file` supports batched edits via `edits=[...]`
- `edit_lines` only supports a single top-level line-range edit

That mismatch is easy for agents to blur, and it led directly to malformed
`edit_lines` calls shaped like `{"path": ..., "edits": [{"start_line": ...}]}`.

This plan adds batched `edit_lines` support and uses that implementation pass to
audit and tighten file-edit tool argument consistency where it most affects real
agent behavior.

## Scope

### Included

- Add `edits=[...]` batch support to `edit_lines`.
- Keep single-edit `edit_lines` behavior backward-compatible.
- Define stable batch semantics for line-number edits:
  - line numbers are interpreted against the original file
  - edits are validated atomically
  - application happens bottom-to-top automatically to avoid drift
  - overlapping ranges fail closed
- Update agent-facing docs/prompts to distinguish the batched shapes of
  `edit_file` and `edit_lines`.
- Perform a focused tool-argument consistency audit across the destructive
  file-edit tools and record remaining follow-ups.

### Deferred

- A broader redesign of all file-edit tools into one unified schema.
- Converting other tools to batched forms unless current evidence shows repeated
  agent misuse.
- Retrofitting `edit_file(edits=[])` empty-array semantics in the same slice.

### Excluded

- Changes to patch application semantics beyond documentation alignment.
- New edit tool families or non-file-edit skill contract refactors.

## Design Decisions And Rationale

### 1. Match `edit_file` ergonomics where it helps, not where it hurts

`edit_lines` should accept `edits=[...]` because agents are already trying that
shape. The contract should align at the top level with `edit_file`, but the
batch semantics should remain line-oriented rather than string-match-oriented.

### 2. Interpret batched line ranges against the original file

This removes the need for the caller to reason about line drift across multiple
edits. It also makes the contract easier to explain: provide original ranges,
and NEXUS3 applies them bottom-to-top automatically.

### 3. Reject overlapping ranges explicitly

Overlapping or duplicate line ranges create ambiguous ownership of the same
source lines. Instead of picking an order-dependent behavior, the tool should
fail closed and tell the caller to merge or split the edits.

### 4. Preserve single-edit behavior

Existing top-level `start_line` / `end_line` / `new_content` calls must keep
working unchanged. Batch mode is additive.

## Implementation Details

### `nexus3/skill/builtin/edit_lines.py`

- Add `edits` schema support:
  - each item has `start_line`, optional `end_line`, and `new_content`
- Support two modes:
  - single-edit mode via top-level fields
  - batch mode via `edits=[...]`
- In batch mode:
  - reject mixed top-level single-edit arguments unless they are exact empty
    placeholders
  - reject empty `edits`
  - validate all ranges against original file length
  - reject overlaps
  - apply edits bottom-to-top against the original line-number space
  - preserve line endings and EOF newline semantics

### Tests

- `tests/unit/skill/test_edit_lines.py`
  - add batch success
  - add out-of-order batch success
  - add overlap failure with rollback
  - add empty `edits` failure
  - add mixed-mode rejection
  - add placeholder-argument tolerance in batch mode
- `tests/integration/test_file_editing_skills.py`
  - add atomic batch rollback coverage for `edit_lines`
  - add batch CRLF / EOF-newline preservation coverage if not already implicit

### Documentation

- `nexus3/defaults/NEXUS-DEFAULT.md`
- `README.md`
- `CLAUDE.md`
- `AGENTS_NEXUS3SKILLSCAT.md`
- `nexus3/skill/README.md`

Update all of the above to say:

- `edit_lines` now supports `edits=[...]`
- batch `edit_lines` is atomic
- line numbers are based on the original file
- overlapping ranges fail closed
- this closes one of the main argument-shape mismatches with `edit_file`

## Testing Strategy

- Focused `ruff check` on touched files.
- Focused unit tests for `edit_lines`.
- Focused integration tests for file-editing skills.
- `git diff --check` to catch doc/format regressions.

## Consistency Audit Findings (Deferred Follow-Ups)

The focused audit around this slice found broader tool-contract inconsistencies
worth tracking separately:

- file-edit tool schemas are still permissive overall; unknown args are often
  silently dropped instead of being rejected
- `edit_file` and `patch` still rely on runtime-only invariants for some dual
  argument shapes
- batch capability is still uneven across the file-edit family
- empty-string semantics differ across write-oriented tools
- path argument naming remains mixed (`path`, `source/destination`,
  `path|target`)

Those are recorded as follow-ups rather than folded into this slice, because
the highest-value immediate fix was to close the real `edit_lines`/`edit_file`
batch-shape mismatch first.

## Implementation Checklist

- [x] Add plan index entry.
- [x] Implement `edit_lines` batch schema and execution path.
- [x] Add unit coverage for batch success/failure semantics.
- [x] Add integration coverage for atomic rollback and newline fidelity.
- [x] Update agent-facing docs and prompts.
- [x] Record remaining argument-consistency findings for later follow-up.
- [x] Run focused validation and sync status docs.

## Documentation Updates

- Make `edit_lines` batching explicit everywhere `edit_file(edits)` is already
  documented, to reduce schema-shape cross-contamination.
- Clarify that single-call multiple `edit_lines` operations no longer require
  caller-managed bottom-to-top ordering when using batch mode.
