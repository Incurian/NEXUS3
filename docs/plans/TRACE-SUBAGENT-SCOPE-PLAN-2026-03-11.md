# Trace Subagent Scope Plan (2026-03-11)

## Overview

Add a trace scope that follows the active non-REPL child agents spawned by the
currently active REPL agent.

The current trace viewer can follow:

- the active REPL session by default
- an explicit pinned session target

That is good for watching the foreground conversation, but it does not yet
provide a clean way to monitor what delegated agents are doing in parallel.
The user wants a second-terminal trace mode that shows only the active
subagents belonging to the currently active REPL agent.

## Scope

Included:

- add `trace --scope subagents`
- keep the existing default scope as the active REPL session
- maintain a shared active-agent session registry in the selected log root
- update pool create/restore/destroy paths to keep that registry current
- make subagent scope follow only agents whose `parent_agent_id` matches the
  current active REPL agent
- multiplex execution and debug trace output across those subagent sessions
  with clear per-agent labeling

Deferred:

- broader `background` or `all` trace scopes
- richer per-subagent filtering
- auto-spawned trace windows from the REPL
- historical replay of subagent activity after the registry no longer lists
  them as active

Excluded:

- changing the default active-session trace behavior
- changing `/tool` or `/tools`
- adding fuzzy session/agent search to trace targeting

## Design Decisions And Rationale

### 1. Add a scope selector, not a new preset

Use:

- `--scope active` (default)
- `--scope subagents`

Rationale:

- `preset` already means “how to render”
- this feature changes “which sessions to follow”
- keeping those dimensions separate scales better if more trace scopes are
  added later

### 2. Use a live active-agent registry in the log root

Add a shared JSON file in the selected log root that records active agent
sessions:

- `agent_id`
- `session_id`
- `session_dir`
- `parent_agent_id`
- `server_pid`
- `updated_at`

The pool should update this registry on:

- create
- restore
- destroy

Rationale:

- agent subagents are real pool agents with their own top-level log
  directories, not nested `create_child_logger()` sessions
- the pool is the authoritative place that knows live `agent_id`,
  `parent_agent_id`, and session-dir mappings

### 3. Subagent scope keys off the active REPL agent

For `--scope subagents` without an explicit target:

- read the current active REPL session pointer
- use its `agent_id` and `server_pid`
- follow active-agent registry entries where:
  - `parent_agent_id == active_agent_id`
  - `server_pid == active_server_pid`

Rationale:

- this matches the user’s desired “only the active but non-REPL sessions”
  behavior
- filtering by `server_pid` avoids mixing stale or unrelated agent entries from
  another process sharing the same log root

### 4. Store agent identity metadata in session DBs

When pool agents are created/restored, write:

- `agent_id`
- `parent_agent_id` (if any)

into session metadata.

Rationale:

- gives the trace viewer a clean way to identify pinned parent sessions
- avoids fragile inference from directory names

### 5. Multiplexed subagent trace must label every entry

Subagent scope should prefix execution/debug output with agent identity so the
user can tell which child produced which line.

Rationale:

- multiple subagents may be active at once
- unlabeled multiplexed output becomes unreadable quickly

## Implementation Details

Primary files:

- `nexus3/session/trace.py`
  - add active-agent session registry helpers
  - add session metadata helpers for `agent_id` / `parent_agent_id`
- `nexus3/rpc/pool.py`
  - register active agent sessions on create
  - persist session metadata for created agents
- `nexus3/rpc/pool_restore.py`
  - register active agent sessions on restore
  - persist session metadata for restored agents
- `nexus3/rpc/pool_lifecycle.py`
  - unregister active agent sessions on destroy
- `nexus3/cli/arg_parser.py`
  - add `trace --scope`
- `nexus3/cli/trace.py`
  - implement multiplexed subagent execution/debug follow behavior

Likely docs:

- `README.md`
- `nexus3/cli/README.md`
- `nexus3/defaults/NEXUS-DEFAULT.md`
- `nexus3/session/README.md`
- `CLAUDE.md`
- `AGENTS.md`
- `docs/plans/README.md`

## Testing Strategy

Add/extend tests for:

- active-agent session registry read/write/remove helpers
- session metadata helper behavior
- trace argument parsing for `--scope`
- subagent scope filtering by `parent_agent_id` and `server_pid`
- multiplexed trace helper behavior where practical

Validation should include:

- focused `ruff`
- focused `mypy`
- focused pytest for session-trace and CLI trace helpers
- practical smoke check with a temporary log root containing:
  - one active parent session pointer
  - multiple active child-agent registry entries
  - multiplexed debug or execution output

## Documentation Updates

When implemented:

- document `trace --scope subagents`
- explain that it follows active child agents of the current REPL agent
- document that the default scope remains the active REPL session

## Validation

Completed validation for the implemented slice:

- `.venv/bin/ruff check nexus3/session/trace.py nexus3/cli/trace.py nexus3/cli/arg_parser.py nexus3/cli/repl.py nexus3/rpc/pool.py nexus3/rpc/pool_lifecycle.py nexus3/rpc/pool_restore.py tests/unit/session/test_trace.py tests/unit/cli/test_trace.py tests/security/test_concurrent_restore.py tests/unit/test_pool.py tests/unit/test_auto_restore.py README.md nexus3/cli/README.md nexus3/defaults/NEXUS-DEFAULT.md nexus3/session/README.md CLAUDE.md AGENTS.md docs/plans/README.md docs/plans/TRACE-SUBAGENT-SCOPE-PLAN-2026-03-11.md`
- `.venv/bin/mypy nexus3/session/trace.py nexus3/cli/trace.py nexus3/cli/arg_parser.py nexus3/cli/repl.py nexus3/rpc/pool.py nexus3/rpc/pool_lifecycle.py nexus3/rpc/pool_restore.py`
- `.venv/bin/pytest -q tests/security/test_concurrent_restore.py tests/unit/test_pool.py tests/unit/test_auto_restore.py tests/unit/session/test_trace.py tests/unit/cli/test_trace.py`
  - `120 passed`
- `git diff --check`
- practical smoke with a temporary log root:
  - `/home/inc/repos/NEXUS3/.venv/bin/python -m nexus3 trace --log-dir /tmp/nexus3-trace-subagents-smoke --scope subagents --once --history 4`
  - trace attached only `worker-a` and `worker-b` under active parent
    `parent-agent`, prefixed output with `[worker-*]`, and ignored the
    unrelated `worker-other` session

## Checklist

- [x] Add and index this plan.
- [x] Add active-agent session registry helpers.
- [x] Update pool create/restore/destroy paths to keep the registry current.
- [x] Add `trace --scope` and implement subagent-scope follow logic.
- [x] Add focused tests.
- [x] Sync docs and running status.
- [x] Run focused validation and a practical smoke check.
