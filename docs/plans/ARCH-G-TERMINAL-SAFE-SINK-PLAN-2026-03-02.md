# Plan G: Terminal Safe Sink Boundary (2026-03-02)

## Overview

Create a single output sink abstraction that guarantees untrusted text is sanitized before terminal rendering.

## Scope

Included:
- Define trusted vs untrusted output APIs.
- Route REPL/client/MCP output through sink.
- Normalize handling of ANSI/OSC/CSI/CR unsafe sequences.

Deferred:
- UI styling improvements unrelated to safety.

Excluded:
- Redesign of terminal presentation model.

## Design Decisions and Rationale

1. Sanitize at sink boundary, not ad hoc at call sites.
2. Preserve trusted formatting explicitly while defaulting dynamic text to untrusted.
3. Keep behavior consistent across REPL, streaming display, and client commands.

## Implementation Details

Primary files to change:
- [core/text_safety.py](/home/inc/repos/NEXUS3/nexus3/core/text_safety.py)
- [display/printer.py](/home/inc/repos/NEXUS3/nexus3/display/printer.py)
- [display/spinner.py](/home/inc/repos/NEXUS3/nexus3/display/spinner.py)
- [display/streaming.py](/home/inc/repos/NEXUS3/nexus3/display/streaming.py)
- [cli/repl.py](/home/inc/repos/NEXUS3/nexus3/cli/repl.py)
- [cli/lobby.py](/home/inc/repos/NEXUS3/nexus3/cli/lobby.py)
- [cli/connect_lobby.py](/home/inc/repos/NEXUS3/nexus3/cli/connect_lobby.py)
- [cli/repl_commands.py](/home/inc/repos/NEXUS3/nexus3/cli/repl_commands.py)
- [cli/confirmation_ui.py](/home/inc/repos/NEXUS3/nexus3/cli/confirmation_ui.py)
- [cli/client_commands.py](/home/inc/repos/NEXUS3/nexus3/cli/client_commands.py)
- [mcp/error_formatter.py](/home/inc/repos/NEXUS3/nexus3/mcp/error_formatter.py)
- New: `nexus3/display/safe_sink.py`

Phases:
1. Add sink API (`print_trusted`, `print_untrusted`).
2. Migrate high-risk paths (MCP errors, client stderr, REPL tool traces).
3. Migrate remaining display calls to sink and remove duplicate sanitization branches.
4. Validate terminal behavior across supported output modes.

## Execution Status

- 2026-03-04: Phase 1 foundation completed.
- Added `nexus3/display/safe_sink.py` with explicit trusted/untrusted print and stream APIs using existing `text_safety` primitives.
- Integrated minimally into `InlinePrinter` (trusted `print`, untrusted streaming chunk sink) without broad call-site migration.
- Added focused unit tests for sink sanitization contract under `tests/unit/display/test_safe_sink.py`.
- 2026-03-04: Phase 2 high-risk migration slice completed.
- Migrated `nexus3/cli/client_commands.py` stderr paths (`_print_error`, `_print_info`) to `SafeSink` trusted/untrusted stream writes.
- Hardened `nexus3/mcp/error_formatter.py` dynamic-field rendering through `SafeSink` print sanitization contract for server/context/command/stderr/raw preview interpolation.
- Added focused regression tests in `tests/unit/cli/test_client_commands_safe_sink.py` and extended `tests/unit/mcp/test_error_formatter.py` sanitization coverage.
- Validation: targeted `ruff` and targeted `pytest` suites passed.
- 2026-03-05: Phase 3 incremental migration slice completed.
- Migrated `nexus3/cli/repl_commands.py::_mcp_connection_consent` dynamic `server_name` and `tool_names` rendering to `SafeSink` sanitization before Rich-markup output.
- Added focused regression tests in `tests/unit/cli/test_repl_commands_safe_sink.py`.
- Validation: `.venv/bin/ruff check nexus3/cli/repl_commands.py tests/unit/cli/test_repl_commands_safe_sink.py` and `.venv/bin/pytest -v tests/unit/cli/test_repl_commands_safe_sink.py tests/unit/test_repl_commands.py` passed.

## Testing Strategy

- Extend escape-injection security tests across all sink entrypoints.
- Snapshot tests for expected visible output with malicious payload fixtures.
- Ensure legitimate trusted formatting remains intact.

## Implementation Checklist

- [x] Add safe sink abstraction.
- [x] Migrate high-risk output paths.
- [ ] Migrate all remaining print/stream paths.
- [ ] Remove redundant/fragmented sanitization call sites.

## Documentation Updates

- Update display/CLI docs describing trusted vs untrusted output contract.

## Related Documents

- [Reviews Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- [Plans Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/plans/README.md)
- [Canonical Review Master Final](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- [Architecture Investigation](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- [Architecture Milestone Schedule](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
