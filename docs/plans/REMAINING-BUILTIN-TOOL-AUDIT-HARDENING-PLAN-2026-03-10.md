# Remaining Built-In Tool Audit Hardening Plan (2026-03-10)

## Overview

The broad March 10 tool-family hardening plan closed the file-edit, clipboard
management, nexus, shell, GitLab, and MCP slices, but the remaining built-in
tools still contain concrete contract and safety defects:

- `concat_files(dry_run=false)` writes an output file without being modeled as a
  write-path tool for confirmation/allowance purposes.
- the remaining read/search/listing family and clipboard wrapper/info tools
  still silently drop unknown top-level arguments instead of failing closed.
- `tail`, `concat_files`, `copy`, `cut`, and `paste` still use lossy
  `errors="replace"` decoding paths that can silently mangle non-UTF8 files.
- `clipboard_import` trusts JSON structure too loosely and can raise internal
  exceptions on malformed-but-valid JSON payloads.

This plan covers the bounded hardening needed to close those concrete findings
without reopening already-completed tool families.

## Scope

### Included

- Harden `concat_files` write-path semantics, confirmation, and path extraction.
- Add strict top-level unknown-argument rejection to the remaining built-in
  read/search/listing tools and clipboard wrapper/info tools.
- Fail closed on non-UTF8 clipboard file operations and remaining read-only
  tools that still perform lossy decoding.
- Validate `clipboard_import` payload structure before iterating/importing.
- Add focused regressions for every shipped fix.

### Deferred

- Broader prompt redesign for remaining tool families.
- New compatibility aliases unless a fresh concrete transcript requires them.
- Deeper clipboard tag feature work beyond documenting the current
  `create`/`delete` behavior.

### Excluded

- File-edit family work already covered by the March 10 contract/fidelity plans.
- GitLab and MCP dynamic tool work already covered by their dedicated plans.
- Repo-wide lint cleanup outside files touched by this slice.

## Design Decisions And Rationale

### 1. Close write-path modeling gaps before schema cleanup

`concat_files` currently creates files without participating in the normal
TRUSTED confirmation/write-allowance model. That is the highest-severity item
in this slice and lands first.

### 2. Keep strict unknown-arg rejection consistent across the remaining built-ins

The file-edit, nexus, shell, clipboard-management, and GitLab families already
fail closed on unexpected top-level args. The remaining built-ins should match
that contract instead of silently filtering typoed fields.

### 3. Prefer deterministic refusal over lossy text corruption

For clipboard file manipulation and read-oriented text tools, silently decoding
invalid UTF-8 with replacement characters is misleading. These tools should
refuse invalid UTF-8 inputs rather than rewrite or surface corrupted text.

## Implementation Details

### Phase 1: `concat_files` write-path hardening

Files:

- `nexus3/skill/builtin/concat_files.py`
- `nexus3/session/path_semantics.py`
- `nexus3/session/enforcer.py`
- `nexus3/core/policy.py`
- `tests/security/test_multipath_confirmation.py`
- `tests/unit/session/test_enforcer.py`

Work:

- model `concat_files` as a path-bearing tool in shared semantics
- derive the generated output file path when `dry_run=false`
- ensure TRUSTED confirmation and write allowances apply to that output path
- keep `dry_run=true` read-only

### Phase 2: strict schema hardening for the remaining built-ins

Files:

- `nexus3/skill/builtin/concat_files.py`
- `nexus3/skill/builtin/file_info.py`
- `nexus3/skill/builtin/glob_search.py`
- `nexus3/skill/builtin/grep.py`
- `nexus3/skill/builtin/list_directory.py`
- `nexus3/skill/builtin/tail.py`
- `nexus3/skill/builtin/clipboard_copy.py`
- `nexus3/skill/builtin/clipboard_paste.py`
- `nexus3/skill/builtin/clipboard_search.py`
- `nexus3/skill/builtin/clipboard_tag.py`
- `nexus3/skill/builtin/clipboard_export.py`
- `nexus3/skill/builtin/clipboard_import.py`
- `tests/unit/skill/test_skill_validation.py`
- `tests/unit/skill/test_clipboard_skills.py`
- `tests/unit/skill/test_clipboard_extras.py`

Work:

- set `additionalProperties: false` on the remaining fixed-schema built-ins
- update stale validation tests that still assert silent filtering
- add family-level unknown-arg rejection coverage

### Phase 3: text-fidelity and import-contract hardening

Files:

- `nexus3/skill/builtin/tail.py`
- `nexus3/skill/builtin/concat_files.py`
- `nexus3/skill/builtin/clipboard_copy.py`
- `nexus3/skill/builtin/clipboard_paste.py`
- `nexus3/skill/builtin/clipboard_import.py`
- `tests/unit/test_new_skills.py`
- `tests/unit/skill/test_concat_files.py`
- `tests/unit/skill/test_clipboard_skills.py`
- `tests/unit/skill/test_clipboard_extras.py`

Work:

- reject non-UTF8 input in `tail`
- treat invalid-UTF8 files as skipped/unreadable in `concat_files`
- reject non-UTF8 source/target files in `copy`, `cut`, and `paste`
- validate `clipboard_import` top-level shape, per-entry shape, and field types

## Testing Strategy

- run focused `ruff check` on touched runtime/test/doc files
- run focused pytest coverage for:
  - session/path confirmation behavior
  - strict validation behavior
  - non-UTF8 refusal and malformed import handling
- run `git diff --check` before closeout

## Implementation Checklist

- [x] Record remaining built-in audit findings and bounded hardening scope.
- [x] Phase 1: harden `concat_files` confirmation/path semantics.
- [x] Phase 2: enforce strict top-level schemas across the remaining built-ins.
- [x] Phase 3: close non-UTF8 corruption and malformed import gaps.
- [x] Sync status/docs for the shipped contract changes.
- [x] Run focused validation and record results.

## Documentation Updates

- Update `docs/plans/README.md` to index this plan.
- Update `AGENTS.md` running status with the active phase and findings.
- Sync `README.md`, `nexus3/skill/README.md`, `AGENTS_NEXUS3SKILLSCAT.md`, and
  `CLAUDE.md` for user-visible tool-contract changes.

## Validation Results

- `git diff --check`
- `.venv/bin/ruff check nexus3/core/policy.py nexus3/session/enforcer.py nexus3/session/path_semantics.py nexus3/skill/builtin/clipboard_copy.py nexus3/skill/builtin/clipboard_export.py nexus3/skill/builtin/clipboard_import.py nexus3/skill/builtin/clipboard_paste.py nexus3/skill/builtin/clipboard_search.py nexus3/skill/builtin/clipboard_tag.py nexus3/skill/builtin/concat_files.py nexus3/skill/builtin/file_info.py nexus3/skill/builtin/glob_search.py nexus3/skill/builtin/grep.py nexus3/skill/builtin/list_directory.py nexus3/skill/builtin/tail.py tests/security/test_multipath_confirmation.py tests/unit/session/test_enforcer.py tests/unit/skill/test_clipboard_extras.py tests/unit/skill/test_clipboard_skills.py tests/unit/skill/test_concat_files.py tests/unit/skill/test_skill_validation.py tests/unit/test_new_skills.py tests/unit/test_permissions.py`
- `.venv/bin/pytest -q tests/unit/skill/test_skill_validation.py tests/unit/skill/test_clipboard_skills.py tests/unit/skill/test_clipboard_extras.py tests/unit/test_new_skills.py tests/unit/skill/test_concat_files.py tests/unit/session/test_enforcer.py tests/security/test_multipath_confirmation.py tests/unit/test_permissions.py` (`387 passed`)
