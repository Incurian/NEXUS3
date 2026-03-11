# Dependency License And Telemetry Audit Plan (2026-03-10)

## Overview

NEXUS3 ships under MIT and depends on a small Python runtime stack plus a
larger development/test toolchain. This audit checks the tracked dependency
surface and the currently installed `.venv` artifact set for two questions:

- whether the dependency licenses are compatible with distributing NEXUS3 as an
  MIT-licensed project
- whether any dependency appears to phone home or emit telemetry outside the
  explicit network operations NEXUS3 invokes

The output of this slice is a written audit with concrete findings, evidence,
and follow-up actions where the current dependency story is unclear or drifted.

## Scope

### Included

- Tracked Python dependency manifests in `pyproject.toml`
- Build dependency declared in `[build-system]`
- Installed `.venv` distributions needed to run or develop NEXUS3
- Direct and transitive Python dependencies reachable from the current `.venv`
- License compatibility review
- Telemetry / unsolicited network behavior review

### Deferred

- Untracked local-only trees such as `editors/` unless they become part of the
  committed project dependency surface
- Full legal opinion on every notice/attribution obligation beyond identifying
  concrete obligations and likely compatibility risks

### Excluded

- Third-party model/provider services themselves (OpenAI, Anthropic, etc.)
  beyond the local client libraries in the dependency graph
- NPM/editor-extension dependencies in untracked local worktrees

## Design Decisions And Rationale

### 1. Audit both manifests and the installed environment

The tracked manifest is the canonical intent, but the installed `.venv`
captures the actual transitive artifact set in use today. Reviewing both helps
catch packaging drift and stale metadata.

### 2. Use two evidence channels

- local artifact evidence: installed package metadata, license files, and
  source-grep of installed code
- upstream evidence: official package/docs/repository sources for licenses and
  telemetry claims where local metadata is absent or ambiguous

### 3. Separate compatibility from obligations

Some licenses can be compatible with an MIT-licensed project while still
imposing attribution or notice obligations. The audit should report both.

## Implementation Details

### Phase 1: dependency inventory

Files:

- `pyproject.toml`
- `.venv/.../site-packages/*dist-info`

Work:

- enumerate direct runtime/dev/build dependencies
- enumerate installed transitive distributions
- identify manifest/environment drift

### Phase 2: license and telemetry audit

Files:

- installed dist metadata / license files
- dependency source trees under `.venv`

Work:

- classify each dependency license
- flag any potentially incompatible or obligation-heavy licenses
- grep installed sources for telemetry / analytics / update-check behavior
- confirm ambiguous cases against official upstream sources

### Phase 3: write findings and recommendations

Files:

- audit report under `docs/`
- `AGENTS.md` status note if this becomes the active tracked slice

Work:

- summarize dependency set and risk levels
- call out packaging drift or documentation gaps
- recommend concrete remediations if needed

## Testing Strategy

- no code tests required unless the audit uncovers a repo bug that needs code
  changes
- validate any generated report/docs with `git diff --check`

## Implementation Checklist

- [x] Inventory tracked and installed dependency surfaces.
- [x] Audit license compatibility and obligations.
- [x] Audit telemetry / unsolicited network behavior.
- [x] Write the audit report and recommendations.

## Closeout

Audit report:

- `docs/reviews/DEPENDENCY-LICENSE-AND-TELEMETRY-AUDIT-2026-03-10.md`

Key conclusions:

- current Python dependency set appears compatible with distributing NEXUS3
  under MIT
- no unsolicited telemetry / analytics behavior was found in the installed
  Python dependency sources
- notable follow-up items are dependency-surface hygiene rather than license
  blockers:
  - stale editable metadata still declares `websockets`
  - `aiohttp` remains referenced in test-support code/docs without a current
    declaration in `pyproject.toml`

## Validation

- `git diff --check -- docs/plans/DEPENDENCY-LICENSE-AND-TELEMETRY-AUDIT-PLAN-2026-03-10.md docs/plans/README.md docs/reviews/README.md docs/reviews/DEPENDENCY-LICENSE-AND-TELEMETRY-AUDIT-2026-03-10.md`

## Documentation Updates

- Add this plan to `docs/plans/README.md`.
- Add the final audit report under `docs/`.
