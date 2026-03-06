# Plan Follow-On: Post-M4 Validation Campaign (2026-03-05)

## Overview

Close the remaining environment-dependent validation debt after the
architecture waves by running a structured campaign for soak/performance,
Windows-native behavior, high-concurrency TOCTOU/lifecycle races, and real
terminal red-team verification.

## Scope

Included:
- Plan and execute all deferred post-M4 validation tracks with explicit
  pass/fail gates.
- Standardize artifacts and reporting for each validation run.
- Feed validated findings back into the remediation backlog with ownership.

Deferred:
- Third-party external pentest engagements.
- Broad performance optimization work not tied to validation failures.

Excluded:
- New feature implementation unrelated to validation findings.
- Rewriting architecture plans that are already accepted and in-flight.

## Design Decisions and Rationale

1. Treat validation campaign as execution work with owned deliverables, not
   ad hoc testing.
2. Keep one result schema across all tracks so failures are comparable and
   triageable.
3. Require reproducibility artifacts before declaring any deferred risk closed.

## Implementation Details

Primary files to change:
- [ARCH-MILESTONE-SCHEDULE-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
- `docs/testing/POST-M4-VALIDATION-RUNBOOK.md`
- `docs/validation/README.md`
- `scripts/validation/soak_workload.py`
- `scripts/validation/race_harness.py`
- `scripts/validation/terminal_payload_matrix.py`
- [WINDOWS-LIVE-TESTING-GUIDE.md](/home/inc/repos/NEXUS3/docs/testing/WINDOWS-LIVE-TESTING-GUIDE.md)

Campaign tracks:
1. Soak/performance track:
   - sustained create/send/cancel/destroy/compact workloads
   - memory/latency/error-rate trend capture over long duration.
2. Windows-native track:
   - run manual+scripted validation on real Windows hosts
   - cover junction/reparse behavior, process termination, console behavior.
3. TOCTOU/lifecycle race track:
   - high-concurrency multi-process races for restore/destroy/send and related
     lifecycle boundaries.
4. Terminal red-team track:
   - validate ANSI/OSC/CSI/CR payload handling across emulator matrix
   - confirm SafeSink boundary assumptions under real terminals.

Artifact contract:
- Each run writes metadata + command transcript + summary verdict under
  `docs/validation/<run-id>/`.
- Failures must include reproduction command, environment details, and mapped
  owner target.

## Execution Status

- 2026-03-06: Phase 1/2 bootstrap completed.
- Added canonical runbook:
  [POST-M4-VALIDATION-RUNBOOK.md](/home/inc/repos/NEXUS3/docs/testing/POST-M4-VALIDATION-RUNBOOK.md)
- Added validation artifact contract/index:
  [docs/validation/README.md](/home/inc/repos/NEXUS3/docs/validation/README.md)
- Added campaign harness scripts:
  - `scripts/validation/soak_workload.py`
  - `scripts/validation/race_harness.py`
  - `scripts/validation/terminal_payload_matrix.py`
- Updated Windows track guide with runbook/artifact cross-reference.
- Validation snapshot (2026-03-06, bootstrap):
  - `.venv/bin/ruff check scripts/validation docs/testing/POST-M4-VALIDATION-RUNBOOK.md docs/validation/README.md` passed.
  - `.venv/bin/mypy scripts/validation` passed.
  - `.venv/bin/python scripts/validation/soak_workload.py --dry-run --iterations 2 --artifact-root /tmp/nexus3-validation --run-id postm4-dryrun-20260306z10` passed.
  - `.venv/bin/python scripts/validation/race_harness.py --dry-run --workers 2 --rounds 2 --shared-agent-pool-size 2 --artifact-root /tmp/nexus3-validation --run-id postm4-dryrun-20260306z10` passed.
  - `.venv/bin/python scripts/validation/terminal_payload_matrix.py --artifact-root /tmp/nexus3-validation --run-id postm4-dryrun-20260306z10` passed.
- 2026-03-06: First live execution slice completed (`post-m4-20260306-live1b`).
- Preflight gates passed:
  - `.venv/bin/ruff check nexus3/`
  - `.venv/bin/mypy nexus3/`
  - `.venv/bin/pytest tests/unit -q` (`3112 passed`, `1 skipped`)
  - `.venv/bin/pytest tests/security -q` (`779 passed`)
- Live track outcomes:
  - soak: pass (`docs/validation/post-m4-20260306-live1b/soak/verdict.json`)
  - race: fail on failure-rate threshold, `security_failures=0`
    (`docs/validation/post-m4-20260306-live1b/race/verdict.json`)
  - terminal: pass with manual emulator follow-up warning
    (`docs/validation/post-m4-20260306-live1b/terminal/verdict.json`)
- Findings + follow-up placeholders recorded:
  - `docs/validation/post-m4-20260306-live1b/findings.md`
  - `docs/validation/post-m4-20260306-live1b/issue-links.md`
  - `docs/validation/post-m4-20260306-live1b/windows/` (pending real-host)
- Note:
  - Initial sandboxed harness run (`post-m4-20260306-live1`) produced
    false "No NEXUS3 server running" negatives due nested subprocess sandbox
    limits; soak/race live runs were re-executed unsandboxed.
- 2026-03-06: Race follow-up run completed (`post-m4-20260306-live1c`).
- Race harness updated with contention-aware gating option:
  `--exclude-expected-contention-errors`.
- Follow-up race result:
  - pass (`docs/validation/post-m4-20260306-live1c/race/verdict.json`)
  - `security_failures=0`
  - raw contention churn remains visible in summary artifacts
    (`expected_contention_failures=31`)
- 2026-03-06: Terminal follow-up refresh run completed
  (`post-m4-20260306-live1d`).
- Follow-up terminal result:
  - pass (`docs/validation/post-m4-20260306-live1d/terminal/verdict.json`)
  - `strict_failures=0`
  - `manual_follow_up_cases=1` (`carriage-return`)
- Open campaign gates after `live1d`:
  - Windows-native real-host validation still pending.
  - Live multi-emulator carriage-return verification still pending.
- 2026-03-06: canonical follow-up mapping established:
  - added
    [POST-M4-VALIDATION-FOLLOWUP-TRACKER-2026-03-06.md](/home/inc/repos/NEXUS3/docs/plans/POST-M4-VALIDATION-FOLLOWUP-TRACKER-2026-03-06.md)
  - replaced `TBD-*` placeholders in `live1b`/`live1c`/`live1d` issue-link docs.
  - updated `live1b` findings with explicit owner roles + target windows.

## Testing Strategy

- Gate each track with explicit thresholds:
  - soak: no crash/data-loss regressions; bounded error rate and stable memory
    trend.
  - windows: all required checklists pass on at least one supported Windows
    host environment.
  - race: no authorization/state-integrity failures under stress matrix.
  - terminal: no successful control-sequence spoofing in supported emulator set.
- Use existing unit/security suites as preflight before live campaign runs:
  - `.venv/bin/pytest tests/unit -q`
  - `.venv/bin/pytest tests/security -q`
  - `.venv/bin/ruff check nexus3/`
  - `.venv/bin/mypy nexus3/`

## Implementation Checklist

- [x] Create runbook + artifact format for post-M4 validation tracks.
- [x] Implement or wire campaign scripts for soak/race/terminal tracks.
- [x] Execute soak/perf campaign and archive artifacts.
- [ ] Execute Windows-native campaign on real Windows host(s) and archive
      artifacts.
- [x] Execute high-concurrency TOCTOU/lifecycle race campaign and archive
      artifacts.
- [x] Execute terminal red-team matrix and archive artifacts.
- [x] Convert findings into issues/plan updates with owners and target windows.
- [ ] Mark milestone deferred-validation items closed with evidence links.

## Documentation Updates

- Update deferred validation section in
  [ARCH-MILESTONE-SCHEDULE-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
  with completion evidence links.
- Update `docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md`
  deferred-work section once all tracks close.
- Update `AGENTS.md` running status with campaign state and next gate.

## Related Documents

- [ARCH-MILESTONE-SCHEDULE-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
- [CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
