# AGENTS Template

This is a reusable template for a repository-specific `AGENTS.md`.

Keep this file focused on repo contract: project layout, workflow rules,
commands, validation, debugging, and handoff structure. Put cross-project
agent judgment, phrasing, and best practices in a separate playbook.

## Canonical Guidance

Replace bracketed placeholders like `<PROJECT_NAME>` and trim any sections
that do not fit the project.

- `AGENTS.md` is the canonical agent document for this repo.
- Keep stable project guidance and reference links in this file.
- Keep the most recent checkpoint in [`## Current Handoff`](#current-handoff)
  at the bottom of this file.

## Project Overview

`<PROJECT_NAME>` is a `<SHORT_DESCRIPTION>`.

- Status: `<STATUS>`
- Core areas: `<AREA_1>`, `<AREA_2>`, `<AREA_3>`

Add more overview bullets only if they materially help a new agent orient
itself quickly.

## Architecture

Primary package or app root: `<PRIMARY_ROOT>/`

- `<MODULE_A>/`: `<RESPONSIBILITY>`
- `<MODULE_B>/`: `<RESPONSIBILITY>`
- `<MODULE_C>/`: `<RESPONSIBILITY>`
- `<MODULE_D>/`: `<RESPONSIBILITY>`

Add more module bullets only when they are useful orientation, not exhaustive
cataloging.

## Reference Docs

Detailed references live in companion files to keep this document concise:

- `<REF_A>/`: `<SHORT_DESCRIPTION>`
- `<REF_B>/`: `<SHORT_DESCRIPTION>`
- `<REF_C>/`: `<SHORT_DESCRIPTION>`

Rename or remove these companion files if the project uses a different doc
layout. Keep them updated.

## Ops Notes

Useful commands:

```bash
<APP_COMMAND>
<APP_COMMAND> --help
<DEV_SERVER_COMMAND>
<STATUS_COMMAND>
```

Replace this section with other operational shortcuts.

## Standard Operating Procedures (SOPs)

### Agent Initiative

- Agents should proactively maintain the repo's canonical current-status or
  handoff section when that is part of the project workflow.
- Agents should surface branch, worktree, validation, and next-gate status
  without waiting to be asked every time.
- Agents should ask before turning repeated ad hoc guidance into a permanent
  SOP or policy entry.
- Agents should distinguish discussion mode from execution mode.
- For non-trivial changes, discuss architecture and implementation shape with
  the user before editing code.
- Once a direction is approved, proceed with reasonable initiative rather than
  asking for permission on every small step.

### Documentation

When changing behavior:

- Update relevant module `README.md`
- Update `AGENTS.md` and any other agent-facing docs that describe the changed
  behavior
- Update command or help text for user-facing changes
- Record temporary breakages or known failures if they cannot be fixed
  immediately

### Planning

For non-trivial features, create a plan doc under `<PLANS_DIR>/` before
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

### Engineering

- Type everything; avoid weak typing and unbounded `Any`.
- Fail fast; do not silently swallow exceptions.
- Prefer one clear implementation path over duplicate patterns.
- Add end-to-end tests for new behavior where practical.
- Document user-visible changes.
- Delete dead code and unused imports.
- Do not revert unrelated local changes.
- Keep branches focused and commit in logical units.

Add project-specific coding rules here if they are stable enough to be worth
following every time.

### Testing and Validation

Always use the project's managed executables:

```bash
<ENV_PREFIX> pytest <TEST_PATH> -v
<ENV_PREFIX> pytest <INTEGRATION_TEST_PATH> -v
<ENV_PREFIX> ruff check <LINT_ROOT>
<ENV_PREFIX> mypy <TYPECHECK_ROOT>
```

Never rely on bare `python` or `pytest` if the project uses a managed
environment.

Known caveats in the environment:

- Note any tests or commands that hang or fail under sandboxing.
- Note any commands that reliably require network or unsandboxed execution.
- Document the exact workaround when it is stable enough to recommend.

Live validation is required for changes that affect `<LIVE_SURFACES>`:

```bash
<START_COMMAND>
<SMOKE_COMMAND_1>
<SMOKE_COMMAND_2>
```

If the project does not have a live runtime, replace this with the closest
real smoke path.

### Debugging Playbook

Use this fallback only if a recurring failure resurfaces:

- `<FAILURE_SIGNATURE_1>`
- `<FAILURE_SIGNATURE_2>`

Capture actionable logs with:

```bash
<DEBUG_COMMAND>
```

Then collect the newest diagnostic artifacts under `<LOG_PATH>` and inspect:

- `<ARTIFACT_1>` for `<WHAT_TO_CHECK>`
- `<ARTIFACT_2>` for `<WHAT_TO_CHECK>`
- `<ARTIFACT_3>` for `<WHAT_TO_CHECK>`

When investigating:

1. Verify the last relevant state snapshot before the failure.
2. Confirm the failing request, command, or payload matches that snapshot.
3. Add a focused test for the exact failing shape before patching.

If the failure persists after existing repairs, prefer a general fix at the
lowest stable layer rather than adding another ad-hoc compatibility shim.

## Execution Tracking And Handoff SOP

- Keep stable guidance above and the live checkpoint in
  [`## Current Handoff`](#current-handoff) at the bottom of this file.
- When writing a new handoff, append a new
  `### YYYY-MM-DD - <slice>` block under `## Current Handoff`, then prune the
  previous block in the same edit so only the latest handoff remains here.
- Each handoff should include: branch, active slice, relevant plans or docs,
  recent commits or baseline head, validation status, and next gate.
- When disconnected or compacted, resume from `## Current Handoff` first, then
  reconcile referenced plan checklists before new edits.
- When spawning Codex subagents, explicitly instruct them to avoid escalated or
  sandbox-bypass commands unless absolutely required by the task, to prevent
  avoidable approval stalls.

## Current Workstream (<YYYY-MM-DD>)

For continuity on the current effort, start from:

- Canonical review or audit: `<PATH_OR_LINK>`
- Active milestone or investigation: `<PATH_OR_LINK>`
- Plans index: `<PATH_OR_LINK>`
- Review index: `<PATH_OR_LINK>`

If the project does not use reviews or milestone docs, replace this section
with the equivalent continuity pointers.

## Current Handoff

### <YYYY-MM-DD> - <active slice>

- Branch: `<BRANCH>`
- Baseline head: `<COMMIT>` (`<SUMMARY>`)
- Active slice:
  - `<CURRENT_GOAL_1>`
  - `<CURRENT_GOAL_2>`
- Plan:
  - `<PLAN_PATH_OR_LINK>`
- Implemented locally:
  - `<FILE_OR_AREA>`
    - `<CHANGE>`
    - `<CHANGE>`
- Focused validation passed:
  - `<COMMAND>`
  - `<COMMAND>`
  - `<COMMAND>`
- Residual note:
  - `<KNOWN_LIMITATION_OR_FOLLOW_UP>`
- Next gate:
  - `<NEXT_DECISION_OR_VALIDATION>`
