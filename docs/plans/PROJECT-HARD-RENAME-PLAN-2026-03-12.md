# Project Hard Rename Plan (2026-03-12)

## Overview

This plan prepares a full hard rename of NEXUS3 once the replacement name is
chosen. The target is a deliberate breaking rename across the package, CLI,
user-state directories, RPC namespace, built-in nexus tool family, prompt
filenames, documentation, tests, and release metadata.

Because there are no public users to preserve, the plan assumes a flag-day
rename rather than a compatibility alias period. The implementation here does
not execute the rename yet. It adds a spec-driven helper script so the final
cutover can be run in one controlled pass after the new name is decided.

Current planning-slice validation:

- `.venv/bin/pytest -q tests/unit/test_project_hard_rename_script.py`
- `.venv/bin/ruff check scripts/maintenance/project_hard_rename.py tests/unit/test_project_hard_rename_script.py docs/plans/PROJECT-HARD-RENAME-PLAN-2026-03-12.md docs/plans/README.md AGENTS.md`
- `.venv/bin/mypy scripts/maintenance/project_hard_rename.py`
- `.venv/bin/python scripts/maintenance/project_hard_rename.py --print-spec-template`
- `.venv/bin/python scripts/maintenance/project_hard_rename.py --spec <temp-spec> --manifest /tmp/nexus-rename-manifest.json`
- `git diff --check`

## Scope

Included:

- full-source rename planning for tracked repo files
- a spec-driven helper script for dry-run planning and eventual execution
- explicit inventory of the structured rename surfaces
- documentation of residual manual follow-up items after the scripted pass

Deferred:

- selecting the new product/package/tool name
- actually running the rename
- PyPI/package data validation under the new name
- GitHub repo rename, remote URL updates, and release publication
- migration of existing developer machine state in `~/.nexus3/` and project
  `./.nexus3/` directories

Excluded:

- compatibility aliases for `nexus3`, `.nexus3`, `NEXUS3_API_KEY`, or
  `nexus_*`
- soft-branding-only rename options
- automatic migration of untracked local files, session logs, or caches

## Design Decisions And Rationale

### Hard rename means breaking the old namespace

The rename should replace, not alias, the current public/runtime surfaces:

- package/import root: `nexus3`
- CLI command: `nexus3`
- config/log directory: `.nexus3`
- env/header namespace: `NEXUS3_*`, `x-nexus-*`
- built-in agent-management tools: `nexus_*`
- shipped prompt filenames: `NEXUS.md`, `NEXUS-DEFAULT.md`

Keeping old aliases would make the transition easier, but it would also leave
the current brand embedded in the codebase indefinitely. That is the exact
state this plan is trying to avoid.

### The scripted pass only rewrites tracked repository content

The helper script intentionally operates on `git ls-files`, not a raw recursive
filesystem walk. That keeps it away from local session logs, untracked
artifacts, developer scratch files, `.venv`, and other machine-local state.

This is important because the repo already contains untracked directories that
must remain untouched, and the live `.nexus3/` state under the repo root is not
part of the source rename.

### The helper is spec-driven and dry-run by default

The eventual rename should be parameterized rather than baking in a guessed new
name now. The script therefore reads a JSON spec describing the future name
surfaces and only mutates files when `--execute` is passed.

### Structured surfaces are automated; prose residuals still need a sweep

The script handles deterministic rename surfaces well:

- `nexus3` package/import/CLI references
- `.nexus3`
- `NEXUS3_API_KEY`
- `x-nexus-*`
- `nexus_*`
- `NEXUS.md` / `NEXUS-DEFAULT.md`

It does not attempt an unrestricted bare-word rewrite for every occurrence of
`nexus`/`NEXUS` in prose. Those residual cases need a human audit after the
scripted pass because some are historical, some are example data, and some are
compound terms like `nexus-mcp-server`.

## Implementation Details

### Structured rename surfaces

The current blast radius breaks down into these primary buckets:

1. Package/runtime root
   - `nexus3/`
   - `import nexus3` / `from nexus3 ...`
   - `python -m nexus3`
   - `pyproject.toml` project name, script entry point, coverage source

2. User filesystem state
   - `~/.nexus3/`
   - `./.nexus3/`
   - log/session/config/token paths derived from
     [nexus3/core/constants.py](/home/inc/repos/NEXUS3/nexus3/core/constants.py)

3. Runtime protocol namespace
   - `NEXUS3_API_KEY`
   - `x-nexus-agent`
   - `x-nexus-capability`
   - logger names like `nexus3.server`

4. Agent/tool namespace
   - `nexus_create`
   - `nexus_send`
   - `nexus_status`
   - `nexus_destroy`
   - `nexus_cancel`
   - `nexus_shutdown`
   - corresponding builtin skill module filenames

5. Prompt and template filenames
   - `NEXUS.md`
   - `NEXUS-DEFAULT.md`

6. Docs/tests/repo naming
   - root README and module READMEs
   - plan/review docs
   - `AGENTS_NEXUS3*.md`
   - test fixtures and assertions
   - GitHub URLs and local absolute path references

### Helper script

The helper lives at:

- [project_hard_rename.py](/home/inc/repos/NEXUS3/scripts/maintenance/project_hard_rename.py)

Current contract:

- reads a JSON spec for the future name surfaces
- enumerates tracked repo files with `git ls-files`
- computes path rewrites and content rewrites
- refuses to execute on a dirty tracked worktree unless `--allow-dirty`
- defaults to dry-run planning
- can emit a JSON manifest for review
- never touches untracked files

Current assumptions:

- the future package/import/CLI/distribution root is one shared lowercase name
- the future prompt filename stem is provided separately
- the future builtin tool/header stem is provided separately
- repo slug can differ from the display name for URL/path rewrites

Suggested spec shape:

```json
{
  "root_lower": "orbit",
  "root_upper": "ORBIT",
  "repo_slug": "ORBIT",
  "dot_dir_name": ".orbit",
  "prompt_stem": "ORBIT",
  "tool_stem": "orbit",
  "header_stem": "orbit"
}
```

### Manual follow-up after the scripted pass

Even with the helper, the final hard rename still needs a short manual closure:

1. run residual searches for prose/history/example strings:
   - `rg -n '\bnexus\b|\bNEXUS\b|nexus-'`
2. rename the GitHub repo/remotes if desired
3. decide whether to rename local developer state directories manually
4. rebuild packaging artifacts and smoke-install under the new name
5. verify Windows shell wrappers, install snippets, and `pipx` guidance
6. run a live REPL/RPC sanity pass under the new command name

## Testing Strategy

Before the actual rename:

- unit-test the helper’s path/content rewrite planning
- run the helper in dry-run mode with a sample spec and inspect the manifest
- confirm the manifest excludes untracked local state

During the eventual rename:

- run the helper in execute mode on a clean tracked worktree
- run targeted residual `rg` searches for old surfaces
- run focused static validation:
  - `.venv/bin/ruff check nexus3/ tests/` adjusted to the new package root
  - `.venv/bin/mypy <new-package-root>`
  - `.venv/bin/pytest -q` focused on CLI/RPC/skill registration first
- run live validation:
  - new CLI starts
  - RPC server starts
  - renamed agent-management tools are exposed and callable

## Implementation Checklist

- [x] Audit structured rename surfaces and blast radius.
- [x] Create a full hard-rename plan doc.
- [x] Add a tracked-files-only dry-run helper script.
- [x] Add focused unit coverage for the helper script.
- [ ] Choose the final new name spec.
- [ ] Run helper dry-run and inspect manifest.
- [ ] Execute the scripted rename on a clean tracked worktree.
- [ ] Perform residual manual search-and-fix sweep.
- [ ] Re-run docs/readme/package validation under the new name.
- [ ] Smoke-test live REPL and RPC under the new command.

## Documentation Updates

Completed in this planning slice:

- add this plan doc
- index it from [docs/plans/README.md](/home/inc/repos/NEXUS3/docs/plans/README.md)
- record the current handoff in [AGENTS.md](/home/inc/repos/NEXUS3/AGENTS.md)
- validate the helper with focused unit/static checks and a real dry-run

Required during the actual rename:

- root [README.md](/home/inc/repos/NEXUS3/README.md)
- [AGENTS.md](/home/inc/repos/NEXUS3/AGENTS.md)
- [CLAUDE.md](/home/inc/repos/NEXUS3/CLAUDE.md)
- `nexus3/*/README.md` under the new package root
- prompt/default docs and generated install snippets
