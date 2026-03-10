# AGENTS.md

This file provides guidance to Codex when working in this repository.

## Project Overview

NEXUS3 is a clean-slate rewrite of NEXUS2, an AI-powered CLI agent framework.

- Status: feature-complete
- Core areas: multi-provider support, permission system, MCP integration, context compaction

## Architecture

Primary package: `nexus3/`

- `core/`: types, interfaces, errors, paths, permissions, process termination
- `config/`: schema and config loading
- `provider/`: model provider abstraction and retry logic
- `context/`: context loading, token counting, compaction
- `session/`: session coordination, persistence, logging
- `skill/`: skill protocol, registry, service container
- `clipboard/`: scoped clipboard and persistence
- `patch/`: unified diff parsing and application
- `display/`: terminal presentation and streaming output
- `cli/`: REPL, lobby, server/client modes, commands
- `rpc/`: JSON-RPC dispatching and agent pool
- `mcp/`: MCP integration
- `commands/`: command infrastructure
- `defaults/`: default prompts/config

Each module has its own `README.md`.

## Context Files

Instruction file priority is configurable; defaults include:

```json
["NEXUS.md", "AGENTS.md", "CLAUDE.md", "README.md"]
```

For this repo, keep `AGENTS.md` and `CLAUDE.md` consistent when behavior or workflows change.

## Reference Docs

Detailed references live in companion files to keep this document concise:

- `AGENTS_NEXUS3ARCH.md`: project overview, module architecture, interfaces, skill hierarchy, multi-agent server model
- `AGENTS_NEXUS3CMDCAT.md`: full CLI modes, flags, session model, and REPL command reference
- `AGENTS_NEXUS3SKILLSCAT.md`: full built-in skills table and notes
- `AGENTS_NEXUS3CTXSEC.md`: full context loading/compaction, temporal/git injection, permissions, and security hardening notes
- `AGENTS_NEXUS3CONFIGOPS.md`: configuration reference, provider setup, GitLab/clipboard config, design/SOP/testing workflows, and deferred work tracker

## Current Workstream (2026-03-02)

For continuity on the current review/remediation effort, start from:

- Review index: [docs/reviews/README.md](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- Canonical master review: [docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- Plans index: [docs/plans/README.md](/home/inc/repos/NEXUS3/docs/plans/README.md)
- Architecture investigation: [docs/plans/ARCH-INVESTIGATION-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- Milestone schedule: [docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)

## Engineering SOP

- Type everything; avoid weak typing and `Optional[Any]`.
- Fail fast; do not silently swallow exceptions.
- Prefer one clear implementation path over duplicate patterns.
- Keep code async-first where applicable.
- Add end-to-end tests for new behavior.
- Document user-visible changes.
- Delete dead code and unused imports.
- Do not revert unrelated local changes.
- Keep feature branches focused and commit in logical units.

## Planning Requirements

For non-trivial features, create a plan doc under `docs/` before implementation.

Minimum plan sections:

- Overview
- Scope (included, deferred, excluded)
- Design decisions and rationale
- Implementation details with concrete file paths
- Testing strategy
- Implementation checklist
- Documentation updates

Update the plan incrementally while you work.

Execution tracking SOP (applies to every major plan):
- Add/maintain a running status section in `AGENTS.md` with branch, active milestone/phase, recent commits, and next gate.
- Check off plan checklist items as soon as they are completed (same working session).
- When disconnected/compacted, resume from `AGENTS.md` running status first, then reconcile plan checklists before new edits.
- When spawning Codex subagents, explicitly instruct them to avoid escalated/sandbox-bypass commands unless absolutely required by the task, to prevent avoidable approval stalls.

## Testing and Validation

Always use virtualenv executables:

```bash
.venv/bin/pytest tests/ -v
.venv/bin/pytest tests/integration/ -v
.venv/bin/ruff check nexus3/
.venv/bin/mypy nexus3/
```

Never rely on bare `python` or `pytest`.

Known sandbox caveat (Codex CLI environment):
- In this repo, sandboxed runs may hang on tests that execute file I/O via `asyncio.to_thread(...)` (for example, `Path.read_bytes` inside file-edit skills).
- Symptom: pytest collects tests, starts first test, then stalls without pass/fail output.
- Workaround: rerun the same pytest command unsandboxed/escalated to verify real pass/fail status.

Live validation is required for changes that affect agent behavior, RPC, skills, or permissions:

```bash
nexus3 &
nexus3 rpc create test-agent
nexus3 rpc send test-agent "describe your permissions and what you can do"
nexus3 rpc destroy test-agent
```

## Permissions and Safety

- Respect preset boundaries (`sandboxed`, `trusted`, `yolo`).
- `sandboxed` should remain least-privileged by default in RPC workflows.
- Treat tool enablement, write paths, and agent targeting restrictions as security-sensitive.
- Avoid privilege escalation patterns in subagent creation.

## CLI and Ops Notes

Useful commands:

```bash
nexus3
nexus3 --fresh
nexus3 --resume
NEXUS_DEV=1 nexus3 --serve 9000
nexus3 rpc detect
nexus3 rpc list
nexus3 rpc create NAME
nexus3 rpc send NAME "message"
nexus3 rpc status NAME
```

## Documentation Discipline

When changing behavior:

- Update relevant module `README.md`
- Update `CLAUDE.md` and `AGENTS.md` sections that describe the changed behavior
- Update command/help text for CLI or REPL changes
- Record temporary breakages in `CLAUDE.md` Known Failures if they cannot be fixed immediately

## Current Debugging Handoff (2026-03-04)

Status:
- Probably fixed as of 2026-03-04 after the cancellation/role-sequence hardening set (`5fe3f59`, `612df40`, `6daec54`, `0b04467`), but keep all notes below as the fallback playbook if it recurs.

Goal:
- Eliminate recurring post-cancel provider failures:
  - `Provider returned an empty response`
  - `API request failed (400): Unexpected role 'user' after role 'tool'`

Recent commits on `master` (chronological):
- `5fe3f59`: Mid-stream cancellation handling + reduce false empty-stream warnings.
- `612df40`: Prevent orphan tool-result sequences after cancellation.
- `6daec54`: Repair trailing tool-result tail by inserting synthetic assistant before next user turn.
- `0b04467`: Improve diagnostics:
  - log provider 4xx/5xx error bodies to `raw.jsonl`
  - emit `session.preflight` role snapshots to `verbose.md` before provider calls.

What is currently implemented:
- Pre-turn repair pipeline in `Session.send()` and `Session.run_turn()`:
  1. `_flush_cancelled_tools()` (now guarded; drops stale cancelled IDs)
  2. `context.prune_unpaired_tool_results()` (global scrub of invalid TOOL messages)
  3. `context.fix_orphaned_tool_calls()` (synthesizes missing tool results)
  4. `context.ensure_assistant_after_tool_results()` (prevents USER-after-TOOL tail)
- Provider stream warnings:
  - completed empty streams still warn
  - incomplete/interrupted empty streams now debug-log instead of warning.

Important caveat:
- If users still report 400 role errors, assume there is another sequence shape not covered yet.
- Do not guess; inspect logs from failing run with the exact commands below.

How to capture actionable logs:
```bash
nexus3 -V --raw-log --resume
# or: nexus3 -V --raw-log --session <NAME>
```

Then reproduce once and collect newest session directory under:
- `./.nexus3/logs/YYYY-MM-DD_HHMMSS_*/`

Required files:
- `verbose.md` (must include `session.preflight` entries)
- `raw.jsonl` (must include request + 4xx response bodies)
- `context.md` (conversation sequence around failure)

What to inspect first on next pass:
1. In `verbose.md`, locate last `session.preflight` block before the 400.
2. Verify role order in that preflight snapshot:
   - especially `... TOOL -> USER` adjacency
   - duplicate TOOL results
   - TOOL results without matching assistant tool_calls.
3. In `raw.jsonl`, verify failing request payload `messages` exactly matches the preflight sequence.
4. Add a unit test reproducing that exact shape before patching.

Suggested next hardening if failure persists:
- Add a provider-agnostic message normalizer in `Session` just before provider call:
  - enforce invariants for assistant/tool batches
  - optionally collapse illegal trailing TOOL blocks into a synthetic assistant note
  - emit one structured warning event with before/after diff summary.

## Architecture Overhaul Running Status (2026-03-09)

Branch:
- `feat/arch-overhaul-execution`

Current milestone:
- Post-architecture hardening planning active (2026-03-10):
  - created
    [POST-ARCH-BUGFIX-HARDENING-PLAN-2026-03-10.md](/home/inc/repos/NEXUS3/docs/plans/POST-ARCH-BUGFIX-HARDENING-PLAN-2026-03-10.md)
    to track the open post-arch bugfix backlog (file-editing safety/contract
    fixes, Git Bash shell bug, Git Bash ESC, Git Bash multiline paste, docs
    closeout).
  - active execution gate: Phase 5 live-validation closeout from that plan
    (Windows Git Bash / PowerShell / Windows Terminal evidence refresh).
  - most recent completed implementation gate: Phase 5 fail-closed input
    handling for Git Bash standalone, with focused validation now green.
- `Post-M4` validation campaign closeout complete: external closeout slice
  `post-m4-20260306-live1e` archived real-host Windows evidence and
  multi-emulator carriage-return verification; deterministic closeout gate
  now passes with explicit run ids.
- `M4` implementation closeout complete: Plan E Phases 1-4 and Plan B Phases 1-4 are committed on this branch, and Plan G sink-boundary closure is complete.
- `M2` authorization/concurrency and strict-ingress closeout work is complete on this branch.

Immediate tasks:
- Follow-on hardening execution plan (2026-03-10):
  - canonical next-work plan:
    [POST-ARCH-BUGFIX-HARDENING-PLAN-2026-03-10.md](/home/inc/repos/NEXUS3/docs/plans/POST-ARCH-BUGFIX-HARDENING-PLAN-2026-03-10.md)
  - preferred execution order from the new plan:
    1. Phase 5: Windows live validation refresh for Git Bash/Pwsh/Windows Terminal.
    2. Phase 6: final docs and validation closeout.
  - deferred follow-up note from user testing:
    - first follow-up `outline` audit wave is now implemented locally:
      parser override support (`file_type` / `language`), honest directory-mode
      parameter handling, and fail-closed ambiguous `symbol` resolution. A
      later pass should still inspect fresh transcripts/tool payloads and
      decide whether any remaining misuse belongs in prompt guidance, schema
      ergonomics, or deeper tool behavior.
    - after the current Phase 5/6 closeout, discuss whether to open a dedicated
      follow-up plan for true Git Bash standalone ESC/multiline-paste support.
      The current branch only fails closed and documents the limitation; it
      does not claim a real mintty/backend input fix.
    - later planning item from user:
      create a dedicated plan for “NEXUS3 as an MCP server” so external agents
      can spawn and communicate with Nexus agents without needing bespoke
      server-start choreography. Scope this plan to include an agent-facing
      messaging-queue / inbox model (for example, a “retrieve my messages”
      tool), because Nexus agents currently reply to inbound requests but do
      not have a clean way to initiate asynchronous conversation with outside
      agents.
- Completed follow-on hardening slice (2026-03-10): Plan Phase 5
  fail-closed Git Bash input handling:
  - `nexus3/core/shell_detection.py`
    - added explicit helpers for Git Bash standalone prompt limitations and
      live ESC-cancel capability detection.
  - `nexus3/cli/keys.py`
    - Windows Git Bash standalone now uses the pause-only fallback loop instead
      of attempting misleading `msvcrt` ESC monitoring.
  - `nexus3/cli/prompt_support.py`
    - new shared prompt helpers centralize command hints, Git Bash warnings,
      and prompt-toolkit external-editor enablement.
  - `nexus3/cli/repl.py`
  - `nexus3/cli/repl_runtime.py`
    - startup guidance now fails closed on Git Bash standalone:
      `/cancel` is advertised instead of ESC, multiline-paste limitations are
      warned explicitly, and prompt-toolkit external-editor fallback is enabled.
  - focused regression coverage added/updated in:
    - `tests/unit/core/test_shell_detection.py`
    - `tests/unit/cli/test_confirmation_sync.py`
    - `tests/unit/cli/test_prompt_support.py`
  - focused doc sync updated:
    - `nexus3/cli/README.md`
    - `CLAUDE.md`
    - `docs/testing/WINDOWS-LIVE-TESTING-GUIDE.md`
    - `docs/plans/POST-ARCH-BUGFIX-HARDENING-PLAN-2026-03-10.md`
  - focused validation passed:
    - `.venv/bin/ruff check nexus3/cli/prompt_support.py nexus3/core/shell_detection.py nexus3/cli/keys.py nexus3/cli/repl.py nexus3/cli/repl_runtime.py tests/unit/core/test_shell_detection.py tests/unit/cli/test_confirmation_sync.py tests/unit/cli/test_prompt_support.py`
    - `.venv/bin/pytest -q tests/unit/core/test_shell_detection.py tests/unit/cli/test_confirmation_sync.py tests/unit/cli/test_prompt_support.py` (`41 passed`)
- Completed follow-on hardening slice (2026-03-10, committed `6245dfa`):
  outline tool audit first wave:
  - `nexus3/skill/builtin/outline.py`
    - added file-level parser override support via `file_type=` and
      `language=` for extensionless or misnamed files.
    - directory mode now honors `preview`, `signatures`, and `line_numbers`
      instead of silently ignoring them.
    - directory mode now rejects file-only `symbol` / parser-override usage
      with explicit errors instead of silently dropping those parameters.
    - ambiguous `symbol` matches now fail closed instead of returning the first
      match silently.
    - unsupported file types now return actionable errors pointing callers to
      `read_file` or `file_type=...`.
  - focused regression coverage added/updated in:
    - `tests/unit/skill/test_outline.py`
  - focused doc sync updated:
    - `nexus3/defaults/NEXUS-DEFAULT.md`
    - `AGENTS_NEXUS3SKILLSCAT.md`
    - `nexus3/skill/README.md`
    - `README.md`
    - `CLAUDE.md`
  - focused validation passed:
    - `.venv/bin/ruff check nexus3/skill/builtin/outline.py tests/unit/skill/test_outline.py`
    - `.venv/bin/pytest -q tests/unit/skill/test_outline.py` (`146 passed`)
- Completed follow-on hardening slice (2026-03-10, committed `ab4ec43`, `2e25b3c`):
  outline tool audit second/third waves:
  - `nexus3/core/validation.py`
  - `nexus3/skill/base.py`
    - internal runtime params such as `_parallel` are now stripped before JSON
      Schema validation in both the session validator and the skill-wrapper
      validators, so per-tool strict schemas can reject real unknown params
      without breaking documented parallel execution flags.
  - `nexus3/skill/builtin/outline.py`
    - added `parser=` as a compatibility alias for parser override.
    - directory mode remains non-recursive across the filesystem, but `depth`
      now controls nested symbol levels within each outlined file instead of
      being effectively ignored.
    - `recursive=true` now fails closed with explicit guidance to use
      `glob`/`list_directory` first.
    - `diff=true` now emits an explicit note when git diff context is
      unavailable instead of silently omitting change markers.
    - directory diff marker matching now uses paths relative to the outlined
      directory instead of basenames, so nested same-basename changes no longer
      falsely mark immediate child files as `[CHANGED]`.
    - outline schema now rejects unknown user-facing parameters while still
      permitting `_parallel`.
  - transcript audit findings:
    - current local log artifacts do not contain post-change `outline` misuse
      reproductions; the concern remains hypothesis-driven rather than tied to
      a fresh captured failure.
    - remaining likely follow-up item after this wave:
      - decide whether empty/no-actionable outline states should standardize on
        error vs structured-success signaling, or remain explicit success
        sentinels.
  - focused regression coverage added/updated in:
    - `tests/unit/test_skill_validation.py`
    - `tests/unit/skill/test_outline.py`
  - focused doc sync updated:
    - `nexus3/defaults/NEXUS-DEFAULT.md`
    - `AGENTS_NEXUS3SKILLSCAT.md`
    - `nexus3/skill/README.md`
    - `README.md`
    - `CLAUDE.md`
    - `docs/plans/POST-ARCH-BUGFIX-HARDENING-PLAN-2026-03-10.md`
  - focused validation passed:
    - `.venv/bin/ruff check nexus3/core/validation.py nexus3/skill/base.py nexus3/skill/builtin/outline.py tests/unit/test_skill_validation.py tests/unit/skill/test_outline.py`
    - `.venv/bin/pytest -q tests/unit/test_skill_validation.py tests/unit/skill/test_outline.py` (`167 passed`)
    - `.venv/bin/pytest -q tests/unit/skill/test_skill_validation.py` (`16 passed`)
    - `.venv/bin/ruff check nexus3/skill/builtin/outline.py tests/unit/skill/test_outline.py`
    - `.venv/bin/pytest -q tests/unit/skill/test_outline.py` (`157 passed`)
- Completed live-test regression fix (2026-03-10, local pending commit):
  OpenAI tool-schema compatibility for `patch`:
  - Windows live testing surfaced provider rejection of the `patch` tool
    schema because its top-level parameters object used `anyOf`.
  - updated `nexus3/skill/builtin/patch.py` to remove the top-level combinator
    and keep the `path` vs `target` requirement enforced in runtime
    validation instead.
  - added regression coverage in `tests/unit/skill/test_patch.py` to keep the
    provider-facing schema free of top-level `anyOf` / `oneOf` / `allOf` / `not`.
  - focused validation passed:
    - `.venv/bin/ruff check nexus3/skill/builtin/patch.py tests/unit/skill/test_patch.py`
    - `.venv/bin/pytest -q tests/unit/skill/test_patch.py` (`33 passed`)
- Completed live-test regression fix (2026-03-10, local pending commit):
  `edit_file` batch-mode placeholder normalization:
  - Windows live testing surfaced `edit_file` failures when a caller sent
    `edits=[...]` alongside placeholder `old_string=""` / `new_string=""`.
  - updated `nexus3/skill/builtin/edit_file.py` to treat that exact empty-string
    placeholder shape as omitted in batch mode, while still rejecting real
    mixed-mode calls and invalid empty batch edits.
  - added focused regression coverage in `tests/unit/skill/test_edit_file.py`
    for the placeholder batch shape.
  - focused validation passed:
    - `.venv/bin/ruff check nexus3/skill/builtin/edit_file.py tests/unit/skill/test_edit_file.py`
    - `.venv/bin/pytest -q tests/unit/skill/test_edit_file.py` (`21 passed`)
- Completed live-test regression fix (2026-03-10, local pending commit):
  `patch` empty-placeholder normalization:
  - Windows live testing surfaced `patch` failures when a caller sent inline
    `diff=...` alongside placeholder `diff_file=""` (and sometimes `target=""`).
  - updated `nexus3/skill/builtin/patch.py` to treat empty-string `diff` /
    `diff_file` placeholders as omitted before mutual-exclusion validation.
  - added focused regression coverage in `tests/unit/skill/test_patch.py` for
    the `path=...`, `target=""`, `diff=...`, `diff_file=""` shape.
  - focused validation passed:
    - `.venv/bin/ruff check nexus3/skill/builtin/patch.py tests/unit/skill/test_patch.py`
    - `.venv/bin/pytest -q tests/unit/skill/test_patch.py` (`34 passed`)
- Completed preemptive placeholder audit + follow-up fixes (2026-03-10, local pending commit):
  audit outcome after `edit_file` / `patch` live regressions:
  - attempted parallel subagent audit, but all three explorers were interrupted
    before returning preserved findings; final audit was completed locally.
  - confirmed and fixed two more high-confidence empty-string placeholder bugs:
    - `nexus3/skill/builtin/clipboard_manage.py`
      - `clipboard_update` now treats `source=""` and `new_key=""` as omitted
        instead of resolving `source=""` as a real path or allowing `new_key=""`
        to flow into a rename.
    - `nexus3/skill/builtin/nexus_create.py`
      - `cwd=""` is now treated as omitted so the skill does not pass an empty
        cwd through to RPC create-agent handling.
  - focused regression coverage added:
    - `tests/unit/skill/test_clipboard_manage.py`
    - `tests/unit/skill/test_nexus_create.py`
  - focused validation passed:
    - `.venv/bin/ruff check nexus3/skill/builtin/clipboard_manage.py nexus3/skill/builtin/nexus_create.py tests/unit/skill/test_clipboard_manage.py tests/unit/skill/test_nexus_create.py`
    - `.venv/bin/pytest -q tests/unit/skill/test_clipboard_manage.py tests/unit/skill/test_nexus_create.py` (`44 passed`)
  - remaining audit note:
    - optional enum selectors such as clipboard `scope` still fail at the
      schema-validation boundary if a caller sends `scope=\"\"` placeholders.
      That is a broader shared-normalization / caller-discipline issue, not
      another silent semantic bug like the fixed `edit_file` / `patch` /
      `clipboard_update` / `nexus_create` cases.
- Ongoing Windows live-test investigation (2026-03-10, local pending commit):
  repeated "Got it" / "Got interrupted mid-run" assistant chatter:
  - user observed a trusted Windows REPL session repeatedly re-acknowledging a
    single request and claiming interruptions that were not visible as normal
    user turns in the standard transcript.
  - confirmed:
    - tool-call argument logs are raw provider/model arguments, not UI-invented
      defaults:
      - `nexus3/session/single_tool_runtime.py` validates
        `tool_call.arguments` directly.
      - `nexus3/session/logging.py` writes `tc.arguments` directly into session
        logs.
    - NEXUS has hidden context-repair / cancellation injections that can affect
      the next provider turn without appearing as ordinary user messages:
      - synthetic assistant note:
        `Previous turn was cancelled after tool execution.`
        in `nexus3/context/manager.py`
      - synthetic cancelled tool-result content:
        `Cancelled by user: tool execution was interrupted`
        in `nexus3/session/tool_loop_events_runtime.py` and
        `nexus3/context/compiler.py`
  - important observation from this Codex session:
    - the client/user saw both a `commentary` update and a `final` answer as
      sequential assistant messages. From my side, those were two distinct
      channel emissions, not duplicate final answers.
    - this increases suspicion that some transcript/rendering layers may be
      flattening internal channels or hidden events into ordinary assistant
      messages, making behavior look stranger than the raw model output alone.
  - next repro instructions:
    - user will rerun on Windows with:
      `.venv\\Scripts\\python.exe -m nexus3 -V --raw-log --fresh`
    - inspect newest `.nexus3\\logs\\...` session for:
      - `context.md`
      - `verbose.md`
      - `raw.jsonl`
    - specifically search for:
      - `Previous turn was cancelled after tool execution.`
      - `Cancelled by user: tool execution was interrupted`
      - `SessionCancelled`
      - `ToolBatchHalted`
      - repeated `run_turn.tools.iteration` preflight blocks with no matching
        new user input
  - current diagnosis:
    - placeholder tool args were real model/tool-call outputs
    - repeated interruption-like assistant chatter was traced to provider-side
      request shaping, not just model spontaneity:
      - `raw.jsonl` proved the provider stream itself emitted the repeated
        `Got it ...` text.
      - request payloads for normal mid-turn tool-loop continuation were
        incorrectly receiving a synthetic assistant note
        `Previous turn was cancelled after tool execution.` on every provider
        call after a tool result.
      - root cause: `nexus3/provider/{openai_compat,anthropic}.py` were calling
        `compile_context_messages(...)` with
        `ensure_assistant_after_tool_results=True`, which is only appropriate
        for session preflight before a new USER turn, not for TOOL->ASSISTANT
        continuation inside the same turn.
      - fix (2026-03-10): provider request shaping now disables
        `ensure_assistant_after_tool_results`; session preflight still owns the
        real cancelled-tail repair before new user turns.
      - focused regression coverage added in
        `tests/unit/provider/test_compiler_integration.py`.
  - next gate remains Windows live validation to confirm the documented
    fail-closed behavior on real hosts.
- Patch skill friendliness fix (2026-03-10, local pending commit):
  - `nexus3/skill/builtin/patch.py` now auto-normalizes single-file hunk-only
    diffs (`@@ ... @@` without `---`/`+++`) when `path`/`target` is provided.
  - malformed hunk-only input now gets a targeted guidance error instead of the
    misleading generic `No patch hunks found in diff`.
  - focused regressions added in `tests/unit/skill/test_patch.py`.
- Completed follow-on hardening slice (2026-03-10): Plan Phase 3
  newline / encoding / regex hardening:
  - `nexus3/core/paths.py`
    - `atomic_write_text()` now writes caller-provided newline bytes exactly
      (`newline=""`) instead of relying on platform translation.
  - `nexus3/skill/builtin/append_file.py`
    - CR-only trailing-newline detection now behaves correctly.
    - append path now writes exact UTF-8 bytes with binary O_APPEND semantics,
      preserving the chosen newline bytes cross-platform.
  - `nexus3/skill/builtin/write_file.py`
    - success reporting now reflects the real UTF-8 byte count written.
  - `nexus3/skill/builtin/edit_file.py`
  - `nexus3/skill/builtin/edit_lines.py`
  - `nexus3/skill/builtin/regex_replace.py`
    - text-edit tools now fail closed on undecodable/non-UTF8 input and direct
      byte-sensitive edits to `patch` `fidelity_mode="byte_strict"`.
    - `edit_lines` now preserves EOF newline state when replacing the last line
      of a file that already ended with a newline.
    - `regex_replace` now rejects negative `count`, avoids materializing an
      unbounded `findall()` list, and softens timeout messaging to a
      best-effort local wait window.
  - focused regression coverage added/updated in:
    - `tests/unit/core/test_paths_windows.py`
    - `tests/security/test_p2_append_file.py`
    - `tests/unit/skill/test_edit_lines.py`
    - `tests/unit/skill/test_edit_file.py`
    - `tests/unit/test_regex_replace_skill.py`
  - focused doc sync updated:
    - `nexus3/defaults/NEXUS-DEFAULT.md`
    - `nexus3/skill/README.md`
    - `AGENTS_NEXUS3SKILLSCAT.md`
    - `CLAUDE.md`
    - `docs/plans/POST-ARCH-BUGFIX-HARDENING-PLAN-2026-03-10.md`
  - focused validation passed:
    - `.venv/bin/ruff check nexus3/core/paths.py nexus3/skill/builtin/append_file.py nexus3/skill/builtin/write_file.py nexus3/skill/builtin/edit_file.py nexus3/skill/builtin/edit_lines.py nexus3/skill/builtin/regex_replace.py tests/unit/core/test_paths_windows.py tests/security/test_p2_append_file.py tests/unit/skill/test_edit_lines.py tests/unit/skill/test_edit_file.py tests/unit/test_regex_replace_skill.py`
    - `.venv/bin/pytest -q tests/unit/core/test_paths_windows.py tests/security/test_p2_append_file.py tests/unit/skill/test_edit_lines.py tests/unit/skill/test_edit_file.py tests/unit/test_regex_replace_skill.py` (`92 passed`)
  - Phase 3 is now complete; next gate is Phase 5 Git Bash input handling.
- Completed follow-on hardening slice (2026-03-10): Plan Phase 2C
  patch path-alias + path-semantics closeout:
  - `nexus3/skill/builtin/patch.py`
    - `patch` now accepts `path=` as the preferred file argument while
      preserving `target=` as a compatibility alias.
    - mismatched `path` + `target` inputs now fail closed.
  - `nexus3/session/path_semantics.py`
    - patch semantics now recognize both `path` and `target`, and display-path
      extraction falls back cleanly across aliases.
    - added shared tool-path extraction so permission checks can derive all
      relevant read/write paths from tool semantics.
  - `nexus3/session/enforcer.py`
    - permission checks now use semantics-driven path extraction instead of the
      old hard-coded `path`/`source`/`destination` list, which closes the
      existing `patch(target=...)` path-gating hole as well.
    - aligned `PATH_TOOLS` with current file-editing coverage (`edit_lines`,
      `patch`).
  - focused regression coverage added/updated in:
    - `tests/unit/skill/test_patch.py`
    - `tests/security/test_multipath_confirmation.py`
    - `tests/unit/session/test_enforcer.py`
    - `tests/integration/test_file_editing_skills.py`
  - doc sync updated:
    - `nexus3/defaults/NEXUS-DEFAULT.md`
    - `AGENTS_NEXUS3SKILLSCAT.md`
    - `nexus3/skill/README.md`
    - `nexus3/session/README.md`
    - `CLAUDE.md`
  - focused validation passed:
    - `.venv/bin/ruff check nexus3/skill/builtin/patch.py nexus3/session/path_semantics.py nexus3/session/enforcer.py tests/unit/skill/test_patch.py tests/security/test_multipath_confirmation.py tests/unit/session/test_enforcer.py tests/integration/test_file_editing_skills.py`
    - `.venv/bin/pytest -q tests/unit/skill/test_patch.py tests/security/test_multipath_confirmation.py tests/unit/session/test_enforcer.py`
    - `.venv/bin/pytest -q tests/integration/test_file_editing_skills.py -k patch`
  - Phase 2 is now complete; next gate is Phase 3 newline / encoding / regex
    hardening.
- Completed follow-on hardening slice (2026-03-10): Plan Phase 2B
  read/outline contract corrections:
  - `nexus3/skill/builtin/read_file.py`
    - added `line_numbers=false` raw output mode while preserving numbered
      output as the default.
    - raw mode now preserves trailing spaces and final-line newline state
      instead of stripping line text via unconditional `rstrip()`.
  - `nexus3/skill/builtin/outline.py`
    - `symbol` extraction now honors `line_numbers=false`.
    - unsupported file types still return a non-error fallback, but now
      explicitly direct callers to `read_file`.
  - focused regression coverage added/updated in:
    - `tests/unit/test_skill_enhancements.py`
    - `tests/unit/skill/test_outline.py`
    - `tests/security/test_p2_file_size_limits.py`
  - minimal doc sync landed in:
    - `nexus3/defaults/NEXUS-DEFAULT.md`
    - `AGENTS_NEXUS3SKILLSCAT.md`
    - `nexus3/skill/README.md`
  - focused validation passed:
    - `git diff --check`
    - `.venv/bin/ruff check nexus3/skill/builtin/read_file.py nexus3/skill/builtin/outline.py tests/unit/test_skill_enhancements.py tests/unit/skill/test_outline.py tests/security/test_p2_file_size_limits.py`
    - `.venv/bin/pytest -q tests/unit/test_skill_enhancements.py tests/unit/skill/test_outline.py tests/security/test_p2_file_size_limits.py`
- Completed follow-on hardening slice (2026-03-09): Plan Phase 2A
  patch/edit contract corrections:
  - `nexus3/skill/builtin/patch.py`
    - valid new-file diffs can now create a missing target path when the diff
      marks the file as new, instead of failing early on target non-existence.
  - `nexus3/skill/builtin/edit_file.py`
    - batch edits now fail closed if an earlier in-memory replacement causes a
      later edit target to disappear or become ambiguous, preventing silent
      “success” with a later no-op.
  - focused regression coverage added/updated in:
    - `tests/unit/skill/test_patch.py`
    - `tests/unit/skill/test_edit_file.py`
    - `tests/integration/test_file_editing_skills.py`
  - focused validation passed:
    - `.venv/bin/ruff check nexus3/skill/builtin/patch.py nexus3/skill/builtin/edit_file.py tests/unit/skill/test_patch.py tests/unit/skill/test_edit_file.py tests/integration/test_file_editing_skills.py`
    - `.venv/bin/pytest -q tests/unit/skill/test_patch.py tests/unit/skill/test_edit_file.py`
    - `.venv/bin/pytest -q tests/integration/test_file_editing_skills.py -k 'patch or batch_edit'`
  - remaining Phase 2 scope:
    - `read_file` raw-vs-numbered output contract cleanup
    - `outline` unsupported-file / symbol-mode fallback cleanup
    - any remaining `patch` interface ergonomics (`target` vs `path`) and
      follow-on docs alignment
- Completed follow-on hardening slice (2026-03-09): Plan Phase 4
  Windows `shell_UNSAFE` Git-Bash shell resolution:
  - `nexus3/core/shell_detection.py`
    - added explicit Git-Bash executable resolution that scans PATH and common
      Git-for-Windows install roots while rejecting known WSL launcher shims
      (`System32\\bash.exe`, `WindowsApps\\bash.exe`).
  - `nexus3/skill/builtin/bash.py`
    - Windows Git-Bash `shell_UNSAFE` branch now launches the resolved
      executable path instead of bare `bash`, preserves `MSYSTEM` only for that
      child shell, and fails closed with a deterministic error if no safe Git
      Bash executable can be found.
  - `nexus3/core/__init__.py`
    - exported the new shell-resolution helper.
  - focused regression coverage added/updated in:
    - `tests/unit/core/test_shell_detection.py`
    - `tests/unit/skill/test_bash_windows_behavior.py`
  - focused validation passed:
    - `git diff --check`
    - `.venv/bin/ruff check nexus3/core/__init__.py nexus3/core/shell_detection.py nexus3/skill/builtin/bash.py tests/unit/core/test_shell_detection.py tests/unit/skill/test_bash_windows_behavior.py`
    - `.venv/bin/pytest -q tests/unit/core/test_shell_detection.py tests/unit/skill/test_bash_windows_behavior.py`
  - next gate: Phase 2 (`read_file` / `outline` / `patch` contracts and
    `edit_file` batch atomicity).
- Completed follow-on hardening slice (2026-03-09): Plan Phase 1
  `edit_lines` / `patch` sandboxed + TRUSTED + path-semantics hardening:
  - `nexus3/rpc/global_dispatcher.py`
    - sandboxed RPC `create_agent` no-write-path override set now disables
      `edit_lines` and `patch` alongside the existing write tools.
  - `nexus3/core/policy.py`
    - `DESTRUCTIVE_ACTIONS` now includes `edit_lines` and `patch`, so
      TRUSTED mode requires confirmation for those tools outside CWD.
  - `nexus3/session/path_semantics.py`
    - explicit semantics added for:
      - `edit_lines`: `path` as read/write/display path
      - `patch`: `target` as write/display path and `diff_file` as read path
  - focused regression coverage added/updated in:
    - `tests/unit/test_global_dispatcher.py`
    - `tests/security/test_multipath_confirmation.py`
    - `tests/unit/test_permissions.py`
  - focused validation passed:
    - `git diff --check`
    - `.venv/bin/ruff check nexus3/rpc/global_dispatcher.py nexus3/core/policy.py nexus3/session/path_semantics.py tests/unit/test_global_dispatcher.py tests/security/test_multipath_confirmation.py tests/unit/test_permissions.py`
    - `.venv/bin/pytest -q tests/unit/test_global_dispatcher.py tests/security/test_multipath_confirmation.py tests/unit/test_permissions.py`
  - next gate at completion time was Phase 4 (`shell_UNSAFE` Windows Git-Bash
    WSL misrouting), now complete.
- Compact review handoff (2026-03-09, file-editing tool/doc audit; no code
  changes yet):
  - user requested a deep-dive sanity check of file-editing tools, cross-OS
    and cross-shell behavior, tool-description accuracy, and
    `nexus3/defaults/NEXUS-DEFAULT.md` best-practice guidance while running
    manual tests.
  - branch/head at review time: `feat/arch-overhaul-execution` / `1522581`.
  - confirmed local findings to pick up first:
    - `nexus3/rpc/global_dispatcher.py`, `nexus3/core/presets.py`, and
      `nexus3/core/policy.py`: sandboxed RPC write-tool overrides omit
      `edit_lines` and `patch`, so sandboxed RPC agents created without
      `allowed_write_paths` still retain those two write tools inside their
      cwd. Local verification against the current permission merge confirmed
      `edit_lines=True` and `patch=True` while the other write tools are
      disabled.
    - `nexus3/core/policy.py`: `edit_lines` and `patch` are also missing from
      `DESTRUCTIVE_ACTIONS`, so TRUSTED-mode writes through those tools do not
      trigger outside-CWD confirmation at all.
    - `nexus3/skill/builtin/edit_file.py`: batched `edits` are not truly
      atomic; validation happens against the original content, then edits are
      applied sequentially, so later edits can silently no-op after earlier
      edits mutate the buffer. This conflicts with current
      `NEXUS-DEFAULT.md` wording that all edits succeed or fail together.
    - `nexus3/session/path_semantics.py`: missing explicit semantics for
      `edit_lines` and `patch`; `edit_lines` falls back to generic path
      extraction, while `patch` loses path/display-path/allow-always fidelity
      because it uses `target`, and `nexus3/cli/confirmation_ui.py` can show
      `unknown` for patch confirmations.
    - `nexus3/skill/builtin/edit_lines.py`: replacing the last line of a file
      strips a previously present trailing newline. Current unit coverage
      explicitly expects this, but it contradicts the surrounding
      line-ending-preservation documentation.
  - explorer findings captured:
    - `regex_replace` timeout safety claim is not reliable:
      `findall(...)` pre-scans before the timeout window, and the timed
      `asyncio.to_thread(...)` replacement cannot actually be preempted once
      running.
    - `append_file` misdetects CR-only files as missing a trailing newline and
      can insert an extra line break.
    - `write_file` and `append_file` use text-mode writes with platform newline
      translation risk on Windows, which may not match byte-fidelity or
      "preserve line endings" expectations.
    - `edit_file`, `edit_lines`, and `regex_replace` decode with replacement
      and then rewrite UTF-8, so non-UTF8 files can be silently corrupted.
    - doc drift identified:
      - patch params/behavior are stale in user-facing catalogs
        (`fidelity_mode`, exact-path priority, basename ambiguity fail-closed,
        `diff`/`diff_file` exclusivity, `diff_file` path validation).
      - sandboxed write-disable wording in `NEXUS-DEFAULT.md` is incomplete.
      - confirmation/path-semantics docs omit `edit_lines` and `patch`.
      - `append_file` create-if-missing behavior is undocumented.
      - text-vs-byte-fidelity guidance for file-edit tools is incomplete; docs
        should steer non-UTF8/byte-preserving edits toward `patch`
        (`byte_strict`).
  - explorer status:
    - `Darwin` returned the cross-platform/file-fidelity audit findings above.
    - `Poincare the 2nd` returned the doc-accuracy drift findings above.
    - `Lorentz the 2nd` stalled and was interrupted; rerun only if more review
      depth is needed.
  - recommended next execution order:
    1. Fix the sandboxed/TRUSTED permission gaps for `edit_lines` and
       `patch` (RPC write-tool overrides, `DESTRUCTIVE_ACTIONS`,
       `path_semantics`, confirmation UX), then add focused permission and
       confirmation regressions.
    2. Fix `edit_file` batch atomicity or weaken the user-facing docs if true
       atomic multi-edit behavior is not intended.
    3. Fix `edit_lines` trailing-newline preservation for end-of-file
       replacements and update the focused tests/docs accordingly.
    4. Fix `append_file` CR-only handling and decide whether `write_file` /
       `append_file` should suppress newline translation for predictable
       cross-platform behavior.
    5. Revisit UTF-8-only editing semantics versus `patch` byte-strict
       guidance; either hard-fail non-UTF8 text edits or document the lossy
       behavior explicitly.
    6. After behavior changes, update `NEXUS-DEFAULT.md`,
       `AGENTS_NEXUS3SKILLSCAT.md`, `nexus3/skill/README.md`,
       `nexus3/session/README.md`, and `nexus3/cli/README.md` together.
- Completed follow-on audit checkpoint (2026-03-09, tool-usage failure
  analysis for `edit_*`, `patch`, `outline`; no code changes yet):
  - confirmed local usage-friction findings:
    - `read_file` always prefixes returned lines with `N: ` line numbers, but
      user-facing docs still describe it as plain file content. This likely
      contributes to `edit_file`/`patch` misuse when agents copy numbered text
      into exact-match tool inputs.
    - `patch` uses inconsistent path parameter naming (`target` instead of
      `path`), which is likely a recurrent call-shape failure source relative
      to the rest of the file-editing tool family.
    - `patch` currently hard-requires the target file to exist even though the
      underlying patch engine/parser supports new-file diffs; agents using diff
      workflows to create a new file will fail at the skill boundary.
    - `patch` silently applies only hunks matching the requested single target
      path when given a multi-file diff; that behavior is implementation-real
      but under-documented and is likely confusing for agent-generated
      multi-file patches.
    - `outline` returns success (not error) for unsupported file types with a
      "No outline parser" message, which likely makes fallback behavior worse.
    - `outline(symbol=...)` returns raw numbered source lines rather than an
      outline and interacts subtly with `depth`; this is only lightly
      documented and may confuse retries/tool chaining.
    - `read_file`/`outline(symbol=...)` numbered output plus the current docs
      likely creates a recurring exact-match failure loop for `edit_file` and
      diff-context generation, because the agent-facing contract does not warn
      against copying numbered views directly into edit inputs.
    - `patch` diagnostics expose parser/validation failures, but the
      user-facing guidance still underspecifies the behaviors that matter most
      to retries: single-target application, exact-path preference, existing-
      file requirement at the skill boundary, and the fact that multi-file
      diffs are only partially applied by design.
    - `edit_file` guidance still overstates atomic batched-edit behavior, which
      likely pushes agents toward a mode that is less reliable than described.
  - subagent audit wave status:
    - spawned explorers for edit-tool misuse, patch misuse, and outline misuse.
    - all three were interrupted due context pressure before returning usable
      summaries; no additional findings were preserved from that wave.
  - recommended next execution order for the usage-failure track:
    1. Update the agent-facing docs/prompts so `read_file` and
       `outline(symbol=...)` are explicitly described as numbered views, with
       a warning not to paste numbered lines directly into exact-match tools.
    2. Decide whether `patch` should accept `path` as an alias for `target`
       and whether new-file diffs should be supported at the skill boundary;
       otherwise document both constraints prominently.
    3. Change `outline` unsupported-file responses to a clearer fallback signal
       (preferably an error or explicit “use read_file instead” guidance).
    4. Reconcile `edit_file` batch-mode docs with real behavior before keeping
       it as the preferred multi-edit recommendation.
- Completed follow-on investigation checkpoint (2026-03-09, Windows Git
  Bash vs WSL command-routing audit; no code changes yet):
  - user reported a Windows-side transcript where an agent launched from Git
    Bash concluded its command executions were running in WSL2.
  - confirmed local code findings:
    - there is no general-purpose WSL proxy/routing layer in the codebase.
      Repo-wide search found no `wsl.exe` launch path in `nexus3/`.
    - `bash_safe` executes the requested argv directly via
      `asyncio.create_subprocess_exec(...)` on Windows, so it only runs WSL if
      the requested executable itself is a Windows WSL shim or explicitly
      invokes WSL.
    - `run_python` always executes `sys.executable -c ...`, so it stays in the
      same Python runtime family as the parent NEXUS process.
    - the likely misrouting point is `shell_UNSAFE` on Windows:
      `nexus3/skill/builtin/bash.py` checks parent `os.environ` for `MSYSTEM`
      and, when set, executes bare `bash -lc <command>` instead of resolving a
      known Git-for-Windows bash path. Because child subprocesses inherit the
      sanitized `PATH` from `get_safe_env(...)`, whichever Windows `bash.exe`
      wins PATH resolution is what runs.
    - if that resolved `bash.exe` is `C:\\Windows\\System32\\bash.exe` (WSL
      shim) instead of Git-for-Windows `bash.exe`, `shell_UNSAFE` can
      truthfully execute inside WSL even though the visible parent terminal is
      Git Bash.
  - practical conclusion:
    - this does not look like a pure hallucination path.
    - it also does not mean "NEXUS routes everything through WSL".
    - user-provided live Windows evidence now confirms the issue is isolated to
      `shell_UNSAFE`, not the whole process:
      - `run_python` reported native Windows Python and Git-for-Windows bash:
        `sys.platform=win32`, `platform.system()=Windows`, and
        `shutil.which("bash")=C:\\Program Files\\Git\\usr\\bin\\bash.EXE`.
      - `bash_safe` running `where.exe bash` also reported Git-for-Windows
        first, then `C:\\Windows\\System32\\bash.exe`.
      - `shell_UNSAFE` reported:
        `MSYSTEM=` (unset inside child), `/usr/bin/bash`,
        `Linux ... microsoft-standard-WSL2 ...`, and `/mnt/d/...`.
      - this proves the visible NEXUS process is Windows-native while the
        Windows `shell_UNSAFE` Git-Bash branch can still launch a WSL-backed
        shell subprocess.
    - strongest current explanation:
      - `shell_UNSAFE` chooses the Git-Bash-family branch based on parent
        `os.environ["MSYSTEM"]`, but then launches bare `bash -lc ...`.
      - child env comes from `get_safe_env(...)`, which omits `MSYSTEM`, so the
        child shell no longer has Git-Bash identity markers.
      - on Windows, bare executable resolution for subprocess creation appears
        to be selecting the WSL/System32 bash shim in this path even though
        PATH-oriented probes (`where.exe`, `shutil.which`) show Git-for-Windows
        first.
      - net: this is a real `shell_UNSAFE` Windows shell-selection bug.
  - recommended confirmation steps on the real Windows host:
    1. In the exact Git Bash session that launches NEXUS, compare
       `where.exe bash` and
       `.venv\\Scripts\\python.exe -c "import shutil; print(shutil.which('bash'))"`.
       If either resolves first to `C:\\Windows\\System32\\bash.exe`, the
       environment is primed for WSL handoff.
    2. Inside NEXUS, compare `run_python` reporting `sys.platform` /
       `shutil.which("bash")` against `shell_UNSAFE` reporting `uname -a` /
       `pwd`. If `run_python` stays Windows while `shell_UNSAFE` reports WSL,
       the issue is isolated to shell selection / PATH, not global process
       routing.
  - likely next fix if confirmed:
    - harden Windows `shell_UNSAFE` Git-Bash mode to resolve and launch an
      explicit Git-for-Windows bash path (or fail closed) instead of bare
      `bash`.
    - update docs because current guidance still describes `shell_UNSAFE` as
      generic `shell=True`, which hides the Windows-specific shell-family
      dispatch behavior and the ambiguity around bare `bash`.
  - additional live-testing note from user (2026-03-09):
    - in real Git Bash use, pressing `ESC` during REPL streaming did not
      cancel.
    - local code review strongly suggests this is a real Git-Bash/mintty
      input-path bug, not user error:
      - `nexus3/cli/keys.py` uses `termios` on Unix and falls back to
        `msvcrt.kbhit()/getwch()` on Windows.
      - Git Bash on Windows commonly runs under mintty rather than a native
        Win32 console, so `msvcrt` can exist while still not receiving the
        interactive keystream from the visible terminal window.
      - the current Windows validation artifact
        `docs/validation/post-m4-20260306-live1e/windows/live-check-output.json`
        only recorded `msvcrt` API availability (`kbhit/getwch` present), not a
        real live ESC cancellation pass in Git Bash. That means the
        `post-m4-20260306-live1e` closeout overstated coverage for this case.
    - likely follow-up:
      1. treat Git-Bash ESC failure as a real bug / validation gap;
      2. add a live Git Bash ESC reproduction note/test to
         `docs/testing/WINDOWS-LIVE-TESTING-GUIDE.md`;
      3. decide whether to implement a mintty-aware fallback or explicitly
         document Git Bash standalone as lacking ESC cancellation support until
         fixed.
    - additional real Git Bash input-path bug reported by user:
      - pasting multiline text into the REPL submits the first line
        immediately instead of inserting the full pasted block.
      - likely cause from local code review:
        - `nexus3/cli/repl.py` and `nexus3/cli/repl_runtime.py` construct a
          default single-line `PromptSession(...)` with no explicit multiline
          mode or custom paste/keybinding handling.
        - on terminals with working bracketed-paste support, prompt_toolkit can
          often preserve pasted newlines as one paste event; on Git Bash/mintty
          this support is likely absent or not wired through the Windows input
          path, so newline characters in the paste are treated like Enter and
          the first line is accepted/sent immediately.
      - practical implication:
        - this is probably another real Git Bash REPL bug / validation gap, not
          agent behavior.
      - likely follow-up:
        1. reproduce explicitly in Git Bash vs PowerShell/Windows Terminal;
        2. decide whether the REPL should support multiline input/paste
           robustly across shells or document Git Bash standalone as limited;
        3. if supporting it, add prompt-toolkit configuration/keybindings/tests
           rather than relying on terminal bracketed-paste behavior alone.
- Completed (2026-03-09, docs/status closeout wave):
  - clarified branch-scope status across `AGENTS.md`, `CLAUDE.md`, the
    milestone schedule, and the provider keep-alive plan so the remaining
    keep-alive item is presented as deferred external evidence only.
  - explicit status now says no additional architecture implementation slice
    is queued on this branch; resumption depends on WSL credentials/config for
    the keep-alive evidence checklist.
- Completed (2026-03-09, Plan C runtime-key test-setup hygiene closeout wave):
  - migrated remaining non-compat direct runtime-key test wiring to typed/compat
    APIs in:
    - `tests/security/test_arch_a2_path_decision.py`
    - `tests/security/test_p1_process_group_kill.py`
    - `tests/unit/session/test_session_cancellation.py`
    - `tests/unit/skill/test_nexus_create.py`
    - `tests/unit/skill/vcs/conftest.py`
    - `tests/unit/skill/vcs/test_gitlab_skills.py`
    - `tests/unit/test_git_skill.py`
    - `tests/unit/test_gitlab_toggle.py`
    - `tests/unit/test_new_skills.py`
    - `tests/unit/test_regex_replace_skill.py`
    - `tests/unit/test_skill_registry.py`
  - replaced direct `register("permissions", ...)` calls with
    `set_permissions(...)`.
  - replaced direct `register("cwd", ...)` calls with `set_cwd(...)`.
  - replaced direct `register("allowed_paths", ...)` calls with
    `register_runtime_compat("allowed_paths", ...)`.
  - updated `tests/unit/test_gitlab_toggle.py` mock services to inherit
    `ServiceContainer` so command tests continue using typed accessors.
  - focused validation passed:
    - `.venv/bin/ruff check tests/integration/test_clipboard.py tests/integration/test_file_editing_skills.py tests/integration/test_permission_enforcement.py tests/integration/test_skill_execution.py tests/security/test_arch_a2_path_decision.py tests/security/test_p1_process_group_kill.py tests/unit/session/test_session_cancellation.py tests/unit/skill/test_nexus_create.py tests/unit/skill/vcs/conftest.py tests/unit/skill/vcs/test_gitlab_skills.py tests/unit/test_git_skill.py tests/unit/test_gitlab_toggle.py tests/unit/test_new_skills.py tests/unit/test_regex_replace_skill.py tests/unit/test_skill_registry.py`
      passed.
    - `.venv/bin/pytest -q tests/security/test_arch_a2_path_decision.py tests/security/test_p1_process_group_kill.py tests/unit/session/test_session_cancellation.py tests/unit/skill/test_nexus_create.py tests/unit/skill/vcs/test_gitlab_skills.py tests/unit/test_git_skill.py tests/unit/test_gitlab_toggle.py tests/unit/test_new_skills.py tests/unit/test_regex_replace_skill.py tests/unit/test_skill_registry.py`
      (`279 passed`).
    - `.venv/bin/pytest -q tests/integration/test_clipboard.py tests/integration/test_permission_enforcement.py tests/integration/test_skill_execution.py`
      (`65 passed`).
    - `timeout 180 .venv/bin/pytest -q tests/integration/test_file_editing_skills.py`
      stalled without output in sandbox; unsandboxed rerun
      `.venv/bin/pytest -q tests/integration/test_file_editing_skills.py`
      passed (`17 passed`).
- Completed (2026-03-09, Plan C runtime-key test-setup hygiene wave 2):
  - migrated runtime-key test wiring to typed/compat APIs in:
    - `tests/unit/skill/test_clipboard_skills.py`
    - `tests/unit/skill/test_clipboard_extras.py`
    - `tests/unit/skill/test_clipboard_manage.py`
    - `tests/unit/skill/test_edit_file.py`
    - `tests/unit/skill/test_edit_lines.py`
    - `tests/unit/skill/test_skill_validation.py`
  - replaced direct `register("cwd", ...)` calls with `set_cwd(...)`.
  - replaced direct `register("allowed_paths", ...)` calls with
    `register_runtime_compat("allowed_paths", ...)` where applicable.
  - focused validation passed:
    - `.venv/bin/pytest -q tests/unit/skill/test_clipboard_skills.py tests/unit/skill/test_clipboard_extras.py tests/unit/skill/test_clipboard_manage.py tests/unit/skill/test_edit_file.py tests/unit/skill/test_edit_lines.py tests/unit/skill/test_skill_validation.py` (`154 passed`).
- Completed (2026-03-09, Plan C runtime-key test-setup hygiene wave):
  - migrated runtime-key test wiring to typed/compat APIs in:
    - `tests/unit/skill/test_concat_files.py`
    - `tests/unit/skill/test_glob_search.py`
    - `tests/unit/skill/test_grep_gateway.py`
    - `tests/unit/skill/test_outline.py`
    - `tests/unit/core/test_filesystem_access.py`
    - `tests/unit/skill/test_patch.py`
  - replaced direct `register("cwd", ...)` calls with `set_cwd(...)`.
  - replaced direct `register("allowed_paths", ...)` calls with
    `register_runtime_compat("allowed_paths", ...)`.
  - focused validation passed:
    - `.venv/bin/ruff check tests/unit/skill/test_concat_files.py tests/unit/skill/test_glob_search.py tests/unit/skill/test_grep_gateway.py tests/unit/skill/test_outline.py tests/unit/core/test_filesystem_access.py tests/unit/skill/test_patch.py` passed.
    - `.venv/bin/pytest -q tests/unit/skill/test_concat_files.py tests/unit/skill/test_glob_search.py tests/unit/skill/test_grep_gateway.py tests/unit/skill/test_outline.py tests/unit/core/test_filesystem_access.py tests/unit/skill/test_patch.py` (`214 passed`).
- Completed (2026-03-09, Plan C fixture-modernization closeout wave):
  - retired remaining legacy `MockServiceContainer` test doubles in:
    - `tests/unit/test_new_skills.py`
    - `tests/unit/test_regex_replace_skill.py`
    - `tests/unit/test_skill_enhancements.py`
    - `tests/unit/test_git_skill.py`
    - `tests/unit/skill/test_bash_windows_behavior.py`
    - `tests/security/test_p2_defense_in_depth.py`
  - each file now uses real `ServiceContainer` setup helpers and typed
    `set_cwd(...)` runtime mutation where cwd is configured.
  - focused validation passed:
    - `.venv/bin/pytest -q tests/unit/test_new_skills.py tests/unit/test_regex_replace_skill.py tests/unit/test_skill_enhancements.py tests/unit/test_git_skill.py tests/unit/skill/test_bash_windows_behavior.py tests/security/test_p2_defense_in_depth.py` (`105 passed`).
- Completed checkpoint (2026-03-09, committed `fd33b01`): Plan H
  shim-retirement Phase 3 canonical diagnostics follow-on:
  - retired compatibility remaps in RPC dispatcher/global-dispatcher/protocol
    for create/cancel/destroy ingress paths now covered by schema diagnostics.
  - updated focused ingress regressions in
    `tests/unit/rpc/test_schema_ingress_wiring.py`,
    `tests/unit/test_client.py`, and `tests/unit/test_global_dispatcher.py`.
- Completed (2026-03-09, Plan H closeout wave): Plan H shim-retirement
  closeout slice for `create_agent` canonical diagnostics:
  - retired remaining compatibility-only create-agent field wording remaps in
    `nexus3/rpc/global_dispatcher.py` so malformed fields now surface canonical
    schema diagnostics.
  - updated focused ingress expectations in
    `tests/unit/rpc/test_schema_ingress_wiring.py`.
  - focused validation passed:
    `.venv/bin/ruff check nexus3/rpc/global_dispatcher.py tests/unit/rpc/test_schema_ingress_wiring.py`,
    `.venv/bin/mypy nexus3/rpc/global_dispatcher.py`,
    `.venv/bin/pytest -q tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/test_client.py tests/unit/test_global_dispatcher.py tests/unit/test_rpc_dispatcher.py` (`138 passed`).
- Completed (2026-03-09, committed `5c0e843` and `8143afe`): Plan C
  service-container immutability follow-up (slices 1-3):
  - migrated pool create/restore + parent child-tracking runtime writes/reads
    to typed mutators/accessors in `nexus3/rpc/pool.py`.
  - migrated REPL/session runtime mutation/read paths to typed service APIs in
    `nexus3/cli/repl_commands.py` and `nexus3/session/session.py`.
  - hardened mutator compatibility in `nexus3/skill/services.py`:
    - `set_permissions(...)` now synchronizes/clears legacy `allowed_paths`.
    - runtime-key compatibility registration is now scoped through
      `register_runtime_compat(...)`.
  - expanded focused coverage in `tests/unit/test_pool.py`,
    `tests/unit/test_repl_commands.py`, and
    `tests/unit/skill/test_service_container_immutability.py`.
  - focused validation snapshot:
    - `.venv/bin/ruff check nexus3/rpc/pool.py nexus3/cli/repl_commands.py nexus3/session/session.py nexus3/skill/services.py tests/unit/test_pool.py tests/unit/test_repl_commands.py tests/unit/skill/test_service_container_immutability.py` passed.
    - `.venv/bin/mypy nexus3/rpc/pool.py nexus3/cli/repl_commands.py nexus3/session/session.py nexus3/skill/services.py` passed.
    - `.venv/bin/pytest -q tests/unit/test_repl_commands.py tests/unit/test_pool.py tests/unit/skill/test_service_container_immutability.py tests/unit/session/test_session_cancellation.py tests/unit/session/test_session_permission_kernelization.py` passed (`168 passed`).
- Completed (2026-03-09, committed `b09c079`): Plan H shim-retirement
  Phase 2:
  - retired compatibility-only `create_agent` malformed-ID message remap
    prefix stripping in `nexus3/rpc/global_dispatcher.py` for malformed
    `agent_id` and `parent_agent_id` string inputs.
  - handler now surfaces canonical schema-derived validation detail directly
    while preserving deterministic type diagnostics.
  - updated focused ingress regressions in
    `tests/unit/rpc/test_schema_ingress_wiring.py`.
- Completed (2026-03-06, committed `5c9c0e2`): Plan A v2 kickoff
  Phase 1 (typed create-context foundation):
  - added typed create-stage authorization context/stage models in
    `nexus3/core/authorization_kernel.py` with scalar-wire compatibility.
  - wired `nexus3/rpc/pool.py` create authorization flow to
    `CreateAuthorizationContext` / `CreateAuthorizationStage` (no behavior flip).
  - added focused context-shape regressions in
    `tests/unit/core/test_authorization_kernel.py`.
- Completed (2026-03-06, committed `0a4f99f`): Plan A v2 follow-on
  Phase 2 + 3:
  - `_CreateAuthorizationAdapter` now computes base/delta grant decisions
    adapter-locally from typed create context permission payloads
    (`parent_permissions_json`, `requested_permissions_json`).
  - removed create-stage `parent_can_grant` precompute plumbing from
    `AgentPool._create_unlocked()` and `_enforce_create_authorization()`
    call sites.
  - added focused adapter-authoritative create regressions in
    `tests/unit/rpc/test_pool_create_auth_shadow.py` and extended stage-context
    assertions in `tests/unit/test_pool.py`.
  - focused validation:
    - passed: `ruff` + `mypy`.
    - passed: focused non-`tmp_path` pytest set for typed context and
      adapter-ceiling checks.
    - blocked: broader `tmp_path`-using pytest coverage in this host due
      `WinError 5` ACL denials on pytest temp-root paths (`pytest-of-inc`).
- Completed (2026-03-06, committed `f22de38`): Plan H shim-retirement kickoff
  slice:
  - retired compatibility-only `create_agent.parent_agent_id` malformed-ID
    wording remap in `nexus3/rpc/global_dispatcher.py`
    (`Parent agent not found: <raw>` -> canonical validation detail).
  - updated focused ingress regression expectation in
    `tests/unit/rpc/test_schema_ingress_wiring.py`.
  - documented shim inventory + canonical diagnostics policy and first
    retirement slice execution in
    `docs/plans/ARCH-H-RPC-ERROR-SHIM-RETIREMENT-PLAN-2026-03-05.md`.
  - updated deferred backlog status and RPC diagnostics notes in
    `docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md` and
    `nexus3/rpc/README.md`.
  - focused validation:
    - `.venv/Scripts/ruff.exe check nexus3/rpc/global_dispatcher.py tests/unit/rpc/test_schema_ingress_wiring.py` passed.
    - `.venv/Scripts/mypy.exe nexus3/rpc/global_dispatcher.py` passed.
    - `.venv/Scripts/pytest.exe -q -p no:cacheprovider tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/test_rpc_dispatcher.py tests/unit/test_global_dispatcher.py tests/unit/test_client.py` passed.
- Plan F Phase 1 is committed as `1079cd7` (`plan f phase 1: add ast v2 foundation and baseline fixtures`).
- Plan F Phase 2 is committed as `4ded3fa` (`plan f phase 2: add byte-strict ast-v2 apply path`).
- Plan F Phase 3 is committed as `4c10b0b` (`plan f phase 3: wire legacy vs byte_strict skill mode`).
- Plan F Phase 4 is committed as `a342401` (`plan f phase 4: fail closed on ambiguous patch targets`).
- Plan F Phase 5 is committed as `87c5df1` (`plan f phase 5: add non-utf8 byte-strict fidelity regressions`).
- Plan F Phase 6 is committed as `195ab86` (`plan f phase 6: default patch skill to byte_strict`).
- Plan F Phase 7 is committed as `6e946cf` (`plan f phase 7: retire patch legacy runtime path`).
- Plan E Phase 1 is committed as `e9d6c3e` (`plan e phase 1: add context compiler ir foundation`).
- Plan E Phase 2 is committed as `e3cd304`
  (`plan e phase 2: integrate compiler into session and providers`).
- Plan E Phase 3 is committed as `5632652`
  (`plan e phase 3: add context graph prototype`).
- Plan E Phase 4 is committed as `00c59ed`
  (`plan e phase 4: migrate compaction and truncation to graph pipeline`).
- Plan B Phase 1 is committed as `14bc820`
  (`plan b phase 1: add capability token primitives`).
- Plan B Phase 2 is committed as `43773be`
  (`plan b phase 2: integrate capabilities into direct rpc path`).
- Plan B Phase 3A is committed as `6b65b17`
  (`plan b phase 3a: add http capability transport wiring`):
  - `nexus3/rpc/http.py`: optional `X-Nexus-Capability` header extraction and
    `capability_token` pass-through on global + agent dispatch routes.
  - `nexus3/client.py`: optional explicit `capability_token` client plumbing
    that emits `X-Nexus-Capability` only when configured.
  - `nexus3/rpc/README.md`: HTTP capability semantics + fallback precedence docs.
  - tests: focused HTTP/client wiring regressions for capability-present,
    capability-invalid (`INVALID_PARAMS`), and requester-only fallback flows.
- Plan B Phase 4A is committed as `2cb4817`
  (`plan b phase 4a: add legacy requester fallback telemetry`):
  - `nexus3/rpc/http.py`: emit explicit warning telemetry when deprecated
    requester-only `X-Nexus-Agent` fallback is used without
    `X-Nexus-Capability`.
  - behavior remains compatibility-preserving in this slice
    (requester-only fallback still accepted).
  - docs aligned in `nexus3/rpc/README.md` and
    `docs/plans/ARCH-B-CAPABILITY-TOKENS-PLAN-2026-03-02.md`.
  - focused regression coverage in `tests/unit/test_http_pipeline_layers.py`
    for warning/no-warning paths + unchanged dispatch forwarding.
- Plan B Phase 4B is committed as `ffb8b87`
  (`plan b phase 4b: enforce capability-first http requester identity`):
  - `nexus3/rpc/http.py`: requester-only `X-Nexus-Agent` ingress is now rejected
    unless `X-Nexus-Capability` is also present.
  - deterministic JSON-RPC `INVALID_PARAMS` error returned for requester-only
    header usage.
  - `nexus3/rpc/README.md` + Plan B/schedule docs updated to reflect legacy
    header-path removal semantics.
  - focused regressions in `tests/unit/test_http_pipeline_layers.py` enforce:
    requester-only rejection, capability-present forwarding, invalid-capability
    behavior parity.
- Completed (2026-03-06, committed `34c2f67`): post-M4 validation campaign
  Phase 1/2 bootstrap:
  - added canonical runbook:
    `docs/testing/POST-M4-VALIDATION-RUNBOOK.md`
  - added artifact schema/index:
    `docs/validation/README.md`
  - added campaign harness scripts:
    `scripts/validation/soak_workload.py`,
    `scripts/validation/race_harness.py`,
    `scripts/validation/terminal_payload_matrix.py`
- Completed (2026-03-06, committed `59dab71`): post-M4 validation campaign
  first live execution slice (`post-m4-20260306-live1b`):
  - preflight gates passed:
    `.venv/bin/ruff check nexus3/`,
    `.venv/bin/mypy nexus3/`,
    `.venv/bin/pytest tests/unit -q`,
    `.venv/bin/pytest tests/security -q`
  - soak track passed:
    `docs/validation/post-m4-20260306-live1b/soak/verdict.json`
  - race track executed with non-security failure-rate finding:
    `docs/validation/post-m4-20260306-live1b/race/verdict.json`
    (`failure rate 13.333%`, `security_failures=0`)
  - terminal track passed with manual emulator follow-up warning:
    `docs/validation/post-m4-20260306-live1b/terminal/verdict.json`
  - findings/issues placeholders recorded:
    `docs/validation/post-m4-20260306-live1b/findings.md`,
    `docs/validation/post-m4-20260306-live1b/issue-links.md`
  - windows track recorded as pending real-host execution:
    `docs/validation/post-m4-20260306-live1b/windows/`
  - note: initial sandboxed harness runs (`post-m4-20260306-live1`) produced
    false "No NEXUS3 server running" negatives due nested subprocess sandbox
    constraints; live soak/race reruns used unsandboxed execution.
- Completed (2026-03-06, committed `fa1c66a`): retained artifact docs committed
  for compact continuity:
  - `docs/validation/post-m4-bootstrap-dryrun/`
  - `docs/validation/post-m4-20260306-live1/`
  - `docs/validation/post-m4-20260306-live2/`
- Completed (2026-03-09, committed `05ffb84`): deferred provider keep-alive
  investigation kickoff:
  - added stale/reused-connection classification + bounded cached-client
    recycle retry path in `nexus3/provider/base.py` for non-streaming and
    streaming flows.
  - added focused regressions in
    `tests/unit/provider/test_keepalive_recovery.py`.
  - extended Step 10 diagnostics in `scripts/diagnose-empty-stream.sh` with
    machine-readable evidence output (`10-keepalive-evidence.json`).
  - synced provider keep-alive closeout docs in:
    `docs/plans/PROVIDER-KEEPALIVE-INVESTIGATION-PLAN-2026-03-05.md`,
    `docs/plans/PROVIDER-BUGFIX-PLAN.md`,
    `AGENTS_NEXUS3CONFIGOPS.md`,
    `nexus3/provider/README.md`,
    `CLAUDE.md`.
  - operational defer note (2026-03-09, WSL): real-endpoint evidence capture
    is explicitly deferred pending endpoint credentials/config availability in
    the current WSL environment.
  - this is an operational defer only (no code rollback).
  - reminder checklist for resumption:
    1. configure one known-problematic endpoint+model and one known-good
       endpoint+model.
    2. set required API key environment variables for both endpoints.
    3. run `scripts/diagnose-empty-stream.sh` Step 10 flow.
    4. archive `10-keepalive-evidence.json` artifacts and link run IDs in
       status docs (`AGENTS.md`, `CLAUDE.md`, and milestone/plan docs).
- Completed (2026-03-09, DRY cleanup P2 default-port consolidation):
  - added canonical default-port resolver in `nexus3/core/constants.py`
    (`DEFAULT_SERVER_PORT`, `get_default_server_port()`).
  - updated `nexus3/client.py`, `nexus3/cli/client_commands.py`, and
    `nexus3/skill/base.py` to delegate duplicated default-port resolution to
    the canonical helper.
  - updated `get_rpc_token_path()` to use `DEFAULT_SERVER_PORT` instead of a
    hardcoded literal.
  - focused validation passed:
    - `.venv/bin/ruff check nexus3/core/constants.py nexus3/client.py nexus3/cli/client_commands.py nexus3/skill/base.py`
    - `.venv/bin/mypy nexus3/core/constants.py nexus3/client.py nexus3/cli/client_commands.py nexus3/skill/base.py`
    - `.venv/bin/pytest -q tests/unit/test_client.py tests/unit/cli/test_client_commands_safe_sink.py tests/unit/test_nexus_skill_requester_propagation.py tests/unit/test_auth.py -k "port or default or auto_auth or requester"` (`12 passed, 52 deselected`).
- Completed (2026-03-09, structural-refactor kickoff): extraction map baseline
  documented in
  `docs/plans/STRUCTURAL-REFACTOR-WAVE-PLAN-2026-03-05.md`:
  - established old->new ownership map for REPL/session/pool/display slices.
  - documented façade compatibility-boundary policy and extraction order.
  - checked off the plan’s extraction-map checklist item.
- Completed (2026-03-09, structural-refactor Phase 1A): REPL formatting-helper
  extraction:
  - extracted formatting/sanitization helpers into
    `nexus3/cli/repl_formatting.py` while keeping `nexus3/cli/repl.py` as a
    façade import surface.
  - focused validation passed:
    `.venv/bin/ruff check nexus3/cli/repl.py nexus3/cli/repl_formatting.py`,
    `.venv/bin/mypy nexus3/cli/repl.py nexus3/cli/repl_formatting.py`,
    `.venv/bin/pytest -q tests/unit/cli/test_repl_safe_sink.py tests/unit/test_repl_commands.py`
    (`97 passed`).
- Completed (2026-03-09, structural-refactor Phase 1B): REPL runtime/client-discovery
  and reload-helper extraction:
  - extracted runtime/client-discovery helpers into
    `nexus3/cli/repl_runtime.py`.
  - extracted reload helper into `nexus3/cli/repl_reload.py`.
  - retained façade-compatible symbols/imports in `nexus3/cli/repl.py`.
  - focused validation passed:
    `.venv/bin/ruff check nexus3/cli/repl.py nexus3/cli/repl_runtime.py nexus3/cli/repl_reload.py`,
    `.venv/bin/mypy nexus3/cli/repl.py nexus3/cli/repl_runtime.py nexus3/cli/repl_reload.py`,
    `.venv/bin/pytest -q tests/unit/cli/test_repl_safe_sink.py tests/unit/test_repl_commands.py tests/unit/cli/test_connect_lobby_safe_sink.py tests/unit/test_client.py`
    (`125 passed`).
- Completed (2026-03-09, structural-refactor Phase 2A): Session compaction
  runtime helper extraction:
  - added `nexus3/session/compaction_runtime.py` and moved compaction provider
    and summary helper internals there.
  - kept `Session._get_compaction_provider(...)` and
    `Session._generate_summary(...)` as thin wrappers for compatibility.
  - behavior parity preserved: lazy provider creation, compaction cache
    semantics, and logger lifecycle.
  - focused validation passed:
    `.venv/bin/ruff check nexus3/session/session.py nexus3/session/compaction_runtime.py tests/unit/session/test_session_cancellation.py tests/unit/session/test_enforcer.py tests/unit/session/test_session_permission_kernelization.py tests/unit/test_compaction.py tests/unit/test_context_manager.py tests/unit/context/test_graph.py tests/unit/context/test_compiler.py tests/unit/context/test_compile_baseline.py`,
    `.venv/bin/mypy nexus3/session/session.py nexus3/session/compaction_runtime.py`,
    `.venv/bin/pytest -q tests/unit/session/test_session_cancellation.py tests/unit/session/test_enforcer.py tests/unit/session/test_session_permission_kernelization.py` (`54 passed`),
    `.venv/bin/pytest -q tests/unit/test_compaction.py tests/unit/test_context_manager.py tests/unit/context/test_graph.py tests/unit/context/test_compiler.py tests/unit/context/test_compile_baseline.py` (`75 passed`).
- Completed (2026-03-09, structural-refactor Phase 2B): Session tool-execution
  primitives extraction:
  - added `nexus3/session/tool_runtime.py` and moved tool execution primitives
    there.
  - kept `Session._execute_skill(...)` and
    `Session._execute_tools_parallel(...)` as thin wrappers for compatibility.
  - behavior parity preserved: timeout handling, exception mapping, and
    sanitization semantics.
  - focused validation passed:
    `.venv/bin/ruff check nexus3/session/session.py nexus3/session/compaction_runtime.py nexus3/session/tool_runtime.py`,
    `.venv/bin/mypy nexus3/session/session.py nexus3/session/compaction_runtime.py nexus3/session/tool_runtime.py`,
    `.venv/bin/pytest -q tests/unit/session/test_session_cancellation.py tests/unit/session/test_enforcer.py tests/unit/session/test_session_permission_kernelization.py` (`54 passed`),
    `.venv/bin/pytest -q tests/integration/test_skill_execution.py tests/integration/test_permission_enforcement.py` (`30 passed`).
- Completed (2026-03-09, structural-refactor Phase 2C): Session permission
  runtime extraction:
  - added `nexus3/session/permission_runtime.py`.
  - moved `_McpLevelAuthorizationAdapter`,
    `_GitLabLevelAuthorizationAdapter`, and internals of
    `_handle_mcp_permissions(...)` / `_handle_gitlab_permissions(...)` into
    runtime helpers.
  - kept `Session` permission-handling methods as thin wrappers for
    compatibility.
  - behavior parity preserved for kernel-authoritative decisions and
    confirmation flows.
  - focused validation passed:
    `.venv/bin/ruff check nexus3/session/session.py nexus3/session/compaction_runtime.py nexus3/session/tool_runtime.py nexus3/session/permission_runtime.py`,
    `.venv/bin/mypy nexus3/session/session.py nexus3/session/compaction_runtime.py nexus3/session/tool_runtime.py nexus3/session/permission_runtime.py`,
    `.venv/bin/pytest -q tests/unit/session/test_session_permission_kernelization.py tests/unit/session/test_enforcer.py tests/unit/session/test_session_cancellation.py` (`54 passed`),
    `.venv/bin/pytest -q tests/integration/test_permission_enforcement.py tests/integration/test_skill_execution.py` (`30 passed`).
- Completed (2026-03-09, structural-refactor Phase 2D): Session single-tool
  runtime extraction:
  - added `nexus3/session/single_tool_runtime.py`.
  - moved single-tool execution internals there while keeping
    `Session._execute_single_tool(...)` as a thin compatibility wrapper.
  - behavior parity preserved: permissions fail-closed, enforcer checks and
    confirmation flow (including multi-path allowances), skill
    resolution/unknown-skill handling, malformed `_raw_arguments` handling,
    argument validation, effective timeout derivation, and MCP/GitLab
    permission delegation.
  - focused validation passed:
    `.venv/bin/ruff check nexus3/session/session.py nexus3/session/compaction_runtime.py nexus3/session/tool_runtime.py nexus3/session/permission_runtime.py nexus3/session/single_tool_runtime.py`,
    `.venv/bin/mypy nexus3/session/session.py nexus3/session/compaction_runtime.py nexus3/session/tool_runtime.py nexus3/session/permission_runtime.py nexus3/session/single_tool_runtime.py`,
    `.venv/bin/pytest -q tests/unit/session/test_session_permission_kernelization.py tests/unit/session/test_enforcer.py tests/unit/session/test_session_cancellation.py` (`54 passed`),
    `.venv/bin/pytest -q tests/integration/test_permission_enforcement.py tests/integration/test_skill_execution.py` (`30 passed`).
- Completed (2026-03-09, structural-refactor Phase 2E): Session streaming
  runtime extraction:
  - added `nexus3/session/streaming_runtime.py`.
  - moved callback-adapter streaming internals there while keeping
    `Session._execute_tool_loop_streaming(...)` as a thin compatibility
    wrapper.
  - behavior parity preserved: event->callback mapping and yielded chunk
    semantics remain unchanged.
  - focused validation passed:
    `.venv/bin/ruff check nexus3/session/session.py nexus3/session/streaming_runtime.py`,
    `.venv/bin/mypy nexus3/session/session.py nexus3/session/streaming_runtime.py`,
    `.venv/bin/pytest -q tests/integration/test_skill_execution.py -k "test_tool_call_executes_skill or test_multiple_tool_calls_in_sequence or test_multiple_tool_calls_in_parallel or test_failing_skill_error_in_context or test_max_iterations_prevents_infinite_loop or test_tool_loop_builds_correct_messages"` (`6 passed`),
    `.venv/bin/pytest -q tests/unit/session/test_session_cancellation.py -k "test_stale_cancelled_tools_are_dropped or test_cancelled_tool_tail_repaired_before_next_user_turn or test_preflight_repairs_orphaned_tool_batch_before_user_turn or test_preflight_prunes_stale_tool_results_before_user_turn"` (`4 passed`),
    `.venv/bin/pytest -q tests/unit/session/test_session_cancellation.py -k "test_cancellation_before_assistant_message_no_orphans or test_cancellation_after_first_tool_adds_remaining_results or test_cancelled_error_during_tool_creates_result"` (`3 passed`).
- Completed (2026-03-09, structural-refactor Phase 2F): Session tool-loop
  events runtime extraction:
  - added `nexus3/session/tool_loop_events_runtime.py`.
  - moved `_execute_tool_loop_events(...)` internals there while keeping
    `Session._execute_tool_loop_events(...)` as a thin compatibility wrapper.
  - `send(...)` / `run_turn(...)` call paths are unchanged in this slice.
  - focused validation passed:
    `.venv/bin/ruff check nexus3/session/session.py nexus3/session/tool_loop_events_runtime.py`,
    `.venv/bin/mypy nexus3/session/session.py nexus3/session/tool_loop_events_runtime.py`,
    `.venv/bin/pytest -q tests/unit/session/test_session_cancellation.py tests/unit/session/test_session_permission_kernelization.py tests/unit/session/test_enforcer.py` (`54 passed`),
    `.venv/bin/pytest -q tests/integration/test_skill_execution.py tests/integration/test_permission_enforcement.py` (`30 passed`).
  - live smoke passed:
    `NEXUS_DEV=1 .venv/bin/python -m nexus3 --serve 9000`,
    `.venv/bin/python -m nexus3 rpc create test-agent --port 9000`,
    `.venv/bin/python -m nexus3 rpc send test-agent "describe your permissions and what you can do" --port 9000`,
    `.venv/bin/python -m nexus3 rpc destroy test-agent --port 9000`,
    `.venv/bin/python -m nexus3 rpc shutdown --port 9000`.
- Completed (2026-03-09, structural-refactor Phase 2G): Session turn-entry
  runtime extraction:
  - added `nexus3/session/turn_entry_runtime.py`.
  - `send(...)` and `run_turn(...)` now use
    `prepare_turn_entry(...)` for shared context-mode preflight/reset path.
  - behavior parity preserved; tool-loop runtime behavior is unchanged in this
    slice.
  - focused validation passed:
    `.venv/bin/ruff check nexus3/session/session.py nexus3/session/turn_entry_runtime.py`,
    `.venv/bin/mypy nexus3/session/session.py nexus3/session/turn_entry_runtime.py`,
    `.venv/bin/pytest -q tests/unit/session/test_session_cancellation.py` (`12 passed`),
    `.venv/bin/pytest -q tests/integration/test_skill_execution.py tests/integration/test_permission_enforcement.py tests/integration/test_chat.py` (`40 passed, 2 skipped`).
  - live smoke passed:
    `NEXUS_DEV=1 .venv/bin/python -m nexus3 --serve 9000`,
    `.venv/bin/python -m nexus3 rpc create test-agent --port 9000`,
    `.venv/bin/python -m nexus3 rpc send test-agent "describe your permissions and what you can do" --port 9000`,
    `.venv/bin/python -m nexus3 rpc destroy test-agent --port 9000`,
    `.venv/bin/python -m nexus3 rpc shutdown --port 9000`.
- Completed (2026-03-09, structural-refactor Phase 2H): Session simple-turn
  runtime extraction:
  - added `nexus3/session/simple_turn_runtime.py`.
  - extracted and centralized non-tool simple streaming internals shared by
    `send(...)` and `run_turn(...)`.
  - `send(...)` / `run_turn(...)` now delegate non-tool simple paths to
    `execute_simple_send(...)` / `execute_simple_run_turn(...)` while
    preserving cancellation and empty-response semantics.
  - focused validation passed:
    `.venv/bin/ruff check nexus3/session/session.py nexus3/session/simple_turn_runtime.py nexus3/session/README.md`,
    `.venv/bin/mypy nexus3/session/session.py nexus3/session/simple_turn_runtime.py`,
    `.venv/bin/pytest -q tests/unit/session/test_session_cancellation.py tests/integration/test_chat.py` (`22 passed, 2 skipped`).
- Completed (2026-03-09, structural-refactor Phase 3A): Pool visibility
  extraction:
  - added `nexus3/rpc/pool_visibility.py`.
  - extracted MCP/GitLab visibility adapters and helper internals there.
  - kept `AgentPool` visibility methods as thin wrappers for compatibility.
  - focused validation passed:
    `.venv/bin/ruff check nexus3/rpc/pool.py nexus3/rpc/pool_visibility.py`,
    `.venv/bin/mypy nexus3/rpc/pool.py nexus3/rpc/pool_visibility.py`,
    `.venv/bin/pytest -q tests/unit/test_pool.py -k "mcp_visibility or gitlab_visibility"` (`4 passed`).
- Completed (2026-03-09, structural-refactor Phase 4A): display no-op override
  cleanup:
  - simplified `nexus3/display/theme.py` to `load_theme() -> Theme`,
    removing no-op override argument path with runtime parity preserved.
  - updated `nexus3/display/README.md` and `tests/unit/test_display.py` for
    the canonical theme-loader contract.
  - focused validation passed:
    `.venv/bin/ruff check nexus3/display/theme.py nexus3/display/README.md tests/unit/test_display.py`,
    `.venv/bin/mypy nexus3/display/theme.py nexus3/cli/repl.py nexus3/display/manager.py nexus3/display/spinner.py`,
    `.venv/bin/pytest -q tests/unit/test_display.py tests/unit/display/test_safe_sink.py tests/unit/display/test_escape_sanitization.py` (`137 passed`).
- Completed (2026-03-09, structural-refactor Phase 3B): pool create-path
  extraction foundation:
  - added `nexus3/rpc/pool_create.py`.
  - extracted create authorization adapter + lock-wrapper/runtime helper
    internals there.
  - `AgentPool.create(...)`, `create_temp(...)`, and
    create-authorization enforcement now delegate to extracted helpers.
  - focused validation passed:
    `.venv/bin/ruff check nexus3/rpc/pool.py nexus3/rpc/pool_create.py`,
    `.venv/bin/mypy nexus3/rpc/pool.py nexus3/rpc/pool_create.py`,
    `.venv/bin/pytest -q tests/unit/rpc/test_pool_create_auth_shadow.py tests/unit/test_auto_restore.py tests/unit/test_pool.py -k "create_ or create_temp or restore_ or get_or_restore or mcp_visibility or gitlab_visibility"` (`43 passed`).
- Completed (2026-03-09, structural-refactor Phase 3C): pool restore-path
  extraction:
  - added `nexus3/rpc/pool_restore.py`.
  - moved restore internals (`get_or_restore(...)`,
    `_restore_unlocked(...)`, `restore_from_saved(...)`) to
    dependency-injected runtime helpers while keeping compatibility wrappers in
    `pool.py`.
  - focused validation passed:
    `.venv/bin/ruff check nexus3/rpc/pool.py nexus3/rpc/pool_restore.py`,
    `.venv/bin/mypy nexus3/rpc/pool.py nexus3/rpc/pool_restore.py`,
    `.venv/bin/pytest -q tests/unit/rpc/test_pool_create_auth_shadow.py tests/unit/test_auto_restore.py tests/unit/test_pool.py -k "create_ or create_temp or restore_ or get_or_restore or mcp_visibility or gitlab_visibility"` (`43 passed`),
    `.venv/bin/pytest -q tests/integration/test_permission_inheritance.py tests/integration/test_sandboxed_parent_send.py` (`51 passed`).
- Completed (2026-03-09, structural-refactor Phase 3D): pool lifecycle
  extraction:
  - added `nexus3/rpc/pool_lifecycle.py`.
  - extracted lifecycle internals there: destroy authorization + teardown flow,
    capability issue/verify/revoke helpers, and pool accessor helpers.
  - `pool.py` now retains thin compatibility wrappers that delegate to
    lifecycle helpers.
  - focused validation passed:
    `.venv/bin/ruff check nexus3/rpc/pool.py nexus3/rpc/pool_lifecycle.py nexus3/rpc/pool_create.py nexus3/rpc/pool_restore.py nexus3/rpc/pool_visibility.py`,
    `.venv/bin/mypy nexus3/rpc/pool.py nexus3/rpc/pool_lifecycle.py nexus3/rpc/pool_create.py nexus3/rpc/pool_restore.py nexus3/rpc/pool_visibility.py`,
    `.venv/bin/pytest -q tests/unit/test_pool.py tests/unit/test_auto_restore.py tests/unit/rpc/test_pool_create_auth_shadow.py -k "destroy_ or capability or should_shutdown or list_returns_agent_info_dicts or get_returns_ or len_returns_agent_count or contains_checks_agent_id or mcp_visibility or gitlab_visibility or create_ or create_temp or restore_ or get_or_restore"` (`70 passed`),
    `.venv/bin/pytest -q tests/unit/test_agent_api.py tests/unit/test_rpc_dispatcher.py tests/unit/test_global_dispatcher.py` (`62 passed`),
    `.venv/bin/pytest -q tests/integration/test_permission_inheritance.py tests/integration/test_sandboxed_parent_send.py` (`51 passed`).
- Completed (2026-03-09, structural-refactor wrapper-cleanup wave):
  - removed Session compaction wrappers
    `_get_compaction_provider(...)` and `_generate_summary(...)`; `compact()`
    now calls `compaction_runtime.generate_summary(...)` directly.
  - removed Session loop wrappers `_execute_tool_loop_events(...)` and
    `_execute_tool_loop_streaming(...)`; `send(...)` / `run_turn(...)` now call
    runtime functions directly.
  - removed pool capability-state passthrough wrappers and now build capability
    lifecycle state inline at call sites.
  - removed restore dependency-builder wrappers and `_restore_unlocked` shim in
    `nexus3/rpc/pool.py`; `pool_restore.get_or_restore(...)` and
    `pool_restore.restore_from_saved(...)` now take `shared` + `runtime` and
    invoke `_restore_unlocked(...)` internally.
  - removed `pool.py` wrappers `_destroy_unlocked(...)`,
    `_enforce_create_authorization(...)`, `_is_mcp_visible_for_agent(...)`, and
    `_is_gitlab_visible_for_agent(...)`; wiring now calls extracted runtime
    helpers directly.
- Completed (2026-03-09, structural-refactor Session wrapper-retirement
  closeout):
  - removed remaining Session wrappers `_execute_single_tool(...)`,
    `_handle_mcp_permissions(...)`, `_handle_gitlab_permissions(...)`,
    `_execute_skill(...)`, and `_execute_tools_parallel(...)`.
  - `send(...)` / `run_turn(...)` now build explicit runtime callables and pass
    them to `execute_tool_loop_events(...)`.
  - `tool_loop_events_runtime.execute_tool_loop_events(...)` now accepts
    explicit `execute_tools_parallel` and `execute_single_tool` callables.
  - kernelization tests now call permission runtime helpers directly.
  - focused validation snapshot:
    - `.venv/bin/ruff check nexus3/session/session.py nexus3/session/tool_loop_events_runtime.py nexus3/session/single_tool_runtime.py nexus3/session/tool_runtime.py nexus3/session/README.md tests/unit/session/test_session_permission_kernelization.py tests/integration/test_permission_enforcement.py` passed.
    - `.venv/bin/mypy nexus3/session/session.py nexus3/session/tool_loop_events_runtime.py nexus3/session/single_tool_runtime.py nexus3/session/tool_runtime.py` passed.
    - `.venv/bin/pytest -q tests/unit/test_compaction.py tests/unit/session/test_session_cancellation.py tests/unit/session/test_session_permission_kernelization.py tests/unit/test_pool.py tests/unit/test_auto_restore.py tests/unit/rpc/test_pool_create_auth_shadow.py tests/unit/test_agent_api.py tests/unit/test_rpc_dispatcher.py tests/unit/test_global_dispatcher.py` passed (`213 passed`).
    - `.venv/bin/pytest -q tests/integration/test_permission_enforcement.py tests/integration/test_skill_execution.py tests/integration/test_chat.py tests/integration/test_permission_inheritance.py tests/integration/test_sandboxed_parent_send.py` passed (`91 passed, 2 skipped`).
- Execution status: architecture implementation backlog is complete for the
  current branch scope. Plan C optional test-hygiene backlog is closed except
  for the intentional legacy-compat coverage in
  `tests/unit/skill/test_service_container_immutability.py`; only deferred
  external provider keep-alive evidence remains pending endpoint
  credentials/config availability in the current WSL environment.
  - decision note (2026-03-09): if the deferred keep-alive evidence is clean,
    it closes the final remaining branch-scope checkbox; if it reveals a real
    failure, handle that as a standalone bugfix follow-up rather than reopening
    the architecture execution backlog.
- Next gate after credentials/config are available: execute the reminder
  checklist above and link run IDs/artifacts in status docs.
- Active architecture track: no additional architecture implementation slice is
  currently queued. Provider keep-alive real-endpoint evidence remains an
  operationally deferred external follow-up pending credentials/config.
- Completed (2026-03-06, committed `abef28a`): race follow-up slice
  (`post-m4-20260306-live1c`):
  - updated `scripts/validation/race_harness.py` with
    `--exclude-expected-contention-errors` to gate on unexpected failures
    while still reporting raw contention churn.
  - race follow-up run passed:
    `docs/validation/post-m4-20260306-live1c/race/verdict.json`
    (`security_failures=0`, raw contention failures explicitly reported).
  - updated post-M4 docs to record contention-aware race gating and follow-up
    evidence (`POST-M4-VALIDATION-RUNBOOK.md`, plan/schedule, validation
    README).
- Completed (2026-03-06, committed `055dcb6`): terminal follow-up refresh
  slice (`post-m4-20260306-live1d`):
  - reran `scripts/validation/terminal_payload_matrix.py` for a fresh terminal
    artifact set under `docs/validation/post-m4-20260306-live1d/terminal/`.
  - recorded terminal-only follow-up findings + issue mapping stubs in
    `docs/validation/post-m4-20260306-live1d/{findings.md,issue-links.md}`.
  - terminal strict checks remain green (`strict_failures=0`) while
    manual follow-up remains open (`manual_follow_up_cases=1`) for
    carriage-return multi-emulator behavior.
- Completed (2026-03-06, committed `5487d43`): follow-up tracker mapping slice:
  - added canonical follow-up map
    `docs/plans/POST-M4-VALIDATION-FOLLOWUP-TRACKER-2026-03-06.md`
    with stable IDs for race/terminal/windows follow-ups.
  - replaced `TBD-*` placeholders in
    `docs/validation/post-m4-20260306-live1b/issue-links.md`,
    `docs/validation/post-m4-20260306-live1c/issue-links.md`, and
    `docs/validation/post-m4-20260306-live1d/issue-links.md`.
  - updated `docs/validation/post-m4-20260306-live1b/findings.md` with
    explicit owner roles + target windows aligned to tracker entries.
- Completed (2026-03-06, committed `ad53962`): closeout-gate tooling slice:
  - added `scripts/validation/post_m4_closeout_gate.py` to evaluate campaign
    closure state across soak/race/terminal/windows artifacts + tracker status.
  - added focused regressions in
    `tests/unit/validation/test_post_m4_closeout_gate.py`.
  - focused validation passed:
    - `.venv/bin/ruff check scripts/validation/post_m4_closeout_gate.py tests/unit/validation/test_post_m4_closeout_gate.py`
    - `.venv/bin/mypy scripts/validation/post_m4_closeout_gate.py`
    - `.venv/bin/pytest -q tests/unit/validation/test_post_m4_closeout_gate.py` (`2 passed`)
  - current gate snapshot command:
    `.venv/bin/python scripts/validation/post_m4_closeout_gate.py --json-out /tmp/post-m4-closeout-gate-20260306.json`
    reports expected open checks (Windows status pending, terminal manual marker missing, terminal/windows tracker statuses open).
- Completed (2026-03-06, committed `6bbb2f1`): manual-closeout prep + CI tooling slice:
  - added `scripts/validation/prepare_post_m4_manual_closeout.py` to scaffold
    `windows/*`, `terminal/summary.md`, and `closeout-handoff.md` for a new run id.
  - added focused prep-script regressions in
    `tests/unit/validation/test_prepare_post_m4_manual_closeout.py`.
  - updated `.gitlab-ci.yml` lint/type jobs to cover validation tooling paths:
    - `ruff check nexus3/ scripts/validation/`
    - `ruff format --check nexus3/ scripts/validation/`
    - `mypy nexus3/ scripts/validation/post_m4_closeout_gate.py scripts/validation/prepare_post_m4_manual_closeout.py`
  - updated post-M4 runbook/artifact docs for `closeout-handoff.md` and
    `closeout-gate.json` handoff flow.
- Completed (2026-03-06, committed `8630f8f`): external closeout run
  (`post-m4-20260306-live1e`):
  - prepared closeout scaffold + artifacts:
    `docs/validation/post-m4-20260306-live1e/{windows,terminal,closeout-handoff.md}`.
  - executed Windows real-host evidence checks on `INC-TR` and closed windows
    summary status (`status=pass`) in
    `docs/validation/post-m4-20260306-live1e/windows/summary.json`.
  - executed multi-emulator carriage-return follow-up across
    `cmd`/`powershell`/`pwsh`/`git bash`; archived raw evidence in
    `docs/validation/post-m4-20260306-live1e/terminal/multi-shell-carriage-return-evidence.json`.
  - mirrored terminal closure marker into
    `docs/validation/post-m4-20260306-live1d/terminal/summary.md` for
    deterministic gate compatibility.
  - moved tracker follow-ups `POSTM4-FU-TERM-001` and `POSTM4-FU-WIN-001` to
    `validation-closed` in
    `docs/plans/POST-M4-VALIDATION-FOLLOWUP-TRACKER-2026-03-06.md`.
  - deterministic closeout gate command now passes with archived result:
    `.venv/bin/python scripts/validation/post_m4_closeout_gate.py --artifact-root docs/validation --soak-run-id post-m4-20260306-live1b --race-run-id post-m4-20260306-live1c --terminal-run-id post-m4-20260306-live1d --windows-run-id post-m4-20260306-live1e --json-out docs/validation/post-m4-20260306-live1e/closeout-gate.json`.
- Keep follow-on deferred plans queued behind their dependency gates
  (M4/post-M4 windows) as recorded in milestone schedule.
- Deferred follow-on planning checkpoint (2026-03-05):
  - Added explicit unblocking/execution plans for all currently tracked deferred boundaries (Plan A, Plan H, Plan C service immutability, provider keep-alive investigation, structural refactor wave, post-M4 validation campaign).
  - Added milestone-schedule backlog entries with target windows and exit gates for each follow-on plan.

Compact handover checkpoint (2026-03-09, post-structural Phase 1B wave):
- Branch: `feat/arch-overhaul-execution`
- Current head: `73ccb78` (`docs(status): add post-phase1a compact handover checkpoint`)
- Pre-wave status alignment commit: `73ccb78`
- Execution model used:
  - orchestrator selected next slices and delegated disjoint write scopes to
    parallel Codex subagents.
  - subagent-delivered changes were validated in local WSL before checkpointing.
- Completed in this wave:
  - REPL runtime/client-discovery helper extraction to
    `nexus3/cli/repl_runtime.py`.
  - REPL reload helper extraction to `nexus3/cli/repl_reload.py`.
  - `nexus3/cli/repl.py` retained façade-compatible symbols/imports.
  - structural plan/status docs synced for Phase 1B completion.
- Local validation rerun at checkpoint:
  - `.venv/bin/ruff check nexus3/cli/repl.py nexus3/cli/repl_runtime.py nexus3/cli/repl_reload.py` passed.
  - `.venv/bin/mypy nexus3/cli/repl.py nexus3/cli/repl_runtime.py nexus3/cli/repl_reload.py` passed.
  - `.venv/bin/pytest -q tests/unit/cli/test_repl_safe_sink.py tests/unit/test_repl_commands.py tests/unit/cli/test_connect_lobby_safe_sink.py tests/unit/test_client.py` passed (`125 passed`).
- Next gate after compact:
  1. Execute remaining Session extraction internals (tool-loop/core send-turn internals; event-loop/send-turn extraction) with focused parity checks.
  2. Keep manual provider keep-alive endpoint evidence capture queued until real endpoint access is available.
  3. Windows host is not required for the immediate next gate.

Compact handover checkpoint (2026-03-09, post-structural Phase 2G wave):
- Branch: `feat/arch-overhaul-execution`
- Latest structural execution commit: `f25b020`
  (`structural phase 2g: extract session turn-entry runtime helper`)
- Execution model used:
  - orchestrator selected next safe slices and delegated disjoint work to
    parallel Codex subagents.
  - subagent-delivered changes were reviewed and revalidated locally in WSL
    before each commit.
- Completed in this wave:
  - extracted shared `send(...)`/`run_turn(...)` context-mode preflight/reset
    path to `nexus3/session/turn_entry_runtime.py`.
  - `send(...)` and `run_turn(...)` now call `prepare_turn_entry(...)` while
    preserving existing behavior.
  - synchronized structural status docs (plan/schedule + AGENTS/CLAUDE +
    session README).
- Validation snapshot for this wave:
  - `.venv/bin/ruff check nexus3/session/session.py nexus3/session/turn_entry_runtime.py` passed.
  - `.venv/bin/mypy nexus3/session/session.py nexus3/session/turn_entry_runtime.py` passed.
  - `.venv/bin/pytest -q tests/unit/session/test_session_cancellation.py` passed (`12 passed`).
  - `.venv/bin/pytest -q tests/integration/test_skill_execution.py tests/integration/test_permission_enforcement.py tests/integration/test_chat.py` passed (`40 passed, 2 skipped`).
  - live smoke passed on port 9000:
    `NEXUS_DEV=1 .venv/bin/python -m nexus3 --serve 9000`,
    `.venv/bin/python -m nexus3 rpc create/send/destroy/shutdown --port 9000`.
- Next gate after compact:
  1. Execute remaining post-turn-entry Session core `send(...)` / `run_turn(...)`
     extraction internals with focused parity checks.
  2. Keep provider keep-alive endpoint evidence capture queued until real
     endpoint access is available.
  3. Windows host is not required for the immediate next gate.

Compact handover checkpoint (2026-03-09, post-structural Phase 3D wave):
- Branch: `feat/arch-overhaul-execution`
- Current head before this handover commit: `4eed1fe`
  (`structural wave: extract pool create and restore runtime helpers`)
- Execution model used:
  - orchestrator-first flow from main Codex selected next safe slices.
  - disjoint work was delegated to parallel Codex subagents (module extraction
    first), then integrated in a single-owner `pool.py` pass.
  - every subagent payload was revalidated locally in WSL before commit.
- Completed in this wave:
  - added `nexus3/rpc/pool_lifecycle.py` for destroy/capability/accessor
    lifecycle internals.
  - `nexus3/rpc/pool.py` now delegates lifecycle/capability/accessor paths to
    extracted helpers while preserving public API surface.
  - structural status docs were advanced for Pool Phase 3D completion and
    updated next gate.
- Validation snapshot for this wave:
  - `.venv/bin/ruff check nexus3/rpc/pool.py nexus3/rpc/pool_lifecycle.py nexus3/rpc/pool_create.py nexus3/rpc/pool_restore.py nexus3/rpc/pool_visibility.py` passed.
  - `.venv/bin/mypy nexus3/rpc/pool.py nexus3/rpc/pool_lifecycle.py nexus3/rpc/pool_create.py nexus3/rpc/pool_restore.py nexus3/rpc/pool_visibility.py` passed.
  - `.venv/bin/pytest -q tests/unit/test_pool.py tests/unit/test_auto_restore.py tests/unit/rpc/test_pool_create_auth_shadow.py -k "destroy_ or capability or should_shutdown or list_returns_agent_info_dicts or get_returns_ or len_returns_agent_count or contains_checks_agent_id or mcp_visibility or gitlab_visibility or create_ or create_temp or restore_ or get_or_restore"` passed (`70 passed`).
  - `.venv/bin/pytest -q tests/unit/test_agent_api.py tests/unit/test_rpc_dispatcher.py tests/unit/test_global_dispatcher.py` passed (`62 passed`).
  - `.venv/bin/pytest -q tests/integration/test_permission_inheritance.py tests/integration/test_sandboxed_parent_send.py` passed (`51 passed`).
- Resume steps after compact:
  1. Remove temporary compatibility wrappers in `session.py` and `pool.py` in
     low-risk order (compaction/restore builders first, callback/loop wrappers
     last) after one full green cycle.
  2. Update deferred tracker rows/docs for structural refactor closeout.
  3. Keep provider keep-alive real-endpoint evidence capture queued; Windows
     host is not required for the immediate wrapper-cleanup gate.

Compact handover checkpoint (2026-03-09, post-session-wrapper-retirement wave):
- Branch: `feat/arch-overhaul-execution`
- Completed in this wave:
  - removed remaining Session wrappers `_execute_single_tool(...)`,
    `_handle_mcp_permissions(...)`, `_handle_gitlab_permissions(...)`,
    `_execute_skill(...)`, and `_execute_tools_parallel(...)`.
  - `send(...)` / `run_turn(...)` now build explicit runtime callables and pass
    them to `execute_tool_loop_events(...)`.
  - `tool_loop_events_runtime.execute_tool_loop_events(...)` now accepts
    explicit `execute_tools_parallel` and `execute_single_tool` callables.
  - kernelization tests now call permission runtime helpers directly.
- Validation snapshot for this wave:
  - `.venv/bin/ruff check nexus3/session/session.py nexus3/session/tool_loop_events_runtime.py nexus3/session/single_tool_runtime.py nexus3/session/tool_runtime.py nexus3/session/README.md tests/unit/session/test_session_permission_kernelization.py tests/integration/test_permission_enforcement.py` passed.
  - `.venv/bin/mypy nexus3/session/session.py nexus3/session/tool_loop_events_runtime.py nexus3/session/single_tool_runtime.py nexus3/session/tool_runtime.py` passed.
  - `.venv/bin/pytest -q tests/unit/test_compaction.py tests/unit/session/test_session_cancellation.py tests/unit/session/test_session_permission_kernelization.py tests/unit/test_pool.py tests/unit/test_auto_restore.py tests/unit/rpc/test_pool_create_auth_shadow.py tests/unit/test_agent_api.py tests/unit/test_rpc_dispatcher.py tests/unit/test_global_dispatcher.py` passed (`213 passed`).
  - `.venv/bin/pytest -q tests/integration/test_permission_enforcement.py tests/integration/test_skill_execution.py tests/integration/test_chat.py tests/integration/test_permission_inheritance.py tests/integration/test_sandboxed_parent_send.py` passed (`91 passed, 2 skipped`).
- Resume steps after compact:
  1. No structural wrapper work remains; keep deferred structural tracker/docs
     rows closed in status artifacts.
  2. Keep provider keep-alive real-endpoint evidence operationally deferred
     (2026-03-09) pending endpoint credentials/config availability in the
     current WSL environment (no code rollback).
  3. Once unblocked, execute reminder checklist:
     configure known-problematic + known-good endpoint/model targets, set API
     key env vars, run `scripts/diagnose-empty-stream.sh` Step 10 flow, archive
     `10-keepalive-evidence.json` artifacts, and link run IDs in status docs.
  4. Windows host is not required for the immediate provider-evidence gate.

Recent execution commits (latest first):
- `73ccb78` docs(status): add post-phase1a compact handover checkpoint
- `7fec6c5` structural phase 1a: extract repl formatting helpers
- `cbff9b0` docs(status): align structural kickoff and next-step ordering
- `a22c631` docs(status): record plan h closeout commit in handoff
- `a9aaa12` plan h shim retirement closeout: retire remaining create_agent remaps
- `05ffb84` provider keepalive kickoff: add stale-reuse recovery and diagnostics evidence
- `8143afe` plan c closeout: scope runtime register compatibility path
- `5c0e843` plan c slices 2/3: migrate pool/repl/session runtime state to typed services
- `fd33b01` plan h phase 3 + plan c slice 1: canonical rpc diagnostics and typed service runtime api
- `b09c079` plan h shim retirement phase 2: drop create id message remaps
- `fc890bc` docs(status): add post-plan-h-phase1 compact checkpoint
- `e4bdd23` docs(status): record plan h shim phase 1 commit in AGENTS
- `f22de38` plan h shim retirement phase 1: remove parent id wording remap
- `19e659e` docs(status): record plan a v2 phase 2 commit in AGENTS
- `0a4f99f` plan a v2 phase 2: compute create ceiling grants in adapter
- `5c9c0e2` plan a v2 phase 1: add typed create auth context model
- `8630f8f` post-m4 closeout: archive windows host evidence and pass gate
- `6bbb2f1` post-m4 campaign: add manual closeout prep scaffolding
- `ad53962` post-m4 campaign: add deterministic closeout gate checker
- `5487d43` docs(post-m4): add canonical follow-up tracker mappings
- `d8d7538` docs(status): record terminal follow-up commit in running log
- `055dcb6` post-m4 campaign: add terminal follow-up refresh and sync status
- `abef28a` post-m4 campaign: add contention-aware race follow-up
- `fa1c66a` docs(validation): add retained dry-run and initial live artifacts
- `59dab71` post-m4 campaign: run first live validation slice
- `34c2f67` post-m4 campaign: add runbook and validation harness bootstrap
- `a1e445e` m4 closeout: remediate gate regressions and sync status docs
- `ffb8b87` plan b phase 4b: enforce capability-first http requester identity
- `2cb4817` plan b phase 4a: add legacy requester fallback telemetry
- `6b65b17` plan b phase 3a: add http capability transport wiring
- `35206ec` docs: record plan b phase 2 execution status
- `43773be` plan b phase 2: integrate capabilities into direct rpc path
- `14bc820` plan b phase 1: add capability token primitives
- `00c59ed` plan e phase 4: migrate compaction and truncation to graph pipeline
- `6829838` docs: record plan e phase 3 execution status
- `5632652` plan e phase 3: add context graph prototype
- `5bdce8e` docs: align m3 running status wording
- `d95b599` docs: sync plan e phase 2 committed status and compact checkpoint
- `35bb34e` docs: sync running status after plan e phase 2 commit
- `e3cd304` plan e phase 2: integrate compiler into session and providers
- `e9d6c3e` plan e phase 1: add context compiler ir foundation
- `6e946cf` plan f phase 7: retire patch legacy runtime path
- `78ef205` rpc/protocol: wire parse_request to request schema ingress
- `022f461` repl: sanitize startup metadata output via SafeSink
- `9e08fd2` repl: sanitize post-turn status and error lines
- `4686fd5` rpc/dispatcher: add cancel_all empty-params ingress guard
- `7522446` tests(rpc): cover create auth shadow parity at delta ceiling stage
- `419f370` rpc/pool: add create auth shadow parity at parent ceiling gates
- `029d1e6` repl: sanitize incoming notification previews via SafeSink
- `bae573c` rpc create_agent: drop redundant allowed_write_paths type guard
- `000e256` advance plan h/a: streamline send ingress and add send auth shadow parity
- `149e342` repl: sanitize tool trace lines via SafeSink
- `ef5ffaa` Expand auth kernel shadow parity for tool action checks
- `cd7f3f9` display: sanitize inline printer dynamic output via SafeSink
- `9f29400` harden rpc ingress for cancel and create-agent wait flag
- `6671064` harden protocol response ingress with typed schema validation
- `bdb676e` expand plan A: add target auth kernel shadow parity in enforcer
- `ce3d263` migrate confirmation ui prompts to SafeSink
- `c5eb670` advance plan h: reject boolean json-rpc ids at protocol boundary
- `f6ee537` advance m1: harden send ingress params and migrate lobby outputs to safe sink
- `a53c7dd` advance plan h: fail-fast mcp boundary validation and unify mcp config model
- `1b455b5` advance m1: extend schema ingress create_agent and migrate repl mcp consent to safe sink

Progress snapshot:
- Completed: architecture plan sanity corrections merged locally (schedule + plans A-H scope/gates/checklist alignment).
- Completed: deferred-boundary follow-on planning closeout (2026-03-05):
  - added [ARCH-A-AUTH-REQUEST-MODEL-V2-PLAN-2026-03-05.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-A-AUTH-REQUEST-MODEL-V2-PLAN-2026-03-05.md)
  - added [ARCH-H-RPC-ERROR-SHIM-RETIREMENT-PLAN-2026-03-05.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-H-RPC-ERROR-SHIM-RETIREMENT-PLAN-2026-03-05.md)
  - updated [ARCH-MILESTONE-SCHEDULE-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md) with explicit backlog dependency/exit gates
  - updated [docs/plans/README.md](/home/inc/repos/NEXUS3/docs/plans/README.md) follow-on index section
- Completed (2026-03-06, committed `5c9c0e2`): Plan A follow-on
  request-model-v2 Phase 1 kickoff:
  - implemented typed create-stage context foundation in
    `nexus3/core/authorization_kernel.py`.
  - routed pool create-stage kernel requests through typed context emit/parse
    in `nexus3/rpc/pool.py` while preserving current semantics.
  - added focused context model regressions in
    `tests/unit/core/test_authorization_kernel.py`.
- Completed (2026-03-06, committed `34c2f67`): Post-M4 validation campaign
  Phase 1/2 bootstrap:
  - added [POST-M4-VALIDATION-RUNBOOK.md](/home/inc/repos/NEXUS3/docs/testing/POST-M4-VALIDATION-RUNBOOK.md)
  - added [docs/validation/README.md](/home/inc/repos/NEXUS3/docs/validation/README.md)
  - added `scripts/validation/soak_workload.py`,
    `scripts/validation/race_harness.py`,
    `scripts/validation/terminal_payload_matrix.py`
  - updated [WINDOWS-LIVE-TESTING-GUIDE.md](/home/inc/repos/NEXUS3/docs/testing/WINDOWS-LIVE-TESTING-GUIDE.md)
    with post-M4 runbook/artifact references
- Completed (2026-03-06, committed `59dab71`): Post-M4 validation campaign
  first live execution slice (`post-m4-20260306-live1b`):
  - added run artifact set under
    `docs/validation/post-m4-20260306-live1b/{soak,race,terminal,windows}`
  - recorded findings and follow-up placeholders in
    `docs/validation/post-m4-20260306-live1b/findings.md` and
    `docs/validation/post-m4-20260306-live1b/issue-links.md`
  - preflight + live validation commands captured in campaign plan/status docs
- Completed (2026-03-06, committed `fa1c66a`): retained validation artifacts
  committed for continuity:
  - `docs/validation/post-m4-bootstrap-dryrun/`
  - `docs/validation/post-m4-20260306-live1/`
  - `docs/validation/post-m4-20260306-live2/`
- Completed (2026-03-06, committed `abef28a`): Post-M4 race follow-up slice
  (`post-m4-20260306-live1c`):
  - updated `scripts/validation/race_harness.py` with contention-aware
    failure-rate gating option (`--exclude-expected-contention-errors`)
  - added follow-up artifacts and notes under
    `docs/validation/post-m4-20260306-live1c/`
  - updated post-M4 runbook/validation schema docs and milestone/plan status
    notes for contention-aware race follow-up evidence
- Completed (2026-03-06, local pending commit): Post-M4 external closeout run
  (`post-m4-20260306-live1e`):
  - closed Windows real-host track with pass status:
    `docs/validation/post-m4-20260306-live1e/windows/summary.json`
  - closed multi-emulator carriage-return follow-up with evidence:
    `docs/validation/post-m4-20260306-live1e/terminal/multi-shell-carriage-return-evidence.json`
  - updated tracker statuses to `validation-closed`:
    `docs/plans/POST-M4-VALIDATION-FOLLOWUP-TRACKER-2026-03-06.md`
  - archived deterministic gate pass output:
    `docs/validation/post-m4-20260306-live1e/closeout-gate.json`
- Completed (2026-03-05): Plan E Phase 2 provider/session integration (`e3cd304`):
  - migrated `Session.send()`/`Session.run_turn()` pre-user preflight repair
    path to compiler-backed normalization (`compile_context_messages(...)`)
    with persisted repaired history via `ContextManager.replace_messages(...)`.
  - routed `OpenAICompatProvider` and `AnthropicProvider` request shaping
    through compiler output before provider-specific conversion/injection.
  - retired Anthropic-local orphan `tool_result` synthesis in
    `_convert_messages`; synthesis now occurs in shared compiler repair.
  - added focused coverage in
    `tests/unit/session/test_session_cancellation.py` and
    `tests/unit/provider/test_compiler_integration.py`.
- Completed (2026-03-05): Plan E Phase 3 graph prototype (`5632652`):
  - added compiler-backed graph projection module `nexus3/context/graph.py`
    with typed edge model (`NEXT`, `TOOL_RESULT`) and tool-batch-aware
    atomic groups (`ContextMessageGroup`).
  - exported graph interfaces in `nexus3/context/__init__.py`.
  - added focused graph regressions in `tests/unit/context/test_graph.py`.
  - updated `nexus3/context/README.md` architecture docs for compiler+graph.
- Completed (2026-03-05): Plan E Phase 4 compaction/truncation migration (`00c59ed`):
  - migrated truncation grouping in `nexus3/context/manager.py` to
    compiler/graph-derived atomic message groups.
  - migrated compaction selection in `nexus3/context/compaction.py` to
    compiler-normalized atomic-group preservation.
  - added focused regressions in `tests/unit/test_compaction.py` and
    `tests/unit/test_context_manager.py`.
- Completed (2026-03-05): Plan B Phase 1 capability primitives (`14bc820`):
  - added signed capability token module `nexus3/core/capabilities.py`
    (claims model, signer/verifier, revocation/replay stores, secret helper).
  - exported capability APIs in `nexus3/core/__init__.py`.
  - added focused regressions in `tests/unit/core/test_capabilities.py`.
  - updated `nexus3/core/README.md` capability API/module documentation.
- Completed (2026-03-05): Plan B Phase 2 direct in-process capability integration (`43773be`):
  - added direct-RPC capability scope registry in `nexus3/core/capabilities.py`
    and shared capability ingress identity resolution in
    `nexus3/rpc/dispatch_core.py`.
  - updated `Dispatcher.dispatch(...)` and `GlobalDispatcher.dispatch(...)` to
    accept optional capability tokens and derive requester context from verified
    capability claims.
  - updated `nexus3/rpc/agent_api.py` direct calls to mint/attach per-call
    capability tokens via `AgentPool.issue_direct_capability(...)`.
  - added pool-owned direct capability verification + destroy-time revocation
    lifecycle in `nexus3/rpc/pool.py`.
  - added focused regressions in `tests/unit/test_agent_api.py`,
    `tests/unit/test_rpc_dispatcher.py`, `tests/unit/test_global_dispatcher.py`,
    `tests/unit/test_pool.py`, and `tests/unit/core/test_request_context.py`.
- Completed (2026-03-05): Plan B Phase 3A HTTP ingress-first capability transport (`6b65b17`):
  - updated `nexus3/rpc/http.py` to forward optional
    `X-Nexus-Capability` as `capability_token` through global and
    `/agent/{id}` dispatch paths.
  - updated `nexus3/client.py` with explicit optional capability-token plumbing
    that emits `X-Nexus-Capability` only when configured.
  - updated `nexus3/rpc/README.md` with HTTP capability precedence/fallback docs
    (`capability` first, `X-Nexus-Agent` fallback only when capability absent).
  - added focused regressions in `tests/unit/test_http_pipeline_layers.py` and
    `tests/unit/test_client.py` for capability forwarding, invalid-capability
    `INVALID_PARAMS` surfacing, and requester-only fallback behavior.
- Completed (2026-03-06): Plan B Phase 4A migration-prep telemetry slice (`2cb4817`):
  - updated `nexus3/rpc/http.py` to emit warning telemetry when deprecated
    requester-only `X-Nexus-Agent` fallback is used without
    `X-Nexus-Capability`.
  - preserved compatibility behavior in this slice
    (requester-only fallback still accepted and forwarded).
  - updated `nexus3/rpc/README.md` and
    `docs/plans/ARCH-B-CAPABILITY-TOKENS-PLAN-2026-03-02.md` for
    Phase 4A (telemetry) vs Phase 4B (future enforcement) sequencing.
  - added focused warning-path coverage in
    `tests/unit/test_http_pipeline_layers.py`.
- Completed (2026-03-06): Plan B Phase 4B enforcement slice (`ffb8b87`):
  - updated `nexus3/rpc/http.py` to reject requester-only `X-Nexus-Agent`
    ingress when `X-Nexus-Capability` is absent.
  - deterministic `INVALID_PARAMS` response now returned at HTTP ingress for
    requester-only identity headers.
  - updated `nexus3/rpc/README.md`,
    `docs/plans/ARCH-B-CAPABILITY-TOKENS-PLAN-2026-03-02.md`, and
    `docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md` for Phase 4B completion
    semantics.
  - updated focused regressions in `tests/unit/test_http_pipeline_layers.py`
    for requester-only rejection behavior.
- Completed (2026-03-06, local pending commit): M4 closeout remediation slice:
  - aligned destroy authorization security tests with current kernel-authoritative semantics in `tests/security/test_destroy_authorization.py` (including explicit capability-state fixture initialization for capability-revocation fields used by `AgentPool.destroy`).
  - aligned MCP integration expectations in `tests/integration/test_mcp_errors.py` for current bracket escaping and fail-fast `MCPServerConfig` validation timing.
  - imported `MCPServerConfig` in `nexus3/mcp/__init__.py` from canonical `nexus3.config.schema` source to satisfy explicit-export typing.
  - hardened grep ripgrep fast path in `nexus3/skill/builtin/grep.py` with `--max-filesize` enforcement plus context match-marker parity for `context > 0`.
  - resolved full-gate static drift in `nexus3/skill/builtin/{run_python.py,bash.py,concat_files.py,regex_replace.py}` and updated resilient provider-cap assertions in `tests/security/test_p2_provider_error_caps.py`.
- Validation snapshot (2026-03-06, M4 closeout gates):
  - `.venv/bin/ruff check nexus3/` passed.
  - `.venv/bin/mypy nexus3/` passed (`Success: no issues found in 201 source files`).
  - `.venv/bin/pytest tests/ -v` passed (`4102 passed`, `3 skipped`, `21 warnings`).
  - `.venv/bin/pytest tests/integration/ -v` passed (`211 passed`, `2 skipped`).
  - Focused regression confirmation passed:
    `.venv/bin/pytest -q tests/security/test_destroy_authorization.py tests/integration/test_mcp_errors.py tests/security/test_p2_file_size_limits.py::TestGrepSizeLimits::test_grep_skips_large_files tests/unit/test_skill_enhancements.py::TestGrepIncludeContext::test_context_marks_match_lines tests/security/test_p2_provider_error_caps.py::TestProviderErrorHandlingCodePaths::test_non_streaming_uses_content_slice` (`39 passed`).
  - Live validation executed:
    - `.venv/bin/python -m nexus3 --serve 9000` (server started)
    - `.venv/bin/python -m nexus3 rpc create m4-closeout-3 --port 9000` (success)
    - `.venv/bin/python -m nexus3 rpc send m4-closeout-3 "describe your permissions and what you can do" --port 9000` (success)
    - `.venv/bin/python -m nexus3 rpc destroy m4-closeout-3 --port 9000` (success)
- Validation snapshot (2026-03-05, Plan B Phase 2):
  - `.venv/bin/ruff check nexus3/core/capabilities.py nexus3/core/request_context.py nexus3/core/__init__.py nexus3/rpc/dispatch_core.py nexus3/rpc/dispatcher.py nexus3/rpc/global_dispatcher.py nexus3/rpc/agent_api.py nexus3/rpc/pool.py nexus3/rpc/http.py tests/unit/core/test_request_context.py tests/unit/test_agent_api.py tests/unit/test_rpc_dispatcher.py tests/unit/test_global_dispatcher.py tests/unit/test_pool.py` passed.
  - `.venv/bin/mypy nexus3/core/capabilities.py nexus3/core/request_context.py nexus3/core/__init__.py nexus3/rpc/dispatch_core.py nexus3/rpc/dispatcher.py nexus3/rpc/global_dispatcher.py nexus3/rpc/agent_api.py nexus3/rpc/pool.py nexus3/rpc/http.py` passed.
  - `.venv/bin/pytest -q tests/unit/core/test_request_context.py tests/unit/test_agent_api.py tests/unit/test_rpc_dispatcher.py tests/unit/test_global_dispatcher.py tests/unit/test_pool.py tests/unit/test_initial_message.py` passed (`147 passed`, `1 warning`).
  - `.venv/bin/pytest -q tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/test_nexus_skill_requester_propagation.py` passed (`75 passed`, `1 warning`).
  - Live validation executed:
    - `.venv/bin/python -m nexus3 --serve 9000` (server started)
    - `.venv/bin/python -m nexus3 rpc create test-agent --port 9000` (success)
    - `.venv/bin/python -m nexus3 rpc send test-agent "describe your permissions and what you can do" --port 9000` (success)
    - `.venv/bin/python -m nexus3 rpc destroy test-agent --port 9000` (success)
- Validation snapshot (2026-03-05, Plan B Phase 3A):
  - `.venv/bin/ruff check nexus3/rpc/http.py nexus3/client.py nexus3/rpc/README.md tests/unit/test_http_pipeline_layers.py tests/unit/test_client.py tests/unit/test_global_dispatcher.py tests/unit/test_rpc_dispatcher.py` passed.
  - `.venv/bin/mypy nexus3/rpc/http.py nexus3/client.py` passed.
  - `.venv/bin/pytest -q tests/unit/test_http_pipeline_layers.py tests/unit/test_client.py tests/unit/test_global_dispatcher.py tests/unit/test_rpc_dispatcher.py` passed (`79 passed`, `12 warnings`).
  - Live validation executed:
    - `.venv/bin/python -m nexus3 --serve 9000` (server started)
    - `.venv/bin/python -m nexus3 rpc create arch-b-http-cap --port 9000` (success)
    - `.venv/bin/python -m nexus3 rpc send arch-b-http-cap "describe your permissions and what you can do" --port 9000` (success)
    - `.venv/bin/python -m nexus3 rpc destroy arch-b-http-cap --port 9000` (success)
- Validation snapshot (2026-03-06, Plan B Phase 4A local):
  - `.venv/bin/ruff check nexus3/rpc/http.py tests/unit/test_http_pipeline_layers.py nexus3/rpc/README.md docs/plans/ARCH-B-CAPABILITY-TOKENS-PLAN-2026-03-02.md` passed.
  - `.venv/bin/mypy nexus3/rpc/http.py` passed.
  - `.venv/bin/pytest -q tests/unit/test_http_pipeline_layers.py tests/unit/test_nexus_skill_requester_propagation.py` passed (`21 passed`, `1 warning`).
  - Live validation executed:
    - `.venv/bin/python -m nexus3 --serve 9000` (server started)
    - `.venv/bin/python -m nexus3 rpc create arch-b-phase4a --port 9000` (success)
    - `.venv/bin/python -m nexus3 rpc send arch-b-phase4a "describe your permissions and what you can do" --port 9000` (success)
    - `.venv/bin/python -m nexus3 rpc destroy arch-b-phase4a --port 9000` (success)
- Validation snapshot (2026-03-06, Plan B Phase 4B):
  - `.venv/bin/ruff check nexus3/rpc/http.py tests/unit/test_http_pipeline_layers.py nexus3/rpc/README.md docs/plans/ARCH-B-CAPABILITY-TOKENS-PLAN-2026-03-02.md docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md` passed.
  - `.venv/bin/mypy nexus3/rpc/http.py` passed.
  - `.venv/bin/pytest -q tests/unit/test_http_pipeline_layers.py tests/unit/test_client.py tests/unit/test_global_dispatcher.py tests/unit/test_rpc_dispatcher.py tests/unit/test_nexus_skill_requester_propagation.py` passed (`80 passed`, `13 warnings`).
  - Live validation executed:
    - `.venv/bin/python -m nexus3 --serve 9000` (server started)
    - `.venv/bin/python -m nexus3 rpc create arch-b-phase4b --port 9000` (success)
    - `.venv/bin/python -m nexus3 rpc send arch-b-phase4b "describe your permissions and what you can do" --port 9000` (success)
    - `.venv/bin/python -m nexus3 rpc destroy arch-b-phase4b --port 9000` (success)
- Completed: Plan A M0 foundation interfaces (`nexus3/core/authorization_kernel.py`) + unit tests.
- Completed: Plan H M0 schema inventory scaffold (`nexus3/rpc/schemas.py`) + unit tests.
- Completed: Plan H M1 Phase 2 first compat-safe ingress slice (`destroy_agent`, `get_messages`) wired to typed schemas with existing-style RPC error mapping + focused unit tests.
- Completed: Plan H M1 Phase 2 incremental compat-safe ingress slice (`cancel`, `compact`) wired in `rpc/dispatcher.py` with focused wiring tests.
- Completed: Plan H M1 Phase 2 low-risk no-arg ingress compat-safe schema hooks wired for `shutdown`/`get_tokens`/`get_context` and `list_agents`/`shutdown_server`, with focused compat wiring tests.
- Completed: Plan H M1 Phase 2 behavior-sensitive ingress slice wired in `rpc/dispatcher.py::_handle_send` and `rpc/global_dispatcher.py::_handle_create_agent` with compat-safe schema validation and preserved `InvalidParamsError` style mappings, plus focused wiring tests.
- Completed: Plan H M1 Phase 2 behavior-sensitive extension for `create_agent`:
  - added compat-safe ingress validation coverage for `parent_agent_id` and conditional `wait_for_initial_response` in `rpc/global_dispatcher.py::_handle_create_agent`
  - preserved legacy-style `InvalidParamsError` message mappings (`Parent agent not found: ...`, `wait_for_initial_response must be boolean`)
  - added focused wiring regressions in `tests/unit/rpc/test_schema_ingress_wiring.py`
- Completed: Plan H M1 Phase 3 MCP config consolidation slice:
  - unified `MCPServerConfig` into `nexus3/config/schema.py` as canonical source of truth
  - removed duplicate `MCPServerConfig` dataclass from `nexus3/mcp/registry.py` and kept registry import path compatibility
  - updated `/mcp connect` path to pass canonical MCP config directly to registry (including `args` and `fail_if_no_tools`)
- Completed: Plan H M1 Phase 3 fail-fast malformed-entry slice:
  - removed silent malformed `mcp.json` container/entry skips in `nexus3/context/loader.py::_merge_mcp_servers`
  - malformed `mcpServers`/`servers` container types and non-object list entries now raise `MCPConfigError` with contextual source metadata
  - added focused regressions in `tests/unit/context/test_loader_mcp_fail_fast.py`, including compatibility fallback when `mcpServers` is empty and `servers` is present
- Completed: Plan H M1 Phase 2 send-ingress extension:
  - expanded compat-safe schema validation in `nexus3/rpc/dispatcher.py::_handle_send` to cover optional `request_id`, `source`, and `source_agent_id`
  - preserved explicit `InvalidParamsError` mappings for malformed optional fields and prevented unhashable `request_id` shapes from reaching internal tracking structures
  - added focused malformed-parameter regressions in `tests/unit/rpc/test_schema_ingress_wiring.py`
- Completed: Plan H M1 Phase 2 protocol-boundary hardening:
  - `nexus3/rpc/protocol.py` request/response parsing now explicitly rejects boolean JSON-RPC `id` values (bool no longer accepted via int subclass behavior)
  - added focused parse tests in `tests/unit/rpc/test_schema_ingress_wiring.py` and `tests/unit/test_client.py`
- Completed: Plan H M1 Phase 2 response-envelope ingress hardening:
  - `nexus3/rpc/protocol.py::parse_response` now validates through `RpcResponseEnvelopeSchema`
  - preserved legacy-style ParseError wording for malformed `error` object shapes and existing envelope invariants
  - added focused regressions in `tests/unit/rpc/test_schema_ingress_wiring.py` and `tests/unit/rpc/test_schemas.py`
- Completed: Plan H M1 Phase 2 handler cleanup slice:
  - removed ad hoc `cancel` request-id guard in `rpc/dispatcher.py` and rely on `CancelParamsSchema` compat-safe ingress validation.
  - removed duplicate `wait_for_initial_response` post-create manual parsing in `rpc/global_dispatcher.py` and reused schema-validated field.
  - added focused regressions in `tests/unit/rpc/test_schema_ingress_wiring.py`.
- Completed: Plan H M1 Phase 2 projection cleanup slice:
  - introduced shared schema projection helper `project_known_schema_fields` in `nexus3/rpc/schemas.py` for interim migration cleanup.
  - migrated `rpc/dispatcher.py::_handle_send` and `rpc/global_dispatcher.py::_handle_create_agent` field projection to helper-backed schema ingress flow.
  - preserved legacy-style invalid-param wording and compat-safe extra-param behavior.
  - later retired in architecture execution round 22 after strict full-param ingress became universal.
- Completed: Plan H M1 Phase 2 create-agent cleanup slice:
  - removed redundant post-schema `allowed_write_paths` type guards in `rpc/global_dispatcher.py`.
  - preserved malformed-shape `InvalidParamsError` wording via ingress schema error mapping.
  - kept sandbox/parent-cwd path containment enforcement unchanged.
- Completed: Plan H M1 Phase 2 no-arg ingress cleanup slice:
  - added compat-safe `EmptyParamsSchema` ingress guard for `rpc/dispatcher.py::_handle_cancel_all`.
  - preserved permissive extra-param compatibility behavior.
  - added focused wiring regression in `tests/unit/rpc/test_schema_ingress_wiring.py`.
- Completed: Plan H M1 Phase 2 request-envelope ingress migration:
  - migrated `rpc/protocol.py::parse_request` to typed schema ingress via `RpcRequestEnvelopeSchema`.
  - preserved legacy ParseError wording and positional-params rejection behavior.
  - added focused protocol ingress regressions in `tests/unit/rpc/test_schema_ingress_wiring.py`.
- Completed: Plan H M1 Phase 2 strict-envelope ingress slice:
  - tightened protocol-envelope ingress in `nexus3/rpc/protocol.py` and `nexus3/rpc/schemas.py` to reject unknown top-level JSON-RPC request/response fields.
  - removed request projection-based compatibility and response envelope `extra=\"ignore\"` compatibility override.
  - preserved bool-id rejection and positional-params ParseError wording.
  - added focused regressions in `tests/unit/rpc/test_schema_ingress_wiring.py`, `tests/unit/rpc/test_schemas.py`, and `tests/unit/test_client.py`.
- Completed: Plan H M1 Phase 2 destroy-ingress strictness slice:
  - tightened `nexus3/rpc/global_dispatcher.py::_handle_destroy_agent` to validate full param objects and reject unknown extra params.
  - preserved legacy missing/type/malformed `agent_id` wording and requester propagation behavior.
  - added focused ingress regression in `tests/unit/rpc/test_schema_ingress_wiring.py`.
- Completed: Plan H M1 Phase 2 strict no-arg flip slice:
  - tightened no-arg ingress handlers in `nexus3/rpc/dispatcher.py` (`shutdown`, `get_tokens`, `get_context`, `cancel_all`) and `nexus3/rpc/global_dispatcher.py` (`list_agents`, `shutdown_server`) to reject unknown extra params via strict `EmptyParamsSchema` validation.
  - preserved existing success payloads and method-specific invalid-params wording.
  - updated ingress regressions in `tests/unit/rpc/test_schema_ingress_wiring.py`.
- Completed: baseline E/F harness fixtures/tests under `tests/fixtures/arch_baseline/`, `tests/unit/context/test_compile_baseline.py`, and `tests/unit/patch/test_byte_roundtrip_baseline.py`.
- Completed: Plan G M1 Phase 1 foundation safe sink API (`nexus3/display/safe_sink.py`) with minimal `InlinePrinter` integration and focused unit tests (`tests/unit/display/test_safe_sink.py`).
- Completed: Plan G M1 Phase 2 high-risk output migration:
  - `nexus3/cli/client_commands.py` stderr output paths now use `SafeSink` trusted/untrusted stream methods.
  - `nexus3/mcp/error_formatter.py` dynamic fields now use `SafeSink` print sanitization.
  - Focused tests added/updated in `tests/unit/cli/test_client_commands_safe_sink.py` and `tests/unit/mcp/test_error_formatter.py`.
  - Focused validation passed via `.venv/bin/ruff check` and `.venv/bin/pytest -v tests/unit/mcp/test_error_formatter.py tests/unit/cli/test_client_commands_safe_sink.py tests/unit/display/test_safe_sink.py`.
- Completed: Plan G M1 Phase 3 incremental output migration slice:
  - `nexus3/cli/repl_commands.py::_mcp_connection_consent` now sanitizes dynamic MCP server/tool text through `SafeSink` before Rich-rendered prompt output.
  - Added focused tests in `tests/unit/cli/test_repl_commands_safe_sink.py`.
  - Focused validation passed via `.venv/bin/ruff check nexus3/cli/repl_commands.py tests/unit/cli/test_repl_commands_safe_sink.py` and `.venv/bin/pytest -v tests/unit/cli/test_repl_commands_safe_sink.py tests/unit/test_repl_commands.py`.
- Completed: Plan G M1 Phase 3 incremental output migration slice (connect/lobby prompts):
  - `nexus3/cli/connect_lobby.py` and `nexus3/cli/lobby.py` now sanitize dynamic/untrusted interpolated CLI values through `SafeSink` while preserving trusted static Rich markup.
  - Added focused sanitization+parity regressions in `tests/unit/cli/test_connect_lobby_safe_sink.py` and `tests/unit/cli/test_lobby_safe_sink.py`.
  - Focused validation passed via `.venv/bin/ruff check nexus3/cli/connect_lobby.py nexus3/cli/lobby.py tests/unit/cli/test_connect_lobby_safe_sink.py tests/unit/cli/test_lobby_safe_sink.py` and `.venv/bin/pytest -v tests/unit/cli/test_connect_lobby_safe_sink.py tests/unit/cli/test_lobby_safe_sink.py tests/unit/test_lobby.py`.
- Completed: Plan G M1 Phase 3 incremental output migration slice (confirmation UI prompts):
  - `nexus3/cli/confirmation_ui.py::confirm_tool_action` now sanitizes dynamic fields through `SafeSink` across MCP/exec/nexus/general tool prompts while preserving trusted markup.
  - removed redundant ad hoc escaping variables in this path in favor of sink-boundary sanitization.
  - added focused sanitization/parity regressions in `tests/unit/cli/test_confirmation_ui_safe_sink.py`.
- Completed: Plan G M1 Phase 3 incremental output migration slice (InlinePrinter):
  - `nexus3/display/printer.py` dynamic render methods now sanitize untrusted fields through `SafeSink` (`print_task_start`, `print_task_end`, `print_error`, `print_cancelled`, expanded `print_thinking`).
  - preserved trusted gumball/thinking markup wrappers.
  - added focused sanitization/parity regressions in `tests/unit/display/test_escape_sanitization.py`.
- Completed: Plan G M1 Phase 3 incremental output migration slice (`repl.py` tool traces):
  - migrated dynamic tool-trace spinner lines in `nexus3/cli/repl.py` (`on_tool_active`, `on_batch_progress`, `on_batch_halt`, `nexus_send` trace preview) to SafeSink-backed sanitization.
  - preserved trusted Rich wrappers while sanitizing interpolated untrusted values.
  - added focused regressions in `tests/unit/cli/test_repl_safe_sink.py`.
- Completed: Plan G M1 Phase 3 incremental output migration slice (`repl.py` incoming notifications):
  - migrated incoming notification start/end preview lines to SafeSink-backed sanitization in `nexus3/cli/repl.py`.
  - preserved existing truncation/ellipsis behavior and trusted Rich wrappers.
  - extended focused regressions in `tests/unit/cli/test_repl_safe_sink.py`.
- Completed: Plan G M1 Phase 3 incremental output migration slice (`repl.py` post-turn status/errors):
  - migrated dynamic post-turn lines in `nexus3/cli/repl.py` (`cancel_reason`, `turn_duration`, stream/autosave error text) to SafeSink-backed sanitization.
  - preserved existing wrappers/wording behavior.
  - extended focused regressions in `tests/unit/cli/test_repl_safe_sink.py`.
- Completed: Plan G M1 Phase 3 incremental output migration slice (`repl.py` startup metadata/status):
  - migrated startup/session metadata and embedded RPC status lines in `nexus3/cli/repl.py` to SafeSink-backed sanitization.
  - preserved existing wrappers/wording behavior.
  - extended focused regressions in `tests/unit/cli/test_repl_safe_sink.py`.
- Completed: Plan G M1 Phase 3 incremental output migration slice (`repl.py` remaining client/discovery/status surfaces):
  - migrated remaining dynamic `run_repl`/`run_repl_client`/`_run_connect_with_discovery` lines (created-agent notices, shutdown/connect/provider/invalid-port errors, client metadata/status lines, command output message lines) to SafeSink-backed sanitization helpers.
  - preserved trusted static wrappers while sanitizing interpolated dynamic fields.
  - extended focused regressions in `tests/unit/cli/test_repl_safe_sink.py`.
- Completed: Plan G M1 Phase 3 incremental output migration slice (top-level REPL/serve residual surfaces):
  - migrated residual dynamic top-level lines in `nexus3/cli/repl.py::main`, `nexus3/cli/repl.py::_run_with_reload`, and `nexus3/cli/serve.py::run_serve` to SafeSink-backed sanitization helpers.
  - preserved startup/error wording and flow while sanitizing dynamic command/path/message fields.
  - added focused serve sanitization regressions in `tests/unit/cli/test_serve_safe_sink.py` and extended `tests/unit/cli/test_repl_safe_sink.py`.
- Completed: Plan G Phase 3 cleanup slice (SafeSink helper dedup):
  - added shared `SafeSink.sanitize_print_value(...)` helper in `nexus3/display/safe_sink.py`.
  - removed duplicate local sanitize-wrapper helpers in `nexus3/cli/serve.py` and `nexus3/mcp/error_formatter.py` by routing through shared SafeSink entrypoint.
  - added focused helper regression in `tests/unit/display/test_safe_sink.py` and confirmed existing serve/MCP formatter suites remain green.
- Completed: M1 Plan D grep migration slice routed fallback per-candidate authorization through `FilesystemAccessGateway` and added focused blocked/outside/symlink grep tests.
- Completed: M1 Plan D tool migrations (`glob`, `outline`, `concat_files`, `grep`) to `FilesystemAccessGateway`; remaining Plan D work is consolidated regression/perf guard coverage.
- Completed: M1 Plan D consolidated blocked-path/symlink regression coverage across migrated tool tests (`glob`, `outline`, `concat_files`, `grep`).
- Completed: M2 Plan C Phase 1 destroy-path request-context slice:
  - added immutable `RequestContext` model (`nexus3/core/request_context.py`)
  - removed global mutable requester field in `GlobalDispatcher`
  - propagated request context through global dispatcher destroy flow into pool authorization call
- Completed: M2 Plan A Phase 2 destroy-path shadow parity slice in `nexus3/rpc/pool.py`:
  - added destroy authorization kernel adapter in pool-local shadow mode
  - compute both legacy and kernel decisions in `AgentPool.destroy`
  - continue enforcing legacy allow/deny behavior only
  - emit structured warning when legacy/kernel decisions diverge
- Completed: M2 Plan A Phase 2+3 target-authorization shadow parity slice in `nexus3/session/enforcer.py`:
  - added adapter-backed shadow decision comparison in `_check_target_allowed`
  - kept legacy target restriction enforcement authoritative
  - added structured mismatch warning (`target_auth_shadow_mismatch`) and focused parity tests
- Completed: M2 Plan A Phase 2+3 tool-action authorization shadow parity slice in `nexus3/session/enforcer.py`:
  - added adapter-backed shadow decision comparison in `_check_action_allowed`
  - kept legacy action restriction enforcement authoritative
  - added structured mismatch warning (`tool_action_auth_shadow_mismatch`) and focused parity tests
- Completed: M2 Plan A Phase 2+3 send-lifecycle authorization shadow parity slice in `nexus3/rpc/dispatcher.py`:
  - added adapter-backed shadow decision comparison in `_handle_send` against existing YOLO/REPL legacy check.
  - kept legacy send restriction enforcement authoritative.
  - added structured mismatch warning (`send_auth_shadow_mismatch`) and focused parity tests in `tests/unit/test_rpc_dispatcher.py`.
- Completed: M2 Plan A Phase 2+3 create-lifecycle authorization shadow parity slice in `nexus3/rpc/pool.py`:
  - added adapter-backed shadow decision comparison around create parent ceiling gates (`max depth`, base `can_grant`, delta `can_grant`).
  - kept legacy create permission enforcement authoritative.
  - added structured mismatch warning (`create_auth_shadow_mismatch`) and focused parity tests in `tests/unit/rpc/test_pool_create_auth_shadow.py`.
- Completed: M2 Plan A Phase 2+3 create-lifecycle delta-branch parity coverage slice:
  - added focused delta-ceiling parity + mismatch warning tests in `tests/unit/rpc/test_pool_create_auth_shadow.py`.
  - confirmed legacy deny path remains authoritative when kernel intentionally diverges.
- Completed: M2 Plan A Phase 2+3 create-requester propagation + requester-binding parity slice:
  - threaded `requester_id` through `nexus3/rpc/agent_api.py -> nexus3/rpc/global_dispatcher.py -> nexus3/rpc/pool.py` for create flow request context parity.
  - added shadow-only requester/parent binding comparison stage (`requester_parent_binding`) in create authorization adapter path.
  - preserved legacy create allow/deny behavior and error semantics as authoritative.
  - added focused regressions in `tests/unit/test_agent_api.py`, `tests/unit/test_pool.py`, and `tests/unit/rpc/test_pool_create_auth_shadow.py`.
- Completed: M2 Plan A Phase 2+3 shutdown-server lifecycle shadow parity slice:
  - added `shutdown_server` shadow authorization-kernel parity comparison in `nexus3/rpc/global_dispatcher.py` with request-context requester usage.
  - preserved legacy always-allow shutdown behavior and response/error semantics as authoritative.
  - added focused parity/mismatch regressions in `tests/unit/test_pool.py` and ingress guard coverage in `tests/unit/rpc/test_schema_ingress_wiring.py`.
- Completed: M2 Plan A Phase 2+3 list-agents lifecycle shadow parity slice:
  - added `list_agents` shadow authorization-kernel parity comparison in `nexus3/rpc/global_dispatcher.py` with request-context requester usage.
  - added direct API requester propagation for `list_agents` and `shutdown_server` in `nexus3/rpc/agent_api.py` for parity telemetry consistency.
  - preserved legacy always-allow list behavior and response semantics as authoritative.
  - added focused parity/mismatch regressions in `tests/unit/test_pool.py`, `tests/unit/test_agent_api.py`, and ingress guard coverage in `tests/unit/rpc/test_schema_ingress_wiring.py`.
- Completed: M2 Plan C Phase 3 execution-skill request-safety slice:
  - removed per-call mutable state from `bash_safe`, `shell_UNSAFE`, and `run_python`
  - refactored subprocess creation helpers to pass command/code as local parameters
  - updated Windows behavior tests to assert subprocess call args directly
  - added focused concurrent `run_python` test for per-call payload isolation
- Completed: Plan H strict-ingress closeout audit slice:
  - centralized direct in-process `Request` envelope validation in `nexus3/rpc/dispatch_core.py`
  - preserved strict boundary behavior while improving malformed `params` key diagnostics for direct dispatch
  - added focused regressions for non-string `params` keys and malformed notification no-response behavior
  - synchronized stale Plan H/rpc docs and status text with the now-strict-default ingress posture
- Completed: Plan C closeout slice in `nexus3/rpc/dispatcher.py`:
  - threaded immutable `RequestContext` into agent-scoped read handlers (`get_tokens`, `get_context`, `get_messages`)
  - removed the last known dispatcher boundary where agent-scoped requester identity was dropped after `dispatch()`
  - added focused propagation regressions in `tests/unit/test_rpc_dispatcher.py`
- Completed: Plan A closeout slice in `nexus3/cli/repl_commands.py`:
  - kernelized live REPL permission mutations for preset changes and tool enable/disable checks through a local `SESSION_WRITE`/`AGENT` authorization adapter
  - preserved existing parent-ceiling deny wording while removing ad hoc branch-specific checks from command handlers
  - fixed preset-switch state retention by preserving `depth`, `session_allowances`, and sandbox `cwd`
  - added focused regressions in `tests/unit/test_repl_commands.py`
- Completed: Plan A final GitLab residual slice:
  - routed `/gitlab on|off` enable checks through the shared kernel-backed permission-mutation helper in `nexus3/cli/repl_commands.py`
  - added pool-local GitLab visibility authorization for create/restore registration in `nexus3/rpc/pool.py`
  - threaded explicit GitLab visibility into VCS registration in `nexus3/skill/vcs/__init__.py` and `nexus3/skill/vcs/gitlab/__init__.py`
  - added focused coverage in `tests/unit/test_gitlab_toggle.py` and `tests/unit/test_pool.py`
- Validation snapshot (2026-03-05, post-merge slices):
  - `.venv/bin/ruff check nexus3/cli/repl.py nexus3/rpc/agent_api.py nexus3/rpc/global_dispatcher.py nexus3/rpc/pool.py nexus3/rpc/protocol.py nexus3/rpc/schemas.py tests/unit/cli/test_repl_safe_sink.py tests/unit/rpc/test_pool_create_auth_shadow.py tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/rpc/test_schemas.py tests/unit/test_agent_api.py tests/unit/test_client.py tests/unit/test_pool.py` passed.
  - `.venv/bin/pytest -v tests/unit/cli/test_repl_safe_sink.py tests/unit/rpc/test_pool_create_auth_shadow.py tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/rpc/test_schemas.py tests/unit/test_agent_api.py tests/unit/test_client.py tests/unit/test_pool.py` passed (`176 passed`, `9 warnings`).
- Validation snapshot (2026-03-05, next execution round):
  - `.venv/bin/ruff check nexus3/rpc/global_dispatcher.py nexus3/cli/repl.py nexus3/cli/serve.py tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/test_pool.py tests/unit/cli/test_repl_safe_sink.py tests/unit/cli/test_serve_safe_sink.py` passed.
  - `.venv/bin/pytest -v tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/test_pool.py tests/unit/cli/test_repl_safe_sink.py tests/unit/cli/test_serve_safe_sink.py` passed (`123 passed`).
- Validation snapshot (2026-03-05, strict-noarg follow-up round):
  - `.venv/bin/ruff check nexus3/rpc/dispatcher.py nexus3/rpc/global_dispatcher.py tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/test_pool.py tests/unit/test_rpc_dispatcher.py` passed.
  - `.venv/bin/mypy nexus3/rpc/dispatcher.py nexus3/rpc/global_dispatcher.py` passed.
  - `.venv/bin/pytest -v tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/test_pool.py tests/unit/test_rpc_dispatcher.py` passed (`112 passed`).
- Validation snapshot (2026-03-05, G/A cleanup + parity round):
  - `.venv/bin/ruff check nexus3/cli/serve.py nexus3/display/safe_sink.py nexus3/mcp/error_formatter.py nexus3/rpc/agent_api.py nexus3/rpc/global_dispatcher.py tests/unit/display/test_safe_sink.py tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/test_agent_api.py tests/unit/test_pool.py` passed.
  - `.venv/bin/mypy nexus3/rpc/agent_api.py nexus3/rpc/global_dispatcher.py nexus3/display/safe_sink.py nexus3/mcp/error_formatter.py` passed.
  - `.venv/bin/pytest -v tests/unit/display/test_safe_sink.py tests/unit/cli/test_serve_safe_sink.py tests/unit/mcp/test_error_formatter.py tests/unit/test_pool.py tests/unit/test_agent_api.py tests/unit/rpc/test_schema_ingress_wiring.py` passed (`178 passed`).
- Validation snapshot (2026-03-05, Plan H closeout round):
  - `.venv/bin/ruff check nexus3/rpc/dispatch_core.py nexus3/rpc/dispatcher.py nexus3/rpc/global_dispatcher.py nexus3/rpc/schemas.py tests/unit/rpc/test_schema_ingress_wiring.py` passed.
  - `.venv/bin/mypy nexus3/rpc/dispatch_core.py nexus3/rpc/dispatcher.py nexus3/rpc/global_dispatcher.py` passed.
  - `.venv/bin/pytest -q tests/unit/rpc/test_schema_ingress_wiring.py` passed (`74 passed`).
- Validation snapshot (2026-03-05, Plan A GitLab residual round):
  - `.venv/bin/ruff check nexus3/cli/repl_commands.py nexus3/rpc/pool.py nexus3/skill/vcs/__init__.py nexus3/skill/vcs/gitlab/__init__.py tests/unit/test_gitlab_toggle.py tests/unit/test_pool.py` passed.
  - `.venv/bin/mypy nexus3/cli/repl_commands.py nexus3/rpc/pool.py nexus3/skill/vcs/__init__.py nexus3/skill/vcs/gitlab/__init__.py` passed.
  - `.venv/bin/pytest -q tests/unit/test_gitlab_toggle.py tests/unit/test_pool.py` passed (`83 passed`).
- Next gate:
  - Plan H: strict-ingress work is effectively complete on this branch; only routine doc drift cleanup should remain if new ingress surfaces land later.
  - Plan A: kernel rollout is effectively complete for this branch scope; only the explicitly deferred `parent_can_grant` request-model boundary remains for future redesign work.
  - Plan G: optional consistency-only polish remains in a few sanitize-then-trusted-print callsites; not security-critical.
  - Operational next step: either commit this validated GitLab residual + Plan H closeout checkpoint, or pause and resume from this status block later.

Compact checkpoint (2026-03-06, post-Plan-H-shim-phase1 pre-compact):
- Branch: `feat/arch-overhaul-execution`.
- Head commit: `e4bdd23`.
- Latest commits:
  - `e4bdd23` docs(status): record plan h shim phase 1 commit in AGENTS
  - `f22de38` plan h shim retirement phase 1: remove parent id wording remap
  - `19e659e` docs(status): record plan a v2 phase 2 commit in AGENTS
  - `0a4f99f` plan a v2 phase 2: compute create ceiling grants in adapter
- Completed in latest slice:
  - Plan H shim-retirement Phase 1 kickoff: inventory + canonical policy +
    first compatibility-only remap removal (`create_agent.parent_agent_id` malformed-ID wording).
  - focused checks passed:
    - `.venv/Scripts/ruff.exe check nexus3/rpc/global_dispatcher.py tests/unit/rpc/test_schema_ingress_wiring.py`
    - `.venv/Scripts/mypy.exe nexus3/rpc/global_dispatcher.py`
    - `.venv/Scripts/pytest.exe -q -p no:cacheprovider tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/test_rpc_dispatcher.py tests/unit/test_global_dispatcher.py tests/unit/test_client.py`
- Next immediate steps (resume order):
  1. Continue Plan H shim-retirement Phase 2 by removing next compatibility-only
     wording shims (start with `create_agent` field-mapping branches in
     `nexus3/rpc/global_dispatcher.py` that still remap pydantic messages).
  2. Update affected expectations in `tests/unit/rpc/test_schema_ingress_wiring.py`.
  3. Re-run the same focused Plan H checks above.
  4. Sync `docs/plans/ARCH-H-RPC-ERROR-SHIM-RETIREMENT-PLAN-2026-03-05.md`,
     `docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md`, and `AGENTS.md`,
     then commit.
- Host caveat:
  - git status still warns about inaccessible leftover temp dirs
    (`.tmp-pytest-debug-root/pytest-of-inc`, `.tmp-pytest-phase2-run5`); these
    are untracked and should be ignored unless explicitly cleaned with fixed ACLs.
- Subagent instruction:
  - If using Codex subagents, explicitly require no escalated/sandbox-bypass
    commands unless absolutely necessary.

Compact checkpoint (2026-03-06, post-M4 closeout + Plan A v2 phase2/3 execution):
- Branch: `feat/arch-overhaul-execution`.
- Most recent commits:
  - `f22de38` plan h shim retirement phase 1: remove parent id wording remap
  - `19e659e` docs(status): record plan a v2 phase 2 commit in AGENTS
  - `0a4f99f` plan a v2 phase 2: compute create ceiling grants in adapter
  - `5c9c0e2` plan a v2 phase 1: add typed create auth context model
  - `8630f8f` post-m4 closeout: archive windows host evidence and pass gate
- Plan A v2 execution completed:
  - Phase 2/3: adapter-local base/delta ceiling evaluation from typed context
    payloads and removal of pool-side `parent_can_grant` precompute.
  - Added focused adapter-authoritative regressions and updated create-stage
    context assertions (`test_pool_create_auth_shadow.py`, `test_pool.py`).
- Plan H shim-retirement status:
  - Phase 1 completed (`f22de38`): retired compatibility-only malformed
    `create_agent.parent_agent_id` wording remap and switched to canonical
    validation diagnostics.
- Validation snapshot (local phase2/3 changes):
  - passed: focused `ruff` and `mypy` checks for auth-kernel/pool/tests.
  - passed: focused non-`tmp_path` pytest set for typed context + create
    adapter ceiling behavior.
  - blocked: broader `tmp_path`-using pytest coverage due host ACL denials on
    pytest temp roots (`WinError 5`, `pytest-of-inc`).
- Resume command set:
  1. `git status --short --branch`
  2. `Get-Content docs/plans/ARCH-A-AUTH-REQUEST-MODEL-V2-PLAN-2026-03-05.md`
  3. `rg -n "parent_can_grant|parent_permissions_json|requested_permissions_json" nexus3/core/authorization_kernel.py nexus3/rpc/pool.py`
  4. run focused checks, then commit phase2/3 + docs status updates.
- Subagent note:
  - If using Codex subagents, explicitly instruct: no escalated/sandbox-bypass
    commands unless absolutely required by the task.

Resume-first checklist (post-compact):
1. Confirm branch + cleanliness: `git status --short --branch` (ignore existing unrelated untracked: `docs/plans/DOUBLE-SPINNER-FIX-PLAN.md`, `editors/`, `err/`).
2. Re-open plan checklists:
   - `docs/plans/ARCH-H-STRICT-SCHEMA-GATES-PLAN-2026-03-02.md`
   - `docs/plans/ARCH-G-TERMINAL-SAFE-SINK-PLAN-2026-03-02.md`
   - `docs/plans/ARCH-A-AUTH-KERNEL-PLAN-2026-03-02.md`
3. Dispatch Codex subagents with no-escalation instruction and scoped ownership.
4. After each accepted slice:
   - run focused `.venv/bin/ruff`, `.venv/bin/mypy` (where typed modules changed), and targeted `.venv/bin/pytest`
   - update both the relevant plan checklist and this `AGENTS.md` status block in the same session
   - commit in a single logical unit.

Recovery note:
- If interrupted, restart from this section and `docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md`, then continue checklist-driven execution.

Compact checkpoint (2026-03-05, end of session):
- Branch head: `5106528` (docs tracking after round 6).
- Workspace state at handoff: clean tracked tree; ignore unrelated untracked (`docs/plans/DOUBLE-SPINNER-FIX-PLAN.md`, `editors/`, `err/`).
- Immediate next execution slices:
  1. Plan H: evaluate strict-default ingress flips where compat behavior is now proven by tests (start with request/response envelope paths in `nexus3/rpc/protocol.py`).
  2. Plan G: migrate remaining dynamic `console.print`/`spinner.print` surfaces in `nexus3/cli/repl.py` not yet routed through SafeSink formatter helpers.
  3. Plan A: identify next lifecycle authorization callsite beyond current enforcer/pool/dispatcher coverage and add shadow parity + focused tests.

Compact checkpoint (2026-03-05, architecture execution round):
- Branch head at start of round: `5106528`; working tree now includes new Plan H/G/A execution slices plus docs/status updates.
- New slices completed this round:
  1. Plan H strict-envelope ingress slice (unknown top-level JSON-RPC request/response fields now rejected).
  2. Plan G REPL/client/discovery dynamic output migration slice to SafeSink.
  3. Plan A create requester-context propagation + requester/parent binding shadow parity slice.
- Validation result for this round:
  - Integrated targeted lint/test suites passed (`176 passed`, `9 warnings`).
- Immediate resume targets:
  1. Plan H: remaining method-param compatibility tightening in dispatcher/global-dispatcher handlers.
  2. Plan G: residual top-level CLI output surfaces (`main`, `_run_with_reload`, `serve.py`) and redundant sanitizer cleanup.
  3. Plan A: identify next lifecycle authorization adapter parity slice and sequence toward duplicate branch removal.

Compact checkpoint (2026-03-05, architecture execution round 2):
- Branch head at start of round: `5270ad6`; working tree now includes follow-up Plan H/G/A slices plus docs/status updates.
- New slices completed this round:
  1. Plan H destroy ingress strictness slice (unknown extra params for `destroy_agent` now rejected).
  2. Plan G top-level REPL/serve residual dynamic output migration to SafeSink.
  3. Plan A shutdown-server lifecycle shadow parity slice.
- Validation result for this round:
  - Integrated targeted lint/test suites passed (`123 passed`).
- Immediate resume targets:
  1. Plan H: strictness tightening for remaining compat-only no-arg/extra-param handlers.
  2. Plan G: remove fragmented duplicate formatter/sanitization helper branches.
  3. Plan A: next lifecycle adapter parity slice before duplicate branch removal.

Compact checkpoint (2026-03-05, architecture execution round 3):
- Branch head at start of round: `c26ef61`; working tree now includes a follow-up Plan H strict-noarg ingress slice.
- New slice completed this round:
  1. Plan H strict no-arg handler flip (`shutdown`, `get_tokens`, `get_context`, `cancel_all`, `list_agents`, `shutdown_server`) now rejects extra params.
- Validation result for this round:
  - targeted lint + mypy + pytest suites passed (`112 passed`).
- Immediate resume targets:
  1. Plan H: remaining behavior-sensitive compat branches.
  2. Plan G: formatter/sanitization dedup cleanup.
  3. Plan A: next lifecycle adapter parity slice before duplicate branch removal.

Compact checkpoint (2026-03-05, architecture execution round 4):
- Branch head at start of round: `6c66b85`; working tree now includes Plan G SafeSink dedup and Plan A list-agents parity slices.
- New slices completed this round:
  1. Plan G SafeSink helper dedup (`sanitize_print_value`) and local-wrapper removal in serve/MCP formatter paths.
  2. Plan A `list_agents` lifecycle shadow parity + direct API requester propagation consistency.
- Validation result for this round:
  - integrated lint + mypy + pytest suites passed (`178 passed`).
- Immediate resume targets:
  1. Plan H: remaining behavior-sensitive compat branches.
  2. Plan G: identify any remaining fragmented sanitizer/formatter call-site branches for consolidation.
  3. Plan A: next lifecycle adapter parity slice before duplicate branch removal.

Compact checkpoint (2026-03-05, pre-compact handover):
- Branch head at handover: `026e9f3`.
- Working tree status: clean tracked files; ignore unrelated existing untracked paths (`docs/plans/DOUBLE-SPINNER-FIX-PLAN.md`, `editors/`, `err/`).
- Latest validated state:
  - Plan H strict ingress slices applied through strict no-arg handler flips.
  - Plan G dedup slice applied (`SafeSink.sanitize_print_value`) with serve/MCP formatter wrapper cleanup.
  - Plan A parity slices applied through `shutdown_server` and `list_agents` lifecycle shadow coverage.
  - Latest integrated validation suite passed (`178 passed`) with ruff+mypy green.
- Resume order after compact:
  1. Plan H: identify and tighten remaining behavior-sensitive compatibility branches (if any) and confirm strict-default posture completeness.
  2. Plan G: audit for remaining fragmented sanitization/formatter call sites and consolidate to shared SafeSink entrypoints.
  3. Plan A: select next lifecycle parity adapter slice, then begin planning/sequence for duplicate authorization branch removal.
- SOP reminder:
  - Continue checklist-driven execution and update both relevant plan docs and this `AGENTS.md` status/checkpoint block in the same session before each commit.

Compact checkpoint (2026-03-06, architecture execution round 5):
- Branch head at start of round: `8bd8783`; working tree now includes a Plan H behavior-sensitive strict ingress follow-up.
- New slice completed this round:
  1. Plan H strict `create_agent` ingress hardening (`nexus3/rpc/global_dispatcher.py`) now validates full params object and rejects unknown extra params.
  2. Plan H removed legacy conditional bypass that ignored malformed `wait_for_initial_response` when `initial_message` was absent.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/global_dispatcher.py tests/unit/rpc/test_schema_ingress_wiring.py` passed.
  - `.venv/bin/pytest -v tests/unit/rpc/test_schema_ingress_wiring.py` passed (`47 passed`).
- Immediate resume targets:
  1. Plan H: tighten remaining behavior-sensitive compat branches (`send`, `cancel`, `compact`) where safe.
  2. Plan G: continue sanitization/formatter consolidation from remaining REPL and display fragmented call sites.
  3. Plan A: add next agent-scoped lifecycle shadow parity slice (`shutdown`/`cancel`/`compact`) with requester-context hardening.

Compact checkpoint (2026-03-06, architecture execution round 6):
- Branch head at start of round: `a1362a5`; working tree now includes parallel Plan G and Plan A follow-up slices.
- New slices completed this round:
  1. Plan G consolidated `nexus3/mcp/skill_adapter.py` result sanitization onto `SafeSink` shared entrypoint and added focused adapter sanitization regressions.
  2. Plan A added agent-scoped lifecycle shadow parity in `nexus3/rpc/dispatcher.py` for `shutdown`/`cancel`/`compact` with legacy behavior still authoritative.
  3. Plan A propagated trusted requester context through agent-scoped API dispatch (`nexus3/rpc/agent_api.py`) and updated send-shadow principal selection to prefer trusted requester identity when available.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/mcp/skill_adapter.py nexus3/rpc/dispatcher.py nexus3/rpc/agent_api.py tests/unit/mcp/test_skill_adapter.py tests/unit/test_rpc_dispatcher.py tests/unit/test_agent_api.py` passed.
  - `.venv/bin/mypy nexus3/rpc/dispatcher.py nexus3/rpc/agent_api.py nexus3/mcp/skill_adapter.py` passed.
  - `.venv/bin/pytest -v tests/unit/mcp/test_skill_adapter.py tests/unit/test_rpc_dispatcher.py tests/unit/test_agent_api.py` passed (`42 passed`).
- Immediate resume targets:
  1. Plan H: tighten remaining behavior-sensitive compat ingress in dispatcher (`send`, `cancel`, `compact`) and evaluate strict flips with legacy error wording preservation.
  2. Plan G: continue remaining fragmented sanitizer consolidation in display/REPL residual call sites (`spinner.py`, `streaming.py`, and any remaining direct dynamic prints).
  3. Plan A: identify first safe duplicate authorization branch removal candidate after parity telemetry stabilization.

Compact checkpoint (2026-03-06, architecture execution round 7):
- Branch head at start of round: `256683b`; working tree now includes parallel Plan H and Plan G strictness/consolidation follow-ups.
- New slices completed this round:
  1. Plan H tightened dispatcher ingress for `send`/`cancel`/`compact` to reject unknown extra params while preserving legacy field-specific invalid-params wording.
  2. Plan G consolidated display-layer sanitizer routing in `nexus3/display/spinner.py` and `nexus3/display/streaming.py` to shared `SafeSink` entrypoints.
  3. Added focused regressions in `tests/unit/rpc/test_schema_ingress_wiring.py` and `tests/unit/display/test_escape_sanitization.py` for the new strictness/sanitizer paths.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/dispatcher.py tests/unit/rpc/test_schema_ingress_wiring.py nexus3/display/spinner.py nexus3/display/streaming.py tests/unit/display/test_escape_sanitization.py` passed.
  - `.venv/bin/mypy nexus3/rpc/dispatcher.py nexus3/display/spinner.py nexus3/display/streaming.py` passed.
  - `.venv/bin/pytest -v tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/display/test_escape_sanitization.py tests/unit/display/test_safe_sink.py` passed (`96 passed`).
- Immediate resume targets:
  1. Plan H: decide on remaining compatibility-only protocol parse path (`empty method` rewrite) and whether to flip to strict reject.
  2. Plan G: sweep residual direct dynamic `console.print` sites in `nexus3/cli/repl.py` and low-risk CLI consistency paths for final consolidation.
  3. Plan A: plan/execute first safe duplicate-authorization-branch removal slice after shadow telemetry coverage.

Compact checkpoint (2026-03-06, architecture execution round 8):
- Branch head at start of round: `514c799`; working tree now includes a Plan A phase-4 starter cleanup slice.
- New slice completed this round:
  1. Plan A converted `list_agents` and `shutdown_server` in `nexus3/rpc/global_dispatcher.py` from shadow-only legacy-allow parity to kernel-authoritative enforcement.
  2. Removed duplicate legacy-allow comparison/warning branches for those two methods and added fail-closed deny-path assertions in `tests/unit/test_pool.py`.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/global_dispatcher.py tests/unit/test_pool.py` passed.
  - `.venv/bin/mypy nexus3/rpc/global_dispatcher.py` passed.
  - `.venv/bin/pytest -v tests/unit/test_pool.py` passed (`55 passed`).
- Immediate resume targets:
  1. Plan A: evaluate next safe duplicate-branch removal candidate (`rpc/dispatcher.py` lifecycle checks) while preserving external error semantics.
  2. Plan H: decide on remaining compatibility-only protocol parse path (`empty method` rewrite) and whether to flip to strict reject.
  3. Plan G: sweep residual direct dynamic `console.print` sites in `nexus3/cli/repl.py` and low-risk CLI consistency paths for final consolidation.

Compact checkpoint (2026-03-06, architecture execution round 9):
- Branch head at start of round: `049cba6`; working tree now includes parallel Plan A + Plan G follow-up slices.
- New slices completed this round:
  1. Plan A converted agent-scoped lifecycle authorization in `nexus3/rpc/dispatcher.py` (`shutdown`/`cancel`/`compact`) from shadow parity to kernel-authoritative enforcement with a shared lifecycle auth gate.
  2. Plan G removed remaining unsanitized plain command output rendering in `nexus3/cli/repl.py` by routing through a SafeSink-backed plain formatter helper.
  3. Updated focused regressions in `tests/unit/test_rpc_dispatcher.py` and `tests/unit/cli/test_repl_safe_sink.py`.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/dispatcher.py tests/unit/test_rpc_dispatcher.py nexus3/cli/repl.py tests/unit/cli/test_repl_safe_sink.py` passed.
  - `.venv/bin/mypy nexus3/rpc/dispatcher.py nexus3/cli/repl.py` passed.
  - `.venv/bin/pytest -v tests/unit/test_rpc_dispatcher.py tests/unit/cli/test_repl_safe_sink.py` passed (`40 passed`).
- Immediate resume targets:
  1. Plan A: evaluate remaining duplicate authorization branches (`send` path parity branch and pool/session branches) for next safe kernel-authoritative flip.
  2. Plan H: decide on remaining compatibility-only protocol parse path (`empty method` rewrite) and whether to flip to strict reject.
  3. Plan G: continue residual dynamic REPL print sweep and minor CLI consistency consolidation.

Compact checkpoint (2026-03-06, architecture execution round 10):
- Branch head at start of round: `f0836e0`; working tree now includes Plan H protocol strictness follow-up.
- New slice completed this round:
  1. Plan H removed `parse_request` empty-string method compatibility shim in `nexus3/rpc/protocol.py` and now rejects empty method values with explicit ParseError wording (`method must be a non-empty string`).
  2. Updated focused ingress regression in `tests/unit/rpc/test_schema_ingress_wiring.py` to assert strict reject behavior.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/protocol.py tests/unit/rpc/test_schema_ingress_wiring.py` passed.
  - `.venv/bin/mypy nexus3/rpc/protocol.py` passed.
  - `.venv/bin/pytest -v tests/unit/rpc/test_schema_ingress_wiring.py` passed (`49 passed`).
- Immediate resume targets:
  1. Plan A: evaluate remaining duplicate authorization branches (`send` path parity branch and pool/session branches) for next safe kernel-authoritative flip.
  2. Plan G: continue residual dynamic REPL print sweep and minor CLI consistency consolidation.
  3. Plan H: audit for any remaining compatibility-only protocol/schema behaviors and either retire or document them.

Compact checkpoint (2026-03-06, architecture execution round 11):
- Branch head at start of round: `515237e`; working tree now includes Plan A send-authorization duplicate-branch removal.
- New slice completed this round:
  1. Plan A converted `send` authorization in `nexus3/rpc/dispatcher.py` from shadow parity to kernel-authoritative enforcement.
  2. Preserved trusted requester precedence and kept legacy YOLO/no-REPL deny wording (`Cannot send to YOLO agent - no REPL connected`) via explicit kernel-reason mapping.
  3. Updated send authorization unit coverage in `tests/unit/test_rpc_dispatcher.py` for authoritative allow/deny behavior.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/dispatcher.py tests/unit/test_rpc_dispatcher.py` passed.
  - `.venv/bin/mypy nexus3/rpc/dispatcher.py` passed.
  - `.venv/bin/pytest -v tests/unit/test_rpc_dispatcher.py` passed (`17 passed`).
- Immediate resume targets:
  1. Plan A: evaluate remaining duplicate authorization branches in pool/session enforcement paths for next safe kernel-authoritative flip.
  2. Plan G: continue residual dynamic REPL print sweep and minor CLI consistency consolidation.
  3. Plan H: audit for any remaining compatibility-only protocol/schema behaviors and either retire or document them.

Compact checkpoint (2026-03-06, architecture execution round 12):
- Branch head at start of round: `9a9b073`; working tree now includes Plan A `AgentPool.destroy` duplicate-branch removal.
- New slice completed this round:
  1. Plan A converted destroy authorization in `nexus3/rpc/pool.py` from shadow parity to kernel-authoritative enforcement.
  2. Preserved existing user-facing `AuthorizationError` wording while removing legacy shadow-only branch logic.
  3. Added focused destroy authorization coverage in `tests/unit/test_pool.py` (self allow, parent allow, unauthorized deny, forced kernel deny authoritative behavior).
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/pool.py tests/unit/test_pool.py` passed.
  - `.venv/bin/mypy nexus3/rpc/pool.py` passed.
  - `.venv/bin/pytest -v tests/unit/test_pool.py` passed (`59 passed`).
- Immediate resume targets:
  1. Plan A: evaluate remaining duplicate authorization branches in session enforcer policy checks for next safe kernel-authoritative flip.
  2. Plan G: continue residual dynamic REPL print sweep and minor CLI consistency consolidation.
  3. Plan H: audit for any remaining compatibility-only protocol/schema behaviors and either retire or document them.

Compact checkpoint (2026-03-06, architecture execution round 13):
- Branch head at start of round: `35c5914`; working tree now includes Plan G REPL consistency cleanup.
- New slice completed this round:
  1. Plan G replaced remaining dynamic direct f-string prints in `nexus3/cli/repl.py` (additional-port scanning lines, startup-timeout port line, thought-duration spinner line) with SafeSink-backed helper formatters.
  2. Added focused helper coverage in `tests/unit/cli/test_repl_safe_sink.py` for the new formatter paths.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/cli/repl.py tests/unit/cli/test_repl_safe_sink.py` passed.
  - `.venv/bin/mypy nexus3/cli/repl.py` passed.
  - `.venv/bin/pytest -v tests/unit/cli/test_repl_safe_sink.py` passed (`25 passed`).
- Immediate resume targets:
  1. Plan A: evaluate remaining duplicate authorization branches in session enforcer policy checks for next safe kernel-authoritative flip.
  2. Plan G: sweep any final minor CLI consistency paths (`repl_commands` sharing prompt path) and verify no remaining fragmented sanitizer usage.
  3. Plan H: audit for any remaining compatibility-only protocol/schema behaviors and either retire or document them.

Compact checkpoint (2026-03-06, architecture execution round 14):
- Branch head at start of round: `1bc1800`; working tree now includes Plan A session-action authorization cleanup.
- New slice completed this round:
  1. Plan A converted `session/enforcer.py::_check_action_allowed` to kernel-authoritative enforcement.
  2. Removed tool-action shadow-mismatch warning branch for this method while preserving deny wording (`Tool '<tool>' is not allowed at current permission level`).
  3. Updated action-authorization coverage in `tests/unit/session/test_enforcer.py` for authoritative behavior.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/session/enforcer.py tests/unit/session/test_enforcer.py` passed.
  - `.venv/bin/mypy nexus3/session/enforcer.py` passed.
  - `.venv/bin/pytest -v tests/unit/session/test_enforcer.py` passed (`31 passed`).
- Immediate resume targets:
  1. Plan A: evaluate whether `session/enforcer.py::_check_target_allowed` can be safely flipped to kernel-authoritative (currently still shadow parity).
  2. Plan G: sweep final minor CLI consistency paths (`repl_commands` sharing prompt path) and verify no fragmented sanitizer usage remains.
  3. Plan H: audit for any remaining compatibility-only protocol/schema behaviors and either retire or document them.

Compact checkpoint (2026-03-06, pre-compact handover):
- Tracked working tree currently includes the round-14 Plan A session-action slice plus docs/status updates.
- Ready-to-commit files:
  - `nexus3/session/enforcer.py`
  - `tests/unit/session/test_enforcer.py`
  - `docs/plans/ARCH-A-AUTH-KERNEL-PLAN-2026-03-02.md`
  - `AGENTS.md`
- Validation already completed and green for this slice (ruff + mypy + pytest as listed above).
- Existing unrelated untracked paths remain intentionally untouched: `docs/plans/DOUBLE-SPINNER-FIX-PLAN.md`, `editors/`, `err/`.
- Resume-first command after compact:
  - `git status --short --branch`
  - then continue from this section and Plan A checklist.

Compact checkpoint (2026-03-06, architecture execution round 15):
- Branch head at start of round: `11297f4`; working tree now includes parallel Plan A + Plan H follow-up slices.
- New slices completed this round:
  1. Plan A converted `session/enforcer.py::_check_target_allowed` from shadow parity to kernel-authoritative enforcement.
  2. Removed target-authorization legacy/shadow mismatch warning branch while preserving target-deny wording semantics.
  3. Plan H tightened `rpc/dispatcher.py::_handle_get_messages` ingress to strict full-param validation so unknown extra params are rejected (no more candidate-field projection that dropped extras).
  4. Updated focused regressions in `tests/unit/session/test_enforcer.py` and `tests/unit/rpc/test_schema_ingress_wiring.py` for authoritative/strict behavior.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/session/enforcer.py nexus3/rpc/dispatcher.py tests/unit/session/test_enforcer.py tests/unit/rpc/test_schema_ingress_wiring.py` passed.
  - `.venv/bin/mypy nexus3/session/enforcer.py nexus3/rpc/dispatcher.py` passed.
  - `.venv/bin/pytest -v tests/unit/session/test_enforcer.py tests/unit/rpc/test_schema_ingress_wiring.py` passed (`85 passed`).
- Immediate resume targets:
  1. Plan A: evaluate next safe kernel-authoritative flip for create authorization in `rpc/pool.py::_create_unlocked` (currently still legacy-authoritative with kernel shadow compare).
  2. Plan H: evaluate strict-value (not just extra-key) flips for behavior-sensitive handlers still using `strict=False` (`send`, `cancel`, `compact`, `create_agent`) and protocol `error` object strict typing.
  3. Plan G: finish residual sink-boundary cleanup in `display/streaming.py` tool metadata rendering and remaining dynamic REPL command-result print paths.

Compact checkpoint (2026-03-06, architecture execution round 16):
- Branch head at start of round: `a388420`; working tree now includes Plan G closure slices.
- New slices completed this round:
  1. Plan G hardened dynamic render boundaries in `nexus3/display/streaming.py` (tool name/params + batch active tool name) to sanitize at sink boundary.
  2. Plan G replaced remaining dynamic REPL command-result lines in `nexus3/cli/repl.py` with SafeSink-backed formatters (switch/whisper/create/restore outputs).
  3. Plan G consolidated confirmation parameter formatting in `nexus3/cli/confirmation_ui.py` onto `SafeSink.sanitize_print_value(...)`.
  4. Plan G hardened prompt-toolkit HTML toolbar/prompt interpolation in `nexus3/cli/repl.py` via `_sanitize_prompt_html_text(...)` and sanitized confirmation full-details pager/editor content in `nexus3/cli/confirmation_ui.py`.
  5. Plan G checklist top-level items are now marked complete in `docs/plans/ARCH-G-TERMINAL-SAFE-SINK-PLAN-2026-03-02.md` after re-audit.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/display/streaming.py nexus3/cli/repl.py nexus3/cli/confirmation_ui.py tests/unit/display/test_escape_sanitization.py tests/unit/cli/test_repl_safe_sink.py tests/unit/cli/test_confirmation_ui_safe_sink.py` passed.
  - `.venv/bin/mypy nexus3/display/streaming.py nexus3/cli/repl.py nexus3/cli/confirmation_ui.py` passed.
  - `.venv/bin/pytest -v tests/unit/display/test_escape_sanitization.py tests/unit/cli/test_repl_safe_sink.py tests/unit/cli/test_confirmation_ui_safe_sink.py` passed (`74 passed`).
- Immediate resume targets:
  1. Plan A: evaluate kernel-authoritative create authorization flip in `rpc/pool.py::_create_unlocked` (highest remaining duplicate-branch security surface).
  2. Plan H: evaluate strict-value flips for behavior-sensitive handlers still using `strict=False` (`send`, `cancel`, `compact`, `create_agent`) while preserving legacy error wording.
  3. Plan H: decide whether to enforce strict typed `error` object shape in `rpc/protocol.py::parse_response` using `RpcErrorObjectSchema`.

Compact checkpoint (2026-03-06, architecture execution round 17):
- Branch head at start of round: `e24a164`; working tree now includes a focused Plan H strict-value ingress follow-up.
- New slice completed this round:
  1. Plan H tightened `rpc/dispatcher.py::_handle_cancel` from compat-style value coercion (`strict=False`) to strict-value schema validation (`strict=True`).
  2. Preserved existing invalid-params wording semantics for missing/malformed `request_id` and lifecycle authorization deny wording.
  3. Extended focused ingress regressions in `tests/unit/rpc/test_schema_ingress_wiring.py` to assert float `request_id` rejection and integer `request_id` happy-path behavior.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/dispatcher.py tests/unit/rpc/test_schema_ingress_wiring.py` passed.
  - `.venv/bin/mypy nexus3/rpc/dispatcher.py` passed.
  - `.venv/bin/pytest -v tests/unit/rpc/test_schema_ingress_wiring.py` passed (`56 passed`).
- Immediate resume targets:
  1. Plan H: evaluate next strict-value flip candidate (`send` or `compact`) with legacy wording preservation.
  2. Plan H: assess `rpc/protocol.py::parse_response` strict typed `error` object enforcement via `RpcErrorObjectSchema`.
  3. Plan A: continue duplicate-authorization-branch removal in `rpc/pool.py::_create_unlocked` (create authorization still legacy-authoritative).

Compact checkpoint (2026-03-06, architecture execution round 18):
- Branch head at start of round: `e89fb4b`; working tree now includes a second focused Plan H strict-value ingress follow-up.
- New slice completed this round:
  1. Plan H tightened `rpc/dispatcher.py::_handle_compact` from compat-style value coercion (`strict=False`) to strict-value schema validation (`strict=True`).
  2. Preserved existing invalid-params wording behavior while adding strictness regressions for coercible non-bool `force` values.
  3. Extended focused ingress coverage in `tests/unit/rpc/test_schema_ingress_wiring.py` (`force='true'` and `force=1` now rejected; existing invalid-force/extra-param assertions retained).
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/dispatcher.py tests/unit/rpc/test_schema_ingress_wiring.py` passed.
  - `.venv/bin/mypy nexus3/rpc/dispatcher.py` passed.
  - `.venv/bin/pytest -v tests/unit/rpc/test_schema_ingress_wiring.py` passed (`58 passed`).
- Immediate resume targets:
  1. Plan H: evaluate strict-value flip for `_handle_send` while preserving established field-specific invalid-params wording.
  2. Plan H: assess strict typed `error` object enforcement in `rpc/protocol.py::parse_response` using `RpcErrorObjectSchema`.
  3. Plan A: resume create-authorization duplicate-branch removal in `rpc/pool.py::_create_unlocked`.

Compact checkpoint (2026-03-06, architecture execution round 19):
- Branch head at start of round: `cb7558b`; working tree now includes a third focused Plan H strict-value ingress follow-up.
- New slice completed this round:
  1. Plan H tightened `rpc/dispatcher.py::_handle_send` from compat-style value coercion (`strict=False`) to strict-value schema validation (`strict=True`).
  2. Preserved existing field-specific invalid-params wording for `content`, `request_id`, `source`, and `source_agent_id`.
  3. Expanded focused ingress regressions in `tests/unit/rpc/test_schema_ingress_wiring.py` to reject coercion cases (`request_id=1.0`, `source=b\"rpc\"`, `source_agent_id=1.0`) while retaining previous valid-path behavior.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/dispatcher.py tests/unit/rpc/test_schema_ingress_wiring.py` passed.
  - `.venv/bin/mypy nexus3/rpc/dispatcher.py` passed.
  - `.venv/bin/pytest -v tests/unit/rpc/test_schema_ingress_wiring.py` passed (`61 passed`).
- Immediate resume targets:
  1. Plan H: assess strict typed `error` object enforcement in `rpc/protocol.py::parse_response` using `RpcErrorObjectSchema`.
  2. Plan H: evaluate strict-value flip for `create_agent` ingress in `rpc/global_dispatcher.py` (higher-risk surface).
  3. Plan A: resume create-authorization duplicate-branch removal in `rpc/pool.py::_create_unlocked`.

Compact checkpoint (2026-03-06, architecture execution round 20):
- Branch head at start of round: `59ad445`; working tree now includes Plan H protocol response-envelope strictness follow-up.
- New slice completed this round:
  1. Plan H made `RpcResponseEnvelopeSchema.error` strictly typed (`RpcErrorObjectSchema | None`) in `nexus3/rpc/schemas.py`.
  2. Plan H updated `nexus3/rpc/protocol.py::parse_response` to enforce nested error-object typing while preserving legacy wording for non-object and missing-required-field cases.
  3. Plan H normalized parsed response errors back to plain dict payloads via `model_dump(exclude_none=True)` to avoid model leakage/default-field noise.
  4. Added focused regressions in `tests/unit/rpc/test_schema_ingress_wiring.py` and `tests/unit/rpc/test_schemas.py` for malformed `error.code`/`error.message`, unknown `error` extras, and response error-dict shape.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/schemas.py nexus3/rpc/protocol.py tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/rpc/test_schemas.py` passed.
  - `.venv/bin/mypy nexus3/rpc/schemas.py nexus3/rpc/protocol.py` passed.
  - `.venv/bin/pytest -v tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/rpc/test_schemas.py` passed (`84 passed`).
- Immediate resume targets:
  1. Plan H: evaluate strict-value flip for `create_agent` ingress in `rpc/global_dispatcher.py` (remaining higher-risk behavior-sensitive path).
  2. Plan A: resume create-authorization duplicate-branch removal in `rpc/pool.py::_create_unlocked`.
  3. Plan A: evaluate routing `_check_enabled` through authorization kernel to reduce remaining split policy surface in `session/enforcer.py`.

Compact checkpoint (2026-03-06, pre-compact handover 2):
- Current branch/head: `feat/arch-overhaul-execution` @ `358add2`.
- Tracked working tree: clean.
- Intentional untracked carry-over (do not touch): `docs/plans/DOUBLE-SPINNER-FIX-PLAN.md`, `editors/`, `err/`.
- New commits landed in this execution segment (chronological):
  1. `a388420` - Plan A/H: target authorization kernel-authoritative + strict `get_messages` ingress.
  2. `e24a164` - Plan G closure: residual SafeSink boundaries across REPL/streaming/confirmation.
  3. `e89fb4b` - Plan H: strict-value `cancel` ingress.
  4. `cb7558b` - Plan H: strict-value `compact` ingress.
  5. `59ad445` - Plan H: strict-value `send` ingress.
  6. `358add2` - Plan H: strict typed RPC response `error` object enforcement.
- Resume-first commands after compact:
  1. `git status --short --branch`
  2. `git log --oneline -n 8`
  3. `rg -n \"architecture execution round|pre-compact handover\" AGENTS.md`
- First implementation target after resume:
  1. Plan H `create_agent` strict-value ingress evaluation in `nexus3/rpc/global_dispatcher.py` + focused ingress regressions.
  2. Then return to Plan A `rpc/pool.py::_create_unlocked` duplicate-branch removal.

Compact checkpoint (2026-03-06, architecture execution round 21):
- Branch head at start of round: `6a0c64b`; working tree now includes parallel Plan A + Plan H + Plan G follow-up slices implemented via Codex subagents.
- New slices completed this round:
  1. Plan A converted create authorization in `nexus3/rpc/pool.py::_create_unlocked` from legacy-authoritative shadow parity to kernel-authoritative enforcement.
  2. Plan A removed dead create shadow-mismatch branch/logging (`_compare_create_authorization_shadow`) and preserved legacy `PermissionError` wording for max-depth/base-ceiling/delta-ceiling denies.
  3. Plan H tightened `nexus3/rpc/global_dispatcher.py::_handle_create_agent` to strict-value schema validation (`CreateAgentParamsSchema(..., strict=True)`), preserving established malformed-field error wording and rejecting coercible wait-flag values.
  4. Plan G closed residual sink-boundary cleanup by sanitizing dynamic spinner status text in `nexus3/display/spinner.py::__rich__` and routing residual REPL dynamic port/codepage lines through SafeSink-backed helpers in `nexus3/cli/repl.py`.
  5. Updated focused regressions in `tests/unit/rpc/test_pool_create_auth_shadow.py`, `tests/unit/test_pool.py`, `tests/unit/rpc/test_schema_ingress_wiring.py`, `tests/unit/display/test_escape_sanitization.py`, and `tests/unit/cli/test_repl_safe_sink.py`.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/pool.py nexus3/rpc/global_dispatcher.py nexus3/display/spinner.py nexus3/cli/repl.py tests/unit/rpc/test_pool_create_auth_shadow.py tests/unit/test_pool.py tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/display/test_escape_sanitization.py tests/unit/cli/test_repl_safe_sink.py docs/plans/ARCH-A-AUTH-KERNEL-PLAN-2026-03-02.md docs/plans/ARCH-G-TERMINAL-SAFE-SINK-PLAN-2026-03-02.md docs/plans/ARCH-H-STRICT-SCHEMA-GATES-PLAN-2026-03-02.md` passed.
  - `.venv/bin/mypy nexus3/rpc/pool.py nexus3/rpc/global_dispatcher.py nexus3/display/spinner.py nexus3/cli/repl.py` passed.
  - `.venv/bin/pytest -v tests/unit/rpc/test_pool_create_auth_shadow.py tests/unit/test_pool.py tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/display/test_escape_sanitization.py tests/unit/cli/test_repl_safe_sink.py` passed (`206 passed`).
- Immediate resume targets:
  1. Plan A: evaluate remaining duplicate authorization surfaces (notably whether `_check_enabled` can be routed through kernel-authoritative decisions in `session/enforcer.py`) and sequence final duplicate-branch cleanup.
  2. Plan H: optional cleanup pass to remove now-unused compatibility projection helper `project_known_schema_fields(...)` in `nexus3/rpc/schemas.py` (audit confirms no active callsites).
  3. Plan G: perform a final low-risk audit pass for any residual dynamic print interpolation outside SafeSink helper patterns and either close or explicitly document accepted trusted-only exceptions.

Compact checkpoint (2026-03-06, architecture execution round 22):
- Branch head at start of round: `57e7697`; working tree now includes parallel Plan A + Plan H + Plan G follow-up slices implemented via Codex subagents.
- New slices completed this round:
  1. Plan A migrated `session/enforcer.py::_check_enabled` to kernel-authoritative enforcement via `_ToolEnabledAuthorizationAdapter` and `_enabled_authorization_kernel`.
  2. Plan A preserved exact disabled-tool deny wording (`Tool '<tool>' is disabled by permission policy`) and explicit `check_all` ordering behavior (enabled-check short-circuit before action-check deny).
  3. Plan H removed dead RPC schema helper `project_known_schema_fields(...)` from `nexus3/rpc/schemas.py` and updated stale projection-helper wording in the Plan H document.
  4. Plan G hardened output boundaries by introducing explicit spinner trust APIs (`print_trusted(...)`, `print_untrusted(...)`, trusted compatibility alias), sanitizing `InlinePrinter.print_gumball(...)` by default with explicit trusted variant, and routing connect-lobby default-port interpolation through a SafeSink-backed helper.
  5. Updated focused regressions in `tests/unit/session/test_enforcer.py`, `tests/unit/display/test_safe_sink.py`, `tests/unit/display/test_escape_sanitization.py`, and `tests/unit/cli/test_connect_lobby_safe_sink.py`.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/session/enforcer.py nexus3/rpc/schemas.py nexus3/display/spinner.py nexus3/display/printer.py nexus3/cli/connect_lobby.py tests/unit/session/test_enforcer.py tests/unit/display/test_safe_sink.py tests/unit/display/test_escape_sanitization.py tests/unit/cli/test_connect_lobby_safe_sink.py docs/plans/ARCH-A-AUTH-KERNEL-PLAN-2026-03-02.md docs/plans/ARCH-G-TERMINAL-SAFE-SINK-PLAN-2026-03-02.md docs/plans/ARCH-H-STRICT-SCHEMA-GATES-PLAN-2026-03-02.md` passed.
  - `.venv/bin/mypy nexus3/session/enforcer.py nexus3/rpc/schemas.py nexus3/display/spinner.py nexus3/display/printer.py nexus3/cli/connect_lobby.py` passed.
  - `.venv/bin/pytest -v tests/unit/session/test_enforcer.py tests/unit/rpc/test_schemas.py tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/test_client.py tests/unit/display/test_safe_sink.py tests/unit/display/test_escape_sanitization.py tests/unit/cli/test_connect_lobby_safe_sink.py` passed (`195 passed`; expected SSL CA warning noise in `tests/unit/test_client.py` remains unchanged).
- Immediate resume targets:
  1. Plan A: assess whether any remaining authorization checks outside kernel adapters still exist in session/rpc flows and sequence final duplicate-branch cleanup if found.
  2. Plan G: perform a final narrow audit for low-risk trusted-only formatting surfaces and either convert to explicit trusted helpers or document accepted trusted boundaries.
  3. Documentation consistency sweep: mirror any user-visible authorization/safe-sink boundary behavior updates into module README references if needed.

Compact checkpoint (2026-03-06, architecture execution round 23):
- Branch head at start of round: `586c423`; working tree now includes parallel Plan A + Plan G + docs consistency follow-up slices implemented via Codex subagents.
- New slices completed this round:
  1. Plan A removed the remaining non-kernel destroy bypass branch in `nexus3/rpc/pool.py::destroy(...)` by routing external requester (`requester_id=None`) and `admin_override=True` requests through kernel adapter evaluation.
  2. Plan A preserved existing destroy semantics and wording (`self`/`parent` allow, external/admin allow, deny wording unchanged) while adding focused kernel-path coverage for external/admin allow + fail-closed deny behavior in `tests/unit/test_pool.py`.
  3. Plan G applied low-risk trusted-boundary consistency cleanup in CLI flows:
     - helper-level sanitize-by-value formatting for residual dynamic option/prompt lines in `nexus3/cli/connect_lobby.py` and `nexus3/cli/lobby.py`,
     - explicit `SafeSink.print_trusted(...)` usage for YOLO warning output in `nexus3/cli/repl_commands.py`,
     - explicit `spinner.print_trusted(...)` callsites for remaining trusted REPL trace output in `nexus3/cli/repl.py`.
  4. Documentation consistency sweep completed across module READMEs:
     - `nexus3/rpc/README.md` now documents strict ingress schema behavior and kernel-authoritative RPC authorization flow,
     - `nexus3/display/README.md` now reflects explicit spinner trusted/untrusted API and SafeSink trust boundaries,
     - `nexus3/cli/README.md` now reflects SafeSink trust-boundary semantics in security notes,
     - `nexus3/session/README.md` now reflects kernel-authoritative enabled/action/target checks plus path gating.
- Validation result for this round:
  - `.venv/bin/ruff check docs/plans/ARCH-A-AUTH-KERNEL-PLAN-2026-03-02.md docs/plans/ARCH-G-TERMINAL-SAFE-SINK-PLAN-2026-03-02.md nexus3/rpc/pool.py nexus3/cli/connect_lobby.py nexus3/cli/lobby.py nexus3/cli/repl.py nexus3/cli/repl_commands.py nexus3/rpc/README.md nexus3/display/README.md nexus3/cli/README.md nexus3/session/README.md tests/unit/test_pool.py tests/unit/cli/test_connect_lobby_safe_sink.py tests/unit/test_lobby.py tests/unit/cli/test_repl_safe_sink.py` passed.
  - `.venv/bin/mypy nexus3/rpc/pool.py nexus3/cli/connect_lobby.py nexus3/cli/lobby.py nexus3/cli/repl.py nexus3/cli/repl_commands.py` passed.
  - `.venv/bin/pytest -v tests/unit/test_pool.py tests/unit/cli/test_connect_lobby_safe_sink.py tests/unit/test_lobby.py tests/unit/cli/test_repl_safe_sink.py` passed (`137 passed`).
- Immediate resume targets:
  1. Plan A: evaluate next highest-value remaining split authorization surface (`session.py` MCP/GitLab gating and/or path-gating kernel strategy) and decide whether to migrate now or formally defer.
  2. Plan G: only residual work is optional consistency/documentation polish; functional sanitization coverage is now complete for active CLI/display paths.
  3. Keep `CLAUDE.md` and `AGENTS.md` aligned for any additional behavior-level changes in subsequent rounds.

Compact checkpoint (2026-03-06, pre-compact handover 3):
- Current branch/head: `feat/arch-overhaul-execution` @ `f4e4a27`.
- Tracked working tree: clean.
- Intentional untracked carry-over (do not touch): `docs/plans/DOUBLE-SPINNER-FIX-PLAN.md`, `editors/`, `err/`.
- New commits landed in this execution segment (chronological):
  1. `57e7697` - Plan A/G/H: create auth authoritative + strict `create_agent` ingress + sink residual cleanup.
  2. `586c423` - Plan A/G/H: kernelized `_check_enabled`, retired dead schema projection helper, hardened sink boundaries.
  3. `f4e4a27` - Plan A/G: kernelized destroy external/admin contexts + final CLI sink consistency + module README consistency refresh.
- Resume-first commands after compact:
  1. `git status --short --branch`
  2. `git log --oneline -n 8`
  3. `rg -n "architecture execution round 23|pre-compact handover 3" AGENTS.md`
- First implementation targets after compact:
  1. Plan A: decide/execute whether to kernelize remaining session-level MCP/GitLab permission gating in `nexus3/session/session.py` (currently direct `can_use_mcp` / `can_use_gitlab` checks outside `PermissionEnforcer`).
  2. Plan A: evaluate whether create ceiling `can_grant` computations in `nexus3/rpc/pool.py::_create_unlocked` should be migrated fully into adapter-internal policy decisions or explicitly documented as accepted boundary.
  3. Docs sync: if behavior changes in either target, mirror into `nexus3/session/README.md`, `nexus3/rpc/README.md`, and both `AGENTS.md`/`CLAUDE.md`.

Compact checkpoint (2026-03-06, architecture execution round 24):
- Branch head at start of round: `70413db`; working tree now includes parallel Plan A + Plan H follow-up slices implemented via Codex subagents.
- New slices completed this round:
  1. Plan A added unconditional create lifecycle-entry kernel authorization in `nexus3/rpc/pool.py::_create_unlocked` (`check_stage="lifecycle_entry"`), ensuring root and nested create flows always traverse `AGENT_CREATE` kernel checks.
  2. Plan A kernelized session-level MCP/GitLab permission gates in `nexus3/session/session.py` via dedicated `TOOL_EXECUTE` adapters while preserving existing deny wording and confirmation behavior.
  3. Plan A removed the remaining pre-kernel unknown-target bypass in `nexus3/session/enforcer.py::_check_target_allowed` by routing unknown `allowed_targets` shapes through kernel evaluation with preserved fail-open behavior.
  4. Plan H hardened in-process ingress boundaries: `nexus3/rpc/dispatcher.py::dispatch` and `nexus3/rpc/global_dispatcher.py::dispatch` now validate direct `Request` envelopes (`jsonrpc`/`method`/`id`/`params` shape) before handler routing and return deterministic `INVALID_PARAMS` responses for malformed envelopes.
  5. Added focused coverage:
     - `tests/unit/rpc/test_pool_create_auth_shadow.py`
     - `tests/unit/test_pool.py`
     - `tests/unit/session/test_enforcer.py`
     - `tests/unit/session/test_session_permission_kernelization.py` (new)
     - `tests/unit/rpc/test_schema_ingress_wiring.py`
     - `tests/unit/test_rpc_dispatcher.py`
     - `tests/unit/test_global_dispatcher.py` (new)
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/dispatcher.py nexus3/rpc/global_dispatcher.py nexus3/rpc/pool.py nexus3/session/enforcer.py nexus3/session/session.py tests/unit/rpc/test_pool_create_auth_shadow.py tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/session/test_enforcer.py tests/unit/session/test_session_permission_kernelization.py tests/unit/test_pool.py tests/unit/test_rpc_dispatcher.py tests/unit/test_global_dispatcher.py` passed.
  - `.venv/bin/mypy nexus3/rpc/dispatcher.py nexus3/rpc/global_dispatcher.py nexus3/rpc/pool.py nexus3/session/enforcer.py nexus3/session/session.py` passed.
  - `.venv/bin/pytest -v tests/unit/rpc/test_pool_create_auth_shadow.py tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/session/test_enforcer.py tests/unit/session/test_session_permission_kernelization.py tests/unit/test_pool.py tests/unit/test_rpc_dispatcher.py tests/unit/test_global_dispatcher.py` passed (`208 passed`).
- Immediate resume targets:
  1. Plan A: decide whether create ceiling `can_grant` computations in `rpc/pool.py::_create_unlocked` should move fully behind kernel adapter decisions or remain explicit with documented rationale.
  2. Plan A: document/resolve remaining intentional non-kernel surfaces (notably path access checks and agent read methods) and either migrate or mark deferred with explicit scope notes.
  3. Docs sync: keep `CLAUDE.md` aligned with new session-level MCP/GitLab kernelization and direct-dispatch strict-ingress behavior.

Compact checkpoint (2026-03-06, post-round-24 pause handover):
- Current branch/head: `feat/arch-overhaul-execution` @ `ad9380d`.
- Tracked working tree: clean.
- Intentional untracked carry-over (do not touch): `docs/plans/DOUBLE-SPINNER-FIX-PLAN.md`, `editors/`, `err/`.
- Follow-up audit completed with Codex explorer after `ad9380d`:
  1. Remaining high-value non-kernel surfaces are concentrated in MCP/GitLab tool-visibility gating and a few inline lifecycle/HTTP requester-context surfaces.
  2. Recommended next low-risk slice: kernelize MCP tool-visibility gating in `rpc/pool.py` create/restore paths (and REPL refresh if needed) while preserving current behavior.
  3. Recommended focused tests for next slice: `tests/unit/test_pool.py` (MCP visibility allow/deny parity) and `tests/unit/test_repl_commands.py` (refresh path deny behavior).
- Resume-first commands after compact:
  1. `git status --short --branch`
  2. `git log --oneline -n 8`
  3. `rg -n "architecture execution round 24|post-round-24 pause handover" AGENTS.md`

Compact checkpoint (2026-03-05, architecture execution round 25):
- Branch head at start of round: `5d9029a`; working tree now includes a focused Plan A create-hardening slice implemented via Codex worker subagent.
- New slices completed this round:
  1. Plan A hardened `nexus3/rpc/pool.py::_create_unlocked` so parented creates resolve permissions from live parent agent services (`self._agents[parent_agent_id].services["permissions"]`) instead of trusting caller-supplied `config.parent_permissions`.
  2. Plan A now fail-closes parented create when `parent_agent_id` is missing or does not expose valid permissions service.
  3. Plan A ignores forged/mismatched caller `parent_permissions` for parented create and emits warning telemetry (`Parent permissions mismatch for create(...)`), while keeping existing lifecycle/max-depth/base-ceiling/delta-ceiling/requester-binding deny wording unchanged.
  4. Added/updated focused parented-create coverage in `tests/unit/rpc/test_pool_create_auth_shadow.py`:
     - live-parent ceiling enforcement when forged config `parent_permissions` is passed,
     - live-parent ceiling enforcement when `parent_permissions` is omitted,
     - fail-closed behavior when parent agent is missing.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/pool.py tests/unit/rpc/test_pool_create_auth_shadow.py tests/unit/test_pool.py` passed.
  - `.venv/bin/mypy nexus3/rpc/pool.py` passed.
  - `.venv/bin/pytest -q tests/unit/rpc/test_pool_create_auth_shadow.py tests/unit/test_pool.py` passed (`75 passed`).
- Docs/status sync completed this round:
  1. Updated `docs/plans/ARCH-A-AUTH-KERNEL-PLAN-2026-03-02.md` checklist/progress for adapter completion + live-parent create hardening slice.
  2. Updated `nexus3/rpc/README.md` authorization notes to document live parent-permission resolution for parented creates.
  3. Updated `CLAUDE.md` RPC YOLO note to reflect enforcement path wording (RPC create validation + kernel-authoritative create auth).
- Immediate resume targets:
  1. Plan A: evaluate migration of remaining precomputed `parent_can_grant` booleans in create stages into adapter-first policy evaluation (or explicitly document as accepted boundary if deferred).
  2. Plan A: decide next non-kernel surface slice: MCP tool-visibility gating in `rpc/pool.py` create/restore paths vs path-gating consolidation in `session/enforcer.py`.
  3. Keep `AGENTS.md`/`CLAUDE.md`/plan docs checkpointed per major slice before compact.

Compact checkpoint (2026-03-05, architecture execution round 26):
- Branch head at start of round: `5d9029a`; working tree now includes a focused Plan A MCP-visibility kernelization slice implemented via Codex worker subagent.
- New slices completed this round:
  1. Plan A added pool-local MCP visibility authorization adapter/kernel in `nexus3/rpc/pool.py` (`TOOL_EXECUTE` + `mcp_level_allowed` context) to route MCP tool-surface visibility through kernel evaluation.
  2. Plan A replaced direct `can_use_mcp(...)` visibility branching in both create and restore flows with shared helper-backed kernel evaluation (`check_stage="create"` / `"restore"`), preserving existing level semantics and disabled-tool filtering behavior.
  3. Added focused MCP visibility kernel coverage in `tests/unit/test_pool.py` for:
     - create-path kernel routing + allow-path MCP fetch,
     - forced-kernel-deny create behavior (create succeeds, MCP fetch skipped),
     - restore-path kernel routing + level-denied MCP fetch skip.
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/pool.py tests/unit/test_pool.py tests/unit/rpc/test_pool_create_auth_shadow.py` passed.
  - `.venv/bin/mypy nexus3/rpc/pool.py` passed.
  - `.venv/bin/pytest -q tests/unit/test_pool.py tests/unit/rpc/test_pool_create_auth_shadow.py` passed (`78 passed`).
- Docs/status sync completed this round:
  1. Updated `docs/plans/ARCH-A-AUTH-KERNEL-PLAN-2026-03-02.md` with MCP-visibility kernelization progress.
  2. Updated `nexus3/rpc/README.md` authorization notes to include kernel-backed MCP visibility in create/restore paths.
- Immediate resume targets:
  1. Plan A: evaluate remaining high-value non-kernel surface (`session/enforcer.py` path decision gating) for migration vs defer.
  2. Plan A: keep `parent_can_grant` adapter migration deferred until authorization-request model redesign (`Authorization request model v2` style slice).
  3. Keep AGENTS/CLAUDE/plan checkpoints synchronized on each major implementation slice.

Compact checkpoint (2026-03-05, architecture execution round 27):
- Branch head at start of round: `5d9029a`; working tree now includes a focused Plan A decision/guardrail follow-up after round 26.
- New slices completed this round:
  1. Added regression guardrail in `tests/unit/test_pool.py` asserting stable parented-create authorization stage order when delta is present:
     - `lifecycle_entry -> requester_parent_binding -> max_depth -> base_ceiling -> delta_ceiling`.
  2. Completed feasibility investigation for migrating create `parent_can_grant` computation into adapter internals and explicitly deferred that migration as an intentional boundary (current model: pool computes stage booleans, adapter adjudicates).
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/rpc/pool.py tests/unit/test_pool.py tests/unit/rpc/test_pool_create_auth_shadow.py` passed.
  - `.venv/bin/mypy nexus3/rpc/pool.py` passed.
  - `.venv/bin/pytest -q tests/unit/test_pool.py tests/unit/rpc/test_pool_create_auth_shadow.py` passed (`79 passed`).
- Docs/status sync completed this round:
  1. Updated `docs/plans/ARCH-A-AUTH-KERNEL-PLAN-2026-03-02.md` with explicit defer rationale for `parent_can_grant` adapter migration and stage-order guardrail note.
  2. Updated running targets in this file to keep the defer decision sticky across compaction/resume.
- Immediate resume targets:
  1. Plan A: investigate/execute next high-value non-kernel surface (`session/enforcer.py` path decision gating) or document defer boundary.
  2. Plan A: if no low-risk migration remains, mark residual boundaries explicitly and prepare Plan A closeout criteria for this branch.
  3. Keep docs/checklists/AGENTS checkpoints updated per major slice before compact.

Compact checkpoint (2026-03-05, architecture execution round 28):
- Branch head at start of round: `5d9029a`; working tree now includes a focused Plan A `PermissionEnforcer` path-authorization kernelization slice implemented via Codex worker subagent.
- New slices completed this round:
  1. Plan A added `TOOL_EXECUTE`/`PATH` authorization adapter + kernel in `nexus3/session/enforcer.py` and routed `_check_path_allowed(...)` through kernel-authoritative decisions.
  2. Preserved existing `PathDecisionEngine` semantics and legacy path-deny wording; added deterministic fallback wording for forced kernel deny on legacy-allow path (`Access denied by permission policy`).
  3. Added focused path-authorization kernel coverage in `tests/unit/session/test_enforcer.py` (allowed-path pass, legacy-deny wording preservation, forced-kernel-deny authoritative behavior).
- Validation result for this round:
  - `.venv/bin/ruff check nexus3/session/enforcer.py tests/unit/session/test_enforcer.py nexus3/rpc/pool.py tests/unit/test_pool.py tests/unit/rpc/test_pool_create_auth_shadow.py` passed.
  - `.venv/bin/mypy nexus3/session/enforcer.py nexus3/rpc/pool.py` passed.
  - `.venv/bin/pytest -q tests/unit/session/test_enforcer.py tests/unit/test_pool.py tests/unit/rpc/test_pool_create_auth_shadow.py` passed (`117 passed`).
- Docs/status sync completed this round:
  1. Updated `docs/plans/ARCH-A-AUTH-KERNEL-PLAN-2026-03-02.md` with path-authorization kernelization progress.
  2. Updated `nexus3/session/README.md` permission-check ordering notes to reflect kernel-authoritative path allow/deny enforcement.
- Immediate resume targets:
  1. Plan A: determine if any meaningful duplicate authorization branches remain beyond documented intentional boundary (`parent_can_grant` precompute consumed by adapter).
  2. Plan A: if remaining surfaces are accepted boundaries, write explicit Plan A closeout criteria and mark deferred redesign dependency (`Authorization request model v2` style work).
  3. Keep AGENTS/plan/README checkpoints aligned before compact.

Compact checkpoint (2026-03-05, architecture execution round 29):
- Branch head at start of round: `5d9029a`; working tree now includes new Plan A and Plan C cleanup slices implemented via Codex worker subagents.
- New slices completed this round:
  1. Plan C requester-propagation hardening:
     - preserved `requester_id` on agent-scoped HTTP routes in `nexus3/rpc/http.py`
     - propagated requester context into `create_agent` follow-up `initial_message` dispatch in `nexus3/rpc/global_dispatcher.py` for both waiting and queued paths
     - forwarded requester identity through NexusSkill HTTP fallback in `nexus3/skill/base.py` and `nexus3/client.py`
  2. Plan A duplicate-branch cleanup:
     - removed the local parent-ceiling precheck from `nexus3/skill/builtin/nexus_create.py`, leaving create authorization authoritative in RPC/pool kernel flow while preserving downstream error text
- Validation result for this round:
  - Worker validation:
    - `./.venv/bin/ruff check nexus3/client.py nexus3/skill/base.py nexus3/rpc/http.py nexus3/rpc/global_dispatcher.py tests/unit/test_client.py tests/unit/test_http_pipeline_layers.py tests/unit/test_initial_message.py tests/unit/test_nexus_skill_requester_propagation.py` passed.
    - `./.venv/bin/pytest -v tests/unit/test_client.py tests/unit/test_http_pipeline_layers.py tests/unit/test_initial_message.py tests/unit/test_nexus_skill_requester_propagation.py` passed (`50 passed`).
    - `./.venv/bin/ruff check nexus3/skill/builtin/nexus_create.py tests/unit/skill/test_nexus_create.py docs/plans/ARCH-A-AUTH-KERNEL-PLAN-2026-03-02.md` passed.
    - `./.venv/bin/pytest -q tests/unit/skill/test_nexus_create.py` passed (`2 passed`).
- Docs/status sync completed this round:
  1. Updated `docs/plans/ARCH-C-REQUEST-CONTEXT-PLAN-2026-03-02.md` with requester-propagation status.
  2. Updated `nexus3/rpc/README.md`, `nexus3/skill/README.md`, and `CLAUDE.md` to describe requester propagation across HTTP and initial-message dispatch.
- Immediate resume targets:
  1. Plan A: evaluate the remaining duplicate authorization surface in `nexus3/cli/repl_commands.py::_change_preset` and decide whether to kernelize, relocate, or explicitly defer it.
  2. Plan A: if `repl_commands._change_preset` is intentionally left outside Plan A scope, write explicit closeout criteria and mark `Remove duplicate authorization branches` complete/incomplete accordingly.
  3. Plan C: confirm no further requester-propagation gaps remain beyond documented deferred service-container immutability work.

Compact checkpoint (2026-03-05, post-commit handover):
- Current branch head: `6d89fe4` (`auth/context: harden kernel and requester propagation`).
- Commit contents:
  1. Plan A path authorization kernelization in `nexus3/session/enforcer.py` plus focused coverage.
  2. Plan A duplicate-branch cleanup in `nexus3/skill/builtin/nexus_create.py` plus focused coverage.
  3. Plan C requester propagation through agent-scoped HTTP dispatch, create follow-up initial-message dispatch, and NexusSkill HTTP fallback transport.
  4. Plan/doc updates in `AGENTS.md`, `CLAUDE.md`, `docs/plans/ARCH-A-AUTH-KERNEL-PLAN-2026-03-02.md`, `docs/plans/ARCH-C-REQUEST-CONTEXT-PLAN-2026-03-02.md`, `nexus3/rpc/README.md`, and `nexus3/skill/README.md`.
- Validation already completed before commit:
  - `.venv/bin/ruff check nexus3/client.py nexus3/skill/base.py nexus3/rpc/http.py nexus3/rpc/global_dispatcher.py nexus3/skill/builtin/nexus_create.py tests/unit/test_client.py tests/unit/test_http_pipeline_layers.py tests/unit/test_initial_message.py tests/unit/test_nexus_skill_requester_propagation.py tests/unit/skill/test_nexus_create.py`
  - `.venv/bin/mypy nexus3/client.py nexus3/skill/base.py nexus3/rpc/http.py nexus3/rpc/global_dispatcher.py nexus3/skill/builtin/nexus_create.py`
  - `.venv/bin/pytest -q tests/unit/test_client.py tests/unit/test_http_pipeline_layers.py tests/unit/test_initial_message.py tests/unit/test_nexus_skill_requester_propagation.py tests/unit/skill/test_nexus_create.py`
  - Result: `52 passed` (existing SSL CA warnings only).
- Resume-first target after compact:
  1. Re-open `docs/plans/ARCH-A-AUTH-KERNEL-PLAN-2026-03-02.md` and inspect `nexus3/cli/repl_commands.py::_change_preset` as the last obvious duplicate authorization surface.
  2. If `_change_preset` is outside Plan A’s intended kernel boundary, document that explicitly and close out the remaining Plan A checklist item.
  3. Otherwise, implement the smallest safe cleanup/kernelization slice, then update plan/docs/AGENTS in the same session.

Post-commit note (2026-03-05):
- Round 30 is committed as `b238485` (`close out plan a/c auth and request context gaps`).
- Branch remains `feat/arch-overhaul-execution`.
- Recommended next execution slice after compact: Plan H strict-ingress closeout audit/implementation, since Plan A and Plan C closeout items are now landed and synchronized.

Compact checkpoint (2026-03-05, architecture execution round 30):
- Branch head at start of round: `999b49d`; current working tree includes uncommitted Plan A and Plan C closeout slices plus synchronized docs.
- New slices completed this round:
  1. Plan C dispatcher closeout:
     - threaded immutable `RequestContext` through agent-scoped read handlers in `nexus3/rpc/dispatcher.py` (`get_tokens`, `get_context`, `get_messages`)
     - added focused propagation coverage in `tests/unit/test_rpc_dispatcher.py`
  2. Plan A REPL permission-mutation kernelization:
     - added a kernel-backed REPL permission-mutation adapter in `nexus3/cli/repl_commands.py` for preset changes and tool enable/disable gates
     - preserved existing ceiling-deny wording while fixing preset-switch state retention (`depth`, `session_allowances`, sandbox `cwd`)
     - added focused coverage in `tests/unit/test_repl_commands.py`
- Validation completed for this round:
  - `.venv/bin/ruff check nexus3/cli/repl_commands.py nexus3/rpc/dispatcher.py tests/unit/test_repl_commands.py tests/unit/test_rpc_dispatcher.py`
  - `.venv/bin/mypy nexus3/cli/repl_commands.py nexus3/rpc/dispatcher.py`
  - `.venv/bin/pytest -q tests/unit/test_repl_commands.py tests/unit/test_rpc_dispatcher.py`
  - Result: `91 passed`
- Docs/status sync completed this round:
  1. Updated `docs/plans/ARCH-A-AUTH-KERNEL-PLAN-2026-03-02.md` and `docs/plans/ARCH-C-REQUEST-CONTEXT-PLAN-2026-03-02.md`.
  2. Updated `nexus3/rpc/README.md`, `nexus3/cli/README.md`, and `CLAUDE.md` to reflect the new request-context and `/permissions` behavior.
- Immediate resume targets:
  1. Decide whether to commit this closeout round as its own checkpoint before starting the next architecture slice.
  2. Re-open the milestone schedule and pick the next highest-value post-M2 slice (likely Plan H strict-ingress closeout or Plan G cleanup).
  3. Keep AGENTS/plan checklists synchronized before compact or handoff.

Pre-compact checkpoint (2026-03-05, deferred follow-up planning backlog):
- Status:
  - Added and indexed follow-on plans for previously accepted deferrals:
    - `docs/plans/ARCH-A-AUTH-REQUEST-MODEL-V2-PLAN-2026-03-05.md`
    - `docs/plans/ARCH-H-RPC-ERROR-SHIM-RETIREMENT-PLAN-2026-03-05.md`
  - Added and indexed remaining tracker-backed deferred plans:
    - `docs/plans/ARCH-C-SERVICE-CONTAINER-IMMUTABILITY-PLAN-2026-03-05.md`
    - `docs/plans/PROVIDER-KEEPALIVE-INVESTIGATION-PLAN-2026-03-05.md`
    - `docs/plans/STRUCTURAL-REFACTOR-WAVE-PLAN-2026-03-05.md`
    - `docs/plans/POST-M4-VALIDATION-CAMPAIGN-PLAN-2026-03-05.md`
  - Added explicit backlog dependency/exit gates for follow-on items in:
    - `docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md`
- Remaining plan-authoring backlog:
  - None. All currently tracked deferred items now have dedicated plan docs.
- Additional resume notes:
  - This working tree now includes an uncommitted behavior fix in:
    - `nexus3/rpc/dispatcher.py` (restore context-gated exposure for `get_tokens/get_context/get_messages`)
    - `tests/unit/test_rpc_dispatcher.py` (method-not-found regression + request-context test wiring update)
  - Focused + broad touched-scope validation already run successfully after that fix:
    - `360 passed` on the multi-suite verification run.
  - Unrelated untracked files currently present (do not touch unless explicitly requested):
    - `docs/plans/DOUBLE-SPINNER-FIX-PLAN.md`, `editors/`, `err/`, `package-lock.json`.
- First actions after resume:
  - Status: completed in architecture execution round 31 (2026-03-05); kept here as historical handoff context.
  1. Decide whether to commit the currently staged/uncommitted dispatcher/test/doc updates as a checkpoint before starting the next architecture implementation slice.
  2. Main-plan next slice (start here after compact): M3 Plan F Phase 1 foundation.
     - Add `nexus3/patch/ast_v2.py` typed AST scaffold.
     - Add/extend roundtrip baseline fixtures for patch parse/apply fidelity.
     - Wire minimal parser/applier integration hooks without default-behavior flip.
     - Run focused gates:
       - `.venv/bin/pytest -q tests/unit/patch/test_parser.py tests/unit/patch/test_applier.py tests/unit/patch/test_byte_roundtrip_baseline.py`
       - `.venv/bin/ruff check nexus3/patch tests/unit/patch`
       - `.venv/bin/mypy nexus3/patch`
  3. Commit Plan F Phase 1 as a standalone logical checkpoint before Phase 2.
  4. Next target after Phase 1: M3 Plan F Phase 2 (`byte_strict` parse/apply path) with fidelity regressions.
  5. Keep follow-on deferred plans in backlog mode until their M4/post-M4 dependency gates are satisfied.

Compact-ready execution note (2026-03-05):
- Recommended immediate implementation order:
  1. M3 Plan F Phase 1 (`AST v2 + fixtures`).
  2. M3 Plan F Phase 2 (`byte_strict` apply path).
  3. M3 Plan F Phase 4 (`ambiguous target fail-closed`) and remaining Plan F migration slices.
  4. M3 Plan E Phase 1 compiler IR/invariants once Plan F foundation commits are stable.
- Do not start Plan A/H/C follow-on deferred plans yet; those are scheduled for
  M4/post-M4 windows in the milestone backlog.

Execution checkpoint (2026-03-05, architecture execution round 31):
- Scope completed this round (M3 Plan F Phase 1 foundation):
  1. Added `nexus3/patch/ast_v2.py` typed AST v2 models with raw-line bytes/newline metadata and v2->v1 projection/coercion helpers.
  2. Added additive parser hook `parse_unified_diff_v2(...)` in `nexus3/patch/parser.py` while preserving existing `parse_unified_diff(...)` behavior.
  3. Added applier bridge so `nexus3/patch/applier.py::apply_patch(...)` accepts `PatchFileV2` without changing existing strict/tolerant/fuzzy semantics.
  4. Expanded fixture-driven baseline coverage in `tests/fixtures/arch_baseline/` and `tests/unit/patch/test_byte_roundtrip_baseline.py` for explicit no-EOL marker and whitespace-sensitive payload cases.
  5. Added parser/applier AST-v2 parity coverage in `tests/unit/patch/test_parser.py` and `tests/unit/patch/test_applier.py`.
- Focused validation executed this round:
  - `.venv/bin/pytest -q tests/unit/patch/test_parser.py tests/unit/patch/test_applier.py tests/unit/patch/test_byte_roundtrip_baseline.py` -> `50 passed`.
  - `.venv/bin/ruff check nexus3/patch tests/unit/patch` -> passed (includes a small cleanup in `tests/unit/patch/test_validator.py` removing an unused import).
  - `.venv/bin/mypy nexus3/patch` -> passed.
  - `.venv/bin/pytest -q tests/unit/patch/test_validator.py` -> `14 passed`.
- Next gate:
  1. Commit current Plan F Phase 1 code+fixture+doc checkpoint as a standalone logical unit.
  2. Start M3 Plan F Phase 2 (`byte_strict` parse/apply path) with newline/EOF-fidelity regressions.
  3. Keep follow-on deferred plans in backlog mode until their M4/post-M4 dependency gates are met.

Execution checkpoint (2026-03-05, architecture execution round 32):
- Scope completed this round (M3 Plan F Phase 2 byte-strict path):
  1. Added explicit byte-strict entrypoint `nexus3/patch/applier.py::apply_patch_byte_strict(...)` for AST-v2 patches with newline-token/EOF-marker aware replacement semantics.
  2. Preserved legacy default behavior: `apply_patch(...)` strict/tolerant/fuzzy flow remains unchanged for existing callers.
  3. Added Phase 2 regressions in `tests/unit/patch/test_byte_strict_apply_phase2.py` and mixed-newline fixture `tests/fixtures/arch_baseline/patch_mixed_newline_update.diff`.
  4. Updated patch API docs/exports in `nexus3/patch/__init__.py` and `nexus3/patch/README.md`.
- Focused validation executed this round:
  - `.venv/bin/pytest -q tests/unit/patch/test_byte_strict_apply_phase2.py tests/unit/patch/test_applier.py tests/unit/patch/test_parser.py tests/unit/patch/test_byte_roundtrip_baseline.py tests/unit/patch/test_validator.py` -> `66 passed`.
  - `.venv/bin/ruff check nexus3/patch tests/unit/patch` -> passed.
  - `.venv/bin/mypy nexus3/patch` -> passed.
- Next gate:
  1. Commit Plan F Phase 2 code+tests+docs as standalone checkpoint.
  2. Start M3 Plan F Phase 3 (add explicit mode flag wiring and migration tests between legacy/byte_strict paths).
  3. Keep follow-on deferred plans in backlog mode until their M4/post-M4 dependency gates are met.

Execution checkpoint (2026-03-05, architecture execution round 33):
- Scope completed this round (M3 Plan F Phase 3 mode-flag wiring):
  1. Added patch-skill migration flag in `nexus3/skill/builtin/patch.py`: `fidelity_mode` with `legacy` (default) and `byte_strict`.
  2. Wired explicit fidelity paths:
     - `legacy`: `parse_unified_diff(...)` + `apply_patch(...)`
     - `byte_strict`: `parse_unified_diff_v2(...)` + `apply_patch_byte_strict(...)`
  3. Added migration regressions in `tests/unit/skill/test_patch.py`:
     - byte-strict no-final-newline marker preservation
     - invalid `fidelity_mode` fail-fast validation
     - default legacy-path compatibility assertion
  4. Synced skill API reference in `nexus3/skill/README.md` for new patch parameter and patch-module symbols.
- Focused validation executed this round:
  - `.venv/bin/pytest -q tests/unit/skill/test_patch.py tests/unit/patch/test_byte_strict_apply_phase2.py tests/unit/patch/test_applier.py tests/unit/patch/test_parser.py tests/unit/patch/test_byte_roundtrip_baseline.py tests/unit/patch/test_validator.py` -> `91 passed`.
  - `.venv/bin/pytest -q tests/integration/test_file_editing_skills.py -k patch` -> `9 passed, 8 deselected`.
  - `.venv/bin/ruff check nexus3/skill/builtin/patch.py tests/unit/skill/test_patch.py nexus3/patch tests/unit/patch` -> passed.
  - `.venv/bin/mypy nexus3/skill/builtin/patch.py nexus3/patch` -> passed.
- Next gate:
  1. Commit Plan F Phase 3 code+tests+docs as standalone checkpoint.
  2. Start M3 Plan F Phase 4 target-resolution hardening (`_find_matching_patch` exact-path preference + ambiguity fail-closed behavior/tests).
  3. Keep follow-on deferred plans in backlog mode until their M4/post-M4 dependency gates are met.

Execution checkpoint (2026-03-05, architecture execution round 34):
- Scope completed this round (M3 Plan F Phase 4 target-resolution hardening):
  1. Hardened `nexus3/skill/builtin/patch.py::_find_matching_patch` to prefer exact-path matches (relative-to-cwd first, then absolute-path candidate).
  2. Added fail-closed ambiguity behavior for basename fallback: multiple basename matches now return explicit ambiguity errors instead of selecting first match.
  3. Added/updated multi-file selection regressions in `tests/unit/skill/test_patch.py`:
     - exact-path preference with same-basename candidates
     - ambiguity fail-closed behavior
     - retained unambiguous baseline case.
- Focused validation executed this round:
  - `.venv/bin/pytest -q tests/unit/skill/test_patch.py -k multi_file_diff` -> `4 passed, 23 deselected`.
  - `.venv/bin/pytest -q tests/unit/skill/test_patch.py tests/unit/patch/test_byte_strict_apply_phase2.py tests/unit/patch/test_applier.py tests/unit/patch/test_parser.py tests/unit/patch/test_byte_roundtrip_baseline.py tests/unit/patch/test_validator.py` -> `93 passed`.
  - `.venv/bin/pytest -q tests/integration/test_file_editing_skills.py -k patch` -> `9 passed, 8 deselected`.
  - `.venv/bin/ruff check nexus3/skill/builtin/patch.py tests/unit/skill/test_patch.py` -> passed.
  - `.venv/bin/mypy nexus3/skill/builtin/patch.py` -> passed.
- Next gate:
  1. Commit Plan F Phase 4 code+tests+docs as standalone checkpoint.
  2. Execute remaining Plan F closeout slices (Phase 5/6) before starting Plan E:
     - expand byte-fidelity regressions (non-UTF8/binary-adjacent + remaining ambiguity matrices)
     - evaluate/plan default-flip readiness criteria for byte_strict.
  3. Keep follow-on deferred plans in backlog mode until their M4/post-M4 dependency gates are met.

Execution checkpoint (2026-03-05, architecture execution round 35):
- Scope completed this round (M3 Plan F Phase 5 byte-fidelity regression expansion):
  1. Hardened byte-strict entrypoint `nexus3/patch/applier.py::apply_patch_byte_strict(...)` to accept `str | bytes` input with reversible `utf-8` + `surrogateescape` decoding for non-UTF8 roundtrip safety.
  2. Expanded byte-strict regressions in `tests/unit/patch/test_byte_strict_apply_phase2.py`:
     - invalid UTF-8 adjacent-byte preservation
     - binary-adjacent payload (NUL/control bytes) preservation while nearby text changes
  3. Synced byte-input contract note in `nexus3/patch/README.md`.
- Focused validation executed this round:
  - `.venv/bin/pytest -q tests/unit/patch/test_byte_strict_apply_phase2.py tests/unit/patch/test_applier.py tests/unit/patch/test_parser.py tests/unit/patch/test_byte_roundtrip_baseline.py tests/unit/patch/test_validator.py` -> `68 passed`.
  - `.venv/bin/pytest -q tests/unit/skill/test_patch.py` -> `27 passed`.
  - `.venv/bin/pytest -q tests/integration/test_file_editing_skills.py -k patch` -> `9 passed, 8 deselected`.
  - `.venv/bin/ruff check nexus3/patch/applier.py tests/unit/patch/test_byte_strict_apply_phase2.py` -> passed.
  - `.venv/bin/mypy nexus3/patch/applier.py` -> passed.
- Next gate:
  1. Commit Plan F Phase 5 code+tests+docs as standalone checkpoint.
  2. Execute Plan F Phase 6 closeout: default-flip readiness decision and legacy-branch retirement plan.
  3. Keep follow-on deferred plans in backlog mode until their M4/post-M4 dependency gates are met.

Execution checkpoint (2026-03-05, architecture execution round 36):
- Scope completed this round (M3 Plan F Phase 6 default flip):
  1. Flipped patch-skill `fidelity_mode` default to `byte_strict` in `nexus3/skill/builtin/patch.py`.
  2. Retained explicit `fidelity_mode=\"legacy\"` compatibility path for controlled fallback during soak.
  3. Updated migration assertions in `tests/unit/skill/test_patch.py` to verify:
     - default follows byte-strict newline semantics
     - explicit legacy remains available and behaviorally distinct where expected.
  4. Updated plan/schedule/docs notes (`docs/plans/ARCH-F-...`, `docs/plans/ARCH-MILESTONE-SCHEDULE-...`, `nexus3/skill/README.md`) for default-mode transition state.
- Focused validation executed this round:
  - `.venv/bin/pytest -q tests/unit/skill/test_patch.py` -> `28 passed`.
  - `.venv/bin/pytest -q tests/unit/patch/test_byte_strict_apply_phase2.py tests/unit/patch/test_applier.py tests/unit/patch/test_parser.py tests/unit/patch/test_byte_roundtrip_baseline.py tests/unit/patch/test_validator.py` -> `68 passed`.
  - `.venv/bin/pytest -q tests/integration/test_file_editing_skills.py -k patch` -> `9 passed, 8 deselected`.
  - `.venv/bin/ruff check nexus3/skill/builtin/patch.py tests/unit/skill/test_patch.py` -> passed.
  - `.venv/bin/mypy nexus3/skill/builtin/patch.py` -> passed.
- Next gate:
  1. Decide whether to retire remaining legacy-only branches now or explicitly defer retirement with rationale and target window.
  2. Begin M3 Plan E Phase 1 compiler/invariant implementation after Plan F closeout note is finalized.
  3. Keep follow-on deferred plans in backlog mode until their M4/post-M4 dependency gates are met.

Pre-compact checkpoint (2026-03-05, post-round36 commit):
- Branch/head:
  - `feat/arch-overhaul-execution`
  - `195ab86` (`plan f phase 6: default patch skill to byte_strict`)
- Architecture execution commits in this run:
  1. `1079cd7` Plan F Phase 1 (AST v2 foundation + baseline fixtures).
  2. `4ded3fa` Plan F Phase 2 (byte-strict AST-v2 apply path).
  3. `4c10b0b` Plan F Phase 3 (legacy/byte_strict mode flag wiring in patch skill).
  4. `a342401` Plan F Phase 4 (exact-path preference + ambiguity fail-closed target matching).
  5. `87c5df1` Plan F Phase 5 (non-UTF8/binary-adjacent byte-fidelity regressions).
  6. `195ab86` Plan F Phase 6 (default patch skill fidelity mode flipped to byte_strict).
- Current open architecture decision before Plan E:
  1. Keep legacy fallback branch as-is for soak window (explicitly deferred with rationale/window), or
  2. Retire remaining legacy-only patch-skill branch logic now and finalize Plan F checklist closeout.
- Resume-first commands after compact:
  1. `git status --short --branch`
  2. `sed -n '217,260p' AGENTS.md`
  3. `sed -n '1,240p' docs/plans/ARCH-F-PATCH-AST-BYTE-FIDELITY-PLAN-2026-03-02.md`
  4. `sed -n '1,260p' docs/plans/ARCH-E-CONTEXT-COMPILER-GRAPH-PLAN-2026-03-02.md`
- Next implementation targets after compact:
  1. Resolve Plan F legacy-branch retirement/defer decision and sync checklist/docs.
  2. Start M3 Plan E Phase 1 (`nexus3/context/compiler.py` IR + invariant checker scaffold + focused tests).

Execution checkpoint (2026-03-05, architecture execution round 37):
- Scope completed this round:
  1. Plan F Phase 7 closeout:
     - retired runtime legacy patch-skill apply branch in `nexus3/skill/builtin/patch.py`
     - patch execution now always uses AST-v2 parsing + `apply_patch_byte_strict(...)`
     - kept explicit fail-fast guidance for `fidelity_mode="legacy"` requests
     - updated migration docs/tests in `tests/unit/skill/test_patch.py`, `nexus3/skill/README.md`, and Plan F/schedule notes.
  2. Plan E Phase 1 foundation:
     - added `nexus3/context/compiler.py` with typed compiler IR + invariant report models
     - added deterministic repair/invariant entrypoints:
       `compile_context_messages(...)`, `compile_message_sequence(...)`,
       `check_context_invariants(...)`, `validate_compiled_message_invariants(...)`
     - exported compiler interfaces via `nexus3/context/__init__.py`
     - added focused regressions in `tests/unit/context/test_compiler.py`.
- Focused validation executed this round:
  - `.venv/bin/ruff check nexus3/skill/builtin/patch.py tests/unit/skill/test_patch.py nexus3/context/compiler.py nexus3/context/__init__.py tests/unit/context/test_compiler.py` -> passed.
  - `.venv/bin/mypy nexus3/skill/builtin/patch.py nexus3/context/compiler.py nexus3/context/__init__.py` -> passed.
  - `.venv/bin/pytest -q tests/unit/context/test_compiler.py tests/unit/context/test_compile_baseline.py` -> `8 passed`.
  - `.venv/bin/pytest -q tests/unit/skill/test_patch.py tests/integration/test_file_editing_skills.py -k patch` -> `37 passed, 8 deselected`.
  - `.venv/bin/pytest -q tests/unit/patch/test_byte_strict_apply_phase2.py tests/unit/patch/test_applier.py tests/unit/patch/test_parser.py tests/unit/patch/test_byte_roundtrip_baseline.py tests/unit/patch/test_validator.py` -> `68 passed`.
- Next gate:
  1. Start M3 Plan E Phase 2 integration:
     - route session preflight repair pipeline through compiler output
     - add provider parity coverage for compiler-based message shaping.
  2. Keep follow-on deferred plans in backlog mode until their M4/post-M4 dependency gates are met.

Pre-compact checkpoint (2026-03-05, post-round37 commits):
- Branch/head:
  - `feat/arch-overhaul-execution`
  - `e9d6c3e` (`plan e phase 1: add context compiler ir foundation`)
- Architecture execution commits this round:
  1. `6e946cf` Plan F Phase 7 (retire patch legacy runtime path).
  2. `e9d6c3e` Plan E Phase 1 (context compiler IR + invariants foundation).
- Current local working state:
  1. Only non-architecture local artifacts remain dirty/untracked (`CLAUDE.md`, `editors/`, `err/`, `package-lock.json`).
- Resume-first commands after compact:
  1. `git status --short --branch`
  2. `git log --oneline -n 8`
  3. `sed -n '217,260p' AGENTS.md`
  4. `sed -n '1,260p' docs/plans/ARCH-E-CONTEXT-COMPILER-GRAPH-PLAN-2026-03-02.md`
- Next implementation targets after compact:
  1. Plan E Phase 2: integrate compiler output into session preflight repair path.
  2. Add provider/session parity tests proving compiler-shaped messages preserve current behavior.
  3. Keep follow-on deferred plans backlog-gated until M4/post-M4 windows.

Execution checkpoint (2026-03-05, architecture execution round 38):
- Scope completed this round (M3 Plan E Phase 2 provider/session integration):
  1. Migrated session preflight repair pipeline to compiler-backed normalization:
     - `nexus3/session/session.py` now normalizes context via
       `compile_context_messages(...)` before appending new user turns in
       both `send()` and `run_turn()`.
     - `nexus3/context/manager.py` now exposes `replace_messages(...)` to
       persist repaired history without replay-logging old turns.
  2. Routed providers through compiler output:
     - `nexus3/provider/openai_compat.py::_build_request_body(...)` now
       compiles message sequences before OpenAI-format conversion.
     - `nexus3/provider/anthropic.py::_build_request_body(...)` now compiles
       message sequences before Anthropic conversion.
  3. Retired provider-local orphan synthesis in Anthropic conversion:
     - removed orphan `tool_result` synthesis from
       `nexus3/provider/anthropic.py::_convert_messages(...)`.
     - synthesis now occurs in shared compiler repair path before conversion.
  4. Added focused regressions:
     - `tests/unit/session/test_session_cancellation.py`
       (`TestCompilerBackedPreflightNormalization` + updated provider
       integration expectations).
     - `tests/unit/provider/test_compiler_integration.py` (new).
- Focused validation executed this round:
  - `.venv/bin/ruff check nexus3/session/session.py nexus3/context/manager.py nexus3/provider/anthropic.py nexus3/provider/openai_compat.py tests/unit/session/test_session_cancellation.py tests/unit/provider/test_compiler_integration.py` -> passed.
  - `.venv/bin/mypy nexus3/session/session.py nexus3/context/manager.py nexus3/provider/anthropic.py nexus3/provider/openai_compat.py` -> passed.
  - `.venv/bin/pytest -q tests/unit/session/test_session_cancellation.py tests/unit/provider/test_compiler_integration.py tests/unit/provider/test_prompt_caching.py` -> `36 passed`.
- Next gate:
  1. Keep Plan E Phases 3-4 queued for M4 window unless milestone scope shifts.
  2. Continue deferred follow-on plans only when their dependency gates are met.

Pre-compact checkpoint (2026-03-05, post-round38 commit):
- Branch/head:
  - `feat/arch-overhaul-execution`
  - `e3cd304` (`plan e phase 2: integrate compiler into session and providers`)
- Architecture execution commits this round:
  1. `e3cd304` Plan E Phase 2 (session preflight compiler integration +
     provider compiler shaping + Anthropic synthesis retirement).
- Current local working state:
  1. Non-architecture local artifacts remain dirty/untracked:
     `CLAUDE.md`, `editors/`, `err/`, `package-lock.json`.
- Resume-first commands after compact:
  1. `git status --short --branch`
  2. `git log --oneline -n 8`
  3. `sed -n '217,280p' AGENTS.md`
  4. `sed -n '1,220p' docs/plans/ARCH-E-CONTEXT-COMPILER-GRAPH-PLAN-2026-03-02.md`
- Next implementation targets after compact:
  1. Plan E Phase 3 planning/execution scoping for M4 graph model
     introduction window.
  2. Keep deferred follow-on plans backlog-gated until M4/post-M4 windows.

Execution checkpoint (2026-03-05, architecture execution round 39):
- Scope completed this round (Plan E Phase 3 graph prototype):
  1. Added compiler-backed context graph module:
     - `nexus3/context/graph.py` with typed graph entities
       (`ContextGraph`, `ContextGraphEdge`, `GraphEdgeKind`,
       `ContextMessageGroup`) and traversal helpers.
  2. Graph builder now compiles/normalizes message sequences first and then
     projects:
     - linear adjacency edges (`NEXT`)
     - assistant-to-tool result edges (`TOOL_RESULT`)
     - atomic tool-batch groupings for future compaction/truncation migration.
  3. Exported graph APIs in `nexus3/context/__init__.py`.
  4. Updated context module docs in `nexus3/context/README.md`.
  5. Added focused regressions in `tests/unit/context/test_graph.py`.
- Focused validation executed this round:
  - `.venv/bin/ruff check nexus3/context/graph.py nexus3/context/__init__.py nexus3/context/README.md tests/unit/context/test_graph.py` -> passed.
  - `.venv/bin/mypy nexus3/context/graph.py nexus3/context/__init__.py` -> passed.
  - `.venv/bin/pytest -q tests/unit/context/test_graph.py tests/unit/context/test_compiler.py tests/unit/context/test_compile_baseline.py` -> `12 passed`.
  - `.venv/bin/pytest -q tests/unit/test_context_manager.py` -> `27 passed`.
- Next gate:
  1. Plan E Phase 4: migrate compaction/truncation path to consume compiler/graph pipeline.
  2. Keep deferred follow-on plans backlog-gated until their M4/post-M4 dependency windows are reached.

Pre-compact checkpoint (2026-03-05, post-round39 commit):
- Branch/head:
  - `feat/arch-overhaul-execution`
  - `5632652` (`plan e phase 3: add context graph prototype`)
- Architecture execution commits this round:
  1. `5632652` Plan E Phase 3 (compiler-backed context graph prototype).
- Current local working state:
  1. Non-architecture local artifacts remain dirty/untracked:
     `CLAUDE.md`, `editors/`, `err/`, `package-lock.json`.
- Resume-first commands after compact:
  1. `git status --short --branch`
  2. `git log --oneline -n 10`
  3. `sed -n '220,300p' AGENTS.md`
  4. `sed -n '1,240p' docs/plans/ARCH-E-CONTEXT-COMPILER-GRAPH-PLAN-2026-03-02.md`
- Next implementation targets after compact:
  1. Plan E Phase 4 compiler/graph-backed compaction-truncation integration.
  2. M3 closeout/M4 status bookkeeping after Phase 4 slice lands.

Execution checkpoint (2026-03-05, architecture execution round 40):
- Scope completed this round (Plan E Phase 4 compaction/truncation migration):
  1. `nexus3/context/manager.py::_identify_message_groups(...)` now sources
     atomic groups from `build_context_graph(...)` and persists normalized
     context before truncation grouping.
  2. `nexus3/context/compaction.py::select_messages_for_compaction(...)` now
     runs over compiler-normalized graph groups rather than raw message slices.
  3. Added focused compaction/truncation regressions:
     - `tests/unit/test_compaction.py` (atomic tool-batch preservation +
       compiler-repair-aware selection)
     - `tests/unit/test_context_manager.py`
       (truncation normalization of orphan tool messages)
- Focused validation executed this round:
  - `.venv/bin/ruff check nexus3/context/manager.py nexus3/context/compaction.py tests/unit/test_context_manager.py tests/unit/test_compaction.py` -> passed.
  - `.venv/bin/mypy nexus3/context/manager.py nexus3/context/compaction.py nexus3/context/graph.py nexus3/context/__init__.py` -> passed.
  - `.venv/bin/pytest -q tests/unit/test_context_manager.py tests/unit/test_compaction.py tests/unit/context/test_graph.py tests/unit/context/test_compiler.py tests/unit/context/test_compile_baseline.py` -> `75 passed`.
- Next gate:
  1. M3/M4 transition bookkeeping closeout across AGENTS + milestone schedule.
  2. Sequence next M4 implementation slice (Plan B and/or remaining Plan G wave) based on dependency gates.

Pre-compact checkpoint (2026-03-05, post-round40 commit):
- Branch/head:
  - `feat/arch-overhaul-execution`
  - `00c59ed` (`plan e phase 4: migrate compaction and truncation to graph pipeline`)
- Architecture execution commits this round:
  1. `00c59ed` Plan E Phase 4 (compiler/graph-backed compaction-truncation migration).
- Current local working state:
  1. Non-architecture local artifacts remain dirty/untracked:
     `CLAUDE.md`, `editors/`, `err/`, `package-lock.json`.
- Resume-first commands after compact:
  1. `git status --short --branch`
  2. `git log --oneline -n 12`
  3. `sed -n '220,320p' AGENTS.md`
  4. `sed -n '1,260p' docs/plans/ARCH-E-CONTEXT-COMPILER-GRAPH-PLAN-2026-03-02.md`
- Next implementation targets after compact:
  1. Confirm M3/M4 transition closeout note and milestone ordering.
  2. Start next M4 implementation slice (Plan B or remaining Plan G wave).

Execution checkpoint (2026-03-05, architecture execution round 41):
- Scope completed this round (Plan B Phase 1 capability primitives):
  1. Added `nexus3/core/capabilities.py`:
     - typed claim model (`CapabilityClaims`)
     - signed token issue/verify service (`CapabilitySigner`)
     - revocation/replay protocols + in-memory stores
     - capability secret generation helper.
  2. Exported capability APIs in `nexus3/core/__init__.py`.
  3. Added focused tests in `tests/unit/core/test_capabilities.py`.
  4. Updated `nexus3/core/README.md` to document capability primitives.
- Focused validation executed this round:
  - `.venv/bin/ruff check nexus3/core/capabilities.py nexus3/core/__init__.py nexus3/core/README.md tests/unit/core/test_capabilities.py` -> passed.
  - `.venv/bin/mypy nexus3/core/capabilities.py nexus3/core/__init__.py` -> passed.
  - `.venv/bin/pytest -q tests/unit/core/test_capabilities.py` -> `11 passed`.
- Next gate:
  1. Plan B Phase 2: wire capability verification into direct API dispatch path.
  2. Pause here for requested compaction checkpoint before starting Phase 2.

Pre-compact checkpoint (2026-03-05, post-round41 commit):
- Branch/head:
  - `feat/arch-overhaul-execution`
  - `14bc820` (`plan b phase 1: add capability token primitives`)
- Architecture execution commits this round:
  1. `14bc820` Plan B Phase 1 (capability schema + signer/verifier primitives).
- Current local working state:
  1. Non-architecture local artifacts remain dirty/untracked:
     `CLAUDE.md`, `editors/`, `err/`, `package-lock.json`.
- Resume-first commands after compact:
  1. `git status --short --branch`
  2. `git log --oneline -n 12`
  3. `sed -n '220,340p' AGENTS.md`
  4. `sed -n '1,260p' docs/plans/ARCH-B-CAPABILITY-TOKENS-PLAN-2026-03-02.md`
- Next implementation targets after compact:
  1. Plan B Phase 2 direct API path integration for capabilities.
  2. Keep deferred follow-on plans backlog-gated by documented dependency windows.

## Source of Truth

`CLAUDE.md` contains full project reference detail. This file is the Codex-oriented operating guide distilled from it.

Emergency handover checkpoint (2026-03-07, power-loss shutdown):
- Branch/head:
  - `feat/arch-overhaul-execution` (ahead 7).
- Current local working state (uncommitted):
  - modified: `nexus3/rpc/global_dispatcher.py`
  - modified: `tests/unit/rpc/test_schema_ingress_wiring.py`
  - no commit created yet in this slice.
- Scope completed before shutdown:
  1. Plan H shim-retirement Phase 2 in progress:
     - removed `create_agent` compatibility-only Pydantic message remap
       prefix stripping in `GlobalDispatcher._handle_create_agent(...)` for
       malformed `agent_id` and `parent_agent_id` string inputs.
     - handler now surfaces canonical schema-derived diagnostics directly
       (`Value error, <field> invalid: ...`) while keeping deterministic type
       checks (`... must be string, got: ...`) unchanged.
  2. Updated ingress regressions:
     - changed malformed `parent_agent_id` expectation to canonical schema
       message with field prefix.
     - added explicit malformed string `agent_id` regression asserting canonical
       schema detail.
- Validation executed in this slice:
  - passed: `.venv\\Scripts\\ruff.exe check nexus3/rpc/global_dispatcher.py tests/unit/rpc/test_schema_ingress_wiring.py`
  - passed: `.venv\\Scripts\\pytest.exe -q -p no:cacheprovider tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/test_rpc_dispatcher.py tests/unit/test_global_dispatcher.py tests/unit/test_client.py` (`134 passed`, 12 client CA-path warnings)
  - host baseline issue: `.venv\\Scripts\\mypy.exe nexus3/rpc/global_dispatcher.py` reports unrelated pre-existing repo errors on this host.
  - passed (file-scoped confirmation): `.venv\\Scripts\\mypy.exe --follow-imports=skip nexus3/rpc/global_dispatcher.py`
- Next immediate resume steps:
  1. Update docs/status files for this Phase 2 slice:
     - `docs/plans/ARCH-H-RPC-ERROR-SHIM-RETIREMENT-PLAN-2026-03-05.md`
     - `docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md`
     - `AGENTS.md` running-status sections near the active architecture block.
  2. Optionally refresh `nexus3/rpc/README.md` ingress-diagnostics note for
     `create_agent` malformed ID wording (now schema-derived prefix included).
  3. Re-run focused checks above if any docs/code are touched.
  4. Commit as: `plan h shim retirement phase 2: drop create id message remaps`.
- Environment caveats:
  - `git` requires safe-directory override in this session (`-c safe.directory=...`).
  - recurring warnings for inaccessible temp dirs remain expected:
    `.tmp-pytest-debug-root/pytest-of-inc/`, `.tmp-pytest-phase2-run5/`.

Orchestrator handover checkpoint (2026-03-09, post-wave commit target):
- Branch/head:
  - `feat/arch-overhaul-execution`
  - base head before this local wave: `b09c079`
- Execution mode used in this wave:
  - orchestrator-first flow from the main Codex agent.
  - parallel subagent execution with disjoint file ownership per slice.
  - max parallelism exercised safely (up to 5 concurrent subagents this round).
  - integration model: subagent patch -> main-agent diff review -> unified focused validation.
- Scope completed in this wave (local):
  1. Plan H shim-retirement follow-on (canonical diagnostics migration):
     - `nexus3/rpc/protocol.py`:
       - removed sentence-case mutual-exclusion remaps in `parse_response(...)`;
         now surfaces canonical schema message text.
     - `nexus3/rpc/dispatcher.py`:
       - removed compatibility cancel-param text remaps in `_handle_cancel(...)`;
         now surfaces canonical schema diagnostics.
     - `nexus3/rpc/global_dispatcher.py`:
       - removed compatibility remaps for `create_agent` fields:
         `preset`, `wait_for_initial_response`, non-string
         `parent_agent_id`, and malformed `allowed_write_paths` shape/items.
       - removed pre-schema destroy-agent text remap guards in
         `_handle_destroy_agent(...)`; malformed input now uses schema diagnostics.
     - focused test updates:
       `tests/unit/rpc/test_schema_ingress_wiring.py`,
       `tests/unit/test_client.py`,
       `tests/unit/test_global_dispatcher.py`.
  2. Plan C service-container immutability follow-on, slice 1 foundation:
     - `nexus3/skill/services.py`:
       - added additive typed mutators:
         `set_permissions(...)`, `set_cwd(...)`, `set_model(...)`,
         `set_child_agent_ids(...)`.
       - added typed accessor `get_model(...)`.
       - added immutable runtime snapshot model
         `ServiceContainerRuntimeSnapshot` + `snapshot_runtime()`.
       - preserved legacy compatibility path (`register`/`unregister`/`clear`)
         in this slice.
     - added focused coverage:
       `tests/unit/skill/test_service_container_immutability.py`.
  3. Status/docs synchronization:
     - Plan H docs: `docs/plans/ARCH-H-RPC-ERROR-SHIM-RETIREMENT-PLAN-2026-03-05.md`,
       `docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md`,
       `nexus3/rpc/README.md`.
     - Plan C docs/status:
       `docs/plans/ARCH-C-SERVICE-CONTAINER-IMMUTABILITY-PLAN-2026-03-05.md`,
       `docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md`,
       this `AGENTS.md` running-status block.
- Validation executed this wave:
  - `.venv/bin/ruff check nexus3/rpc/dispatcher.py nexus3/rpc/global_dispatcher.py nexus3/rpc/protocol.py nexus3/skill/services.py tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/test_client.py tests/unit/test_global_dispatcher.py tests/unit/skill/test_service_container_immutability.py` -> passed.
  - `.venv/bin/mypy nexus3/rpc/dispatcher.py nexus3/rpc/global_dispatcher.py nexus3/rpc/protocol.py nexus3/skill/services.py` -> passed.
  - `.venv/bin/pytest -q tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/test_rpc_dispatcher.py tests/unit/test_global_dispatcher.py tests/unit/test_client.py` -> `138 passed`, `12 warnings`.
  - `.venv/bin/pytest -q tests/unit/skill/test_service_container_immutability.py tests/unit/test_skill_registry.py -k ServiceContainer` -> `19 passed`, `24 deselected`.
- Next execution slices after this checkpoint:
  1. Commit this wave as a single logical checkpoint (Plan H canonical diagnostics + Plan C slice-1 foundation + status sync).
  2. Continue Plan C slice 2/3 in parallel with disjoint ownership:
     - slice 2: pool create/restore migration (`nexus3/rpc/pool.py`, `tests/unit/test_pool.py`)
     - slice 3: REPL/session runtime mutation migration
       (`nexus3/cli/repl_commands.py`, `nexus3/session/session.py`,
       `nexus3/session/enforcer.py`, focused REPL/session tests).
  3. Keep Plan H checklist conservative until remaining compatibility-only
     remaps are either retired or explicitly documented as retained invariants.

Orchestrator handover checkpoint (2026-03-09, Plan C final-wave checkpoint-ready follow-on):
- Branch/head:
  - `feat/arch-overhaul-execution`
  - base head before current local follow-on: `b09c079`
- Scope completed in working tree (checkpoint-ready, pending commit):
  1. Pool create/restore migration to typed service runtime mutators/accessors:
     - `nexus3/rpc/pool.py` now uses typed runtime service APIs for create,
       restore, list, and parent-child tracking paths
       (`set_permissions`, `set_cwd`, `set_model`, `get_permissions`,
       `get_child_agent_ids`, `set_child_agent_ids`, `get_model`).
     - focused pool regression updates in `tests/unit/test_pool.py`.
  2. REPL/session runtime mutation/read migration to typed APIs:
     - migrated REPL runtime mutation/read call sites to typed service APIs in
       `nexus3/cli/repl_commands.py`.
     - migrated session runtime model-read flow to typed service APIs in
       `nexus3/session/session.py`.
     - focused REPL regression updates in `tests/unit/test_repl_commands.py`.
  3. Service mutator compatibility hardening for `allowed_paths`:
     - `nexus3/skill/services.py` now synchronizes and clears legacy
       `allowed_paths` compatibility state via `set_permissions(...)`.
     - `ServiceContainer.register(...)` now scopes runtime-key compatibility
       state through `register_runtime_compat(...)`.
     - expanded compatibility regressions in
       `tests/unit/skill/test_service_container_immutability.py`.
- Focused validation snapshot for this follow-on:
  - passed:
    `.venv/bin/ruff check nexus3/rpc/pool.py nexus3/cli/repl_commands.py nexus3/session/session.py nexus3/skill/services.py tests/unit/test_pool.py tests/unit/test_repl_commands.py tests/unit/skill/test_service_container_immutability.py`
  - passed:
    `.venv/bin/mypy nexus3/rpc/pool.py nexus3/cli/repl_commands.py nexus3/session/session.py nexus3/skill/services.py`
  - passed:
    `.venv/bin/pytest -q tests/unit/test_repl_commands.py tests/unit/test_pool.py tests/unit/skill/test_service_container_immutability.py tests/unit/session/test_session_cancellation.py tests/unit/session/test_session_permission_kernelization.py`
    (`168 passed`).
- Concrete resume steps for post-compact continuation:
  1. Commit the checkpoint-ready Plan C service-immutability follow-on
     (slices 1-3) on `feat/arch-overhaul-execution`.
  2. Historical next step at that checkpoint (completed 2026-03-09):
     provider keep-alive investigation kickoff from
     `docs/plans/PROVIDER-KEEPALIVE-INVESTIGATION-PLAN-2026-03-05.md`,
     with the first checkpoint recorded in AGENTS/CLAUDE running status.
  3. Re-run the focused validation trio above after any provider keep-alive
     implementation edits and archive command outputs in session notes.

Compact handover checkpoint (2026-03-09, post-Plan C test-hygiene wave 3):
- Branch/head:
  - `feat/arch-overhaul-execution`
  - latest committed head before compact: `98629da`
- Execution model used in this continuation:
  - main agent operated as orchestrator.
  - work split into disjoint, file-owned parallel subagent waves (up to 6 at once).
  - integration policy: subagent patch -> main-agent validation -> commit.
- Commits landed this continuation:
  - `0522c12` `plan c: modernize legacy servicecontainer test doubles`
  - `e2f1bd1` `plan c: normalize test runtime-key service setup`
  - `98629da` `plan c: continue test runtime-key setup normalization`
- Current wave scope completed in working tree (checkpoint-ready):
  - runtime-key test setup migration in:
    - `tests/security/test_p2_append_file.py`
    - `tests/security/test_p2_file_size_limits.py`
    - `tests/security/test_p2_blocked_paths.py`
    - `tests/security/test_p2_exec_cwd_normalization.py`
    - `tests/integration/test_file_editing_skills.py`
    - `tests/unit/session/test_session_permission_kernelization.py`
  - migration pattern:
    - `register("cwd", ...)` -> `set_cwd(...)`
    - `register("allowed_paths", ...)` ->
      `register_runtime_compat("allowed_paths", ...)` where present
  - incidental lint-debt cleanup in touched files:
    - removed unused imports in
      `tests/security/test_p2_exec_cwd_normalization.py` and
      `tests/security/test_p2_file_size_limits.py`
    - renamed one ambiguous comprehension variable in
      `tests/security/test_p2_file_size_limits.py`
    - wrapped one long assertion line in
      `tests/security/test_p2_file_size_limits.py`
- Validation snapshot for this wave:
  - passed:
    `.venv/bin/ruff check tests/security/test_p2_append_file.py tests/security/test_p2_file_size_limits.py tests/security/test_p2_blocked_paths.py tests/security/test_p2_exec_cwd_normalization.py tests/integration/test_file_editing_skills.py tests/unit/session/test_session_permission_kernelization.py`
  - passed:
    `.venv/bin/pytest -q tests/security/test_p2_append_file.py tests/security/test_p2_file_size_limits.py tests/security/test_p2_blocked_paths.py tests/security/test_p2_exec_cwd_normalization.py tests/unit/session/test_session_permission_kernelization.py`
    (`50 passed`)
  - sandbox caveat encountered on integration test:
    - `timeout 180 .venv/bin/pytest -q tests/integration/test_file_editing_skills.py`
      timed out in sandbox (no output).
    - unsandboxed rerun passed:
      `.venv/bin/pytest -q tests/integration/test_file_editing_skills.py`
      (`17 passed`).
- Resume gates and next actions after compact:
  1. Commit this checkpoint-ready wave.
  2. Continue optional Plan C test-hygiene waves only on disjoint files
     (same orchestrator + parallel subagent model).
  3. Primary architecture gate remains unchanged:
     provider keep-alive real-endpoint evidence is deferred pending endpoint/model credentials and API keys in WSL.
  4. Windows host is not currently required for this gate; resume keep-alive
     Step 10 evidence once credentials/config become available.

Compact handoff checkpoint (2026-03-10, MCP schema regression + follow-up audit note):
- New live bug reported from MCP/OpenAI tool use:
  - `API request failed (400)`
  - provider payload error:
    `Invalid schema for function 'mcp_agentbridge_list_worlds': In context=(), object schema missing properties.`
- User report context:
  - this surfaced while using MCP-backed tools.
  - user also wants a later audit of GitLab tools for similar provider/schema compatibility issues and any related defects.
- Investigation status before compact:
  - bug is very likely real.
  - likely cause is empty/no-arg MCP input schemas being passed through unchanged into OpenAI-compatible function/tool definitions.
  - OpenAI appears to reject object schemas that omit `properties` entirely or otherwise present a provider-incompatible empty-object shape.
- Key files inspected:
  - `nexus3/mcp/skill_adapter.py`
    - MCP tool schemas are forwarded into skill parameters without provider-specific normalization.
  - `nexus3/mcp/protocol.py`
    - `MCPTool.input_schema` defaults to `{}` and `from_dict()` preserves incoming `inputSchema` directly.
  - `nexus3/skill/registry.py`
    - skill/tool definitions are emitted using `spec.parameters` / `skill.parameters` directly.
  - `nexus3/cli/repl_commands.py`
    - MCP skill definitions appended directly with `parameters: mcp_skill.parameters`.
  - `nexus3/rpc/pool.py` and `nexus3/rpc/pool_restore.py`
    - also forward MCP skill parameters directly into tool definitions.
  - `nexus3/provider/openai_compat.py`
    - provider sends tool definitions through as-shaped; no compatibility normalization found in the inspected path.
- Evidence / supporting observations:
  - MCP test fixtures already include empty-object input schemas, for example in `nexus3/mcp/test_server/definitions.py` (`get_time`).
  - ripgrep also showed empty object schemas in tests including:
    - `tests/unit/test_pool.py`
    - `tests/unit/skill/test_skillspec.py`
    - `tests/unit/mcp/test_protocol.py`
    - `tests/security/test_mcp_security.py`
  - `nexus3/provider/anthropic.py` also uses an empty-object fallback shape (`{"type": "object", "properties": {}}`), so schema-compat normalization should be handled carefully and probably centrally rather than ad hoc per callsite.
- Most likely implementation direction next turn:
  1. add centralized provider-facing schema normalization for no-arg tool schemas.
  2. cover MCP empty-schema shapes: `{}`, `{"type": "object"}`, and `{"type": "object", "properties": {}}`.
  3. add focused regressions for the OpenAI-compatible tool-definition path.
  4. after fixing MCP, schedule the requested GitLab-tool audit for similar schema/boundary issues.
- Important caution:
  - no code fix was landed yet for this MCP bug before compact.
  - do not accidentally revert the recent outline-audit changes; this MCP work is separate.

Execution checkpoint (2026-03-10, MCP/OpenAI empty-schema fix landed):
- Fixed live MCP/OpenAI provider regression:
  - OpenAI-compatible request shaping in `nexus3/provider/openai_compat.py`
    now normalizes no-arg tool schemas on the outbound provider path.
  - normalized shapes:
    - `{}`
    - `{"type": "object"}` (and other top-level object schemas with missing
      `properties`)
  - outbound normalized form:
    - `{"type": "object", "properties": {}}`
- Rationale:
  - MCP servers legitimately advertise no-arg tools with empty/default
    `inputSchema` values.
  - OpenAI-compatible APIs rejected those raw shapes with
    `invalid_function_parameters` / `object schema missing properties`.
  - provider-side normalization was chosen as the narrowest safe boundary so
    local skill/MCP contracts stay unchanged.
- Focused regressions added in:
  - `tests/unit/provider/test_compiler_integration.py`
    - empty `{}` schema normalization
    - `{"type": "object"}` normalization with non-mutating behavior
    - pass-through of already-valid `{"type": "object", "properties": {}}`
- Docs synced:
  - `nexus3/provider/README.md`
  - `CLAUDE.md`
- Validation snapshot:
  - passed:
    `.venv/bin/ruff check nexus3/provider/openai_compat.py tests/unit/provider/test_compiler_integration.py`
  - passed:
    `.venv/bin/pytest -q tests/unit/provider/test_compiler_integration.py`
    (`8 passed`)
- Quick follow-up audit result:
  - built-in GitLab skills do not appear to use the same empty top-level
    schema pattern; their parameter schemas are explicit object schemas with
    real properties.
  - a deeper GitLab tool audit is still worth doing later for other boundary
    issues, per user request, but the exact MCP/OpenAI empty-schema failure did
    not reproduce in the quick built-in GitLab scan.

Execution checkpoint (2026-03-10, GitLab artifact local-write path gating):
- GitLab audit confirmed one high-severity non-schema issue:
  - `gitlab_artifact` download actions write local files via `output_path`, but
    the tool was not registered in generic path semantics / destructive-action
    metadata.
  - effect before fix:
    - TRUSTED path confirmation and path gating did not treat
      `gitlab_artifact.output_path` like a write target.
    - a TRUSTED agent with GitLab enabled could download artifacts to local
      paths outside CWD without the normal path-based confirmation flow.
- Fix landed in:
  - `nexus3/session/path_semantics.py`
    - register `gitlab_artifact` with `write_keys=("output_path",)` and
      `display_key="output_path"`.
  - `nexus3/core/policy.py`
    - mark `gitlab_artifact` as destructive so TRUSTED confirmation logic
      applies to out-of-CWD local writes.
  - `tests/security/test_multipath_confirmation.py`
    - added semantics, display-path, extracted-path, confirmation-context, and
      TRUSTED confirmation regressions for `gitlab_artifact`.
  - `nexus3/session/README.md`
    - synced path-semantics docs.
  - `CLAUDE.md`
    - synced recent-fix note.
- Focused validation snapshot:
  - passed:
    `.venv/bin/ruff check nexus3/session/path_semantics.py nexus3/core/policy.py tests/security/test_multipath_confirmation.py`
  - passed:
    `.venv/bin/pytest -q tests/security/test_multipath_confirmation.py -k 'gitlab_artifact or patch or edit_lines or copy_file or rename'`
    (`35 passed`, `16 deselected`)
- Schema-side GitLab audit update:
  - built-in GitLab tool schemas did not show the MCP/OpenAI top-level empty
    object failure shape.
  - one lower-risk observation remains for later: nested free-form object usage
    in `gitlab_feature_flag.strategies[*].parameters` could be future provider
    friction if any provider starts enforcing recursive object-property
    requirements more strictly.

Compact handoff checkpoint (2026-03-10, post-MCP fix / post-GitLab audit):
- MCP/OpenAI empty-schema regression is fixed and pushed:
  - commit `5b83c9d` `fix(provider): normalize empty mcp tool schemas for openai`
  - provider-side normalization in `nexus3/provider/openai_compat.py` covers:
    - `{}`
    - `{"type": "object"}`
    - preserves already-valid `{"type": "object", "properties": {}}`
- GitLab audit found and fixed a separate high-severity issue:
  - commit `b63b704` `fix(gitlab): gate artifact downloads by output path`
  - `gitlab_artifact.output_path` is now treated as a write target in session path semantics and TRUSTED confirmation logic.
- Remaining GitLab follow-ups recorded for later:
  1. `nexus3/skill/vcs/gitlab/base.py`
     - synchronous `subprocess.run(...)` git autodetection in async execution paths (`_detect_instance_from_remote`, `_resolve_project`) still blocks the event loop up to the timeout window.
  2. `nexus3/skill/vcs/gitlab/artifact.py`
     - artifact download helpers still bypass shared `GitLabClient._request(...)` retry/rate-limit/error shaping by calling `client._ensure_client()` + raw `http_client.get(url)` directly.
  3. `nexus3/skill/vcs/gitlab/feature_flag.py`
     - nested free-form object at `strategies[*].parameters` is not a current provider break, but is the most likely future schema-friction point if providers ever enforce recursive object-property strictness.
- Important next-turn note:
  - user reports MCP is still having issues even after the empty-schema fix.
  - next turn should pivot back to MCP investigation first, not continue GitLab follow-up work.
  - likely first step: capture the new exact MCP error/transcript and compare it against the now-pushed `5b83c9d` behavior.

Compact handoff checkpoint (2026-03-10, MCP nested-schema follow-up):
- user later hit a new OpenAI-compatible provider rejection for MCP tool
  `mcp_agentbridge_tempo_pawn_move_to`:
  - `Invalid schema ... In context=('properties', 'location'), array schema missing items.`
- investigated pre-arch behavior before patching:
  - there was no earlier MCP adapter/provider normalization pass to restore.
  - older MCP adapter versions passed `tool.input_schema` through directly.
  - earlier `openai_compat.py` versions passed tool schemas through directly as
    well; the previous fix (`5b83c9d`) only added top-level no-arg object
    normalization.
  - conclusion: this is not an arch regression that removed a sanitizer; it is
    a newer/deeper external schema shape that now needs provider-boundary
    normalization.
- local fix in progress in `nexus3/provider/openai_compat.py`:
  - recursive outbound OpenAI normalization now adds provider-safe placeholders
    for nested fragments:
    - `{"type": "object"}` -> add `properties: {}`
    - `{"type": "array"}` -> add `items: {}`
  - still preserves caller-owned tool definitions (no in-place mutation).
- focused regressions added in
  `tests/unit/provider/test_compiler_integration.py` for:
  - nested array property without `items`
  - nested object property without `properties`
- focused validation passed locally:
  - `.venv/bin/ruff check nexus3/provider/openai_compat.py tests/unit/provider/test_compiler_integration.py`
  - `.venv/bin/pytest -q tests/unit/provider/test_compiler_integration.py`
- if the user reports another MCP schema rejection after this, inspect the next
  provider error context literally; likely remaining classes are other nested
  provider-strict JSON Schema requirements rather than the old top-level empty
  schema bug.

Deferred follow-up note (2026-03-10, edit_lines validation anomaly):
- user reports a lesser agent sometimes gets:
  - `Invalid arguments for edit_lines: Invalid argument: 'start_line' is a required property`
- code read confirms that exact message only comes from JSON Schema validation
  before `edit_lines.execute()` runs:
  - `nexus3/skill/builtin/edit_lines.py` requires `start_line` in schema
  - `nexus3/core/validation.py` / validation wrapper emit the required-property error only when the key is actually absent from the validated argument dict
- important implication:
  - if the same tool-call preview truly showed `start_line=...`, then preview and validated args diverged somewhere upstream
  - otherwise the likely cause is agent misuse with a near-miss key such as
    `startLine`, `start line`, `line`, or a different adjacent call being
    mistaken for the failing one
- preview path to inspect later:
  - `nexus3/cli/confirmation_ui.py::format_tool_params`
  - `nexus3/cli/repl.py` pending-tool trace path
- malformed JSON is less likely here because `_raw_arguments` failures produce a
  different error path in `nexus3/session/single_tool_runtime.py`

Execution update (2026-03-10, edit-lines batch alignment slice):
- Added new plan doc:
  - `docs/plans/EDIT-LINES-BATCH-AND-TOOL-CONTRACT-ALIGNMENT-PLAN-2026-03-10.md`
- Implemented batched `edit_lines(edits=[...])` support in
  `nexus3/skill/builtin/edit_lines.py`:
  - single-edit top-level mode remains supported
  - batch mode now accepts `edits=[{start_line, end_line?, new_content}, ...]`
  - batch ranges are interpreted against the original file and applied
    bottom-to-top automatically
  - overlapping ranges fail closed
  - batch writes remain atomic
- Added focused coverage in:
  - `tests/unit/skill/test_edit_lines.py`
  - `tests/integration/test_file_editing_skills.py`
- Updated agent-facing docs/prompts in:
  - `README.md`
  - `CLAUDE.md`
  - `nexus3/defaults/NEXUS-DEFAULT.md`
  - `AGENTS_NEXUS3SKILLSCAT.md`
  - `nexus3/skill/README.md`
  - `docs/plans/README.md`
- Focused consistency-audit follow-ups recorded in the new plan doc:
  - permissive schemas / silent extra-arg dropping
  - `edit_file` / `patch` runtime-only dual-shape invariants
  - uneven batch capability across the file-edit family
  - inconsistent empty-string semantics
  - mixed path argument naming
- Focused validation passed:
  - `.venv/bin/ruff check nexus3/skill/builtin/edit_lines.py tests/unit/skill/test_edit_lines.py tests/integration/test_file_editing_skills.py README.md CLAUDE.md nexus3/defaults/NEXUS-DEFAULT.md AGENTS_NEXUS3SKILLSCAT.md nexus3/skill/README.md docs/plans/EDIT-LINES-BATCH-AND-TOOL-CONTRACT-ALIGNMENT-PLAN-2026-03-10.md docs/plans/README.md`
  - `.venv/bin/pytest -q tests/unit/skill/test_edit_lines.py tests/integration/test_file_editing_skills.py -k edit_lines`
  - `git diff --check`


Planning checkpoint (2026-03-10, file-edit contract harmonization discussion):
- Approved keep-as-is differences:
  - semantic content names remain tool-specific where they reflect the edit
    model (`content`, `new_content`, `new_string`, `replacement`)
  - two-path operations keep `source` / `destination`
  - patch-specific diff controls (`diff`, `diff_file`, `mode`, `dry_run`) stay
    patch-specific
  - `edit_file.replace_all` remains specific to literal-match disambiguation
- Approved note/reminder items (document rather than flatten):
  - `read_file` is numbered by default; exact-match edits should usually use
    `line_numbers=false`
  - future ergonomics follow-up: consider accepting `read_file.start_line` and
    `read_file.end_line` as compatibility aliases for the existing
    `offset` / `limit` paging contract
  - `edit_file(edits=[...])` batch items must be independent
  - `edit_lines(edits=[...])` uses original-file line numbers and auto-orders
    bottom-to-top
  - text-edit tools stay UTF-8-only; byte-sensitive work should use `patch`
- Approved harmonization targets:
  1. reject unknown args consistently across the file-edit family
  2. keep `path` as the canonical single-target file-edit argument
  3. keep `edits=[...]` as the shared batch convention where batching exists
  4. centralize empty-placeholder normalization instead of patching it tool by
     tool forever
- Added follow-on implementation plan:
  - `docs/plans/FILE-EDIT-TOOL-CONTRACT-HARMONIZATION-PLAN-2026-03-10.md`
- Deferred adjacent follow-up for later:
  - run a similar contract audit across other tool families, not just file-edit
    tools (for example: GitLab, MCP-exposed tools, clipboard, nexus_*, exec/
    shell, and other high-misuse tool groups)
  - talk with the user specifically about the shell tool family again later
    (`bash_safe`, `shell_UNSAFE`, `run_python`) and decide which contract
    differences are intentional vs worth harmonizing

Execution update (2026-03-10, file-edit contract harmonization phase 1):
- Completed Phase 1 from
  `docs/plans/FILE-EDIT-TOOL-CONTRACT-HARMONIZATION-PLAN-2026-03-10.md`:
  reject unknown args consistently across the file-edit family.
- Hardened these file-edit tools with `additionalProperties: false` so malformed
  extra args now fail closed instead of being silently dropped:
  - `nexus3/skill/builtin/read_file.py`
  - `nexus3/skill/builtin/write_file.py`
  - `nexus3/skill/builtin/edit_file.py`
  - `nexus3/skill/builtin/edit_lines.py`
  - `nexus3/skill/builtin/append_file.py`
  - `nexus3/skill/builtin/regex_replace.py`
  - `nexus3/skill/builtin/patch.py`
  - `nexus3/skill/builtin/copy_file.py`
  - `nexus3/skill/builtin/rename.py`
  - `nexus3/skill/builtin/mkdir.py`
- Nested batch items are now strict as well for:
  - `edit_file.edits[*]`
  - `edit_lines.edits[*]`
- Focused validation coverage added in
  `tests/unit/skill/test_skill_validation.py`:
  - top-level unknown-arg rejection across the file-edit family
  - nested unknown-field rejection for `edit_file.edits[*]` and
    `edit_lines.edits[*]`
- Agent-facing docs synced with the new contract rule:
  - `nexus3/defaults/NEXUS-DEFAULT.md`
  - `AGENTS_NEXUS3SKILLSCAT.md`
  - `nexus3/skill/README.md`
  - `CLAUDE.md`
- Focused validation passed:
  - `.venv/bin/ruff check nexus3/skill/builtin/read_file.py nexus3/skill/builtin/write_file.py nexus3/skill/builtin/append_file.py nexus3/skill/builtin/regex_replace.py nexus3/skill/builtin/copy_file.py nexus3/skill/builtin/rename.py nexus3/skill/builtin/mkdir.py nexus3/skill/builtin/edit_file.py nexus3/skill/builtin/edit_lines.py nexus3/skill/builtin/patch.py tests/unit/skill/test_skill_validation.py`
  - `.venv/bin/pytest -q tests/unit/test_skill_validation.py tests/unit/skill/test_skill_validation.py` (`40 passed`)
  - `git diff --check`
- Next gate:
  - Phase 2: keep `patch.path` canonical and continue de-emphasizing
    `patch.target` without breaking compatibility.

Execution update (2026-03-10, file-edit contract harmonization phase 2):
- Completed Phase 2 from
  `docs/plans/FILE-EDIT-TOOL-CONTRACT-HARMONIZATION-PLAN-2026-03-10.md`:
  continue canonicalizing `patch.path` while preserving `target` compatibility.
- `nexus3/skill/builtin/patch.py` now treats `path=` as the public canonical
  target argument and emits a compatibility reminder in successful output when
  callers still use legacy `target=`.
- `target=` remains accepted as a non-breaking compatibility alias; no runtime
  behavior change to patch application semantics beyond the reminder.
- Synced canonical patch contract wording in:
  - `nexus3/defaults/NEXUS-DEFAULT.md`
  - `AGENTS_NEXUS3SKILLSCAT.md`
  - `nexus3/skill/README.md`
  - `CLAUDE.md`
  - `README.md`
- Added focused regressions in `tests/unit/skill/test_patch.py` for:
  - canonical `path=` success without alias reminder
  - legacy `target=` success with compatibility reminder
- Focused validation passed:
  - `.venv/bin/ruff check nexus3/skill/builtin/patch.py tests/unit/skill/test_patch.py`
  - `.venv/bin/pytest -q tests/unit/skill/test_patch.py` (`38 passed`)
  - `.venv/bin/pytest -q tests/integration/test_file_editing_skills.py -k patch` (`10 passed`)
  - `git diff --check`
- Next gate:
  - Phase 3: centralize empty-placeholder normalization for file-edit tools
    instead of maintaining one-off per-tool branches.

Execution update (2026-03-10, file-edit contract harmonization phase 3):
- Completed Phase 3 from
  `docs/plans/FILE-EDIT-TOOL-CONTRACT-HARMONIZATION-PLAN-2026-03-10.md`:
  centralize empty-placeholder normalization for file-edit tools.
- Added narrow shared helper module:
  - `nexus3/skill/argument_normalization.py`
  - provides shared optional-string omission normalization for callers that send
    `\"\"` when they mean “parameter omitted”
- Migrated duplicated one-off normalization branches in:
  - `nexus3/skill/builtin/edit_file.py`
  - `nexus3/skill/builtin/edit_lines.py`
  - `nexus3/skill/builtin/patch.py`
- Behavior is unchanged intentionally:
  - `edit_file` batch placeholder single-edit fields still normalize safely
  - `edit_lines` batch placeholder `new_content=\"\"` still means omitted
  - `patch` placeholder `diff=\"\"` / `diff_file=\"\"` still mean omitted
- Focused validation passed:
  - `.venv/bin/ruff check nexus3/skill/argument_normalization.py nexus3/skill/builtin/edit_file.py nexus3/skill/builtin/edit_lines.py nexus3/skill/builtin/patch.py tests/unit/skill/test_edit_file.py tests/unit/skill/test_edit_lines.py tests/unit/skill/test_patch.py`
  - `.venv/bin/pytest -q tests/unit/skill/test_edit_file.py tests/unit/skill/test_edit_lines.py tests/unit/skill/test_patch.py` (`84 passed`)
- Next gate:
  - File-edit contract harmonization plan is complete.
  - Next sensible follow-up is the broader discussion already approved by the
    user: which remaining cross-tool inconsistencies are appropriate vs should
    be standardized next, and then a similar audit for other tool families.
  - after compact/resume, start that broad audit rather than another file-edit
    slice unless the user redirects.
  - deferred hygiene reminder: return to full 100% green validation
    (not just focused touched-file passes) after the current audit/fix cycle.

Execution update (2026-03-10, broad tool-family audit kickoff):
- Added new broad follow-up plan:
  - `docs/plans/BROAD-TOOL-FAMILY-AUDIT-AND-HARDENING-PLAN-2026-03-10.md`
- Broad audit findings recorded for the next non-file-edit families:
  - clipboard family has the highest-severity issues:
    - `clipboard_update(source=...)` was reading files via raw
      `Path(...).resolve()` instead of the shared path-validation stack
    - clipboard file tools were not fully wired into
      `session/path_semantics.py`
    - TRUSTED destructive confirmation did not cover all clipboard
      write-side file tools (`cut`, `paste`, `clipboard_export`)
  - `nexus_*` family remains non-strict on unknown args and still has
    doc/runtime drift around `nexus_create` knobs and request-id behavior
  - shell/exec/git family remains non-strict on unknown args, though current
    docs are broadly accurate after the Windows shell fixes
  - GitLab/MCP-adjacent follow-ups remain open:
    - GitLab top-level schemas are still non-strict
    - shared validation currently strips valid dynamic keys from open-ended
      MCP-style schemas by collapsing validated args back to explicit
      `properties`
    - GitLab autodetection still blocks the event loop with synchronous
      subprocess calls
- Active phase:
  - Phase 1 from
    `docs/plans/BROAD-TOOL-FAMILY-AUDIT-AND-HARDENING-PLAN-2026-03-10.md`:
    clipboard security hardening
- Phase 1 implementation target:
  - route `clipboard_update(source=...)` through shared path validation
  - register clipboard file tools in `session/path_semantics.py`
  - bring clipboard file writers under the normal TRUSTED confirmation model
  - add focused permission/path regressions before moving on to the nexus/shell
    families

Execution update (2026-03-10, broad tool-family audit phase 1 complete):
- Completed Phase 1 from
  `docs/plans/BROAD-TOOL-FAMILY-AUDIT-AND-HARDENING-PLAN-2026-03-10.md`:
  clipboard security hardening
- Hardened clipboard file-path handling and confirmation semantics in:
  - `nexus3/skill/builtin/clipboard_manage.py`
    - `clipboard_update(source=...)` now resolves through the shared
      `PathResolver` path-validation stack instead of raw `Path(...).resolve()`
  - `nexus3/session/path_semantics.py`
    - registered explicit semantics for `copy`, `cut`, `paste`,
      `clipboard_export`, `clipboard_import`, and `clipboard_update`
  - `nexus3/core/policy.py`
    - added `cut`, `paste`, and `clipboard_export` to TRUSTED destructive
      action handling
  - `nexus3/session/enforcer.py`
    - updated the path-tool registry for clipboard file tools
- Added focused regressions in:
  - `tests/unit/skill/test_clipboard_manage.py`
    - blocked/out-of-scope `clipboard_update(source=...)`
  - `tests/security/test_multipath_confirmation.py`
    - clipboard tool path semantics, write-path extraction, TRUSTED
      confirmation, and confirmation-context coverage
  - `tests/unit/test_permissions.py`
    - clipboard destructive-action membership and cwd-aware confirmation checks
- Synced plan/status/module docs in:
  - `docs/plans/BROAD-TOOL-FAMILY-AUDIT-AND-HARDENING-PLAN-2026-03-10.md`
  - `docs/plans/README.md`
  - `nexus3/session/README.md`
- Focused validation passed:
  - `.venv/bin/ruff check nexus3/skill/builtin/clipboard_manage.py nexus3/session/path_semantics.py nexus3/session/enforcer.py nexus3/core/policy.py tests/unit/skill/test_clipboard_manage.py tests/security/test_multipath_confirmation.py tests/unit/test_permissions.py docs/plans/BROAD-TOOL-FAMILY-AUDIT-AND-HARDENING-PLAN-2026-03-10.md docs/plans/README.md AGENTS.md nexus3/session/README.md`
  - `.venv/bin/pytest -q tests/unit/skill/test_clipboard_manage.py tests/security/test_multipath_confirmation.py tests/unit/test_permissions.py` (`183 passed`)
  - `git diff --check`
- Next gate:
  - Phase 2: nexus family contract hardening
  - keep the MCP/open-ended-schema validation hazard recorded for the later
    shared validation slice before expanding strictness to more external-tool
    families

Execution update (2026-03-10, broad tool-family audit phase 2 complete):
- Completed Phase 2 from
  `docs/plans/BROAD-TOOL-FAMILY-AUDIT-AND-HARDENING-PLAN-2026-03-10.md`:
  nexus-family contract hardening
- Hardened the `nexus_*` family in:
  - `nexus3/skill/builtin/nexus_create.py`
    - top-level schema is now strict (`additionalProperties: false`)
    - blank `model=""` / whitespace-only model placeholders now normalize to
      omission instead of producing confusing downstream model-resolution
      behavior
    - parameter descriptions now explicitly state that
      `wait_for_initial_response` only matters when `initial_message` is
      provided
  - `nexus3/skill/builtin/nexus_send.py`
    - top-level schema is now strict
    - whitespace-only content is rejected before dispatch
  - `nexus3/skill/builtin/nexus_status.py`
    - top-level schema is now strict
  - `nexus3/skill/builtin/nexus_cancel.py`
    - top-level schema is now strict
    - `request_id` now accepts string or integer to match RPC id semantics
  - `nexus3/skill/builtin/nexus_destroy.py`
    - top-level schema is now strict
  - `nexus3/skill/builtin/nexus_shutdown.py`
    - top-level schema is now strict
- Added focused regressions in:
  - `tests/unit/skill/test_nexus_create.py`
    - blank-model placeholder normalization
  - `tests/unit/skill/test_nexus_skills.py`
    - integer `nexus_cancel.request_id`
    - whitespace-only `nexus_send` rejection
  - `tests/unit/skill/test_skill_validation.py`
    - unknown-arg rejection across the full `nexus_*` family
- Synced user-facing docs in:
  - `nexus3/defaults/NEXUS-DEFAULT.md`
  - `AGENTS_NEXUS3SKILLSCAT.md`
  - `README.md`
  - `nexus3/skill/README.md`
  - `CLAUDE.md`
- Focused validation passed:
  - `.venv/bin/ruff check nexus3/skill/builtin/nexus_create.py nexus3/skill/builtin/nexus_send.py nexus3/skill/builtin/nexus_status.py nexus3/skill/builtin/nexus_cancel.py nexus3/skill/builtin/nexus_destroy.py nexus3/skill/builtin/nexus_shutdown.py tests/unit/skill/test_nexus_create.py tests/unit/skill/test_nexus_skills.py tests/unit/skill/test_skill_validation.py`
  - `.venv/bin/pytest -q tests/unit/skill/test_nexus_create.py tests/unit/skill/test_nexus_skills.py tests/unit/skill/test_skill_validation.py tests/unit/test_initial_message.py -k 'nexus or initial_message or validation'` (`53 passed`)
  - `git diff --check`
- Next gate:
  - Phase 3: shell / exec family contract hardening
  - keep the MCP/open-ended-schema validation hazard queued for the later
    shared validation slice rather than mixing it into the shell-family work

Execution update (2026-03-10, broad tool-family audit phase 3 complete):
- Completed Phase 3 from
  `docs/plans/BROAD-TOOL-FAMILY-AUDIT-AND-HARDENING-PLAN-2026-03-10.md`:
  shell / exec / git family contract hardening
- Hardened the shell/exec/git family in:
  - `nexus3/skill/builtin/bash.py`
    - top-level schemas for `bash_safe` and `shell_UNSAFE` are now strict
      (`additionalProperties: false`)
    - blank or whitespace-only `command` payloads now fail fast instead of
      being passed to a subprocess
  - `nexus3/skill/builtin/run_python.py`
    - top-level schema is now strict
    - blank or whitespace-only `code` payloads now fail fast instead of
      spawning a no-op interpreter process
  - `nexus3/skill/builtin/git.py`
    - top-level schema is now strict
  - `nexus3/skill/builtin/echo.py`
    - top-level schema is now strict
  - `nexus3/skill/builtin/sleep.py`
    - top-level schema is now strict
- Added focused regressions in:
  - `tests/unit/skill/test_skill_validation.py`
    - unknown-arg rejection across `bash_safe`, `shell_UNSAFE`, `run_python`,
      `git`, `echo`, and `sleep`
    - updated strictness expectation for `sleep`
- Synced user-facing docs in:
  - `nexus3/defaults/NEXUS-DEFAULT.md`
  - `README.md`
  - `nexus3/skill/README.md`
  - `AGENTS_NEXUS3SKILLSCAT.md`
  - `CLAUDE.md`
- Focused validation passed:
  - `.venv/bin/ruff check nexus3/skill/builtin/bash.py nexus3/skill/builtin/run_python.py nexus3/skill/builtin/git.py nexus3/skill/builtin/echo.py nexus3/skill/builtin/sleep.py tests/unit/skill/test_skill_validation.py AGENTS_NEXUS3SKILLSCAT.md CLAUDE.md nexus3/defaults/NEXUS-DEFAULT.md README.md nexus3/skill/README.md`
  - `.venv/bin/pytest -q tests/unit/skill/test_skill_validation.py tests/unit/test_skill_validation.py tests/unit/test_git_skill.py tests/unit/skill/test_bash_windows_behavior.py` (`84 passed`)
  - `git diff --check`
- Next gate:
  - Phase 4: clipboard / GitLab schema strictness and shared MCP/open-ended
    validation repair
  - keep the broader GitLab operational follow-ups queued for the later
    bounded slice after shared validation is corrected
