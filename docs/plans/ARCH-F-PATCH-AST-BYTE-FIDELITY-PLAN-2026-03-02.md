# Plan F: Patch AST with Byte-Fidelity Contract (2026-03-02)

## Overview

Replace text-normalizing patch handling with an AST and applier contract that preserve bytes, newline semantics, and EOF markers by default.

## Scope

Included:
- Patch AST v2 carrying raw line bytes and newline metadata.
- Byte-strict apply mode and staged default migration.
- Safer file-target resolution to avoid basename ambiguity.

Deferred:
- Removal of legacy tolerant path until compatibility period completes.

Excluded:
- Support for unrelated patch formats.

## Design Decisions and Rationale

1. Matching leniency and output fidelity must be decoupled.
2. Preserve bytes unless explicit normalization is requested.
3. Ambiguous file targeting must fail closed.

## Implementation Details

Primary files to change:
- [patch/parser.py](/home/inc/repos/NEXUS3/nexus3/patch/parser.py)
- [patch/applier.py](/home/inc/repos/NEXUS3/nexus3/patch/applier.py)
- [patch/validator.py](/home/inc/repos/NEXUS3/nexus3/patch/validator.py)
- [skill/builtin/patch.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/patch.py)
- New: `nexus3/patch/ast_v2.py`

Phases:
1. Add AST v2 and roundtrip fixtures.
2. Implement byte-strict parse/apply path.
3. Add mode flag (`legacy` vs `byte_strict`) with tests.
4. Tighten file selection: exact path preferred, ambiguity fails.
5. Flip default to byte-strict after confidence window.

## Testing Strategy

- Golden tests for trailing whitespace and EOF marker preservation.
- CRLF/LF mixed newline preservation tests.
- Non-UTF8 and binary-adjacent patch safety tests.
- Ambiguous basename targeting failure tests.
- Migration tests replacing current basename-accept behavior with ambiguity fail-closed behavior.

## Implementation Checklist

- [x] Add AST v2 parser/projection foundation (raw-line/newline metadata, v2 parse hook, v2->v1 applier bridge).
- [x] Implement byte-strict applier entrypoint (`apply_patch_byte_strict`) for AST-v2 patches (default path unchanged).
- [ ] Add legacy compatibility mode and migration flag.
- [ ] Harden file target resolution.
- [ ] Add ambiguity fail-closed and byte-fidelity regression tests (EOF/non-UTF8/binary-adjacent).
- [ ] Flip default and remove fragile legacy branches.

Status note (2026-03-05, M3 Plan F Phase 1):
- Added `nexus3/patch/ast_v2.py` with typed v2 AST models carrying raw bytes and newline metadata.
- Added additive parser hook `parse_unified_diff_v2(...)` in `nexus3/patch/parser.py` with parity projection helpers.
- Added minimal applier integration bridge so `apply_patch(...)` accepts `PatchFileV2` without changing existing strict/tolerant/fuzzy semantics.
- Expanded fixture-driven patch byte roundtrip baselines for explicit no-EOL marker and whitespace-sensitive payload cases.
- Focused gates passed:
  - `.venv/bin/pytest -q tests/unit/patch/test_parser.py tests/unit/patch/test_applier.py tests/unit/patch/test_byte_roundtrip_baseline.py`
  - `.venv/bin/ruff check nexus3/patch tests/unit/patch`
  - `.venv/bin/mypy nexus3/patch`

Status note (2026-03-05, M3 Plan F Phase 2):
- Added explicit byte-strict apply entrypoint in `nexus3/patch/applier.py`:
  - `apply_patch_byte_strict(content: str, patch: PatchFileV2, ...) -> ApplyResult`
  - preserves newline/EOF semantics via per-line newline tokens and `\ No newline at end of file` marker enforcement.
  - keeps existing `apply_patch(...)` strict/tolerant/fuzzy semantics unchanged.
- Added focused Phase 2 regressions in:
  - `tests/unit/patch/test_byte_strict_apply_phase2.py`
  - `tests/fixtures/arch_baseline/patch_mixed_newline_update.diff`
- Focused gates passed:
  - `.venv/bin/pytest -q tests/unit/patch/test_byte_strict_apply_phase2.py tests/unit/patch/test_applier.py tests/unit/patch/test_parser.py tests/unit/patch/test_byte_roundtrip_baseline.py tests/unit/patch/test_validator.py`
  - `.venv/bin/ruff check nexus3/patch tests/unit/patch`
  - `.venv/bin/mypy nexus3/patch`

## Documentation Updates

- Update patch module README and CLI help text for mode semantics.
- Document migration timeline for default mode change.

## Related Documents

- [Reviews Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- [Plans Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/plans/README.md)
- [Canonical Review Master Final](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- [Architecture Investigation](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- [Architecture Milestone Schedule](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
