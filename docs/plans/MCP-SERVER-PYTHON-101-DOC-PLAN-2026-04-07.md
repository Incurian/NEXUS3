# MCP Server Python 101 Doc Plan (2026-04-07)

## Overview

Add a beginner-friendly guide for writing Python MCP servers that work with
NEXUS3.

The repo already documents NEXUS3's MCP client/runtime and includes internal
test servers, but it does not yet have a simple step-by-step tutorial for
people who want to build their own MCP tool server in Python. The new guide
should focus on the smallest working surface first, then show how to grow it.

## Scope

Included:

- add a durable tutorial doc for "MCP servers and tools for NEXUS3 in Python"
- cover the two transport types NEXUS3 supports in practice for this use case:
  - stdio subprocess servers
  - HTTP POST JSON-RPC servers
- show the minimal MCP methods needed for a tools-only server
- include full working Python examples for both transports
- explain how to add another tool
- show the exact NEXUS3 `mcp.json` configuration for each example
- link the new guide from the main MCP docs so it is discoverable

Deferred:

- equivalent tutorials in JavaScript/TypeScript or other languages
- advanced topics like resources, prompts, pagination, streaming progress, or
  MCP auth/session management
- packaging/publishing guidance for third-party MCP server distributions

Excluded:

- changes to the MCP client/runtime behavior itself
- changes to the built-in MCP test servers beyond doc cross-links

## Design Decisions And Rationale

### 1. Start with tools-only servers

The beginner path should only require:

- `initialize`
- `notifications/initialized` (ignored, no response)
- `tools/list`
- `tools/call`

Rationale:

- this is the smallest surface NEXUS3 needs for useful MCP tool integration
- resources and prompts are valuable, but they are not required for the first
  successful server

### 2. Teach stdio first, then HTTP

The guide should explain both transports, but it should recommend stdio first.

Rationale:

- stdio is the most common local MCP deployment pattern
- stdio avoids a separate port, background server process, and HTTP framework
- HTTP is still important for shared/remote integrations and deserves a full
  example too

### 3. Use self-contained Python examples

The examples should be copy-pasteable into one file each and should not depend
on NEXUS3 internals.

Rationale:

- readers may be building an MCP server outside this repo
- a 101 guide should minimize prerequisites and hidden imports

### 4. Be explicit about NEXUS3-specific integration details

The guide should call out:

- how to configure `mcp.json`
- how NEXUS3 prefixes MCP tool names
- how to refresh tool lists after adding tools
- stdio logging rules (`stderr`, not `stdout`)

Rationale:

- those are the integration details most likely to block first-time users

## Implementation Details

Primary files:

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

- the new guide is internally consistent with the current NEXUS3 MCP transport
  behavior
- the links from the existing MCP docs resolve and point to the new guide
- touched markdown files are formatting-clean under `git diff --check`

## Documentation Updates

- add and index this plan doc
- add the beginner tutorial under `docs/references/`
- link it from the top-level README MCP section and `nexus3/mcp/README.md`
- point the test-server README at the beginner guide
- keep `AGENTS.md` / `CLAUDE.md` reference-doc lists current if the new guide
  should be treated as a durable reference

## Implementation Checklist

- [x] Audit the existing MCP docs and example servers already in the repo.
- [x] Record the tutorial/doc plan.
- [x] Write the beginner Python MCP server guide with stdio and HTTP examples.
- [x] Link it from the existing MCP docs.
- [x] Update `AGENTS.md` current handoff.
- [x] Run markdown hygiene validation.

Validation completed:

- `.venv/bin/python -m py_compile docs/references/mcp-python-examples/101-stdio/hello_stdio_server.py docs/references/mcp-python-examples/101-http/hello_http_server.py`
- `.venv/bin/ruff check docs/references/mcp-python-examples/101-stdio/hello_stdio_server.py docs/references/mcp-python-examples/101-http/hello_http_server.py`
- `git diff --check`
- Follow-up audit fixes:
  - refreshed the example-bundle README and per-example READMEs to teach a
    clearer learning path and recommend `nexus3 --fresh`
  - changed the checked-in stdio configs to use `python3` as the default
    interpreter
  - moved the checked-in HTTP example from port `8765` to `9876` after
    confirming that `nexus3 --fresh` uses embedded RPC port `8765`
  - added `tests/integration/test_mcp_python_examples.py` to smoke test the
    checked-in 101 examples against the real MCP client
