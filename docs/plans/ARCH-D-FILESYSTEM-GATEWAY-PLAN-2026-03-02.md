# Plan D: Unified Filesystem Access Gateway (2026-03-02)

## Overview

Create a single filesystem access layer that enforces allowed/blocked path decisions per resolved file for all multi-file tools.

## Scope

Included:
- New shared access gateway module.
- Migrate `outline`, `concat_files`, `grep`, and `glob` to gateway.
- Enforce per-entry path checks and symlink-safe access behavior.

Deferred:
- Broad performance optimization beyond required guardrails.

Excluded:
- Full virtual filesystem abstraction.

## Design Decisions and Rationale

1. Every candidate file must be authorized at use time, not just base-directory validation.
2. Gateway must consume existing decision primitives (`PathDecisionEngine`, `PathResolver`).
3. Keep fast-path scan performance while enforcing policy post-filtering.
4. Migration must remove direct per-candidate `validate_path(...allowed_paths=...)` usage in multi-file loops and route through ServiceContainer-aware gateway decisions.

## Implementation Details

Primary files to change:
- [core/path_decision.py](/home/inc/repos/NEXUS3/nexus3/core/path_decision.py)
- [core/resolver.py](/home/inc/repos/NEXUS3/nexus3/core/resolver.py)
- [skill/builtin/outline.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/outline.py)
- [skill/builtin/concat_files.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/concat_files.py)
- [skill/builtin/grep.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/grep.py)
- [skill/builtin/glob_search.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/glob_search.py) (`glob` skill)
- New: `nexus3/core/filesystem_access.py`

Phases:
1. Implement gateway APIs (`iter_authorized_files`, `read_authorized_file`, optional match filtering).
2. Migrate one tool at a time with behavior parity tests.
3. Enforce blocked-path policy consistently across all migrated tools.
4. Add perf guardrails for large-tree scans.

## Testing Strategy

- Add security regression tests for symlink escape and blocked-path bypass per tool.
- Add cross-tool consistency tests.
- Add large-directory performance guard tests (bounded runtime thresholds).

## Implementation Checklist

- [x] Add filesystem gateway.
- [x] M1 first migration slice: migrate `glob` to gateway + targeted parity tests.
- [ ] Migrate `outline`.
- [ ] Migrate `concat_files`.
- [ ] Migrate `grep` and `glob`.
- [ ] Add blocked-path and symlink regression suite.

## Documentation Updates

- Update skill docs for path-policy behavior consistency.
- Update security notes for filesystem boundary guarantees.

## Related Documents

- [Reviews Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- [Plans Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/plans/README.md)
- [Canonical Review Master Final](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- [Architecture Investigation](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- [Architecture Milestone Schedule](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
