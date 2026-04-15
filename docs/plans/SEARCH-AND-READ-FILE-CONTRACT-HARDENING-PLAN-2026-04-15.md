# Search And Read File Contract Hardening Plan (2026-04-15)

## Overview

This slice hardens two agent-facing built-in tool behaviors that can mislead
models during repository navigation:

- `search_text` can miss real matches on the ripgrep fast path because plain
  `rg --json` skips hidden and gitignored files by default, while the Python
  fallback does not.
- `read_file` does not currently report partial-read windows clearly enough for
  agents to distinguish "I read the requested slice" from "I read the whole
  file", especially when output is truncated.

The goal is to make the search/read contract more deterministic and make
partial reads explicit enough that agents can continue from the correct line
instead of silently assuming they saw the full file.

## Scope

### Included

- align unrestricted ripgrep-backed `search_text` behavior with the Python
  fallback for ordinary project files by searching hidden and gitignored files
  while preserving explicit heavy-directory exclusions
- add focused regression coverage for the ripgrep path so hidden and ignored
  files are not silently skipped
- make `read_file` partial-read output explicitly describe the returned line
  window and next offset when more content remains
- add focused regression coverage for `read_file` truncation messaging

### Deferred

- broader `search_text` contract changes such as literal-mode aliases, ranked
  search, or multiple-pattern search
- structural output changes for `read_file` beyond the minimum needed to make
  partial reads explicit
- broader prompt/doc rewrites unless the final behavior change requires a small
  update for accuracy

### Excluded

- changing permission gating or path-scoping rules
- changing RPC `get_messages(limit=200)` behavior
- redesigning `outline`, `concat_files`, or other read/navigation tools

## Design Decisions And Rationale

### 1. Ripgrep fast-path behavior should match the built-in search contract, not raw `rg` defaults

`search_text` is a NEXUS tool, not a thin shell wrapper. If the caller asks to
search a directory, hidden files and gitignored files that live under that path
should not disappear only because the unrestricted path happened to use
ripgrep. We should enable hidden/no-ignore behavior on the fast path and keep
the existing explicit exclusions for heavyweight directories.

### 2. Preserve explicit exclusions even when enabling hidden/no-ignore

The Python fallback intentionally skips directories such as `.git`,
`node_modules`, `.venv`, `.nexus3`, and similar heavy/non-source locations.
The ripgrep path should keep that safety/perf behavior instead of switching to
"search absolutely everything".

### 3. `read_file` should teach continuation directly in the tool result

When a read returns only a slice, the result should say so explicitly and
include the continuation line. That is more reliable for agents than requiring
them to infer truncation from a generic footer.

### 4. Keep the public tool surface stable

This slice should not add new top-level parameters or split tool names. The
fix belongs in runtime behavior and result wording, not in a new public tool
shape.

## Implementation Details

Primary files:

- `nexus3/skill/builtin/grep.py`
  - add ripgrep flags/globs so unrestricted fast-path search includes hidden
    and gitignored files while still excluding known heavy directories
  - harden `include` parsing so comma-separated lists like `*.h, *.cpp` work
    alongside brace expansion, and malformed include strings fail clearly
  - keep existing result formatting and invalid-UTF8 handling intact
- `nexus3/skill/builtin/read_file.py`
  - enrich partial-read reporting with an explicit returned window and next
    offset when more content remains
- `tests/unit/test_skill_enhancements.py`
  - add targeted regressions for ripgrep hidden/gitignored-file coverage and
    `read_file` partial-read messaging
  - add `search_text(include=...)` coverage for comma-separated lists and
    malformed input errors
- `tests/unit/skill/test_grep_parallel.py`
  - extend ripgrep command/behavior coverage if needed for the fast path

Potential doc/handoff updates if behavior text changes materially:

- `docs/plans/README.md`
- `AGENTS.md`
- `CLAUDE.md`

## Testing Strategy

Focused validation:

- `.venv/bin/pytest -q tests/unit/test_skill_enhancements.py tests/unit/skill/test_grep_parallel.py`
- `.venv/bin/ruff check nexus3/skill/builtin/grep.py nexus3/skill/builtin/read_file.py tests/unit/test_skill_enhancements.py tests/unit/skill/test_grep_parallel.py`
- `.venv/bin/mypy nexus3/skill/builtin/grep.py nexus3/skill/builtin/read_file.py`

If session/runtime wording or behavior shifts more broadly than expected:

- add any narrow companion tests needed for documentation/examples
- consider a live RPC smoke pass because these are agent-facing tool behaviors

## Implementation Checklist

- [x] capture the confirmed ripgrep mismatch in this plan and regressions
- [x] patch unrestricted ripgrep-backed `search_text` to include hidden and
      gitignored files while preserving explicit exclusions
- [x] add fast-path regression coverage for hidden and ignored files
- [x] accept comma-separated `search_text(include=...)` lists and fail clearly
      on malformed include strings
- [x] patch `read_file` partial-read output to report the returned line window
      and next offset explicitly
- [x] add `read_file` truncation/continuation regression coverage
- [x] run focused validation
- [x] update handoff/docs as needed

## Documentation Updates

- add this plan to `docs/plans/README.md`
- update `AGENTS.md` / `CLAUDE.md` current handoff if the slice lands
- update user-facing docs only if the final search/read behavior description is
  no longer accurate

## Validation Status

Observed reproduction before the patch:

- plain `rg --json needle <dir>` matched a normal file but skipped a hidden file
  and a `.gitignore`d file in the same directory tree

Focused validation passed:

- `.venv/bin/pytest -q tests/unit/test_skill_enhancements.py` (`39 passed`)
- `.venv/bin/pytest -q tests/unit/skill/test_grep_parallel.py` (`14 passed`)
- `.venv/bin/ruff check nexus3/skill/builtin/grep.py nexus3/skill/builtin/read_file.py tests/unit/test_skill_enhancements.py tests/unit/skill/test_grep_parallel.py`
- `.venv/bin/mypy nexus3/skill/builtin/grep.py nexus3/skill/builtin/read_file.py`

Follow-on include-parser validation passed:

- `.venv/bin/pytest -q tests/unit/test_skill_enhancements.py` (`41 passed`)
- `.venv/bin/pytest -q tests/unit/skill/test_grep_parallel.py` (`15 passed`)
- `.venv/bin/ruff check nexus3/skill/builtin/grep.py tests/unit/test_skill_enhancements.py tests/unit/skill/test_grep_parallel.py README.md nexus3/skill/README.md nexus3/defaults/NEXUS-DEFAULT.md`
- `.venv/bin/mypy nexus3/skill/builtin/grep.py`
