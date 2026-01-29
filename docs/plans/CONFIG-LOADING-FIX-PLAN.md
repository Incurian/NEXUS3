# Plan: Config Loading Fix (Unified Approach)

## Overview

Fix configuration loading issues by unifying the duplicate JSON loading code and fixing Windows path handling in one place.

**Issues:**
1. Home directory config not loaded on Windows/Git Bash (path format mismatch)
2. Global directory loaded twice (as global AND ancestor)
3. Duplicate `_load_json_file()` implementations
4. Silent failures with no diagnostics

## User-Reported Issue

**Environment**: Windows 11 + Git Bash
**Scenario**: Home config exists (`~/.nexus3/config.json`), no project config
**Symptom**: Error references `OPENROUTER_API_KEY` from DEFAULT config, not user's home config
**Error**: `ProviderError: API key not found. Set the OPENROUTER_API_KEY environment variable.`

## Root Cause

1. **Windows Path Mismatch**: `Path.home()` may return Unix-style `/c/Users/...` in Git Bash, but `path.exists()` fails without `Path.resolve()`

2. **Duplicate Code**: Two separate JSON loading implementations:
   - `config/load_utils.py` → `load_json_file()` - raises if not found
   - `config/loader.py` → `_load_json_file()` - returns None if not found

   The Windows fix needs to be applied to BOTH, but they're separate.

3. **Ancestor Overlap**: `find_ancestor_config_dirs()` doesn't exclude global directory

## Design Decision: Unify JSON Loading

Instead of fixing the Windows issue in multiple places, unify the JSON loading:

| Function | Behavior | Use Case |
|----------|----------|----------|
| `load_json_file(path)` | Raises `LoadError` if not found | Required files |
| `load_json_file_optional(path)` | Returns `None` if not found | Optional config layers |

Both will use `Path.resolve()` for Windows compatibility.

## Scope

### Included
- Unify JSON loading in `load_utils.py`
- Fix Windows path handling (single location)
- Fix ancestor/global overlap
- Add debug logging
- Better error messages

### Deferred
- None

### Explicitly Excluded
- Config schema changes

## Implementation Details

### Phase 1: Unify JSON Loading

**File: `nexus3/config/load_utils.py`**

Add `load_json_file_optional()` and add `resolve()` to both functions:

```python
"""Unified JSON loading utility for config and context files."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from nexus3.core.errors import LoadError

logger = logging.getLogger(__name__)


def load_json_file(path: Path, error_context: str = "") -> dict[str, Any]:
    """Load and parse a JSON file with consistent error handling.

    Args:
        path: Path to the JSON file to load.
        error_context: Optional context string for error messages.

    Returns:
        Parsed JSON as a dict. Returns empty dict if file is empty.

    Raises:
        LoadError: If the file doesn't exist, can't be read, or contains invalid JSON.
    """
    context_prefix = f"{error_context}: " if error_context else ""

    # Use resolve() for Windows compatibility (Git Bash path format)
    resolved = path.resolve()

    if not resolved.exists():
        raise LoadError(f"{context_prefix}File not found: {path}")

    try:
        content = resolved.read_text(encoding="utf-8-sig")
    except OSError as e:
        raise LoadError(f"{context_prefix}Failed to read file {path}: {e}") from e

    content = content.strip()
    if not content:
        return {}

    try:
        result = json.loads(content)
    except json.JSONDecodeError as e:
        raise LoadError(f"{context_prefix}Invalid JSON in {path}: {e}") from e

    if not isinstance(result, dict):
        raise LoadError(
            f"{context_prefix}Expected object in {path}, got {type(result).__name__}"
        )

    return result


def load_json_file_optional(path: Path, error_context: str = "") -> dict[str, Any] | None:
    """Load JSON file if it exists, returning None for missing files.

    Use this for optional config layers (global, ancestor, local) where the
    file may or may not exist.

    Args:
        path: Path to the JSON file to load.
        error_context: Optional context string for error messages.

    Returns:
        Parsed JSON as dict, empty dict for empty files, or None if file missing.

    Raises:
        LoadError: If file exists but can't be read or contains invalid JSON.
    """
    # Use resolve() for Windows compatibility (Git Bash path format)
    resolved = path.resolve()

    if not resolved.is_file():
        logger.debug("Config file not found: %s (resolved: %s)", path, resolved)
        return None

    logger.debug("Loading config file: %s", resolved)
    return load_json_file(resolved, error_context)
```

### Phase 2: Update config/loader.py

**File: `nexus3/config/loader.py`**

Remove BOTH `_load_json_file()` AND `_load_from_path()`, use unified functions, exclude global from ancestors.

**Why also `_load_from_path()`?** It duplicates JSON loading logic (lines 152-163). Use unified `load_json_file()` (required variant) instead:

```python
"""Configuration loading with fail-fast behavior and layered merging."""

import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from nexus3.config.schema import Config
from nexus3.config.load_utils import load_json_file, load_json_file_optional
from nexus3.core.constants import get_defaults_dir, get_nexus_dir
from nexus3.core.errors import ConfigError, LoadError
from nexus3.core.utils import deep_merge, find_ancestor_config_dirs

logger = logging.getLogger(__name__)

# Path to shipped defaults in the install directory
DEFAULTS_DIR = get_defaults_dir()
DEFAULT_CONFIG = DEFAULTS_DIR / "config.json"


# DELETE _load_json_file() - use load_json_file_optional() instead

# SIMPLIFY _load_from_path() - use load_json_file() instead of inline parsing
def _load_from_path(path: Path) -> Config:
    """Load and validate config from a specific path."""
    try:
        data = load_json_file(path, error_context="config")
    except LoadError as e:
        raise ConfigError(e.message) from e  # Use e.message for consistency

    try:
        return Config.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"Config validation failed for {path}: {e}") from e


def load_config(path: Path | None = None, cwd: Path | None = None) -> Config:
    """Load configuration from file with layered merging."""
    if path is not None:
        return _load_from_path(path)

    effective_cwd = cwd or Path.cwd()
    merged: dict[str, Any] = {}
    loaded_from: list[Path] = []

    # Layer 1: Shipped defaults
    default_data = load_json_file_optional(DEFAULT_CONFIG)
    if default_data:
        merged = deep_merge(merged, default_data)
        loaded_from.append(DEFAULT_CONFIG)

    # Layer 2: Global user config
    global_config = get_nexus_dir() / "config.json"
    global_data = load_json_file_optional(global_config)
    if global_data:
        merged = deep_merge(merged, global_data)
        loaded_from.append(global_config)
    else:
        logger.debug("No global config at: %s", global_config)

    # Layer 3: Ancestor directories
    # Determine ancestor_depth (check local first for override)
    local_config = effective_cwd / ".nexus3" / "config.json"
    local_depth = None
    local_data_peek = load_json_file_optional(local_config)
    if local_data_peek:
        local_depth = local_data_peek.get("context", {}).get("ancestor_depth")
    ancestor_depth = (
        local_depth
        if local_depth is not None
        else merged.get("context", {}).get("ancestor_depth", 2)
    )

    # BUGFIX: Exclude global dir to avoid loading it twice
    global_dir = get_nexus_dir()
    ancestor_dirs = find_ancestor_config_dirs(
        effective_cwd,
        ancestor_depth,
        exclude_paths=[global_dir],
    )

    for ancestor_dir in ancestor_dirs:
        ancestor_config = ancestor_dir / "config.json"
        ancestor_data = load_json_file_optional(ancestor_config)
        if ancestor_data:
            merged = deep_merge(merged, ancestor_data)
            loaded_from.append(ancestor_config)

    # Layer 4: Project local config
    local_data = load_json_file_optional(local_config)
    if local_data:
        merged = deep_merge(merged, local_data)
        loaded_from.append(local_config)

    # Log final sources for debugging
    if loaded_from:
        logger.info("Config loaded from: %s", [str(p) for p in loaded_from])
    else:
        logger.debug("No config files found, using defaults")

    # Validate merged config
    if not merged:
        return Config()

    try:
        return Config.model_validate(merged)
    except ValidationError as e:
        sources = ", ".join(str(p) for p in loaded_from)
        raise ConfigError(f"Config validation failed (merged from {sources}): {e}") from e
```

### Phase 3: Update context/loader.py

**File: `nexus3/context/loader.py`**

Replace `_load_json()` wrapper, exclude global from ancestors:

```python
# In imports, add:
from nexus3.config.load_utils import load_json_file_optional

# DELETE _load_json() method - use load_json_file_optional() directly

# In _load_layer(), change:
#   layer.config = self._load_json(config_path)
# To:
    try:
        layer.config = load_json_file_optional(config_path)
    except LoadError as e:
        raise ContextLoadError(e.message) from e  # Use e.message for consistency

# In load(), add exclusion:
    # 2. Load ancestors (exclude global dir to avoid duplicate)
    global_dir = self._get_global_dir()
    ancestor_dirs = find_ancestor_config_dirs(
        self._cwd,
        self._config.ancestor_depth,
        exclude_paths=[global_dir],
    )
```

### Phase 4: Update find_ancestor_config_dirs

**File: `nexus3/core/utils.py`**

Add `exclude_paths` parameter:

```python
def find_ancestor_config_dirs(
    cwd: Path,
    max_depth: int = 2,
    exclude_paths: list[Path] | None = None,
) -> list[Path]:
    """Find .nexus3 directories in ancestor paths.

    Args:
        cwd: Starting directory.
        max_depth: Maximum number of ancestor levels to check.
        exclude_paths: Paths to exclude (e.g., global dir). Uses resolve() for comparison.

    Returns:
        List of ancestor config directories (furthest to nearest).
    """
    ancestors = []
    # Use resolve() for consistent cross-platform comparison
    current = cwd.resolve().parent

    # Normalize exclude paths for comparison
    excluded_resolved = set()
    if exclude_paths:
        excluded_resolved = {p.resolve() for p in exclude_paths}

    for _ in range(max_depth):
        if current == current.parent:  # Reached root
            break
        config_dir = current / NEXUS_DIR_NAME
        if config_dir.is_dir():
            # Skip if this matches an excluded path (e.g., global dir)
            if config_dir.resolve() not in excluded_resolved:
                ancestors.append(config_dir)
        current = current.parent

    return list(reversed(ancestors))
```

### Phase 5: Better Error Messages + Graceful Failure

**File: `nexus3/provider/base.py`**

Improve API key error to show config sources:

```python
def _get_api_key(self) -> str:
    """Get API key from environment or config."""
    # ... existing lookup logic ...

    if not api_key:
        from nexus3.core.constants import get_nexus_dir
        global_config = get_nexus_dir() / "config.json"

        msg = f"API key not found. Set the {self._config.api_key_env} environment variable."

        # Help diagnose config loading issues
        if not global_config.resolve().is_file():
            msg += f"\n\nNote: No config found at {global_config}"
            msg += "\nExpected location: ~/.nexus3/config.json"
        else:
            msg += f"\n\nConfig exists at: {global_config}"
            msg += "\nCheck your provider's api_key_env setting."

        raise ProviderError(msg)
```

**File: `nexus3/cli/repl_commands.py`**

Catch `ProviderError` in `cmd_model()` (~line 1445) to prevent crash:

```python
from nexus3.core.errors import ProviderError

# In cmd_model(), wrap the provider_registry.get() call:
if provider_registry is not None:
    try:
        new_provider = provider_registry.get(
            new_model.provider_name, new_model.model_id, new_model.reasoning
        )
        agent.session.provider = new_provider
    except ProviderError as e:
        return CommandOutput.error(f"Failed to switch model: {e.message}")
```

**File: `nexus3/rpc/bootstrap.py` or `nexus3/rpc/pool.py`**

Catch `ProviderError` during agent creation to fail gracefully instead of crash:

```python
# Wherever providers are first created, wrap with try/except
try:
    provider = provider_registry.get(...)
except ProviderError as e:
    # Log error and raise a user-friendly error
    raise AgentCreationError(f"Provider initialization failed: {e.message}") from e
```

### Phase 6: Update Exports

**File: `nexus3/config/__init__.py`**

Add new function to exports:

```python
from nexus3.config.load_utils import load_json_file, load_json_file_optional

__all__ = [
    # ... existing ...
    "load_json_file",
    "load_json_file_optional",
]
```

## Testing Strategy

### Unit Tests

**File: `tests/unit/test_load_utils.py`**

```python
def test_load_json_file_optional_missing(tmp_path):
    """Returns None for missing file."""
    result = load_json_file_optional(tmp_path / "missing.json")
    assert result is None


def test_load_json_file_optional_exists(tmp_path):
    """Loads existing file."""
    config = tmp_path / "config.json"
    config.write_text('{"key": "value"}')
    result = load_json_file_optional(config)
    assert result == {"key": "value"}


def test_load_json_file_optional_invalid_json(tmp_path):
    """Raises LoadError for invalid JSON."""
    config = tmp_path / "config.json"
    config.write_text('not json')
    with pytest.raises(LoadError):
        load_json_file_optional(config)


def test_load_json_file_uses_resolve(tmp_path, monkeypatch):
    """Path.resolve() is called for Windows compatibility."""
    config = tmp_path / "config.json"
    config.write_text('{}')

    # Track resolve() calls
    original_resolve = Path.resolve
    resolve_called = []
    def tracking_resolve(self):
        resolve_called.append(self)
        return original_resolve(self)

    monkeypatch.setattr(Path, "resolve", tracking_resolve)
    load_json_file_optional(config)
    assert len(resolve_called) > 0
```

**File: `tests/unit/test_ancestor_discovery.py`**

```python
def test_excludes_specified_paths(tmp_path):
    """Should not include excluded paths in results."""
    global_dir = tmp_path / ".nexus3"
    global_dir.mkdir()
    project = tmp_path / "projects" / "myapp"
    project.mkdir(parents=True)

    # Without exclusion
    ancestors = find_ancestor_config_dirs(project, max_depth=3)
    assert global_dir in ancestors

    # With exclusion
    ancestors = find_ancestor_config_dirs(project, max_depth=3, exclude_paths=[global_dir])
    assert global_dir not in ancestors


def test_exclusion_uses_resolved_paths(tmp_path):
    """Exclusion comparison should work across path formats."""
    global_dir = tmp_path / ".nexus3"
    global_dir.mkdir()
    project = tmp_path / "projects" / "myapp"
    project.mkdir(parents=True)

    # Exclude using non-resolved path
    ancestors = find_ancestor_config_dirs(
        project,
        max_depth=3,
        exclude_paths=[tmp_path / ".nexus3"]  # Not resolved
    )
    assert global_dir not in ancestors
```

### Integration Tests

**File: `tests/integration/test_config_loading.py`**

```python
def test_global_config_not_duplicated_as_ancestor(tmp_path, monkeypatch):
    """Global dir should not appear in both global and ancestor sources."""
    # Setup: home/.nexus3 and home/projects/app
    home = tmp_path / "home"
    nexus_dir = home / ".nexus3"
    nexus_dir.mkdir(parents=True)
    (nexus_dir / "config.json").write_text('{"test": "global"}')

    project = home / "projects" / "app"
    project.mkdir(parents=True)

    # Mock Path.home()
    monkeypatch.setattr(Path, "home", lambda: home)

    # Load config from project dir
    config = load_config(cwd=project)

    # Verify global was loaded (not just defaults)
    # This would fail on Windows before the fix
    assert config is not None
```

### Live Testing (Windows)

1. On Windows with Git Bash:
   ```bash
   # Create home config with unique API key env
   mkdir -p ~/.nexus3
   echo '{"providers":{"test":{"type":"openai","api_key_env":"MY_CUSTOM_KEY"}}}' > ~/.nexus3/config.json

   # Run nexus3 with debug logging
   NEXUS_LOG_LEVEL=DEBUG nexus3

   # Should see: "Config loaded from: ['/c/Users/.../config.json']"
   # NOT just the defaults
   ```

2. Verify no duplicate loading:
   ```bash
   # With verbose logging, should NOT see global loaded twice
   ```

## Implementation Checklist

### Phase 1: Unify JSON Loading
- [x] **P1.1** Add `load_json_file_optional()` to `nexus3/config/load_utils.py`
- [x] **P1.2** Add `Path.resolve()` to both functions in `load_utils.py`
- [x] **P1.3** Add debug logging to `load_json_file_optional()`
- [x] **P1.4** Update `nexus3/config/__init__.py` exports

### Phase 2: Update Loaders
- [x] **P2.1** Delete `_load_json_file()` from `nexus3/config/loader.py`
- [x] **P2.2** Simplify `_load_from_path()` to use `load_json_file()` (required variant)
- [x] **P2.3** Update `load_config()` to use `load_json_file_optional()`
- [x] **P2.4** Add `exclude_paths=[global_dir]` to ancestor discovery in `load_config()`
- [x] **P2.5** Delete `_load_json()` from `nexus3/context/loader.py`
- [x] **P2.6** Update `ContextLoader._load_layer()` to use `load_json_file_optional()`
- [x] **P2.7** Add `exclude_paths=[global_dir]` to ancestor discovery in `ContextLoader.load()`

### Phase 3: Update Utilities
- [x] **P3.1** Add `exclude_paths` parameter to `find_ancestor_config_dirs()`
- [x] **P3.2** Use `Path.resolve()` in ancestor comparison

### Phase 4: Better Errors (No Crash)
- [x] **P4.1** Improve API key error message in `nexus3/provider/base.py`
- [x] **P4.2** Catch `ProviderError` in `cmd_model()` (`nexus3/cli/repl_commands.py` ~line 1445)
- [x] **P4.3** Catch `ProviderError` in agent creation paths (global_dispatcher, repl)

### Phase 5: Tests
- [x] **P5.1** Add tests for `load_json_file_optional()`
- [x] **P5.2** Add tests for `exclude_paths` in `find_ancestor_config_dirs()`
- [x] **P5.3** Add integration test for no-duplicate loading

### Phase 6: Documentation
- [x] **P6.1** Update `nexus3/config/README.md` with `load_json_file_optional()` function
- [x] **P6.2** Remove references to `_load_json_file()` in `nexus3/config/README.md`
- [x] **P6.3** Verified `nexus3/defaults/README.md` does not reference `_load_json_file()`

## Quick Reference

| File | Change |
|------|--------|
| `nexus3/config/load_utils.py` | Add `load_json_file_optional()`, add `resolve()` to both |
| `nexus3/config/loader.py` | Delete `_load_json_file()`, simplify `_load_from_path()`, use unified, exclude global |
| `nexus3/context/loader.py` | Delete `_load_json()`, use unified, exclude global |
| `nexus3/core/utils.py` | Add `exclude_paths` to `find_ancestor_config_dirs()` |
| `nexus3/provider/base.py` | Better API key error message |
| `nexus3/cli/repl_commands.py` | Catch `ProviderError` in `/model` command |
| `nexus3/rpc/pool.py` | Catch `ProviderError` during agent creation |
| `nexus3/config/__init__.py` | Export new function |
