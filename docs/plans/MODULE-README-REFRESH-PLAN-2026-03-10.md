# Module README Refresh Plan (2026-03-10)

## Overview

NEXUS3 keeps a local `README.md` in each implemented top-level module, but the
documentation quality and freshness vary by area. After the March 10 hardening
waves, the user-facing root docs were synced repeatedly, while the module-local
READMEs were updated more unevenly.

This plan refreshes the module READMEs in parallel so each module overview
reflects the current architecture, constraints, and user-visible behavior.

## Scope

### Included

- Review and update the existing module READMEs for:
  - `nexus3/cli`
  - `nexus3/clipboard`
  - `nexus3/commands`
  - `nexus3/config`
  - `nexus3/context`
  - `nexus3/core`
  - `nexus3/defaults`
  - `nexus3/display`
  - `nexus3/mcp`
  - `nexus3/patch`
  - `nexus3/provider`
  - `nexus3/rpc`
  - `nexus3/session`
  - `nexus3/skill`
  - `nexus3/skill/vcs`
- Bring module docs into line with shipped contract changes from the recent
  architecture hardening and tool-audit work.
- Record any modules that appear intentionally deferred or only partially
  implemented.

### Deferred

- Adding a new `README.md` for `nexus3/ide`.
- Deep narrative rewrites where the current module README is structurally fine
  and only needs targeted corrections.
- Cross-repo doc-style normalization outside files touched by this slice.

### Excluded

- Rewriting root docs (`README.md`, `CLAUDE.md`, `AGENTS.md`) beyond any
  minimal status synchronization needed for this plan.
- Behavioral code changes that are discovered during documentation review
  unless a concrete doc-blocking bug appears.

## Design Decisions And Rationale

### 1. Refresh existing module READMEs before adding new ones

The repository already relies on per-module READMEs as its primary local
reference surface. The highest-value documentation pass is to tighten the
implemented modules first, not to add a placeholder README for `ide`.

### 2. Parallelize by disjoint module groups

The module READMEs are independent enough to assign in parallel without merge
conflict risk. Each worker owns a disjoint write set.

### 3. Prefer precise corrections over broad rewriting

The goal is freshness and accuracy, not prose churn. Preserve useful existing
structure where it already matches the code.

## Implementation Details

### Phase 1: inventory + ownership

Files:

- `docs/plans/MODULE-README-REFRESH-PLAN-2026-03-10.md`
- `docs/plans/README.md`

Work:

- record scope and exclusions
- divide module README ownership into disjoint groups

### Phase 2: parallel module review/update

Worker groups:

1. Core runtime group
   - `nexus3/core/README.md`
   - `nexus3/context/README.md`
   - `nexus3/config/README.md`
   - `nexus3/defaults/README.md`
2. Session/interaction group
   - `nexus3/cli/README.md`
   - `nexus3/display/README.md`
   - `nexus3/session/README.md`
   - `nexus3/commands/README.md`
3. Tooling/integration group
   - `nexus3/skill/README.md`
   - `nexus3/clipboard/README.md`
   - `nexus3/patch/README.md`
   - `nexus3/provider/README.md`
   - `nexus3/rpc/README.md`
   - `nexus3/mcp/README.md`
   - `nexus3/skill/vcs/README.md`

Work:

- compare each module README against current code and recent shipped changes
- update stale contracts, caveats, and examples
- keep README structure intact unless a module doc is clearly misleading

### Phase 3: integrate + validate

Files:

- touched module README files
- `AGENTS.md`

Work:

- review worker diffs
- resolve any cross-module wording inconsistencies
- record closeout and any intentionally deferred doc gaps

## Testing Strategy

- `git diff --check`
- run `ruff check` only if any Python files need incidental edits
- no pytest rerun required unless a README review exposes a doc-blocking code
  bug and code changes are made

## Implementation Checklist

- [x] Record module README refresh scope and exclusions.
- [x] Assign module groups for parallel review/update.
- [x] Refresh module READMEs across all in-scope modules.
- [x] Integrate worker results and normalize cross-module wording.
- [x] Sync status/checkpoint docs for the finished slice.

## Closeout

Updated module READMEs:

- `nexus3/core/README.md`
- `nexus3/context/README.md`
- `nexus3/config/README.md`
- `nexus3/cli/README.md`
- `nexus3/session/README.md`
- `nexus3/commands/README.md`
- `nexus3/skill/README.md`
- `nexus3/clipboard/README.md`
- `nexus3/patch/README.md`
- `nexus3/provider/README.md`

Reviewed and left unchanged for this slice:

- `nexus3/defaults/README.md`
- `nexus3/display/README.md`
- `nexus3/rpc/README.md`
- `nexus3/mcp/README.md`
- `nexus3/skill/vcs/README.md`

Intentionally deferred:

- `nexus3/ide/README.md` was not added; `nexus3/ide` remains explicitly out of scope while that area stays unfinished.

## Validation

- `git diff --check -- AGENTS.md nexus3/core/README.md nexus3/context/README.md nexus3/config/README.md nexus3/defaults/README.md nexus3/cli/README.md nexus3/display/README.md nexus3/session/README.md nexus3/commands/README.md nexus3/skill/README.md nexus3/clipboard/README.md nexus3/patch/README.md nexus3/provider/README.md nexus3/rpc/README.md nexus3/mcp/README.md nexus3/skill/vcs/README.md`
- `git diff --no-index --check -- /dev/null docs/plans/MODULE-README-REFRESH-PLAN-2026-03-10.md` (no whitespace errors; exits `1` because the file is compared against `/dev/null`)

## Documentation Updates

- Update `docs/plans/README.md` to index this plan.
- Update `AGENTS.md` running status when the slice is complete.
