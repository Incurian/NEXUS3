# Ruff Backlog Closeout Plan (2026-03-10)

## Overview

Repo-wide Ruff currently fails on a long-standing backlog concentrated in test
files. The current failure set is dominated by safe hygiene issues
(`unused-import`, `unsorted-imports`) plus manual cleanup items (`line-too-long`,
`unused-variable`, broad exception assertions).

This slice aims to reduce the backlog to zero and restore a clean
`.venv/bin/ruff check nexus3/ tests/` result without changing test behavior.

## Scope

### Included

- Repo-wide Ruff cleanup for `nexus3/` and `tests/`
- Safe autofixes where Ruff can rewrite imports/annotations cleanly
- Manual cleanup for remaining `E501`, `F841`, `B017`, and similar issues

### Deferred

- Broader test refactors that are not required for lint compliance
- Non-Ruff style rewrites outside files touched by the current backlog

### Excluded

- Behavioral code changes unrelated to satisfying the current lint failures

## Design Decisions And Rationale

### 1. Safe autofix first

Ruff can automatically clear a large fraction of the backlog with low risk.
That should happen before manual editing so the remaining work set is stable.

### 2. Split manual cleanup by disjoint file groups

The leftover issues are concentrated in a few test clusters and can be fixed in
parallel without merge conflicts.

### 3. Preserve test intent

Line wraps, import cleanup, and exception specificity changes should not alter
what a test is asserting.

## Implementation Details

### Phase 1: inventory

Work:

- capture repo-wide Ruff totals and top offending files
- separate safe autofixable vs manual issues

### Phase 2: safe autofix

Work:

- run Ruff with `--fix` across `nexus3/` and `tests/`
- review resulting diff for accidental semantic churn

### Phase 3: manual closeout

Work:

- fix remaining long lines, unused locals, and broad exception assertions
- use parallel workers on disjoint file clusters if helpful

### Phase 4: validation

Work:

- rerun `.venv/bin/ruff check nexus3/ tests/`
- rerun focused pytest only if a manual lint fix risks changing test behavior

## Execution Notes

- Safe autofix pass:
  - `.venv/bin/ruff check nexus3/ tests/ --fix`
  - reduced the backlog from 156 findings to 74 remaining manual issues
- Manual closeout:
  - split the manual cleanup across parallel workers on disjoint test-file
    clusters
  - cleaned the remaining long lines, dead locals, and broad exception
    assertions without changing test intent
- Final validation:
  - `.venv/bin/ruff check nexus3/ tests/` now passes
  - `git diff --check` passes
  - no pytest rerun was needed because the remaining edits were lint-only test
    cleanups and the full suite had already passed earlier in the session

## Testing Strategy

- `.venv/bin/ruff check nexus3/ tests/`
- targeted pytest only for touched test clusters if needed

## Implementation Checklist

- [x] Capture current Ruff backlog shape.
- [x] Apply safe Ruff autofixes.
- [x] Fix remaining manual lint failures.
- [x] Re-run Ruff to zero.

## Documentation Updates

- Add this plan to `docs/plans/README.md`.
