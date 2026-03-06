# Soak Validation Summary: `post-m4-bootstrap-dryrun`

## Configuration
- iterations: 1
- port: 9000
- dry_run: True

## Metrics
- total commands: 4
- failures: 0 (0.000%)
- send p50 latency: 0.000s
- send p95 latency: 0.000s

## Verdict
- pass: True
- failed checks: 0

### Warnings
- dry-run mode enabled: commands were not executed

## Failure Excerpt
- none

## Reproduction Command
```bash
.venv/bin/python scripts/validation/soak_workload.py --port 9000 --iterations 1 --agent-prefix postm4-soak
```
