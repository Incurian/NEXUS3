# Plan: Split NEXUS.md Context

## OPEN QUESTIONS

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| **Q1** | Content split? | A) Minimal defaults B) Balanced C) Comprehensive defaults | **B) Balanced** - tools/limits in defaults, identity in user's |
| **Q2** | File naming? | A) NEXUS-DEFAULT.md B) NEXUS-SYSTEM.md C) NEXUS-BASE.md | **A) NEXUS-DEFAULT.md** |
| **Q3** | Section order? | A) defaults→user→project B) user→defaults→project | **A) defaults first** |

---

## Overview

**Problem:** Users who customize `~/.nexus3/NEXUS.md` lose ability to get tool documentation updates from package upgrades.

**Solution:** Split into two files:
- `NEXUS-DEFAULT.md` - Tool docs, permissions, limits (lives in package only, auto-updates)
- `NEXUS.md` - User's custom identity/instructions (in ~/.nexus3/, preserved)

**Key simplification:** NEXUS-DEFAULT.md lives ONLY in the package (`nexus3/defaults/`). No copying to user home. Package upgrades automatically bring new defaults.

---

## Scope

### Included
- Create `NEXUS-DEFAULT.md` in package defaults
- Update loader to load package defaults + user's NEXUS.md
- Backwards compatible with existing single-file setup

### NOT Included (Simplified Away)
- ~~`--update-defaults` CLI command~~ (not needed - package always has latest)
- ~~Copying NEXUS-DEFAULT.md to ~/.nexus3/~~ (not needed)
- ~~Migration commands~~ (not needed)

---

## Architecture

### File Layout
```
nexus3/defaults/
├── NEXUS-DEFAULT.md    # Tool docs, permissions, limits (ALWAYS loaded from here)
└── NEXUS.md            # Identity template (copied to ~/.nexus3/ on init)

~/.nexus3/
└── NEXUS.md            # User's customizations (optional)
```

### Loading Order
1. `nexus3/defaults/NEXUS-DEFAULT.md` (always from package)
2. `~/.nexus3/NEXUS.md` (user's, if exists) OR `nexus3/defaults/NEXUS.md` (fallback)
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

    System defaults (NEXUS-DEFAULT.md) always come from the package.
    User customization (NEXUS.md) comes from ~/.nexus3/ if it exists,
    otherwise falls back to package template.

    Returns:
        List of layers: [system-defaults layer, user/global layer]
    """
    layers = []
    global_dir = self._get_global_dir()
    defaults_dir = self._get_defaults_dir()

    # 1. Always load NEXUS-DEFAULT.md from package (system docs/tools)
    pkg_default = defaults_dir / "NEXUS-DEFAULT.md"
    if pkg_default.is_file():
        layer = ContextLayer(name="system-defaults", path=defaults_dir)
        layer.prompt = pkg_default.read_text(encoding="utf-8-sig")
        layers.append(layer)

    # 2. Load user's NEXUS.md from global dir, or fall back to package template
    user_nexus = global_dir / "NEXUS.md"
    if user_nexus.is_file():
        layer = ContextLayer(name="global", path=global_dir)
        layer.prompt = user_nexus.read_text(encoding="utf-8-sig")
        # Also load config/mcp from global dir
        layer.config = self._load_json_optional(global_dir / "config.json")
        layer.mcp = self._load_json_optional(global_dir / "mcp.json")
        layers.append(layer)
    else:
        # Fall back to package NEXUS.md template
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

### Phase 3: Update Init (Simplified)

**File:** `nexus3/cli/init_commands.py`

`init_global()` only needs to copy the user's NEXUS.md template (not NEXUS-DEFAULT.md):

```python
# Copy NEXUS.md template from defaults (user can customize this)
default_nexus = defaults_dir / "NEXUS.md"
if default_nexus.exists():
    _safe_write_text(
        global_dir / "NEXUS.md",
        default_nexus.read_text(encoding="utf-8"),
    )

# NOTE: NEXUS-DEFAULT.md is NOT copied - it's always loaded from package
```

---

## Migration

**Existing users:** Everything works unchanged. Old single-file setup continues to work.

**Benefits of this approach:**
- Package upgrades automatically include new tool documentation
- No manual `--update-defaults` step needed
- User customizations in `~/.nexus3/NEXUS.md` are never overwritten
- Simpler mental model: package has docs, user has identity

---

## Files to Modify

| File | Change |
|------|--------|
| `nexus3/defaults/NEXUS-DEFAULT.md` | NEW - tool/permission content |
| `nexus3/defaults/NEXUS.md` | Reduce to identity only |
| `nexus3/context/loader.py` | Return type change, load both files |
| `nexus3/cli/init_commands.py` | Remove NEXUS-DEFAULT.md copying (if any) |

---

## Implementation Checklist

### Phase 1: Split Files
- [ ] **P1.1** Create `nexus3/defaults/NEXUS-DEFAULT.md` with tool/permission content
- [ ] **P1.2** Reduce `nexus3/defaults/NEXUS.md` to identity/principles

### Phase 2: Loader
- [ ] **P2.1** Change `_load_global_layer()` return type to `list[ContextLayer]`
- [ ] **P2.2** Update `_load_global_layer()` to always load package NEXUS-DEFAULT.md first
- [ ] **P2.3** Update `_load_global_layer()` to load user NEXUS.md or package fallback
- [ ] **P2.4** Update `load()` caller to iterate over list
- [ ] **P2.5** Add "system-defaults" section header handling in `_format_prompt_section()`

### Phase 3: Init (Simplified)
- [ ] **P3.1** Verify `init_global()` only copies NEXUS.md template (not NEXUS-DEFAULT.md)

### Phase 4: Testing
- [ ] **P4.1** Test fresh install loads both package files
- [ ] **P4.2** Test user with custom ~/.nexus3/NEXUS.md gets package defaults + their custom
- [ ] **P4.3** Test backwards compat with old single-file setup (no NEXUS-DEFAULT.md)
- [ ] **P4.4** Test section headers appear correctly in context

### Phase 5: Documentation
- [ ] **P5.1** Update CLAUDE.md Context Management section

---

## Effort Estimate

~1-2 hours implementation, ~30 minutes testing.
