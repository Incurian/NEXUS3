# Post-M4 Validation Follow-Up Tracker (2026-03-06)

This document is the canonical source for post-M4 follow-up mapping IDs across race, terminal, and Windows validation tracks.

## Status Legend

- `open`: follow-up evidence is still required to close the gate.
- `validation-closed`: required follow-up evidence is captured and accepted.

## Canonical Follow-Ups

### POSTM4-FU-RACE-001

- Track: `race`
- Scope: contention-aware failure-rate follow-up after the non-security threshold breach in `post-m4-20260306-live1b`.
- Owner role: Validation/Runtime owner
- Target window: 2026-03-06 follow-up slice (`post-m4-20260306-live1c`)
- Status: `validation-closed`
- Evidence:
  - [live1b race verdict](/home/inc/repos/NEXUS3/docs/validation/post-m4-20260306-live1b/race/verdict.json)
  - [live1b race summary](/home/inc/repos/NEXUS3/docs/validation/post-m4-20260306-live1b/race/summary.json)
  - [live1c race verdict](/home/inc/repos/NEXUS3/docs/validation/post-m4-20260306-live1c/race/verdict.json)
  - [live1c race summary](/home/inc/repos/NEXUS3/docs/validation/post-m4-20260306-live1c/race/summary.json)

### POSTM4-FU-TERM-001

- Track: `terminal`
- Scope: live multi-emulator carriage-return verification for terminal follow-up cases.
- Owner role: CLI/Display owner
- Target window: 2026-03-06 real-host closeout slice (`post-m4-20260306-live1e`)
- Status: `validation-closed`
- Evidence:
  - [live1b terminal verdict](/home/inc/repos/NEXUS3/docs/validation/post-m4-20260306-live1b/terminal/verdict.json)
  - [live1d terminal verdict](/home/inc/repos/NEXUS3/docs/validation/post-m4-20260306-live1d/terminal/verdict.json)
  - [live1d terminal summary](/home/inc/repos/NEXUS3/docs/validation/post-m4-20260306-live1d/terminal/summary.md)
  - [live1e terminal summary](/home/inc/repos/NEXUS3/docs/validation/post-m4-20260306-live1e/terminal/summary.md)
  - [live1e multi-shell carriage-return evidence](/home/inc/repos/NEXUS3/docs/validation/post-m4-20260306-live1e/terminal/multi-shell-carriage-return-evidence.json)

### POSTM4-FU-WIN-001

- Track: `windows`
- Scope: Windows-native validation campaign execution on a real host and artifact closeout.
- Owner role: Windows validation owner
- Target window: 2026-03-06 real-host closeout slice (`post-m4-20260306-live1e`)
- Status: `validation-closed`
- Evidence:
  - [live1b windows summary](/home/inc/repos/NEXUS3/docs/validation/post-m4-20260306-live1b/windows/summary.json)
  - [live1b windows checklist](/home/inc/repos/NEXUS3/docs/validation/post-m4-20260306-live1b/windows/checklist.md)
  - [Windows live testing guide](/home/inc/repos/NEXUS3/docs/testing/WINDOWS-LIVE-TESTING-GUIDE.md)
  - [live1e windows summary](/home/inc/repos/NEXUS3/docs/validation/post-m4-20260306-live1e/windows/summary.json)
  - [live1e windows checklist](/home/inc/repos/NEXUS3/docs/validation/post-m4-20260306-live1e/windows/checklist.md)
  - [live1e windows metadata](/home/inc/repos/NEXUS3/docs/validation/post-m4-20260306-live1e/windows/metadata.json)
