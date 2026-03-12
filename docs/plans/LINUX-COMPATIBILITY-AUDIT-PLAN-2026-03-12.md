# Linux Compatibility Audit Plan (2026-03-12)

## Overview

Audit Linux-specific and generic-Unix behavior after the macOS compatibility
slice, with special attention to whether the mac-focused shell changes
accidentally altered established Linux semantics.

The goal is to preserve good Linux behavior, keep the cross-platform fixes that
are real improvements, and only change Linux behavior where there is a clear
reason.

## Scope

Included:

- audit Linux-specific and generic-Unix code paths affected by the macOS slice
- decide whether the new `shell_UNSAFE(shell="auto")` behavior is acceptable on
  Linux or should be scoped back down
- keep the cross-platform `VISUAL` / `EDITOR` parsing improvement if it is
  Linux-safe
- add focused Linux regression coverage
- update current-facing docs and running status

Deferred:

- live distro-by-distro validation
- Linux desktop-specific editor integration beyond the current REPL preview path
- deeper shell-family expansion beyond the current supported set
- distribution-specific service/packaging integration

Excluded:

- macOS-only GUI behavior changes
- Windows-specific runtime changes
- unrelated terminal or provider behavior

## Design Decisions And Rationale

### 1. Linux should keep its prior `shell_UNSAFE(auto)` contract unless there is a compelling reason to change it

Behavior:

- Linux `shell_UNSAFE(shell="auto")` should continue using the generic shell
  execution path rather than following `$SHELL`
- macOS can retain the host-shell-aware `auto` behavior introduced for zsh

Rationale:

- the earlier macOS fix solved a real user-expectation mismatch
- Linux hosts have more varied shell setups, so changing `auto` there is a
  larger semantic shift with less clear payoff
- preserving old Linux behavior minimizes regression risk

### 2. Cross-platform editor env parsing stays

Behavior:

- `VISUAL` / `EDITOR` command parsing remains enabled on Linux

Rationale:

- values like `code --wait` are common on Linux too
- this is a real correctness fix, not a platform-specific preference

## Implementation Details

Primary files:

- `nexus3/skill/builtin/bash.py`

Regression coverage:

- `tests/unit/skill/test_bash_unix_behavior.py`

Supporting docs:

- `README.md`
- `nexus3/skill/README.md`
- `nexus3/defaults/NEXUS-DEFAULT.md`
- `AGENTS.md`
- `docs/plans/README.md`

Implementation notes:

- keep explicit `shell="zsh"` support
- scope the host-shell-aware auto-shell resolution to macOS only
- add a Linux regression test that asserts `auto` still uses the generic shell
  path even when `$SHELL` is set to a supported shell

## Testing Strategy

Focused coverage should confirm:

- Linux `shell_UNSAFE(shell="auto")` still uses the generic shell path
- macOS `shell_UNSAFE(shell="auto")` still prefers zsh when appropriate
- explicit Unix `shell="zsh"` still works
- the earlier editor-preview regression coverage still passes

Validation:

- focused `pytest`
- focused `ruff`
- focused `mypy`
- `git diff --check`

## Documentation Updates

- add and index the plan doc
- update shell docs to describe macOS-specific `auto` behavior accurately
- record the active Linux audit slice in `AGENTS.md`

## Checklist

- [x] Add and index the plan doc.
- [x] Scope Unix host-shell-aware auto mode back to macOS only.
- [x] Add focused Linux regression coverage.
- [x] Sync docs and running-status notes.
- [x] Run focused validation.

Validation completed:

- `.venv/bin/pytest -q tests/unit/skill/test_bash_unix_behavior.py tests/unit/skill/test_bash_windows_behavior.py` (`12 passed`)
- `.venv/bin/pytest -q tests/unit/cli/test_editor_preview.py tests/unit/test_repl_commands.py -k 'tool_opens_editor'` (`1 passed, 84 deselected`) plus the earlier editor-preview focused coverage still passing
- `.venv/bin/ruff check nexus3/skill/builtin/bash.py tests/unit/skill/test_bash_unix_behavior.py tests/unit/skill/test_bash_windows_behavior.py nexus3/cli/editor_preview.py tests/unit/cli/test_editor_preview.py README.md nexus3/defaults/NEXUS-DEFAULT.md docs/plans/README.md docs/plans/LINUX-COMPATIBILITY-AUDIT-PLAN-2026-03-12.md AGENTS.md`
- `.venv/bin/mypy nexus3/skill/builtin/bash.py nexus3/cli/editor_preview.py`
- `git diff --check`

Residual audit notes:

- The earlier cross-platform `VISUAL` / `EDITOR` parsing fix remains a net
  improvement for Linux and does not require special scoping.
- Generic Unix process termination, key monitoring, and subprocess execution
  still look reasonable for Linux based on static review.
- The remaining Linux risk is normal distro/environment variance rather than an
  obvious code-path defect found in this pass.
