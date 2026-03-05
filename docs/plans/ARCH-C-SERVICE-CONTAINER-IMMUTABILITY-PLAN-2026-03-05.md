# Plan C Follow-On: Service Container Immutability (2026-03-05)

## Overview

Close the remaining Plan C deferred boundary by replacing the globally mutable
`ServiceContainer` runtime pattern with an explicit immutable snapshot model and
typed mutation paths for the small set of fields that must change during an
agent lifetime.

## Scope

Included:
- Introduce an immutable service snapshot contract for agent runtime state.
- Replace ad hoc `services.register(...)` mutations in production paths with
  explicit update methods.
- Keep behavior parity for `/cd`, `/permissions`, `/model`, create/restore, and
  child tracking while removing open-ended container mutation from hot paths.

Deferred:
- Capability-token identity redesign (Plan B).
- Large test-fixture modernization for every `ServiceContainer` test double.

Excluded:
- Permission policy behavior changes.
- Skill API redesign outside service access/mutation contracts.

## Design Decisions and Rationale

1. Preserve behavior first; change state-shape and mutation discipline second.
2. Separate immutable boot-time dependencies from mutable per-agent state.
3. Require explicit typed mutation APIs for runtime changes (`cwd`,
   `permissions`, `model`, `child_agent_ids`) instead of generic `register`.

## Implementation Details

Primary files to change:
- [services.py](/home/inc/repos/NEXUS3/nexus3/skill/services.py)
- [pool.py](/home/inc/repos/NEXUS3/nexus3/rpc/pool.py)
- [repl_commands.py](/home/inc/repos/NEXUS3/nexus3/cli/repl_commands.py)
- [session.py](/home/inc/repos/NEXUS3/nexus3/session/session.py)
- [enforcer.py](/home/inc/repos/NEXUS3/nexus3/session/enforcer.py)
- [test_repl_commands.py](/home/inc/repos/NEXUS3/tests/unit/test_repl_commands.py)
- [test_pool.py](/home/inc/repos/NEXUS3/tests/unit/test_pool.py)
- New: `tests/unit/skill/test_service_container_immutability.py`

Planned slices:
1. Define typed immutable service snapshot(s) and constrained mutator API in
   `skill/services.py`.
2. Migrate pool create/restore wiring to initialize immutable snapshots.
3. Migrate REPL runtime mutations (`/cd`, `/permissions`, `/model`) onto typed
   mutator paths.
4. Remove production reliance on generic open-ended mutation primitives (or
   restrict them to test-only compatibility adapters with explicit TODO
   retirement notes).

## Testing Strategy

- Add focused tests proving mutation isolation and no cross-agent state bleed.
- Add regression coverage for each runtime mutation surface:
  - `/cd` updates cwd only for the targeted agent
  - `/permissions` updates policy + tool definitions correctly
  - `/model` updates provider/model context consistently
- Run focused checks:
  - `.venv/bin/pytest -q tests/unit/test_repl_commands.py tests/unit/test_pool.py tests/unit/session/test_enforcer.py tests/unit/session/test_session_permission_kernelization.py`
  - `.venv/bin/ruff check nexus3/skill/services.py nexus3/rpc/pool.py nexus3/cli/repl_commands.py nexus3/session/session.py nexus3/session/enforcer.py`
  - `.venv/bin/mypy nexus3/skill/services.py nexus3/rpc/pool.py nexus3/cli/repl_commands.py nexus3/session/session.py nexus3/session/enforcer.py`

## Implementation Checklist

- [ ] Add immutable service snapshot model and typed runtime mutation APIs.
- [ ] Migrate pool create/restore service wiring to snapshot initialization.
- [ ] Migrate REPL runtime mutation call sites to typed service mutators.
- [ ] Add focused immutability/isolation regressions for production mutation
      paths.
- [ ] Retire or explicitly scope generic mutation helpers to non-production use.
- [ ] Sync Plan C, milestone backlog, and AGENTS status after rollout.

## Documentation Updates

- Update [ARCH-C-REQUEST-CONTEXT-PLAN-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-C-REQUEST-CONTEXT-PLAN-2026-03-02.md)
  deferred note when immutability work lands.
- Update [skill/README.md](/home/inc/repos/NEXUS3/nexus3/skill/README.md)
  service-container usage guidance.
- Update `AGENTS.md` and `CLAUDE.md` deferred tracker entries for this item.

## Related Documents

- [ARCH-C-REQUEST-CONTEXT-PLAN-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-C-REQUEST-CONTEXT-PLAN-2026-03-02.md)
- [ARCH-MILESTONE-SCHEDULE-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
