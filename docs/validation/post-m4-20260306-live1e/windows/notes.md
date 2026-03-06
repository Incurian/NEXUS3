# Windows Track Notes: post-m4-20260306-live1e

- Real-host execution completed on `INC-TR` (Windows `10.0.19045`) with
  Python `3.13.5`.
- Windows-required sections are all passing. Raw evidence is recorded in:
  - `docs/validation/post-m4-20260306-live1e/windows/live-check-output.json`
  - `docs/validation/post-m4-20260306-live1e/windows/summary.json`
- Cross-shell carriage-return follow-up evidence is recorded in:
  - `docs/validation/post-m4-20260306-live1e/terminal/multi-shell-carriage-return-evidence.json`
- Environment caveat:
  - In this Codex environment, subprocess checks initially failed in sandbox
    mode (`WinError 5`) and were rerun unsandboxed to capture real-host results.
