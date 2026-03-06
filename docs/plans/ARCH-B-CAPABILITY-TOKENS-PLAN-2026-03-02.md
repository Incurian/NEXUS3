# Plan B: Capability Tokens for Delegation (2026-03-02)

## Overview

Move from caller-id/header-driven delegation to explicit scoped capabilities for agent-to-agent operations.

## Scope

Included:
- Introduce opaque capability objects with scope, expiry, and revocation.
- Start in-process for direct API path.
- Optional HTTP transport phase for cross-process delegation.

Deferred:
- Full removal of legacy headers until migration complete.

Excluded:
- External auth provider integration.

## Design Decisions and Rationale

1. Execute after Plan A baseline to avoid mixed policy semantics.
2. Capability scopes must be attenuated (child cannot exceed parent grant).
3. Revoke and expiry must be first-class, not optional add-ons.

## Implementation Details

Primary files to change:
- [rpc/global_dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/global_dispatcher.py)
- [rpc/pool.py](/home/inc/repos/NEXUS3/nexus3/rpc/pool.py)
- [rpc/http.py](/home/inc/repos/NEXUS3/nexus3/rpc/http.py)
- [rpc/agent_api.py](/home/inc/repos/NEXUS3/nexus3/rpc/agent_api.py)
- [skill/base.py](/home/inc/repos/NEXUS3/nexus3/skill/base.py)
- [client.py](/home/inc/repos/NEXUS3/nexus3/client.py)
- New: `nexus3/core/capabilities.py`

Phases:
1. Define capability format and verification API.
2. Use capabilities in direct in-process calls.
3. Add optional signed/opaque HTTP capability transport.
4. Deprecate `X-Nexus-Agent` identity semantics and remove legacy path.

## Testing Strategy

- Add tests for attenuation, expiry, revocation, and replay rejection.
- Add HTTP path tests for malformed/expired capabilities.
- Preserve compatibility tests during transition period.
- Add explicit negative tests for malformed capability payloads on direct API and HTTP ingress paths.

## Implementation Checklist

- [x] Define capability schema and signer/verifier.
- [x] Integrate into direct API path.
- [x] Integrate optional HTTP transport (Phase 3A ingress/client compatibility path).
- [ ] Remove legacy identity-only authorization path.

## Execution Status

- 2026-03-05: Phase 1 completed and committed as `14bc820`.
- Added `nexus3/core/capabilities.py` with:
  - typed capability claims model (`CapabilityClaims`)
  - signed token issue/verify service (`CapabilitySigner`) using
    HMAC-SHA256 over canonical JSON payloads
  - explicit error taxonomy for format/signature/expiry/scope/revocation/replay
  - revocation/replay protocols and in-memory stores
  - secret generation helper (`generate_capability_secret`)
- Exported capability APIs through `nexus3/core/__init__.py`.
- Added focused regressions in `tests/unit/core/test_capabilities.py`:
  - round-trip issue/verify
  - tamper/signature rejection
  - expiry and required-scope checks
  - parent attenuation (scope + expiry)
  - revocation and replay rejection
  - malformed token rejection
- Updated `nexus3/core/README.md` with capability token API/module docs.
- Validation:
  - `.venv/bin/ruff check nexus3/core/capabilities.py nexus3/core/__init__.py nexus3/core/README.md tests/unit/core/test_capabilities.py` passed.
  - `.venv/bin/mypy nexus3/core/capabilities.py nexus3/core/__init__.py` passed.
  - `.venv/bin/pytest -q tests/unit/core/test_capabilities.py` passed (`11 passed`).
- 2026-03-05: Phase 2 completed and committed as `43773be`.
- Added direct-path capability scope registry in `nexus3/core/capabilities.py`
  (`DIRECT_RPC_SCOPE_BY_METHOD`, `DIRECT_RPC_ALL_SCOPES`,
  `direct_rpc_scope_for_method`).
- Added shared capability-ingress identity resolution in
  `nexus3/rpc/dispatch_core.py::resolve_dispatch_identity(...)`.
- Updated direct dispatchers to accept optional capability tokens and build
  `RequestContext` from verified claims:
  - `nexus3/rpc/dispatcher.py::Dispatcher.dispatch(...)`
  - `nexus3/rpc/global_dispatcher.py::GlobalDispatcher.dispatch(...)`
- Updated direct in-process API path to mint and attach per-call capability
  tokens via pool-owned issuance:
  - `nexus3/rpc/agent_api.py`
  - `nexus3/rpc/pool.py` (`issue_direct_capability`, `verify_direct_capability`,
    destroy-time revocation of tracked issued tokens)
- Added focused capability-path regressions:
  - `tests/unit/test_agent_api.py`
  - `tests/unit/test_rpc_dispatcher.py`
  - `tests/unit/test_global_dispatcher.py`
  - `tests/unit/test_pool.py`
  - `tests/unit/core/test_request_context.py`
- Validation:
  - `.venv/bin/ruff check nexus3/core/capabilities.py nexus3/core/request_context.py nexus3/core/__init__.py nexus3/rpc/dispatch_core.py nexus3/rpc/dispatcher.py nexus3/rpc/global_dispatcher.py nexus3/rpc/agent_api.py nexus3/rpc/pool.py nexus3/rpc/http.py tests/unit/core/test_request_context.py tests/unit/test_agent_api.py tests/unit/test_rpc_dispatcher.py tests/unit/test_global_dispatcher.py tests/unit/test_pool.py` passed.
  - `.venv/bin/mypy nexus3/core/capabilities.py nexus3/core/request_context.py nexus3/core/__init__.py nexus3/rpc/dispatch_core.py nexus3/rpc/dispatcher.py nexus3/rpc/global_dispatcher.py nexus3/rpc/agent_api.py nexus3/rpc/pool.py nexus3/rpc/http.py` passed.
  - `.venv/bin/pytest -q tests/unit/core/test_request_context.py tests/unit/test_agent_api.py tests/unit/test_rpc_dispatcher.py tests/unit/test_global_dispatcher.py tests/unit/test_pool.py tests/unit/test_initial_message.py` passed (`147 passed`).
  - `.venv/bin/pytest -q tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/test_nexus_skill_requester_propagation.py` passed (`75 passed`).
  - Live validation executed on `2026-03-05`:
    - `.venv/bin/python -m nexus3 --serve 9000`
    - `.venv/bin/python -m nexus3 rpc create test-agent --port 9000`
    - `.venv/bin/python -m nexus3 rpc send test-agent "describe your permissions and what you can do" --port 9000`
    - `.venv/bin/python -m nexus3 rpc destroy test-agent --port 9000`
- 2026-03-05: Phase 3A completed (local branch state, commit pending).
- Added HTTP capability transport wiring:
  - `nexus3/rpc/http.py` now extracts optional `X-Nexus-Capability` and passes
    it through dispatch as `capability_token` on both global and agent routes.
  - `nexus3/client.py` now supports explicit optional
    `capability_token` configuration and emits `X-Nexus-Capability` only when
    set (default caller behavior unchanged).
  - `nexus3/rpc/README.md` documents HTTP capability precedence/fallback:
    valid capability subject overrides requester identity; requester-header
    fallback applies only when capability header is absent; invalid capability
    fails with deterministic `INVALID_PARAMS`.
- Added focused regressions:
  - `tests/unit/test_http_pipeline_layers.py`
  - `tests/unit/test_client.py`
- Validation:
  - `.venv/bin/ruff check nexus3/rpc/http.py nexus3/client.py nexus3/rpc/README.md tests/unit/test_http_pipeline_layers.py tests/unit/test_client.py tests/unit/test_global_dispatcher.py tests/unit/test_rpc_dispatcher.py` passed.
  - `.venv/bin/mypy nexus3/rpc/http.py nexus3/client.py` passed.
  - `.venv/bin/pytest -q tests/unit/test_http_pipeline_layers.py tests/unit/test_client.py tests/unit/test_global_dispatcher.py tests/unit/test_rpc_dispatcher.py` passed (`79 passed`, `12 warnings`).
  - Live validation executed on `2026-03-05`:
    - `.venv/bin/python -m nexus3 --serve 9000`
    - `.venv/bin/python -m nexus3 rpc create arch-b-http-cap --port 9000`
    - `.venv/bin/python -m nexus3 rpc send arch-b-http-cap "describe your permissions and what you can do" --port 9000`
    - `.venv/bin/python -m nexus3 rpc destroy arch-b-http-cap --port 9000`

## Documentation Updates

- Update RPC docs for delegation model and wire protocol changes.
- Document migration timeline for header deprecation.

## Related Documents

- [Reviews Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- [Plans Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/plans/README.md)
- [Canonical Review Master Final](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- [Architecture Investigation](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- [Architecture Milestone Schedule](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
