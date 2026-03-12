# Release v1.0.0 Plan (2026-03-12)

## Overview

Prepare and publish the first stable `v1.0.0` release of NEXUS3.

This slice covers the canonical version bump, release-note publication, and
tagging so the repository state and distributed package metadata all agree on
the first stable release.

## Scope

Included:

- bump canonical version metadata to `1.0.0`
- update user-visible version strings that still show `0.1.0`
- add a top-level release note/changelog entry for `v1.0.0`
- call out the recent runtime dependency addition and reinstall requirement
- tag and push `v1.0.0`

Deferred:

- broader retrospective writeup for all pre-1.0 milestones
- packaging/distribution changes beyond the existing editable-install flow

Excluded:

- new feature work
- dependency changes beyond documenting the already-added runtime dependency

## Design Decisions And Rationale

### 1. Use `v1.0.0` as the first stable semantic version

Behavior:

- canonical package version becomes `1.0.0`
- git tag becomes `v1.0.0`

Rationale:

- the project is now being treated as feature-complete and merge-stable

### 2. Keep release notes in a canonical top-level changelog

Behavior:

- add `CHANGELOG.md` with a `v1.0.0` release entry

Rationale:

- there was no established release-notes location yet, so a top-level
  changelog is the simplest durable convention

### 3. Make the reinstall note explicit

Behavior:

- release notes explicitly tell existing checkouts to rerun their install step
  because `psutil` was added recently as a runtime dependency

Rationale:

- this is the easiest failure mode for upgraders to hit after pulling the new
  release

## Implementation Details

Primary files:

- `pyproject.toml`
- `nexus3/__init__.py`
- `nexus3/cli/repl.py`
- `README.md`
- `CHANGELOG.md`

Supporting docs:

- `AGENTS.md`
- `docs/plans/README.md`

## Testing Strategy

Validation should confirm:

- version strings are consistent across the canonical surfaces
- touched files pass focused lint checks
- `import nexus3; print(nexus3.__version__)` reports `1.0.0`
- working tree formatting remains clean

## Documentation Updates

- add and index this plan doc
- update running status in `AGENTS.md`
- publish the new top-level changelog entry

## Checklist

- [x] Add and index the plan doc.
- [x] Bump canonical version metadata to `1.0.0`.
- [x] Add `v1.0.0` release notes with reinstall guidance.
- [x] Sync any user-visible version strings.
- [x] Run focused validation.
- [ ] Tag and push `v1.0.0`.

Validation completed:

- `.venv/bin/python -c "import nexus3; print(nexus3.__version__)"` (`1.0.0`)
- `.venv/bin/ruff check pyproject.toml README.md CHANGELOG.md AGENTS.md docs/plans/README.md docs/plans/RELEASE-V1.0.0-PLAN-2026-03-12.md nexus3/__init__.py nexus3/cli/repl.py`
- `git diff --check`
