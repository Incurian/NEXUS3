# Plan C: Request-Scoped Immutable Execution Context (2026-03-02)

## Overview

Replace shared mutable request identity state with immutable per-request context propagated end-to-end.

## Scope

Included:
- Remove mutable shared requester storage in global dispatcher path.
- Make skill execution request-safe (no per-call mutable state on singleton skill instances).
- Introduce request context object (request id, requester, policy snapshot, trace id).

Deferred:
- Wider service-container immutability redesign (follow-on plan:
  [ARCH-C-SERVICE-CONTAINER-IMMUTABILITY-PLAN-2026-03-05.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-C-SERVICE-CONTAINER-IMMUTABILITY-PLAN-2026-03-05.md)).

Excluded:
- Capability delegation semantics (Plan B).

## Design Decisions and Rationale

1. No authorization-relevant mutable state on shared dispatcher objects.
2. Request context is passed explicitly (or via tightly-scoped `ContextVar`).
3. Skill instances must be stateless per call.

## Implementation Details

Primary files to change:
- [rpc/global_dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/global_dispatcher.py)
- [rpc/dispatch_core.py](/home/inc/repos/NEXUS3/nexus3/rpc/dispatch_core.py)
- [rpc/http.py](/home/inc/repos/NEXUS3/nexus3/rpc/http.py)
- [session/session.py](/home/inc/repos/NEXUS3/nexus3/session/session.py)
- [skill/registry.py](/home/inc/repos/NEXUS3/nexus3/skill/registry.py)
- [skill/base.py](/home/inc/repos/NEXUS3/nexus3/skill/base.py)
- [skill/builtin/bash.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/bash.py)
- [skill/builtin/run_python.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/run_python.py)
- [skill/services.py](/home/inc/repos/NEXUS3/nexus3/skill/services.py)
- New: `nexus3/core/request_context.py`

Phases:
1. Add request-context model and dispatcher propagation.
2. Refactor shared mutable requester field out of dispatcher.
3. Refactor singleton skills to avoid per-call state on `self`.
4. Add optional guardrails to detect request-state mutation in shared services.

## Testing Strategy

- Add concurrent dispatch tests proving requester isolation.
- Add parallel skill invocation tests for state isolation.
- Re-run destroy/send authorization concurrency scenarios.

## Implementation Checklist

- [x] Introduce request context model.
- [x] Remove global mutable requester field.
- [x] Make selected built-in skills stateless per call.
- [x] Add concurrency tests and stress-style regressions.

Closeout note (2026-03-05):
- The remaining deferred boundary for service-container immutability is tracked
  in [ARCH-C-SERVICE-CONTAINER-IMMUTABILITY-PLAN-2026-03-05.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-C-SERVICE-CONTAINER-IMMUTABILITY-PLAN-2026-03-05.md).

### M2 Commit 1 Status (2026-03-04)

- Added immutable `RequestContext` model at `nexus3/core/request_context.py`.
- Propagated request context through `GlobalDispatcher.dispatch()` into destroy-path authorization.
- Removed shared mutable requester field usage in global destroy flow.
- Added focused unit coverage for `RequestContext` immutability/field shape and
  overlapping destroy dispatch requester isolation in `tests/unit/`.

### M2 Commit 2 Status (2026-03-05)

- Refactored `bash_safe`, `shell_UNSAFE`, and `run_python` to remove per-call
  mutable instance state (`_args`, `_command`, `_code`).
- Updated execution flow to pass parsed command args/code through local
  process-factory parameters.
- Updated Windows shell-selection tests to assert subprocess call arguments
  directly.
- Added focused concurrent `run_python` execution test proving per-call code
  payload isolation on a shared skill instance.

### M2 Commit 3 Status (2026-03-05)

- Propagated immutable requester context through agent-scoped HTTP dispatch in
  `nexus3/rpc/http.py`, so `/agent/{id}` routes no longer drop `X-Nexus-Agent`
  before reaching `Dispatcher.dispatch(..., requester_id=...)`.
- Propagated requester context through `create_agent` follow-up initial-message
  dispatch in `nexus3/rpc/global_dispatcher.py` for both waiting and queued
  paths.
- Extended `NexusSkill` HTTP fallback in `nexus3/skill/base.py` and
  `nexus3/client.py` to forward requester identity when operating from agent
  context, preserving requester-aware authorization outside the in-process
  `DirectAgentAPI` path.
- Added focused regressions in `tests/unit/test_http_pipeline_layers.py`,
  `tests/unit/test_initial_message.py`, `tests/unit/test_client.py`, and
  `tests/unit/test_nexus_skill_requester_propagation.py`.

### M2 Commit 4 Status (2026-03-05)

- Threaded immutable `RequestContext` through the remaining agent-scoped
  read-only dispatcher handlers in `nexus3/rpc/dispatcher.py`
  (`get_tokens`, `get_context`, `get_messages`), so agent-scoped caller
  identity is no longer dropped at the handler boundary.
- Added focused propagation coverage in `tests/unit/test_rpc_dispatcher.py`
  proving those handlers receive the caller's `requester_id` and derived
  `request_id`.

## Documentation Updates

- Update RPC/session docs for request context propagation.
- Document skill statelessness expectations for contributors.

## Related Documents

- [Reviews Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- [Plans Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/plans/README.md)
- [Canonical Review Master Final](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- [Architecture Investigation](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- [Architecture Milestone Schedule](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
