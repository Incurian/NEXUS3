# README Refresh Plan (2026-04-07)

## Overview

Refresh the repo root `README.md` and the package-level `README.md` files under
`nexus3/` so they are complete, internally consistent, and aligned with the
current codebase.

This pass focuses on factual correctness first: stale counts, incomplete
package overviews, and thin subpackage docs that no longer explain the shipped
surface well enough.

## Scope

Included:

- audit and refresh the repo root [`README.md`](/home/inc/repos/NEXUS3/README.md)
- audit and refresh package/module readmes under `nexus3/`
- expand the thin package overviews for:
  - `nexus3/README.md`
  - `nexus3/skill/builtin/README.md`
  - `nexus3/skill/vcs/gitlab/README.md`
  - `nexus3/mcp/test_server/README.md`
- fix any concrete stale claims discovered during the audit

Deferred:

- adding a new `README.md` for the intentionally deferred `nexus3/ide`
- rewriting already-accurate long-form module docs for style only
- refreshing docs outside the root/module README surface

Excluded:

- behavior changes in Python code unless a doc-blocking bug is discovered
- broad documentation reorganization outside the touched readmes

## Design Decisions And Rationale

### 1. Audit against current code, not prior prose

Module READMEs in this repo are detailed enough that doc-to-doc comparison is
not sufficient. Current code, exports, and registration helpers are the source
of truth.

### 2. Prioritize thin and stale surfaces

Most module READMEs are already substantial. The highest-value refresh is to
correct the root README and expand the package docs that are too thin to stand
alone.

### 3. Reduce future drift where exact counts are not valuable

If a precise number is easy to validate and materially useful, keep it. If it
is likely to drift and adds little value, prefer wording that stays correct as
the project evolves.

## Implementation Details

Primary files:

- `/home/inc/repos/NEXUS3/README.md`
- `/home/inc/repos/NEXUS3/nexus3/README.md`
- `/home/inc/repos/NEXUS3/nexus3/cli/README.md`
- `/home/inc/repos/NEXUS3/nexus3/context/README.md`
- `/home/inc/repos/NEXUS3/nexus3/core/README.md`
- `/home/inc/repos/NEXUS3/nexus3/provider/README.md`
- `/home/inc/repos/NEXUS3/nexus3/skill/builtin/README.md`
- `/home/inc/repos/NEXUS3/nexus3/skill/vcs/README.md`
- `/home/inc/repos/NEXUS3/nexus3/skill/vcs/gitlab/README.md`
- `/home/inc/repos/NEXUS3/nexus3/mcp/test_server/README.md`
- `/home/inc/repos/NEXUS3/docs/plans/README-REFRESH-PLAN-2026-04-07.md`
- `/home/inc/repos/NEXUS3/docs/plans/README.md`

Audit targets:

- validate root README counts and module-surface claims
- verify package overview docs against actual package root files and exports
- ensure the thin subpackage docs explain layout, registration/entry points,
  and security/runtime constraints where relevant

## Testing Strategy

- `git diff --check`
- focused command validation for any refreshed quantitative claims
- no pytest rerun unless a documentation correction requires code changes

## Implementation Checklist

- [x] Audit the current README surface and record the plan.
- [x] Refresh the root README for current counts and module coverage.
- [x] Refresh thin package/module READMEs under `nexus3/`.
- [x] Run focused validation and record outcomes.

## Closeout

Updated files:

- `/home/inc/repos/NEXUS3/README.md`
- `/home/inc/repos/NEXUS3/nexus3/README.md`
- `/home/inc/repos/NEXUS3/nexus3/cli/README.md`
- `/home/inc/repos/NEXUS3/nexus3/context/README.md`
- `/home/inc/repos/NEXUS3/nexus3/core/README.md`
- `/home/inc/repos/NEXUS3/nexus3/provider/README.md`
- `/home/inc/repos/NEXUS3/nexus3/skill/builtin/README.md`
- `/home/inc/repos/NEXUS3/nexus3/skill/vcs/README.md`
- `/home/inc/repos/NEXUS3/nexus3/skill/vcs/gitlab/README.md`
- `/home/inc/repos/NEXUS3/nexus3/mcp/test_server/README.md`
- `/home/inc/repos/NEXUS3/docs/plans/README.md`
- `/home/inc/repos/NEXUS3/docs/plans/README-REFRESH-PLAN-2026-04-07.md`

Key outcomes:

- corrected the stale root README skill-count claim in the architecture table
- corrected the root README CLI reference so `rpc` and `trace` are documented
  as first-class subcommands and the REPL command table includes
  `/gitlab test [NAME]`
- documented all currently supported `mcp.json` shapes in the root README and
  context module README, including NEXUS3 object/list forms plus
  Claude-compatible `mcpServers`
- corrected the core README export block so it matches the direct-RPC
  capability helpers actually re-exported from `nexus3.core`
- expanded the thin package READMEs so they document package-root files,
  registration surfaces, runtime behavior, and related docs
- refreshed module docs where the audit found concrete drift (`cli`, `context`,
  `core`, `provider`, `skill/vcs`, `skill/vcs/gitlab`) and left the rest of
  the module README surface unchanged where it already matched the code

## Validation

- `git diff --check`
- `git diff --no-index --check -- /dev/null docs/plans/README-REFRESH-PLAN-2026-04-07.md` (no whitespace errors; exits `1` because the file is new)
- `rg -n "44 built-in|3400\\+|Two MCP config formats are supported|nexus3/skill/vcs/config.py" README.md nexus3 -g 'README.md'` (no matches)
- `rg -n "nexus3 rpc <SUBCOMMAND>|nexus3 trace \\[TARGET\\] \\[FLAGS\\]|/gitlab test|DIRECT_RPC_SCOPE_BY_METHOD|Three MCP config shapes are supported" README.md nexus3/context/README.md nexus3/core/README.md` (expected matches present)
- package README coverage check:
  - `.venv/bin/python - <<'PY' ...` verified no implemented `nexus3/` package
    with Python files is missing a `README.md` (`missing []`)

## Documentation Updates

- add and index this plan in `docs/plans/README.md`
- keep the refreshed README files internally cross-linked where useful
