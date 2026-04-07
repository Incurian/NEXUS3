# Changelog

## v1.1.0 - 2026-04-07

Second stable NEXUS3 release.

Highlights:

- normalized tool-call payload handling across OpenAI-compatible and
  Anthropic-compatible provider paths, including malformed-argument diagnostics
  and interrupted-stream handling
- hardened the patch pipeline so fuzzy dry-runs match real apply behavior and
  malformed hunks fail earlier with targeted guidance
- simplified file-editing tool contracts by splitting overloaded public shapes
  into single-purpose tools like `edit_file_batch`, `edit_lines_batch`, and
  `patch_from_file`
- aligned prompt guidance, tool descriptions, permission defaults, and docs
  with the simplified tool surface so weaker models see one canonical schema
  per tool

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
