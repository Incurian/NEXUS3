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

## Architecture Overhaul Running Status (2026-03-05)

Branch:
- `feat/arch-overhaul-execution`

Current milestone:
- `M1` (Boundary Enforcement Wave) and `M2` (Authorization/Concurrency Wave) in progress.

Immediate tasks:
- Continue M1 implementation slices:
  - Plan H remaining method-ingress strictness cleanup after current compat-safe slices
  - Plan G Phase 3/4 remaining output-path migration + sanitization cleanup
- Continue M2 implementation slices:
  - Plan A Phase 2+3 expansion beyond destroy-path shadow parity
  - Plan C propagation beyond destroy path as needed by remaining auth/rpc routes

Recent execution commits (latest first):
- `78ef205` rpc/protocol: wire parse_request to request schema ingress
- `022f461` repl: sanitize startup metadata output via SafeSink
- `9e08fd2` repl: sanitize post-turn status and error lines
- `4686fd5` rpc/dispatcher: add cancel_all empty-params ingress guard
- `7522446` tests(rpc): cover create auth shadow parity at delta ceiling stage
- `419f370` rpc/pool: add create auth shadow parity at parent ceiling gates
- `029d1e6` repl: sanitize incoming notification previews via SafeSink
- `bae573c` rpc create_agent: drop redundant allowed_write_paths type guard
- `000e256` advance plan h/a: streamline send ingress and add send auth shadow parity
- `149e342` repl: sanitize tool trace lines via SafeSink
- `ef5ffaa` Expand auth kernel shadow parity for tool action checks
- `cd7f3f9` display: sanitize inline printer dynamic output via SafeSink
- `9f29400` harden rpc ingress for cancel and create-agent wait flag
- `6671064` harden protocol response ingress with typed schema validation
- `bdb676e` expand plan A: add target auth kernel shadow parity in enforcer
- `ce3d263` migrate confirmation ui prompts to SafeSink
- `c5eb670` advance plan h: reject boolean json-rpc ids at protocol boundary
- `f6ee537` advance m1: harden send ingress params and migrate lobby outputs to safe sink
- `a53c7dd` advance plan h: fail-fast mcp boundary validation and unify mcp config model
- `1b455b5` advance m1: extend schema ingress create_agent and migrate repl mcp consent to safe sink

Progress snapshot:
- Completed: architecture plan sanity corrections merged locally (schedule + plans A-H scope/gates/checklist alignment).
- Completed: Plan A M0 foundation interfaces (`nexus3/core/authorization_kernel.py`) + unit tests.
- Completed: Plan H M0 schema inventory scaffold (`nexus3/rpc/schemas.py`) + unit tests.
- Completed: Plan H M1 Phase 2 first compat-safe ingress slice (`destroy_agent`, `get_messages`) wired to typed schemas with existing-style RPC error mapping + focused unit tests.
- Completed: Plan H M1 Phase 2 incremental compat-safe ingress slice (`cancel`, `compact`) wired in `rpc/dispatcher.py` with focused wiring tests.
- Completed: Plan H M1 Phase 2 low-risk no-arg ingress compat-safe schema hooks wired for `shutdown`/`get_tokens`/`get_context` and `list_agents`/`shutdown_server`, with focused compat wiring tests.
- Completed: Plan H M1 Phase 2 behavior-sensitive ingress slice wired in `rpc/dispatcher.py::_handle_send` and `rpc/global_dispatcher.py::_handle_create_agent` with compat-safe schema validation and preserved `InvalidParamsError` style mappings, plus focused wiring tests.
- Completed: Plan H M1 Phase 2 behavior-sensitive extension for `create_agent`:
  - added compat-safe ingress validation coverage for `parent_agent_id` and conditional `wait_for_initial_response` in `rpc/global_dispatcher.py::_handle_create_agent`
  - preserved legacy-style `InvalidParamsError` message mappings (`Parent agent not found: ...`, `wait_for_initial_response must be boolean`)
  - added focused wiring regressions in `tests/unit/rpc/test_schema_ingress_wiring.py`
- Completed: Plan H M1 Phase 3 MCP config consolidation slice:
  - unified `MCPServerConfig` into `nexus3/config/schema.py` as canonical source of truth
  - removed duplicate `MCPServerConfig` dataclass from `nexus3/mcp/registry.py` and kept registry import path compatibility
  - updated `/mcp connect` path to pass canonical MCP config directly to registry (including `args` and `fail_if_no_tools`)
- Completed: Plan H M1 Phase 3 fail-fast malformed-entry slice:
  - removed silent malformed `mcp.json` container/entry skips in `nexus3/context/loader.py::_merge_mcp_servers`
  - malformed `mcpServers`/`servers` container types and non-object list entries now raise `MCPConfigError` with contextual source metadata
  - added focused regressions in `tests/unit/context/test_loader_mcp_fail_fast.py`, including compatibility fallback when `mcpServers` is empty and `servers` is present
- Completed: Plan H M1 Phase 2 send-ingress extension:
  - expanded compat-safe schema validation in `nexus3/rpc/dispatcher.py::_handle_send` to cover optional `request_id`, `source`, and `source_agent_id`
  - preserved explicit `InvalidParamsError` mappings for malformed optional fields and prevented unhashable `request_id` shapes from reaching internal tracking structures
  - added focused malformed-parameter regressions in `tests/unit/rpc/test_schema_ingress_wiring.py`
- Completed: Plan H M1 Phase 2 protocol-boundary hardening:
  - `nexus3/rpc/protocol.py` request/response parsing now explicitly rejects boolean JSON-RPC `id` values (bool no longer accepted via int subclass behavior)
  - added focused parse tests in `tests/unit/rpc/test_schema_ingress_wiring.py` and `tests/unit/test_client.py`
- Completed: Plan H M1 Phase 2 response-envelope ingress hardening:
  - `nexus3/rpc/protocol.py::parse_response` now validates through `RpcResponseEnvelopeSchema`
  - preserved legacy-style ParseError wording for malformed `error` object shapes and existing envelope invariants
  - added focused regressions in `tests/unit/rpc/test_schema_ingress_wiring.py` and `tests/unit/rpc/test_schemas.py`
- Completed: Plan H M1 Phase 2 handler cleanup slice:
  - removed ad hoc `cancel` request-id guard in `rpc/dispatcher.py` and rely on `CancelParamsSchema` compat-safe ingress validation.
  - removed duplicate `wait_for_initial_response` post-create manual parsing in `rpc/global_dispatcher.py` and reused schema-validated field.
  - added focused regressions in `tests/unit/rpc/test_schema_ingress_wiring.py`.
- Completed: Plan H M1 Phase 2 projection cleanup slice:
  - added shared schema projection helper `project_known_schema_fields` in `nexus3/rpc/schemas.py`.
  - migrated `rpc/dispatcher.py::_handle_send` and `rpc/global_dispatcher.py::_handle_create_agent` field projection to helper-backed schema ingress flow.
  - preserved legacy-style invalid-param wording and compat-safe extra-param behavior.
- Completed: Plan H M1 Phase 2 create-agent cleanup slice:
  - removed redundant post-schema `allowed_write_paths` type guards in `rpc/global_dispatcher.py`.
  - preserved malformed-shape `InvalidParamsError` wording via ingress schema error mapping.
  - kept sandbox/parent-cwd path containment enforcement unchanged.
- Completed: Plan H M1 Phase 2 no-arg ingress cleanup slice:
  - added compat-safe `EmptyParamsSchema` ingress guard for `rpc/dispatcher.py::_handle_cancel_all`.
  - preserved permissive extra-param compatibility behavior.
  - added focused wiring regression in `tests/unit/rpc/test_schema_ingress_wiring.py`.
- Completed: Plan H M1 Phase 2 request-envelope ingress migration:
  - migrated `rpc/protocol.py::parse_request` to typed schema ingress via `RpcRequestEnvelopeSchema`.
  - preserved legacy ParseError wording and positional-params rejection behavior.
  - added focused protocol ingress regressions in `tests/unit/rpc/test_schema_ingress_wiring.py`.
- Completed: Plan H M1 Phase 2 strict-envelope ingress slice:
  - tightened protocol-envelope ingress in `nexus3/rpc/protocol.py` and `nexus3/rpc/schemas.py` to reject unknown top-level JSON-RPC request/response fields.
  - removed request projection-based compatibility and response envelope `extra=\"ignore\"` compatibility override.
  - preserved bool-id rejection and positional-params ParseError wording.
  - added focused regressions in `tests/unit/rpc/test_schema_ingress_wiring.py`, `tests/unit/rpc/test_schemas.py`, and `tests/unit/test_client.py`.
- Completed: Plan H M1 Phase 2 destroy-ingress strictness slice:
  - tightened `nexus3/rpc/global_dispatcher.py::_handle_destroy_agent` to validate full param objects and reject unknown extra params.
  - preserved legacy missing/type/malformed `agent_id` wording and requester propagation behavior.
  - added focused ingress regression in `tests/unit/rpc/test_schema_ingress_wiring.py`.
- Completed: Plan H M1 Phase 2 strict no-arg flip slice:
  - tightened no-arg ingress handlers in `nexus3/rpc/dispatcher.py` (`shutdown`, `get_tokens`, `get_context`, `cancel_all`) and `nexus3/rpc/global_dispatcher.py` (`list_agents`, `shutdown_server`) to reject unknown extra params via strict `EmptyParamsSchema` validation.
  - preserved existing success payloads and method-specific invalid-params wording.
  - updated ingress regressions in `tests/unit/rpc/test_schema_ingress_wiring.py`.
- Completed: baseline E/F harness fixtures/tests under `tests/fixtures/arch_baseline/`, `tests/unit/context/test_compile_baseline.py`, and `tests/unit/patch/test_byte_roundtrip_baseline.py`.
- Completed: Plan G M1 Phase 1 foundation safe sink API (`nexus3/display/safe_sink.py`) with minimal `InlinePrinter` integration and focused unit tests (`tests/unit/display/test_safe_sink.py`).
- Completed: Plan G M1 Phase 2 high-risk output migration:
  - `nexus3/cli/client_commands.py` stderr output paths now use `SafeSink` trusted/untrusted stream methods.
  - `nexus3/mcp/error_formatter.py` dynamic fields now use `SafeSink` print sanitization.
  - Focused tests added/updated in `tests/unit/cli/test_client_commands_safe_sink.py` and `tests/unit/mcp/test_error_formatter.py`.
  - Focused validation passed via `.venv/bin/ruff check` and `.venv/bin/pytest -v tests/unit/mcp/test_error_formatter.py tests/unit/cli/test_client_commands_safe_sink.py tests/unit/display/test_safe_sink.py`.
- Completed: Plan G M1 Phase 3 incremental output migration slice:
  - `nexus3/cli/repl_commands.py::_mcp_connection_consent` now sanitizes dynamic MCP server/tool text through `SafeSink` before Rich-rendered prompt output.
  - Added focused tests in `tests/unit/cli/test_repl_commands_safe_sink.py`.
  - Focused validation passed via `.venv/bin/ruff check nexus3/cli/repl_commands.py tests/unit/cli/test_repl_commands_safe_sink.py` and `.venv/bin/pytest -v tests/unit/cli/test_repl_commands_safe_sink.py tests/unit/test_repl_commands.py`.
- Completed: Plan G M1 Phase 3 incremental output migration slice (connect/lobby prompts):
  - `nexus3/cli/connect_lobby.py` and `nexus3/cli/lobby.py` now sanitize dynamic/untrusted interpolated CLI values through `SafeSink` while preserving trusted static Rich markup.
  - Added focused sanitization+parity regressions in `tests/unit/cli/test_connect_lobby_safe_sink.py` and `tests/unit/cli/test_lobby_safe_sink.py`.
  - Focused validation passed via `.venv/bin/ruff check nexus3/cli/connect_lobby.py nexus3/cli/lobby.py tests/unit/cli/test_connect_lobby_safe_sink.py tests/unit/cli/test_lobby_safe_sink.py` and `.venv/bin/pytest -v tests/unit/cli/test_connect_lobby_safe_sink.py tests/unit/cli/test_lobby_safe_sink.py tests/unit/test_lobby.py`.
- Completed: Plan G M1 Phase 3 incremental output migration slice (confirmation UI prompts):
  - `nexus3/cli/confirmation_ui.py::confirm_tool_action` now sanitizes dynamic fields through `SafeSink` across MCP/exec/nexus/general tool prompts while preserving trusted markup.
  - removed redundant ad hoc escaping variables in this path in favor of sink-boundary sanitization.
  - added focused sanitization/parity regressions in `tests/unit/cli/test_confirmation_ui_safe_sink.py`.
- Completed: Plan G M1 Phase 3 incremental output migration slice (InlinePrinter):
  - `nexus3/display/printer.py` dynamic render methods now sanitize untrusted fields through `SafeSink` (`print_task_start`, `print_task_end`, `print_error`, `print_cancelled`, expanded `print_thinking`).
  - preserved trusted gumball/thinking markup wrappers.
  - added focused sanitization/parity regressions in `tests/unit/display/test_escape_sanitization.py`.
- Completed: Plan G M1 Phase 3 incremental output migration slice (`repl.py` tool traces):
  - migrated dynamic tool-trace spinner lines in `nexus3/cli/repl.py` (`on_tool_active`, `on_batch_progress`, `on_batch_halt`, `nexus_send` trace preview) to SafeSink-backed sanitization.
  - preserved trusted Rich wrappers while sanitizing interpolated untrusted values.
  - added focused regressions in `tests/unit/cli/test_repl_safe_sink.py`.
- Completed: Plan G M1 Phase 3 incremental output migration slice (`repl.py` incoming notifications):
  - migrated incoming notification start/end preview lines to SafeSink-backed sanitization in `nexus3/cli/repl.py`.
  - preserved existing truncation/ellipsis behavior and trusted Rich wrappers.
  - extended focused regressions in `tests/unit/cli/test_repl_safe_sink.py`.
- Completed: Plan G M1 Phase 3 incremental output migration slice (`repl.py` post-turn status/errors):
  - migrated dynamic post-turn lines in `nexus3/cli/repl.py` (`cancel_reason`, `turn_duration`, stream/autosave error text) to SafeSink-backed sanitization.
  - preserved existing wrappers/wording behavior.
  - extended focused regressions in `tests/unit/cli/test_repl_safe_sink.py`.
- Completed: Plan G M1 Phase 3 incremental output migration slice (`repl.py` startup metadata/status):
  - migrated startup/session metadata and embedded RPC status lines in `nexus3/cli/repl.py` to SafeSink-backed sanitization.
  - preserved existing wrappers/wording behavior.
  - extended focused regressions in `tests/unit/cli/test_repl_safe_sink.py`.
- Completed: Plan G M1 Phase 3 incremental output migration slice (`repl.py` remaining client/discovery/status surfaces):
  - migrated remaining dynamic `run_repl`/`run_repl_client`/`_run_connect_with_discovery` lines (created-agent notices, shutdown/connect/provider/invalid-port errors, client metadata/status lines, command output message lines) to SafeSink-backed sanitization helpers.
  - preserved trusted static wrappers while sanitizing interpolated dynamic fields.
  - extended focused regressions in `tests/unit/cli/test_repl_safe_sink.py`.
- Completed: Plan G M1 Phase 3 incremental output migration slice (top-level REPL/serve residual surfaces):
  - migrated residual dynamic top-level lines in `nexus3/cli/repl.py::main`, `nexus3/cli/repl.py::_run_with_reload`, and `nexus3/cli/serve.py::run_serve` to SafeSink-backed sanitization helpers.
  - preserved startup/error wording and flow while sanitizing dynamic command/path/message fields.
  - added focused serve sanitization regressions in `tests/unit/cli/test_serve_safe_sink.py` and extended `tests/unit/cli/test_repl_safe_sink.py`.
- Completed: Plan G Phase 3 cleanup slice (SafeSink helper dedup):
  - added shared `SafeSink.sanitize_print_value(...)` helper in `nexus3/display/safe_sink.py`.
  - removed duplicate local sanitize-wrapper helpers in `nexus3/cli/serve.py` and `nexus3/mcp/error_formatter.py` by routing through shared SafeSink entrypoint.
  - added focused helper regression in `tests/unit/display/test_safe_sink.py` and confirmed existing serve/MCP formatter suites remain green.
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
- Completed: M2 Plan A Phase 2+3 target-authorization shadow parity slice in `nexus3/session/enforcer.py`:
  - added adapter-backed shadow decision comparison in `_check_target_allowed`
  - kept legacy target restriction enforcement authoritative
  - added structured mismatch warning (`target_auth_shadow_mismatch`) and focused parity tests
- Completed: M2 Plan A Phase 2+3 tool-action authorization shadow parity slice in `nexus3/session/enforcer.py`:
  - added adapter-backed shadow decision comparison in `_check_action_allowed`
  - kept legacy action restriction enforcement authoritative
  - added structured mismatch warning (`tool_action_auth_shadow_mismatch`) and focused parity tests
- Completed: M2 Plan A Phase 2+3 send-lifecycle authorization shadow parity slice in `nexus3/rpc/dispatcher.py`:
  - added adapter-backed shadow decision comparison in `_handle_send` against existing YOLO/REPL legacy check.
  - kept legacy send restriction enforcement authoritative.
  - added structured mismatch warning (`send_auth_shadow_mismatch`) and focused parity tests in `tests/unit/test_rpc_dispatcher.py`.
- Completed: M2 Plan A Phase 2+3 create-lifecycle authorization shadow parity slice in `nexus3/rpc/pool.py`:
  - added adapter-backed shadow decision comparison around create parent ceiling gates (`max depth`, base `can_grant`, delta `can_grant`).
  - kept legacy create permission enforcement authoritative.
  - added structured mismatch warning (`create_auth_shadow_mismatch`) and focused parity tests in `tests/unit/rpc/test_pool_create_auth_shadow.py`.
- Completed: M2 Plan A Phase 2+3 create-lifecycle delta-branch parity coverage slice:
  - added focused delta-ceiling parity + mismatch warning tests in `tests/unit/rpc/test_pool_create_auth_shadow.py`.
  - confirmed legacy deny path remains authoritative when kernel intentionally diverges.
- Completed: M2 Plan A Phase 2+3 create-requester propagation + requester-binding parity slice:
  - threaded `requester_id` through `nexus3/rpc/agent_api.py -> nexus3/rpc/global_dispatcher.py -> nexus3/rpc/pool.py` for create flow request context parity.
  - added shadow-only requester/parent binding comparison stage (`requester_parent_binding`) in create authorization adapter path.
  - preserved legacy create allow/deny behavior and error semantics as authoritative.
  - added focused regressions in `tests/unit/test_agent_api.py`, `tests/unit/test_pool.py`, and `tests/unit/rpc/test_pool_create_auth_shadow.py`.
- Completed: M2 Plan A Phase 2+3 shutdown-server lifecycle shadow parity slice:
  - added `shutdown_server` shadow authorization-kernel parity comparison in `nexus3/rpc/global_dispatcher.py` with request-context requester usage.
  - preserved legacy always-allow shutdown behavior and response/error semantics as authoritative.
  - added focused parity/mismatch regressions in `tests/unit/test_pool.py` and ingress guard coverage in `tests/unit/rpc/test_schema_ingress_wiring.py`.
- Completed: M2 Plan A Phase 2+3 list-agents lifecycle shadow parity slice:
  - added `list_agents` shadow authorization-kernel parity comparison in `nexus3/rpc/global_dispatcher.py` with request-context requester usage.
  - added direct API requester propagation for `list_agents` and `shutdown_server` in `nexus3/rpc/agent_api.py` for parity telemetry consistency.
  - preserved legacy always-allow list behavior and response semantics as authoritative.
  - added focused parity/mismatch regressions in `tests/unit/test_pool.py`, `tests/unit/test_agent_api.py`, and ingress guard coverage in `tests/unit/rpc/test_schema_ingress_wiring.py`.
- Completed: M2 Plan C Phase 3 execution-skill request-safety slice:
  - removed per-call mutable state from `bash_safe`, `shell_UNSAFE`, and `run_python`
  - refactored subprocess creation helpers to pass command/code as local parameters
  - updated Windows behavior tests to assert subprocess call args directly
  - added focused concurrent `run_python` test for per-call payload isolation
- Validation snapshot (2026-03-05, post-merge slices):
  - `.venv/bin/ruff check nexus3/cli/repl.py nexus3/rpc/agent_api.py nexus3/rpc/global_dispatcher.py nexus3/rpc/pool.py nexus3/rpc/protocol.py nexus3/rpc/schemas.py tests/unit/cli/test_repl_safe_sink.py tests/unit/rpc/test_pool_create_auth_shadow.py tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/rpc/test_schemas.py tests/unit/test_agent_api.py tests/unit/test_client.py tests/unit/test_pool.py` passed.
  - `.venv/bin/pytest -v tests/unit/cli/test_repl_safe_sink.py tests/unit/rpc/test_pool_create_auth_shadow.py tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/rpc/test_schemas.py tests/unit/test_agent_api.py tests/unit/test_client.py tests/unit/test_pool.py` passed (`176 passed`, `9 warnings`).
- Validation snapshot (2026-03-05, next execution round):
  - `.venv/bin/ruff check nexus3/rpc/global_dispatcher.py nexus3/cli/repl.py nexus3/cli/serve.py tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/test_pool.py tests/unit/cli/test_repl_safe_sink.py tests/unit/cli/test_serve_safe_sink.py` passed.
  - `.venv/bin/pytest -v tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/test_pool.py tests/unit/cli/test_repl_safe_sink.py tests/unit/cli/test_serve_safe_sink.py` passed (`123 passed`).
- Validation snapshot (2026-03-05, strict-noarg follow-up round):
  - `.venv/bin/ruff check nexus3/rpc/dispatcher.py nexus3/rpc/global_dispatcher.py tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/test_pool.py tests/unit/test_rpc_dispatcher.py` passed.
  - `.venv/bin/mypy nexus3/rpc/dispatcher.py nexus3/rpc/global_dispatcher.py` passed.
  - `.venv/bin/pytest -v tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/test_pool.py tests/unit/test_rpc_dispatcher.py` passed (`112 passed`).
- Validation snapshot (2026-03-05, G/A cleanup + parity round):
  - `.venv/bin/ruff check nexus3/cli/serve.py nexus3/display/safe_sink.py nexus3/mcp/error_formatter.py nexus3/rpc/agent_api.py nexus3/rpc/global_dispatcher.py tests/unit/display/test_safe_sink.py tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/test_agent_api.py tests/unit/test_pool.py` passed.
  - `.venv/bin/mypy nexus3/rpc/agent_api.py nexus3/rpc/global_dispatcher.py nexus3/display/safe_sink.py nexus3/mcp/error_formatter.py` passed.
  - `.venv/bin/pytest -v tests/unit/display/test_safe_sink.py tests/unit/cli/test_serve_safe_sink.py tests/unit/mcp/test_error_formatter.py tests/unit/test_pool.py tests/unit/test_agent_api.py tests/unit/rpc/test_schema_ingress_wiring.py` passed (`178 passed`).
- Next gate:
  - Plan H: target remaining behavior-sensitive compat branches and finalize strict-default ingress posture where safe.
  - Plan G: continue redundant sanitization-callsite cleanup by identifying any remaining fragmented formatter/sanitizer branches for SafeSink consolidation.
  - Plan A: continue adapter rollout into remaining lifecycle call sites and sequence duplicate authorization branch removal once shadow telemetry is stable.

Resume-first checklist (post-compact):
1. Confirm branch + cleanliness: `git status --short --branch` (ignore existing unrelated untracked: `docs/plans/DOUBLE-SPINNER-FIX-PLAN.md`, `editors/`, `err/`).
2. Re-open plan checklists:
   - `docs/plans/ARCH-H-STRICT-SCHEMA-GATES-PLAN-2026-03-02.md`
   - `docs/plans/ARCH-G-TERMINAL-SAFE-SINK-PLAN-2026-03-02.md`
   - `docs/plans/ARCH-A-AUTH-KERNEL-PLAN-2026-03-02.md`
3. Dispatch Codex subagents with no-escalation instruction and scoped ownership.
4. After each accepted slice:
   - run focused `.venv/bin/ruff`, `.venv/bin/mypy` (where typed modules changed), and targeted `.venv/bin/pytest`
   - update both the relevant plan checklist and this `AGENTS.md` status block in the same session
   - commit in a single logical unit.

Recovery note:
- If interrupted, restart from this section and `docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md`, then continue checklist-driven execution.

Compact checkpoint (2026-03-05, end of session):
- Branch head: `5106528` (docs tracking after round 6).
- Workspace state at handoff: clean tracked tree; ignore unrelated untracked (`docs/plans/DOUBLE-SPINNER-FIX-PLAN.md`, `editors/`, `err/`).
- Immediate next execution slices:
  1. Plan H: evaluate strict-default ingress flips where compat behavior is now proven by tests (start with request/response envelope paths in `nexus3/rpc/protocol.py`).
  2. Plan G: migrate remaining dynamic `console.print`/`spinner.print` surfaces in `nexus3/cli/repl.py` not yet routed through SafeSink formatter helpers.
  3. Plan A: identify next lifecycle authorization callsite beyond current enforcer/pool/dispatcher coverage and add shadow parity + focused tests.

Compact checkpoint (2026-03-05, architecture execution round):
- Branch head at start of round: `5106528`; working tree now includes new Plan H/G/A execution slices plus docs/status updates.
- New slices completed this round:
  1. Plan H strict-envelope ingress slice (unknown top-level JSON-RPC request/response fields now rejected).
  2. Plan G REPL/client/discovery dynamic output migration slice to SafeSink.
  3. Plan A create requester-context propagation + requester/parent binding shadow parity slice.
- Validation result for this round:
  - Integrated targeted lint/test suites passed (`176 passed`, `9 warnings`).
- Immediate resume targets:
  1. Plan H: remaining method-param compatibility tightening in dispatcher/global-dispatcher handlers.
  2. Plan G: residual top-level CLI output surfaces (`main`, `_run_with_reload`, `serve.py`) and redundant sanitizer cleanup.
  3. Plan A: identify next lifecycle authorization adapter parity slice and sequence toward duplicate branch removal.

Compact checkpoint (2026-03-05, architecture execution round 2):
- Branch head at start of round: `5270ad6`; working tree now includes follow-up Plan H/G/A slices plus docs/status updates.
- New slices completed this round:
  1. Plan H destroy ingress strictness slice (unknown extra params for `destroy_agent` now rejected).
  2. Plan G top-level REPL/serve residual dynamic output migration to SafeSink.
  3. Plan A shutdown-server lifecycle shadow parity slice.
- Validation result for this round:
  - Integrated targeted lint/test suites passed (`123 passed`).
- Immediate resume targets:
  1. Plan H: strictness tightening for remaining compat-only no-arg/extra-param handlers.
  2. Plan G: remove fragmented duplicate formatter/sanitization helper branches.
  3. Plan A: next lifecycle adapter parity slice before duplicate branch removal.

Compact checkpoint (2026-03-05, architecture execution round 3):
- Branch head at start of round: `c26ef61`; working tree now includes a follow-up Plan H strict-noarg ingress slice.
- New slice completed this round:
  1. Plan H strict no-arg handler flip (`shutdown`, `get_tokens`, `get_context`, `cancel_all`, `list_agents`, `shutdown_server`) now rejects extra params.
- Validation result for this round:
  - targeted lint + mypy + pytest suites passed (`112 passed`).
- Immediate resume targets:
  1. Plan H: remaining behavior-sensitive compat branches.
  2. Plan G: formatter/sanitization dedup cleanup.
  3. Plan A: next lifecycle adapter parity slice before duplicate branch removal.

Compact checkpoint (2026-03-05, architecture execution round 4):
- Branch head at start of round: `6c66b85`; working tree now includes Plan G SafeSink dedup and Plan A list-agents parity slices.
- New slices completed this round:
  1. Plan G SafeSink helper dedup (`sanitize_print_value`) and local-wrapper removal in serve/MCP formatter paths.
  2. Plan A `list_agents` lifecycle shadow parity + direct API requester propagation consistency.
- Validation result for this round:
  - integrated lint + mypy + pytest suites passed (`178 passed`).
- Immediate resume targets:
  1. Plan H: remaining behavior-sensitive compat branches.
  2. Plan G: identify any remaining fragmented sanitizer/formatter call-site branches for consolidation.
  3. Plan A: next lifecycle adapter parity slice before duplicate branch removal.

Compact checkpoint (2026-03-05, pre-compact handover):
- Branch head at handover: `026e9f3`.
- Working tree status: clean tracked files; ignore unrelated existing untracked paths (`docs/plans/DOUBLE-SPINNER-FIX-PLAN.md`, `editors/`, `err/`).
- Latest validated state:
  - Plan H strict ingress slices applied through strict no-arg handler flips.
  - Plan G dedup slice applied (`SafeSink.sanitize_print_value`) with serve/MCP formatter wrapper cleanup.
  - Plan A parity slices applied through `shutdown_server` and `list_agents` lifecycle shadow coverage.
  - Latest integrated validation suite passed (`178 passed`) with ruff+mypy green.
- Resume order after compact:
  1. Plan H: identify and tighten remaining behavior-sensitive compatibility branches (if any) and confirm strict-default posture completeness.
  2. Plan G: audit for remaining fragmented sanitization/formatter call sites and consolidate to shared SafeSink entrypoints.
  3. Plan A: select next lifecycle parity adapter slice, then begin planning/sequence for duplicate authorization branch removal.
- SOP reminder:
  - Continue checklist-driven execution and update both relevant plan docs and this `AGENTS.md` status/checkpoint block in the same session before each commit.

Compact checkpoint (2026-03-06, architecture execution round 5):
- Branch head at start of round: `8bd8783`; working tree now includes a Plan H behavior-sensitive strict ingress follow-up.
- New slice completed this round:
  1. Plan H strict `create_agent` ingress hardening (`nexus3/rpc/global_dispatcher.py`) now validates full params object and rejects unknown extra params.
  2. Plan H removed legacy conditional bypass that ignored malformed `wait_for_initial_response` when `initial_message` was absent.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/global_dispatcher.py tests/unit/rpc/test_schema_ingress_wiring.py` passed.
  - `.venv/bin/pytest -v tests/unit/rpc/test_schema_ingress_wiring.py` passed (`47 passed`).
- Immediate resume targets:
  1. Plan H: tighten remaining behavior-sensitive compat branches (`send`, `cancel`, `compact`) where safe.
  2. Plan G: continue sanitization/formatter consolidation from remaining REPL and display fragmented call sites.
  3. Plan A: add next agent-scoped lifecycle shadow parity slice (`shutdown`/`cancel`/`compact`) with requester-context hardening.

Compact checkpoint (2026-03-06, architecture execution round 6):
- Branch head at start of round: `a1362a5`; working tree now includes parallel Plan G and Plan A follow-up slices.
- New slices completed this round:
  1. Plan G consolidated `nexus3/mcp/skill_adapter.py` result sanitization onto `SafeSink` shared entrypoint and added focused adapter sanitization regressions.
  2. Plan A added agent-scoped lifecycle shadow parity in `nexus3/rpc/dispatcher.py` for `shutdown`/`cancel`/`compact` with legacy behavior still authoritative.
  3. Plan A propagated trusted requester context through agent-scoped API dispatch (`nexus3/rpc/agent_api.py`) and updated send-shadow principal selection to prefer trusted requester identity when available.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/mcp/skill_adapter.py nexus3/rpc/dispatcher.py nexus3/rpc/agent_api.py tests/unit/mcp/test_skill_adapter.py tests/unit/test_rpc_dispatcher.py tests/unit/test_agent_api.py` passed.
  - `.venv/bin/mypy nexus3/rpc/dispatcher.py nexus3/rpc/agent_api.py nexus3/mcp/skill_adapter.py` passed.
  - `.venv/bin/pytest -v tests/unit/mcp/test_skill_adapter.py tests/unit/test_rpc_dispatcher.py tests/unit/test_agent_api.py` passed (`42 passed`).
- Immediate resume targets:
  1. Plan H: tighten remaining behavior-sensitive compat ingress in dispatcher (`send`, `cancel`, `compact`) and evaluate strict flips with legacy error wording preservation.
  2. Plan G: continue remaining fragmented sanitizer consolidation in display/REPL residual call sites (`spinner.py`, `streaming.py`, and any remaining direct dynamic prints).
  3. Plan A: identify first safe duplicate authorization branch removal candidate after parity telemetry stabilization.

Compact checkpoint (2026-03-06, architecture execution round 7):
- Branch head at start of round: `256683b`; working tree now includes parallel Plan H and Plan G strictness/consolidation follow-ups.
- New slices completed this round:
  1. Plan H tightened dispatcher ingress for `send`/`cancel`/`compact` to reject unknown extra params while preserving legacy field-specific invalid-params wording.
  2. Plan G consolidated display-layer sanitizer routing in `nexus3/display/spinner.py` and `nexus3/display/streaming.py` to shared `SafeSink` entrypoints.
  3. Added focused regressions in `tests/unit/rpc/test_schema_ingress_wiring.py` and `tests/unit/display/test_escape_sanitization.py` for the new strictness/sanitizer paths.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/dispatcher.py tests/unit/rpc/test_schema_ingress_wiring.py nexus3/display/spinner.py nexus3/display/streaming.py tests/unit/display/test_escape_sanitization.py` passed.
  - `.venv/bin/mypy nexus3/rpc/dispatcher.py nexus3/display/spinner.py nexus3/display/streaming.py` passed.
  - `.venv/bin/pytest -v tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/display/test_escape_sanitization.py tests/unit/display/test_safe_sink.py` passed (`96 passed`).
- Immediate resume targets:
  1. Plan H: decide on remaining compatibility-only protocol parse path (`empty method` rewrite) and whether to flip to strict reject.
  2. Plan G: sweep residual direct dynamic `console.print` sites in `nexus3/cli/repl.py` and low-risk CLI consistency paths for final consolidation.
  3. Plan A: plan/execute first safe duplicate-authorization-branch removal slice after shadow telemetry coverage.

Compact checkpoint (2026-03-06, architecture execution round 8):
- Branch head at start of round: `514c799`; working tree now includes a Plan A phase-4 starter cleanup slice.
- New slice completed this round:
  1. Plan A converted `list_agents` and `shutdown_server` in `nexus3/rpc/global_dispatcher.py` from shadow-only legacy-allow parity to kernel-authoritative enforcement.
  2. Removed duplicate legacy-allow comparison/warning branches for those two methods and added fail-closed deny-path assertions in `tests/unit/test_pool.py`.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/global_dispatcher.py tests/unit/test_pool.py` passed.
  - `.venv/bin/mypy nexus3/rpc/global_dispatcher.py` passed.
  - `.venv/bin/pytest -v tests/unit/test_pool.py` passed (`55 passed`).
- Immediate resume targets:
  1. Plan A: evaluate next safe duplicate-branch removal candidate (`rpc/dispatcher.py` lifecycle checks) while preserving external error semantics.
  2. Plan H: decide on remaining compatibility-only protocol parse path (`empty method` rewrite) and whether to flip to strict reject.
  3. Plan G: sweep residual direct dynamic `console.print` sites in `nexus3/cli/repl.py` and low-risk CLI consistency paths for final consolidation.

Compact checkpoint (2026-03-06, architecture execution round 9):
- Branch head at start of round: `049cba6`; working tree now includes parallel Plan A + Plan G follow-up slices.
- New slices completed this round:
  1. Plan A converted agent-scoped lifecycle authorization in `nexus3/rpc/dispatcher.py` (`shutdown`/`cancel`/`compact`) from shadow parity to kernel-authoritative enforcement with a shared lifecycle auth gate.
  2. Plan G removed remaining unsanitized plain command output rendering in `nexus3/cli/repl.py` by routing through a SafeSink-backed plain formatter helper.
  3. Updated focused regressions in `tests/unit/test_rpc_dispatcher.py` and `tests/unit/cli/test_repl_safe_sink.py`.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/dispatcher.py tests/unit/test_rpc_dispatcher.py nexus3/cli/repl.py tests/unit/cli/test_repl_safe_sink.py` passed.
  - `.venv/bin/mypy nexus3/rpc/dispatcher.py nexus3/cli/repl.py` passed.
  - `.venv/bin/pytest -v tests/unit/test_rpc_dispatcher.py tests/unit/cli/test_repl_safe_sink.py` passed (`40 passed`).
- Immediate resume targets:
  1. Plan A: evaluate remaining duplicate authorization branches (`send` path parity branch and pool/session branches) for next safe kernel-authoritative flip.
  2. Plan H: decide on remaining compatibility-only protocol parse path (`empty method` rewrite) and whether to flip to strict reject.
  3. Plan G: continue residual dynamic REPL print sweep and minor CLI consistency consolidation.

Compact checkpoint (2026-03-06, architecture execution round 10):
- Branch head at start of round: `f0836e0`; working tree now includes Plan H protocol strictness follow-up.
- New slice completed this round:
  1. Plan H removed `parse_request` empty-string method compatibility shim in `nexus3/rpc/protocol.py` and now rejects empty method values with explicit ParseError wording (`method must be a non-empty string`).
  2. Updated focused ingress regression in `tests/unit/rpc/test_schema_ingress_wiring.py` to assert strict reject behavior.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/protocol.py tests/unit/rpc/test_schema_ingress_wiring.py` passed.
  - `.venv/bin/mypy nexus3/rpc/protocol.py` passed.
  - `.venv/bin/pytest -v tests/unit/rpc/test_schema_ingress_wiring.py` passed (`49 passed`).
- Immediate resume targets:
  1. Plan A: evaluate remaining duplicate authorization branches (`send` path parity branch and pool/session branches) for next safe kernel-authoritative flip.
  2. Plan G: continue residual dynamic REPL print sweep and minor CLI consistency consolidation.
  3. Plan H: audit for any remaining compatibility-only protocol/schema behaviors and either retire or document them.

Compact checkpoint (2026-03-06, architecture execution round 11):
- Branch head at start of round: `515237e`; working tree now includes Plan A send-authorization duplicate-branch removal.
- New slice completed this round:
  1. Plan A converted `send` authorization in `nexus3/rpc/dispatcher.py` from shadow parity to kernel-authoritative enforcement.
  2. Preserved trusted requester precedence and kept legacy YOLO/no-REPL deny wording (`Cannot send to YOLO agent - no REPL connected`) via explicit kernel-reason mapping.
  3. Updated send authorization unit coverage in `tests/unit/test_rpc_dispatcher.py` for authoritative allow/deny behavior.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/dispatcher.py tests/unit/test_rpc_dispatcher.py` passed.
  - `.venv/bin/mypy nexus3/rpc/dispatcher.py` passed.
  - `.venv/bin/pytest -v tests/unit/test_rpc_dispatcher.py` passed (`17 passed`).
- Immediate resume targets:
  1. Plan A: evaluate remaining duplicate authorization branches in pool/session enforcement paths for next safe kernel-authoritative flip.
  2. Plan G: continue residual dynamic REPL print sweep and minor CLI consistency consolidation.
  3. Plan H: audit for any remaining compatibility-only protocol/schema behaviors and either retire or document them.

Compact checkpoint (2026-03-06, architecture execution round 12):
- Branch head at start of round: `9a9b073`; working tree now includes Plan A `AgentPool.destroy` duplicate-branch removal.
- New slice completed this round:
  1. Plan A converted destroy authorization in `nexus3/rpc/pool.py` from shadow parity to kernel-authoritative enforcement.
  2. Preserved existing user-facing `AuthorizationError` wording while removing legacy shadow-only branch logic.
  3. Added focused destroy authorization coverage in `tests/unit/test_pool.py` (self allow, parent allow, unauthorized deny, forced kernel deny authoritative behavior).
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/pool.py tests/unit/test_pool.py` passed.
  - `.venv/bin/mypy nexus3/rpc/pool.py` passed.
  - `.venv/bin/pytest -v tests/unit/test_pool.py` passed (`59 passed`).
- Immediate resume targets:
  1. Plan A: evaluate remaining duplicate authorization branches in session enforcer policy checks for next safe kernel-authoritative flip.
  2. Plan G: continue residual dynamic REPL print sweep and minor CLI consistency consolidation.
  3. Plan H: audit for any remaining compatibility-only protocol/schema behaviors and either retire or document them.

Compact checkpoint (2026-03-06, architecture execution round 13):
- Branch head at start of round: `35c5914`; working tree now includes Plan G REPL consistency cleanup.
- New slice completed this round:
  1. Plan G replaced remaining dynamic direct f-string prints in `nexus3/cli/repl.py` (additional-port scanning lines, startup-timeout port line, thought-duration spinner line) with SafeSink-backed helper formatters.
  2. Added focused helper coverage in `tests/unit/cli/test_repl_safe_sink.py` for the new formatter paths.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/cli/repl.py tests/unit/cli/test_repl_safe_sink.py` passed.
  - `.venv/bin/mypy nexus3/cli/repl.py` passed.
  - `.venv/bin/pytest -v tests/unit/cli/test_repl_safe_sink.py` passed (`25 passed`).
- Immediate resume targets:
  1. Plan A: evaluate remaining duplicate authorization branches in session enforcer policy checks for next safe kernel-authoritative flip.
  2. Plan G: sweep any final minor CLI consistency paths (`repl_commands` sharing prompt path) and verify no remaining fragmented sanitizer usage.
  3. Plan H: audit for any remaining compatibility-only protocol/schema behaviors and either retire or document them.

Compact checkpoint (2026-03-06, architecture execution round 14):
- Branch head at start of round: `1bc1800`; working tree now includes Plan A session-action authorization cleanup.
- New slice completed this round:
  1. Plan A converted `session/enforcer.py::_check_action_allowed` to kernel-authoritative enforcement.
  2. Removed tool-action shadow-mismatch warning branch for this method while preserving deny wording (`Tool '<tool>' is not allowed at current permission level`).
  3. Updated action-authorization coverage in `tests/unit/session/test_enforcer.py` for authoritative behavior.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/session/enforcer.py tests/unit/session/test_enforcer.py` passed.
  - `.venv/bin/mypy nexus3/session/enforcer.py` passed.
  - `.venv/bin/pytest -v tests/unit/session/test_enforcer.py` passed (`31 passed`).
- Immediate resume targets:
  1. Plan A: evaluate whether `session/enforcer.py::_check_target_allowed` can be safely flipped to kernel-authoritative (currently still shadow parity).
  2. Plan G: sweep final minor CLI consistency paths (`repl_commands` sharing prompt path) and verify no fragmented sanitizer usage remains.
  3. Plan H: audit for any remaining compatibility-only protocol/schema behaviors and either retire or document them.

Compact checkpoint (2026-03-06, pre-compact handover):
- Tracked working tree currently includes the round-14 Plan A session-action slice plus docs/status updates.
- Ready-to-commit files:
  - `nexus3/session/enforcer.py`
  - `tests/unit/session/test_enforcer.py`
  - `docs/plans/ARCH-A-AUTH-KERNEL-PLAN-2026-03-02.md`
  - `AGENTS.md`
- Validation already completed and green for this slice (ruff + mypy + pytest as listed above).
- Existing unrelated untracked paths remain intentionally untouched: `docs/plans/DOUBLE-SPINNER-FIX-PLAN.md`, `editors/`, `err/`.
- Resume-first command after compact:
  - `git status --short --branch`
  - then continue from this section and Plan A checklist.

Compact checkpoint (2026-03-06, architecture execution round 15):
- Branch head at start of round: `11297f4`; working tree now includes parallel Plan A + Plan H follow-up slices.
- New slices completed this round:
  1. Plan A converted `session/enforcer.py::_check_target_allowed` from shadow parity to kernel-authoritative enforcement.
  2. Removed target-authorization legacy/shadow mismatch warning branch while preserving target-deny wording semantics.
  3. Plan H tightened `rpc/dispatcher.py::_handle_get_messages` ingress to strict full-param validation so unknown extra params are rejected (no more candidate-field projection that dropped extras).
  4. Updated focused regressions in `tests/unit/session/test_enforcer.py` and `tests/unit/rpc/test_schema_ingress_wiring.py` for authoritative/strict behavior.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/session/enforcer.py nexus3/rpc/dispatcher.py tests/unit/session/test_enforcer.py tests/unit/rpc/test_schema_ingress_wiring.py` passed.
  - `.venv/bin/mypy nexus3/session/enforcer.py nexus3/rpc/dispatcher.py` passed.
  - `.venv/bin/pytest -v tests/unit/session/test_enforcer.py tests/unit/rpc/test_schema_ingress_wiring.py` passed (`85 passed`).
- Immediate resume targets:
  1. Plan A: evaluate next safe kernel-authoritative flip for create authorization in `rpc/pool.py::_create_unlocked` (currently still legacy-authoritative with kernel shadow compare).
  2. Plan H: evaluate strict-value (not just extra-key) flips for behavior-sensitive handlers still using `strict=False` (`send`, `cancel`, `compact`, `create_agent`) and protocol `error` object strict typing.
  3. Plan G: finish residual sink-boundary cleanup in `display/streaming.py` tool metadata rendering and remaining dynamic REPL command-result print paths.

Compact checkpoint (2026-03-06, architecture execution round 16):
- Branch head at start of round: `a388420`; working tree now includes Plan G closure slices.
- New slices completed this round:
  1. Plan G hardened dynamic render boundaries in `nexus3/display/streaming.py` (tool name/params + batch active tool name) to sanitize at sink boundary.
  2. Plan G replaced remaining dynamic REPL command-result lines in `nexus3/cli/repl.py` with SafeSink-backed formatters (switch/whisper/create/restore outputs).
  3. Plan G consolidated confirmation parameter formatting in `nexus3/cli/confirmation_ui.py` onto `SafeSink.sanitize_print_value(...)`.
  4. Plan G hardened prompt-toolkit HTML toolbar/prompt interpolation in `nexus3/cli/repl.py` via `_sanitize_prompt_html_text(...)` and sanitized confirmation full-details pager/editor content in `nexus3/cli/confirmation_ui.py`.
  5. Plan G checklist top-level items are now marked complete in `docs/plans/ARCH-G-TERMINAL-SAFE-SINK-PLAN-2026-03-02.md` after re-audit.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/display/streaming.py nexus3/cli/repl.py nexus3/cli/confirmation_ui.py tests/unit/display/test_escape_sanitization.py tests/unit/cli/test_repl_safe_sink.py tests/unit/cli/test_confirmation_ui_safe_sink.py` passed.
  - `.venv/bin/mypy nexus3/display/streaming.py nexus3/cli/repl.py nexus3/cli/confirmation_ui.py` passed.
  - `.venv/bin/pytest -v tests/unit/display/test_escape_sanitization.py tests/unit/cli/test_repl_safe_sink.py tests/unit/cli/test_confirmation_ui_safe_sink.py` passed (`74 passed`).
- Immediate resume targets:
  1. Plan A: evaluate kernel-authoritative create authorization flip in `rpc/pool.py::_create_unlocked` (highest remaining duplicate-branch security surface).
  2. Plan H: evaluate strict-value flips for behavior-sensitive handlers still using `strict=False` (`send`, `cancel`, `compact`, `create_agent`) while preserving legacy error wording.
  3. Plan H: decide whether to enforce strict typed `error` object shape in `rpc/protocol.py::parse_response` using `RpcErrorObjectSchema`.

Compact checkpoint (2026-03-06, architecture execution round 17):
- Branch head at start of round: `e24a164`; working tree now includes a focused Plan H strict-value ingress follow-up.
- New slice completed this round:
  1. Plan H tightened `rpc/dispatcher.py::_handle_cancel` from compat-style value coercion (`strict=False`) to strict-value schema validation (`strict=True`).
  2. Preserved existing invalid-params wording semantics for missing/malformed `request_id` and lifecycle authorization deny wording.
  3. Extended focused ingress regressions in `tests/unit/rpc/test_schema_ingress_wiring.py` to assert float `request_id` rejection and integer `request_id` happy-path behavior.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/dispatcher.py tests/unit/rpc/test_schema_ingress_wiring.py` passed.
  - `.venv/bin/mypy nexus3/rpc/dispatcher.py` passed.
  - `.venv/bin/pytest -v tests/unit/rpc/test_schema_ingress_wiring.py` passed (`56 passed`).
- Immediate resume targets:
  1. Plan H: evaluate next strict-value flip candidate (`send` or `compact`) with legacy wording preservation.
  2. Plan H: assess `rpc/protocol.py::parse_response` strict typed `error` object enforcement via `RpcErrorObjectSchema`.
  3. Plan A: continue duplicate-authorization-branch removal in `rpc/pool.py::_create_unlocked` (create authorization still legacy-authoritative).

Compact checkpoint (2026-03-06, architecture execution round 18):
- Branch head at start of round: `e89fb4b`; working tree now includes a second focused Plan H strict-value ingress follow-up.
- New slice completed this round:
  1. Plan H tightened `rpc/dispatcher.py::_handle_compact` from compat-style value coercion (`strict=False`) to strict-value schema validation (`strict=True`).
  2. Preserved existing invalid-params wording behavior while adding strictness regressions for coercible non-bool `force` values.
  3. Extended focused ingress coverage in `tests/unit/rpc/test_schema_ingress_wiring.py` (`force='true'` and `force=1` now rejected; existing invalid-force/extra-param assertions retained).
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/dispatcher.py tests/unit/rpc/test_schema_ingress_wiring.py` passed.
  - `.venv/bin/mypy nexus3/rpc/dispatcher.py` passed.
  - `.venv/bin/pytest -v tests/unit/rpc/test_schema_ingress_wiring.py` passed (`58 passed`).
- Immediate resume targets:
  1. Plan H: evaluate strict-value flip for `_handle_send` while preserving established field-specific invalid-params wording.
  2. Plan H: assess strict typed `error` object enforcement in `rpc/protocol.py::parse_response` using `RpcErrorObjectSchema`.
  3. Plan A: resume create-authorization duplicate-branch removal in `rpc/pool.py::_create_unlocked`.

Compact checkpoint (2026-03-06, architecture execution round 19):
- Branch head at start of round: `cb7558b`; working tree now includes a third focused Plan H strict-value ingress follow-up.
- New slice completed this round:
  1. Plan H tightened `rpc/dispatcher.py::_handle_send` from compat-style value coercion (`strict=False`) to strict-value schema validation (`strict=True`).
  2. Preserved existing field-specific invalid-params wording for `content`, `request_id`, `source`, and `source_agent_id`.
  3. Expanded focused ingress regressions in `tests/unit/rpc/test_schema_ingress_wiring.py` to reject coercion cases (`request_id=1.0`, `source=b\"rpc\"`, `source_agent_id=1.0`) while retaining previous valid-path behavior.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/dispatcher.py tests/unit/rpc/test_schema_ingress_wiring.py` passed.
  - `.venv/bin/mypy nexus3/rpc/dispatcher.py` passed.
  - `.venv/bin/pytest -v tests/unit/rpc/test_schema_ingress_wiring.py` passed (`61 passed`).
- Immediate resume targets:
  1. Plan H: assess strict typed `error` object enforcement in `rpc/protocol.py::parse_response` using `RpcErrorObjectSchema`.
  2. Plan H: evaluate strict-value flip for `create_agent` ingress in `rpc/global_dispatcher.py` (higher-risk surface).
  3. Plan A: resume create-authorization duplicate-branch removal in `rpc/pool.py::_create_unlocked`.

Compact checkpoint (2026-03-06, architecture execution round 20):
- Branch head at start of round: `59ad445`; working tree now includes Plan H protocol response-envelope strictness follow-up.
- New slice completed this round:
  1. Plan H made `RpcResponseEnvelopeSchema.error` strictly typed (`RpcErrorObjectSchema | None`) in `nexus3/rpc/schemas.py`.
  2. Plan H updated `nexus3/rpc/protocol.py::parse_response` to enforce nested error-object typing while preserving legacy wording for non-object and missing-required-field cases.
  3. Plan H normalized parsed response errors back to plain dict payloads via `model_dump(exclude_none=True)` to avoid model leakage/default-field noise.
  4. Added focused regressions in `tests/unit/rpc/test_schema_ingress_wiring.py` and `tests/unit/rpc/test_schemas.py` for malformed `error.code`/`error.message`, unknown `error` extras, and response error-dict shape.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/schemas.py nexus3/rpc/protocol.py tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/rpc/test_schemas.py` passed.
  - `.venv/bin/mypy nexus3/rpc/schemas.py nexus3/rpc/protocol.py` passed.
  - `.venv/bin/pytest -v tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/rpc/test_schemas.py` passed (`84 passed`).
- Immediate resume targets:
  1. Plan H: evaluate strict-value flip for `create_agent` ingress in `rpc/global_dispatcher.py` (remaining higher-risk behavior-sensitive path).
  2. Plan A: resume create-authorization duplicate-branch removal in `rpc/pool.py::_create_unlocked`.
  3. Plan A: evaluate routing `_check_enabled` through authorization kernel to reduce remaining split policy surface in `session/enforcer.py`.

## Source of Truth

`CLAUDE.md` contains full project reference detail. This file is the Codex-oriented operating guide distilled from it.
