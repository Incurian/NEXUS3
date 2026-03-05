# Plan H Follow-On: RPC Error Shim Retirement (2026-03-05)

## Overview

Retire legacy compatibility error-text shims in JSON-RPC boundary handling after
strict ingress rollout has stabilized, while keeping deterministic boundary
errors and minimizing downstream client breakage.

## Scope

Included:
- Inventory and classify remaining compatibility-preserving error-text shims
  across protocol and dispatcher ingress.
- Define a canonical error-surface policy for malformed request/params paths.
- Remove obsolete wording-mapping branches where compatibility windows are
  closed.

Deferred:
- JSON-RPC error code remapping or semantic changes.
- Broader non-RPC user-facing copy overhaul.

Excluded:
- New RPC method design.
- Client transport/auth changes not directly related to error-shim removal.

## Design Decisions and Rationale

1. Preserve deterministic machine behavior; simplify string-compat only where
   safe.
2. Remove shim branches incrementally with explicit regression updates.
3. Keep notification semantics unchanged (`id=None` malformed requests still
   return no response).

## Implementation Details

Primary files to change:
- [protocol.py](/home/inc/repos/NEXUS3/nexus3/rpc/protocol.py)
- [dispatch_core.py](/home/inc/repos/NEXUS3/nexus3/rpc/dispatch_core.py)
- [dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/dispatcher.py)
- [global_dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/global_dispatcher.py)
- [schemas.py](/home/inc/repos/NEXUS3/nexus3/rpc/schemas.py)
- [README.md](/home/inc/repos/NEXUS3/nexus3/rpc/README.md)
- [test_schema_ingress_wiring.py](/home/inc/repos/NEXUS3/tests/unit/rpc/test_schema_ingress_wiring.py)
- [test_client.py](/home/inc/repos/NEXUS3/tests/unit/test_client.py)

Planned slices:
1. Build shim inventory with current behavior matrix (message text + code + path).
2. Mark each shim as:
   - required invariant behavior
   - compatibility-only mapping eligible for removal
3. Remove compatibility-only mappings in smallest safe groups and update tests.
4. Update RPC docs with post-shim canonical diagnostics examples.

## Testing Strategy

- Keep strict ingress negative-path coverage green while updating expected error
  text where intentionally changed.
- Add explicit regressions for canonical malformed-envelope and malformed-params
  outputs across:
  - protocol parsing (`parse_request`, `parse_response`)
  - direct dispatch ingress
  - method-params schema ingress
- Run focused checks:
  - `.venv/bin/pytest -q tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/test_client.py tests/unit/test_rpc_dispatcher.py tests/unit/test_global_dispatcher.py`
  - `.venv/bin/ruff check nexus3/rpc/protocol.py nexus3/rpc/dispatch_core.py nexus3/rpc/dispatcher.py nexus3/rpc/global_dispatcher.py tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/test_client.py tests/unit/test_rpc_dispatcher.py tests/unit/test_global_dispatcher.py`
  - `.venv/bin/mypy nexus3/rpc/protocol.py nexus3/rpc/dispatch_core.py nexus3/rpc/dispatcher.py nexus3/rpc/global_dispatcher.py`

## Implementation Checklist

- [ ] Create and document RPC shim inventory with removal priority tiers.
- [ ] Define canonical post-shim diagnostics policy for malformed RPC inputs.
- [ ] Remove compatibility-only shim branches in protocol/dispatch layers.
- [ ] Update focused regression expectations and ensure no behavior drift in
      codes/notification semantics.
- [ ] Sync Plan H status, RPC README examples, and AGENTS running status.

## Documentation Updates

- Update [ARCH-H-STRICT-SCHEMA-GATES-PLAN-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-H-STRICT-SCHEMA-GATES-PLAN-2026-03-02.md)
  deferred notes when shim retirement is complete.
- Update [ARCH-MILESTONE-SCHEDULE-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
  follow-on backlog status.
- Update [rpc/README.md](/home/inc/repos/NEXUS3/nexus3/rpc/README.md)
  malformed-request diagnostics examples.

## Related Documents

- [ARCH-H-STRICT-SCHEMA-GATES-PLAN-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-H-STRICT-SCHEMA-GATES-PLAN-2026-03-02.md)
- [ARCH-MILESTONE-SCHEDULE-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
