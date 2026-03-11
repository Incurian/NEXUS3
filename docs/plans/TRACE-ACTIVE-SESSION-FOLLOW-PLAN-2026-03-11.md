# Trace Active Session Follow Plan (2026-03-11)

## Overview

Teach `nexus3 trace` to follow the currently active REPL session by default
when it is looking at the same log root as the running REPL/server.

Today the trace viewer resolves one session directory at startup and stays
pinned there until exit. That is fine for explicit historical inspection, but
it is a poor default for the “second terminal alongside the REPL” workflow.
The user wants the trace window to keep following whichever agent/session is
currently active in the REPL, while still allowing explicit pinning when a
specific session target is provided.

## Scope

Included:

- add an explicit active-session pointer file in the shared log root
- update the REPL to publish the currently displayed session to that pointer
- make `nexus3 trace` follow that pointer by default when no explicit target
  is provided
- keep explicit `TARGET` behavior pinned to the requested session
- apply the same follow-active behavior to both `execution` and `debug`
  trace presets
- emit a visible notice when the trace viewer retargets to a different active
  session

Deferred:

- auto-spawning a trace window from the REPL
- following the “active agent” across different log roots or different hosts
- richer multi-server disambiguation than “last writer wins”
- stale-pointer liveness detection beyond graceful clear-on-exit

Excluded:

- changing persisted tool-record lookup commands (`/tools`, `/tool`)
- changing the main REPL message/tool layout in this plan
- changing default trace presets or adding new presets

## Design Decisions And Rationale

### 1. Same log root is the real boundary

The trace viewer should follow the active REPL session when it is looking at
the same log root, not merely when the shell cwd happens to match.

Rationale:

- the server may use a custom `--log-dir`
- cwd alone is not a reliable cross-terminal coordination signal
- the trace viewer only has durable visibility into the log tree

### 2. Use an explicit active-session pointer file

Add a small JSON file at:

- `<log_root>/.active-session.json`

It should contain at least:

- `session_id`
- `session_dir`
- `agent_id`
- `server_pid`
- `server_instance_id`
- `updated_at`

Rationale:

- makes active-session follow explicit and durable
- avoids guessing from latest-directory mtimes
- gives clean ownership for best-effort clear-on-exit

### 3. Default trace behavior follows active, explicit target stays pinned

Behavior:

- no explicit `TARGET`: follow active session when pointer exists, otherwise
  fall back to the newest session directory under the log root
- explicit `TARGET`: resolve and pin to that session; no auto-retargeting
- `--latest`: keep equivalent to the no-target behavior for now, but update
  help/docs so it is clear that “active when available, otherwise latest” is
  the actual behavior

Rationale:

- preserves the current “easy default” UX
- avoids surprising target retargeting when the user explicitly asked for a
  specific session

### 4. On retarget, print a notice and reset per-session cursors

When active-session follow detects a different session:

- print a dim session-switch notice
- show recent history from the new session
- reset the execution/debug follow cursor against the new session

Rationale:

- makes the retarget visible instead of silently changing context
- avoids mixing offsets or line positions across different session artifacts

### 5. REPL owns pointer updates

The REPL should update the active-session pointer:

- after initial session/logger selection on startup
- after agent switches
- after restore-and-switch flows
- after create-and-switch flows
- clear it on graceful shutdown only if the pointer still belongs to the same
  `server_instance_id`

Rationale:

- the REPL already knows which session is currently displayed to the user
- ownership checks prevent older processes from deleting a newer pointer

## Implementation Details

Primary files:

- `nexus3/session/trace.py`
  - add active-session pointer helpers and dataclass
- `nexus3/cli/repl.py`
  - write/update/clear the active-session pointer from the REPL lifecycle
- `nexus3/cli/trace.py`
  - resolve default trace binding from active pointer or newest session
  - retarget follow loops when the active pointer changes
- `nexus3/cli/arg_parser.py`
  - update `trace` help text to match the new semantics

Likely docs:

- `README.md`
- `nexus3/cli/README.md`
- `nexus3/session/README.md`
- `CLAUDE.md`
- `AGENTS.md`
- `docs/plans/README.md`

Implementation notes:

- store absolute `session_dir` paths in the pointer file
- validate that the pointed session lives under the selected log root and has
  a `session.db`
- treat malformed/missing pointer files as “no active pointer” and fall back
  cleanly
- keep “last writer wins” semantics if multiple REPL/server processes share
  the same log root

## Testing Strategy

Add/extend tests for:

- active-session pointer read/write/clear behavior
- trace default resolution preferring active pointer over plain newest-session
  fallback
- explicit target remaining pinned
- session-switch notice / retarget helpers where practical

Validation should include:

- focused `ruff`
- focused `mypy`
- focused pytest for session-trace helpers and CLI trace logic
- practical smoke check with a temporary log root and active-pointer switch

## Documentation Updates

When implemented:

- document that `nexus3 trace` follows the active session by default when the
  selected log root contains an active-session pointer
- document the fallback to newest session when no active pointer exists
- document that explicit `TARGET` remains pinned

## Validation

Completed validation for the implemented slice:

- `.venv/bin/ruff check nexus3/session/trace.py nexus3/cli/trace.py nexus3/cli/repl.py nexus3/cli/arg_parser.py tests/unit/session/test_trace.py tests/unit/cli/test_trace.py`
- `.venv/bin/mypy nexus3/session/trace.py nexus3/cli/trace.py nexus3/cli/repl.py nexus3/cli/arg_parser.py`
- `.venv/bin/pytest -q tests/unit/session/test_trace.py tests/unit/cli/test_trace.py`
  - `18 passed`
- practical smoke with a temporary log root:
  - started `nexus3 trace --log-dir /tmp/nexus3-trace-follow --preset debug --history 1 --poll-interval 0.1`
  - trace initially followed `/tmp/nexus3-trace-follow/agent-a/2026-03-11_agent_a`
  - after publishing a new active-session pointer for `agent-b`, the viewer printed a switch notice and retargeted to `/tmp/nexus3-trace-follow/agent-b/2026-03-11_agent_b`

## Checklist

- [x] Add and index this plan.
- [x] Implement active-session pointer helpers.
- [x] Update the REPL lifecycle to publish the active session.
- [x] Update the trace viewer to follow the active session by default.
- [x] Add focused tests for pointer handling and trace resolution.
- [x] Sync docs and running status.
- [x] Run focused validation and a practical smoke check.
