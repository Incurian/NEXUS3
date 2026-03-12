# REPL Recent History Plan (2026-03-12)

## Overview

Add a small pulled-history block to the REPL so that when the terminal attaches
to an existing session context, the user can immediately see the last couple of
conversation messages without opening `trace`.

The target behavior is a dim/grey `Recent history` block rendered on session
attach points such as startup and agent switching.

## Scope

Included:

- render a bounded dim recent-history block in the REPL
- source that block from the last non-empty user/assistant messages
- show it when the REPL attaches to an existing session context:
  - initial startup
  - agent switch
  - restore
  - whisper attach / return
- add focused formatting/selection regression coverage
- update current-facing docs and running-status notes

Deferred:

- configurable history depth or preview limits
- showing recent tool calls/results in the same block
- sharing one history-rendering helper between REPL and `trace`

Excluded:

- trace viewer behavior changes
- persisted session/log schema changes
- command surface changes

## Design Decisions And Rationale

### 1. Conversation messages only

Behavior:

- only user/assistant messages with non-empty text are shown
- tool-only records are excluded

Rationale:

- the request was for recent messages, not another full execution trace
- keeping tool output out avoids duplicating the normal REPL tool-result UI

### 2. Dim styling to indicate pulled history

Behavior:

- the block is rendered in dim grey instead of live role colors

Rationale:

- pulled history should read as context, not as newly streamed output

### 3. Bounded previews

Behavior:

- only the last two qualifying messages are shown
- each message preview is bounded by line and character limits with explicit
  truncation notes

Rationale:

- startup/switch attach should stay lightweight
- explicit truncation avoids silently hiding the shape of long messages

## Implementation Details

Primary files:

- `nexus3/cli/repl.py`
- `nexus3/cli/repl_formatting.py`
- `tests/unit/cli/test_repl_safe_sink.py`

Supporting docs:

- `README.md`
- `nexus3/cli/README.md`
- `CLAUDE.md`
- `AGENTS.md`
- `docs/plans/README.md`

Planned behavior details:

- add a formatting helper that builds a dim recent-history block from message
  objects
- add a small REPL helper that prints that block when there is qualifying
  history
- call that helper after startup metadata and on agent attach transitions

## Testing Strategy

Focused coverage should confirm:

- history selection keeps only the last non-empty user/assistant messages
- preview lines sanitize correctly
- multiline previews truncate deterministically

Validation:

- focused `ruff`
- focused `mypy`
- focused `pytest` for REPL formatting helpers

## Documentation Updates

- add and index the plan doc
- update REPL/current-facing docs to mention the recent-history block
- record the active slice in `AGENTS.md`

## Checklist

- [x] Add and index the plan doc.
- [x] Implement dim recent-history rendering for REPL attach points.
- [x] Add focused regression coverage.
- [x] Sync docs and running-status notes.
- [x] Run focused validation.

Validation completed:

- `.venv/bin/pytest -q tests/unit/cli/test_repl_safe_sink.py` (`39 passed`)
- `.venv/bin/ruff check nexus3/cli/repl.py nexus3/cli/repl_formatting.py tests/unit/cli/test_repl_safe_sink.py README.md nexus3/cli/README.md CLAUDE.md AGENTS.md docs/plans/README.md docs/plans/REPL-RECENT-HISTORY-PLAN-2026-03-12.md`
- `.venv/bin/mypy nexus3/cli/repl.py nexus3/cli/repl_formatting.py`
- `git diff --check`
