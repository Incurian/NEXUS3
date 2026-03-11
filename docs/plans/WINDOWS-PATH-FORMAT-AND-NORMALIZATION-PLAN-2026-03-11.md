# Windows Path Format And Normalization Plan (2026-03-11)

## Overview

Clarify the canonical tool-path format for Windows users and add a small amount
of shared path normalization so common Windows-adjacent path shapes are
accepted more reliably.

Today the shared resolver already normalizes backslashes to forward slashes,
but the current docs are broader and fuzzier than the actual runtime contract.
In particular, the docs imply more Git Bash path interchangeability than the
shared resolver explicitly guarantees.

This plan keeps the preferred standard simple while adding only the narrowest
safe compatibility rewrites in the shared path kernel.

## Scope

Included:

- state the preferred Windows tool-path format explicitly in current-facing
  docs
- keep the preferred rule host-native and forward-slash based
- add shared native-Windows compatibility rewrites for:
  - Git Bash drive paths like `/d/Repo/file.txt`
  - WSL-style mount paths like `/mnt/d/Repo/file.txt`
- ensure file-path tools and `cwd` resolution benefit consistently because they
  share the same path kernel
- add focused unit coverage for the shared path normalization helper

Deferred:

- broader path-dialect guessing beyond the narrow common cases above
- host-to-host translation outside native Windows
- shell-specific special cases outside the shared resolver

Excluded:

- changing the preferred tool-path standard away from forward slashes
- adding per-tool path-format rules
- any dependency changes

## Design Decisions And Rationale

### 1. Preferred format stays host-native absolute paths with forward slashes

Behavior:

- on native Windows, prefer `D:/Repo/file.txt`
- on Linux/WSL, prefer native POSIX paths such as `/mnt/d/Repo/file.txt` or
  `/home/user/...`

Rationale:

- one canonical format is easier to teach than shell-specific variants
- forward slashes avoid JSON escaping problems
- host-native paths avoid ambiguous cross-environment guessing

### 2. Compatibility rewrites remain narrow and host-gated

Behavior:

- native Windows accepts `/d/...` and `/mnt/d/...` as compatibility input
- UNC paths like `//server/share/...` are preserved
- non-Windows hosts do not attempt broad Windows-dialect rewrites

Rationale:

- these are the most common safe conversions
- broader heuristics are harder to reason about and easier to misfire

### 3. Shared path kernel owns the behavior

Behavior:

- normalize in `nexus3/core/paths.py`
- file-path tools and `resolve_cwd()` inherit the same conversion rules via the
  shared path decision engine

Rationale:

- one implementation path keeps behavior consistent and testable

## Implementation Details

Primary files:

- `nexus3/core/paths.py`
- `tests/unit/core/test_paths_windows.py`

Supporting docs:

- `nexus3/defaults/NEXUS-DEFAULT.md`
- `README.md`
- `nexus3/core/README.md`
- `CLAUDE.md`
- `AGENTS.md`
- `docs/plans/README.md`

## Testing Strategy

Focused coverage should confirm:

- backslash normalization still works
- native-Windows compatibility rewrites accept `/d/...` and `/mnt/d/...`
- UNC paths are preserved
- non-Windows hosts do not apply the Windows-only rewrites

Validation:

- focused `ruff`
- focused pytest for core Windows path normalization
- `git diff --check`

## Documentation Updates

- centralize the preferred Windows tool-path format as forward-slash absolute
  drive-letter paths on native Windows
- document compatibility rewrites as convenience input, not the preferred form

## Checklist

- [x] Add and index the plan doc.
- [x] Clarify the preferred Windows path format in current-facing docs.
- [x] Add narrow shared compatibility rewrites in the path kernel.
- [x] Add focused unit coverage.
- [x] Run focused validation.

Validation completed:

- `.venv/bin/ruff check nexus3/core/paths.py tests/unit/core/test_paths_windows.py tests/security/test_p2_exec_cwd_normalization.py tests/security/test_p2_blocked_paths.py README.md CLAUDE.md AGENTS.md nexus3/core/README.md nexus3/defaults/NEXUS-DEFAULT.md docs/plans/README.md docs/plans/WINDOWS-PATH-FORMAT-AND-NORMALIZATION-PLAN-2026-03-11.md`
- `.venv/bin/pytest -q tests/unit/core/test_paths_windows.py tests/security/test_p2_exec_cwd_normalization.py tests/security/test_p2_blocked_paths.py` (`40 passed`)
- `git diff --check`
