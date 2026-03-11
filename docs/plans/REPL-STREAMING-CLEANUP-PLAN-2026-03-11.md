# REPL Streaming Cleanup Plan (2026-03-11)

## Overview

Clean up the REPL streaming/display architecture so ordinary presentation
changes, including streamed assistant coloring, do not require fragile changes
across multiple partially overlapping display paths.

The current behavior works for the common happy path, but the architecture is
harder to modify than it should be. A small attempted styling change exposed
that the REPL is maintaining duplicated line/buffer state across layers, and
that the codebase still carries an older Rich-native streaming stack that is no
longer the active REPL path.

This plan records the current findings and defines the cleanup direction before
implementation.

## Scope

Included:

- document the current streaming/display findings
- choose a single canonical REPL streaming/display architecture
- remove or quarantine stale display abstractions that are no longer runtime
  authorities
- consolidate streamed-line ownership into one layer
- separate trust/sanitization concerns from transport-specific rendering
- make streamed assistant styling changes local and safe

Deferred:

- broader terminal theming system redesign
- custom user-configurable themes
- redesigning non-REPL client-mode output
- changing trace semantics beyond shared styling/formatting infrastructure

Excluded:

- changing provider streaming semantics
- changing permission prompts or MCP interaction flows
- changing session persistence or log schema

## Current Findings

### 1. The codebase carries two incompatible streaming architectures

The live REPL uses:

- `nexus3/display/spinner.py`
- direct callback wiring in `nexus3/cli/repl.py`

But the repository still exports and documents:

- `nexus3/display/streaming.py`
- `nexus3/display/manager.py`

Those older pieces appear to be effectively deprecated in runtime practice but
remain first-class in module exports, tests, and docs.

Impact:

- display behavior is harder to reason about than necessary
- maintenance effort is split across code that is not the actual REPL path
- future changes risk fixing the wrong abstraction

### 2. Stream line state has two owners

The REPL tracks `_stream_line_open` in `nexus3/cli/repl.py`, while the spinner
tracks its own `_stream_buffer` in `nexus3/display/spinner.py`.

Impact:

- the REPL is reasoning about newline/partial-line state using raw chunks
  instead of the sanitized/rendered stream state
- small changes to buffering or rendering can desynchronize the two layers
- tool-boundary flushing is more fragile than it needs to be

### 3. Sanitization behavior is coupled to output transport

`SafeSink.print_untrusted()` performs full display sanitization for Rich
printing, while `SafeSink.write_untrusted()` only strips terminal escapes for
raw stream writes.

Impact:

- moving streamed assistant output from raw writes to Rich printing changes the
  sanitizer contract as a side effect
- styling changes become entangled with trust-boundary concerns

### 4. The theme layer is not the real visual source of truth

`nexus3/display/theme.py` advertises centralized styling, but much of the real
REPL styling lives in `nexus3/cli/repl_formatting.py` or in hardcoded display
code.

Impact:

- “change the REPL color scheme” is not a local theme edit
- styling decisions are split across unrelated modules

## Design Decisions And Rationale

### 1. Pick one canonical REPL display path

Near-term direction:

- treat the spinner-based REPL path as canonical
- treat `StreamingDisplay` / `DisplayManager` as stale unless a concrete runtime
  caller is restored deliberately

Rationale:

- the active REPL already uses `Spinner`
- shrinking the number of active abstractions is a prerequisite for safe
  cleanup

### 2. Make the spinner the sole owner of streamed-line state

Move partial-line/open-line bookkeeping behind the spinner boundary instead of
recomputing it in `repl.py`.

Rationale:

- buffering/render state belongs with the buffering primitive
- the REPL should orchestrate phases, not mirror transport details

### 3. Separate ingress sanitization from render-target escaping

The architecture should distinguish:

- stripping terminal control sequences from model/tool chunks
- escaping content for Rich-markup rendering when applicable

Rationale:

- transport choice should not change trust semantics accidentally
- streamed styling should become a rendering concern, not a sink-contract trap

### 4. Centralize visible REPL/trace styling intentionally

Keep shared trace/REPL palette decisions in one place and make it explicit
which output classes still bypass that palette.

Rationale:

- visual changes should be local edits
- inconsistent hardcoded styling has already caused avoidable churn

## Implementation Details

Primary files to inspect/update:

- `nexus3/cli/repl.py`
  - remove duplicated stream-line bookkeeping from REPL orchestration
- `nexus3/display/spinner.py`
  - become the single owner of streamed assistant buffering/render state
- `nexus3/display/safe_sink.py`
  - split or clarify transport-independent vs transport-specific sanitization
- `nexus3/display/theme.py`
  - keep only styling concerns that are actually respected at runtime
- `nexus3/cli/repl_formatting.py`
  - keep shared REPL/trace formatting decisions centralized

Likely deletion/quarantine targets:

- `nexus3/display/streaming.py`
- `nexus3/display/manager.py`
- related stale docs/tests if they no longer describe supported runtime paths

Likely docs:

- `nexus3/display/README.md`
- `nexus3/cli/README.md`
- `README.md`
- `CLAUDE.md`
- `AGENTS.md`
- `docs/plans/README.md`

## Testing Strategy

Add or update focused coverage for:

- spinner-owned streamed-line state transitions
- tool-boundary flush behavior without REPL-side duplicate state tracking
- trust-boundary behavior for streamed assistant content under the chosen
  render transport
- REPL formatting integration where assistant output, tool output, and errors
  interleave

Validation should include:

- focused `ruff`
- focused `mypy`
- focused pytest for display and REPL output helpers
- practical interactive smoke checks for:
  - plain assistant streaming
  - assistant streaming followed by tool batches
  - cancellation/error mid-stream

## Documentation Updates

When implementing:

- document the canonical REPL display architecture
- remove or clearly mark stale/deprecated display paths
- document any remaining limitations around styled streamed assistant output

## Checklist

- [x] Create and index this plan.
- [x] Record current review findings and cleanup direction.
- [x] Update running status for the new branch/workstream.
- [ ] Decide whether to delete or explicitly quarantine deprecated display modules.
- [ ] Make spinner the single owner of streamed-line state.
- [ ] Refactor stream sanitization/render responsibilities.
- [ ] Revalidate REPL streaming/tool interleave behavior.
- [ ] Sync docs after implementation.
