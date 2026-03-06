# Terminal Manual Follow-Up: `post-m4-20260306-live1e`

## Scope
- Capture live multi-emulator carriage-return verification notes here.
- Automated baseline source run: `post-m4-20260306-live1d`.

## Live Multi-Emulator Verification (2026-03-06)
- Executed carriage-return probe
  (`docs/validation/post-m4-20260306-live1e/terminal/cr_probe.py`) in:
  - `cmd`
  - `powershell` (5.1)
  - `pwsh` (7.5.4)
  - `git bash` (5.2.15)
- Raw captured evidence:
  - `docs/validation/post-m4-20260306-live1e/terminal/multi-shell-carriage-return-evidence.json`
- Probe output retained carriage return bytes (`0d`) and overwrite token
  consistently across all tested shells.

## Manual Verification Closure
Multi-emulator verification: PASS
