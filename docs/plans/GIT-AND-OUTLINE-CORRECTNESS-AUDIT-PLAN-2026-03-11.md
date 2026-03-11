# Git And Outline Correctness Audit Plan (2026-03-11)

## Overview

This plan tracks a bounded correctness audit for two parser-heavy built-in
tools:

- `git`, specifically structured parsing of `status` output
- `outline`, specifically markdown heading extraction

The trigger was fresh testing that surfaced two concrete issues:

- `git status --short` raw output correctly showed untracked files while
  `parsed.untracked` came back empty
- markdown `outline` treated fenced code-block lines as real headings

The goal is not a broad rewrite. The goal is to eliminate nearby
misclassification / misleading-structured-output cases, add focused regression
coverage, and leave unsupported formats explicitly unsupported rather than
silently misparsed.

## Scope

Included:

- audit and tighten `git status` structured parsing for supported formats
- make unsupported `git status` formats avoid misleading parsed output
- audit markdown heading extraction for nearby false-positive cases
- add focused unit coverage and a live RPC smoke check
- sync current-facing docs and running status

Deferred:

- full `git status --porcelain=v2` structured parsing
- broader git-command parsing beyond `status`
- full Markdown/CommonMark AST support
- deeper audits of every non-markdown `outline` parser

Excluded:

- changing the external schema of the `git` or `outline` tools
- renaming tools
- broad prompt redesign

## Design Decisions And Rationale

### 1. Support only honest `git status` structured parsing

`git` currently attaches `parsed` data for `status` calls, but it should only
do so when the output format is one we actually understand.

Planned boundary:

- support:
  - default human-readable `git status`
  - short/porcelain-v1-style status (`--short`, `-s`, `--porcelain`,
    `--porcelain=v1`)
  - branch header parsing when present (`## ...`)
- do not claim structured parsing for:
  - `--porcelain=v2`
  - `-z`

Rationale:

- unsupported formats should not produce confident but wrong `parsed` output
- skipping `parsed` is safer and more honest than pretending to understand v2

### 2. Fix markdown false positives before adding more markdown features

The markdown parser is intentionally lightweight. The audit should focus first
on false positives and misleading structure extraction, not on full Markdown
feature parity.

Planned focus:

- fenced code blocks with backticks
- fenced code blocks with tildes
- fence open/close matching behavior
- nearby heading formatting quirks that still fit the current lightweight model

Rationale:

- false headings are worse for agent behavior than missing optional markdown
  niceties
- a narrow parser with honest boundaries is preferable to a larger heuristic
  parser that lies

## Implementation Details

Primary files:

- `nexus3/skill/builtin/git.py`
- `nexus3/skill/builtin/outline.py`
- `tests/unit/test_git_skill.py`
- `tests/unit/skill/test_outline.py`

Supporting docs/status:

- `README.md`
- `nexus3/skill/README.md`
- `nexus3/defaults/NEXUS-DEFAULT.md`
- `CLAUDE.md`
- `AGENTS_NEXUS3SKILLSCAT.md`
- `AGENTS.md`

Implementation notes:

- add explicit status-format gating in `git` so unsupported formats do not emit
  misleading `parsed`
- extend `git` parser coverage with representative long-form and short-form
  edge cases
- harden markdown fence tracking in `outline`
- add focused markdown tests around fenced content and other nearby
  misclassification risks

## Testing Strategy

Focused validation:

- `.venv/bin/ruff check nexus3/skill/builtin/git.py nexus3/skill/builtin/outline.py tests/unit/test_git_skill.py tests/unit/skill/test_outline.py README.md nexus3/skill/README.md nexus3/defaults/NEXUS-DEFAULT.md CLAUDE.md AGENTS_NEXUS3SKILLSCAT.md AGENTS.md`
- `.venv/bin/pytest -q tests/unit/test_git_skill.py tests/unit/skill/test_outline.py`

Live validation:

- run a trusted RPC agent against a temp git repo and confirm parsed
  untracked entries for `git status --short`
- run the same agent against a fenced-markdown fixture and confirm `outline`
  only returns real headings

## Documentation Updates

- describe the supported `git status` parsed-output boundary more precisely
- note markdown fenced-code handling in `outline` docs if behavior changes
- record audit status in `AGENTS.md`

## Checklist

- [x] Reproduce the reported `git` and `outline` issues locally.
- [x] Create this focused audit plan.
- [x] Tighten `git status` structured parsing boundaries and regressions.
- [x] Tighten markdown `outline` parsing and regressions.
- [x] Sync docs/status for any user-visible contract changes.
- [x] Run focused lint/tests and live RPC validation.

## Closeout Notes

Implemented:

- `git status` structured parsing now supports:
  - human-readable default `git status`
  - short / porcelain-v1-style output
- unsupported status formats now fail honest:
  - `--porcelain=v2`
  - `-z`
  - these retain raw output but do not attach misleading `parsed`
- markdown `outline` now:
  - ignores fenced code blocks using backticks or tildes
  - trims trailing closing `#` markers from ATX headings

Focused validation passed:

- `.venv/bin/ruff check nexus3/skill/builtin/git.py nexus3/skill/builtin/outline.py tests/unit/test_git_skill.py tests/unit/skill/test_outline.py README.md nexus3/skill/README.md nexus3/defaults/NEXUS-DEFAULT.md CLAUDE.md AGENTS_NEXUS3SKILLSCAT.md AGENTS.md docs/plans/README.md docs/plans/GIT-AND-OUTLINE-CORRECTNESS-AUDIT-PLAN-2026-03-11.md`
- `.venv/bin/pytest -q tests/unit/test_git_skill.py tests/unit/skill/test_outline.py` (`193 passed`)

Live validation passed:

- trusted RPC agent confirmed `git status --short` returned parsed untracked
  entries for a temp repo
- trusted RPC agent confirmed `git status --porcelain=v2` omitted `parsed`
  output
- trusted RPC agent confirmed markdown `outline` on a fenced-code fixture only
  returned real headings
