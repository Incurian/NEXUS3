# Terminal Validation Summary: `post-m4-20260306-live1d`

## Matrix Results
| Case | Result | Manual Follow-Up |
| --- | --- | --- |
| `ansi-color` | PASS | no |
| `osc-title` | PASS | no |
| `csi-clear` | PASS | no |
| `rich-markup` | PASS | no |
| `mixed-ansi-and-markup` | PASS | no |
| `control-bytes` | PASS | no |
| `carriage-return` | PASS | yes |

## Verdict
- pass: True
- strict failures: 0
- manual follow-up cases: 1

### Warnings
- carriage-return: contains carriage return; requires live emulator verification

## Manual Follow-Up (2026-03-06)
- `carriage-return` remains a manual-follow-up class even with strict checks passing.
- Multi-emulator verification completed on a real Windows host in
  `post-m4-20260306-live1e`:
  - `docs/validation/post-m4-20260306-live1e/terminal/summary.md`
  - `docs/validation/post-m4-20260306-live1e/terminal/multi-shell-carriage-return-evidence.json`
- Windows-native validation closeout also completed in:
  `docs/validation/post-m4-20260306-live1e/windows/summary.json` (`status=pass`).
- Multi-emulator verification: PASS

## Reproduction Command
```bash
.venv/bin/python scripts/validation/terminal_payload_matrix.py --artifact-root docs/validation --run-id post-m4-20260306-live1d
```
