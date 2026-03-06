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
- [ ] Execute soak/perf campaign and archive artifacts.
- [ ] Execute Windows-native campaign on real Windows host(s) and archive
      artifacts.
- [ ] Execute high-concurrency TOCTOU/lifecycle race campaign and archive
      artifacts.
- [ ] Execute terminal red-team matrix and archive artifacts.
- [ ] Convert findings into issues/plan updates with owners and target windows.
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
