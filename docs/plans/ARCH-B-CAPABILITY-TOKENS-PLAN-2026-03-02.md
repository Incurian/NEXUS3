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

- [ ] Define capability schema and signer/verifier.
- [ ] Integrate into direct API path.
- [ ] Integrate optional HTTP transport.
- [ ] Remove legacy identity-only authorization path.

## Documentation Updates

- Update RPC docs for delegation model and wire protocol changes.
- Document migration timeline for header deprecation.

## Related Documents

- [Reviews Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- [Plans Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/plans/README.md)
- [Canonical Review Master Final](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- [Architecture Investigation](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- [Architecture Milestone Schedule](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
