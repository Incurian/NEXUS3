# Plan E: Context Compiler and Graph Model (2026-03-02)

## Overview

Introduce an invariant-enforcing context compiler first, then evolve to a graph-backed context model to reduce duplication and prevent malformed message sequences.

## Scope

Included:
- Add compiled conversation IR with invariant checks.
- Route providers through compiler output.
- Add graph model phase after compiler parity is established.

Deferred:
- Full replacement of existing context manager internals until parity proven.

Excluded:
- New prompt strategy features unrelated to invariants.

## Design Decisions and Rationale

1. Start with compiler layer to capture value without immediate full graph migration.
2. Enforce tool-call/result pairing and role sequence invariants centrally.
3. Keep provider-specific formatting as output adapters on a shared compiled model.

## Implementation Details

Primary files to change:
- [context/manager.py](/home/inc/repos/NEXUS3/nexus3/context/manager.py)
- [context/compaction.py](/home/inc/repos/NEXUS3/nexus3/context/compaction.py)
- [session/session.py](/home/inc/repos/NEXUS3/nexus3/session/session.py)
- [provider/openai_compat.py](/home/inc/repos/NEXUS3/nexus3/provider/openai_compat.py)
- [provider/anthropic.py](/home/inc/repos/NEXUS3/nexus3/provider/anthropic.py)
- [core/types.py](/home/inc/repos/NEXUS3/nexus3/core/types.py)
- New: `nexus3/context/compiler.py`
- Later new: `nexus3/context/graph.py`

Phases:
1. Build compiler IR and invariants over existing message list.
2. Route both providers through compiler output with parity tests, and migrate `Session` preflight repair logic to compiler-backed invariants.
3. Introduce optional graph representation for provenance/compaction edges.
4. Switch compaction/truncation to graph-aware compilation.

## Testing Strategy

- Provider parity tests for identical transcript inputs.
- Property tests for no orphan tool results and valid role order.
- Compaction/truncation equivalence tests before and after graph phase.
- Preflight/request payload parity tests and migration tests removing provider-local orphan synthesis logic.

## Implementation Checklist

- [x] Add compiler IR and invariant checker.
- [x] Integrate with provider adapters.
- [x] Migrate session preflight pipeline to compiler-backed invariants.
- [x] Add graph model prototype.
- [x] Migrate compaction/truncation through compiler pipeline.

Status note (2026-03-05, M3 Plan E Phase 1):
- Added `nexus3/context/compiler.py` with typed compiler IR and invariant
  checker:
  - `CompiledContextIR`, `ToolBatchIR`, `CompileDiagnostics`,
    `InvariantReport`, and `InvariantViolation` models
  - deterministic repair pipeline entrypoint
    `compile_context_messages(...)` (with compatibility alias
    `compile_message_sequence(...)`)
  - centralized invariant check helpers
    `check_context_invariants(...)` and
    `validate_compiled_message_invariants(...)`
- Exported compiler interfaces from `nexus3/context/__init__.py`.
- Added focused compiler regressions in
  `tests/unit/context/test_compiler.py` (fixture parity + diagnostics +
  invariant reporting + repairs-disabled behavior).
- Focused validation passed:
  - `.venv/bin/pytest -q tests/unit/context/test_compiler.py tests/unit/context/test_compile_baseline.py` -> `8 passed`
  - `.venv/bin/ruff check nexus3/context/compiler.py nexus3/context/__init__.py tests/unit/context/test_compiler.py`
  - `.venv/bin/mypy nexus3/context/compiler.py nexus3/context/__init__.py`

Status note (2026-03-05, M3 Plan E Phase 2, committed as `e3cd304`):
- Session preflight repair is now compiler-backed:
  - `nexus3/session/session.py` normalizes persisted context through
    `compile_context_messages(...)` before appending each new user turn.
  - `nexus3/context/manager.py` adds `replace_messages(...)` for exact
    replacement of repaired history.
- Provider request shaping now compiles message sequences first:
  - `nexus3/provider/openai_compat.py::_build_request_body(...)`
  - `nexus3/provider/anthropic.py::_build_request_body(...)`
- Anthropic-local orphan synthesis was retired:
  - `_convert_messages(...)` no longer synthesizes missing tool results.
  - shared compiler repair now owns missing-result synthesis.
- Focused regression coverage added/updated:
  - `tests/unit/session/test_session_cancellation.py`
  - `tests/unit/provider/test_compiler_integration.py`
- Focused validation passed:
  - `.venv/bin/ruff check nexus3/session/session.py nexus3/context/manager.py nexus3/provider/anthropic.py nexus3/provider/openai_compat.py tests/unit/session/test_session_cancellation.py tests/unit/provider/test_compiler_integration.py`
  - `.venv/bin/mypy nexus3/session/session.py nexus3/context/manager.py nexus3/provider/anthropic.py nexus3/provider/openai_compat.py`
  - `.venv/bin/pytest -q tests/unit/session/test_session_cancellation.py tests/unit/provider/test_compiler_integration.py tests/unit/provider/test_prompt_caching.py` -> `36 passed`

Status note (2026-03-05, Plan E Phase 3, committed as `5632652`):
- Added graph prototype module `nexus3/context/graph.py`:
  - typed graph nodes/edges (`ContextGraph`, `ContextGraphEdge`,
    `GraphEdgeKind`) over compiler-normalized messages
  - tool-batch-aware atomic grouping model (`ContextMessageGroup`) for
    future truncation/compaction migration
  - query helpers (`incoming(...)`, `outgoing(...)`) for edge traversal
- Exported graph interfaces in `nexus3/context/__init__.py`.
- Added focused graph regressions in `tests/unit/context/test_graph.py`.
- Updated `nexus3/context/README.md` architecture docs for compiler+graph.
- Focused validation passed:
  - `.venv/bin/ruff check nexus3/context/graph.py nexus3/context/__init__.py nexus3/context/README.md tests/unit/context/test_graph.py`
  - `.venv/bin/mypy nexus3/context/graph.py nexus3/context/__init__.py`
  - `.venv/bin/pytest -q tests/unit/context/test_graph.py tests/unit/context/test_compiler.py tests/unit/context/test_compile_baseline.py` -> `12 passed`
  - `.venv/bin/pytest -q tests/unit/test_context_manager.py` -> `27 passed`

Status note (2026-03-05, Plan E Phase 4, committed as `00c59ed`):
- Migrated truncation and compaction selection through compiler/graph pipeline:
  - `nexus3/context/manager.py::_identify_message_groups(...)` now builds
    groups from `build_context_graph(...)` and persists normalized messages
    before truncation grouping.
  - `nexus3/context/compaction.py::select_messages_for_compaction(...)`
    now selects from compiler-normalized atomic groups instead of raw
    per-message slicing.
- Added focused regressions for graph-backed group behavior:
  - `tests/unit/test_compaction.py`:
    - preserves assistant tool batches atomically
    - verifies compiler repair is applied before compaction selection
  - `tests/unit/test_context_manager.py`:
    - validates truncation path normalizes orphan TOOL messages
- Focused validation passed:
  - `.venv/bin/ruff check nexus3/context/manager.py nexus3/context/compaction.py tests/unit/test_context_manager.py tests/unit/test_compaction.py`
  - `.venv/bin/mypy nexus3/context/manager.py nexus3/context/compaction.py nexus3/context/graph.py nexus3/context/__init__.py`
  - `.venv/bin/pytest -q tests/unit/test_context_manager.py tests/unit/test_compaction.py tests/unit/context/test_graph.py tests/unit/context/test_compiler.py tests/unit/context/test_compile_baseline.py` -> `75 passed`

## Documentation Updates

- Update context README with compiler/graph architecture.
- Remove stale docs about previous linear-only assumptions.

## Related Documents

- [Reviews Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- [Plans Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/plans/README.md)
- [Canonical Review Master Final](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- [Architecture Investigation](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- [Architecture Milestone Schedule](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
