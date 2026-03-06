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
- This run was executed in the current Linux/WSL environment only; multi-emulator verification is still open.
- Baseline Windows-native validation remains open in `post-m4-20260306-live1b/windows/summary.json` (`status=pending_real_host`).

## Reproduction Command
```bash
.venv/bin/python scripts/validation/terminal_payload_matrix.py --artifact-root docs/validation --run-id post-m4-20260306-live1d
```
