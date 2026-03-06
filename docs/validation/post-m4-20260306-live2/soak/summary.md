# Soak Validation Summary: `post-m4-20260306-live2`

## Configuration
- iterations: 2
- port: 9000
- dry_run: False

## Metrics
- total commands: 8
- failures: 8 (100.000%)
- send p50 latency: 0.530s
- send p95 latency: 0.533s

## Verdict
- pass: False
- failed checks: 1

### Failed checks
- failure rate 100.000% exceeded threshold 1.000%

## Failure Excerpt
- `create` rc=1: /home/inc/repos/NEXUS3/nexus3/cli/client_commands.py:37: UserWarning: SSL CA cert file does not exist: '/etc/ssl/certs/corporate-ca.crt' -> /etc/ssl/certs/corporate-ca.crt
  config = load_config()
Error: No NEXUS3 server running on port 9000
Start a server with: nexus3
- `send` rc=1: /home/inc/repos/NEXUS3/nexus3/cli/client_commands.py:37: UserWarning: SSL CA cert file does not exist: '/etc/ssl/certs/corporate-ca.crt' -> /etc/ssl/certs/corporate-ca.crt
  config = load_config()
Error: No NEXUS3 server running on port 9000
- `compact` rc=1: /home/inc/repos/NEXUS3/nexus3/cli/client_commands.py:37: UserWarning: SSL CA cert file does not exist: '/etc/ssl/certs/corporate-ca.crt' -> /etc/ssl/certs/corporate-ca.crt
  config = load_config()
Error: No NEXUS3 server running on port 9000
- `destroy` rc=1: /home/inc/repos/NEXUS3/nexus3/cli/client_commands.py:37: UserWarning: SSL CA cert file does not exist: '/etc/ssl/certs/corporate-ca.crt' -> /etc/ssl/certs/corporate-ca.crt
  config = load_config()
Error: No NEXUS3 server running on port 9000
- `create` rc=1: /home/inc/repos/NEXUS3/nexus3/cli/client_commands.py:37: UserWarning: SSL CA cert file does not exist: '/etc/ssl/certs/corporate-ca.crt' -> /etc/ssl/certs/corporate-ca.crt
  config = load_config()
Error: No NEXUS3 server running on port 9000
Start a server with: nexus3
- `send` rc=1: /home/inc/repos/NEXUS3/nexus3/cli/client_commands.py:37: UserWarning: SSL CA cert file does not exist: '/etc/ssl/certs/corporate-ca.crt' -> /etc/ssl/certs/corporate-ca.crt
  config = load_config()
Error: No NEXUS3 server running on port 9000
- `compact` rc=1: /home/inc/repos/NEXUS3/nexus3/cli/client_commands.py:37: UserWarning: SSL CA cert file does not exist: '/etc/ssl/certs/corporate-ca.crt' -> /etc/ssl/certs/corporate-ca.crt
  config = load_config()
Error: No NEXUS3 server running on port 9000
- `destroy` rc=1: /home/inc/repos/NEXUS3/nexus3/cli/client_commands.py:37: UserWarning: SSL CA cert file does not exist: '/etc/ssl/certs/corporate-ca.crt' -> /etc/ssl/certs/corporate-ca.crt
  config = load_config()
Error: No NEXUS3 server running on port 9000

## Reproduction Command
```bash
.venv/bin/python scripts/validation/soak_workload.py --port 9000 --iterations 2 --agent-prefix postm4-soak
```
