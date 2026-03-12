# REPL RPC Idle Activity Plan (2026-03-12)

## Overview

Keep the embedded RPC server alive while the unified REPL is actively in use.

Today the embedded HTTP server only resets its idle timer on incoming HTTP/RPC
connections. Direct REPL turns call `Session` in-process, so a long period of
active REPL use can still let the RPC server idle out even though the terminal
is busy.

This slice adds a shared activity tracker so direct REPL activity also resets
the embedded server idle timer.

## Scope

Included:

- add a shared embedded-server activity tracker in the HTTP server layer
- treat direct REPL activity as embedded-server activity
- touch that tracker on:
  - REPL input
  - direct streamed content
  - reasoning/tool lifecycle callbacks
- add focused unit coverage for the shared tracker
- update current-facing docs and running status

Deferred:

- auto-restarting the embedded HTTP server after idle shutdown
- reconnect/retry behavior for long-lived external clients that cache tokens

Excluded:

- changes to external RPC client auto-discovery behavior
- changes to in-process `nexus_send` / pool agent routing

## Design Decisions And Rationale

### 1. Shared tracker instead of REPL-specific timeout logic

Behavior:

- `run_http_server(...)` accepts a shared activity tracker
- HTTP connections and direct REPL activity both touch the same tracker

Rationale:

- keeps idle policy centralized in the server layer
- avoids duplicating timeout arithmetic in the REPL

### 2. Any live REPL activity counts

Behavior:

- ordinary REPL input, streamed content, reasoning, and tool execution all
  refresh the timer

Rationale:

- from the user’s perspective, active REPL use means the embedded server is
  still “in use”
- this also prevents idle shutdown during long tool-heavy turns that do not
  involve HTTP traffic

### 3. No token-migration machinery in this slice

Behavior:

- in-process agents remain unaffected because they do not use the HTTP token
- external clients that construct a fresh `NexusClient.with_auto_auth()` or
  `nexus3 rpc ...` call will discover the current token file each time
- long-lived external clients that cache an old token remain a separate
  reconnect problem

Rationale:

- token-rotation handling only matters if/when the server is actually restarted
- this slice reduces unwanted idle shutdowns without widening into restart
  orchestration

## Implementation Details

Primary files:

- `nexus3/rpc/http.py`
- `nexus3/cli/repl.py`
- `tests/unit/test_http_pipeline_layers.py`

Supporting docs:

- `README.md`
- `nexus3/cli/README.md`
- `nexus3/rpc/README.md`
- `CLAUDE.md`
- `AGENTS.md`
- `docs/plans/README.md`

## Testing Strategy

Focused coverage should confirm:

- the activity tracker updates and reports idle duration correctly
- focused lint/type/test passes for the touched REPL/RPC files

## Documentation Updates

- add and index the plan doc
- update idle-timeout wording so it reflects REPL activity as well as RPC
- record the active slice in running status

## Checklist

- [x] Add and index the plan doc.
- [x] Add shared embedded-server activity tracking and wire REPL activity into it.
- [x] Add focused regression coverage.
- [x] Sync docs and running-status notes.
- [x] Run focused validation.

Validation completed:

- `.venv/bin/pytest -q tests/unit/test_http_pipeline_layers.py tests/unit/cli/test_repl_safe_sink.py` (`60 passed`)
- `.venv/bin/ruff check nexus3/rpc/http.py nexus3/cli/repl.py tests/unit/test_http_pipeline_layers.py README.md nexus3/cli/README.md nexus3/rpc/README.md CLAUDE.md AGENTS.md docs/plans/README.md docs/plans/REPL-RPC-IDLE-ACTIVITY-PLAN-2026-03-12.md`
- `.venv/bin/mypy nexus3/rpc/http.py nexus3/cli/repl.py`
- `git diff --check`
