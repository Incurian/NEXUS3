# REPL Tool Result Preview Standardization Plan (2026-03-12)

## Overview

Standardize successful REPL tool-result rendering around the bounded inline
preview block that was originally added only for `mcp_*` tools.

The target state is that successful tools with visible output all render with
the same shape:

- a compact success summary line
- a bounded, sanitized inline preview block
- explicit truncation when the preview is clipped

## Scope

Included:

- replace the MCP-only preview block with a generic successful-tool preview
  block in the REPL
- keep `nexus_send` readable by previewing parsed response content instead of
  raw JSON when possible
- make the success summary line compact and non-duplicative alongside the new
  preview block
- update focused REPL formatting tests
- update current-facing docs and running-status notes

Deferred:

- configurable preview limits
- richer structured previews for JSON, diffs, or non-text tool payloads
- changing persisted tool-record storage or `/tool` retrieval behavior

Excluded:

- tool execution/runtime changes
- error-path rendering redesign
- trace viewer formatting changes

## Design Decisions And Rationale

### 1. Reuse one preview pattern for all successful tools

Behavior:

- successful tools with visible output render a shared `Result preview` block
- `mcp_*` results no longer use a special label or code path

Rationale:

- the user explicitly prefers the MCP preview shape as the general REPL result
  pattern
- one code path is easier to keep consistent than a growing list of
  tool-specific display exceptions

### 2. Keep `nexus_send` semantically readable

Behavior:

- `nexus_send` keeps a structured preview, but it now uses the same block
  layout as other tools
- when the tool result contains a `content` field, that human-visible content
  becomes the preview body instead of the raw transport JSON

Rationale:

- showing raw `nexus_send` JSON would technically be “standardized,” but it is
  materially worse than the current response preview
- this preserves useful semantics while still converging on one visual shape

### 3. Summary line becomes metadata-focused

Behavior:

- the success line summarizes output as `N line(s)` plus size when large
- the actual content lives in the preview block

Rationale:

- the previous “echo the first line” summary becomes redundant once every tool
  also shows a preview block
- compact metadata avoids content duplication and keeps the top success line
  easy to scan

## Implementation Details

Primary files:

- `nexus3/cli/repl.py`
- `nexus3/cli/repl_formatting.py`
- `tests/unit/cli/test_repl_safe_sink.py`

Supporting docs:

- `README.md`
- `nexus3/cli/README.md`
- `nexus3/defaults/NEXUS-DEFAULT.md`
- `nexus3/mcp/README.md`
- `CLAUDE.md`
- `AGENTS.md`
- `docs/plans/README.md`

Planned behavior details:

- replace `_format_mcp_result_preview_lines(...)` with a generic tool-result
  preview formatter
- select preview payloads centrally in the REPL callback layer so tool-specific
  exceptions stay narrow
- print preview blocks for successful tools immediately after the normal
  success summary line
- keep preview limits fixed and deterministic for this slice

## Testing Strategy

Focused coverage should confirm:

- generic preview blocks sanitize and truncate correctly
- custom preview labels still use the same block shape
- `nexus_send` selects parsed response content for preview when available
- success summaries no longer depend on MCP-specific logic

Validation:

- focused `ruff`
- focused `mypy`
- focused `pytest` for REPL formatting helpers

## Documentation Updates

- replace MCP-specific preview wording with all-tools wording in current-facing
  docs
- note the new local milestone in `AGENTS.md`

## Checklist

- [x] Add and index the plan doc.
- [x] Replace MCP-only preview rendering with a generic successful-tool
  preview path.
- [x] Keep `nexus_send` readable while adopting the standard preview block.
- [x] Update focused docs and running-status notes.
- [x] Run focused validation.

Validation completed:

- `.venv/bin/pytest -q tests/unit/cli/test_repl_safe_sink.py` (`37 passed`)
- `.venv/bin/ruff check nexus3/cli/repl.py nexus3/cli/repl_formatting.py tests/unit/cli/test_repl_safe_sink.py README.md nexus3/cli/README.md nexus3/defaults/NEXUS-DEFAULT.md nexus3/mcp/README.md CLAUDE.md AGENTS.md docs/plans/README.md docs/plans/REPL-TOOL-RESULT-PREVIEW-STANDARDIZATION-PLAN-2026-03-12.md`
- `.venv/bin/mypy nexus3/cli/repl.py nexus3/cli/repl_formatting.py`
- `git diff --check`
