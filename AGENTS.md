# AGENTS.md

This file provides guidance to Codex when working in this repository.

## Project Overview

NEXUS3 is a clean-slate rewrite of NEXUS2, an AI-powered CLI agent framework.

- Status: feature-complete
- Core areas: multi-provider support, permission system, MCP integration, context compaction

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

Each module has its own `README.md`.

## Context Files

Instruction file priority is configurable; defaults include:

```json
["NEXUS.md", "AGENTS.md", "CLAUDE.md", "README.md"]
```

For this repo, keep `AGENTS.md` and `CLAUDE.md` consistent when behavior or workflows change.

## Reference Docs

Detailed references live in companion files to keep this document concise:

- `AGENTS_NEXUS3ARCH.md`: project overview, module architecture, interfaces, skill hierarchy, multi-agent server model
- `AGENTS_NEXUS3CMDCAT.md`: full CLI modes, flags, session model, and REPL command reference
- `AGENTS_NEXUS3SKILLSCAT.md`: full built-in skills table and notes
- `AGENTS_NEXUS3CTXSEC.md`: full context loading/compaction, temporal/git injection, permissions, and security hardening notes
- `AGENTS_NEXUS3CONFIGOPS.md`: configuration reference, provider setup, GitLab/clipboard config, design/SOP/testing workflows, and deferred work tracker

## Current Workstream (2026-03-02)

For continuity on the current review/remediation effort, start from:

- Review index: [docs/reviews/README.md](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- Canonical master review: [docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- Plans index: [docs/plans/README.md](/home/inc/repos/NEXUS3/docs/plans/README.md)
- Architecture investigation: [docs/plans/ARCH-INVESTIGATION-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- Milestone schedule: [docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)

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

For non-trivial features, create a plan doc under `docs/` before implementation.

Minimum plan sections:

- Overview
- Scope (included, deferred, excluded)
- Design decisions and rationale
- Implementation details with concrete file paths
- Testing strategy
- Implementation checklist
- Documentation updates

Update the plan incrementally while you work.

## Testing and Validation

Always use virtualenv executables:

```bash
.venv/bin/pytest tests/ -v
.venv/bin/pytest tests/integration/ -v
.venv/bin/ruff check nexus3/
.venv/bin/mypy nexus3/
```

Never rely on bare `python` or `pytest`.

Known sandbox caveat (Codex CLI environment):
- In this repo, sandboxed runs may hang on tests that execute file I/O via `asyncio.to_thread(...)` (for example, `Path.read_bytes` inside file-edit skills).
- Symptom: pytest collects tests, starts first test, then stalls without pass/fail output.
- Workaround: rerun the same pytest command unsandboxed/escalated to verify real pass/fail status.

Live validation is required for changes that affect agent behavior, RPC, skills, or permissions:

```bash
nexus3 &
nexus3 rpc create test-agent
nexus3 rpc send test-agent "describe your permissions and what you can do"
nexus3 rpc destroy test-agent
```

## Permissions and Safety

- Respect preset boundaries (`sandboxed`, `trusted`, `yolo`).
- `sandboxed` should remain least-privileged by default in RPC workflows.
- Treat tool enablement, write paths, and agent targeting restrictions as security-sensitive.
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
- Update `CLAUDE.md` and `AGENTS.md` sections that describe the changed behavior
- Update command/help text for CLI or REPL changes
- Record temporary breakages in `CLAUDE.md` Known Failures if they cannot be fixed immediately

## Source of Truth

`CLAUDE.md` contains full project reference detail. This file is the Codex-oriented operating guide distilled from it.
