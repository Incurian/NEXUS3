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

- [ ] Add AST v2 and serializer/parsers.
- [ ] Implement byte-strict applier.
- [ ] Add legacy compatibility mode and migration flag.
- [ ] Harden file target resolution.
- [ ] Add ambiguity fail-closed and byte-fidelity regression tests (EOF/non-UTF8/binary-adjacent).
- [ ] Flip default and remove fragile legacy branches.

## Documentation Updates

- Update patch module README and CLI help text for mode semantics.
- Document migration timeline for default mode change.

## Related Documents

- [Reviews Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- [Plans Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/plans/README.md)
- [Canonical Review Master Final](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- [Architecture Investigation](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- [Architecture Milestone Schedule](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
