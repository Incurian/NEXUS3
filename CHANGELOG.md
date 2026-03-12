# Changelog

## v1.0.0 - 2026-03-12

First stable NEXUS3 release.

Highlights:

- unified multi-agent REPL and RPC workflows on `master`
- trace viewer with active-session and subagent follow support
- cleaned-up REPL streaming/tool rendering, including standardized tool result
  previews and recent-history pull on attach
- embedded RPC idle activity now stays alive during direct REPL use
- module README coverage and top-level docs were audited and corrected before
  release

Upgrade note:

- If you are updating an existing checkout, rerun your install command because
  `psutil` was added recently as a runtime dependency for the host process
  tools.
- Use the same install variant you normally use:
  - `pip install -e .`
  - `pip install -e ".[dev]"`
  - `pip install -e ".[ci]"`
