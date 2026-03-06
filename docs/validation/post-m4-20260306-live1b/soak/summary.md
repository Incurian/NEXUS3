# Soak Validation Summary: `post-m4-20260306-live1b`

## Configuration
- iterations: 25
- port: 9000
- dry_run: False

## Metrics
- total commands: 100
- failures: 0 (0.000%)
- send p50 latency: 5.438s
- send p95 latency: 6.877s

## Verdict
- pass: True
- failed checks: 0

## Failure Excerpt
- none

## Reproduction Command
```bash
.venv/bin/python scripts/validation/soak_workload.py --port 9000 --iterations 25 --agent-prefix postm4-soak
```
