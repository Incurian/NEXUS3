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
- 2026-03-05: Phase 3 incremental migration slice completed (connect/lobby prompts).
- Migrated high-volume dynamic CLI rendering in `nexus3/cli/connect_lobby.py` and `nexus3/cli/lobby.py` to sanitize untrusted interpolated fields through `SafeSink` while preserving trusted static Rich markup.
- Added focused regressions in `tests/unit/cli/test_connect_lobby_safe_sink.py` and `tests/unit/cli/test_lobby_safe_sink.py`.
- Validation: `.venv/bin/ruff check nexus3/cli/connect_lobby.py nexus3/cli/lobby.py tests/unit/cli/test_connect_lobby_safe_sink.py tests/unit/cli/test_lobby_safe_sink.py` and `.venv/bin/pytest -v tests/unit/cli/test_connect_lobby_safe_sink.py tests/unit/cli/test_lobby_safe_sink.py tests/unit/test_lobby.py` passed.
- 2026-03-05: Phase 3 incremental migration slice completed (confirmation UI prompts).
- Migrated `nexus3/cli/confirmation_ui.py::confirm_tool_action` dynamic fields to `SafeSink` sanitization for MCP/exec/nexus/general tool prompts while preserving trusted Rich markup labels.
- Removed redundant ad hoc per-branch escaping variables in this path in favor of the sink boundary contract.
- Added focused regressions in `tests/unit/cli/test_confirmation_ui_safe_sink.py`.
- Validation: `.venv/bin/ruff check nexus3/cli/confirmation_ui.py tests/unit/cli/test_confirmation_ui_safe_sink.py` and `.venv/bin/pytest -v tests/unit/cli/test_confirmation_ui_safe_sink.py` passed.
- 2026-03-05: Phase 3 incremental migration slice completed (InlinePrinter dynamic rendering).
- Migrated high-frequency dynamic output paths in `nexus3/display/printer.py` (`print_task_start`, `print_task_end`, `print_error`, `print_cancelled`, expanded `print_thinking`) to sanitize untrusted fields via `SafeSink`.
- Preserved trusted markup wrappers (gumball/thinking formatting) while removing direct unsanitized interpolation in this path.
- Added focused regressions in `tests/unit/display/test_escape_sanitization.py`.
- Validation: `.venv/bin/ruff check nexus3/display/printer.py tests/unit/display/test_escape_sanitization.py` and `.venv/bin/pytest -v tests/unit/display/test_escape_sanitization.py tests/unit/display/test_safe_sink.py` passed.
- 2026-03-05: Phase 3 incremental migration slice completed (`repl.py` tool trace lines).
- Migrated dynamic spinner tool-trace output in `nexus3/cli/repl.py` (`on_tool_active`, `on_batch_progress`, `on_batch_halt`, and `nexus_send` response preview trace) to SafeSink-backed sanitization while preserving trusted Rich wrappers.
- Added focused regressions in `tests/unit/cli/test_repl_safe_sink.py`.
- Validation: `.venv/bin/ruff check nexus3/cli/repl.py tests/unit/cli/test_repl_safe_sink.py` and `.venv/bin/pytest -v tests/unit/cli/test_repl_safe_sink.py` passed.
- 2026-03-05: Phase 3 incremental migration slice completed (`repl.py` incoming notification preview lines).
- Migrated incoming notification output in `nexus3/cli/repl.py` (incoming start lines and response-sent end line) to SafeSink-backed sanitization while preserving existing truncation/ellipsis routing behavior and trusted Rich wrappers.
- Extended focused regressions in `tests/unit/cli/test_repl_safe_sink.py`.
- Validation: `.venv/bin/ruff check nexus3/cli/repl.py tests/unit/cli/test_repl_safe_sink.py` and `.venv/bin/pytest -v tests/unit/cli/test_repl_safe_sink.py` passed.
- 2026-03-05: Phase 3 incremental migration slice completed (`repl.py` post-turn status/error lines).
- Migrated post-turn dynamic status output in `nexus3/cli/repl.py` (cancel reason, turn duration, stream error text, auto-save error text) to SafeSink-backed sanitization while preserving existing wrappers/wording.
- Extended focused regressions in `tests/unit/cli/test_repl_safe_sink.py`.
- Validation: `.venv/bin/ruff check nexus3/cli/repl.py tests/unit/cli/test_repl_safe_sink.py` and `.venv/bin/pytest -v tests/unit/cli/test_repl_safe_sink.py` passed.
- 2026-03-05: Phase 3 incremental migration slice completed (`repl.py` startup metadata/status lines).
- Migrated startup/session metadata and embedded RPC status output in `nexus3/cli/repl.py` (agent/session/server/context metadata + embedded RPC listening/server-log lines) to SafeSink-backed sanitization while preserving existing wrappers/wording.
- Extended focused regressions in `tests/unit/cli/test_repl_safe_sink.py`.
- Validation: `.venv/bin/ruff check nexus3/cli/repl.py tests/unit/cli/test_repl_safe_sink.py` and `.venv/bin/pytest -v tests/unit/cli/test_repl_safe_sink.py` passed.
- 2026-03-05: Phase 3 incremental migration slice completed (`repl.py` remaining dynamic client/discovery/status surfaces).
- Migrated remaining high-value dynamic lines in `nexus3/cli/repl.py` across `run_repl`, `run_repl_client`, and `_run_connect_with_discovery` to SafeSink-backed sanitization (created-agent lines, shutdown warnings, invalid-port/spec errors, provider/init/connect errors, client metadata/status lines, and command output message rendering).
- Extended focused regressions in `tests/unit/cli/test_repl_safe_sink.py` to cover the new formatter helpers and dynamic field sanitization behavior.
- Validation: `.venv/bin/ruff check nexus3/cli/repl.py tests/unit/cli/test_repl_safe_sink.py` and `.venv/bin/pytest -v tests/unit/cli/test_repl_safe_sink.py` passed.
- 2026-03-05: Phase 3 incremental migration slice completed (top-level REPL/serve residual dynamic surfaces).
- Migrated residual dynamic output in `nexus3/cli/repl.py` (`main`, `_run_with_reload`) and `nexus3/cli/serve.py` (`run_serve`) to SafeSink-backed sanitization helpers while preserving startup/error wording and flow.
- Added focused `serve` sanitization regressions in `tests/unit/cli/test_serve_safe_sink.py` and extended `tests/unit/cli/test_repl_safe_sink.py` for top-level REPL reload/command formatting paths.
- Validation: `.venv/bin/ruff check nexus3/cli/repl.py nexus3/cli/serve.py tests/unit/cli/test_repl_safe_sink.py tests/unit/cli/test_serve_safe_sink.py` and `.venv/bin/pytest -v tests/unit/cli/test_repl_safe_sink.py tests/unit/cli/test_serve_safe_sink.py` passed.
- 2026-03-05: Phase 3 cleanup slice completed (SafeSink helper dedup).
- Added shared `SafeSink.sanitize_print_value(...)` entrypoint and removed duplicated local sanitization wrappers in `nexus3/cli/serve.py` and `nexus3/mcp/error_formatter.py`.
- Added focused helper coverage in `tests/unit/display/test_safe_sink.py` and validated existing `serve` + MCP formatting regressions remain green.
- Validation: `.venv/bin/ruff check nexus3/display/safe_sink.py nexus3/cli/serve.py nexus3/mcp/error_formatter.py tests/unit/display/test_safe_sink.py tests/unit/cli/test_serve_safe_sink.py tests/unit/mcp/test_error_formatter.py` and `.venv/bin/pytest -v tests/unit/display/test_safe_sink.py tests/unit/cli/test_serve_safe_sink.py tests/unit/mcp/test_error_formatter.py` passed.
- 2026-03-06: Phase 3 cleanup slice completed (MCP skill adapter sink consolidation).
- Migrated `nexus3/mcp/skill_adapter.py` dynamic tool result sanitization from direct core helper usage to shared `SafeSink` sanitizer entrypoint to reduce fragmented boundary patterns.
- Added focused adapter sanitization regressions in `tests/unit/mcp/test_skill_adapter.py` for success/error payload escaping (ANSI + Rich markup).
- Validation: `.venv/bin/ruff check nexus3/mcp/skill_adapter.py tests/unit/mcp/test_skill_adapter.py`, `.venv/bin/mypy nexus3/mcp/skill_adapter.py`, and `.venv/bin/pytest -v tests/unit/mcp/test_skill_adapter.py` passed.
- 2026-03-06: Phase 3 cleanup slice completed (display streaming/spinner sink consolidation).
- Migrated `nexus3/display/spinner.py` and `nexus3/display/streaming.py` untrusted chunk/error-preview sanitization to shared `SafeSink` sanitizer entrypoints.
- Added focused display regressions in `tests/unit/display/test_escape_sanitization.py` for spinner streaming chunk sanitization and streaming tool error preview sanitization.
- Validation: `.venv/bin/ruff check nexus3/display/spinner.py nexus3/display/streaming.py tests/unit/display/test_escape_sanitization.py`, `.venv/bin/mypy nexus3/display/spinner.py nexus3/display/streaming.py`, and `.venv/bin/pytest -v tests/unit/display/test_escape_sanitization.py tests/unit/display/test_safe_sink.py` passed.
- 2026-03-06: Phase 3 cleanup slice completed (REPL plain output sink hardening).
- Replaced direct unsanitized plain command-output rendering in `nexus3/cli/repl.py` (`console.print(output.message)`) with `SafeSink`-backed formatting helper.
- Added focused regression in `tests/unit/cli/test_repl_safe_sink.py` for plain-message sanitization behavior.
- Validation: `.venv/bin/ruff check nexus3/cli/repl.py tests/unit/cli/test_repl_safe_sink.py`, `.venv/bin/mypy nexus3/cli/repl.py`, and `.venv/bin/pytest -v tests/unit/cli/test_repl_safe_sink.py` passed.
- 2026-03-06: Phase 3 cleanup slice completed (REPL dynamic f-string print consistency).
- Replaced remaining dynamic direct f-string prints in `nexus3/cli/repl.py` for scanning-additional-ports, startup-timeout port output, and thought-duration spinner output with SafeSink-backed helper formatters.
- Added focused regressions in `tests/unit/cli/test_repl_safe_sink.py` for the new formatter helpers.
- Validation: `.venv/bin/ruff check nexus3/cli/repl.py tests/unit/cli/test_repl_safe_sink.py`, `.venv/bin/mypy nexus3/cli/repl.py`, and `.venv/bin/pytest -v tests/unit/cli/test_repl_safe_sink.py` passed.
- 2026-03-05: Phase 3 follow-up cleanup slice completed (residual SafeSink boundaries).
- Hardened `nexus3/display/streaming.py` sink boundaries by sanitizing dynamic tool metadata at render time (tool name, params, and active batch tool name).
- Replaced remaining command-result dynamic f-string `console.print` paths in `nexus3/cli/repl.py` with SafeSink-backed formatter helpers while preserving existing user-visible wording/wrappers.
- Consolidated remaining `escape_rich_markup` formatting branches in `nexus3/cli/confirmation_ui.py::format_tool_params` onto shared `SafeSink.sanitize_print_value(...)`, including sanitize-before-truncate sequencing for safer preview formatting.
- Added focused regressions in `tests/unit/display/test_escape_sanitization.py`, `tests/unit/cli/test_repl_safe_sink.py`, and `tests/unit/cli/test_confirmation_ui_safe_sink.py`.
- Validation: `.venv/bin/ruff check nexus3/display/streaming.py nexus3/cli/repl.py nexus3/cli/confirmation_ui.py tests/unit/display/test_escape_sanitization.py tests/unit/cli/test_repl_safe_sink.py tests/unit/cli/test_confirmation_ui_safe_sink.py`, `.venv/bin/mypy nexus3/display/streaming.py nexus3/cli/repl.py nexus3/cli/confirmation_ui.py`, and `.venv/bin/pytest -v tests/unit/display/test_escape_sanitization.py tests/unit/cli/test_repl_safe_sink.py tests/unit/cli/test_confirmation_ui_safe_sink.py` passed.
- 2026-03-05: Phase 3 closure slice completed (toolbar/prompt HTML + confirmation full-details).
- Hardened prompt-toolkit HTML rendering in `nexus3/cli/repl.py` toolbar and prompt paths by sanitizing dynamic fields through `_sanitize_prompt_html_text(...)` before `HTML(...)` interpolation.
- Hardened `nexus3/cli/confirmation_ui.py::_format_full_tool_details` and `_show_tool_details` by sanitizing tool/id/path/argument details with stream-safe sanitization before external pager/editor rendering.
- Added focused regressions in `tests/unit/cli/test_repl_safe_sink.py` and `tests/unit/cli/test_confirmation_ui_safe_sink.py`.
- Validation: `.venv/bin/ruff check nexus3/display/streaming.py nexus3/cli/repl.py nexus3/cli/confirmation_ui.py tests/unit/display/test_escape_sanitization.py tests/unit/cli/test_repl_safe_sink.py tests/unit/cli/test_confirmation_ui_safe_sink.py`, `.venv/bin/mypy nexus3/display/streaming.py nexus3/cli/repl.py nexus3/cli/confirmation_ui.py`, and `.venv/bin/pytest -v tests/unit/display/test_escape_sanitization.py tests/unit/cli/test_repl_safe_sink.py tests/unit/cli/test_confirmation_ui_safe_sink.py` passed (`74 passed`).

## Testing Strategy

- Extend escape-injection security tests across all sink entrypoints.
- Snapshot tests for expected visible output with malicious payload fixtures.
- Ensure legitimate trusted formatting remains intact.

## Implementation Checklist

- [x] Add safe sink abstraction.
- [x] Migrate high-risk output paths.
- [x] Migrate all remaining print/stream paths.
  - [x] Migrated `InlinePrinter` dynamic render path to `SafeSink` sanitization.
  - [x] Migrated `nexus3/cli/repl.py` tool-trace spinner output path to `SafeSink` sanitization.
  - [x] Migrated `nexus3/cli/repl.py` incoming notification preview path to `SafeSink` sanitization.
  - [x] Migrated `nexus3/cli/repl.py` post-turn status/error dynamic lines to `SafeSink` sanitization.
  - [x] Migrated `nexus3/cli/repl.py` startup metadata/status dynamic lines to `SafeSink` sanitization.
  - [x] Migrated `nexus3/cli/repl.py` remaining dynamic `run_repl`/`run_repl_client`/`_run_connect_with_discovery` status and error interpolation paths to SafeSink sanitization helpers.
  - [x] Migrated residual dynamic top-level REPL/serve startup-reload surfaces (`nexus3/cli/repl.py::main`, `nexus3/cli/repl.py::_run_with_reload`, `nexus3/cli/serve.py::run_serve`) to SafeSink sanitization helpers.
- [x] Remove redundant/fragmented sanitization call sites.
  - [x] Removed redundant ad hoc escaping in `nexus3/cli/confirmation_ui.py::confirm_tool_action` during SafeSink migration.
  - [x] Collapsed duplicate sanitize-wrapper branches in `nexus3/cli/serve.py` and `nexus3/mcp/error_formatter.py` onto shared `SafeSink.sanitize_print_value(...)`.
  - [x] Consolidated MCP skill adapter result sanitization in `nexus3/mcp/skill_adapter.py` to `SafeSink` shared sanitizer entrypoint.
  - [x] Consolidated display streaming/spinner sanitizer branches in `nexus3/display/spinner.py` and `nexus3/display/streaming.py` to `SafeSink` shared sanitizer entrypoints.
  - [x] Removed remaining unsanitized plain command-output render path in `nexus3/cli/repl.py` by routing through SafeSink helper formatting.
  - [x] Replaced remaining dynamic direct f-string prints in `nexus3/cli/repl.py` with SafeSink-backed helper formatters for consistency.
  - [x] Hardened prompt-toolkit toolbar/prompt HTML dynamic interpolation in `nexus3/cli/repl.py` via `_sanitize_prompt_html_text(...)`.
  - [x] Sanitized confirmation full-details viewer content/title in `nexus3/cli/confirmation_ui.py` before pager/editor display.

## Documentation Updates

- Update display/CLI docs describing trusted vs untrusted output contract.

## Related Documents

- [Reviews Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- [Plans Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/plans/README.md)
- [Canonical Review Master Final](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- [Architecture Investigation](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- [Architecture Milestone Schedule](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
