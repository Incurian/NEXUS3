# Plan A Follow-On: Authorization Request Model V2 (2026-03-05)

## Overview

Eliminate the remaining Plan A accepted boundary where create-stage
`parent_can_grant` booleans are precomputed in `rpc/pool.py` and then consumed
by adapter decisions. Move that grant computation into adapter-authoritative
evaluation using richer typed authorization request context.

## Scope

Included:
- Extend authorization request context modeling to support the create-stage
  data needed for adapter-local grant evaluation.
- Migrate create-stage grant checks from pool precompute to adapter evaluation.
- Preserve existing allow/deny semantics and user-facing error wording while
  removing the precompute boundary.

Deferred:
- Capability-token migration and delegation identity redesign (Plan B).
- Broad permission semantics redesign beyond current create-stage behavior.

Excluded:
- New permission presets or policy-level behavior changes.
- Non-create authorization logic unless required for shared type migration.

## Design Decisions and Rationale

1. Keep authorization fail-closed during migration.
2. Prefer typed context structures over ad hoc scalar booleans for create-stage
   state.
3. Preserve API- and UX-visible behavior first; structural cleanup second.

## Implementation Details

Primary files to change:
- [authorization_kernel.py](/home/inc/repos/NEXUS3/nexus3/core/authorization_kernel.py)
- [pool.py](/home/inc/repos/NEXUS3/nexus3/rpc/pool.py)
- [test_pool_create_auth_shadow.py](/home/inc/repos/NEXUS3/tests/unit/rpc/test_pool_create_auth_shadow.py)
- [test_pool.py](/home/inc/repos/NEXUS3/tests/unit/test_pool.py)
- [ARCH-A-AUTH-KERNEL-PLAN-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-A-AUTH-KERNEL-PLAN-2026-03-02.md)

Planned slices:
1. Introduce a typed create-context shape for authorization requests, with
   compatibility support for current scalar-only consumers.
2. Update `_CreateAuthorizationAdapter` to compute base/delta `can_grant`
   decisions from typed create context instead of `parent_can_grant` booleans.
3. Remove create-stage `parent_can_grant` precompute from
   `AgentPool._create_unlocked()` and associated `_enforce_create_authorization`
   call sites.
4. Delete obsolete compatibility branches and tighten tests around adapter-first
   decision flow.

## Execution Status

- 2026-03-06: kickoff slice (Phase 1 typed create-context foundation) completed
  as committed baseline:
  - added typed create context/stage models to
    `nexus3/core/authorization_kernel.py` with scalar context compatibility
    (`to_context_map` / `from_context_map`).
  - wired create authorization paths in `nexus3/rpc/pool.py` to consume
    `CreateAuthorizationContext` + `CreateAuthorizationStage` while preserving
    existing allow/deny behavior.
  - added focused context-shape regressions in
    `tests/unit/core/test_authorization_kernel.py`.
- 2026-03-06: follow-on slice (Phase 2 + Phase 3) completed:
  - `_CreateAuthorizationAdapter` now computes base/delta ceiling grants from
    typed scalar context payloads (`parent_permissions_json`,
    `requested_permissions_json`) via adapter-local `AgentPermissions.can_grant(...)`.
  - removed create-stage `parent_can_grant` precompute plumbing from
    `AgentPool._create_unlocked(...)` and
    `AgentPool._enforce_create_authorization(...)` call sites.
  - added focused adapter-authoritative regressions in
    `tests/unit/rpc/test_pool_create_auth_shadow.py` for:
    - base/delta ceiling allow/deny from typed context permission payloads.
    - missing/malformed typed payload fail-closed behavior.
  - extended stage-order context regression in `tests/unit/test_pool.py` to
    assert no `parent_can_grant` field is emitted for create ceiling stages.
  - validation snapshot:
    - `.venv/Scripts/ruff.exe check nexus3/core/authorization_kernel.py nexus3/rpc/pool.py tests/unit/core/test_authorization_kernel.py` passed.
    - `.venv/Scripts/mypy.exe nexus3/core/authorization_kernel.py nexus3/rpc/pool.py` passed.
    - `.venv/Scripts/pytest.exe -q tests/unit/core/test_authorization_kernel.py tests/unit/rpc/test_pool_create_auth_shadow.py::test_create_adapter_base_ceiling_allow_uses_typed_context_permissions tests/unit/rpc/test_pool_create_auth_shadow.py::test_create_adapter_delta_ceiling_deny_uses_typed_context_permissions tests/unit/rpc/test_pool_create_auth_shadow.py::test_create_adapter_base_ceiling_missing_permissions_payload_denies tests/unit/rpc/test_pool_create_auth_shadow.py::test_create_adapter_base_ceiling_malformed_permissions_payload_denies` passed.
    - broader `tmp_path`-using pytest coverage remains blocked in this environment by host ACL denials creating/accessing pytest temp roots (`WinError 5`, `pytest-of-inc`).

## Testing Strategy

- Extend create authorization tests to prove adapter-local grant evaluation for:
  - base ceiling deny/allow
  - delta ceiling deny/allow
  - malformed or missing context fail-closed behavior
- Preserve coverage for requester/parent binding, max depth, and live-parent
  permission resolution.
- Run focused checks:
  - `.venv/bin/pytest -q tests/unit/rpc/test_pool_create_auth_shadow.py tests/unit/test_pool.py`
  - `.venv/bin/ruff check nexus3/rpc/pool.py nexus3/core/authorization_kernel.py tests/unit/rpc/test_pool_create_auth_shadow.py tests/unit/test_pool.py`
  - `.venv/bin/mypy nexus3/rpc/pool.py nexus3/core/authorization_kernel.py`

## Implementation Checklist

- [x] Define typed create-stage authorization context model in core auth kernel.
- [x] Migrate create adapter grant decisions to adapter-local computation.
- [x] Remove `parent_can_grant` precompute plumbing from pool call sites.
- [x] Add/adjust focused regressions for adapter-authoritative create checks.
- [x] Update Plan A closeout notes and AGENTS running status after completion.

## Documentation Updates

- Update [ARCH-A-AUTH-KERNEL-PLAN-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-A-AUTH-KERNEL-PLAN-2026-03-02.md)
  to remove the accepted-boundary defer note once migrated.
- Update [ARCH-MILESTONE-SCHEDULE-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
  status references if scheduling changes.
- Update `AGENTS.md` and `CLAUDE.md` authorization architecture notes if
  behavior/contract wording changes.

## Related Documents

- [ARCH-A-AUTH-KERNEL-PLAN-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-A-AUTH-KERNEL-PLAN-2026-03-02.md)
- [ARCH-MILESTONE-SCHEDULE-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
