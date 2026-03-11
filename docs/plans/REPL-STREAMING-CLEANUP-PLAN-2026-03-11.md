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

Implementation status (in progress):

- `Spinner` now owns streamed-line state and explicit block-boundary framing
  APIs; `repl.py` no longer mirrors `_stream_line_open`
- streamed assistant styling now stays on the raw streaming path instead of
  routing complete lines back through Rich printing
- `SafeSink` now exposes the transport split explicitly:
  terminal-control stripping vs Rich-safe escaping
- `nexus3.display` package-root exports now quarantine the legacy display
  stack from the active public surface
- follow-up live-test regression fix:
  - `Session.send()` / `Session.run_turn()` now serialize through a shared
    per-session turn slot
  - dispatcher incoming-turn notifications now wait until that turn slot is
    actually acquired, so queued incoming RPC sends do not interrupt an active
    REPL tool turn
  - `nexus_send` now rejects self-target to avoid deadlocking behind its own
    active turn
- follow-up turn-mutation fix:
  - external `compact()` now serializes through the same shared session turn
    slot as `send()` / `run_turn()`
  - in-turn auto-compaction now uses `compact_locked()` so tool-loop
    compaction remains safe without re-entering that lock
- follow-up streamed-content fix:
  - simple-turn and tool-loop runtimes now reconcile assistant text that only
    appears on the final `StreamComplete.message.content`
  - pre-tool narration is now emitted before tool execution even when the
    provider never sent earlier `ContentDelta` chunks for that text
  - plain final-only assistant responses now still surface to the caller
    instead of silently appearing only in persisted context

## Interaction Inventory

The cleanup must explicitly account for every REPL output path that currently
interleaves with streamed assistant text or depends on streaming state:

### Main turn streaming path

- plain assistant streaming from `Session.send()` into `Spinner.print_streaming()`
- first-chunk transition from `WAITING` to `RESPONDING`
- partial assistant lines that do not end with `\n`
- final stream flush on normal completion

### Reasoning / thinking notifications

- `on_reasoning(True)` switching the spinner into `THINKING`
- `on_reasoning(False)` returning to `RESPONDING`
- accumulated thought-duration summary printed before tool output or after turn

### Tool lifecycle interleave

- `on_batch_start()`
- `on_tool_active()`
- `on_batch_progress()` success path
- `on_batch_progress()` error path
- `on_batch_halt()`
- `on_batch_complete()`
- tool timing and active/pending bookkeeping used by ESC cancellation

### Tool-output special cases

- `nexus_send` response preview block
- `mcp_*` result preview blocks
- ordinary success summaries from `_summarize_tool_output(...)`
- explicit tool-id header lines above call/result/error/halt blocks

### Cancellation / interruption

- ESC during plain assistant streaming
- ESC while a tool is active
- cancelled-tool persistence via `add_cancelled_tools(...)`
- post-turn cancelled status line
- newline/flush behavior when cancellation happens mid-line

### Error paths

- `NexusError` / provider error rendering after a partial streamed line
- tool error rendering inside a batch
- autosave error line printed after turn completion
- toolbar error-state updates following a failed turn

### Prompt / command interleave

- slash commands handled at the prompt instead of inside the stream
- slash-command result printing (`SUCCESS`, `ERROR`, `SWITCH_AGENT`,
  `ENTER_WHISPER`, `QUIT`)
- commands that synchronously prompt with `console.input("[y/n]: ")`
- `KeyboardInterrupt` / `EOFError` behavior at the prompt

### Out-of-band session mutation

- RPC `compact` while a REPL turn or tool batch is already active
- slash-command `/compact` while external sends are queued
- in-turn auto-compaction before provider calls and after final responses

### Agent-routing edge cases

- whisper mode redirecting user messages to another agent session
- session callback attach/detach on agent switch to avoid foreign-agent tool
  output leaking into the active REPL
- incoming RPC turn notifications interrupting the prompt with their own
  spinner + start/end notification lines

### End-of-turn framing

- leading blank line before turn output
- newline termination before spinner teardown
- trailing blank line after streamed content
- turn-completed status line for successful turns

## Testing Strategy

Add or update focused coverage for:

- spinner-owned streamed-line state transitions
- tool-boundary flush behavior without REPL-side duplicate state tracking
- trust-boundary behavior for streamed assistant content under the chosen
  render transport
- REPL formatting integration where assistant output, tool output, and errors
  interleave
- incoming-turn notification behavior relative to prompt/stream state
- slash-command and confirmation-prompt flows remaining outside the streaming
  state machine
- whisper/agent-switch callback routing so non-displayed sessions cannot
  render tool output into the current REPL

Validation should include:

- focused `ruff`
- focused `mypy`
- focused pytest for display and REPL output helpers
- practical interactive smoke checks for:
  - plain assistant streaming
  - assistant streaming followed by tool batches
  - cancellation/error mid-stream
  - `nexus_send` tool preview + response preview
  - MCP result preview interleave
  - incoming RPC turn notification while idle at prompt
  - whisper-mode send path
  - slash-command prompt flows that call `console.input(...)`

Validation completed so far:

- `.venv/bin/pytest -q tests/unit/display/test_safe_sink.py
  tests/unit/display/test_escape_sanitization.py
  tests/unit/cli/test_repl_safe_sink.py tests/unit/test_display.py`
  (`177 passed`)
- `.venv/bin/ruff check nexus3/display/safe_sink.py nexus3/display/spinner.py
  nexus3/display/theme.py nexus3/display/__init__.py nexus3/cli/repl.py
  nexus3/cli/repl_formatting.py tests/unit/display/test_safe_sink.py
  tests/unit/display/test_escape_sanitization.py
  tests/unit/cli/test_repl_safe_sink.py tests/unit/test_display.py`
- `.venv/bin/mypy nexus3/display/safe_sink.py nexus3/display/spinner.py
  nexus3/display/theme.py nexus3/cli/repl.py nexus3/cli/repl_formatting.py`
- `git diff --check`
- stdout-proxy smoke: styled streamed line + buffered partial line + tool block
  ordering all rendered correctly through Rich's redirected stdout path
- live spinner smoke: `Spinner.show()` / streamed lines / tool block / hide()
  completed without dropped lines or duplicate reset fragments
  - note: this shell has `console.no_color=True`, so the live smoke confirmed
    framing/order correctness rather than visible magenta color
- incoming-turn regression validation:
  - `.venv/bin/pytest -q tests/unit/rpc/test_schema_ingress_wiring.py
    tests/unit/test_agent_api.py tests/unit/test_rpc_dispatcher.py
    tests/unit/session/test_session_cancellation.py
    tests/unit/skill/test_nexus_skills.py tests/unit/display/test_safe_sink.py
    tests/unit/display/test_escape_sanitization.py
    tests/unit/cli/test_repl_safe_sink.py tests/unit/test_display.py`
    (`323 passed`)

## Documentation Updates

When implementing:

- document the canonical REPL display architecture
- remove or clearly mark stale/deprecated display paths
- document any remaining limitations around styled streamed assistant output

## Checklist

- [x] Create and index this plan.
- [x] Record current review findings and cleanup direction.
- [x] Update running status for the new branch/workstream.
- [x] Decide whether to delete or explicitly quarantine deprecated display modules.
- [x] Make spinner the single owner of streamed-line state.
- [x] Refactor stream sanitization/render responsibilities.
- [x] Preserve correct behavior for reasoning, tools, previews, commands, incoming turns, cancellation, and end-of-turn framing.
- [x] Revalidate REPL streaming/tool interleave behavior.
- [x] Sync docs after implementation.
