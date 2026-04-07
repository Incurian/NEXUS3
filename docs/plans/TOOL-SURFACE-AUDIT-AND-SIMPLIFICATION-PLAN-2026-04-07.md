# Tool Surface Audit And Simplification Plan (2026-04-07)

## Overview

This slice audits the remaining built-in tool surfaces after the `edit_file` /
`edit_file_batch` split and applies the same contract rule more broadly:

- one public tool name per top-level argument shape
- no public compatibility aliases when one canonical name is sufficient
- explicit discriminators such as `action` or `mode` are acceptable only when
  the top-level object shape remains stable and the model is not forced to pick
  between hidden aliases or mutually exclusive wrapper shapes

The goal is to improve weak-model tool-call reliability, especially for the
default prompt and OpenAI-compatible providers that work best with flat,
unambiguous object schemas.

## Scope

Included:

- audit the remaining built-in tool surfaces and classify them by risk
- simplify high-risk public contracts that still expose multiple top-level
  shapes or compatibility aliases
- keep backwards compatibility at the runtime / execute boundary where needed
- update default prompt and skill documentation to teach the simplified shapes
- add regression tests for the new public schemas and compatibility rewrites

Deferred:

- large action-dispatched families such as GitLab tools
- broad clipboard-family decomposition beyond documentation guidance
- public process-tool renames/splits unless the current audit finds a concrete
  failure mode that justifies the churn

Excluded:

- MCP tool contracts owned by external servers
- provider-specific tool schema normalization internals beyond doc alignment

## Audit Findings

High-risk public surfaces:

1. `edit_lines`
   - currently exposes both a single-edit top-level shape and a batch
     `edits=[...]` top-level shape
   - this mirrors the old `edit_file` failure pattern
2. `patch`
   - currently exposes both inline `diff` and file-backed `diff_file`
   - also advertises `target` as a public alias for `path`
3. `read_file`
   - still teaches both canonical `offset`/`limit` and compatibility aliases
     `start_line`/`end_line`
4. `outline`
   - still teaches three names for the same parser-override concept:
     `file_type`, `language`, and `parser`

Acceptable but watch-listed surfaces:

1. action/mode-dispatched tools such as `clipboard_tag`, `paste`, and GitLab
   tools
   - these still have a stable top-level shape with an explicit discriminator
   - they are complex, but they do not rely on hidden alias pairs or separate
     wrapper shapes
2. `get_process`
   - exact PID and unique-query lookup are different selector styles, but the
     tool is read-only and already has a strong discovery path via
     `list_processes`
   - keep for now unless telemetry or concrete failures show it needs a split

## Design Decisions And Rationale

1. Split `edit_lines` into:
   - `edit_lines` for one line-range replacement
   - `edit_lines_batch` for atomic multi-range replacements

Rationale:

- this directly matches the successful `edit_file` / `edit_file_batch` pattern
- batch semantics are strong enough to deserve their own tool name

2. Split `patch` into:
   - `patch` for inline diff text
   - `patch_from_file` for loading diff text from a diff/patch file

Rationale:

- inline diff text and diff-file loading are distinct top-level shapes
- weak models should not need to choose between `diff` and `diff_file`
- `target` remains compatibility-only, not part of the public contract

3. Hide compatibility aliases from public read/navigation schemas:
   - `read_file`: canonical `offset` / `limit`
   - `outline`: canonical `parser`

Rationale:

- aliases are useful for compatibility, but they should not be taught as equal
  public options in the default prompt

4. Keep explicit discriminator families intact for now.

Rationale:

- explicit `action` / `mode` fields are less error-prone than alias-driven
  shape overloading
- splitting those families now would add large churn with less immediate
  reliability gain

## Implementation Details

Primary code changes:

- `nexus3/skill/builtin/edit_lines.py`
  - introduce dedicated single-edit and batch-edit skill surfaces
  - preserve shared implementation and current file-fidelity behavior
- `nexus3/skill/builtin/patch.py`
  - introduce `patch_from_file`
  - keep legacy alias/input compatibility in execution paths
- `nexus3/skill/builtin/read_file.py`
  - keep alias support in execution helpers while removing it from the public
    schema/teaching surface
- `nexus3/skill/builtin/outline.py`
  - keep parser override aliases for compatibility while exposing only the
    canonical public parameter
- `nexus3/session/single_tool_runtime.py`
  - normalize legacy tool-call shapes before validation
- `nexus3/skill/builtin/registration.py`
  - register any new dedicated tool names
- `nexus3/session/path_semantics.py`
  - register semantics for new tool names
- `nexus3/session/enforcer.py`
  - include new tool names in path-tool gating
- `nexus3/core/policy.py`
  - include new write tools in destructive-action logic
- docs:
  - `nexus3/defaults/NEXUS-DEFAULT.md`
  - `nexus3/skill/README.md`
  - `nexus3/skill/builtin/README.md`
  - `README.md`
  - `AGENTS_NEXUS3SKILLSCAT.md`
  - `nexus3/session/README.md`

Tests:

- `tests/unit/skill/test_edit_lines.py`
- `tests/unit/skill/test_patch.py`
- `tests/unit/session/test_single_tool_runtime.py`
- `tests/unit/skill/test_skill_validation.py`
- `tests/integration/test_file_editing_skills.py`
- permission/path-semantics tests that enumerate write tools or tool names

## Testing Strategy

Focused:

- unit tests for public schema shape changes
- runtime normalization tests for legacy `edit_lines(edits=[...])`,
  `patch(diff_file=...)`, `read_file(start_line=...)`, and parser alias calls
- integration tests for `edit_lines_batch` and `patch_from_file`
- permission/path-semantics tests for new tool names

Broader:

- targeted lint + type checks for touched modules
- full repo test suite after the contract changes settle

Live validation:

- rerun the standard RPC smoke path if any session/runtime/permission changes
  materially affect tool execution

## Implementation Checklist

- [x] split `edit_lines` public contract and add `edit_lines_batch`
- [x] split `patch` public contract and add `patch_from_file`
- [x] hide `read_file` alias parameters from the public schema
- [x] hide `outline` parser aliases from the public schema
- [x] add single-tool runtime compatibility normalization for legacy calls
- [x] update registration / policy / path semantics / confirmation references
- [x] update default prompt and skill docs
- [x] run focused validation
- [x] run full test suite
- [x] update `AGENTS.md` current handoff

## Validation Status

- Focused validation passed:
  - `.venv/bin/pytest -q tests/unit/skill/test_edit_lines.py tests/unit/skill/test_patch.py tests/unit/session/test_single_tool_runtime.py tests/unit/skill/test_skill_validation.py tests/unit/test_skill_enhancements.py tests/unit/skill/test_outline.py tests/security/test_multipath_confirmation.py tests/unit/session/test_enforcer.py tests/integration/test_file_editing_skills.py tests/unit/test_permissions.py tests/unit/test_global_dispatcher.py tests/unit/test_git_context.py` (`602 passed`)
  - `.venv/bin/ruff check nexus3/skill/builtin/edit_lines.py nexus3/skill/builtin/patch.py nexus3/skill/builtin/read_file.py nexus3/skill/builtin/outline.py nexus3/session/single_tool_runtime.py nexus3/session/path_semantics.py nexus3/session/enforcer.py nexus3/core/policy.py nexus3/commands/core.py nexus3/rpc/global_dispatcher.py nexus3/context/git_context.py tests/unit/skill/test_edit_lines.py tests/unit/skill/test_patch.py tests/unit/session/test_single_tool_runtime.py tests/unit/skill/test_skill_validation.py tests/unit/test_skill_enhancements.py tests/unit/skill/test_outline.py tests/security/test_multipath_confirmation.py tests/unit/session/test_enforcer.py tests/integration/test_file_editing_skills.py tests/unit/test_permissions.py tests/unit/test_global_dispatcher.py tests/unit/test_git_context.py`
  - `.venv/bin/mypy nexus3/skill/builtin/edit_lines.py nexus3/skill/builtin/patch.py nexus3/skill/builtin/read_file.py nexus3/skill/builtin/outline.py nexus3/session/single_tool_runtime.py nexus3/session/path_semantics.py nexus3/session/enforcer.py nexus3/core/policy.py nexus3/commands/core.py nexus3/rpc/global_dispatcher.py nexus3/context/git_context.py`
- Full suite passed:
  - `.venv/bin/pytest tests/ -q` (`4570 passed, 3 skipped, 22 warnings`)
- Live validation passed on port `9000`:
  - `NEXUS_DEV=1 .venv/bin/nexus3 --serve 9000`
  - `.venv/bin/nexus3 rpc detect --port 9000`
  - `.venv/bin/nexus3 rpc create test-agent --port 9000`
  - `.venv/bin/nexus3 rpc send test-agent "describe your permissions and what you can do" --port 9000`
  - `.venv/bin/nexus3 rpc destroy test-agent --port 9000`
  - `.venv/bin/nexus3 rpc list --port 9000`
  - destroy/list cleanup required a brief follow-up poll before the final empty list
- Hygiene:
  - `git diff --check`

## Documentation Updates

- teach only canonical public shapes in `NEXUS-DEFAULT.md`
- explicitly document the design rule in `nexus3/skill/README.md`
- refresh built-in skill tables and counts
- note that explicit discriminator tools are acceptable exceptions, while
  compatibility aliases should stay hidden from the public surface
