# AGENTS.md

This file provides guidance to Codex when working in this repository.

## Canonical Guidance

- `AGENTS.md` is the canonical agent document for this repo.
- Keep stable project guidance and reference links in this file.
- Keep the most recent checkpoint in [`## Current Handoff`](#current-handoff)
  at the bottom of this file.
- `CLAUDE.md` should mirror the stable guidance here and point back to
  [`## Current Handoff`](#current-handoff) for the latest status.

## Project Overview

NEXUS3 is a clean-slate rewrite of NEXUS2, an AI-powered CLI agent framework.

- Status: feature-complete
- Core areas: multi-provider support, permission system, MCP integration,
  context compaction

## Architecture

Primary package: `nexus3/`

- `core/`: types, interfaces, errors, paths, permissions, process termination
- `config/`: schema and config loading
- `provider/`: model provider abstraction and retry logic
- `context/`: context loading, token counting, compaction
- `session/`: session coordination, persistence, logging
- `skill/`: skill protocol, registry, service container
- `clipboard/`: scoped clipboard and persistence
- `patch/`: unified diff parsing and application
- `display/`: terminal presentation and streaming output
- `cli/`: REPL, lobby, server/client modes, commands
- `rpc/`: JSON-RPC dispatching and agent pool
- `mcp/`: MCP integration
- `commands/`: command infrastructure
- `defaults/`: default prompts/config

Each implemented module has its own `README.md`; `nexus3/ide` remains
intentionally deferred and does not have one yet.

## Context Files

Instruction file priority is configurable; defaults include:

```json
["NEXUS.md", "AGENTS.md", "CLAUDE.md", "README.md"]
```

For this repo, keep `AGENTS.md` and `CLAUDE.md` consistent when behavior or
workflow guidance changes.

## Reference Docs

Detailed references live in companion files to keep this document concise:

- `AGENTS_NEXUS3ARCH.md`: project overview, module architecture, interfaces,
  skill hierarchy, multi-agent server model
- `AGENTS_NEXUS3CMDCAT.md`: full CLI modes, flags, session model, and REPL
  command reference
- `AGENTS_NEXUS3SKILLSCAT.md`: full built-in skills table and notes
- `AGENTS_NEXUS3CTXSEC.md`: full context loading/compaction, temporal/git
  injection, permissions, and security hardening notes
- `AGENTS_NEXUS3CONFIGOPS.md`: configuration reference, provider setup,
  GitLab/clipboard config, design/SOP/testing workflows, and deferred work
  tracker
- `docs/references/TOOL-SURFACE-DESIGN-GUIDELINES.md`: lessons from the
  2026-04 tool-syntax simplification work and rules for future tool design
- `docs/references/MCP-SERVER-PYTHON-101.md`: beginner tutorial for building
  Python MCP tool servers that work with NEXUS3 over stdio or HTTP
- `docs/references/MCP-SERVER-PYTHON-202.md`: follow-on guide for MCP
  resources, prompts, and how additional MCP capabilities surface in NEXUS3
- `docs/references/mcp-python-examples/`: checked-in example projects with
  server code and `.nexus3/mcp.json` for the 101/202 MCP docs

## Current Workstream (2026-03-02)

For continuity on the current review/remediation effort, start from:

- Review index:
  [docs/reviews/README.md](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- Canonical master review:
  [docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- Plans index:
  [docs/plans/README.md](/home/inc/repos/NEXUS3/docs/plans/README.md)
- Architecture investigation:
  [docs/plans/ARCH-INVESTIGATION-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- Milestone schedule:
  [docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)

## Engineering SOP

- Type everything; avoid weak typing and `Optional[Any]`.
- Fail fast; do not silently swallow exceptions.
- Prefer one clear implementation path over duplicate patterns.
- Keep code async-first where applicable.
- Add end-to-end tests for new behavior.
- Document user-visible changes.
- Delete dead code and unused imports.
- Do not revert unrelated local changes.
- Keep feature branches focused and commit in logical units.

## Planning Requirements

For non-trivial features, create a plan doc under `docs/` before
implementation.

Minimum plan sections:

- Overview
- Scope (included, deferred, excluded)
- Design decisions and rationale
- Implementation details with concrete file paths
- Testing strategy
- Implementation checklist
- Documentation updates

Update the plan incrementally while you work.

Execution tracking and handoff SOP:

- Keep stable guidance above and the live checkpoint in
  [`## Current Handoff`](#current-handoff) at the bottom of this file.
- When writing a new handoff, append a new
  `### YYYY-MM-DD - <slice>` block under `## Current Handoff`, then prune the
  previous block in the same edit so only the latest handoff remains here.
- Each handoff should include: branch, active slice, relevant plans/docs,
  recent commits or baseline head, validation status, and next gate.
- When disconnected or compacted, resume from `## Current Handoff` first, then
  reconcile referenced plan checklists before new edits.
- When spawning Codex subagents, explicitly instruct them to avoid escalated or
  sandbox-bypass commands unless absolutely required by the task, to prevent
  avoidable approval stalls.

## Testing and Validation

Always use virtualenv executables:

```bash
.venv/bin/pytest tests/ -v
.venv/bin/pytest tests/integration/ -v
.venv/bin/ruff check nexus3/
.venv/bin/mypy nexus3/
```

Never rely on bare `python` or `pytest`.

Known sandbox caveats in the Codex CLI environment:

- Sandboxed runs may hang on tests that execute file I/O via
  `asyncio.to_thread(...)` (for example, `Path.read_bytes` inside file-edit
  skills).
- Symptom: pytest collects tests, starts the first test, then stalls without
  pass/fail output.
- Workaround: rerun the same pytest command unsandboxed or escalated to verify
  real pass/fail status.
- Sandbox networking also blocks `git push` reliably in Codex CLI.
- Workaround: when the user explicitly asks to push, skip the sandboxed push
  attempt and run the push unsandboxed or escalated immediately.

Live validation is required for changes that affect agent behavior, RPC,
skills, or permissions:

```bash
nexus3 &
nexus3 rpc create test-agent
nexus3 rpc send test-agent "describe your permissions and what you can do"
nexus3 rpc destroy test-agent
```

## Permissions and Safety

- Respect preset boundaries (`sandboxed`, `trusted`, `yolo`).
- `sandboxed` should remain least-privileged by default in RPC workflows.
- Treat tool enablement, write paths, and agent targeting restrictions as
  security-sensitive.
- Avoid privilege escalation patterns in subagent creation.

## CLI and Ops Notes

Useful commands:

```bash
nexus3
nexus3 --fresh
nexus3 --resume
NEXUS_DEV=1 nexus3 --serve 9000
nexus3 rpc detect
nexus3 rpc list
nexus3 rpc create NAME
nexus3 rpc send NAME "message"
nexus3 rpc status NAME
```

## Documentation Discipline

When changing behavior:

- Update relevant module `README.md`
- Update `CLAUDE.md` and `AGENTS.md` sections that describe the changed
  behavior
- Update command/help text for CLI or REPL changes
- Record temporary breakages in `CLAUDE.md` Known Failures if they cannot be
  fixed immediately

## Debugging Playbook

Use this fallback only if the post-cancel provider failures recur:

- `Provider returned an empty response`
- `API request failed (400): Unexpected role 'user' after role 'tool'`

Capture actionable logs with:

```bash
nexus3 -V --raw-log --resume
# or: nexus3 -V --raw-log --session <NAME>
```

Then collect the newest session directory under `./.nexus3/logs/` and inspect:

- `verbose.md` for the last `session.preflight` block before the failure
- `raw.jsonl` for the exact outbound payload and any provider 4xx/5xx body
- `context.md` for the surrounding conversation sequence

When investigating:

1. Verify the preflight role order, especially `TOOL -> USER` adjacency,
   duplicate tool results, or tool results without matching assistant
   `tool_calls`.
2. Confirm the failing request payload in `raw.jsonl` matches the preflight
   snapshot.
3. Add a unit test for the exact failing sequence before patching.

If the failure persists after existing repairs, prefer a provider-agnostic
message normalizer just before the provider call rather than another
ad-hoc compatibility shim.

## Current Handoff

### 2026-04-07 - MCP Python docs didactic audit final polish

- Branch: `master`
- Baseline head: `6bd96f1`
- Active slice:
  - finish the didactic audit of the Python MCP example bundle against the
    actual NEXUS CLI and MCP client behavior
  - remove machine-specific walkthrough assumptions that make the examples
    brittle outside this checkout
  - keep the canonical docs and mirrored example-bundle copies in sync
- Plans/docs:
  - [docs/plans/MCP-SERVER-PYTHON-101-DOC-PLAN-2026-04-07.md](/home/inc/repos/NEXUS3/docs/plans/MCP-SERVER-PYTHON-101-DOC-PLAN-2026-04-07.md)
  - [docs/plans/MCP-SERVER-PYTHON-202-DOC-PLAN-2026-04-07.md](/home/inc/repos/NEXUS3/docs/plans/MCP-SERVER-PYTHON-202-DOC-PLAN-2026-04-07.md)
  - [docs/references/MCP-SERVER-PYTHON-101.md](/home/inc/repos/NEXUS3/docs/references/MCP-SERVER-PYTHON-101.md)
  - [docs/references/MCP-SERVER-PYTHON-202.md](/home/inc/repos/NEXUS3/docs/references/MCP-SERVER-PYTHON-202.md)
  - [docs/references/mcp-python-examples/README.md](/home/inc/repos/NEXUS3/docs/references/mcp-python-examples/README.md)
- Implemented locally:
  - `/mcp` REPL commands now merge configured servers from both
    `config.json` and layered `mcp.json`
  - `ContextLoader` now accepts the documented `mcp.json` object form:
    - `{"servers": {"name": {...}}}`
    - list form and `mcpServers` remain supported
  - 101/202 docs now explain transport vs capabilities, `mcp.json` fields,
    merge behavior, and the low-friction `/mcp connect ... --allow-all --private`
    tutorial path
  - the example-bundle README and per-example READMEs now teach a clearer
    progression, recommend `nexus3 --fresh`, and call out NEXUS-specific
    constraints explicitly
  - the example-bundle README and mirrored 101 guide copies now include
    prerequisites plus first-failure troubleshooting for interpreter/path,
    stdout-vs-stderr, reconnect, and HTTP URL drift issues
  - checked-in example servers now make config fields observable:
    - `101-stdio`: `args`, `env`, and `cwd` change the greeting behavior, and
      the checked-in config now uses `python3`
    - `101-http`: audited and moved to port `9876` after confirming that
      `nexus3 --fresh` binds the embedded RPC server on `8765`
    - `202-capabilities`: `args`, `env`, and `cwd` affect tool/resource/prompt
      output, and the checked-in config now uses `python3`
  - added `tests/integration/test_mcp_python_examples.py` so the checked-in
    examples are smoke-tested against the real MCP client
  - added
    [inspect_capabilities.py](/home/inc/repos/NEXUS3/docs/references/mcp-python-examples/202-capabilities/inspect_capabilities.py)
    so the 202 bundle now demonstrates:
    - `tools/list`
    - `resources/list`
    - `prompts/list`
    - `resources/read`
    - `prompts/get`
    through NEXUS's Python MCP client using the checked-in example config
  - the canonical 202 guide and mirrored bundle copy now point readers at the
    runnable helper and explain the current REPL/client boundary explicitly
  - linked the MCP docs from the top-level README, MCP module docs, test
    server README, AGENTS, and CLAUDE
  - final doc polish from live validation:
    - replaced machine-specific shell paths with `<repo-root>` placeholders
    - documented the repo-local `<repo-root>/.venv/bin/nexus3` fallback for
      walkthroughs started from example directories
    - clarified that extra `/mcp` entries may appear from layered config and
      are not part of the example flow
    - clarified that the toy servers satisfy
      `notifications/initialized` by ignoring no-id notifications unless they
      need custom behavior
    - clarified that the HTTP 101 example is intentionally stateless and that
      the 202 helper must run from the repo root or equivalent `PYTHONPATH`
    - kept the mirrored example-bundle 101/202 guide copies identical to the
      canonical docs
- Validation status:
  - focused tests passed:
    - `.venv/bin/pytest -q tests/unit/test_repl_commands.py tests/unit/test_context_loader.py tests/unit/context/test_loader_mcp_fail_fast.py` (`112 passed`)
  - example code validation passed:
    - `.venv/bin/python -m py_compile docs/references/mcp-python-examples/101-stdio/hello_stdio_server.py docs/references/mcp-python-examples/101-http/hello_http_server.py docs/references/mcp-python-examples/202-capabilities/capability_server.py docs/references/mcp-python-examples/202-capabilities/inspect_capabilities.py`
    - `.venv/bin/ruff check nexus3/cli/repl_commands.py nexus3/context/loader.py tests/unit/test_repl_commands.py tests/unit/test_context_loader.py tests/unit/context/test_loader_mcp_fail_fast.py docs/references/mcp-python-examples/101-stdio/hello_stdio_server.py docs/references/mcp-python-examples/101-http/hello_http_server.py docs/references/mcp-python-examples/202-capabilities/capability_server.py`
    - `.venv/bin/ruff check docs/references/mcp-python-examples/202-capabilities/inspect_capabilities.py tests/integration/test_mcp_python_examples.py`
  - example smoke tests passed:
    - `.venv/bin/pytest -q tests/integration/test_mcp_python_examples.py` (`4 passed`)
  - direct helper validation passed:
    - `.venv/bin/python docs/references/mcp-python-examples/202-capabilities/inspect_capabilities.py`
    - rerun after final doc edits: `.venv/bin/python docs/references/mcp-python-examples/202-capabilities/inspect_capabilities.py`
  - end-to-end example audit passed:
    - stdio example connected, exposed tools, and returned the configured greeting
    - HTTP example connected from the documented two-terminal flow and returned
      expected tool results without colliding with NEXUS's embedded RPC server
    - capabilities example exposed tools/resources/prompts and reflected config
      values in outputs
    - capability helper exercised `resources/read` and `prompts/get` with the
      same client/transport layer NEXUS uses internally
    - final live CLI verification after doc polish:
      - `/home/inc/repos/NEXUS3/.venv/bin/nexus3 --fresh` from
        `101-stdio/` connected `hello_stdio` and listed `mcp_hello_stdio_hello`
        plus `mcp_hello_stdio_add`
      - `/home/inc/repos/NEXUS3/.venv/bin/nexus3 --fresh` from
        `202-capabilities/` connected `capability_demo` and listed the
        documented resources and prompts
  - example smoke tests passed after final doc edits:
    - `.venv/bin/pytest -q tests/integration/test_mcp_python_examples.py` (`4 passed`)
  - hygiene passed:
    - `git diff --check`
- Next gate:
  - push only when requested
