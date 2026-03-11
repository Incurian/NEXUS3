# Trace Viewer And Diagnostic Routing Plan (2026-03-11)

## Overview

Add a non-interactive live trace viewer as a separate CLI mode and use it as
the preferred real-time surface for optional diagnostic streams.

The current REPL is intentionally conversation-first. It already shows tool
activity, and recent work added bounded MCP result previews, but deeper
inspection and opt-in debugging still push toward either cluttering the main
REPL or forcing the user to dig through session logs by hand.

This plan establishes a broader direction:

- keep the main REPL focused on the conversation and default-on tool trace
- add a separate live trace viewer for execution-heavy and debug-heavy views
- route optional diagnostic surfaces enabled by CLI flags away from the main
  REPL and toward trace views / persisted logs instead

## Scope

Included:

- define a dedicated trace-viewer feature as a planned CLI surface
- define the initial execution-oriented trace preset:
  - short user/assistant message previews
  - full tool calls
  - full tool results
- define follow-on trace presets for richer diagnostics
- record that on-demand full tool-result retrieval and live trace viewing are
  complementary features, not alternatives
- record the policy that opt-in diagnostic modes triggered by CLI arguments
  should not dump their extra output into the main REPL

Deferred:

- exact CLI command names and flag spelling
- any convenience helper that auto-spawns a second terminal window
- a unified structured event bus for every trace type
- replay mode for historical sessions
- rich filtering, searching, or interactivity inside the trace viewer

Excluded:

- changing default-on REPL output that already belongs in the main interface
- removing persisted log files such as `verbose.md` or `raw.jsonl`
- changing MCP result flattening/storage in this plan

## Design Decisions And Rationale

### 1. Separate trace viewer, not more REPL clutter

Preferred shape:

- separate CLI command / mode
- non-interactive, read-only, real-time
- intended to run in another terminal when desired

Rationale:

- the user wants observability without turning the main REPL into a debug pane
- a separate viewer composes better with long-running sessions and shell
  workflows

### 2. Start with an execution preset, but design for multiple trace types

Planned direction:

- execution trace: short message previews, full tool calls/results
- debug trace: execution plus timing/warnings/session diagnostics
- provider trace: provider/request lifecycle summaries
- raw trace: likely later and probably more sensitive/noisy

Rationale:

- the “inverse of the REPL” concept is useful beyond tool inspection
- multiple trace presets are a better long-term abstraction than bespoke
  one-off windows for each debug mode

### 3. Retrieval command remains worthwhile

Planned complementary surfaces:

- REPL retrieval commands such as `/tool last`, `/tool <id-prefix>`, and
  likely `/tools [n]`
- separate live trace viewer for streaming observability

Rationale:

- the trace viewer solves live monitoring
- REPL retrieval solves targeted historical inspection from the conversation
  surface

### 4. Use structured session data, not rendered text logs

Preferred data source:

- session SQLite/log storage first
- fall back to richer event plumbing only when needed

Avoid:

- scraping `verbose.md`
- scraping rendered REPL scrollback

Rationale:

- execution records already persist enough structure to reconstruct tool calls
  and results by `tool_call_id`
- structured sources survive compaction and are less fragile than pretty logs

### 5. Optional diagnostic flags should stop cluttering the main REPL

Policy direction:

- default-on conversational/tool output that belongs in the REPL stays there
- optional diagnostic modes enabled by CLI arguments should not print their
  extra detail into the main REPL
- if the user wants those details in real time, they should use a trace view
- persisted artifacts (`verbose.md`, `raw.jsonl`, SQLite events) remain valid
  sources of truth

Current motivation:

- `-v/--verbose` currently pushes debug output to the terminal
- `-V/--log-verbose` and `--raw-log` are already file-oriented, and the trace
  system should become the live-view path for that information rather than
  teaching users to mix diagnostic chatter into the main REPL

Rationale:

- this keeps the main REPL readable
- it gives one consistent answer to “where do I watch debug info live?”

## Implementation Details

Likely primary areas for later implementation:

- CLI command surface and argument parsing:
  - `nexus3/cli/arg_parser.py`
  - `nexus3/cli/repl_runtime.py`
  - new trace-viewer command/module(s)
- session/log ingestion:
  - `nexus3/session/storage.py`
  - `nexus3/session/logging.py`
  - `nexus3/session/types.py`
- REPL tool ID exposure and retrieval commands:
  - `nexus3/cli/repl.py`
  - `nexus3/cli/repl_formatting.py`
  - `nexus3/cli/repl_commands.py`
  - `nexus3/cli/confirmation_ui.py` or a shared editor-preview helper
- docs/status:
  - `README.md`
  - `nexus3/cli/README.md`
  - `nexus3/defaults/NEXUS-DEFAULT.md`
  - `CLAUDE.md`
  - `AGENTS.md`

Planned v1 trace-viewer behavior:

- separate command/mode, not an in-REPL interactive panel
- user/assistant messages rendered as short previews
- tool calls rendered with full name and full args
- tool results rendered with full success/error bodies
- safe terminal sanitization still applies
- explicit session/agent targeting should be supported

Planned later UX follow-up:

- optional convenience command to spawn a second terminal window running the
  trace viewer, after the core trace mode exists and proves useful

## Testing Strategy

Future implementation should cover:

- execution trace rendering from persisted session data
- deterministic incremental follow behavior for new messages/events
- stable tool-result lookup by visible tool identifier / `tool_call_id`
- separation between normal REPL output and optional diagnostic trace output
- at least one practical live validation run with REPL + parallel trace viewer

Validation should likely include:

- focused `ruff`
- focused pytest for trace formatting, session-log reading, and REPL command
  behavior
- practical live validation with one terminal running the REPL and another
  terminal following the trace stream

## Documentation Updates

When implemented:

- document the trace command(s) and presets
- document the relationship between:
  - normal REPL output
  - live trace viewing
  - persisted logs (`context.md`, `verbose.md`, `raw.jsonl`, SQLite storage)
- update CLI flag docs so opt-in diagnostic flags no longer imply “debug spam
  in the main REPL”

## Validation

Completed validation for the implemented v1 slice:

- `.venv/bin/ruff check nexus3/cli/editor_preview.py nexus3/session/trace.py nexus3/cli/trace.py nexus3/cli/confirmation_ui.py nexus3/cli/arg_parser.py nexus3/cli/repl.py nexus3/cli/repl_commands.py nexus3/cli/repl_formatting.py tests/unit/session/test_trace.py tests/unit/cli/test_trace.py tests/unit/test_repl_commands.py tests/unit/cli/test_repl_safe_sink.py`
- `.venv/bin/mypy nexus3/cli/editor_preview.py nexus3/session/trace.py nexus3/cli/trace.py nexus3/cli/confirmation_ui.py nexus3/cli/arg_parser.py nexus3/cli/repl.py nexus3/cli/repl_commands.py nexus3/cli/repl_formatting.py`
- `.venv/bin/pytest -q tests/unit/session/test_trace.py tests/unit/cli/test_trace.py tests/unit/test_repl_commands.py tests/unit/cli/test_repl_safe_sink.py`
  - `112 passed`
- practical smoke checks:
  - `/home/inc/repos/NEXUS3/.venv/bin/python -m nexus3 trace --latest --once --history 2` rendered a real latest-session snapshot from `.nexus3/logs`
  - `nexus3 trace /tmp/nexus3-trace-smoke --once` rendered the expected snapshot
  - `nexus3 trace /tmp/nexus3-trace-live` followed `session.db` updates in real time
  - `nexus3 trace /tmp/nexus3-trace-live --preset debug` followed appended `verbose.md` lines in real time

## Checklist

- [x] Add and index this planning doc.
- [x] Record the complementary REPL retrieval + live trace direction.
- [x] Record the policy that opt-in diagnostic CLI flags should route away
      from the main REPL and toward trace views / logs.
- [x] Implement the first execution trace viewer preset.
- [x] Implement REPL-side tool ID exposure and retrieval commands.
- [x] Move optional live diagnostic output off the main REPL.
- [x] Run focused validation and a practical dual-terminal live check.
