# Plan Follow-On: Provider Keep-Alive Investigation (2026-03-05)

## Overview

Investigate the deferred provider keep-alive failure pattern
("fresh connection works, reused connection fails"), determine whether it is
environment-only or reproducible in maintained paths, and implement the
minimum safe mitigation if needed.

## Scope

Included:
- Build reproducible diagnostics for fresh-vs-reused connection behavior in
  sync and streaming flows.
- Add structured provider diagnostics for keep-alive/stale-connection failures.
- Gate and implement a minimal mitigation path if first-party reproducibility
  is confirmed.

Deferred:
- Broad provider transport redesign.
- Automatic endpoint health routing across backends.

Excluded:
- New provider feature work unrelated to connection lifecycle stability.
- Changes to model prompting/response parsing logic outside keep-alive handling.

## Design Decisions and Rationale

1. Evidence-first: reproduce and classify before changing transport behavior.
2. Keep mitigation minimal and fail-safe (fresh-client retry on known stale
   connection signatures).
3. Preserve current retry semantics and user-visible error framing unless a
   bug fix requires explicit change.

## Implementation Details

Primary files to change:
- [base.py](/home/inc/repos/NEXUS3/nexus3/provider/base.py)
- [schema.py](/home/inc/repos/NEXUS3/nexus3/config/schema.py)
- [test_lifecycle.py](/home/inc/repos/NEXUS3/tests/unit/provider/test_lifecycle.py)
- New: `tests/unit/provider/test_keepalive_recovery.py`
- [diagnose-empty-stream.sh](/home/inc/repos/NEXUS3/scripts/diagnose-empty-stream.sh)
- [PROVIDER-BUGFIX-PLAN.md](/home/inc/repos/NEXUS3/docs/plans/PROVIDER-BUGFIX-PLAN.md)

Planned slices:
1. Add a dedicated keep-alive diagnostic harness extension (or paired script)
   that records request mode, timing, and failure signatures across reuse/fresh
   paths.
2. Add provider-level diagnostics for likely stale-connection failures
   (`httpx.RemoteProtocolError`, mid-stream read failures, unexpected EOF-like
   failures) with request-attempt context.
3. If reproducible in maintained environments, add bounded stale-connection
   recovery:
   - close cached client
   - retry once with a fresh client
   - preserve existing global retry bounds
4. Add optional config guard for operational control if mitigation changes are
   needed in sensitive environments (for example, explicit keep-alive disable
   fallback).

## Testing Strategy

- Unit-test stale-connection recovery paths with mocked `httpx.AsyncClient`
  failures on reused connections and success on fresh reconnect.
- Verify no regression in existing lifecycle/retry behavior.
- Focused checks:
  - `.venv/bin/pytest -q tests/unit/provider/test_keepalive_recovery.py tests/unit/provider/test_lifecycle.py tests/unit/provider/test_retry_zero.py tests/unit/provider/test_empty_stream.py`
  - `.venv/bin/ruff check nexus3/provider/base.py nexus3/config/schema.py tests/unit/provider/test_keepalive_recovery.py`
  - `.venv/bin/mypy nexus3/provider/base.py nexus3/config/schema.py`
- Manual validation: rerun keep-alive diagnostics against at least one
  problematic endpoint and one known-good endpoint, then capture logs in
  `err/diagnose-*`.

## Implementation Checklist

- [ ] Add reproducible keep-alive diagnostic harness and artifact format.
- [ ] Add provider diagnostic classification for stale/reused-connection
      failures.
- [ ] Decide mitigation branch from evidence (no-change vs fresh-client retry).
- [ ] Implement and test bounded stale-connection mitigation if required.
- [ ] Update provider bugfix/deferred docs with final decision and rollout
      guidance.

## Documentation Updates

- Update [PROVIDER-BUGFIX-PLAN.md](/home/inc/repos/NEXUS3/docs/plans/PROVIDER-BUGFIX-PLAN.md)
  to remove or close the keep-alive defer note.
- Update `AGENTS_NEXUS3CONFIGOPS.md` and `CLAUDE.md` deferred tracker entries
  for HTTP keep-alive.
- Add operator-facing troubleshooting notes to `nexus3/provider/README.md` if
  mitigation toggles are introduced.

## Related Documents

- [PROVIDER-BUGFIX-PLAN.md](/home/inc/repos/NEXUS3/docs/plans/PROVIDER-BUGFIX-PLAN.md)
- [ARCH-MILESTONE-SCHEDULE-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
