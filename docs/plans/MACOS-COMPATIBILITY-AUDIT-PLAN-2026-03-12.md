# macOS Compatibility Audit Plan (2026-03-12)

## Overview

Audit the current Linux/Unix-default behavior for macOS compatibility and fix
the most likely real user pain points without requiring live Mac hardware.

This slice focuses on areas where "generic Unix" behavior is likely to diverge
from actual macOS expectations:

- REPL external-editor preview behavior
- shell selection for `shell_UNSAFE`
- related documentation and regression coverage

## Scope

Included:

- audit current macOS-relevant code paths in REPL/editor and execution tools
- make REPL external-editor preview behave sensibly on macOS by default
- parse `VISUAL` / `EDITOR` as real command vectors instead of raw strings
- add explicit `zsh` support to `shell_UNSAFE`
- make Unix `shell_UNSAFE(shell="auto")` prefer a supported host shell on macOS
  instead of silently defaulting to `/bin/sh` when a better match is available
- add focused unit coverage for the above behavior
- update current-facing docs

Deferred:

- live macOS terminal validation
- filesystem case-sensitivity hardening for case-insensitive APFS volumes
- macOS-specific packaging/distribution work
- GUI/clipboard integration outside the existing REPL preview path

Excluded:

- provider/runtime changes unrelated to platform execution
- Windows or WSL behavior changes except where shared logic needs small updates
- large terminal abstraction rewrites

## Design Decisions And Rationale

### 1. Treat macOS as a first-class Unix variant where user expectations differ

Behavior:

- keep the generic Unix path where it is already correct
- add targeted macOS handling where the current fallback is technically
  functional but clearly not user-friendly

Rationale:

- this keeps the slice small and avoids speculative platform churn
- the goal is to remove likely pain points, not invent a separate macOS stack

### 2. Parse editor environment variables as shell-style command vectors

Behavior:

- `VISUAL` / `EDITOR` values are split with shell-style parsing
- examples like `code --wait` and `open -W -n -a TextEdit` should work

Rationale:

- treating the full env var as one executable path is incorrect on Unix/macOS
- this is low-risk and improves all non-Windows hosts

### 3. Default REPL preview editor should feel native on macOS

Behavior:

- when no editor env var is set, macOS uses `open` with TextEdit in a blocking
  mode instead of falling back to pagers like `less` / `cat`

Rationale:

- the current pager fallback works, but it is not a good default editor
- TextEdit is present on macOS and is a more natural fit for popup-style preview

### 4. `shell_UNSAFE(shell="auto")` should not mean "/bin/sh regardless of host"

Behavior:

- explicit `zsh` is added as a supported shell family
- on Unix, `auto` prefers a known host shell from `$SHELL` when it maps cleanly
  to a supported shell family
- on macOS, this means the common `/bin/zsh` setup works as expected
- unknown shell families still fall back to the old generic shell path

Rationale:

- macOS users commonly expect zsh semantics
- retaining a safe fallback avoids overfitting to arbitrary shell implementations

## Implementation Details

Primary files:

- `nexus3/cli/editor_preview.py`
- `nexus3/skill/builtin/bash.py`

Regression coverage:

- `tests/unit/cli/test_editor_preview.py`
- `tests/unit/skill/test_bash_unix_behavior.py`

Supporting docs:

- `README.md`
- `nexus3/cli/README.md`
- `nexus3/skill/README.md`
- `nexus3/defaults/NEXUS-DEFAULT.md`
- `AGENTS.md`
- `docs/plans/README.md`

Implementation notes:

- add small helpers for editor command parsing and macOS default editor
- keep Windows behavior unchanged
- keep Unix shell fallback behavior available for unsupported `$SHELL` values
- document that `shell_UNSAFE(shell="auto")` follows a supported host shell
  when possible and that `zsh` is explicitly available

## Testing Strategy

Focused unit coverage should confirm:

- `VISUAL` / `EDITOR` values with arguments are parsed correctly
- macOS default editor resolution prefers a blocking `open`/TextEdit path
- macOS editor preview uses the expected subprocess path
- explicit `shell="zsh"` works on Unix hosts
- macOS/Unix `shell="auto"` honors supported `$SHELL` values such as zsh
- unsupported Unix `$SHELL` values still fall back cleanly

Validation:

- focused `ruff`
- focused `mypy`
- focused `pytest`
- `git diff --check`

## Documentation Updates

- add and index the plan doc
- update CLI/editor preview docs
- update skill/default prompt docs for `shell_UNSAFE`
- record the current slice in `AGENTS.md`

## Checklist

- [x] Add and index the plan doc.
- [x] Implement macOS editor-preview improvements.
- [x] Implement Unix/macOS shell selection improvements.
- [x] Add focused regression coverage.
- [x] Sync current-facing docs and running-status notes.
- [x] Run focused validation.

Validation completed:

- `.venv/bin/pytest -q tests/unit/cli/test_editor_preview.py tests/unit/skill/test_bash_unix_behavior.py tests/unit/skill/test_bash_windows_behavior.py` (`14 passed`)
- `.venv/bin/pytest -q tests/unit/test_repl_commands.py -k 'tool_opens_editor'` (`1 passed, 82 deselected`)
- `.venv/bin/ruff check nexus3/cli/editor_preview.py nexus3/skill/builtin/bash.py tests/unit/cli/test_editor_preview.py tests/unit/skill/test_bash_unix_behavior.py tests/unit/skill/test_bash_windows_behavior.py README.md nexus3/cli/README.md nexus3/skill/README.md nexus3/defaults/NEXUS-DEFAULT.md docs/plans/README.md docs/plans/MACOS-COMPATIBILITY-AUDIT-PLAN-2026-03-12.md AGENTS.md`
- `.venv/bin/mypy nexus3/cli/editor_preview.py nexus3/skill/builtin/bash.py`
- `git diff --check`

Residual audit notes:

- Core process management, ESC monitoring, and generic Unix subprocess
  handling still look reasonable for macOS based on static review.
- The biggest remaining unverified area is path/security behavior on
  case-insensitive APFS volumes; current path normalization still treats
  non-Windows hosts as case-sensitive.
- Live macOS terminal validation is still deferred.
