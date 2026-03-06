# Post-M4 Validation Findings: post-m4-20260306-live1b

## Summary

- Soak track: PASS (`soak/verdict.json`)
- Race track: FAIL (`race/verdict.json`)
- Terminal track: PASS with manual follow-up warning (`terminal/verdict.json`)
- Windows-native track: PENDING real-host execution (`windows/summary.json`)

## Findings

1. Race failure-rate threshold breach (non-security)
   - Severity: medium
   - Track: `race`
   - Evidence:
     - `race/summary.json`: `failure_rate=0.13333333333333333`, `security_failures=0`
     - `race/verdict.json`: failed check `failure rate 13.333% exceeded threshold 2.000%`
   - Interpretation:
     - No authorization/state-integrity security signature failures were detected.
     - Failure pressure appears operational/lifecycle under concurrent churn and needs deeper triage.
   - Follow-up status:
     - `validation-closed` via `post-m4-20260306-live1c`
   - Owner target:
     - Validation/Runtime owner
   - Follow-up window:
     - 2026-03-06 follow-up slice (`post-m4-20260306-live1c`)
   - Tracker:
     - [POSTM4-FU-RACE-001](/home/inc/repos/NEXUS3/docs/plans/POST-M4-VALIDATION-FOLLOWUP-TRACKER-2026-03-06.md#postm4-fu-race-001)

2. Terminal carriage-return emulator follow-up required
   - Severity: low
   - Track: `terminal`
   - Evidence:
     - `terminal/verdict.json`: warning `carriage-return: contains carriage return; requires live emulator verification`
   - Interpretation:
     - Script-level sanitization checks pass, but real terminal emulator behavior still requires manual confirmation.
   - Follow-up status:
     - `open`
   - Owner target:
     - CLI/Display owner
   - Follow-up window:
     - Week of 2026-03-09 (next live multi-emulator validation slot)
   - Tracker:
     - [POSTM4-FU-TERM-001](/home/inc/repos/NEXUS3/docs/plans/POST-M4-VALIDATION-FOLLOWUP-TRACKER-2026-03-06.md#postm4-fu-term-001)

3. Windows-native campaign not yet executed
   - Severity: medium
   - Track: `windows`
   - Evidence:
     - `windows/summary.json`: `status=pending_real_host`
   - Interpretation:
     - This environment cannot close the Windows gate; required real-host run remains open.
   - Follow-up status:
     - `open`
   - Owner target:
     - Windows validation owner
   - Follow-up window:
     - Week of 2026-03-09 (first available real-host run slot)
   - Tracker:
     - [POSTM4-FU-WIN-001](/home/inc/repos/NEXUS3/docs/plans/POST-M4-VALIDATION-FOLLOWUP-TRACKER-2026-03-06.md#postm4-fu-win-001)
