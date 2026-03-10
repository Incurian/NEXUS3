# Read/Text Fidelity Hardening Plan (2026-03-10)

## Overview

The broader March 10 tool-audit waves closed most schema and permission gaps,
but a smaller cluster of read-oriented tools still silently replacement-decode
invalid UTF-8 instead of failing closed or skipping invalid files explicitly.

Concrete remaining issues:

- `read_file` replacement-decodes invalid UTF-8, so its dedicated UTF-8 error
  path is unreachable and raw-mode fidelity is misleading.
- `outline` replacement-decodes invalid UTF-8, making its UTF-8 refusal path
  and directory-skip behavior effectively dead.
- `grep` replacement-decodes invalid UTF-8 in the Python fallback and also
  mishandles ripgrep JSON `lines.bytes`, which can surface blank or corrupted
  match text instead of deterministic skip/error behavior.
- `clipboard_update(source=...)` still replacement-decodes source files even
  after `copy` / `cut` / `paste` were hardened.
- `patch(diff_file=...)` still replacement-decodes diff files instead of
  refusing malformed text input.

This plan closes those fidelity issues without redesigning the tools into
binary-capable workflows.

## Scope

### Included

- Fail closed on invalid UTF-8 in `read_file` file reads.
- Fail closed on invalid UTF-8 in `outline` file mode and make directory mode
  skip invalid UTF-8 files intentionally rather than by accident.
- Make `grep` treat invalid UTF-8 files deterministically in both Python and
  ripgrep paths.
- Fail closed on invalid UTF-8 in `clipboard_update(source=...)`.
- Fail closed on invalid UTF-8 in `patch(diff_file=...)`.
- Add focused regressions and sync user-facing docs for the resulting contract.

### Deferred

- General binary-safe read/search tool support.
- Changes to subprocess/log decoding for shell/git/provider output, where
  replacement decoding is still acceptable for best-effort diagnostics.
- New encoding options beyond UTF-8.

### Excluded

- Reworking permission/path semantics for these tools; this slice is fidelity
  hardening, not a new authorization pass.
- Reopening already-closed file-edit or clipboard confirmation work.

## Design Decisions And Rationale

### 1. Single-file read tools should fail closed

`read_file`, `outline(file)`, `clipboard_update(source=...)`, and
`patch(diff_file=...)` all operate on a specific text input. For those calls,
invalid UTF-8 should return a clear error instead of fabricating replacement
characters.

### 2. Directory search/outline flows should stay resilient

For `grep(path=<dir>)` and `outline(path=<dir>)`, one invalid file should not
abort the whole directory result. The right contract is to skip invalid UTF-8
files explicitly and, where feasible, report that they were skipped.

### 3. Keep fast and fallback grep paths behaviorally aligned

The ripgrep fast path and Python fallback should not diverge on invalid UTF-8
handling. Both should avoid surfacing corrupted text and should converge on the
same skip/error contract.

## Implementation Details

### Phase 1: read/outline fidelity closeout

Files:

- `nexus3/skill/builtin/read_file.py`
- `nexus3/skill/builtin/outline.py`
- `tests/unit/test_skill_enhancements.py`
- `tests/unit/skill/test_outline.py`

Work:

- remove replacement decoding from `read_file`
- make the existing UTF-8 refusal path reachable
- remove replacement decoding from `outline`
- preserve directory-mode skip behavior by explicitly skipping invalid UTF-8
  files in directory outlines

### Phase 2: grep UTF-8 parity

Files:

- `nexus3/skill/builtin/grep.py`
- `tests/unit/test_skill_enhancements.py`
- `tests/unit/skill/test_grep_gateway.py`

Work:

- stop searching replacement-decoded text in the Python fallback
- handle ripgrep JSON `lines.bytes` deterministically instead of rendering
  blank/corrupted matches
- keep single-file grep fail-closed and directory grep skip-based

### Phase 3: remaining file-input readers + docs

Files:

- `nexus3/skill/builtin/clipboard_manage.py`
- `nexus3/skill/builtin/patch.py`
- `tests/unit/skill/test_clipboard_manage.py`
- `tests/unit/skill/test_patch.py`
- prompt/docs tables

Work:

- reject invalid UTF-8 source files in `clipboard_update(source=...)`
- reject invalid UTF-8 diff files in `patch(diff_file=...)`
- sync docs for `grep` path requirement and UTF-8 text-only behavior

## Testing Strategy

- run focused `ruff check` on touched runtime/test/doc files
- run focused pytest coverage for:
  - invalid UTF-8 refusal in single-file tools
  - directory skip behavior for `outline` / `grep`
  - ripgrep-path and Python-fallback parity for `grep`
  - malformed diff/source file handling
- run `git diff --check` before closeout

## Implementation Checklist

- [x] Record the remaining read/text fidelity findings and scope.
- [x] Phase 1: harden `read_file` and `outline`.
- [x] Phase 2: harden `grep` UTF-8 parity.
- [x] Phase 3: harden `clipboard_update(source=...)`, `patch(diff_file=...)`, and docs.
- [x] Run focused validation and record results.
- [x] Sync plan/status/docs closeout.

## Documentation Updates

- Update `docs/plans/README.md` to index this plan.
- Update `AGENTS.md` running status with the new slice and next gate.
- Sync `README.md`, `CLAUDE.md`, `AGENTS_NEXUS3SKILLSCAT.md`,
  `nexus3/defaults/NEXUS-DEFAULT.md`, and `nexus3/skill/README.md` for
  UTF-8 text-only and `grep(path=...)` contract wording.

## Validation Results

- `git diff --check`
- `.venv/bin/ruff check nexus3/skill/builtin/read_file.py nexus3/skill/builtin/outline.py nexus3/skill/builtin/grep.py nexus3/skill/builtin/clipboard_manage.py nexus3/skill/builtin/patch.py tests/unit/test_skill_enhancements.py tests/unit/skill/test_outline.py tests/unit/skill/test_clipboard_manage.py tests/unit/skill/test_patch.py`
- `.venv/bin/pytest -q tests/unit/test_skill_enhancements.py tests/unit/skill/test_outline.py tests/unit/skill/test_clipboard_manage.py tests/unit/skill/test_patch.py` (`272 passed`)
