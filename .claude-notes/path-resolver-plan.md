# PathResolver Refactor Plan

## Problem
4+ duplicate path resolution implementations, each with slight differences. Bugs fixed in one aren't fixed in others.

## Current Implementations to Replace

1. **FileSkill._validate_path()** - `nexus3/skill/base.py:456-462`
2. **ExecutionSkill._resolve_working_directory()** - `nexus3/skill/base.py:836-872`
3. **FilteredCommandSkill._validate_cwd()** - `nexus3/skill/base.py:1077-1105`
4. **global_dispatcher.py inline** - `nexus3/rpc/global_dispatcher.py:270-282`

## Additional Path.cwd() Bugs to Fix

| File | Line | Issue |
|------|------|-------|
| repl.py | 770, 807, 1445 | Session save uses os.getcwd() |
| commands/core.py | 513 | /save uses os.getcwd() |
| session.py | 464 | Tool exec fallback uses Path.cwd() |
| repl.py | 182 | Confirmation preview wrong cwd |

## PathResolver Design

```python
class PathResolver:
    """Unified path resolution for all agent contexts."""

    def __init__(self, services: ServiceContainer):
        self._services = services

    def resolve(
        self,
        path: str | Path,
        tool_name: str | None = None,
        must_exist: bool = False,
        must_be_dir: bool = False,
    ) -> Path:
        """Resolve path relative to agent's cwd, validate against allowed_paths."""
        # 1. Get agent's cwd
        agent_cwd = self._services.get_cwd()

        # 2. Resolve relative paths against agent cwd
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = agent_cwd / p

        # 3. Get per-tool allowed_paths
        allowed = self._services.get_tool_allowed_paths(tool_name) if tool_name else None

        # 4. Validate via validate_path (follows symlinks, checks containment)
        resolved = validate_path(p, allowed_paths=allowed)

        # 5. Existence checks
        if must_exist and not resolved.exists():
            raise PathSecurityError(f"Path not found: {path}")
        if must_be_dir and not resolved.is_dir():
            raise PathSecurityError(f"Not a directory: {path}")

        return resolved
```

## Implementation Steps

1. Create `nexus3/core/resolver.py` with PathResolver class
2. Update FileSkill._validate_path() to use PathResolver
3. Update ExecutionSkill._resolve_working_directory() to use PathResolver
4. Update FilteredCommandSkill._validate_cwd() to use PathResolver
5. Update global_dispatcher.py to use PathResolver
6. Fix the 6 Path.cwd() bugs in repl.py, commands/core.py, session.py
7. Run tests

## Already Fixed Today

- global_dispatcher.py: parent cwd inheritance, relative path resolution
- context/loader.py: get_system_info() now takes cwd param
- context/loader.py: load_for_subagent() regenerates environment with agent's cwd
- skill/base.py: FilteredCommandSkill._validate_cwd() fixed
- skill/builtin/git.py: now uses _validate_cwd()
