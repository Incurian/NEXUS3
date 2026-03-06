# Post-M4 Manual Closeout Handoff: `post-m4-20260306-live1e`

Completion status (2026-03-06): complete

1. Run the Windows guide on a real Windows host and update:
   `windows/metadata.json`, `windows/checklist.md`, `windows/summary.json`,
   and `windows/notes.md`.
   Reference: `docs/testing/WINDOWS-LIVE-TESTING-GUIDE.md`
2. Run live multi-emulator carriage-return verification and replace the
   TODO marker in `terminal/summary.md` with a real `PASS`/`FAIL` result.
   Mirror the final closure marker into
   `docs\validation\post-m4-20260306-live1d\terminal\summary.md`
   because the closeout gate reads that terminal run id.
3. Update tracker statuses in
   `docs/plans/POST-M4-VALIDATION-FOLLOWUP-TRACKER-2026-03-06.md` after
   linking evidence for terminal and Windows follow-ups.
4. Run the closeout gate with explicit run ids:

```bash
.venv/bin/python scripts/validation/post_m4_closeout_gate.py           --artifact-root docs\validation           --soak-run-id post-m4-20260306-live1b           --race-run-id post-m4-20260306-live1c           --terminal-run-id post-m4-20260306-live1d           --windows-run-id post-m4-20260306-live1e           --json-out docs\validation\post-m4-20260306-live1e\closeout-gate.json
```
