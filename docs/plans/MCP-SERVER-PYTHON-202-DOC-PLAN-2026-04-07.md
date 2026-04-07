# MCP Server Python 202 Doc Plan (2026-04-07)

## Overview

Add a follow-on guide for MCP server authors who already understand the basic
tools-only path and want to expose additional MCP capabilities in Python.

The 101 guide covers stdio and HTTP transports plus the minimal tools-only
surface that NEXUS3 needs for the first successful integration. The 202 guide
should explain the next layer:

- resources
- prompts
- how those surfaces differ from tools inside NEXUS3

## Scope

Included:

- add a durable follow-on guide for Python MCP server capabilities beyond tools
- explain what resources and prompts are in practical NEXUS3 terms
- explain how NEXUS3 surfaces each MCP capability today
- include a full working Python server example that exposes:
  - tools
  - resources
  - prompts
- show the required MCP methods for those capabilities
- show how to inspect the surfaces from NEXUS3
- explain when to wrap resources/prompts with a tool for agent use

Deferred:

- pagination, progress notifications, and advanced streaming examples
- structured content, image content, and binary resource walkthroughs
- session-aware HTTP servers with explicit `mcp-session-id` handling

Excluded:

- changes to MCP runtime behavior
- automatic adaptation of MCP resources/prompts into callable NEXUS tools

## Design Decisions And Rationale

### 1. Center the guide on NEXUS behavior, not only generic MCP

The guide should explicitly distinguish:

- tools -> adapted into callable NEXUS tools
- resources -> discoverable/readable MCP content surface
- prompts -> discoverable/fetchable MCP prompt-template surface

Rationale:

- this is the practical distinction NEXUS users care about when deciding what
  kind of server interface to expose

### 2. Use one full combined server example

The 202 guide should use one self-contained Python example that exposes all
three MCP capability families in one place.

Rationale:

- this avoids repeating transport boilerplate
- it makes the method mapping obvious:
  - `tools/list` / `tools/call`
  - `resources/list` / `resources/read`
  - `prompts/list` / `prompts/get`

### 3. Keep transport discussion light

The 202 guide should treat capabilities as transport-independent and point back
to the 101 guide for the stdio vs HTTP transport setup.

Rationale:

- the main new concept here is capability surface, not transport wiring

## Implementation Details

Primary files:

- `docs/references/MCP-SERVER-PYTHON-202.md`
- `docs/references/MCP-SERVER-PYTHON-101.md`

Supporting docs:

- `README.md`
- `nexus3/mcp/README.md`
- `nexus3/mcp/test_server/README.md`
- `docs/plans/README.md`
- `AGENTS.md`
- `CLAUDE.md`

## Testing Strategy

Validation should confirm:

- the new guide matches current NEXUS MCP behavior
- 101 and 202 cross-reference each other cleanly
- touched markdown passes `git diff --check`

## Documentation Updates

- add and index this plan
- add the 202 guide under `docs/references/`
- update the 101 guide to clarify that only tools become callable NEXUS tools
- link 202 from the MCP docs and from the 101 guide
- update `AGENTS.md` current handoff

## Implementation Checklist

- [x] Confirm current NEXUS behavior for tools vs resources vs prompts.
- [x] Record the doc plan.
- [x] Add the 202 guide with a full combined Python server example.
- [x] Clarify the 101 guide around capability surfaces in NEXUS.
- [x] Link the 202 guide from existing MCP docs.
- [x] Update `AGENTS.md` current handoff.
- [x] Run markdown hygiene validation.

Validation completed:

- `.venv/bin/python -m py_compile docs/references/mcp-python-examples/202-capabilities/capability_server.py`
- `.venv/bin/ruff check docs/references/mcp-python-examples/202-capabilities/capability_server.py`
- `git diff --check`
- Follow-up audit fixes:
  - expanded the example-bundle README and `202-capabilities/README.md` to
    explain the NEXUS-specific distinction between tools vs resources/prompts
  - added `tests/integration/test_mcp_python_examples.py` to smoke test the
    capabilities example against the real MCP client
  - added `docs/references/mcp-python-examples/202-capabilities/inspect_capabilities.py`
    so the example bundle now demonstrates `resources/read` and `prompts/get`
    through NEXUS's Python MCP client instead of stopping at REPL discovery
  - updated the canonical 202 guide and the mirrored example-bundle copy to
    document the REPL-vs-client boundary explicitly and point readers at the
    runnable helper
