# AGENTS.md

This file provides guidance to Codex when working in this repository.

## Canonical Guidance

- `AGENTS.md` is the canonical agent document for this repo.
- Keep stable project guidance and reference links in this file.
- Keep the most recent checkpoint in [`## Current Handoff`](#current-handoff)
  at the bottom of this file.
- `CLAUDE.md` should mirror the stable guidance here and point back to
  [`## Current Handoff`](#current-handoff) for the latest status.

## Project Overview

NEXUS3 is a clean-slate rewrite of NEXUS2, an AI-powered CLI agent framework.

- Status: feature-complete
- Core areas: multi-provider support, permission system, MCP integration,
  context compaction

## Architecture

Primary package: `nexus3/`

- `core/`: types, interfaces, errors, paths, permissions, process termination
- `config/`: schema and config loading
- `provider/`: model provider abstraction and retry logic
- `context/`: context loading, token counting, compaction
- `session/`: session coordination, persistence, logging
- `skill/`: skill protocol, registry, service container
- `clipboard/`: scoped clipboard and persistence
- `patch/`: unified diff parsing and application
- `display/`: terminal presentation and streaming output
- `cli/`: REPL, lobby, server/client modes, commands
- `rpc/`: JSON-RPC dispatching and agent pool
- `mcp/`: MCP integration
- `commands/`: command infrastructure
- `defaults/`: default prompts/config

Each implemented module has its own `README.md`; `nexus3/ide` remains
intentionally deferred and does not have one yet.

## Context Files

Instruction file priority is configurable; defaults include:

```json
["NEXUS.md", "AGENTS.md", "CLAUDE.md", "README.md"]
```

For this repo, keep `AGENTS.md` and `CLAUDE.md` consistent when behavior or
workflow guidance changes.

## Reference Docs

Detailed references live in companion files to keep this document concise:

- `AGENTS_NEXUS3ARCH.md`: project overview, module architecture, interfaces,
  skill hierarchy, multi-agent server model
- `AGENTS_NEXUS3CMDCAT.md`: full CLI modes, flags, session model, and REPL
  command reference
- `AGENTS_NEXUS3SKILLSCAT.md`: full built-in skills table and notes
- `AGENTS_NEXUS3CTXSEC.md`: full context loading/compaction, temporal/git
  injection, permissions, and security hardening notes
- `AGENTS_NEXUS3CONFIGOPS.md`: configuration reference, provider setup,
  GitLab/clipboard config, design/SOP/testing workflows, and deferred work
  tracker

## Current Workstream (2026-03-02)

For continuity on the current review/remediation effort, start from:

- Review index:
  [docs/reviews/README.md](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- Canonical master review:
  [docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- Plans index:
  [docs/plans/README.md](/home/inc/repos/NEXUS3/docs/plans/README.md)
- Architecture investigation:
  [docs/plans/ARCH-INVESTIGATION-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- Milestone schedule:
  [docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)

## Engineering SOP

- Type everything; avoid weak typing and `Optional[Any]`.
- Fail fast; do not silently swallow exceptions.
- Prefer one clear implementation path over duplicate patterns.
- Keep code async-first where applicable.
- Add end-to-end tests for new behavior.
- Document user-visible changes.
- Delete dead code and unused imports.
- Do not revert unrelated local changes.
- Keep feature branches focused and commit in logical units.

## Planning Requirements

For non-trivial features, create a plan doc under `docs/` before
implementation.

Minimum plan sections:

- Overview
- Scope (included, deferred, excluded)
- Design decisions and rationale
- Implementation details with concrete file paths
- Testing strategy
- Implementation checklist
- Documentation updates

Update the plan incrementally while you work.

Execution tracking and handoff SOP:

- Keep stable guidance above and the live checkpoint in
  [`## Current Handoff`](#current-handoff) at the bottom of this file.
- When writing a new handoff, append a new
  `### YYYY-MM-DD - <slice>` block under `## Current Handoff`, then prune the
  previous block in the same edit so only the latest handoff remains here.
- Each handoff should include: branch, active slice, relevant plans/docs,
  recent commits or baseline head, validation status, and next gate.
- When disconnected or compacted, resume from `## Current Handoff` first, then
  reconcile referenced plan checklists before new edits.
- When spawning Codex subagents, explicitly instruct them to avoid escalated or
  sandbox-bypass commands unless absolutely required by the task, to prevent
  avoidable approval stalls.

## Testing and Validation

Always use virtualenv executables:

```bash
.venv/bin/pytest tests/ -v
.venv/bin/pytest tests/integration/ -v
.venv/bin/ruff check nexus3/
.venv/bin/mypy nexus3/
```

Never rely on bare `python` or `pytest`.

Known sandbox caveats in the Codex CLI environment:

- Sandboxed runs may hang on tests that execute file I/O via
  `asyncio.to_thread(...)` (for example, `Path.read_bytes` inside file-edit
  skills).
- Symptom: pytest collects tests, starts the first test, then stalls without
  pass/fail output.
- Workaround: rerun the same pytest command unsandboxed or escalated to verify
  real pass/fail status.
- Sandbox networking also blocks `git push` reliably in Codex CLI.
- Workaround: when the user explicitly asks to push, skip the sandboxed push
  attempt and run the push unsandboxed or escalated immediately.

Live validation is required for changes that affect agent behavior, RPC,
skills, or permissions:

```bash
nexus3 &
nexus3 rpc create test-agent
nexus3 rpc send test-agent "describe your permissions and what you can do"
nexus3 rpc destroy test-agent
```

## Permissions and Safety

- Respect preset boundaries (`sandboxed`, `trusted`, `yolo`).
- `sandboxed` should remain least-privileged by default in RPC workflows.
- Treat tool enablement, write paths, and agent targeting restrictions as
  security-sensitive.
- Avoid privilege escalation patterns in subagent creation.

## CLI and Ops Notes

Useful commands:

```bash
nexus3
nexus3 --fresh
nexus3 --resume
NEXUS_DEV=1 nexus3 --serve 9000
nexus3 rpc detect
nexus3 rpc list
nexus3 rpc create NAME
nexus3 rpc send NAME "message"
nexus3 rpc status NAME
```

## Documentation Discipline

When changing behavior:

- Update relevant module `README.md`
- Update `CLAUDE.md` and `AGENTS.md` sections that describe the changed
  behavior
- Update command/help text for CLI or REPL changes
- Record temporary breakages in `CLAUDE.md` Known Failures if they cannot be
  fixed immediately

## Debugging Playbook

Use this fallback only if the post-cancel provider failures recur:

- `Provider returned an empty response`
- `API request failed (400): Unexpected role 'user' after role 'tool'`

Capture actionable logs with:

```bash
nexus3 -V --raw-log --resume
# or: nexus3 -V --raw-log --session <NAME>
```

Then collect the newest session directory under `./.nexus3/logs/` and inspect:

- `verbose.md` for the last `session.preflight` block before the failure
- `raw.jsonl` for the exact outbound payload and any provider 4xx/5xx body
- `context.md` for the surrounding conversation sequence

When investigating:

1. Verify the preflight role order, especially `TOOL -> USER` adjacency,
   duplicate tool results, or tool results without matching assistant
   `tool_calls`.
2. Confirm the failing request payload in `raw.jsonl` matches the preflight
   snapshot.
3. Add a unit test for the exact failing sequence before patching.

If the failure persists after existing repairs, prefer a provider-agnostic
message normalizer just before the provider call rather than another
ad-hoc compatibility shim.

## Current Handoff

### 2026-03-12 - AGENTS/CLAUDE handoff cleanup active locally

- Branch: `master`
- Baseline head: `d649f50` (`release: cut v1.0.0`)
- Active slice:
  - reduce `AGENTS.md` to stable guidance plus a single current handoff block
  - trim `CLAUDE.md` to mirrored general guidance with a pointer back to this
    section
- Plan:
  - [docs/plans/AGENTS-CLAUDE-HANDOFF-RESTRUCTURE-PLAN-2026-03-12.md](/home/inc/repos/NEXUS3/docs/plans/AGENTS-CLAUDE-HANDOFF-RESTRUCTURE-PLAN-2026-03-12.md)
- Important current repo state:
  - `origin/master` and tag `v1.0.0` point at `d649f50`
  - [CHANGELOG.md](/home/inc/repos/NEXUS3/CHANGELOG.md) includes the release
    note telling existing checkouts to rerun their install step because
    `psutil` was added recently as a runtime dependency
- Focused validation passed:
  - `wc -l AGENTS.md CLAUDE.md` -> `254 / 177`
  - `.venv/bin/ruff check AGENTS.md CLAUDE.md docs/plans/README.md docs/plans/AGENTS-CLAUDE-HANDOFF-RESTRUCTURE-PLAN-2026-03-12.md`
  - `git diff --check`
- Next gate:
  - commit this cleanup slice
