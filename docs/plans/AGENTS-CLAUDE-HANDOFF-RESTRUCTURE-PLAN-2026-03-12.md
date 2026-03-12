# AGENTS And CLAUDE Handoff Restructure Plan (2026-03-12)

## Overview

Restructure `AGENTS.md` and `CLAUDE.md` so:

- `AGENTS.md` becomes the canonical agent document
- stable guidance stays easy to find
- historical running-status churn is removed
- the repo keeps only the most recent handoff/checkpoint in `AGENTS.md`

## Scope

Included:

- trim `AGENTS.md` down to stable guidance plus one current handoff section
- define a simple handoff SOP that keeps the live checkpoint at the bottom of
  `AGENTS.md`
- trim `CLAUDE.md` to mirrored stable guidance and a pointer back to
  `AGENTS.md`
- update plan indexes and running-status notes to reflect the new workflow

Deferred:

- moving older historical handoff material into archival docs
- broader prose/style refresh beyond the handoff model

Excluded:

- product or runtime behavior changes
- refactoring the companion `AGENTS_NEXUS3*.md` reference docs

## Design Decisions And Rationale

### 1. `AGENTS.md` is the canonical source

Behavior:

- `AGENTS.md` owns the stable workflow guidance and the current checkpoint

Rationale:

- one canonical repo instruction file is easier to maintain than parallel
  long-form variants

### 2. Keep only one live handoff block

Behavior:

- the current checkpoint lives under `## Current Handoff` at the bottom of
  `AGENTS.md`
- when writing a new handoff, append the new block there and prune the older
  one in the same edit

Rationale:

- this keeps handoff writing low-friction without letting the instruction file
  grow indefinitely again

### 3. `CLAUDE.md` mirrors stable guidance only

Behavior:

- `CLAUDE.md` keeps the broad repo guidance Claude Code needs
- current updates point back to `AGENTS.md`

Rationale:

- avoids duplicated running history while preserving compatibility with tools
  that still read `CLAUDE.md`

## Implementation Details

Primary files:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/plans/README.md`

Supporting docs:

- this plan doc

## Testing Strategy

Validation should confirm:

- links and section references are consistent
- touched markdown passes focused lint checks
- `git diff --check` stays clean

## Documentation Updates

- add and index this plan doc
- update the `AGENTS.md` handoff block to reflect the active cleanup slice
- add the `CLAUDE.md` pointer back to `AGENTS.md#current-handoff`

## Checklist

- [x] Add and index the plan doc.
- [x] Rewrite `AGENTS.md` to stable guidance plus one current handoff section.
- [x] Rewrite `CLAUDE.md` to mirrored stable guidance plus pointer back to `AGENTS.md`.
- [x] Run focused validation.
- [x] Sync the live handoff block with validation results.

Validation completed:

- `wc -l AGENTS.md CLAUDE.md` -> `254 / 177`
- `.venv/bin/ruff check AGENTS.md CLAUDE.md docs/plans/README.md docs/plans/AGENTS-CLAUDE-HANDOFF-RESTRUCTURE-PLAN-2026-03-12.md`
- `git diff --check`
