# Plan A: Single Authorization Kernel (2026-03-02)

## Overview

Consolidate fragmented authorization logic into one policy decision layer used consistently by session, RPC, and tool execution paths.

## Scope

Included:
- Introduce `AuthorizationKernel` and typed decision model.
- Route existing auth checks through kernel adapters without changing behavior in phase 1.
- Centralize lifecycle authorization (create/destroy/send/targeting).

Deferred:
- Capability-token migration (covered in Plan B).

Excluded:
- Broad permission semantics redesign.

## Design Decisions and Rationale

1. Preserve behavior first, then tighten policy.
2. One entrypoint for both visibility and execution authorization decisions.
3. Fail-closed defaults for unknown actions/resources.

## Implementation Details

Primary files to change:
- [session/enforcer.py](/home/inc/repos/NEXUS3/nexus3/session/enforcer.py)
- [session/session.py](/home/inc/repos/NEXUS3/nexus3/session/session.py)
- [rpc/pool.py](/home/inc/repos/NEXUS3/nexus3/rpc/pool.py)
- [rpc/global_dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/global_dispatcher.py)
- [rpc/dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/dispatcher.py)
- [rpc/agent_api.py](/home/inc/repos/NEXUS3/nexus3/rpc/agent_api.py)
- [core/permissions.py](/home/inc/repos/NEXUS3/nexus3/core/permissions.py)
- New: `nexus3/core/authorization_kernel.py`

Phases:
1. Add kernel interfaces and decision DTOs.
2. Add shadow-mode parity checks comparing legacy decision vs kernel decision.
3. Route all tool/lifecycle checks through kernel adapters.
4. Remove duplicated call-site policy branches once parity is stable.

## Testing Strategy

- Add unit parity tests for kernel vs legacy decisions.
- Extend security tests around destroy/create authorization.
- Ensure integration parity for sandboxed parent-send and inheritance tests.

## Implementation Checklist

- [x] Define `AuthorizationKernel` API and decision schema. (M0 Slice A foundation)
- [ ] Implement adapters for session and RPC call sites.
- [x] Add parity logging/assertions under test flag. (M2 Commit 2 testing slice: destroy parity matrix + shadow mismatch warning assertion)
- Progress (2026-03-05): M2 Commit 2 completed for destroy authorization shadow parity in [rpc/pool.py](/home/inc/repos/NEXUS3/nexus3/rpc/pool.py) with legacy-enforced decisions + kernel shadow compare mismatch warning.
- Progress (2026-03-05): M2 Commit 3 completed for targeting authorization shadow parity in [session/enforcer.py](/home/inc/repos/NEXUS3/nexus3/session/enforcer.py) with legacy-enforced decisions + kernel shadow compare mismatch warning (`target_auth_shadow_mismatch`).
- Progress (2026-03-05): M2 Commit 4 completed for tool-action authorization shadow parity in [session/enforcer.py](/home/inc/repos/NEXUS3/nexus3/session/enforcer.py) with legacy-enforced decisions + kernel shadow compare mismatch warning (`tool_action_auth_shadow_mismatch`).
- Progress (2026-03-05): M2 Commit 5 completed for send-lifecycle authorization shadow parity in [rpc/dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/dispatcher.py) with legacy-enforced decisions + kernel shadow compare mismatch warning (`send_auth_shadow_mismatch`).
- Progress (2026-03-05): M2 Commit 6 completed for create-lifecycle authorization shadow parity in [rpc/pool.py](/home/inc/repos/NEXUS3/nexus3/rpc/pool.py) at parent ceiling gates with legacy-enforced decisions + kernel shadow compare mismatch warning (`create_auth_shadow_mismatch`).
- Progress (2026-03-05): M2 Commit 7 expanded create-lifecycle parity coverage for delta-ceiling branch in [tests/unit/rpc/test_pool_create_auth_shadow.py](/home/inc/repos/NEXUS3/tests/unit/rpc/test_pool_create_auth_shadow.py), confirming both parity and mismatch-warning behavior while legacy enforcement remains authoritative.
- Progress (2026-03-05): M2 Commit 8 propagated create requester context through [rpc/agent_api.py](/home/inc/repos/NEXUS3/nexus3/rpc/agent_api.py), [rpc/global_dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/global_dispatcher.py), and [rpc/pool.py](/home/inc/repos/NEXUS3/nexus3/rpc/pool.py), adding shadow-only requester/parent binding parity warnings while preserving legacy create enforcement and error semantics.
- Progress (2026-03-05): M2 Commit 9 added `shutdown_server` lifecycle shadow parity in [rpc/global_dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/global_dispatcher.py), with request-context requester propagation and mismatch warning telemetry while preserving legacy always-allow behavior and response/error semantics.
- Progress (2026-03-05): M2 Commit 10 added `list_agents` lifecycle shadow parity in [rpc/global_dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/global_dispatcher.py), including request-context requester propagation from [rpc/agent_api.py](/home/inc/repos/NEXUS3/nexus3/rpc/agent_api.py) and mismatch warning telemetry while preserving legacy always-allow list behavior and response semantics.
- Progress (2026-03-06): M2 Commit 11 added agent-scoped lifecycle shadow parity in [rpc/dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/dispatcher.py) for `shutdown`/`cancel`/`compact`, added trusted requester-context propagation for agent-scoped dispatch in [rpc/agent_api.py](/home/inc/repos/NEXUS3/nexus3/rpc/agent_api.py), and prioritized trusted requester identity in send shadow principal selection while preserving legacy behavior and error semantics as authoritative.
- Progress (2026-03-06): M3 Commit 12 started duplicate-branch removal by making `list_agents` and `shutdown_server` kernel-authoritative in [rpc/global_dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/global_dispatcher.py), removing legacy shadow-only always-allow branches while preserving allow-path responses and adding fail-closed deny behavior coverage in [tests/unit/test_pool.py](/home/inc/repos/NEXUS3/tests/unit/test_pool.py).
- Progress (2026-03-06): M3 Commit 13 continued duplicate-branch removal by making agent-scoped lifecycle authorization in [rpc/dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/dispatcher.py) (`shutdown`/`cancel`/`compact`) kernel-authoritative with shared enforcement helper and fail-closed deny behavior, replacing shadow-only legacy-allow branches while preserving allow-path responses and updating [tests/unit/test_rpc_dispatcher.py](/home/inc/repos/NEXUS3/tests/unit/test_rpc_dispatcher.py).
- Progress (2026-03-06): M3 Commit 14 made send authorization in [rpc/dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/dispatcher.py) kernel-authoritative, removing shadow-only legacy allow/deny branch + mismatch warning logic while preserving trusted requester precedence and legacy YOLO/no-REPL deny wording (`Cannot send to YOLO agent - no REPL connected`) with focused updates in [tests/unit/test_rpc_dispatcher.py](/home/inc/repos/NEXUS3/tests/unit/test_rpc_dispatcher.py).
- Progress (2026-03-06): M3 Commit 15 made destroy authorization in [rpc/pool.py](/home/inc/repos/NEXUS3/nexus3/rpc/pool.py) kernel-authoritative, removing legacy shadow-only allow/deny branch logic while preserving existing AuthorizationError wording and adding focused destroy authorization coverage in [tests/unit/test_pool.py](/home/inc/repos/NEXUS3/tests/unit/test_pool.py) (self/parent allow, unauthorized deny, forced-kernel-deny authoritative behavior).
- Progress (2026-03-06): M3 Commit 16 made tool-action authorization in [session/enforcer.py](/home/inc/repos/NEXUS3/nexus3/session/enforcer.py) (`_check_action_allowed`) kernel-authoritative, removing legacy shadow-mismatch warning branch while preserving user-facing deny wording and adding authoritative-behavior coverage updates in [tests/unit/session/test_enforcer.py](/home/inc/repos/NEXUS3/tests/unit/session/test_enforcer.py).
- Progress (2026-03-06): M3 Commit 17 made target authorization in [session/enforcer.py](/home/inc/repos/NEXUS3/nexus3/session/enforcer.py) (`_check_target_allowed`) kernel-authoritative, removing legacy-authoritative allow/deny and shadow-mismatch warning logic while preserving target-deny wording semantics and adding focused forced-kernel-deny coverage in [tests/unit/session/test_enforcer.py](/home/inc/repos/NEXUS3/tests/unit/session/test_enforcer.py).
- [ ] Remove duplicate authorization branches.

## Documentation Updates

- Update `nexus3/core/README.md` and `nexus3/rpc/README.md` for centralized authorization flow.
- Update AGENTS/CLAUDE sections describing permission checks.

## Related Documents

- [Reviews Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- [Plans Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/plans/README.md)
- [Canonical Review Master Final](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- [Architecture Investigation](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- [Architecture Milestone Schedule](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
