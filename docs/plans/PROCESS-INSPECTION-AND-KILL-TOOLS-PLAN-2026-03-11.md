# Process Inspection And Kill Tools Plan (2026-03-11)

## Overview

This plan adds a built-in cross-platform process inspection and termination
capability so agents do not need to fall back to shell commands like `ps`,
`tasklist`, `pgrep`, `kill`, or `taskkill`.

The design goal is "just works" behavior across Linux, macOS, and Windows
without requiring the agent to reason about the host OS or shell family.

Implementation note:

- the original combined `processes` design described in this plan was later
  refined by
  [PROCESS-TOOL-SPLIT-PLAN-2026-03-11.md](/home/inc/repos/NEXUS3/docs/plans/PROCESS-TOOL-SPLIT-PLAN-2026-03-11.md),
  which replaced it with `list_processes` and `get_process`, and removed
  `pid` from the list-tool contract.

The recommended surface is two tools:

- `processes`: read-only process discovery and inspection
- `kill_process`: explicit process termination by PID

## Scope

Included:

- add a read-only `processes` tool for list/find/get use cases
- add a destructive `kill_process` tool for PID-based termination
- make the process layer cross-platform and shell-independent
- add bounded result pagination (`limit`, `offset`, `next_offset`)
- redact obvious secrets from returned command lines
- add focused docs/tests/validation

Deferred:

- fuzzy matching beyond exact / contains / regex
- interactive process tree visualization
- exposing full environment blocks for processes
- advanced sort fields beyond stable default ordering
- deep per-platform enrichment beyond a sane common field set

Excluded:

- shell-based implementations (`ps`, `tasklist`, `wmic`, etc.) as the primary API
- killing by fuzzy match or regex
- "kill by port" shortcuts without first resolving the owning PID

## Design Decisions And Rationale

### 1. Use two tools, not one overloaded tool

Recommended tools:

- `processes(action=list|get, ...)`
- `kill_process(pid, tree?, force?, timeout_seconds?)`

Rationale:

- read-only inspection and destructive termination have different trust and
  confirmation expectations
- the UI/policy model stays simpler than a single multi-action tool

### 2. Cross-platform implementation should use a real process library

Preferred backend: `psutil`

Rationale:

- user expectation is that the tool abstracts away OS/shell differences
- `psutil` is purpose-built for cross-platform process/system inspection and
  local process management
- it is much less brittle than parsing OS-specific shell command output

Dependency note:

- `psutil` was checked at the official PyPI package page on 2026-03-11
- PyPI currently lists `psutil` as BSD-3-Clause and describes it as a
  cross-platform library for process/system monitoring
- no telemetry/phone-home behavior is suggested by its package purpose or
  official package metadata, but if adopted it should still be recorded in the
  project's dependency audit docs
- reminder from user: every new dependency added during this workstream must be
  audited for MIT compatibility and telemetry/privacy concerns before closeout

### 3. Listing/discovery can support flexible matching; termination cannot

`processes` should support:

- `pid`
- `query`
- `match=exact|contains|regex`
- `user?`
- `port?`

`kill_process` should require:

- explicit `pid`

Rationale:

- regex/contains are useful for discovery
- kill-by-match is too error-prone, especially with multiple similar processes

### 4. Pagination should be bounded and honest

`processes(action="list")` should support:

- `limit` defaulting to `50`
- `offset` defaulting to `0`
- stable default ordering, ideally by PID ascending
- return metadata:
  - `count`
  - `total`
  - `offset`
  - `limit`
  - `truncated`
  - `next_offset`

Rationale:

- agents should not dump the whole process table by default
- offset-based paging is acceptable as best-effort even though process tables
  are volatile

### 5. Command-line display must be sanitized

The tool should return a redacted `command_preview` rather than a fully trusted
raw command line.

Initial redaction rules:

- sanitize terminal control characters before display
- redact values associated with obvious sensitive markers such as:
  - `token`
  - `api_key`
  - `secret`
  - `password`
  - `authorization`
  - `bearer`
- clamp long command previews

Rationale:

- process command lines often contain tokens and credentials
- a best-effort redaction layer is much better than raw leakage

### 6. Termination defaults should be safe and explicit

`kill_process` defaults:

- `tree=true`
- `force=false`
- `timeout_seconds` defaults to a short graceful window

Behavior:

- graceful termination first
- escalate to force only if needed or if `force=true`
- return structured result showing what happened

Rationale:

- tree termination matches user expectations for dev servers and toolchains
- graceful-first reduces collateral damage

### 7. Self-protection is required

The tool should fail closed for obviously dangerous self-targets unless an
explicit future override mode is added.

Initial protected targets:

- current NEXUS server process when detectable
- current NEXUS CLI/session process when detectable

Rationale:

- agents should not casually kill the runtime they are currently using

## Proposed Tool Contracts

### `processes`

Parameters:

- `action`: `"list"` or `"get"`
- `pid?`: integer
- `query?`: string
- `match?`: `"exact" | "contains" | "regex"` (default `"contains"`)
- `user?`: string
- `port?`: integer
- `limit?`: integer (default `50`)
- `offset?`: integer (default `0`)

Behavior:

- `action="list"`:
  - returns paginated process summaries
- `action="get"`:
  - if `pid` is provided, return one detailed process record
  - otherwise allow query-based narrowing, but error if zero or multiple
    matches remain

Suggested output fields:

- `pid`
- `ppid`
- `name`
- `status`
- `username`
- `create_time`
- `command_preview`
- `cwd` when available
- `cpu_percent` best-effort
- `memory_rss`
- `listening_ports` / `connections` summary when requested via `port`

### `kill_process`

Parameters:

- `pid`: integer
- `tree?`: boolean (default `true`)
- `force?`: boolean (default `false`)
- `timeout_seconds?`: number

Behavior:

- validates target PID
- rejects protected/self-target processes
- performs graceful-first termination
- returns structured result including whether escalation occurred

## Implementation Details

Primary files:

- `pyproject.toml`
- `nexus3/skill/builtin/processes.py` (new)
- `nexus3/skill/builtin/kill_process.py` (new)
- `nexus3/skill/builtin/registration.py`
- `nexus3/core/process_tools.py` (new)

Likely supporting files:

- `nexus3/session/enforcer.py`
- `nexus3/defaults/NEXUS-DEFAULT.md`
- `nexus3/skill/README.md`
- `README.md`
- `CLAUDE.md`
- `AGENTS_NEXUS3SKILLSCAT.md`
- `AGENTS.md`

Implementation notes:

- add `psutil` as a runtime dependency after updating dependency audit notes
- keep the process backend in Python rather than shelling out
- factor shared helpers for:
  - process snapshot collection
  - command-line redaction
  - PID protection checks
- reuse existing termination primitives in `nexus3/core/process.py` where
  possible, extending them as needed for PID-driven termination
- make the read-only `processes` tool return JSON for predictable downstream use

## Permission Model

Recommended policy:

- `processes`:
  - disabled in `SANDBOXED`
  - allowed without confirmation in `TRUSTED`/`YOLO`
- `kill_process`:
  - disabled in `SANDBOXED`
  - always requires confirmation in `TRUSTED`
  - allowed in `YOLO`

Rationale:

- process inspection reveals host/runtime state outside the current repo
- process termination is destructive and should be treated like other
  confirmation-gated host actions

## Testing Strategy

Focused unit coverage:

- process filtering and pagination
- regex / contains / exact matching behavior
- command-line redaction
- unsupported / missing PID handling
- self-protection checks
- graceful-vs-force termination decision flow
- Windows and Unix behavior via mocking where needed

Focused live validation:

- spawn a disposable background process
- find it via `processes`
- inspect by PID via `processes(action="get", pid=...)`
- terminate it via `kill_process`
- verify it is gone

## Documentation Updates

- add both tools to current-facing skill tables
- explain that agents should prefer these tools over shell `ps`/`tasklist`
  / `pgrep` / `kill` / `taskkill`
- document that command previews are redacted and paginated
- record the new dependency in the dependency audit docs if `psutil` is adopted

## Checklist

- [x] Add and audit the `psutil` dependency for this use case.
- [x] Record any adopted dependency in the dependency audit docs with
  license/privacy notes.
- [x] Implement `processes`.
- [x] Implement `kill_process`.
- [x] Wire registration and permission behavior.
- [x] Add focused tests.
- [x] Sync docs/status.
- [x] Run focused validation and live checks.

Validation completed:

- `.venv/bin/ruff check nexus3/core/process_tools.py nexus3/skill/builtin/processes.py nexus3/skill/builtin/kill_process.py nexus3/skill/builtin/registration.py nexus3/core/policy.py nexus3/core/presets.py nexus3/config/schema.py nexus3/cli/confirmation_ui.py tests/unit/skill/test_process_tools.py tests/unit/cli/test_confirmation_ui_safe_sink.py tests/unit/test_permission_presets.py README.md nexus3/skill/README.md nexus3/defaults/NEXUS-DEFAULT.md CLAUDE.md AGENTS_NEXUS3SKILLSCAT.md AGENTS.md docs/plans/PROCESS-INSPECTION-AND-KILL-TOOLS-PLAN-2026-03-11.md docs/reviews/DEPENDENCY-LICENSE-AND-TELEMETRY-AUDIT-2026-03-10.md nexus3/cli/README.md nexus3/config/README.md`
- `.venv/bin/mypy nexus3/core/process_tools.py nexus3/skill/builtin/processes.py nexus3/skill/builtin/kill_process.py`
- `.venv/bin/pytest -q tests/unit/skill/test_process_tools.py tests/unit/cli/test_confirmation_ui_safe_sink.py tests/unit/test_permission_presets.py tests/unit/test_permissions.py` (`203 passed`)
- `.venv/bin/pytest tests/ -q` (`4433 passed, 3 skipped, 22 warnings`)
- live validation:
  - trusted RPC agent reached `processes` and invalid auto-injected `port`
    parameters failed closed with explicit errors (`port must be > 0`,
    `PID 2616 is not associated with port 2616`)
  - direct runtime harness against a detached real process confirmed
    `get_process_details(...)` returned expected fields and `terminate_pid(...)`
    succeeded with `success=true` and the process no longer alive afterward
