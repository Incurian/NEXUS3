# Ripgrep Availability And Determinism Plan (2026-03-11)

## Overview

Built-in `grep` currently gets its fast path only when `rg` is already
installed and available on `PATH`, and that availability is detected via a
module-load `shutil.which("rg")` check. That means directory-search
performance depends on ambient host state in a way that is not explicit in
config, packaging, or runtime diagnostics.

This slice makes ripgrep availability more deterministic without taking on an
immediate cross-platform binary-vendoring project. The goal is a clear
contract: when NEXUS should use ripgrep, how it finds it, how users can point
to it explicitly, and how/when the tool should fail closed instead of silently
changing search backends.

## Scope

### Included

- Replace import-time `RG_AVAILABLE` detection with an explicit runtime
  ripgrep-resolution helper
- Add a supported config surface for ripgrep path/availability policy
- Make built-in `grep` backend selection more explicit and deterministic for
  directory searches
- Update docs/tests so the optional fast-path contract is clear

### Deferred

- Bundling or vendoring ripgrep binaries into NEXUS distributions
- Reworking restricted/sandboxed directory search so it can safely use an
  external backend under `allowed_paths` constraints
- Python fallback regex-engine swaps
- Fuzzy path or content search

### Excluded

- Removing the Python fallback
- Making ripgrep a universal hard dependency for all installs
- Changing content-search semantics beyond backend selection and diagnostics

## Design Decisions And Rationale

### 1. Do not vendor ripgrep in this slice

Bundling `rg` would require platform-specific binary distribution,
release/build plumbing, third-party notices, and long-term update ownership.
That may still be worth doing later, but it is a packaging strategy project,
not the smallest credible fix for the current determinism problem.

### 2. Ripgrep detection should happen at runtime, not module import

The current `RG_AVAILABLE = shutil.which("rg") is not None` snapshot is too
static:

- it is harder to test cleanly
- it does not reflect environment changes after import
- it hides the actual executable path that will be used

Resolution should move behind a helper that can consult config, validate the
resolved executable, and cache results appropriately.

### 3. Availability should be explicit in config

The user should be able to say:

- where ripgrep lives (`ripgrep_path`)
- whether ambient `PATH` lookup is acceptable
- whether directory search may silently fall back to Python, or should fail
  closed when ripgrep cannot be used

The recommended minimal contract is a new top-level search config, for example:

- `search.ripgrep_path?: str`
- `search.require_ripgrep?: bool`

Exact naming can be finalized during implementation, but the policy should be
config-driven rather than hidden in ambient host state.

### 4. Default behavior should stay secure and compatible

In default/auto mode:

- if ripgrep is available and safe to use, `grep` uses it
- otherwise `grep` falls back to the current Python backend

This preserves current behavior for ordinary users while making the fast-path
contract explicit and testable.

### 5. Required-ripgrep mode should fail closed with a reason

If a user explicitly requires ripgrep, directory `grep` should not silently
drop to Python because that defeats the point of making performance/backend
selection deterministic. Failures should explain whether the reason is:

- ripgrep missing
- configured ripgrep path invalid
- current permission mode/path restrictions prevent safe external search

### 6. Backend choice should be visible in diagnostics, not buried in code

The implementation should make it easy to tell which backend was selected.
That can live in debug/logging and tool-level diagnostics rather than in noisy
default match output, but the behavior must be inspectable.

## Implementation Details

### Phase 1: config and resolution plumbing

Files:

- `nexus3/config/schema.py`
- `nexus3/config/README.md`
- new shared helper under `nexus3/core/` for external-tool resolution

Work:

- add a top-level search config model for ripgrep policy/path selection
- normalize and validate configured ripgrep paths
- introduce a shared runtime helper that:
  - resolves a configured ripgrep path if provided
  - optionally falls back to `PATH` lookup
  - reports usable/unusable status with a concrete reason

### Phase 2: `grep` backend determinism

Files:

- `nexus3/skill/builtin/grep.py`
- `tests/unit/test_skill_enhancements.py`
- `tests/unit/skill/test_grep_parallel.py`
- `tests/unit/skill/test_grep_gateway.py`
- config-focused regression tests in the existing config test suite

Work:

- remove module-level `RG_AVAILABLE` gating
- resolve ripgrep through the new helper at execution time
- preserve Python fallback in default mode
- add required-ripgrep fail-closed behavior for directory searches when
  external ripgrep is unavailable or disallowed
- make backend choice and fallback reasons inspectable in diagnostics/tests

### Phase 3: docs and operator guidance

Files:

- `README.md`
- `nexus3/defaults/NEXUS-DEFAULT.md`
- `nexus3/skill/README.md`
- `CLAUDE.md`
- `AGENTS.md`

Work:

- document ripgrep as an optional accelerator with an explicit contract
- explain how configured ripgrep interacts with permission-restricted searches
- document required-ripgrep mode and its failure behavior
- keep bundled-binary strategy explicitly deferred

## Testing Strategy

- targeted Ruff:
  - `.venv/bin/ruff check nexus3/config/schema.py nexus3/skill/builtin/grep.py tests/`
- targeted pytest:
  - config tests covering ripgrep path/policy validation
  - grep tests covering:
    - runtime resolution
    - configured path success/failure
    - default fallback behavior
    - required-ripgrep fail-closed behavior
    - restricted-search interactions
- live validation because this slice changes a built-in skill/backend contract:
  - verify an agent can still describe `grep` accurately
  - verify backend/fallback behavior is visible in the intended diagnostic
    surface

## Implementation Checklist

- [x] Add a top-level ripgrep policy/path config surface.
- [x] Replace import-time `RG_AVAILABLE` checks with runtime resolution.
- [x] Implement required-ripgrep fail-closed behavior for directory search.
- [x] Add/update regression coverage for backend selection and config-driven
      behavior.
- [x] Sync docs for the explicit ripgrep contract and deferred vendoring
      decision.

## Closeout

Completed work:

- `nexus3/config/schema.py`
  - added `SearchConfig` with `ripgrep_path` and `require_ripgrep`
- `nexus3/core/external_tools.py`
  - added shared runtime ripgrep resolution
- `nexus3/skill/builtin/grep.py`
  - removed import-time `RG_AVAILABLE`
  - resolves ripgrep at execution time
  - keeps Python fallback in default mode
  - fails closed for directory search when `require_ripgrep=true` and ripgrep
    is unavailable or disallowed by the current path-restriction model
- `nexus3/skill/services.py`
- `nexus3/session/session.py`
  - made root config available to skill runtime through `ServiceContainer`
- focused regression coverage added/updated in:
  - `tests/unit/core/test_external_tools.py`
  - `tests/unit/skill/test_grep_parallel.py`
  - `tests/unit/test_skill_enhancements.py`
  - `tests/unit/test_config.py`
  - `tests/unit/session/test_session_permission_kernelization.py`
- docs/operator guidance synced in:
  - `README.md`
  - `nexus3/defaults/NEXUS-DEFAULT.md`
  - `nexus3/skill/README.md`
  - `nexus3/config/README.md`
  - `CLAUDE.md`
  - `AGENTS.md`

## Documentation Updates

- Update `docs/plans/README.md` to index this plan.
- Update `AGENTS.md` running status to reference the plan and keep regex/fuzzy
  work deferred in backlog rather than mixing it into this slice.

## Validation

- Focused Ruff:
  - `.venv/bin/ruff check nexus3/config/schema.py nexus3/core/external_tools.py nexus3/skill/services.py nexus3/session/session.py nexus3/skill/builtin/grep.py tests/unit/core/test_external_tools.py tests/unit/skill/test_grep_parallel.py tests/unit/test_skill_enhancements.py tests/unit/test_config.py tests/unit/session/test_session_permission_kernelization.py`
- Focused pytest:
  - `.venv/bin/pytest -q tests/unit/core/test_external_tools.py tests/unit/skill/test_grep_parallel.py tests/unit/test_skill_enhancements.py tests/unit/test_config.py tests/unit/skill/test_glob_search.py tests/unit/session/test_session_permission_kernelization.py` (`105 passed, 2 warnings`)
- Repo-wide Ruff:
  - `.venv/bin/ruff check nexus3/ tests/`
- Full pytest:
  - `.venv/bin/pytest tests/ -q` (`4408 passed, 3 skipped, 22 warnings`)
- Live validation:
  - trusted RPC agent `search-check` described built-in `grep` as the
    preferred content-search tool and used built-in `grep` instead of shell
    search; response also reflected the new `search.ripgrep_path` config name
