# Search Text Rename Plan (2026-03-11)

## Overview

Rename the built-in content-search tool from `grep` to `search_text` without
changing its search behavior or parameter contract.

The goal is to reduce shell-shaped model priors. The built-in tool is already
the preferred content-search path, but the name `grep` keeps encouraging shell
`grep` / `rg` habits and makes the built-in tool look more CLI-like than it is.

## Scope

Included:

- change the canonical built-in tool name from `grep` to `search_text`
- keep the existing parameter contract and behavior:
  - `pattern`
  - `path`
  - `recursive?`
  - `ignore_case?`
  - `max_matches?`
  - `include?`
  - `context?`
- update registration, policy/path semantics, tests, prompts, and user-facing
  docs
- update current running-status notes to reflect the rename

Deferred:

- any behavior changes to the search backend
- fuzzy search
- explicit multi-path search support
- renaming the module file `nexus3/skill/builtin/grep.py`

Excluded:

- backward-compat aliases for `grep`
- changing ripgrep fallback behavior

## Design Decisions And Rationale

### 1. Public tool name changes, implementation file can stay put

Canonical public name:

- `search_text`

Rationale:

- the user-facing contract is what shapes agent behavior
- keeping the module filename as `grep.py` avoids churn where the internal file
  name is not externally meaningful

### 2. No behavior change

The tool should keep the current single-path contract:

- one `path`
- that path may be a file or a directory
- directory mode may search many files

Rationale:

- the requested change is naming and guidance, not capability expansion
- this keeps the rename low-risk and easy to validate

### 3. No backward-compat alias

Behavior:

- built-in registration should expose `search_text`
- current-facing docs should teach `search_text`
- tests and references should be updated to the new name

Rationale:

- keeping both names would prolong shell-priming and muddy the canonical tool
  guidance

## Implementation Details

Primary files:

- `nexus3/skill/builtin/grep.py`
- `nexus3/skill/builtin/registration.py`
- `nexus3/session/path_semantics.py`
- `nexus3/core/policy.py`
- `nexus3/session/enforcer.py`

Likely supporting files:

- search-related tests
- permission/path-semantics tests
- current-facing docs:
  - `README.md`
  - `nexus3/defaults/NEXUS-DEFAULT.md`
  - `nexus3/skill/README.md`
  - `CLAUDE.md`
  - `AGENTS_NEXUS3SKILLSCAT.md`
  - `AGENTS.md`

## Testing Strategy

Focused coverage should confirm:

- the tool registers as `search_text`
- path semantics and permission logic recognize `search_text`
- existing content-search tests still pass under the new name
- docs/examples no longer teach built-in `grep` as the canonical tool

Validation:

- focused `ruff`
- focused pytest slices for grep/search tool behavior and permission wiring
- one live RPC check showing an agent can describe and use `search_text`

## Documentation Updates

- replace current-facing built-in `grep` references with `search_text`
- keep shell guidance explicit:
  - prefer built-in `search_text` over shell `grep` / `rg`
- historical notes in archived execution logs may retain `grep` when clearly
  historical

## Checklist

- [x] Add plan/index/status tracking for the rename.
- [x] Rename the canonical built-in tool from `grep` to `search_text`.
- [x] Update policy/path-semantics/permission wiring.
- [x] Update focused tests.
- [x] Sync current-facing docs and prompts.
- [x] Run focused validation and a live RPC check.

Validation completed:

- `.venv/bin/ruff check nexus3/skill/builtin/grep.py nexus3/skill/builtin/registration.py nexus3/session/path_semantics.py nexus3/core/policy.py nexus3/session/enforcer.py nexus3/config/schema.py nexus3/skill/base.py README.md CLAUDE.md AGENTS.md AGENTS_NEXUS3SKILLSCAT.md nexus3/defaults/NEXUS-DEFAULT.md nexus3/skill/README.md nexus3/config/README.md nexus3/session/README.md nexus3/display/README.md nexus3/display/printer.py tests/unit/test_skill_enhancements.py tests/unit/skill/test_grep_parallel.py tests/unit/skill/test_grep_gateway.py tests/unit/skill/test_skill_validation.py tests/unit/test_git_context.py tests/unit/test_error_sanitization.py tests/security/test_multipath_confirmation.py tests/security/test_p2_file_size_limits.py`
- `.venv/bin/mypy nexus3/skill/builtin/grep.py`
- `.venv/bin/pytest -q tests/unit/test_skill_enhancements.py tests/unit/skill/test_grep_parallel.py tests/unit/skill/test_grep_gateway.py tests/unit/skill/test_skill_validation.py tests/unit/test_git_context.py tests/unit/test_error_sanitization.py tests/security/test_multipath_confirmation.py tests/security/test_p2_file_size_limits.py` (`257 passed`)
- live RPC validation on port `9000`:
  - trusted agent described built-in `search_text` with the updated public name
  - the same agent successfully called `search_text(pattern='Search Text Rename Plan', path='/home/inc/repos/NEXUS3/docs/plans/SEARCH-TEXT-RENAME-PLAN-2026-03-11.md')` and reported a real match
