# Plan C: Request-Scoped Immutable Execution Context (2026-03-02)

## Overview

Replace shared mutable request identity state with immutable per-request context propagated end-to-end.

## Scope

Included:
- Remove mutable shared requester storage in global dispatcher path.
- Make skill execution request-safe (no per-call mutable state on singleton skill instances).
- Introduce request context object (request id, requester, policy snapshot, trace id).

Deferred:
- Wider service-container immutability redesign.

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

- [ ] Introduce request context model.
- [ ] Remove global mutable requester field.
- [ ] Make selected built-in skills stateless per call.
- [ ] Add concurrency tests and stress-style regressions.

## Documentation Updates

- Update RPC/session docs for request context propagation.
- Document skill statelessness expectations for contributors.

## Related Documents

- [Reviews Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- [Plans Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/plans/README.md)
- [Canonical Review Master Final](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- [Architecture Investigation](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- [Architecture Milestone Schedule](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
