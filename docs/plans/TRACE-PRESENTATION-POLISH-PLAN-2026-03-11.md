# Trace Presentation Polish Plan (2026-03-11)

## Overview

Polish the first trace-viewer / REPL tool-trace slice so it is easier to scan
in real use:

- REPL tool IDs should be clearly visible but visually quiet
- execution-trace entries should be color-separated by entry type
- long tool call/result bodies in the trace viewer should truncate by default
  instead of flooding the terminal

This is a presentation and observability pass on top of the already-shipped
trace / `/tool` / `/tools` functionality.

## Scope

Included:

- audit current REPL tool-trace rendering paths for missing visible tool IDs
- move REPL tool IDs to a dedicated dim header line above each tool call /
  result / error / halt block
- keep REPL tool-call/result body lines cleaner by removing inline IDs
- add execution-trace color treatment for:
  - user messages
  - assistant messages
  - tool calls
  - tool results
- color both trace headers and trace body content, with body content less
  saturated than the header family
- add default execution-trace truncation for tool call/result bodies
- expose a CLI flag to control truncation
- update focused docs/tests/status

Deferred:

- auto-following the currently active REPL agent/session
- auto-retargeting traces after server restart
- additional trace presets beyond the current shipped pair
- separate truncation controls for tool-call args vs tool-result bodies

Excluded:

- changing persisted trace storage/schema
- changing `/tool` editor-view retrieval behavior
- changing the current message-preview strategy for user/assistant lines

## Design Decisions And Rationale

### 1. Dim header lines for REPL tool IDs

The REPL should show tool IDs as stable handles, but they should not compete
with the actual tool action/result text. A dedicated dim header line above each
tool block solves that better than inline IDs.

### 2. Trace colors should emphasize categories, not raw content noise

Execution trace output benefits from strong visual separation by entry type,
but the actual body text should stay easier on the eyes than the header. Use a
brighter header color family with a calmer body style from the same family.

### 3. Bounded trace bodies are a better default

The trace viewer is for real-time observability, not unlimited dumping.
Default truncation around 50 lines keeps it useful without overwhelming the
terminal, while still allowing an explicit unlimited mode.

### 4. One shared truncation control is enough for v1

Use a single execution-trace option such as `--max-tool-lines` for both tool
call args and tool result bodies. If callers later need separate controls, add
them in a later pass.

## Implementation Details

Primary files:

- `nexus3/cli/repl.py`
- `nexus3/cli/repl_formatting.py`
- `nexus3/cli/trace.py`
- `nexus3/cli/arg_parser.py`
- `tests/unit/cli/test_repl_safe_sink.py`
- `tests/unit/cli/test_trace.py`
- `README.md`
- `nexus3/cli/README.md`
- `nexus3/defaults/NEXUS-DEFAULT.md`
- `CLAUDE.md`
- `AGENTS.md`

Planned changes:

- add REPL helper(s) for dim tool-id header lines
- print those headers before tool call/result/error/halt lines
- refactor execution trace entries to carry entry kind plus body lines instead
  of only pre-rendered plain lines
- render execution trace through per-kind header/body formatters
- add `--max-tool-lines` with a default of `50`; `0` means unlimited
- truncate long tool arg/result bodies with explicit note lines

## Testing Strategy

- focused formatting unit tests for the new REPL tool-id header layout
- focused trace unit tests for:
  - colored/kind-aware execution rendering structure
  - truncation behavior
  - `--max-tool-lines` argument parsing
- focused lint/mypy/pytest on the trace/repl slice
- one practical execution-trace smoke run against a real session log

## Documentation Updates

- update CLI docs for `--max-tool-lines`
- update trace examples to mention truncation control
- sync current running status in `AGENTS.md`

## Validation

Completed validation for the implemented polish slice:

- `.venv/bin/ruff check nexus3/cli/editor_preview.py nexus3/session/trace.py nexus3/cli/trace.py nexus3/cli/confirmation_ui.py nexus3/cli/arg_parser.py nexus3/cli/repl.py nexus3/cli/repl_commands.py nexus3/cli/repl_formatting.py tests/unit/session/test_trace.py tests/unit/cli/test_trace.py tests/unit/test_repl_commands.py tests/unit/cli/test_repl_safe_sink.py README.md CLAUDE.md AGENTS.md nexus3/cli/README.md nexus3/defaults/NEXUS-DEFAULT.md docs/plans/README.md docs/plans/TRACE-PRESENTATION-POLISH-PLAN-2026-03-11.md`
- `.venv/bin/mypy nexus3/cli/editor_preview.py nexus3/session/trace.py nexus3/cli/trace.py nexus3/cli/confirmation_ui.py nexus3/cli/arg_parser.py nexus3/cli/repl.py nexus3/cli/repl_commands.py nexus3/cli/repl_formatting.py`
- `.venv/bin/pytest -q tests/unit/session/test_trace.py tests/unit/cli/test_trace.py tests/unit/test_repl_commands.py tests/unit/cli/test_repl_safe_sink.py`
  - `116 passed`
- `git diff --check`
- practical smoke check:
  - `/home/inc/repos/NEXUS3/.venv/bin/python -m nexus3 trace --latest --once --history 2 --max-tool-lines 1`
    rendered a real latest-session snapshot with execution-trace truncation
    note output

## Checklist

- [x] Audit REPL tool-render paths for missing visible IDs.
- [x] Move REPL tool IDs to dim header lines above tool blocks.
- [x] Add colored execution-trace headers and body styling.
- [x] Add configurable tool-body truncation to execution trace.
- [x] Update focused docs/status.
- [x] Run focused validation and a real trace smoke check.
