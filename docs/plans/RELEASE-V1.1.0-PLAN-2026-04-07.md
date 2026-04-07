# Release v1.1.0 Plan (2026-04-07)

## Overview

Prepare and publish `v1.1.0` for the current post-`v1.0.0` hardening and tool
surface simplification work now merged on `master`.

This slice covers the canonical version bump, release-note publication, and
tagging so package metadata, user-visible strings, and git history all agree
on `v1.1.0`.

## Scope

Included:

- bump canonical package version metadata to `1.1.0`
- update user-visible release strings that still show `v1.0.0`
- add a top-level changelog entry for `v1.1.0`
- tag and push `v1.1.0`

Deferred:

- longer retrospective notes beyond the changelog summary
- release automation or packaging workflow changes

Excluded:

- new feature work beyond the already-merged branch content
- dependency or installer changes

## Design Decisions And Rationale

### 1. Treat the merged tool-surface and provider hardening work as a minor release

Behavior:

- canonical package version becomes `1.1.0`
- git tag becomes `v1.1.0`

Rationale:

- the merged work added new public tool names, improved compatibility and
  resilience, and materially changed the user-facing prompt/tool surface
  without being a breaking rename of the existing package

### 2. Keep release notes in the top-level changelog

Behavior:

- `CHANGELOG.md` gains a new `v1.1.0` entry above `v1.0.0`

Rationale:

- the repository already established `CHANGELOG.md` as the canonical release
  note location in the `v1.0.0` release

### 3. Keep version surfaces narrowly scoped

Behavior:

- update the canonical metadata, CLI banner, README release text, and handoff
  docs
- leave unrelated protocol/schema/example versions untouched

Rationale:

- many files contain independent protocol or fixture versions that are not the
  package release version and should not be churned during a release bump

## Implementation Details

Primary files:

- `pyproject.toml`
- `nexus3/__init__.py`
- `nexus3/cli/repl.py`
- `README.md`
- `CHANGELOG.md`

Supporting docs:

- `docs/plans/README.md`
- `AGENTS.md`

## Testing Strategy

Validation should confirm:

- canonical version strings are consistent across the release-facing surfaces
- `import nexus3; print(nexus3.__version__)` reports `1.1.0`
- touched files pass focused lint checks
- the working tree formatting remains clean
- the `v1.1.0` tag points at the release commit

## Documentation Updates

- add and index this release plan
- add the `v1.1.0` changelog entry
- update the current handoff in `AGENTS.md`

## Checklist

- [x] Add and index the plan doc.
- [x] Bump canonical version metadata to `1.1.0`.
- [x] Add `v1.1.0` release notes.
- [x] Sync user-visible version strings.
- [x] Run focused validation.
- [x] Commit the release bump.
- [ ] Tag and push `v1.1.0`.

Validation completed:

- `.venv/bin/python -c "import nexus3; print(nexus3.__version__)"` (`1.1.0`)
- `.venv/bin/ruff check pyproject.toml README.md CHANGELOG.md AGENTS.md docs/plans/README.md docs/plans/RELEASE-V1.1.0-PLAN-2026-04-07.md nexus3/__init__.py nexus3/cli/repl.py`
- `git diff --check`
