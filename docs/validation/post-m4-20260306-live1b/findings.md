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
   - Owner target:
     - Validation/Runtime owner (TBD)
   - Follow-up window:
     - Immediate post-M4 campaign continuation (next execution slice)

2. Terminal carriage-return emulator follow-up required
   - Severity: low
   - Track: `terminal`
   - Evidence:
     - `terminal/verdict.json`: warning `carriage-return: contains carriage return; requires live emulator verification`
   - Interpretation:
     - Script-level sanitization checks pass, but real terminal emulator behavior still requires manual confirmation.
   - Owner target:
     - CLI/Display owner (TBD)
   - Follow-up window:
     - Immediate post-M4 campaign continuation

3. Windows-native campaign not yet executed
   - Severity: medium
   - Track: `windows`
   - Evidence:
     - `windows/summary.json`: `status=pending_real_host`
   - Interpretation:
     - This environment cannot close the Windows gate; required real-host run remains open.
   - Owner target:
     - Windows validation owner (TBD)
   - Follow-up window:
     - Next available Windows host validation slot
