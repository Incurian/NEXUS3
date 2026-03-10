# Post-Arch Bugfix Hardening Plan (2026-03-10)

## Overview

Architecture execution on `feat/arch-overhaul-execution` is complete enough to stop treating architecture work as the active backlog. Since that closeout, follow-on manual testing and tool audits uncovered a separate hardening backlog spanning:

- file-editing tool safety and contract drift
- agent misuse traps around `read_file` / `outline` / `patch`
- Windows Git Bash shell correctness (`shell_UNSAFE` launching WSL)
- Windows Git Bash REPL input correctness (ESC cancellation and multiline paste)

Two immediate post-architecture bugs are already fixed and are not part of this plan's open backlog:

- `be68552` `fix(cli): avoid rich markup crash in confirmation ui`
- `1522581` `fix(skill): treat blank nexus_create message as omitted`

This plan defines the remaining post-architecture bugfix/hardening work as a focused follow-on stream rather than reopening the architecture plan.

## Scope

### Included

- Close file-editing security gaps for `edit_lines` and `patch` in RPC sandboxing, TRUSTED confirmation, and path semantics.
- Fix or explicitly re-spec incorrect file-tool behavior around batched edits, newline handling, encoding fidelity, and regex validation.
- Reduce agent misuse caused by mismatched tool contracts and under-specified docs, especially for `read_file`, `outline`, and `patch`.
- Fix Windows Git Bash `shell_UNSAFE` shell selection so Git-Bash-launched sessions do not jump into WSL.
- Fix or fail-closed/document Windows Git Bash REPL limitations around ESC cancellation and multiline paste.
- Update user-facing and internal docs so they match real behavior.
- Add focused automated coverage and live Windows validation for the affected behavior.

### Deferred

- Full redesign of the REPL input system if targeted Git Bash fixes are insufficient. The preferred path is a bounded hardening pass, not an unbounded TUI rewrite.
- Any new file-editing tool families or prompt redesign unrelated to the bugs already identified.
- Provider keep-alive evidence work; that remains a separate deferred operational item.
- Follow-up audit of repeated agent misuse of `outline` parameterization/contract
  after the current hardening stream. User-observed symptom: agents often fail
  to invoke `outline` correctly in practice even after the Phase 2 contract
  cleanup, so a later pass should inspect real transcripts/tool calls and decide
  whether the remaining issue is prompt guidance, schema ergonomics, or agent
  behavior.

### Excluded

- Architecture implementation backlog that was already closed out in March 2026.
- Already-fixed post-architecture bugfixes listed in the Overview.

## Design Decisions And Rationale

### 1. Fix safety holes before ergonomics

The highest-priority issues are permission/confirmation gaps that let `edit_lines` and `patch` bypass intended controls. Those are security-sensitive and should land before broader tool-contract cleanup.

### 2. Treat tool output shape as API

The current `read_file`, `outline`, and `patch` behaviors are internally coherent but not described precisely enough for agents. We should either make the contract explicit in code and docs or add compatibility-friendly aliases/flags where that reduces repeated misuse.

### 3. Prefer deterministic shell resolution on Windows

The confirmed WSL bug is caused by ambiguous `bash` resolution in the Windows `shell_UNSAFE` path. Windows shell-family dispatch must resolve the intended executable explicitly; bare `bash` is not acceptable here.

### 4. Stop treating API availability as live-validation success

The existing Windows validation marked ESC green by checking `msvcrt` availability, but real Git Bash behavior still failed. Live validation must exercise actual user interactions in Git Bash, not just library imports.

### 5. Fail closed for lossy text editing

For text-oriented edit tools, silent corruption of non-UTF8 files is worse than a deterministic refusal. If byte-fidelity cannot be guaranteed, the tool should fail and steer the agent toward `patch` byte-strict mode.

## Implementation Details

## Phase 1: File-Editing Safety And Permission Hardening

### Goals

- Close sandboxed and TRUSTED-mode loopholes around `edit_lines` and `patch`.
- Restore correct confirmation UI/path-allowance behavior.

### Concrete changes

- `nexus3/rpc/global_dispatcher.py`
  - Include `edit_lines` and `patch` in the sandboxed no-write-path disable set used for RPC child creation.
- `nexus3/core/presets.py`
  - Verify preset-level disabled tool maps align with the dispatcher override behavior.
- `nexus3/core/policy.py`
  - Add `edit_lines` and `patch` to destructive/write action gating so TRUSTED-mode outside-CWD writes require confirmation.
- `nexus3/session/path_semantics.py`
  - Add explicit semantics for `edit_lines` and `patch` so display-path extraction and allow-always persistence are correct.
- `nexus3/session/single_tool_runtime.py`
  - Ensure the updated path semantics are honored consistently during confirmation dispatch.
- `nexus3/cli/confirmation_ui.py`
  - Verify patch/edit-lines prompts show stable path data and correct menu choices.

### Tests

- `tests/unit/test_permissions.py`
- `tests/unit/test_global_dispatcher.py`
- `tests/unit/cli/test_confirmation_ui_safe_sink.py`
- add focused regressions for sandboxed RPC child permissions and TRUSTED-mode confirmation behavior

## Phase 2: File-Tool Contract And Agent-Ergonomics Corrections

### Goals

- Reduce repeated agent misuse of `read_file`, `outline`, `patch`, and batched `edit_file`.
- Make tool behavior match the written guidance.

### Concrete changes

- `nexus3/skill/builtin/read_file.py`
  - Preferred direction: add an explicit line-number control (`line_numbers` or equivalent compatibility-safe flag) so agents can request raw file text when exact-match editing or diff construction is needed.
  - If a code-path change is rejected, then tighten prompt/docs so numbered output is treated as an explicit view mode, not plain file content.
- `nexus3/skill/builtin/outline.py`
  - Return a clearer failure/fallback signal for unsupported file types instead of success-with-unhelpful-output.
  - Document or tighten the `symbol` mode behavior so it is clearly a numbered source excerpt, not a semantic outline.
- `nexus3/skill/builtin/patch.py`
  - Accept `path` as a compatibility alias for `target`.
  - Keep single-target semantics explicit.
  - Evaluate enabling new-file diffs at the skill boundary; if retained as unsupported, fail with precise guidance.
- `nexus3/skill/builtin/edit_file.py`
  - Implement true batch atomicity or explicitly reject batches that cannot be applied atomically against one stable input snapshot.

### Tests

- `tests/unit/skill/test_patch.py`
- `tests/unit/skill/test_outline.py`
- `tests/integration/test_file_editing_skills.py`
- add focused regressions for `read_file` raw/numbered behavior, patch aliasing, unsupported outline fallback, and atomic batch edit handling

### Current Progress (2026-03-10)

- Completed in the current branch:
  - `patch` now accepts valid new-file diffs when the target path does not yet exist.
  - `edit_file` batch mode now fails closed if earlier edits invalidate later edit targets in-memory.
  - `read_file` now supports `line_numbers=false` raw reads while keeping numbered output as the default.
  - `outline(symbol=...)` now honors `line_numbers=false`, and unsupported file types now explicitly direct callers to `read_file`.
  - follow-up `outline` audit first wave:
    - `outline` now accepts `file_type=` / `language=` parser overrides for files.
    - directory mode now honors `preview`, `signatures`, and `line_numbers`.
    - directory mode now rejects file-only `symbol` / parser-override parameters explicitly.
    - ambiguous `outline(symbol=...)` matches now fail closed instead of returning the first match silently.
  - follow-up `outline` audit second wave:
    - `outline` now accepts `parser=` as a compatibility alias for parser override.
    - directory mode keeps filesystem traversal non-recursive but now respects `depth` for nested symbols within each file.
    - `recursive=true` now fails closed with explicit guidance instead of being silently ignored.
    - `diff=true` now emits an explicit note when git diff context is unavailable.
    - directory diff marker matching now uses paths relative to the outlined directory, preventing nested same-basename changes from leaking onto immediate files.
  - `patch` now accepts `path=` as the preferred file argument while preserving
    `target=` as a compatibility alias, and mismatched `path` + `target`
    inputs fail closed.
  - patch permission/confirmation path extraction now runs through shared tool
    semantics, closing the previous `patch(target=...)` path-gating hole.
- Phase 2 is complete.
- Next gate:
  - Phase 3 newline / encoding / regex hardening.

## Phase 3: Text Fidelity, Newlines, And Regex Hardening

### Goals

- Remove silent or misleading behavior in text-edit tools.
- Make cross-OS text edits predictable.

### Concrete changes

- `nexus3/skill/builtin/edit_lines.py`
  - Preserve EOF newline state when replacing the last line if the original file ended with a newline.
- `nexus3/skill/builtin/append_file.py`
  - Fix CR-only trailing-newline detection.
  - Decide and implement explicit newline-write semantics instead of relying on implicit platform translation.
- `nexus3/skill/builtin/write_file.py`
  - Align write mode with the newline-fidelity decision from `append_file`.
- `nexus3/skill/builtin/edit_file.py`
- `nexus3/skill/builtin/edit_lines.py`
- `nexus3/skill/builtin/regex_replace.py`
  - Fail closed on non-UTF8 / undecodable text instead of `errors="replace"` lossy rewrites.
  - Direct agents toward `patch` byte-strict mode for byte-sensitive edits.
- `nexus3/skill/builtin/regex_replace.py`
  - Reject negative `count`.
  - Remove or soften timeout/safety claims that the current implementation cannot truly guarantee.

### Tests

- `tests/unit/skill/test_edit_lines.py`
- `tests/security/test_p2_append_file.py`
- `tests/unit/test_new_skills.py`
- `tests/unit/test_regex_replace_skill.py`
- add non-UTF8 refusal regressions for text-edit tools

### Current Progress (2026-03-10)

- Completed in the current branch:
  - `edit_lines` now preserves EOF newline state when replacing the last line of
    a file that already ended with a newline.
  - `append_file` now detects CR-only trailing newlines correctly and appends
    exact UTF-8 bytes without platform newline translation.
  - `write_file` now writes caller-provided newline bytes exactly through the
    shared atomic text-write helper.
  - `edit_file`, `edit_lines`, and `regex_replace` now fail closed on
    undecodable/non-UTF8 input and steer byte-sensitive edits to `patch`
    `fidelity_mode="byte_strict"`.
  - `regex_replace` now rejects negative `count` and softens its timeout claim
    to a best-effort local wait window.
  - focused regressions now cover non-UTF8 refusal, CR-only append handling,
    exact newline-write semantics, and the `regex_replace` negative-count path.
- Phase 3 is complete.
- Next gate:
  - Phase 5 Git Bash ESC + multiline-paste handling.

## Phase 4: Windows Git Bash Shell Correctness

### Goals

- Eliminate the confirmed case where `shell_UNSAFE` jumps from a native Windows NEXUS process into WSL.

### Concrete changes

- `nexus3/skill/builtin/bash.py`
  - Replace the Windows Git-Bash-family `bash -lc` launch with explicit Git-for-Windows bash resolution.
  - Fail closed with a precise error if a safe Git Bash executable cannot be identified.
- `nexus3/core/shell_detection.py`
  - Add helper logic or companion utilities for resolving the intended Windows shell executable, not just identifying the shell family.
- `nexus3/skill/builtin/env.py`
  - Evaluate passing shell-identity variables such as `MSYSTEM` only for the explicit Git-Bash launch path if they are required for consistent child-shell behavior.

### Tests

- `tests/unit/skill/test_bash_windows_behavior.py`
- add focused regressions proving that Git-Bash mode does not launch the System32/WSL bash shim when Git-for-Windows bash is available
- live Windows verification in Git Bash with the three-check procedure already captured in `AGENTS.md`

## Phase 5: Windows Git Bash REPL Input Correctness

### Goals

- Fix or clearly fail-closed/document Git Bash standalone limitations for ESC cancellation and multiline paste.

### Concrete changes

- `nexus3/cli/keys.py`
  - Add shell/backend-aware input monitoring instead of assuming `msvcrt` is sufficient for every Windows terminal.
  - Preferred direction: introduce a backend split that can distinguish native console input from Git Bash/mintty behavior.
- `nexus3/core/shell_detection.py`
  - Extend shell capability reporting to identify Git Bash/mintty input limitations explicitly.
- `nexus3/cli/repl.py`
- `nexus3/cli/repl_runtime.py`
  - Add prompt-toolkit configuration and/or key bindings for robust multiline paste handling.
  - If live ESC support in Git Bash cannot be implemented safely in this slice, surface a clear startup warning rather than silently advertising `ESC cancel` as available.

### Tests And Validation

- add unit tests for backend selection and startup warning conditions
- update live Windows test procedure to include:
  - real ESC cancellation in Git Bash during streaming
  - real multiline paste of a 3-line block in Git Bash, PowerShell, and Windows Terminal
- archive new Windows evidence under `docs/validation/<run-id>/windows/`

### Current Progress (2026-03-10)

- Completed in the current branch:
  - shell-derived prompt-capability helpers now distinguish Git Bash standalone
    input limitations from supported Windows console backends.
  - `KeyMonitor` now fails closed on Git Bash standalone by using the pause-only
    fallback loop instead of pretending `msvcrt`-backed ESC monitoring is
    available there.
  - main REPL startup no longer advertises `ESC to cancel` on Git Bash
    standalone; it now points users to `/cancel` and surfaces an explicit
    warning about multiline-paste limitations.
  - main REPL and client REPL now enable prompt-toolkit's external-editor
    fallback when those Git Bash limitations are detected.
  - focused unit coverage now exercises shell capability detection, the
    Git-Bash pause-only fallback path, and the prompt-support helpers.
- Remaining Phase 5 gate:
  - update live Windows evidence to confirm the new fail-closed behavior and
    capture the Git Bash / PowerShell / Windows Terminal matrix.

## Phase 6: Documentation And Validation Closeout

### Goals

- Align every user-facing description with the actual post-fix behavior.
- Replace stale closeout confidence with real evidence.

### Concrete changes

- `nexus3/defaults/NEXUS-DEFAULT.md`
  - update file-tool best practices, numbered-view warnings, patch guidance, and Windows shell guidance
- `AGENTS_NEXUS3SKILLSCAT.md`
  - align skill tables with current params/behavior
- `nexus3/skill/README.md`
  - align editing-tool behavior, newline/encoding semantics, and execution-tool notes
- `nexus3/session/README.md`
  - align path semantics / confirmation behavior
- `nexus3/cli/README.md`
  - align ESC handling/platform support claims
- `docs/testing/WINDOWS-LIVE-TESTING-GUIDE.md`
  - add explicit live Git Bash ESC and multiline-paste procedures
- `CLAUDE.md`
- `AGENTS.md`
  - keep running status, known caveats, and execution notes in sync
- `docs/plans/README.md`
  - index this plan

## Testing Strategy

### Automated

- Run focused `ruff` and `pytest` on each phase’s touched files.
- Run targeted integration coverage for file-editing skills after Phase 2/3.
- Re-run broader unit/security/integration subsets only when a phase touches shared permission/runtime plumbing.

### Live Validation

- Windows Git Bash:
  - verify `run_python`, `bash_safe`, and `shell_UNSAFE` no longer diverge into WSL unexpectedly
  - verify ESC really cancels a long response
  - verify multiline paste no longer auto-submits the first line
- PowerShell / Windows Terminal:
  - verify no regressions relative to Git Bash fixes

### Sandbox Caveat

- Continue using repo virtualenv executables for all local automation.
- For file-editing integration tests that stall in sandbox due `asyncio.to_thread(...)`, rerun unsandboxed per existing repo SOP.

## Execution Order

1. Phase 1: safety/permission holes
2. Phase 4: Windows `shell_UNSAFE` WSL bug
3. Phase 2: contract/ergonomics cleanup
4. Phase 3: fidelity/newline/encoding hardening
5. Phase 5: Git Bash REPL input fixes
6. Phase 6: docs + live validation closeout

Rationale:
- Phase 1 is security-sensitive.
- Phase 4 has a confirmed live correctness bug with a small, isolated fault domain.
- Phases 2 and 3 fix repeated agent/tool misuse and silent data-risk behavior.
- Phase 5 likely needs the most live Windows feedback and should happen after the narrower shell fix.
- Phase 6 should trail behavior changes so docs and evidence match the final state.

## Implementation Checklist

- [x] Create execution tracker entries in `AGENTS.md` for this plan and keep them current.
- [x] Phase 1: close `edit_lines` / `patch` sandboxed, TRUSTED, and path-semantics gaps.
- [x] Phase 1: add focused permission/confirmation regressions.
- [x] Phase 4: fix Windows `shell_UNSAFE` Git-Bash shell resolution.
- [x] Phase 4: add focused Windows shell-resolution regressions.
- [x] Phase 2: align `read_file` / `outline` / `patch` agent-facing contract.
- [x] Phase 2: fix or re-spec `edit_file` batch atomicity.
- [x] Phase 3: fix newline, encoding, and regex hardening items.
- [x] Phase 3: add fidelity/non-UTF8 regressions.
- [x] Phase 5: fix or explicitly fail-closed/document Git Bash ESC behavior.
- [x] Phase 5: fix or explicitly fail-closed/document Git Bash multiline paste behavior.
- [ ] Phase 5: add/update live Git Bash validation steps and collect evidence.
- [ ] Phase 6: update all affected docs and status files.
- [ ] Phase 6: run final focused validation and archive results.

Deferred follow-up note from Windows testing:
- After the current Phase 5/6 closeout, explicitly decide whether to open a
  dedicated follow-up plan for true Git Bash standalone ESC/multiline-paste
  support. The current implementation is intentionally fail-closed and
  documented; it is not a claim that mintty/backend input handling is fixed.

## Documentation Updates

When behavior changes land, update all of the following in the same wave where practical:

- `nexus3/defaults/NEXUS-DEFAULT.md`
- `AGENTS_NEXUS3SKILLSCAT.md`
- `nexus3/skill/README.md`
- `nexus3/session/README.md`
- `nexus3/cli/README.md`
- `docs/testing/WINDOWS-LIVE-TESTING-GUIDE.md`
- `CLAUDE.md`
- `AGENTS.md`
- `docs/plans/README.md`

## Exit Criteria

This plan is complete when all of the following are true:

- `edit_lines` and `patch` no longer bypass intended sandbox/confirmation policy.
- The file-editing tool docs no longer misdescribe numbered output, patch semantics, or batch atomicity.
- Text-edit tools either preserve fidelity or fail closed instead of silently corrupting non-UTF8 content.
- A Git-Bash-launched Windows NEXUS session no longer routes `shell_UNSAFE` into WSL.
- Git Bash live validation demonstrates working ESC cancellation and multiline paste, or NEXUS now surfaces an explicit, documented limitation instead of silently failing.
- All updated behavior is reflected in docs and recorded in `AGENTS.md` running status.
