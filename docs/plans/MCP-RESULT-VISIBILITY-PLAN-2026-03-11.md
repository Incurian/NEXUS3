# MCP Result Visibility Plan (2026-03-11)

## Overview

Improve normal REPL visibility for successful MCP tool calls by showing a
bounded inline preview of the returned data.

Today MCP tool results are not lost, but they are flattened to plain text in
`MCPSkillAdapter` and then only surfaced through the generic tool-success trace
line. That makes real MCP return payloads hard for users to see without
digging through logs or inferring results indirectly from the model's follow-up
message.

This plan adds a default-on, collapsed preview for successful `mcp_*` tool
calls in the REPL. Long results remain truncated by default so the terminal is
not flooded.

## Scope

Included:

- add default-on bounded inline preview blocks for successful `mcp_*` tool
  calls in the REPL
- keep previews sanitized and truncated by line/character limits
- avoid dumb duplication by making the normal success summary line more
  compact for MCP tools
- update focused REPL formatting tests
- update current-facing docs and running status notes

Deferred:

- on-demand full view of previous tool results
- preserving structured MCP result payloads through `ToolResult`
- rendering non-text MCP content types in a richer UI
- applying the same inline preview behavior to all native tools

Excluded:

- changes to MCP transport/client behavior
- changes to MCP permission rules
- changes to the existing `MCPSkillAdapter` text-flattening contract

## Design Decisions And Rationale

### 1. REPL-only UX slice first

Behavior:

- successful `mcp_*` tool calls show an inline preview block in the normal REPL
  tool trace
- the core tool-result model remains text-only for now

Rationale:

- the user-visible problem is mainly a display problem
- this keeps the fix low-risk and avoids a repo-wide `ToolResult` redesign

### 2. Default-on, collapsed by default

Behavior:

- no new config flag for v1
- previews are bounded by fixed line/character limits
- truncated previews explicitly say they were truncated

Rationale:

- the user asked for default-on behavior
- bounded previews preserve usability without overwhelming the terminal

### 3. MCP-only for the first pass

Behavior:

- only `mcp_*` success results get the new preview block
- existing `nexus_send` response-preview behavior stays as-is

Rationale:

- MCP was the concrete UX gap discussed
- this avoids broadening the change into a general tool-output redesign

### 4. Full-result inspection stays backlog-only

Behavior:

- no `/last_tool` or equivalent command in this slice
- the backlog should explicitly track on-demand full previous-result viewing

Rationale:

- the user asked to defer that discussion
- it likely needs command/UI/state design beyond this bounded preview change

## Implementation Details

Primary files:

- `nexus3/cli/repl.py`
- `nexus3/cli/repl_formatting.py`
- `tests/unit/cli/test_repl_safe_sink.py`

Supporting docs:

- `README.md`
- `nexus3/defaults/NEXUS-DEFAULT.md`
- `nexus3/cli/README.md`
- `nexus3/mcp/README.md`
- `CLAUDE.md`
- `AGENTS.md`
- `docs/plans/README.md`

Planned behavior details:

- use the existing `on_batch_progress(...)` REPL callback as the insertion point
- keep the normal success line, but summarize MCP output as line/size metadata
  instead of echoing the first line
- print a sanitized preview block immediately after that line for successful
  `mcp_*` results
- bound preview output by a fixed number of lines and characters

## Testing Strategy

Focused coverage should confirm:

- preview blocks are sanitized correctly
- preview blocks truncate deterministically
- MCP tool success summaries no longer duplicate the first output line

Validation:

- focused `ruff`
- focused pytest for REPL formatting helpers
- a live local MCP check if practical, using the existing test MCP server

## Documentation Updates

- describe the new default-on bounded MCP preview behavior in current-facing
  docs
- record the later backlog item for on-demand full previous tool-result viewing

## Checklist

- [x] Add and index the plan doc.
- [x] Add default-on bounded MCP preview rendering in the REPL.
- [x] Add focused regression coverage for sanitization/truncation.
- [x] Sync current-facing docs and running-status notes.
- [x] Run focused validation and a practical live check.

Validation completed:

- `.venv/bin/ruff check nexus3/cli/repl.py nexus3/cli/repl_formatting.py tests/unit/cli/test_repl_safe_sink.py README.md CLAUDE.md nexus3/defaults/NEXUS-DEFAULT.md nexus3/cli/README.md nexus3/mcp/README.md docs/plans/README.md docs/plans/MCP-RESULT-VISIBILITY-PLAN-2026-03-11.md AGENTS.md`
- `.venv/bin/mypy nexus3/cli/repl.py nexus3/cli/repl_formatting.py`
- `.venv/bin/pytest -q tests/unit/cli/test_repl_safe_sink.py tests/integration/test_mcp_client.py -k 'test_skill_execute or test_call_echo'` (`2 passed, 67 deselected`)
- unsandboxed local MCP subprocess harness connected `nexus3.mcp.test_server`,
  executed a real `mcp_test_echo` call, and produced the expected summary line
  plus bounded inline preview block
- partial unsandboxed live REPL check:
  - `/mcp connect test --allow-all --private` succeeded and exposed the test
    tools in a fresh session
  - the follow-up provider turn stalled before issuing a tool call, so full
    model-loop preview rendering could not be observed through the live REPL in
    that environment
