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

- [ ] Establish extraction map with old->new module ownership and stable
      compatibility import boundaries.
- [ ] Complete REPL extraction slices with parity checks.
- [ ] Complete Session extraction slices with parity checks.
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
