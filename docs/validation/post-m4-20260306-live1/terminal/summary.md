# Terminal Validation Summary: `post-m4-20260306-live1`

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

## Reproduction Command
```bash
.venv/bin/python scripts/validation/terminal_payload_matrix.py --output-root docs/validation
```
