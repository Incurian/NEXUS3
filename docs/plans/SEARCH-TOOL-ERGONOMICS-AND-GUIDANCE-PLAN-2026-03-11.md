# Search Tool Ergonomics And Guidance Plan (2026-03-11)

## Overview

NEXUS3 already has built-in path and content search tools, but agents still
fall back to shell/PowerShell search commands more often than they should.
The clearest current gap is `glob`: it is secure and functional, but it is
still a thin `Path.glob(...)` wrapper with substring-based excludes and very
little ergonomic help for common file-finder tasks.

This slice improves built-in search-tool ergonomics where the current schema is
too bare, and updates prompt/docs guidance so agents are explicitly taught to
prefer `glob` and built-in content search over shell equivalents when shell
composition is not required.

## Scope

### Included

- Improve `glob` enough to cover the most common shell/PowerShell file-finder
  use cases without invoking `exec` or `shell_UNSAFE`
- Add explicit built-in search guidance to prompt/docs surfaces:
  - prefer `glob` for file/path discovery
  - prefer built-in content search for content lookup
  - use shell search only when shell composition or exact external CLI
    semantics are genuinely required
- Preserve existing path-gateway and blocked-path protections while adjusting
  search ergonomics
- Add/update regression coverage for the new `glob` contract and guidance

### Deferred

- Renaming built-in `grep` to a less shell-priming name such as
  `search_text`
- Multiple-pattern path search beyond a single primary pattern
- Depth control, metadata-rich listing, and sorted/ranked search views beyond
  what is needed to displace common shell file-finder usage
- Any fuzzy matching behavior

### Excluded

- Replacing built-in content search semantics in this slice
- Shell-tool policy changes beyond the guidance updates needed to steer agents
  toward built-ins
- Full-text ranking, indexing, or fuzzy path/content search

## Design Decisions And Rationale

### 1. Fix the built-in path search ergonomics before renaming tools

The user-observed problem is not just naming. `glob` is currently too bare for
several common search workflows, so prompt guidance alone will not fully
displace shell `Get-ChildItem`, `find`, or similar commands. The first step is
to make the built-in tool more capable while keeping its model-simple contract.

### 2. Keep `glob` pattern-based, but add explicit ergonomic controls

The current tool relies too heavily on callers knowing `Path.glob(...)`
semantics such as `**`. The updated contract should keep glob patterns, but
add explicit parameters for common control points so the tool is easier to use
correctly:

- `recursive?: bool`
- `kind?: "file" | "directory" | "any"`
- `exclude?: string[]` with true glob-style matching rather than substring
  filtering

This closes the biggest shell-search gap without turning `glob` into a general
filesystem query language.

### 3. Preserve current pattern behavior where practical

Existing callers already rely on `pattern`. The redesign should avoid needless
breakage:

- existing patterns remain valid
- explicit `recursive` becomes the recommended control, rather than requiring
  `**` knowledge
- output remains path-oriented and bounded by `max_results`

### 4. Exclusions should match paths, not substrings

Today `exclude=["node_modules"]` works only because `glob` does substring
checks on rendered paths. That is underspecified and hard to reason about.
Exclusion behavior should instead be defined in terms of relative-path glob
matching so users and agents can predict what will be skipped.

### 5. Guidance belongs in prompts as well as reference docs

Agents do not reliably infer preferred tool choice from README tables alone.
The default prompt and tool catalogs should explicitly say:

- use `glob` for file/path discovery
- use built-in content search for file-content search
- avoid shell search unless shell syntax is actually needed

## Implementation Details

### Phase 1: `glob` contract and behavior upgrade

Files:

- `nexus3/skill/builtin/glob_search.py`
- `tests/unit/test_skill_enhancements.py`
- `tests/unit/skill/test_glob_search.py`

Work:

- add explicit `recursive` support for common recursive path search
- add `kind` filtering so callers can request files, directories, or either
- replace substring-based `exclude` checks with true glob-aware exclusion
  matched against relative paths
- keep `max_results` behavior bounded and deterministic
- preserve existing gateway-based path filtering and blocked-path behavior

### Phase 2: prompt and documentation guidance

Files:

- `nexus3/defaults/NEXUS-DEFAULT.md`
- `README.md`
- `nexus3/skill/README.md`
- `AGENTS_NEXUS3SKILLSCAT.md`
- `CLAUDE.md`
- `AGENTS.md`

Work:

- update the `glob` schema/description to match the new parameters
- add explicit tool-choice guidance for search workflows
- include practical guidance such as:
  - use `glob` instead of shell `Get-ChildItem`, `dir`, or `find` for normal
    file discovery
  - use built-in content search instead of shell `grep`/`rg` unless shell
    composition is needed
- keep the future `grep` rename as a documented deferred discussion rather
  than mixing it into this implementation slice

### Phase 3: validation closeout

Files:

- touched runtime/test/doc files above

Work:

- verify new `glob` behavior with focused unit coverage
- verify path-gateway behavior still holds under new traversal/filtering
- run live validation so an agent can describe the new tool contract and the
  updated guidance

## Testing Strategy

- targeted Ruff:
  - `.venv/bin/ruff check nexus3/skill/builtin/glob_search.py tests/unit/test_skill_enhancements.py tests/unit/skill/test_glob_search.py`
- targeted pytest:
  - `.venv/bin/pytest -q tests/unit/test_skill_enhancements.py tests/unit/skill/test_glob_search.py`
- add any extra focused tests needed if schema/validation surfaces are touched
- live validation because this slice changes a built-in skill contract and
  prompt guidance:
  - verify an agent now describes `glob` with the new parameters
  - verify prompt guidance steers toward built-in search over shell search

## Implementation Checklist

- [ ] Finalize the upgraded `glob` contract (`recursive`, `kind`, true
      exclude semantics).
- [ ] Implement the `glob` runtime changes with preserved path-gateway
      protections.
- [ ] Add/update regression tests for recursive search, kind filtering, and
      exclusion behavior.
- [ ] Sync prompt guidance and tool-reference docs.
- [ ] Run focused validation and live validation.

## Documentation Updates

- Update `docs/plans/README.md` to index this plan.
- Update `AGENTS.md` running status to reference this follow-on plan and its
  execution order.
