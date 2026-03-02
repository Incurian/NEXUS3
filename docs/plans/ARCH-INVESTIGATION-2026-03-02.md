# Architecture Investigation and Planning (2026-03-02)

## Overview

This document consolidates investigation results for eight architectural proposals raised during review remediation planning.

Investigation method:
- Parallel Codex explorer subagents (no Nexus runtime agents used).
- Static code-path analysis against current repository state.
- Prioritized for risk reduction against findings in `docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md`.

## Value Verdict

All eight proposals are valuable enough to plan.

Priority order (recommended):
1. H: Strict schema gates at boundaries
2. D: Unified filesystem access layer
3. A: Single authorization kernel
4. C: Request-scoped immutable execution context
5. F: Patch AST with byte-fidelity contract
6. G: Terminal safe sink boundary
7. B: Capability tokens (after A/C baseline)
8. E: Context graph + invariant-enforcing compiler (start with compiler-only phase)

## Scope

Included:
- Investigation outcomes and value decision for A-H.
- One implementation plan per proposal under `docs/plans/`.

Deferred:
- Live exploit validation and soak/perf proof where explicit runtime environments are required.
- Windows-native behavior verification.

Excluded:
- Immediate implementation work in production code.

## Design Decisions and Rationale

1. Plan each proposal separately to allow independent ownership and sequencing.
2. Keep plans behavior-preserving in early phases and defer breaking changes to gated flips.
3. Require dedicated tests per architecture step before broad rollout.

## Plan Index

1. [ARCH-A-AUTH-KERNEL-PLAN-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-A-AUTH-KERNEL-PLAN-2026-03-02.md)
2. [ARCH-B-CAPABILITY-TOKENS-PLAN-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-B-CAPABILITY-TOKENS-PLAN-2026-03-02.md)
3. [ARCH-C-REQUEST-CONTEXT-PLAN-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-C-REQUEST-CONTEXT-PLAN-2026-03-02.md)
4. [ARCH-D-FILESYSTEM-GATEWAY-PLAN-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-D-FILESYSTEM-GATEWAY-PLAN-2026-03-02.md)
5. [ARCH-E-CONTEXT-COMPILER-GRAPH-PLAN-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-E-CONTEXT-COMPILER-GRAPH-PLAN-2026-03-02.md)
6. [ARCH-F-PATCH-AST-BYTE-FIDELITY-PLAN-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-F-PATCH-AST-BYTE-FIDELITY-PLAN-2026-03-02.md)
7. [ARCH-G-TERMINAL-SAFE-SINK-PLAN-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-G-TERMINAL-SAFE-SINK-PLAN-2026-03-02.md)
8. [ARCH-H-STRICT-SCHEMA-GATES-PLAN-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-H-STRICT-SCHEMA-GATES-PLAN-2026-03-02.md)

## Testing Strategy

Global strategy across all plans:
- Add targeted unit tests first.
- Add integration/security tests for boundary behavior next.
- Run full local quality gates after each architecture milestone:
- `.venv/bin/pytest tests/ -v`
- `.venv/bin/ruff check nexus3/`
- `.venv/bin/mypy nexus3/`

## Implementation Checklist

- [x] Investigate A-H with Codex subagents.
- [x] Produce plan docs for each proposal.
- [ ] Assign owners and milestone windows.
- [ ] Execute in priority order with milestone PRs.
- [ ] Update review master with links to merged fixes.

## Documentation Updates

When each proposal is implemented:
- Update module READMEs for affected subsystems.
- Update [AGENTS.md](/home/inc/repos/NEXUS3/AGENTS.md) and [CLAUDE.md](/home/inc/repos/NEXUS3/CLAUDE.md) where behavior/workflow changes.

## Milestone Schedule

Execution schedule:
- [ARCH-MILESTONE-SCHEDULE-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)

## Related Documents

- [Reviews Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- [Plans Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/plans/README.md)
- [Canonical Review Master Final](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- [Architecture Investigation](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- [Architecture Milestone Schedule](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
