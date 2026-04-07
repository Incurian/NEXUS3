# Patch Tool Robustness Plan (2026-04-07)

## Overview

The `patch` tool is mostly aligned with the repo's fail-closed editing model,
but two rough edges remain:

- `dry_run` can report a failure for `mode="fuzzy"` even when the real apply
  path would succeed.
- malformed hunk bodies with missing non-empty context prefixes produce
  misleading validation failures instead of a targeted parse-level guidance
  error.

This slice keeps the conservative single-target and byte-fidelity behavior
intact while removing those two UX inconsistencies.

## Scope

### Included

- Make `patch(..., dry_run=True)` simulate the selected apply mode in memory so
  dry-run results match real execution semantics for `strict`, `tolerant`, and
  `fuzzy`.
- Add targeted malformed-hunk detection for non-empty hunk lines that are
  missing the required leading unified-diff prefix.
- Add focused regressions for both behaviors.
- Update the patch module and skill documentation to describe the refined
  behavior.

### Deferred

- Changing the public parser API to surface structured parse diagnostics.
- Broad parser heuristics that automatically coerce malformed non-empty hunk
  lines into context.
- Any loosening of exact-path / ambiguous-basename fail-closed behavior for
  multi-file diffs.

### Excluded

- Replacing byte-strict apply semantics with a more permissive default.
- Altering permissions or path-validation behavior for the patch skill.

## Design Decisions And Rationale

### 1. Dry-run should reflect the chosen execution mode

Users rely on `dry_run` to answer "would this exact call succeed?" Returning a
validator-only answer for `mode="fuzzy"` is misleading because the real apply
path uses additional matching logic.

### 2. Malformed hunk guidance belongs at the skill boundary

The parser currently remains conservative and additive. A skill-level preflight
can detect the common malformed shape and return an actionable error without
forcing a broader parser API redesign in the same slice.

### 3. Keep fail-closed path resolution unchanged

The path-matching rules are intentionally conservative for a permission-bound
single-file editing tool. This slice improves diagnostics, not targeting
behavior.

## Implementation Details

### Phase 1: Mode-Accurate Dry Run

Files:

- `nexus3/skill/builtin/patch.py`
- `tests/unit/skill/test_patch.py`

Work:

- Reuse the same in-memory apply path for dry-run that real execution uses
  after validation/fixups.
- Preserve strict-mode fast failure for invalid patches.
- Surface apply warnings during dry-run output, especially fuzzy-match notes.

### Phase 2: Malformed Hunk Diagnostics

Files:

- `nexus3/skill/builtin/patch.py`
- `tests/unit/skill/test_patch.py`

Work:

- Detect non-empty hunk body lines that are missing `" "`, `"+"`, or `"-"`
  prefixes before parsing.
- Return a targeted error that explains the required unified-diff prefixes.
- Keep the existing bare-empty-line compatibility behavior unchanged.

### Phase 3: Documentation

Files:

- `nexus3/patch/README.md`
- `nexus3/skill/README.md`
- `docs/plans/README.md`

Work:

- Document that dry-run now reflects the selected apply mode.
- Document the malformed non-empty hunk-line guidance.
- Add this plan to the plans index.

## Testing Strategy

- Focused unit coverage for patch skill dry-run and malformed hunk diagnostics.
- Focused patch module / skill test runs.
- Focused `ruff check` and `mypy` on touched files.
- Repo-required live RPC validation because this changes skill behavior.

## Implementation Checklist

- [x] Add plan file and index entry.
- [x] Align dry-run with actual apply semantics.
- [x] Add malformed-hunk preflight with targeted errors.
- [x] Add regression tests.
- [x] Update docs.
- [x] Run focused validation.
- [x] Run live RPC validation.

## Documentation Updates

- Note in the skill docs that `dry_run` reflects the requested matching mode.
- Note in the patch README that malformed non-empty hunk lines now fail with a
  targeted unified-diff-prefix error instead of a generic mismatch.

## Validation Results

- `.venv/bin/pytest -q tests/unit/skill/test_patch.py tests/unit/patch/test_parser.py tests/unit/patch/test_applier.py tests/unit/patch/test_validator.py tests/unit/patch/test_byte_strict_apply_phase2.py tests/integration/test_file_editing_skills.py -q`
- `.venv/bin/ruff check nexus3/skill/builtin/patch.py tests/unit/skill/test_patch.py`
- `.venv/bin/mypy nexus3/skill/builtin/patch.py`
- `.venv/bin/pytest tests/ -v`
  - `4533 passed, 3 skipped, 22 warnings`
- Live RPC validation on port `9000`:
  - `NEXUS_DEV=1 .venv/bin/python -m nexus3 --serve 9000`
  - `.venv/bin/python -m nexus3 rpc detect --port 9000`
  - `.venv/bin/python -m nexus3 rpc create test-agent --port 9000`
  - `.venv/bin/python -m nexus3 rpc send test-agent "describe your permissions and what you can do" --port 9000`
  - `.venv/bin/python -m nexus3 rpc destroy test-agent --port 9000`
  - `.venv/bin/python -m nexus3 rpc list --port 9000`
- `git diff --check`
