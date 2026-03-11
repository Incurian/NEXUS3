# Process Tool Split Plan (2026-03-11)

## Overview

This follow-up plan replaces the overloaded `processes(action=...)` tool with
two explicit read-only tools:

- `list_processes`
- `get_process`

The goal is to reduce model misuse around mixed list/get parameters, especially
the tendency to invent optional fields like `port=0` or attach exact-PID fields
to discovery requests where they do not belong.

This plan keeps `kill_process` as the explicit destructive companion tool.

## Scope

Included:

- replace `processes` with explicit `list_processes` and `get_process`
- keep `kill_process` unchanged except for any required doc/wiring alignment
- normalize `port=0` to omitted for the read-only process tools
- keep `pid` strict (`pid <= 0` remains invalid)
- make `list_processes` discovery-only by removing its unnecessary `pid` field
- update permission/preset wiring, tests, docs, and live validation notes

Deferred:

- fuzzy matching beyond exact / contains / regex
- any broader process-tool schema redesign beyond the list/get split
- changing `kill_process` semantics beyond doc alignment

Excluded:

- backward-compat aliases for `processes`
- kill-by-query or kill-by-port behavior

## Design Decisions And Rationale

### 1. Split read-only discovery from detailed lookup

Canonical tools:

- `list_processes(...)`
- `get_process(...)`
- `kill_process(...)`

Rationale:

- the model no longer has to pick an `action`
- schemas become smaller and less confusable
- `get_process` can require either `pid` or `query` without carrying list-only
  pagination fields

### 2. `port=0` is placeholder-normalized only for read-only process tools

Behavior:

- `list_processes(port=0)` behaves as if `port` were omitted
- `get_process(port=0)` behaves as if `port` were omitted
- negative ports still fail closed

Rationale:

- `0` is not a meaningful local-port filter here
- live validation showed the model tends to invent `port=0` as a bogus default
- this is a narrow defensive normalization, not a general rule for numeric
  fields

### 3. `pid` remains strict

Behavior:

- `pid <= 0` remains invalid for `get_process` and `kill_process`
- `pid=0` is not treated as omitted, even if `query` is present

Rationale:

- PID is the strongest identity selector in this tool family
- overloading `0` to mean "unset" would make exact lookup semantics less clear

### 4. `list_processes` does not accept `pid`

Behavior:

- `list_processes` exposes discovery filters only
- exact PID lookup is handled solely by `get_process`

Rationale:

- `pid` is an identity selector, not a natural list filter
- keeping it on the list schema encouraged bogus `pid=0` model calls
- the backend does not need a separate exact-PID list path once `get_process`
  exists

## Proposed Tool Contracts

### `list_processes`

Parameters:

- `query?`: string
- `match?`: `"exact" | "contains" | "regex"` (default `"contains"`)
- `user?`: string
- `port?`: integer (`0` normalized to omitted)
- `limit?`: integer (default `50`)
- `offset?`: integer (default `0`)

Output:

- paginated process summaries
- `count`, `total`, `offset`, `limit`, `truncated`, `next_offset`, `items`

### `get_process`

Parameters:

- `pid?`: integer
- `query?`: string
- `match?`: `"exact" | "contains" | "regex"` (default `"contains"`)
- `user?`: string
- `port?`: integer (`0` normalized to omitted)

Behavior:

- if `pid` is provided, inspect that exact process
- otherwise require `query`
- query-based lookup must resolve to exactly one process or fail closed

### `kill_process`

No contract change in this plan.

## Implementation Details

Primary files:

- `nexus3/skill/builtin/processes.py` or replacement split files
- `nexus3/skill/builtin/registration.py`
- `nexus3/core/process_tools.py`
- `nexus3/core/policy.py`
- `nexus3/core/presets.py`

Supporting files:

- docs and prompt references
- focused process-tool tests
- confirmation/permission docs where tool names are listed

## Testing Strategy

Focused unit coverage:

- `list_processes` pagination and filters
- `get_process` PID and query resolution
- `port=0` normalization
- `list_processes` schema no longer exposes `pid`
- `pid <= 0` rejection remains intact for `get_process` / `kill_process`
- registration and sandboxed preset wiring updates

Validation:

- focused `ruff`
- focused `mypy` on process-tool modules
- focused pytest slice for process tools and touched permission/UI docs/tests
- a small live check or direct runtime harness confirming the split tools work

## Documentation Updates

- replace `processes` references in current-facing docs with
  `list_processes` / `get_process`
- keep `kill_process` guidance adjacent
- explicitly note built-in process-tool preference over shell equivalents

## Checklist

- [x] Add plan/index/status tracking for the split.
- [x] Replace `processes` with `list_processes` and `get_process`.
- [x] Add `port=0` normalization for the read-only process tools.
- [x] Remove `pid` from `list_processes`.
- [x] Update permission and registration wiring.
- [x] Update focused tests.
- [x] Sync docs/status.
- [x] Run focused validation and a live/runtime behavior check.

Validation completed:

- `.venv/bin/ruff check nexus3/skill/builtin/processes.py nexus3/skill/builtin/registration.py nexus3/core/policy.py nexus3/core/presets.py tests/unit/skill/test_process_tools.py tests/unit/test_permission_presets.py README.md nexus3/defaults/NEXUS-DEFAULT.md CLAUDE.md AGENTS_NEXUS3SKILLSCAT.md nexus3/skill/README.md AGENTS.md docs/plans/PROCESS-TOOL-SPLIT-PLAN-2026-03-11.md docs/reviews/DEPENDENCY-LICENSE-AND-TELEMETRY-AUDIT-2026-03-10.md`
- `.venv/bin/mypy nexus3/skill/builtin/processes.py`
- `.venv/bin/pytest -q tests/unit/skill/test_process_tools.py tests/unit/test_permission_presets.py tests/unit/cli/test_confirmation_ui_safe_sink.py tests/unit/test_permissions.py` (`208 passed`)
- live validation:
  - trusted RPC agent described `list_processes` without a `pid` parameter and
    `get_process` with explicit PID support
  - trusted RPC agent successfully executed
    `list_processes(query='python', match='contains', limit=1)` and returned a
    real first result without inventing `pid`
