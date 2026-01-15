# Consolidated Refactor Plan: PathResolver + Config/Context DRY

Created: 2026-01-15
Branch: `refactor/path-resolver`

## Problem Statement

Multi-agent testing revealed bugs where relative paths resolved against wrong cwd. Root cause: 4+ duplicate path resolution implementations with subtle differences.

Additional DRY violations found:
- `.nexus3` path hardcoded in 5 locations
- `deep_merge()` duplicated in config/loader.py and context/loader.py
- Ancestor discovery duplicated in same files

## Execution Order

```
Phase 1: core/constants.py (no dependencies)
    ↓
Phase 2: core/utils.py - deep_merge(), find_ancestor_config_dirs()
    ↓
Phase 3: core/resolver.py - PathResolver class
    ↓
Phase 4: Migrate skill base classes to use PathResolver
    ↓
Phase 5: Fix Path.cwd() bugs in repl.py, session.py, etc.
```

---

## Phase 1: Core Constants

**Create `/home/inc/repos/NEXUS3/nexus3/core/constants.py`**

```python
"""Core constants and paths for NEXUS3."""

from pathlib import Path

NEXUS_DIR_NAME = ".nexus3"

def get_nexus_dir() -> Path:
    """Get ~/.nexus3 (global config directory)."""
    return Path.home() / NEXUS_DIR_NAME

def get_defaults_dir() -> Path:
    """Get package defaults directory."""
    import nexus3
    return Path(nexus3.__file__).parent / "defaults"

def get_sessions_dir() -> Path:
    """Get sessions storage directory."""
    return get_nexus_dir() / "sessions"

def get_rpc_token_path(port: int = 8765) -> Path:
    """Get RPC token file path for a given port."""
    nexus_dir = get_nexus_dir()
    return nexus_dir / "rpc.token" if port == 8765 else nexus_dir / f"rpc-{port}.token"
```

**Files to Update:**

| File | Line | Current | Change To |
|------|------|---------|-----------|
| `rpc/auth.py` | 47 | `Path.home() / ".nexus3"` | `from nexus3.core.constants import get_nexus_dir` |
| `config/loader.py` | 141 | `Path.home() / ".nexus3" / "config.json"` | `get_nexus_dir() / "config.json"` |
| `context/loader.py` | 204 | `return Path.home() / ".nexus3"` | `return get_nexus_dir()` |
| `session/session_manager.py` | 83 | `Path.home() / ".nexus3"` | `get_nexus_dir()` |
| `cli/init_commands.py` | 62 | `Path.home() / ".nexus3"` | `get_nexus_dir()` |

---

## Phase 2: Shared Utilities

**Create `/home/inc/repos/NEXUS3/nexus3/core/utils.py`**

```python
"""Shared utility functions for NEXUS3."""

from pathlib import Path
from typing import Any

from nexus3.core.constants import NEXUS_DIR_NAME

def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge dicts. Override values take precedence.

    - Dicts are recursively merged
    - Lists are extended (not replaced)
    - Other values are overwritten
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            result[key] = result[key] + value
        else:
            result[key] = value
    return result

def find_ancestor_config_dirs(cwd: Path, max_depth: int = 2) -> list[Path]:
    """Find .nexus3 directories in ancestor paths.

    Returns list in order from furthest (grandparent) to nearest (parent).
    """
    ancestors = []
    current = cwd.parent

    for _ in range(max_depth):
        if current == current.parent:  # Reached root
            break
        config_dir = current / NEXUS_DIR_NAME
        if config_dir.is_dir():
            ancestors.append(config_dir)
        current = current.parent

    return list(reversed(ancestors))
```

**Files to Update:**

| File | Lines | Change |
|------|-------|--------|
| `config/loader.py` | 22-44 | Delete `_deep_merge()`, import from `core.utils` |
| `config/loader.py` | 79-102 | Delete `_find_ancestor_config_dirs()`, import from `core.utils` |
| `context/loader.py` | 147-165 | Delete `deep_merge()`, import from `core.utils` |
| `context/loader.py` | 212-231 | Delete `_find_ancestor_dirs()` method, use imported function |
| `context/__init__.py` | exports | Re-export `deep_merge` from `core.utils` for backwards compat |

---

## Phase 3: PathResolver

**Create `/home/inc/repos/NEXUS3/nexus3/core/resolver.py`**

```python
"""Unified path resolution for all agent contexts."""

from pathlib import Path
from typing import TYPE_CHECKING

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import validate_path

if TYPE_CHECKING:
    from nexus3.skill.services import ServiceContainer


class PathResolver:
    """Unified path resolution for all agent contexts.

    Replaces duplicated logic in:
    - FileSkill._validate_path()
    - ExecutionSkill._resolve_working_directory()
    - FilteredCommandSkill._validate_cwd()
    - global_dispatcher.py inline validation
    """

    def __init__(self, services: "ServiceContainer"):
        self._services = services

    def resolve(
        self,
        path: str | Path,
        tool_name: str | None = None,
        must_exist: bool = False,
        must_be_dir: bool = False,
    ) -> Path:
        """Resolve path relative to agent's cwd, validate against allowed_paths."""
        # 1. Get agent's cwd (not process cwd)
        agent_cwd = self._services.get_cwd()

        # 2. Resolve relative paths against agent cwd
        p = Path(path).expanduser() if isinstance(path, str) else path.expanduser()
        if not p.is_absolute():
            p = agent_cwd / p

        # 3. Get per-tool allowed_paths
        allowed = self._services.get_tool_allowed_paths(tool_name) if tool_name else None

        # 4. Validate via validate_path (follows symlinks, checks containment)
        resolved = validate_path(p, allowed_paths=allowed)

        # 5. Existence checks
        if must_exist and not resolved.exists():
            raise PathSecurityError(str(path), f"Path not found: {path}")
        if must_be_dir and not resolved.is_dir():
            raise PathSecurityError(str(path), f"Not a directory: {path}")

        return resolved

    def resolve_cwd(
        self,
        cwd: str | None,
        tool_name: str | None = None,
    ) -> tuple[str | None, str | None]:
        """Resolve working directory for subprocess execution.

        Returns (resolved_cwd_string, error_message_or_none).
        """
        agent_cwd = self._services.get_cwd()

        if not cwd:
            return str(agent_cwd), None

        try:
            resolved = self.resolve(cwd, tool_name=tool_name, must_exist=True, must_be_dir=True)
            return str(resolved), None
        except PathSecurityError as e:
            return None, str(e)
```

---

## Phase 4: Migrate Skill Base Classes

**Changes to `nexus3/skill/base.py`:**

| Method | Lines | Change |
|--------|-------|--------|
| `FileSkill._validate_path()` | 456-462 | Use `PathResolver.resolve()` |
| `ExecutionSkill._resolve_working_directory()` | 836-872 | Use `PathResolver.resolve_cwd()` |
| `FilteredCommandSkill._validate_cwd()` | 1077-1105 | Use `PathResolver.resolve_cwd()` |

Each skill base class will instantiate PathResolver with its services:
```python
def _validate_path(self, path: str) -> Path | ToolResult:
    from nexus3.core.resolver import PathResolver
    resolver = PathResolver(self._services)
    try:
        return resolver.resolve(path, tool_name=self.name)
    except PathSecurityError as e:
        return ToolResult(error=str(e))
```

---

## Phase 5: Path.cwd() Bug Fixes

| File | Line | Issue | Fix |
|------|------|-------|-----|
| `cli/repl.py` | 770 | `os.getcwd()` in session save | Get from agent's services |
| `cli/repl.py` | 807 | `os.getcwd()` in session save | Get from agent's services |
| `cli/repl.py` | 1445 | `os.getcwd()` in session save | Get from agent's services |
| `commands/core.py` | 513 | `/save` uses `os.getcwd()` | Get from agent's services |
| `session/session.py` | 464 | `Path.cwd()` fallback | Get from services |
| `cli/repl.py` | 182 | Preview shows wrong cwd | Get from current agent |

---

## Test Strategy

**Run after each phase:**
```bash
pytest tests/unit/ -v
pytest tests/integration/ -v
ruff check nexus3/
mypy nexus3/
```

**Existing tests to verify:**
- `tests/unit/test_config_loader_layered.py` - deep_merge, ancestor discovery
- `tests/unit/test_context_loader.py` - context loading

**New tests needed:**
- `tests/unit/test_core_constants.py` - path functions
- `tests/unit/test_core_utils.py` - move existing deep_merge tests
- `tests/unit/test_path_resolver.py` - relative resolution, per-tool paths, error cases

---

## Backwards Compatibility

1. `context/__init__.py` re-exports `deep_merge` from `core.utils`
2. Skills keep same external API (PathResolver is internal)
3. ServiceContainer already has `get_cwd()` - no changes needed

---

## Risk Assessment

| Phase | Risk | Mitigation |
|-------|------|------------|
| 1. Constants | Low | Simple string replacement |
| 2. Utils | Low | Identical implementations |
| 3. PathResolver | Medium | Unifies existing tested code |
| 4. Migration | Medium | Incremental, test each skill |
| 5. Bug fixes | Low | Small targeted changes |
