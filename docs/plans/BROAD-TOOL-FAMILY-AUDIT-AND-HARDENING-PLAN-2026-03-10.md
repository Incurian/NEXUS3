# Broad Tool-Family Audit And Hardening Plan (2026-03-10)

## Overview

The file-edit family harmonization closed one major contract hotspot, but the
same failure patterns remain across other tool families:

- silent dropping of unknown arguments
- provider-facing schema fragments that are too loose or incomplete
- family-specific permission/confirmation gaps
- prompt/doc tables that no longer match runtime behavior

The first critical follow-up is the clipboard family. Unlike the shell, nexus,
and GitLab families, clipboard tools currently have real permission-boundary
problems, not just schema/docs drift.

## Scope

### Included

- Audit the remaining non-file-edit built-in tool families:
  - shell / execution / git
  - nexus agent-management
  - clipboard
  - GitLab / MCP-adjacent provider-exposed schemas
- Fix the highest-severity clipboard security and confirmation issues first.
- Add a phased hardening plan for the remaining families.

### Deferred

- A full shell-family redesign beyond current Git Bash follow-ups.
- Large GitLab transport refactors such as async subprocess autodetection and
  centralizing artifact downloads onto the shared client path.
- Auditing every single non-built-in MCP tool schema in the same patch series.

### Excluded

- Reworking the semantics of distinct tool families into one generic API.
- Retiring backwards-compatibility aliases in the same sweep unless they are
  directly security-relevant.

## Audit Findings

### Cross-Family

1. Outside the file-edit family, most tool schemas still do not set
   `additionalProperties: false`, so unknown args are silently filtered by the
   shared validation wrapper instead of being rejected.
2. Prompt/docs are not consistently synced to the runtime contract, especially
   for `nexus_*` and clipboard tools.

### Clipboard

1. `clipboard_update(source=...)` reads source files via raw `Path(...).resolve()`
   instead of the normal path-validation stack.
2. Clipboard file-writing tools are not fully wired into shared path semantics
   and TRUSTED destructive-action confirmation:
   - `cut`
   - `paste`
   - `clipboard_export`
3. Clipboard path-reading tools are under-specified in path semantics, which
   keeps permission checks and confirmation context out of sync with actual
   behavior.
4. `clipboard_tag` exposes actions that are only partially implemented
   (`delete` is still a deliberate error path).

### Nexus Agent-Management

1. `nexus_*` tool schemas were non-strict and silently dropped typoed args
   until Phase 2 hardened them.
2. `nexus_create` previously forwarded blank `model=""` placeholders instead of
   normalizing them to omission.
3. Prompt/docs tables previously omitted some valid knobs
   (`allowed_write_paths`, `disable_tools`, `wait_for_initial_response`,
   `port`) in some user-facing references.
4. `wait_for_initial_response=true` without `initial_message` is intentionally
   accepted as a no-op by the underlying RPC contract, so the skill/docs must
   document that behavior rather than pretend it blocks.
5. `nexus_cancel` previously accepted only string `request_id`, while the RPC
   layer accepts broader JSON-RPC id types.

### Shell / Exec / Git

1. `bash_safe`, `shell_UNSAFE`, `run_python`, `git`, `echo`, and `sleep` are
   were non-strict on unknown args before Phase 3.
2. The shell-family docs are broadly accurate after recent Windows work, but
   still rely on prompt guidance rather than schema enforcement for malformed
   calls.

### GitLab / MCP-Adjacent

1. All built-in GitLab skill schemas were non-strict on unknown args before
   Phase 4.
2. Shared tool-argument validation was stripping valid keys from open-ended
   schemas by filtering validated arguments back down to explicit
   `schema["properties"]` keys only. That is safe for strict built-in tools but
   breaks MCP-exposed tools that intentionally rely on `additionalProperties`,
   `patternProperties`, or object schemas without explicit `properties`.
2. `gitlab_feature_flag` still contains nested loose object fragments that are
   plausible future provider-compatibility hazards if object-schema strictness
   tightens further.
3. GitLab autodetection still uses synchronous `subprocess.run(...)` in async
   skill paths.

## Design Decisions And Rationale

### 1. Fix real permission holes before broad schema cleanup

Clipboard path/confirmation gaps can lead to behavior that is actually less
safe than intended. Those outrank contract cleanliness work.

### 2. Standardize strict argument rejection family-by-family

The file-edit family already moved to fail-closed unknown-arg behavior. The
remaining families should follow, but in bounded slices so tests/docs stay
reviewable.

### 3. Keep semantic differences where they reflect real domain behavior

This plan is about harmonizing outer contracts and enforcement, not flattening
clipboard, shell, nexus, and GitLab tools into one generic schema.

## Implementation Details

### Phase 1: Clipboard Security Hardening

Files:

- `nexus3/skill/builtin/clipboard_manage.py`
- `nexus3/session/path_semantics.py`
- `nexus3/core/policy.py`
- `tests/unit/skill/test_clipboard_manage.py`
- `tests/security/test_multipath_confirmation.py`
- `tests/unit/test_permissions.py`
- `AGENTS.md`

Work:

- Route `clipboard_update(source=...)` through the shared path-validation stack.
- Register clipboard path semantics so permission checks and confirmation logic
  see the correct read/write paths.
- Mark clipboard file-writing tools as destructive where TRUSTED confirmation
  should apply.
- Add focused regressions for:
  - blocked/out-of-scope `clipboard_update(source=...)`
  - `cut` / `paste` / `clipboard_export` confirmation semantics

### Phase 2: Nexus Family Contract Hardening

Files:

- `nexus3/skill/builtin/nexus_*.py`
- `tests/unit/skill/test_skill_validation.py`
- `tests/unit/skill/test_nexus_create.py`
- prompt/docs tables

Work:

- Add strict unknown-arg rejection to the `nexus_*` family.
- Normalize `model=""` to omission in `nexus_create`.
- Keep the current `wait_for_initial_response` without `initial_message`
  behavior documented as a no-op rather than changing the RPC contract here.
- Broaden `nexus_cancel.request_id` to match RPC id types.
- Sync prompt/docs tables.

### Phase 3: Shell / Exec Family Contract Hardening

Files:

- `nexus3/skill/builtin/bash.py`
- `nexus3/skill/builtin/run_python.py`
- `nexus3/skill/builtin/git.py`
- `nexus3/skill/builtin/echo.py`
- `nexus3/skill/builtin/sleep.py`
- relevant validation/docs tests

Work:

- Add strict unknown-arg rejection.
- Reject blank/whitespace-only `command` and `code` payloads before subprocess
  launch.
- Re-check prompt/docs wording against current Windows shell-selection behavior.

### Phase 4: Clipboard / GitLab Schema Strictness And Docs

Files:

- clipboard family schemas/docs
- GitLab family schemas/docs
- shared validation tests

Work:

- Bring remaining clipboard schemas under strict unknown-arg rejection.
- Bring GitLab top-level schemas under strict unknown-arg rejection.
- Fix shared validation so MCP/open-ended schemas preserve validated dynamic
  keys instead of being collapsed back to only explicit property names.
- Wrap GitLab registry-created skills with the standard validation layer so
  direct registry usage matches the rest of the built-in families.
- Revisit nested GitLab object fragments that are likely provider-compatibility
  hazards.

### Phase 5: GitLab Operational Follow-Ups

Files:

- `nexus3/skill/vcs/gitlab/base.py`
- `nexus3/skill/vcs/gitlab/artifact.py`
- related tests/docs

Work:

- Move blocking git autodetection off the event loop.
- Move artifact fetches onto the shared GitLab client request path.

## Testing Strategy

- Focused `ruff check` on touched skill/core/session/test files.
- Focused unit coverage for:
  - validation behavior
  - permission/confirmation behavior
  - family-specific boundary fixes
- Focused integration/security coverage where path or confirmation semantics are
  involved.
- `git diff --check` before each commit.

## Implementation Checklist

- [x] Record broad audit findings and phased fix order.
- [x] Phase 1: harden clipboard path validation and confirmation semantics.
- [x] Phase 2: harden `nexus_*` contracts.
- [ ] Phase 3: harden shell / exec family contracts.
- [ ] Phase 4: tighten clipboard and GitLab schema strictness/docs.
- [ ] Phase 5: address GitLab operational follow-ups or defer explicitly.
- [ ] Return to full 100% green validation, not only focused touched-file runs.

## Documentation Updates

- Update `docs/plans/README.md`.
- Keep `AGENTS.md` running status aligned with the active phase and next gate.
- Sync `CLAUDE.md`, `AGENTS_NEXUS3SKILLSCAT.md`, and `nexus3/defaults/NEXUS-DEFAULT.md`
  whenever user-facing tool contracts change.
