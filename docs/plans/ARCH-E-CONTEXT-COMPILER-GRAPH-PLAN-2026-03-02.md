# Plan E: Context Compiler and Graph Model (2026-03-02)

## Overview

Introduce an invariant-enforcing context compiler first, then evolve to a graph-backed context model to reduce duplication and prevent malformed message sequences.

## Scope

Included:
- Add compiled conversation IR with invariant checks.
- Route providers through compiler output.
- Add graph model phase after compiler parity is established.

Deferred:
- Full replacement of existing context manager internals until parity proven.

Excluded:
- New prompt strategy features unrelated to invariants.

## Design Decisions and Rationale

1. Start with compiler layer to capture value without immediate full graph migration.
2. Enforce tool-call/result pairing and role sequence invariants centrally.
3. Keep provider-specific formatting as output adapters on a shared compiled model.

## Implementation Details

Primary files to change:
- [context/manager.py](/home/inc/repos/NEXUS3/nexus3/context/manager.py)
- [context/compaction.py](/home/inc/repos/NEXUS3/nexus3/context/compaction.py)
- [provider/openai_compat.py](/home/inc/repos/NEXUS3/nexus3/provider/openai_compat.py)
- [provider/anthropic.py](/home/inc/repos/NEXUS3/nexus3/provider/anthropic.py)
- [core/types.py](/home/inc/repos/NEXUS3/nexus3/core/types.py)
- New: `nexus3/context/compiler.py`
- Later new: `nexus3/context/graph.py`

Phases:
1. Build compiler IR and invariants over existing message list.
2. Route both providers through compiler output with parity tests.
3. Introduce optional graph representation for provenance/compaction edges.
4. Switch compaction/truncation to graph-aware compilation.

## Testing Strategy

- Provider parity tests for identical transcript inputs.
- Property tests for no orphan tool results and valid role order.
- Compaction/truncation equivalence tests before and after graph phase.

## Implementation Checklist

- [ ] Add compiler IR and invariant checker.
- [ ] Integrate with provider adapters.
- [ ] Add graph model prototype.
- [ ] Migrate compaction/truncation through compiler pipeline.

## Documentation Updates

- Update context README with compiler/graph architecture.
- Remove stale docs about previous linear-only assumptions.

## Related Documents

- [Reviews Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- [Plans Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/plans/README.md)
- [Canonical Review Master Final](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- [Architecture Investigation](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- [Architecture Milestone Schedule](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
