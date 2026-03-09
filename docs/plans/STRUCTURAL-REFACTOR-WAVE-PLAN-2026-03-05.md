# Plan Follow-On: Structural Refactor Wave (2026-03-05)

## Overview

Execute the deferred large-structure cleanup wave for oversized core modules
(`repl.py`, `session.py`, `pool.py`) and display configuration wiring, with
strict behavior parity and no architectural policy changes.

## Scope

Included:
- Controlled decomposition of `nexus3/cli/repl.py`, `nexus3/session/session.py`,
  and `nexus3/rpc/pool.py` into smaller modules with stable public entrypoints.
- Display configuration cleanup so theme/display settings have one canonical
  contract and no-op placeholders are removed.
- Progressive extraction with compatibility wrappers to avoid large atomic
  rewrites.

Deferred:
- Broad naming cleanup and unrelated DRY refactors already tracked elsewhere.
- UI redesign beyond configuration consistency.

Excluded:
- Permission model changes.
- RPC protocol behavior changes.
- Provider or skill semantics changes not required by extraction.

## Design Decisions and Rationale

1. Extract by responsibility boundaries, not by arbitrary line count.
2. Keep import surface stable during migration (`repl.py`, `session.py`,
   `pool.py` remain façade entrypoints until final cutover).
3. Add parity tests before each move so refactor regressions are detected at
   the exact slice that introduced them.

## Implementation Details

Primary files to change:
- [repl.py](/home/inc/repos/NEXUS3/nexus3/cli/repl.py)
- [session.py](/home/inc/repos/NEXUS3/nexus3/session/session.py)
- [pool.py](/home/inc/repos/NEXUS3/nexus3/rpc/pool.py)
- [theme.py](/home/inc/repos/NEXUS3/nexus3/display/theme.py)
- [schema.py](/home/inc/repos/NEXUS3/nexus3/config/schema.py)
- [README.md](/home/inc/repos/NEXUS3/nexus3/cli/README.md)
- [README.md](/home/inc/repos/NEXUS3/nexus3/session/README.md)
- [README.md](/home/inc/repos/NEXUS3/nexus3/rpc/README.md)

Planned slices:
1. REPL split:
   - extract formatting helpers and output adapters from `repl.py`
   - extract client/discovery/reload runners into dedicated modules
   - keep `run_repl(...)` public API stable.
2. Session split:
   - extract tool-execution loop and permission-gated tool wrappers
   - extract compaction provider/summary paths
   - keep `Session.send(...)`/`Session.run_turn(...)` semantics unchanged.
3. Pool split:
   - extract create/restore assembly helpers
   - extract authorization adapter + visibility helper sections
   - keep `AgentPool` external API unchanged.
4. Display config cleanup:
   - replace placeholder `load_theme(overrides=...)` no-op path with canonical
     config-backed override flow
   - document supported override fields and defaults.

## Extraction Map (Kickoff 2026-03-09)

Compatibility boundary policy:
- Keep `nexus3/cli/repl.py`, `nexus3/session/session.py`, and
  `nexus3/rpc/pool.py` as stable façade entrypoints during extraction.
- Extract internals into sibling modules and re-export via façade imports until
  one full parity-green cycle is complete.
- Do not change external call signatures while moving code.

Proposed old->new ownership map:

| Current Module | Extraction Targets | Compatibility Boundary |
|---|---|---|
| `nexus3/cli/repl.py` | `nexus3/cli/repl_formatting.py`, `nexus3/cli/repl_runtime.py`, `nexus3/cli/repl_reload.py` | `run_repl(...)`, `main()`, `_run_with_reload(...)` remain in `repl.py` |
| `nexus3/session/session.py` | `nexus3/session/turn_runner.py`, `nexus3/session/tool_runtime.py`, `nexus3/session/compaction_runtime.py` | `Session` public methods (`send`, `run_turn`, lifecycle APIs) remain in `session.py` |
| `nexus3/rpc/pool.py` | `nexus3/rpc/pool_create.py`, `nexus3/rpc/pool_restore.py`, `nexus3/rpc/pool_visibility.py` | `AgentPool` class + exported pool types remain in `pool.py` |
| display config paths (`nexus3/display` + config usage sites) | `nexus3/display/theme_contract.py` (or equivalent typed contract module) | Existing theme-loading call sites remain unchanged until final cleanup |

Execution notes:
- Initial extraction order (lowest risk first):
  1. REPL formatting helpers
  2. REPL runtime/client-discovery helpers
  3. Session tool/compaction internals
  4. Pool create/restore internals
  5. Display contract cleanup
- Each extraction step must run the focused parity suite before moving to the
  next boundary.

## Execution Status

- 2026-03-09: Phase 1A (REPL formatting-helper extraction) completed in WSL.
  - Extracted SafeSink-backed REPL formatting/sanitization helpers into
    `nexus3/cli/repl_formatting.py`.
  - Kept `nexus3/cli/repl.py` as façade entrypoint by importing helper names
    so existing call sites and tests remain unchanged.
  - Focused validation passed:
    - `.venv/bin/ruff check nexus3/cli/repl.py nexus3/cli/repl_formatting.py`
    - `.venv/bin/mypy nexus3/cli/repl.py nexus3/cli/repl_formatting.py`
    - `.venv/bin/pytest -q tests/unit/cli/test_repl_safe_sink.py tests/unit/test_repl_commands.py` (`97 passed`)
- 2026-03-09: Phase 1B (REPL runtime/client-discovery + reload extraction)
  completed in WSL.
  - Extracted runtime/client-discovery helpers into
    `nexus3/cli/repl_runtime.py`.
  - Extracted reload helper into `nexus3/cli/repl_reload.py`.
  - Kept `nexus3/cli/repl.py` as a façade import surface for compatibility.
  - Focused validation passed:
    - `.venv/bin/ruff check nexus3/cli/repl.py nexus3/cli/repl_runtime.py nexus3/cli/repl_reload.py`
    - `.venv/bin/mypy nexus3/cli/repl.py nexus3/cli/repl_runtime.py nexus3/cli/repl_reload.py`
    - `.venv/bin/pytest -q tests/unit/cli/test_repl_safe_sink.py tests/unit/test_repl_commands.py tests/unit/cli/test_connect_lobby_safe_sink.py tests/unit/test_client.py` (`125 passed`)
- 2026-03-09: Phase 2A (Session compaction runtime helper extraction)
  completed in WSL.
  - Added `nexus3/session/compaction_runtime.py` for compaction provider and
    summary helper logic.
  - Kept `Session._get_compaction_provider(...)` and
    `Session._generate_summary(...)` as thin wrappers delegating to the helper
    module.
  - Behavior parity preserved: lazy provider creation, compaction cache
    semantics, and logger lifecycle.
  - Focused validation passed:
    - `.venv/bin/ruff check nexus3/session/session.py nexus3/session/compaction_runtime.py tests/unit/session/test_session_cancellation.py tests/unit/session/test_enforcer.py tests/unit/session/test_session_permission_kernelization.py tests/unit/test_compaction.py tests/unit/test_context_manager.py tests/unit/context/test_graph.py tests/unit/context/test_compiler.py tests/unit/context/test_compile_baseline.py`
    - `.venv/bin/mypy nexus3/session/session.py nexus3/session/compaction_runtime.py`
    - `.venv/bin/pytest -q tests/unit/session/test_session_cancellation.py tests/unit/session/test_enforcer.py tests/unit/session/test_session_permission_kernelization.py` (`54 passed`)
    - `.venv/bin/pytest -q tests/unit/test_compaction.py tests/unit/test_context_manager.py tests/unit/context/test_graph.py tests/unit/context/test_compiler.py tests/unit/context/test_compile_baseline.py` (`75 passed`)
- 2026-03-09: Phase 2B (Session tool execution primitives extraction)
  completed in WSL.
  - Added `nexus3/session/tool_runtime.py` for extracted tool execution
    primitives.
  - Kept `Session._execute_skill(...)` and
    `Session._execute_tools_parallel(...)` as thin wrappers delegating to
    `tool_runtime.py`.
  - Behavior parity preserved: timeout handling, exception mapping, and
    sanitization semantics.
  - Focused validation passed:
    - `.venv/bin/ruff check nexus3/session/session.py nexus3/session/compaction_runtime.py nexus3/session/tool_runtime.py`
    - `.venv/bin/mypy nexus3/session/session.py nexus3/session/compaction_runtime.py nexus3/session/tool_runtime.py`
    - `.venv/bin/pytest -q tests/unit/session/test_session_cancellation.py tests/unit/session/test_enforcer.py tests/unit/session/test_session_permission_kernelization.py` (`54 passed`)
    - `.venv/bin/pytest -q tests/integration/test_skill_execution.py tests/integration/test_permission_enforcement.py` (`30 passed`)
- 2026-03-09: Phase 2C (Session permission runtime extraction) completed in
  WSL.
  - Added `nexus3/session/permission_runtime.py` for permission runtime helper
    ownership.
  - Moved `_McpLevelAuthorizationAdapter`,
    `_GitLabLevelAuthorizationAdapter`, and internals of
    `_handle_mcp_permissions(...)` / `_handle_gitlab_permissions(...)` into
    runtime helpers.
  - Kept `Session` permission-handling methods as thin wrappers for
    compatibility.
  - Behavior parity preserved for kernel-authoritative decisions and
    confirmation flows.
  - Focused validation passed:
    - `.venv/bin/ruff check nexus3/session/session.py nexus3/session/compaction_runtime.py nexus3/session/tool_runtime.py nexus3/session/permission_runtime.py`
    - `.venv/bin/mypy nexus3/session/session.py nexus3/session/compaction_runtime.py nexus3/session/tool_runtime.py nexus3/session/permission_runtime.py`
    - `.venv/bin/pytest -q tests/unit/session/test_session_permission_kernelization.py tests/unit/session/test_enforcer.py tests/unit/session/test_session_cancellation.py` (`54 passed`)
    - `.venv/bin/pytest -q tests/integration/test_permission_enforcement.py tests/integration/test_skill_execution.py` (`30 passed`)
- 2026-03-09: Phase 2D (Session single-tool runtime extraction) completed in
  WSL.
  - Added `nexus3/session/single_tool_runtime.py` for single-tool execution
    runtime helper ownership.
  - Kept `Session._execute_single_tool(...)` as a thin wrapper delegating to
    `single_tool_runtime.py`.
  - Behavior parity preserved: permissions fail-closed, enforcer checks and
    confirmation flow (including multi-path allowances), skill
    resolution/unknown-skill handling, malformed `_raw_arguments` handling,
    argument validation, effective timeout derivation, and MCP/GitLab
    permission delegation.
  - Focused validation passed:
    - `.venv/bin/ruff check nexus3/session/session.py nexus3/session/compaction_runtime.py nexus3/session/tool_runtime.py nexus3/session/permission_runtime.py nexus3/session/single_tool_runtime.py`
    - `.venv/bin/mypy nexus3/session/session.py nexus3/session/compaction_runtime.py nexus3/session/tool_runtime.py nexus3/session/permission_runtime.py nexus3/session/single_tool_runtime.py`
    - `.venv/bin/pytest -q tests/unit/session/test_session_permission_kernelization.py tests/unit/session/test_enforcer.py tests/unit/session/test_session_cancellation.py` (`54 passed`)
    - `.venv/bin/pytest -q tests/integration/test_permission_enforcement.py tests/integration/test_skill_execution.py` (`30 passed`)
- 2026-03-09: Phase 2E (Session streaming runtime extraction) completed in
  WSL.
  - Added `nexus3/session/streaming_runtime.py` for callback-adapter streaming
    runtime helper ownership.
  - Kept `Session._execute_tool_loop_streaming(...)` as a thin wrapper
    delegating to `streaming_runtime.py`.
  - Behavior parity preserved: event->callback mapping and yielded chunk
    semantics remained unchanged.
  - Focused validation passed:
    - `.venv/bin/ruff check nexus3/session/session.py nexus3/session/streaming_runtime.py`
    - `.venv/bin/mypy nexus3/session/session.py nexus3/session/streaming_runtime.py`
    - `.venv/bin/pytest -q tests/integration/test_skill_execution.py -k "test_tool_call_executes_skill or test_multiple_tool_calls_in_sequence or test_multiple_tool_calls_in_parallel or test_failing_skill_error_in_context or test_max_iterations_prevents_infinite_loop or test_tool_loop_builds_correct_messages"` (`6 passed`)
    - `.venv/bin/pytest -q tests/unit/session/test_session_cancellation.py -k "test_stale_cancelled_tools_are_dropped or test_cancelled_tool_tail_repaired_before_next_user_turn or test_preflight_repairs_orphaned_tool_batch_before_user_turn or test_preflight_prunes_stale_tool_results_before_user_turn"` (`4 passed`)
    - `.venv/bin/pytest -q tests/unit/session/test_session_cancellation.py -k "test_cancellation_before_assistant_message_no_orphans or test_cancellation_after_first_tool_adds_remaining_results or test_cancelled_error_during_tool_creates_result"` (`3 passed`)
- 2026-03-09: Phase 2F (Session tool-loop events runtime extraction) completed
  in WSL.
  - Added `nexus3/session/tool_loop_events_runtime.py` for tool-loop event
    runtime helper ownership.
  - Kept `Session._execute_tool_loop_events(...)` as a thin wrapper delegating
    to `tool_loop_events_runtime.py`.
  - `send(...)` / `run_turn(...)` call paths remained unchanged.
  - Focused validation passed:
    - `.venv/bin/ruff check nexus3/session/session.py nexus3/session/tool_loop_events_runtime.py`
    - `.venv/bin/mypy nexus3/session/session.py nexus3/session/tool_loop_events_runtime.py`
    - `.venv/bin/pytest -q tests/unit/session/test_session_cancellation.py tests/unit/session/test_session_permission_kernelization.py tests/unit/session/test_enforcer.py` (`54 passed`)
    - `.venv/bin/pytest -q tests/integration/test_skill_execution.py tests/integration/test_permission_enforcement.py` (`30 passed`)
  - Live smoke validation passed:
    - `NEXUS_DEV=1 .venv/bin/python -m nexus3 --serve 9000`
    - `.venv/bin/python -m nexus3 rpc create test-agent --port 9000`
    - `.venv/bin/python -m nexus3 rpc send test-agent "describe your permissions and what you can do" --port 9000`
    - `.venv/bin/python -m nexus3 rpc destroy test-agent --port 9000`
    - `.venv/bin/python -m nexus3 rpc shutdown --port 9000`
- 2026-03-09: Phase 2G (Session turn-entry runtime extraction) completed in
  WSL.
  - Added `nexus3/session/turn_entry_runtime.py` for shared turn-entry
    preflight/reset helper ownership.
  - `send(...)` and `run_turn(...)` now route shared context-mode preflight and
    reset logic through `prepare_turn_entry(...)`.
  - Behavior parity preserved; tool-loop runtime behavior was unchanged in this
    slice.
  - Focused validation passed:
    - `.venv/bin/ruff check nexus3/session/session.py nexus3/session/turn_entry_runtime.py`
    - `.venv/bin/mypy nexus3/session/session.py nexus3/session/turn_entry_runtime.py`
    - `.venv/bin/pytest -q tests/unit/session/test_session_cancellation.py` (`12 passed`)
    - `.venv/bin/pytest -q tests/integration/test_skill_execution.py tests/integration/test_permission_enforcement.py tests/integration/test_chat.py` (`40 passed, 2 skipped`)
  - Live smoke validation passed:
    - `NEXUS_DEV=1 .venv/bin/python -m nexus3 --serve 9000`
    - `.venv/bin/python -m nexus3 rpc create test-agent --port 9000`
    - `.venv/bin/python -m nexus3 rpc send test-agent "describe your permissions and what you can do" --port 9000`
    - `.venv/bin/python -m nexus3 rpc destroy test-agent --port 9000`
    - `.venv/bin/python -m nexus3 rpc shutdown --port 9000`
- Next gate: execute remaining post-turn-entry Session core `send(...)` /
  `run_turn(...)` extraction internals with focused parity checks.

## Testing Strategy

- Before each extraction slice, lock behavior with focused parity tests and
  update only import paths when possible.
- Maintain existing high-signal suites as gate checks:
  - `.venv/bin/pytest -q tests/unit/cli/test_repl_safe_sink.py tests/unit/test_repl_commands.py tests/unit/test_pool.py tests/unit/test_rpc_dispatcher.py tests/unit/session/test_enforcer.py tests/unit/session/test_session_permission_kernelization.py`
  - `.venv/bin/ruff check nexus3/cli nexus3/session nexus3/rpc nexus3/display tests/unit/cli tests/unit/session tests/unit/rpc tests/unit`
  - `.venv/bin/mypy nexus3/cli nexus3/session nexus3/rpc nexus3/display`
- Add module-move regression tests where current coverage is weak (import-path
  stability and runtime wiring checks).

## Implementation Checklist

- [x] Establish extraction map with old->new module ownership and stable
      compatibility import boundaries.
- [x] Complete REPL formatting-helper extraction slice with parity checks.
- [x] Complete REPL extraction slices with parity checks.
- [x] Complete Session Phase 2A compaction runtime helper extraction with
      focused parity checks.
- [x] Complete Session Phase 2B tool execution primitives extraction with
      focused parity checks.
- [x] Complete Session Phase 2C permission runtime extraction with focused
      parity checks.
- [x] Complete Session Phase 2D single-tool runtime extraction with focused
      parity checks.
- [x] Complete Session Phase 2E streaming runtime extraction with focused
      parity checks.
- [x] Complete Session Phase 2F tool-loop events runtime extraction with
      focused parity checks.
- [x] Complete Session Phase 2G turn-entry runtime extraction with focused
      parity checks.
- [ ] Complete remaining post-turn-entry Session core `send(...)` /
      `run_turn(...)` extraction internals with parity checks.
- [ ] Complete Pool extraction slices with parity checks.
- [ ] Land display-config cleanup with documented override contract.
- [ ] Remove temporary compatibility wrappers after one full green cycle.
- [ ] Update deferred tracker rows for structural refactors and display config.

## Documentation Updates

- Update `AGENTS_NEXUS3CONFIGOPS.md` deferred structural-refactor entries.
- Update `CLAUDE.md` Deferred Work table once each tracked item is complete.
- Add a short migration map in module READMEs for contributors.

## Related Documents

- [DRY-CLEANUP-PLAN.md](/home/inc/repos/NEXUS3/docs/plans/DRY-CLEANUP-PLAN.md)
- [ARCH-MILESTONE-SCHEDULE-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
