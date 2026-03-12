# Docs Completeness And Correctness Audit Plan (2026-03-12)

## Overview

Audit documentation completeness and correctness before merging
`feat/repl-streaming-cleanup` back to `master`.

This pass has two goals:

- ensure module `README.md` coverage under `nexus3/` matches the current code
  layout and intended package boundaries
- verify that high-level claims in current-facing docs still match actual
  behavior after the REPL/trace cleanup work

## Scope

Included:

- audit `nexus3/*/README.md` coverage and obvious stale sections
- identify missing package readmes where the repo expects one
- verify major claims in:
  - `README.md`
  - `AGENTS.md`
  - `nexus3/defaults/NEXUS-DEFAULT.md`
- update docs and running status to reflect corrected behavior
- run focused validation for touched docs and any code touched during claim
  correction

Deferred:

- deep line-by-line proofreading of every long-form example
- full rewrite of module docs for style consistency alone
- documentation for intentionally deferred areas such as `nexus3/ide`

Excluded:

- unrelated product/design changes
- broad command-surface redesign

## Design Decisions And Rationale

### 1. Audit against the codebase, not prior docs

Behavior:

- current code and tests are the source of truth for factual claims

Rationale:

- this branch already changed multiple REPL/RPC behaviors, so doc-to-doc
  comparisons are not sufficient

### 2. Prefer narrow corrections over broad rewrites

Behavior:

- fix missing/stale claims directly where they are wrong
- add missing package readmes only when the package is clearly part of the
  documented module surface

Rationale:

- this keeps the merge-prep pass bounded and reviewable

### 3. Treat running-status docs as part of the merge surface

Behavior:

- `AGENTS.md` / `CLAUDE.md` status and known-behavior notes must stay aligned
  with the final branch state

Rationale:

- this repo relies on those files for continuity after compaction/disconnects

## Implementation Details

Primary files:

- `README.md`
- `AGENTS.md`
- `CLAUDE.md`
- `nexus3/defaults/NEXUS-DEFAULT.md`
- `nexus3/*/README.md` and any missing package readmes that need to be added

Supporting docs:

- `docs/plans/README.md`

## Testing Strategy

Validation should be proportional to touched files:

- focused `ruff` over touched markdown/python files
- focused `mypy` / `pytest` if any code changes are needed to make docs true
- `git diff --check`

## Documentation Updates

- add and index this audit plan
- sync current running status in `AGENTS.md`
- sync `CLAUDE.md` if behavior or workflow wording changes

## Checklist

- [x] Add and index the plan doc.
- [x] Audit module README completeness and fix coverage gaps.
- [x] Audit high-level claim correctness and fix stale statements.
- [x] Run focused validation.
- [ ] Prepare merge-ready summary for `master`.

Validation completed:

- `.venv/bin/pytest -q tests/unit/test_http_pipeline_layers.py tests/unit/cli/test_repl_safe_sink.py` (`60 passed`)
- `.venv/bin/ruff check nexus3/rpc/http.py nexus3/cli/repl.py tests/unit/test_http_pipeline_layers.py README.md AGENTS.md CLAUDE.md docs/plans/README.md docs/plans/REPL-RPC-IDLE-ACTIVITY-PLAN-2026-03-12.md docs/plans/DOCS-COMPLETENESS-AND-CORRECTNESS-AUDIT-PLAN-2026-03-12.md nexus3/README.md nexus3/cli/README.md nexus3/defaults/NEXUS-DEFAULT.md nexus3/display/README.md nexus3/mcp/README.md nexus3/mcp/test_server/README.md nexus3/rpc/README.md nexus3/session/README.md nexus3/skill/README.md nexus3/skill/builtin/README.md nexus3/skill/vcs/README.md nexus3/skill/vcs/gitlab/README.md`
- `.venv/bin/mypy nexus3/rpc/http.py nexus3/cli/repl.py`
- `git diff --check`
