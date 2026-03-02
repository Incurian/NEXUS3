# Architecture Milestone Schedule (2026-03-02)

## Overview

This schedule turns the A-H architecture plans into execution milestones with dependency gates, owner placeholders, and ship criteria.

## Milestone Order

### M0: Foundation and Safety Harness

Target scope:
- Plan H Phase 1 (schema inventory/models, no behavior flip)
- Plan A Phase 0 (authorization inventory + kernel interface)
- Baseline tests/fixtures for Plan E/F migration harness

Owners:
- `Owner H: TBD`
- `Owner A: TBD`
- `Owner E/F harness: TBD`

Dependencies:
- None

Exit gates:
- New schema and kernel interfaces merged behind behavior-preserving adapters.
- Added baseline regression fixtures for context compile and patch byte roundtrips.
- CI green on `.venv/bin/pytest tests/ -v`, `.venv/bin/ruff check nexus3/`, `.venv/bin/mypy nexus3/`.

### M1: Boundary Enforcement Wave

Target scope:
- Plan D Phases 1-3 (filesystem gateway + multi-file tool migration)
- Plan H Phase 2 (ingress schema wiring with compatibility warnings)
- Plan G Phase 1-2 (safe sink API + high-risk path migration)

Owners:
- `Owner D: TBD`
- `Owner H: TBD`
- `Owner G: TBD`

Dependencies:
- M0 complete

Exit gates:
- `outline`, `concat_files`, `grep`, `glob_search` enforce per-file allowed/blocked decisions.
- Malformed RPC/mcp inputs fail through typed validators (compat mode enabled if needed).
- High-risk untrusted terminal outputs routed through safe sink.
- Security regression suite for blocked-path/symlink/terminal payloads passing.

### M2: Authorization and Concurrency Wave

Target scope:
- Plan A Phases 1-3 (route checks through kernel, remove duplicate branches)
- Plan C Phases 1-3 (immutable request context + skill statelessness)
- Plan H Phase 3 (strict mode default flip where safe)

Owners:
- `Owner A: TBD`
- `Owner C: TBD`
- `Owner H strict flip: TBD`

Dependencies:
- M1 complete

Exit gates:
- All lifecycle/tool authorization uses kernel path.
- No shared mutable requester state in global dispatcher path.
- Parallel skill execution tests prove no cross-call mutable state leaks.
- Strict schema mode default enabled for approved ingress surfaces.

### M3: Data Integrity Wave

Target scope:
- Plan F Phases 1-4 (Patch AST v2 + byte_strict path + safer target resolution)
- Plan E Phases 1-2 (context compiler with invariants; provider parity)

Owners:
- `Owner F: TBD`
- `Owner E: TBD`

Dependencies:
- M2 complete

Exit gates:
- Patch apply preserves whitespace/newline semantics in byte_strict mode.
- Ambiguous patch targets fail closed.
- Provider pipelines consume invariant-checked compiled context.
- No orphan tool-result messages in compiler outputs.

### M4: Delegation and Strategic Evolution

Target scope:
- Plan B Phases 1-4 (capability tokens in-process, optional HTTP, deprecate legacy identity path)
- Plan E Phases 3-4 (graph model introduction and compiler-backed compaction/truncation)
- Plan G Phase 3-4 (complete sink migration, cleanup)

Owners:
- `Owner B: TBD`
- `Owner E: TBD`
- `Owner G: TBD`

Dependencies:
- M3 complete

Exit gates:
- Capability-based delegation active on primary paths; legacy identity path deprecated.
- Graph-backed context path validated for parity and invariants.
- Terminal sink boundary fully adopted across display/CLI paths.

## Cross-Milestone Dependency Rules

1. Do not start Plan B deprecation work before Plan A + Plan C baseline is stable.
2. Do not flip strict schemas globally before compatibility diagnostics are verified in M1/M2.
3. Do not flip patch defaults to byte_strict before M3 fidelity tests are consistently green.
4. Keep one architecture owner accountable per plan, even when implementation contributors are multiple.

## Recommended Team Slice

1. Track A+C under one lead (`Auth/Context lead`) to avoid duplicated context plumbing.
2. Track D+G+H under one lead (`Boundary lead`) because all are ingress/egress hardening.
3. Track E+F under one lead (`Data integrity lead`) due to shared invariants/fidelity concerns.
4. Bring B online only after A+C API surfaces settle.

## Reporting Cadence

- Weekly architecture sync with per-plan status:
- `Not Started`
- `In Progress`
- `Blocked`
- `Ready for Review`
- `Merged`

Required status payload per plan:
- Current phase
- PR links
- Test status
- Known risks
- Next gate date

## Deferred Validation Tracking (Post-M4)

Still required after implementation waves:
1. Long soak/performance validation under representative workloads.
2. Windows-native validation on actual Windows hosts.
3. Timing-sensitive TOCTOU/lifecycle race validation under high concurrency.
4. Real terminal red-team validation across emulator variants.

## Related Documents

- [Reviews Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- [Plans Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/plans/README.md)
- [Canonical Review Master Final](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- [Architecture Investigation](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- [Architecture Milestone Schedule](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
