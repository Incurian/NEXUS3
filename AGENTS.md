# AGENTS.md

This file provides guidance to Codex when working in this repository.

## Project Overview

NEXUS3 is a clean-slate rewrite of NEXUS2, an AI-powered CLI agent framework.

- Status: feature-complete
- Core areas: multi-provider support, permission system, MCP integration, context compaction

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

Each module has its own `README.md`.

## Context Files

Instruction file priority is configurable; defaults include:

```json
["NEXUS.md", "AGENTS.md", "CLAUDE.md", "README.md"]
```

For this repo, keep `AGENTS.md` and `CLAUDE.md` consistent when behavior or workflows change.

## Reference Docs

Detailed references live in companion files to keep this document concise:

- `AGENTS_NEXUS3ARCH.md`: project overview, module architecture, interfaces, skill hierarchy, multi-agent server model
- `AGENTS_NEXUS3CMDCAT.md`: full CLI modes, flags, session model, and REPL command reference
- `AGENTS_NEXUS3SKILLSCAT.md`: full built-in skills table and notes
- `AGENTS_NEXUS3CTXSEC.md`: full context loading/compaction, temporal/git injection, permissions, and security hardening notes
- `AGENTS_NEXUS3CONFIGOPS.md`: configuration reference, provider setup, GitLab/clipboard config, design/SOP/testing workflows, and deferred work tracker

## Current Workstream (2026-03-02)

For continuity on the current review/remediation effort, start from:

- Review index: [docs/reviews/README.md](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- Canonical master review: [docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- Plans index: [docs/plans/README.md](/home/inc/repos/NEXUS3/docs/plans/README.md)
- Architecture investigation: [docs/plans/ARCH-INVESTIGATION-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- Milestone schedule: [docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)

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

For non-trivial features, create a plan doc under `docs/` before implementation.

Minimum plan sections:

- Overview
- Scope (included, deferred, excluded)
- Design decisions and rationale
- Implementation details with concrete file paths
- Testing strategy
- Implementation checklist
- Documentation updates

Update the plan incrementally while you work.

Execution tracking SOP (applies to every major plan):
- Add/maintain a running status section in `AGENTS.md` with branch, active milestone/phase, recent commits, and next gate.
- Check off plan checklist items as soon as they are completed (same working session).
- When disconnected/compacted, resume from `AGENTS.md` running status first, then reconcile plan checklists before new edits.
- When spawning Codex subagents, explicitly instruct them to avoid escalated/sandbox-bypass commands unless absolutely required by the task, to prevent avoidable approval stalls.

## Testing and Validation

Always use virtualenv executables:

```bash
.venv/bin/pytest tests/ -v
.venv/bin/pytest tests/integration/ -v
.venv/bin/ruff check nexus3/
.venv/bin/mypy nexus3/
```

Never rely on bare `python` or `pytest`.

Known sandbox caveat (Codex CLI environment):
- In this repo, sandboxed runs may hang on tests that execute file I/O via `asyncio.to_thread(...)` (for example, `Path.read_bytes` inside file-edit skills).
- Symptom: pytest collects tests, starts first test, then stalls without pass/fail output.
- Workaround: rerun the same pytest command unsandboxed/escalated to verify real pass/fail status.

Live validation is required for changes that affect agent behavior, RPC, skills, or permissions:

```bash
nexus3 &
nexus3 rpc create test-agent
nexus3 rpc send test-agent "describe your permissions and what you can do"
nexus3 rpc destroy test-agent
```

## Permissions and Safety

- Respect preset boundaries (`sandboxed`, `trusted`, `yolo`).
- `sandboxed` should remain least-privileged by default in RPC workflows.
- Treat tool enablement, write paths, and agent targeting restrictions as security-sensitive.
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
- Update `CLAUDE.md` and `AGENTS.md` sections that describe the changed behavior
- Update command/help text for CLI or REPL changes
- Record temporary breakages in `CLAUDE.md` Known Failures if they cannot be fixed immediately

## Current Debugging Handoff (2026-03-04)

Status:
- Probably fixed as of 2026-03-04 after the cancellation/role-sequence hardening set (`5fe3f59`, `612df40`, `6daec54`, `0b04467`), but keep all notes below as the fallback playbook if it recurs.

Goal:
- Eliminate recurring post-cancel provider failures:
  - `Provider returned an empty response`
  - `API request failed (400): Unexpected role 'user' after role 'tool'`

Recent commits on `master` (chronological):
- `5fe3f59`: Mid-stream cancellation handling + reduce false empty-stream warnings.
- `612df40`: Prevent orphan tool-result sequences after cancellation.
- `6daec54`: Repair trailing tool-result tail by inserting synthetic assistant before next user turn.
- `0b04467`: Improve diagnostics:
  - log provider 4xx/5xx error bodies to `raw.jsonl`
  - emit `session.preflight` role snapshots to `verbose.md` before provider calls.

What is currently implemented:
- Pre-turn repair pipeline in `Session.send()` and `Session.run_turn()`:
  1. `_flush_cancelled_tools()` (now guarded; drops stale cancelled IDs)
  2. `context.prune_unpaired_tool_results()` (global scrub of invalid TOOL messages)
  3. `context.fix_orphaned_tool_calls()` (synthesizes missing tool results)
  4. `context.ensure_assistant_after_tool_results()` (prevents USER-after-TOOL tail)
- Provider stream warnings:
  - completed empty streams still warn
  - incomplete/interrupted empty streams now debug-log instead of warning.

Important caveat:
- If users still report 400 role errors, assume there is another sequence shape not covered yet.
- Do not guess; inspect logs from failing run with the exact commands below.

How to capture actionable logs:
```bash
nexus3 -V --raw-log --resume
# or: nexus3 -V --raw-log --session <NAME>
```

Then reproduce once and collect newest session directory under:
- `./.nexus3/logs/YYYY-MM-DD_HHMMSS_*/`

Required files:
- `verbose.md` (must include `session.preflight` entries)
- `raw.jsonl` (must include request + 4xx response bodies)
- `context.md` (conversation sequence around failure)

What to inspect first on next pass:
1. In `verbose.md`, locate last `session.preflight` block before the 400.
2. Verify role order in that preflight snapshot:
   - especially `... TOOL -> USER` adjacency
   - duplicate TOOL results
   - TOOL results without matching assistant tool_calls.
3. In `raw.jsonl`, verify failing request payload `messages` exactly matches the preflight sequence.
4. Add a unit test reproducing that exact shape before patching.

Suggested next hardening if failure persists:
- Add a provider-agnostic message normalizer in `Session` just before provider call:
  - enforce invariants for assistant/tool batches
  - optionally collapse illegal trailing TOOL blocks into a synthetic assistant note
  - emit one structured warning event with before/after diff summary.

## Architecture Overhaul Running Status (2026-03-04)

Branch:
- `feat/arch-overhaul-execution`

Current milestone:
- `M1` (Boundary Enforcement Wave) in progress.

Immediate tasks:
- Continue M1 implementation slices:
  - Plan D gateway migration (`outline`, `concat_files`, `grep`) after `glob` first slice
  - Plan H Phase 2 ingress schema wiring (remaining non-low-risk paths; compatibility mode where required)
  - Plan G Phase 3 remaining output-path migration after high-risk slice completion

Progress snapshot:
- Completed: architecture plan sanity corrections merged locally (schedule + plans A-H scope/gates/checklist alignment).
- Completed: Plan A M0 foundation interfaces (`nexus3/core/authorization_kernel.py`) + unit tests.
- Completed: Plan H M0 schema inventory scaffold (`nexus3/rpc/schemas.py`) + unit tests.
- Completed: Plan H M1 Phase 2 first compat-safe ingress slice (`destroy_agent`, `get_messages`) wired to typed schemas with existing-style RPC error mapping + focused unit tests.
- Completed: Plan H M1 Phase 2 incremental compat-safe ingress slice (`cancel`, `compact`) wired in `rpc/dispatcher.py` with focused wiring tests.
- Completed: Plan H M1 Phase 2 low-risk no-arg ingress compat-safe schema hooks wired for `shutdown`/`get_tokens`/`get_context` and `list_agents`/`shutdown_server`, with focused compat wiring tests.
- Completed: Plan H M1 Phase 2 behavior-sensitive ingress slice wired in `rpc/dispatcher.py::_handle_send` and `rpc/global_dispatcher.py::_handle_create_agent` with compat-safe schema validation and preserved `InvalidParamsError` style mappings, plus focused wiring tests.
- Completed: baseline E/F harness fixtures/tests under `tests/fixtures/arch_baseline/`, `tests/unit/context/test_compile_baseline.py`, and `tests/unit/patch/test_byte_roundtrip_baseline.py`.
- Completed: Plan G M1 Phase 1 foundation safe sink API (`nexus3/display/safe_sink.py`) with minimal `InlinePrinter` integration and focused unit tests (`tests/unit/display/test_safe_sink.py`).
- Completed: Plan G M1 Phase 2 high-risk output migration:
  - `nexus3/cli/client_commands.py` stderr output paths now use `SafeSink` trusted/untrusted stream methods.
  - `nexus3/mcp/error_formatter.py` dynamic fields now use `SafeSink` print sanitization.
  - Focused tests added/updated in `tests/unit/cli/test_client_commands_safe_sink.py` and `tests/unit/mcp/test_error_formatter.py`.
  - Focused validation passed via `.venv/bin/ruff check` and `.venv/bin/pytest -v tests/unit/mcp/test_error_formatter.py tests/unit/cli/test_client_commands_safe_sink.py tests/unit/display/test_safe_sink.py`.
- Completed: M1 Plan D grep migration slice routed fallback per-candidate authorization through `FilesystemAccessGateway` and added focused blocked/outside/symlink grep tests.
- Completed: M1 Plan D tool migrations (`glob`, `outline`, `concat_files`, `grep`) to `FilesystemAccessGateway`; remaining Plan D work is consolidated regression/perf guard coverage.
- Completed: M1 Plan D consolidated blocked-path/symlink regression coverage across migrated tool tests (`glob`, `outline`, `concat_files`, `grep`).
- Completed: M2 Plan C Phase 1 destroy-path request-context slice:
  - added immutable `RequestContext` model (`nexus3/core/request_context.py`)
  - removed global mutable requester field in `GlobalDispatcher`
  - propagated request context through global dispatcher destroy flow into pool authorization call
- Completed: M2 Plan A Phase 2 destroy-path shadow parity slice in `nexus3/rpc/pool.py`:
  - added destroy authorization kernel adapter in pool-local shadow mode
  - compute both legacy and kernel decisions in `AgentPool.destroy`
  - continue enforcing legacy allow/deny behavior only
  - emit structured warning when legacy/kernel decisions diverge
- Completed: M2 Plan C Phase 3 execution-skill request-safety slice:
  - removed per-call mutable state from `bash_safe`, `shell_UNSAFE`, and `run_python`
  - refactored subprocess creation helpers to pass command/code as local parameters
  - updated Windows behavior tests to assert subprocess call args directly
  - added focused concurrent `run_python` test for per-call payload isolation
- Next gate: run expanded validation (broader suites pending) and continue M1 Plan H ingress wiring plus Plan G Phase 3 migration slices.

Recovery note:
- If interrupted, restart from this section and `docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md`, then continue checklist-driven execution.

## Source of Truth

`CLAUDE.md` contains full project reference detail. This file is the Codex-oriented operating guide distilled from it.
