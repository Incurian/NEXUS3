# Plan: Split NEXUS.md Context

## OPEN QUESTIONS

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| **Q1** | Content split? | A) Minimal defaults B) Balanced C) Comprehensive defaults | **B) Balanced** - tools/limits in defaults, identity in user's |
| **Q2** | Update mechanism? | A) Copy from package B) Fetch remote C) Version-check | **A) Copy** - simple, offline |
| **Q3** | File naming? | A) NEXUS-DEFAULT.md B) NEXUS-SYSTEM.md C) NEXUS-BASE.md | **A) NEXUS-DEFAULT.md** |
| **Q4** | Migration for existing users? | A) Automatic B) Manual C) No migration | **C) No migration** - backwards compat |
| **Q5** | Section order? | A) defaults→user→project B) user→defaults→project | **A) defaults first** |

---

## Overview

**Problem:** Users who customize `~/.nexus3/NEXUS.md` lose ability to get tool documentation updates from package upgrades.

**Solution:** Split into two files:
- `NEXUS-DEFAULT.md` - Tool docs, permissions, limits (updatable from package)
- `NEXUS.md` - User's custom identity/instructions (preserved on updates)

---

## Scope

### Included
- Create `NEXUS-DEFAULT.md` in package defaults
- Update loader to load both files
- `--update-defaults` CLI command
- `--init-global` creates both files

### Deferred
- Automatic migration of existing installs
- Version tracking

---

## Architecture

### File Layout
```
nexus3/defaults/
├── NEXUS-DEFAULT.md    # Tool docs, permissions, limits
└── NEXUS.md            # Identity template

~/.nexus3/
├── NEXUS-DEFAULT.md    # Copied from package, updatable
└── NEXUS.md            # User's customizations
```

### Loading Order
1. `~/.nexus3/NEXUS-DEFAULT.md` (or package fallback)
2. `~/.nexus3/NEXUS.md` (user's)
3. Ancestor `.nexus3/NEXUS.md`
4. Local `.nexus3/NEXUS.md`

### Content Split

Based on current 281-line `nexus3/defaults/NEXUS.md`:

**Move to NEXUS-DEFAULT.md (~230 lines):**
- Permission System (levels, ceiling, RPC quirks)
- Logs (server log, session logs, SQLite schema)
- Tool Limits (file size, timeouts, context recovery)
- Available Tools (tables of all tools)
- Agent Communication Details
- Execution Modes (sequential/parallel)
- Path Formats (WSL)
- Self-Knowledge (NEXUS3 development)

**Keep in NEXUS.md (~50 lines):**
- Agent identity, principles, role description
- Response Format (behavioral guidance)

---

## Implementation

### Phase 1: Create Split Files

**File:** `nexus3/defaults/NEXUS-DEFAULT.md` (NEW)

Create with tool/system documentation extracted from current NEXUS.md.

**File:** `nexus3/defaults/NEXUS.md` (MODIFY)

Reduce to identity/behavioral content only.

### Phase 2: Update Loader

**File:** `nexus3/context/loader.py`

**Critical Change:** `_load_global_layer()` return type changes from `ContextLayer | None` to `list[ContextLayer]`.

**Current signature (line 256):**
```python
def _load_global_layer(self) -> ContextLayer | None:
```

**New signature:**
```python
def _load_global_layer(self) -> list[ContextLayer]:
```

**New implementation:**
```python
def _load_global_layer(self) -> list[ContextLayer]:
    """Load the global layer with both system defaults and user customization.

    Returns:
        List of layers: [system-defaults layer, user NEXUS.md layer]
    """
    layers = []
    global_dir = self._get_global_dir()
    defaults_dir = self._get_defaults_dir()

    # 1. Load NEXUS-DEFAULT.md (system docs/tools)
    user_default = global_dir / "NEXUS-DEFAULT.md"
    if user_default.is_file():
        layer = ContextLayer(name="system-defaults", path=global_dir)
        layer.prompt = user_default.read_text(encoding="utf-8-sig")
        layers.append(layer)
    else:
        # Fallback to package NEXUS-DEFAULT.md
        pkg_default = defaults_dir / "NEXUS-DEFAULT.md"
        if pkg_default.is_file():
            layer = ContextLayer(name="system-defaults", path=defaults_dir)
            layer.prompt = pkg_default.read_text(encoding="utf-8-sig")
            layers.append(layer)

    # 2. Load user's NEXUS.md (identity/customization)
    user_nexus = global_dir / "NEXUS.md"
    if user_nexus.is_file():
        layer = ContextLayer(name="global", path=global_dir)
        layer.prompt = user_nexus.read_text(encoding="utf-8-sig")
        # Also load config/mcp from global dir
        layer.config = self._load_json_optional(global_dir / "config.json")
        layer.mcp = self._load_json_optional(global_dir / "mcp.json")
        layers.append(layer)
    elif not layers:
        # If user has no NEXUS.md and no NEXUS-DEFAULT.md, fall back to package NEXUS.md
        pkg_nexus = defaults_dir / "NEXUS.md"
        if pkg_nexus.is_file():
            layer = ContextLayer(name="global", path=defaults_dir)
            layer.prompt = pkg_nexus.read_text(encoding="utf-8-sig")
            layers.append(layer)

    return layers
```

**Update caller in `load()` method (lines 504-517):**

```python
# Current:
global_layer = self._load_global_layer()
if global_layer:
    layers.append(global_layer)
    # ... rest of handling

# Change to:
global_layers = self._load_global_layer()
for global_layer in global_layers:
    layers.append(global_layer)
    if global_layer.name == "global":
        sources.global_dir = self._get_global_dir()

    section = self._format_prompt_section(global_layer, sources)
    if section:
        prompt_sections.append(section)

    if global_layer.config:
        merged_config = deep_merge(merged_config, global_layer.config)
        sources.config_sources.append(global_layer.path / "config.json")
```

**Add section header for "system-defaults" in `_format_prompt_section()` (after line 357):**

```python
if layer.name == "system-defaults":
    source_path = layer.path / "NEXUS-DEFAULT.md"
    header = "## System Defaults"
elif layer.name == "defaults":
    # ... existing code
```

### Phase 3: Update Init Commands

**File:** `nexus3/cli/init_commands.py`

**Add new function:**
```python
def update_defaults() -> tuple[bool, str]:
    """Update NEXUS-DEFAULT.md in global directory from package.

    Copies the latest NEXUS-DEFAULT.md from the package to ~/.nexus3/,
    allowing users to get updated tool documentation without overwriting
    their personal NEXUS.md customizations.

    Returns:
        Tuple of (success, message).
    """
    global_dir = get_nexus_dir()
    defaults_dir = get_defaults_dir()

    if not global_dir.exists():
        return False, f"Global directory not initialized: {global_dir}\nRun 'nexus3 --init-global' first."

    pkg_default = defaults_dir / "NEXUS-DEFAULT.md"
    if not pkg_default.exists():
        return False, f"Package defaults not found: {pkg_default}"

    try:
        user_default = global_dir / "NEXUS-DEFAULT.md"
        _safe_write_text(user_default, pkg_default.read_text(encoding="utf-8"))
        return True, f"Updated system defaults at {user_default}"
    except InitSymlinkError as e:
        return False, f"Security error: {e}"
    except OSError as e:
        return False, f"Failed to update defaults: {e}"
```

**Update `init_global()` to copy both files:**
```python
# Copy NEXUS-DEFAULT.md from package
default_nexus_default = defaults_dir / "NEXUS-DEFAULT.md"
if default_nexus_default.exists():
    _safe_write_text(
        global_dir / "NEXUS-DEFAULT.md",
        default_nexus_default.read_text(encoding="utf-8"),
    )

# Copy NEXUS.md from defaults
default_nexus = defaults_dir / "NEXUS.md"
if default_nexus.exists():
    _safe_write_text(
        global_dir / "NEXUS.md",
        default_nexus.read_text(encoding="utf-8"),
    )
```

### Phase 4: Add CLI Argument

**File:** `nexus3/cli/arg_parser.py` (after line 312)

```python
parser.add_argument(
    "--update-defaults",
    action="store_true",
    help="Update ~/.nexus3/NEXUS-DEFAULT.md from package defaults and exit",
)
```

**File:** `nexus3/cli/repl.py` (after line 1917, with other init handling)

```python
# Handle update-defaults command
if hasattr(args, 'update_defaults') and args.update_defaults:
    from nexus3.cli.init_commands import update_defaults

    success, message = update_defaults()
    print(message)
    raise SystemExit(0 if success else 1)
```

---

## Migration

**Existing users:** Everything works unchanged. Old single-file setup continues to work.

**Optional migration:**
1. Run `nexus3 --update-defaults` to add `NEXUS-DEFAULT.md`
2. Optionally remove duplicate tool docs from personal `NEXUS.md`

---

## Files to Modify

| File | Change |
|------|--------|
| `nexus3/defaults/NEXUS-DEFAULT.md` | NEW - tool/permission content |
| `nexus3/defaults/NEXUS.md` | Reduce to identity only |
| `nexus3/context/loader.py` | Return type change, load both files |
| `nexus3/cli/init_commands.py` | Add `update_defaults()`, modify `init_global()` |
| `nexus3/cli/arg_parser.py` | Add `--update-defaults` |
| `nexus3/cli/repl.py` | Add handler for `--update-defaults` |

---

## Implementation Checklist

### Phase 1: Split Files
- [ ] **P1.1** Create `nexus3/defaults/NEXUS-DEFAULT.md` with tool/permission content
- [ ] **P1.2** Reduce `nexus3/defaults/NEXUS.md` to identity/principles

### Phase 2: Loader
- [ ] **P2.1** Change `_load_global_layer()` return type to `list[ContextLayer]`
- [ ] **P2.2** Update `_load_global_layer()` to load both files
- [ ] **P2.3** Update `load()` caller to iterate over list
- [ ] **P2.4** Add "system-defaults" section header handling

### Phase 3: Commands
- [ ] **P3.1** Add `update_defaults()` function to init_commands.py
- [ ] **P3.2** Add `--update-defaults` CLI flag to arg_parser.py
- [ ] **P3.3** Add handler in repl.py for --update-defaults
- [ ] **P3.4** Update `init_global()` to copy both files

### Phase 4: Testing
- [ ] **P4.1** Test new install creates both files
- [ ] **P4.2** Test `--update-defaults` copies NEXUS-DEFAULT.md
- [ ] **P4.3** Test backwards compat with old single-file setup
- [ ] **P4.4** Test section headers appear correctly in context

### Phase 5: Documentation
- [ ] **P5.1** Update CLAUDE.md Context Management section
- [ ] **P5.2** Document migration for existing users

---

## Effort Estimate

~2-3 hours implementation, ~1 hour testing.
