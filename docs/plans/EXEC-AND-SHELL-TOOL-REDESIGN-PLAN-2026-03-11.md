# Exec And Shell Tool Redesign Plan (2026-03-11)

## Overview

NEXUS3 currently exposes two execution-oriented shell tools with confusing
naming and uneven permission UX:

- `bash_safe`: direct subprocess execution with `shlex.split()` and no shell
  interpretation
- `shell_UNSAFE`: full shell execution with platform-dependent shell-family
  selection

This slice replaces the misleading safe-tool naming with a canonical `exec`
tool, makes the safe tool contract explicit and non-shell, adds explicit shell
selection to `shell_UNSAFE`, and narrows TRUSTED-mode "allow always" behavior
for the safe tool to command-specific directory allowances.

## Scope

### Included

- Replace `bash_safe` with canonical `exec`
- Remove legacy `bash` / `bash_safe` compatibility from runtime behavior,
  schemas, tests, and docs
- Redesign safe execution parameters to an explicit non-shell contract
- Add explicit `shell=` selection to `shell_UNSAFE`
- Replace tool-wide safe-exec allowances with command-specific directory
  allowances
- Update confirmation UI, policy logic, docs, and tests to the new standard

### Deferred

- Broader redesign of `run_python`
- New filtering/policy layers that semantically classify executables as
  "dangerous" or "safe" beyond the existing permission model
- Prompt-guidance cleanup for specific command families such as search/grep
  workflows

### Excluded

- Backward compatibility for saved sessions, historical tool names, or old
  execution allowances
- Transition aliases for `bash`, `bash_safe`, or string-based safe-exec input
- Any attempt to make `shell_UNSAFE` eligible for persistent "allow always"
  approval

## Design Decisions And Rationale

### 1. Canonical safe tool name is `exec`

The current name `bash_safe` is misleading because the tool does not run a
shell. It performs direct subprocess execution without shell interpretation.
The new standard should name the tool after what it actually does.

### 2. `exec` uses structured non-shell parameters

The new safe tool contract should be explicit:

- `program: string`
- `args: string[]` (default empty)
- `cwd?: string`
- `timeout?: integer`

This removes shell-style parsing ambiguity, makes the executable identity
explicit, and gives permissions/confirmation a precise object to reason about.

### 3. `shell_UNSAFE` keeps string `command`, but gains explicit `shell=`

`shell_UNSAFE` exists specifically for shell syntax and should continue to take
one shell command string. It should add an explicit:

- `shell?: "auto" | "bash" | "gitbash" | "powershell" | "pwsh" | "cmd"`

Unsupported or unavailable requested shells must fail closed. Tool results and
logs should expose the shell family actually used.

### 4. Safe-exec allowances become command-specific and directory-scoped

The current allowance model stores execution permissions by tool name, which is
too broad for a generic execution tool. The new model should store allowances
for a normalized executable identity and only for the current directory scope.

For `exec`, the approval boundary is:

- resolved executable path when it can be determined safely
- otherwise a normalized `program` fallback string

Global "allow everywhere" should not be offered for `exec`.

### 5. `shell_UNSAFE` remains per-use only

The unsafe shell has too much semantic ambiguity to safely support persistent
allowances. Pipes, aliases, shell functions, subshells, and shell-specific
syntax make "allow this command always" an unreliable security boundary.

### 6. `run_python` remains a separate high-risk tool

`run_python` already performs direct `sys.executable -c ...` execution without
shell interpretation, but its trust model is different enough that this slice
should not merge it into `exec` or reuse the new command-specific allowance
logic.

### 7. No transition layer

The user explicitly approved a clean break. The implementation should remove
the old standard rather than carrying aliases, dual schemas, or migration code.

## Implementation Details

### Phase 1: safe execution API reshape

Files:

- `nexus3/skill/builtin/bash.py`
- `nexus3/skill/builtin/registration.py`
- `nexus3/session/enforcer.py`
- `nexus3/config/schema.py`

Work:

- replace the current safe execution tool with canonical `exec`
- remove `bash_safe` and legacy `bash` naming from skill registration and
  permission-sensitive tool lists
- change the safe execution schema from `command: str` to explicit
  `program` + `args`
- keep direct subprocess execution with sanitized environment, cwd validation,
  timeout enforcement, and process-tree termination
- update configuration/tool permission surfaces that still name the old tool

Implementation note:

- if filesystem churn is acceptable, rename
  `nexus3/skill/builtin/bash.py` to a clearer module such as
  `nexus3/skill/builtin/execution.py`; otherwise keep the file path and change
  the exported skill names only

### Phase 2: executable identity and allowance model

Files:

- `nexus3/core/allowances.py`
- `nexus3/core/policy.py`
- `nexus3/core/permissions.py`
- `nexus3/session/confirmation.py`
- `nexus3/cli/confirmation_ui.py`
- `nexus3/session/enforcer.py`
- new shared helper module under `nexus3/core/` for executable identity

Work:

- replace tool-wide safe-exec allowances with command-specific allowances
- add shared normalization/resolution for executable identity:
  - resolve against the effective executable search path when possible
  - case-fold/normalize on Windows
  - fall back to normalized `program` if resolution is unavailable
- store only directory-scoped allowances for `exec`
- remove unused global safe-exec allowance behavior from `exec`
- keep `shell_UNSAFE` approval as allow-once or deny only

### Phase 3: explicit shell selection for `shell_UNSAFE`

Files:

- `nexus3/skill/builtin/bash.py`
- `nexus3/core/shell_detection.py`
- `tests/unit/skill/test_bash_windows_behavior.py`

Work:

- add `shell=` enum support to `shell_UNSAFE`
- map each requested shell family to explicit process creation:
  - `auto`: preserve the best-available current-family selection logic
  - `bash`: explicit bash family
  - `gitbash`: explicit Git-for-Windows bash path resolution
  - `powershell`: Windows PowerShell
  - `pwsh`: PowerShell 7+
  - `cmd`: `cmd.exe`
- fail closed when the requested shell is unavailable on the current host
- include the resolved shell family in debug/logging surfaces and user-facing
  output where practical

### Phase 4: UI, docs, and prompt guidance sync

Files:

- `nexus3/defaults/NEXUS-DEFAULT.md`
- `nexus3/skill/README.md`
- `nexus3/session/README.md`
- `nexus3/cli/README.md`
- `README.md`
- `CLAUDE.md`
- `AGENTS.md`
- `AGENTS_NEXUS3SKILLSCAT.md`

Work:

- update all tool tables and usage guidance to `exec`
- explain clearly that `exec` is non-shell direct process execution and should
  be preferred when shell syntax is not required
- explain that `shell_UNSAFE` is the explicit shell-syntax tool and now takes
  `shell=`
- update confirmation wording to:
  - preview `program` separately from `args`
  - offer `allow once`, `allow this command in this directory`, `deny` for
    `exec`
  - keep `allow once`, `deny` for `shell_UNSAFE`

### Phase 5: test and validation closeout

Files:

- `tests/security/test_p2_defense_in_depth.py`
- `tests/unit/test_permissions.py`
- `tests/unit/cli/test_confirmation_ui_safe_sink.py`
- `tests/unit/skill/test_bash_windows_behavior.py`
- `tests/unit/provider/test_streaming_tool_calls.py`
- any provider/session fixture tests that still refer to `bash` / `bash_safe`

Work:

- update all tool-name references to `exec`
- replace string-command safe-exec fixtures with `program` + `args`
- add explicit tests for command-scoped allowance identity behavior
- add explicit tests for `shell_UNSAFE(shell=...)` success/fail-closed paths
- verify `run_python` remains unchanged

## Testing Strategy

- targeted Ruff:
  - `.venv/bin/ruff check nexus3/ tests/`
- targeted pytest for the touched execution, permission, confirmation, and
  provider-fixture clusters
- full suite closeout because the tool-name and schema changes are broad:
  - `.venv/bin/pytest tests/ -q`
- live validation because this slice changes skills and permission UX:
  - start a local NEXUS3 server/session
  - confirm `exec` appears instead of `bash_safe`
  - confirm TRUSTED-mode `exec` prompts use command-specific directory
    allowance wording
  - confirm `shell_UNSAFE(shell=...)` routes through the requested shell or
    fails closed if unavailable

## Implementation Checklist

- [x] Replace `bash_safe` with canonical `exec`.
- [x] Redesign safe execution input to `program` + `args`.
- [x] Remove legacy `bash` / `bash_safe` compatibility code and references.
- [x] Add normalized executable-identity helpers for `exec`.
- [x] Replace tool-wide safe-exec allowances with command-specific
      directory allowances.
- [x] Add `shell=` enum support to `shell_UNSAFE`.
- [x] Update confirmation UI wording and option sets.
- [x] Sync docs and prompt guidance to the new standard.
- [x] Re-run Ruff, targeted pytest, full pytest, and live validation.

## Validation Results

- `.venv/bin/ruff check nexus3/ tests/`
- Focused pytest slice:
  `.venv/bin/pytest -q tests/unit/core/test_executable_identity.py tests/security/test_p0_env_sanitization.py tests/security/test_p2_defense_in_depth.py tests/unit/cli/test_confirmation_ui_safe_sink.py tests/unit/skill/test_bash_windows_behavior.py tests/unit/skill/test_skill_validation.py tests/unit/test_permissions.py tests/unit/provider/test_streaming_tool_calls.py tests/unit/test_git_context.py tests/unit/test_gitlab_toggle.py tests/unit/rpc/test_pool_create_auth_shadow.py tests/unit/test_repl_commands.py tests/unit/session/test_enforcer.py`
  (`360 passed`)
- Full pytest:
  `.venv/bin/pytest tests/ -q`
  (`4392 passed, 3 skipped, 21 warnings`)
- Live validation:
  - started local RPC server with `NEXUS_DEV=1 .venv/bin/python -m nexus3 --serve 9000`
  - created trusted agent via RPC
  - confirmed a real agent turn described execution tools as:
    - `exec(program, args?, timeout?, cwd?)`
    - `shell_UNSAFE(command, shell?, timeout?, cwd?)`
    - `run_python(code, timeout?, cwd?)`
  - confirmed a trusted `exec` attempt through RPC was blocked pending user approval
    (`Action cancelled by user` path), which matches the intended confirmation gate

## Documentation Updates

- Add this plan to `docs/plans/README.md`.
- Update the shell/execution sections in:
  - `nexus3/defaults/NEXUS-DEFAULT.md`
  - `nexus3/skill/README.md`
  - `nexus3/session/README.md`
  - `nexus3/cli/README.md`
  - `README.md`
  - `CLAUDE.md`
  - `AGENTS.md`
  - `AGENTS_NEXUS3SKILLSCAT.md`
