# Plan: Configurable Instruction File Priority

## Overview

NEXUS3 currently hardcodes `NEXUS.md` as the instruction filename across the context loading system. This makes NEXUS3 projects invisible to other tools (Claude Code looks for `CLAUDE.md`, the open AGENTS.md standard uses `AGENTS.md`) and vice versa.

This feature makes the instruction filename configurable via an ordered priority list, enabling cross-tool compatibility while preserving NEXUS3's existing layered context architecture.

**Current state:**
- `ContextLoader._load_layer()` hardcodes `NEXUS.md` as the only instruction file (line 221)
- `_load_global_layer()` hardcodes `~/.nexus3/NEXUS.md` (line 282)
- `_format_prompt_section()` hardcodes `NEXUS.md` in source path labels (lines 371-381)
- `load_for_subagent()` hardcodes `.nexus3/NEXUS.md` and `NEXUS.md` (lines 604, 608)
- `init_local()` creates `.nexus3/NEXUS.md` (line 167)
- `init_global()` creates `~/.nexus3/NEXUS.md` (line 109)
- `ContextConfig` has `include_readme` and `readme_as_fallback` fields for README handling
- No concept of searching multiple filenames or multiple directories per filename

**Goal:** Replace the hardcoded `NEXUS.md` filename with a configurable priority list that searches across standard tool-convention directories, finding the first matching file per layer.

---

## Scope

### Included in v1

| Change | Description |
|--------|-------------|
| `context.instruction_files` config | Ordered priority list with default `["NEXUS.md", "AGENTS.md", "CLAUDE.md", "README.md"]` |
| Per-filename search locations | Each filename checks its tool-convention directories (e.g., CLAUDE.md checks `.claude/`) |
| Priority search in loader | `_load_layer()` iterates the list, first file found wins per layer |
| `/init` filename argument | `/init` creates `.nexus3/AGENTS.md` by default, `/init NEXUS.md` or `/init CLAUDE.md` for others |
| Remove `include_readme` | Replaced by putting `README.md` in the priority list |
| Remove `readme_as_fallback` | Replaced by putting `README.md` at end of priority list |
| `ContextLayer.prompt_source_path` | Track which file was actually loaded (for accurate source labels) |
| Updated `_format_prompt_section()` | Use actual source path instead of hardcoded `NEXUS.md` |
| Updated `load_for_subagent()` | Search using priority list instead of hardcoded filename |

### Deferred to Future

| Feature | Reason |
|---------|--------|
| Cross-tool config directory merging | Only search for instruction files in other tool dirs, not their config.json/mcp.json |
| `--init-global` filename argument | Global always creates `NEXUS.md` (private user config, not cross-tool) |
| Auto-detection of project tool ecosystem | Too complex, priority list is sufficient |

### Explicitly Excluded

| Feature | Reason |
|---------|--------|
| Loading multiple instruction files per layer | Spec says first-found wins, not concatenation |
| Changing `.nexus3/` directory name | Out of scope, config/mcp still live in `.nexus3/` |
| Changing `NEXUS-DEFAULT.md` or `~/.nexus3/NEXUS.md` | System defaults and global config are exempt |
| Changing `config.json` or `mcp.json` loading | Only instruction file discovery changes |

---

## Design Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| Where does search logic live? | `ContextLoader._find_instruction_file()` | Centralizes search in one new method, called by `_load_layer()` and `load_for_subagent()` |
| How to handle README.md in the priority list? | README.md entries use the existing `_format_readme_section()` wrapping | README content is untrusted documentation; wrapping with boundaries is a security measure that must be preserved |
| Should `_format_prompt_section` still label sources as "NEXUS.md"? | No, use actual found filename | Source labels should be accurate for debugging |
| What does `/init` create by default? | `.nexus3/AGENTS.md` (open standard) | AGENTS.md is the emerging open standard for agent instructions; cross-tool compatible |
| Should global init change? | No, always `~/.nexus3/NEXUS.md` | Global config is NEXUS3-private, not cross-tool |
| How to deprecate `include_readme` / `readme_as_fallback`? | Remove from schema, log warning if found in config | Clean break; the priority list subsumes both features |
| What if `instruction_files` is an empty list? | Fall through to no instruction file (same as today when no NEXUS.md exists) | Fail-open matches current behavior |
| Should ancestor layers use the same priority list? | Yes, all non-global layers use the same list | Consistency; the list is a global setting |

---

## Security Considerations

### README.md Injection Risk

The existing `readme_as_fallback` was opt-in because README.md files may contain untrusted content (injection vectors). The new system preserves this safety:

1. **README.md is last in the default list** -- only loaded when no other instruction file exists (equivalent to `readme_as_fallback`).
2. **README content is always wrapped** with `_format_readme_section()` boundaries that explicitly mark it as documentation, not agent instructions.
3. **Users opt in** by including `README.md` in their `instruction_files` list. Removing it from the list disables README loading entirely.

### Cross-Tool Directory Traversal

The search checks `.claude/CLAUDE.md` and `.agents/AGENTS.md` -- directories from other tools. Security mitigations:

1. **Read-only** -- we only read files, never write to other tools' directories.
2. **Symlink defense** -- `_load_file()` uses `path.is_file()` which follows symlinks but returns content (same as current `NEXUS.md` loading). The existing security model already handles symlinks at the write layer.
3. **No credential exposure** -- instruction files are prompt text, not configs. We never read `config.json` or `mcp.json` from other tools' directories.
4. **Explicit opt-in** -- the list is user-configured. If a user doesn't want `.claude/CLAUDE.md` searched, they remove `CLAUDE.md` from the list.

---

## Architecture

### Search Logic

For each layer (ancestor or local), the new `_find_instruction_file()` method iterates the priority list:

```
For filename in instruction_files:
    For location in get_search_locations(filename, layer_dir):
        If file exists at location:
            Return (content, source_path)

Return None  (no instruction file found for this layer)
```

### Search Locations per Filename

| Filename | Locations checked (in order) | Rationale |
|----------|------------------------------|-----------|
| `NEXUS.md` | `.nexus3/NEXUS.md` -> `./NEXUS.md` | NEXUS3 convention + legacy root support |
| `AGENTS.md` | `.nexus3/AGENTS.md` -> `.agents/AGENTS.md` -> `./AGENTS.md` | NEXUS3 dir + open standard dir + root |
| `CLAUDE.md` | `.nexus3/CLAUDE.md` -> `.claude/CLAUDE.md` -> `.agents/CLAUDE.md` -> `./CLAUDE.md` | NEXUS3 dir + Claude Code dir + agents dir + root |
| `README.md` | `./README.md` | Root only (never in config dirs) |
| Other | `.nexus3/{filename}` -> `./{filename}` | Default: NEXUS3 dir + root |

### Affected Files

```
nexus3/
├── config/
│   └── schema.py              # ContextConfig: add instruction_files, remove include_readme/readme_as_fallback
├── context/
│   └── loader.py              # ContextLoader: _find_instruction_file(), _load_layer(), _format_prompt_section(), load_for_subagent()
├── cli/
│   ├── init_commands.py       # init_local(): accept filename arg, default to AGENTS.md
│   └── repl_commands.py       # cmd_init(): parse filename argument
├── defaults/
│   └── config.json            # Update context section
tests/
├── unit/
│   ├── test_context_loader.py # Update existing + add priority search tests
│   └── test_init_commands.py  # Update for new default filename
└── security/
    └── test_p2_18_readme_injection.py  # Update for new README behavior
```

### Files Verified: No Changes Required

These files create `ContextLoader` with `context_config=config.context`, so the new `instruction_files` field flows through automatically:

| File | Usage | Why No Change Needed |
|------|-------|----------------------|
| `nexus3/rpc/pool.py` (line 487) | Creates ContextLoader for subagent context | Passes `context_config=self._shared.config.context` |
| `nexus3/rpc/bootstrap.py` (line 284) | Creates ContextLoader for base context loading | Passes `context_config=config.context` |
| `nexus3/session/session.py` (line 110) | Stores ContextLoader for compaction prompt reload | ContextLoader already has config with `instruction_files` |

---

## Implementation Details

### Phase 1: Config Schema Changes

**File: `nexus3/config/schema.py`**

Replace `include_readme` and `readme_as_fallback` with `instruction_files`:

```python
class ContextConfig(BaseModel):
    """Configuration for context loading.

    Controls how instruction files are loaded from multiple directory layers.

    Example in config.json:
        "context": {
            "ancestor_depth": 2,
            "instruction_files": ["NEXUS.md", "AGENTS.md", "CLAUDE.md", "README.md"]
        }
    """

    model_config = ConfigDict(extra="forbid")

    ancestor_depth: int = Field(
        default=2,
        ge=0,
        le=10,
        description="How many directory levels above CWD to search for .nexus3/",
    )
    instruction_files: list[str] = Field(
        default=["NEXUS.md", "AGENTS.md", "CLAUDE.md", "README.md"],
        description=(
            "Ordered list of instruction filenames to search for in each layer. "
            "First file found wins. README.md entries are wrapped with documentation "
            "boundaries for security."
        ),
    )

    @field_validator("instruction_files", mode="after")
    @classmethod
    def validate_instruction_files(cls, v: list[str]) -> list[str]:
        """Validate instruction file entries are safe filenames."""
        for name in v:
            # Must be a simple filename, not a path
            if "/" in name or "\\" in name:
                raise ValueError(
                    f"instruction_files entries must be filenames, not paths: {name!r}"
                )
            # Must end in .md
            if not name.lower().endswith(".md"):
                raise ValueError(
                    f"instruction_files entries must be .md files: {name!r}"
                )
            # No path traversal
            if ".." in name:
                raise ValueError(
                    f"instruction_files entries must not contain '..': {name!r}"
                )
        return v
```

### Phase 2: Deprecation Handling

**File: `nexus3/config/schema.py`**

Add a model validator on `ContextConfig` that warns if the old fields are present in raw config. Since we use `extra="forbid"`, simply removing the fields will cause validation errors if users have them in their config.json. We need to handle migration gracefully.

Strategy: Add a pre-validator on the `Config` model that transforms old fields:

```python
class Config(BaseModel):
    # ... existing fields ...

    @model_validator(mode="before")
    @classmethod
    def migrate_deprecated_context_fields(cls, data: Any) -> Any:
        """Migrate deprecated context config fields to instruction_files."""
        if not isinstance(data, dict):
            return data
        context = data.get("context")
        if not isinstance(context, dict):
            return data

        migrated = False

        # If old fields present and no instruction_files, migrate
        if "instruction_files" not in context:
            include_readme = context.pop("include_readme", None)
            readme_as_fallback = context.pop("readme_as_fallback", None)

            if include_readme is not None or readme_as_fallback is not None:
                migrated = True
                # Default list without README.md
                files = ["NEXUS.md", "AGENTS.md", "CLAUDE.md"]
                # Add README.md if either old option was true
                if include_readme or readme_as_fallback:
                    files.append("README.md")
                context["instruction_files"] = files
                import logging
                logging.getLogger(__name__).warning(
                    "Deprecated config fields 'include_readme' and 'readme_as_fallback' "
                    "migrated to 'instruction_files'. Please update your config.json."
                )
        else:
            # instruction_files is set, just remove old fields silently
            context.pop("include_readme", None)
            context.pop("readme_as_fallback", None)

        return data
```

Note: This migration validator goes on `Config` (the root model), not `ContextConfig`, because the pre-validator needs to run before Pydantic sees the `extra="forbid"` on `ContextConfig`.

### Phase 3: ContextLoader Search Logic

**File: `nexus3/context/loader.py`**

Add the `_get_search_locations()` and `_find_instruction_file()` methods:

```python
# Known search directories for specific filenames
# Maps filename -> list of subdirectories to check (in order)
# Each entry is relative to the project root (parent of .nexus3)
INSTRUCTION_FILE_SEARCH_DIRS: dict[str, list[str]] = {
    "NEXUS.md": [".nexus3", "."],
    "AGENTS.md": [".nexus3", ".agents", "."],
    "CLAUDE.md": [".nexus3", ".claude", ".agents", "."],
    "README.md": ["."],
}

# Default search pattern for unknown filenames
DEFAULT_SEARCH_DIRS = [".nexus3", "."]


@dataclass
class InstructionFileResult:
    """Result of searching for an instruction file."""

    content: str
    source_path: Path
    filename: str  # e.g., "NEXUS.md", "AGENTS.md"
    is_readme: bool  # True if this is a README.md (needs wrapping)
```

Add methods to `ContextLoader`:

```python
def _get_search_locations(
    self, filename: str, project_root: Path
) -> list[Path]:
    """Get ordered search locations for an instruction filename.

    Args:
        filename: The instruction filename (e.g., "NEXUS.md", "CLAUDE.md").
        project_root: The project root directory (parent of .nexus3).

    Returns:
        List of absolute file paths to check, in priority order.
    """
    search_dirs = INSTRUCTION_FILE_SEARCH_DIRS.get(
        filename, DEFAULT_SEARCH_DIRS
    )
    locations = []
    for dir_name in search_dirs:
        if dir_name == ".":
            locations.append(project_root / filename)
        else:
            locations.append(project_root / dir_name / filename)
    return locations

def _find_instruction_file(
    self, project_root: Path
) -> InstructionFileResult | None:
    """Search for the first matching instruction file using priority list.

    Iterates through configured instruction_files list, checking each
    filename's search locations. Returns the first file found.

    Args:
        project_root: The project root directory to search in.

    Returns:
        InstructionFileResult if found, None if no instruction file exists.
    """
    for filename in self._config.instruction_files:
        locations = self._get_search_locations(filename, project_root)
        for location in locations:
            content = self._load_file(location)
            if content is not None:
                return InstructionFileResult(
                    content=content,
                    source_path=location,
                    filename=filename,
                    is_readme=(filename.upper() == "README.MD"),
                )
    return None
```

### Phase 4: Update `_load_layer()`

**File: `nexus3/context/loader.py`**

Replace the hardcoded NEXUS.md loading in `_load_layer()`:

Current code (lines 218-227):
```python
# Load NEXUS.md - check in .nexus3 first, then project root for legacy
nexus_path = directory / "NEXUS.md"
if not nexus_path.is_file() and directory.name == ".nexus3":
    # Legacy: also check parent directory (project root)
    legacy_path = directory.parent / "NEXUS.md"
    if legacy_path.is_file():
        nexus_path = legacy_path
layer.prompt = self._load_file(nexus_path)
```

New code:
```python
# Find instruction file using priority search
if directory.name == ".nexus3":
    project_root = directory.parent
else:
    project_root = directory

result = self._find_instruction_file(project_root)
if result is not None:
    if result.is_readme:
        # README.md content goes into layer.readme for wrapping
        # (layer.prompt stays None by default)
        layer.readme = result.content
    else:
        layer.prompt = result.content
    layer.prompt_source_path = result.source_path
    layer.prompt_filename = result.filename
```

This also requires adding fields to `ContextLayer`:

```python
@dataclass
class ContextLayer:
    """A single layer of context (global, ancestor, or local)."""

    name: str  # "global", "ancestor:dirname", "local"
    path: Path  # Directory path

    prompt: str | None = None  # Instruction file content
    readme: str | None = None  # README.md content (for wrapping)
    config: dict[str, Any] | None = None  # config.json content (pre-validation)
    mcp: dict[str, Any] | None = None  # mcp.json content

    # Track which instruction file was found (for accurate source labels)
    prompt_source_path: Path | None = None  # Actual file path loaded
    prompt_filename: str | None = None  # e.g., "NEXUS.md", "AGENTS.md"
```

Since we now handle README.md as part of the priority search (and it goes through `_find_instruction_file`), the separate README loading block in `_load_layer()` (lines 229-238) should be removed. README.md is only loaded if it appears in `instruction_files` and no higher-priority file was found first.

### Phase 5: Update `_format_prompt_section()`

**File: `nexus3/context/loader.py`**

The method currently hardcodes `NEXUS.md` in source paths. Update to use `layer.prompt_source_path`:

Current code for source path determination (lines 366-382):
```python
# Determine source path for labeling
if layer.name == "system-defaults":
    source_path = self._get_defaults_dir() / "NEXUS-DEFAULT.md"
    header = "## System Defaults"
elif layer.name == "defaults":
    source_path = self._get_defaults_dir() / "NEXUS.md"
    header = "## Default Configuration"
elif layer.name == "global":
    source_path = self._get_global_dir() / "NEXUS.md"
    header = "## Global Configuration"
elif layer.name.startswith("ancestor:"):
    dirname = layer.name.split(":", 1)[1]
    source_path = layer.path / "NEXUS.md"
    header = f"## Ancestor Configuration ({dirname})"
else:  # local
    source_path = layer.path / "NEXUS.md"
    header = "## Project Configuration"
```

New code:
```python
# Determine source path for labeling
if layer.name == "system-defaults":
    source_path = self._get_defaults_dir() / "NEXUS-DEFAULT.md"
    header = "## System Defaults"
elif layer.name == "defaults":
    source_path = self._get_defaults_dir() / "NEXUS.md"
    header = "## Default Configuration"
elif layer.name == "global":
    source_path = self._get_global_dir() / "NEXUS.md"
    header = "## Global Configuration"
elif layer.name.startswith("ancestor:"):
    dirname = layer.name.split(":", 1)[1]
    source_path = layer.prompt_source_path or (layer.path / "NEXUS.md")
    header = f"## Ancestor Configuration ({dirname})"
else:  # local
    source_path = layer.prompt_source_path or (layer.path / "NEXUS.md")
    header = "## Project Configuration"
```

Also update the README handling logic. The current approach uses separate `include_readme` / `readme_as_fallback` config flags. The new approach: if the instruction file found IS `README.md`, wrap it with boundaries. The check changes from config flags to checking `layer.prompt_filename`:

```python
content = layer.prompt
readme_content: str | None = None

# Determine README source path (README.md is in parent of .nexus3)
if layer.path.name == ".nexus3":
    readme_source_path = layer.path.parent / "README.md"
else:
    readme_source_path = layer.path / "README.md"

# If the instruction file found was README.md, wrap it
if content is None and layer.readme and layer.prompt_filename == "README.md":
    readme_content = self._format_readme_section(layer.readme, readme_source_path)
elif not content:
    return None
```

This simplification removes the `include_readme` / `readme_as_fallback` branches entirely since they are superseded by the priority list.

### Phase 6: Update `load_for_subagent()`

**File: `nexus3/context/loader.py`**

Current code (lines 603-608):
```python
# Load agent's local NEXUS.md
local_nexus = self._cwd / ".nexus3" / "NEXUS.md"

# Also check for NEXUS.md directly in cwd (legacy support)
if not local_nexus.is_file():
    local_nexus = self._cwd / "NEXUS.md"
```

New code:
```python
# Find instruction file using priority search
result = self._find_instruction_file(self._cwd)
local_nexus = result.source_path if result else self._cwd / ".nexus3" / "NEXUS.md"
```

The rest of the method (checking parent context, building subagent prompt) works with the resolved path and does not need changes.

### Phase 7: Update `/init` Command

**File: `nexus3/cli/init_commands.py`**

Change `init_local()` to accept a filename parameter, defaulting to `AGENTS.md`:

```python
def init_local(
    cwd: Path | None = None,
    force: bool = False,
    filename: str = "AGENTS.md",
) -> tuple[bool, str]:
    """Initialize a local ./.nexus3/ configuration directory.

    Creates project-specific configuration files with templates.

    Args:
        cwd: Directory to initialize in. Defaults to Path.cwd().
        force: If True, overwrite existing files. If False, skip if directory exists.
        filename: Name of the instruction file to create (default: AGENTS.md).

    Returns:
        Tuple of (success, message).
    """
    target_dir = (cwd or Path.cwd()) / ".nexus3"

    if target_dir.exists() and not force:
        return False, (
            f"Directory already exists: {target_dir}\n"
            "Use /init --force to overwrite."
        )

    try:
        secure_mkdir(target_dir)

        # P1.8 SECURITY: Use _safe_write_text to prevent symlink attacks
        # Create instruction file template
        _safe_write_text(target_dir / filename, NEXUS_MD_TEMPLATE)

        # Create config.json template
        _safe_write_text(target_dir / "config.json", CONFIG_JSON_TEMPLATE)

        # Create empty mcp.json
        _safe_write_text(target_dir / "mcp.json", MCP_JSON_TEMPLATE)

        return True, f"Initialized project configuration at {target_dir}"

    except InitSymlinkError as e:
        return False, f"Security error: {e}"
    except OSError as e:
        return False, f"Failed to create project config: {e}"
```

**File: `nexus3/cli/repl_commands.py`**

Update `cmd_init()` to parse the filename argument:

```python
async def cmd_init(ctx: CommandContext, args: str | None) -> CommandOutput:
    """Initialize project configuration directory.

    Usage:
        /init                - Create .nexus3/ with AGENTS.md (default)
        /init NEXUS.md       - Create .nexus3/ with NEXUS.md
        /init CLAUDE.md      - Create .nexus3/ with CLAUDE.md
        /init --force        - Overwrite existing files
        /init --global       - Initialize ~/.nexus3/ instead
    """
    from nexus3.cli.init_commands import init_global, init_local

    parts = (args or "").split()
    force = "--force" in parts or "-f" in parts
    global_mode = "--global" in parts or "-g" in parts

    # Extract filename argument (any .md file that isn't a flag)
    filename = "AGENTS.md"  # default
    for part in parts:
        if part.startswith("-"):
            continue
        if part.lower().endswith(".md"):
            filename = part
            break

    if global_mode:
        success, message = init_global(force=force)
    else:
        success, message = init_local(force=force, filename=filename)

    if success:
        return CommandOutput.success(message=message)
    else:
        return CommandOutput.error(message)
```

### Phase 8: Update Defaults Config

**File: `nexus3/defaults/config.json`**

Replace the context section:

Current:
```json
"context": {
    "include_readme": false,
    "readme_as_fallback": false
}
```

New:
```json
"context": {
    "instruction_files": ["NEXUS.md", "AGENTS.md", "CLAUDE.md", "README.md"]
}
```

---

## Testing Strategy

### Unit Tests

**File: `tests/unit/test_context_loader.py`**

New test class `TestInstructionFilePriority`:

```python
class TestInstructionFilePriority:
    """Tests for configurable instruction file priority search."""

    def test_finds_nexus_md_first(self, tmp_path: Path) -> None:
        """NEXUS.md is found first when it exists (default priority)."""
        nexus_dir = tmp_path / ".nexus3"
        nexus_dir.mkdir()
        (nexus_dir / "NEXUS.md").write_text("NEXUS content")
        (tmp_path / "AGENTS.md").write_text("AGENTS content")

        loader = ContextLoader(cwd=tmp_path)
        result = loader._find_instruction_file(tmp_path)
        assert result is not None
        assert result.filename == "NEXUS.md"
        assert result.content == "NEXUS content"

    def test_falls_through_to_agents_md(self, tmp_path: Path) -> None:
        """AGENTS.md found when no NEXUS.md exists."""
        (tmp_path / ".agents").mkdir()
        (tmp_path / ".agents" / "AGENTS.md").write_text("AGENTS content")

        loader = ContextLoader(cwd=tmp_path)
        result = loader._find_instruction_file(tmp_path)
        assert result is not None
        assert result.filename == "AGENTS.md"
        assert result.source_path == tmp_path / ".agents" / "AGENTS.md"

    def test_falls_through_to_claude_md(self, tmp_path: Path) -> None:
        """CLAUDE.md found when no NEXUS.md or AGENTS.md exists."""
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "CLAUDE.md").write_text("CLAUDE content")

        loader = ContextLoader(cwd=tmp_path)
        result = loader._find_instruction_file(tmp_path)
        assert result is not None
        assert result.filename == "CLAUDE.md"

    def test_falls_through_to_readme(self, tmp_path: Path) -> None:
        """README.md found as last resort."""
        (tmp_path / "README.md").write_text("README content")

        loader = ContextLoader(cwd=tmp_path)
        result = loader._find_instruction_file(tmp_path)
        assert result is not None
        assert result.filename == "README.md"
        assert result.is_readme is True

    def test_no_instruction_file_found(self, tmp_path: Path) -> None:
        """Returns None when no instruction file exists."""
        loader = ContextLoader(cwd=tmp_path)
        result = loader._find_instruction_file(tmp_path)
        assert result is None

    def test_nexus3_dir_checked_first_for_agents(self, tmp_path: Path) -> None:
        """.nexus3/AGENTS.md takes priority over .agents/AGENTS.md."""
        nexus_dir = tmp_path / ".nexus3"
        nexus_dir.mkdir()
        (nexus_dir / "AGENTS.md").write_text("from nexus3")
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir()
        (agents_dir / "AGENTS.md").write_text("from agents")

        config = ContextConfig(instruction_files=["AGENTS.md"])
        loader = ContextLoader(cwd=tmp_path, context_config=config)
        result = loader._find_instruction_file(tmp_path)
        assert result is not None
        assert result.source_path == nexus_dir / "AGENTS.md"
        assert result.content == "from nexus3"

    def test_claude_md_checks_all_directories(self, tmp_path: Path) -> None:
        """CLAUDE.md searches .nexus3, .claude, .agents, then root."""
        (tmp_path / "CLAUDE.md").write_text("root CLAUDE")

        config = ContextConfig(instruction_files=["CLAUDE.md"])
        loader = ContextLoader(cwd=tmp_path, context_config=config)
        result = loader._find_instruction_file(tmp_path)
        assert result is not None
        assert result.source_path == tmp_path / "CLAUDE.md"

    def test_custom_priority_list(self, tmp_path: Path) -> None:
        """Custom instruction_files list is respected."""
        (tmp_path / "CLAUDE.md").write_text("CLAUDE content")
        (tmp_path / "AGENTS.md").write_text("AGENTS content")

        # CLAUDE.md first in list
        config = ContextConfig(instruction_files=["CLAUDE.md", "AGENTS.md"])
        loader = ContextLoader(cwd=tmp_path, context_config=config)
        result = loader._find_instruction_file(tmp_path)
        assert result is not None
        assert result.filename == "CLAUDE.md"

    def test_empty_instruction_files_list(self, tmp_path: Path) -> None:
        """Empty list means no instruction file is searched for."""
        (tmp_path / "NEXUS.md").write_text("content")

        config = ContextConfig(instruction_files=[])
        loader = ContextLoader(cwd=tmp_path, context_config=config)
        result = loader._find_instruction_file(tmp_path)
        assert result is None

    def test_readme_marked_as_readme(self, tmp_path: Path) -> None:
        """README.md entries have is_readme=True for wrapping."""
        (tmp_path / "README.md").write_text("readme content")

        loader = ContextLoader(cwd=tmp_path)
        result = loader._find_instruction_file(tmp_path)
        assert result is not None
        assert result.is_readme is True

    def test_non_readme_not_marked(self, tmp_path: Path) -> None:
        """Non-README files have is_readme=False."""
        (tmp_path / ".nexus3").mkdir()
        (tmp_path / ".nexus3" / "NEXUS.md").write_text("content")

        loader = ContextLoader(cwd=tmp_path)
        result = loader._find_instruction_file(tmp_path)
        assert result is not None
        assert result.is_readme is False
```

**File: `tests/unit/test_context_loader.py`**

New test class `TestInstructionFileInLoad`:

```python
class TestInstructionFileInLoad:
    """Tests for instruction file priority in full load() flow."""

    def test_load_finds_agents_md(self, tmp_path: Path, monkeypatch) -> None:
        """Full load() discovers AGENTS.md in .agents/ directory."""
        # Setup: only AGENTS.md exists
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir()
        (agents_dir / "AGENTS.md").write_text("Agent instructions here")
        # Need .nexus3 dir for loader to consider this a local layer
        (tmp_path / ".nexus3").mkdir()

        monkeypatch.setattr("nexus3.context.loader.ContextLoader._get_global_dir", lambda self: tmp_path / "fake_global")
        monkeypatch.setattr("nexus3.context.loader.ContextLoader._get_defaults_dir", lambda self: tmp_path / "fake_defaults")

        loader = ContextLoader(cwd=tmp_path)
        context = loader.load(is_repl=False)
        assert "Agent instructions here" in context.system_prompt

    def test_source_path_reflects_actual_file(self, tmp_path: Path, monkeypatch) -> None:
        """ContextSources records the actual file path, not hardcoded NEXUS.md."""
        (tmp_path / ".nexus3").mkdir()
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "CLAUDE.md").write_text("Claude instructions")

        monkeypatch.setattr("nexus3.context.loader.ContextLoader._get_global_dir", lambda self: tmp_path / "fake_global")
        monkeypatch.setattr("nexus3.context.loader.ContextLoader._get_defaults_dir", lambda self: tmp_path / "fake_defaults")

        config = ContextConfig(instruction_files=["CLAUDE.md"])
        loader = ContextLoader(cwd=tmp_path, context_config=config)
        context = loader.load(is_repl=False)

        local_sources = [s for s in context.sources.prompt_sources if s.layer_name == "local"]
        assert len(local_sources) == 1
        assert local_sources[0].path == tmp_path / ".claude" / "CLAUDE.md"
```

**File: `tests/unit/test_init_commands.py`**

Update existing tests and add new ones:

```python
def test_init_local_default_creates_agents_md(tmp_path: Path) -> None:
    """Default init creates AGENTS.md, not NEXUS.md."""
    success, msg = init_local(cwd=tmp_path)
    assert success
    assert (tmp_path / ".nexus3" / "AGENTS.md").exists()
    assert not (tmp_path / ".nexus3" / "NEXUS.md").exists()

def test_init_local_nexus_filename(tmp_path: Path) -> None:
    """init with NEXUS.md creates NEXUS.md."""
    success, msg = init_local(cwd=tmp_path, filename="NEXUS.md")
    assert success
    assert (tmp_path / ".nexus3" / "NEXUS.md").exists()

def test_init_local_claude_filename(tmp_path: Path) -> None:
    """init with CLAUDE.md creates CLAUDE.md."""
    success, msg = init_local(cwd=tmp_path, filename="CLAUDE.md")
    assert success
    assert (tmp_path / ".nexus3" / "CLAUDE.md").exists()

def test_init_global_always_nexus_md(tmp_path: Path, monkeypatch) -> None:
    """Global init always creates NEXUS.md regardless of arguments."""
    monkeypatch.setattr("nexus3.cli.init_commands.get_nexus_dir", lambda: tmp_path / ".nexus3")
    success, msg = init_global()
    assert success
    assert (tmp_path / ".nexus3" / "NEXUS.md").exists()
```

**File: `tests/unit/test_config_schema.py` (or existing config test file)**

```python
def test_context_config_instruction_files_default() -> None:
    """Default instruction_files has correct priority."""
    config = ContextConfig()
    assert config.instruction_files == ["NEXUS.md", "AGENTS.md", "CLAUDE.md", "README.md"]

def test_context_config_rejects_path_in_instruction_files() -> None:
    """Paths in instruction_files are rejected."""
    with pytest.raises(ValidationError):
        ContextConfig(instruction_files=["../NEXUS.md"])

def test_context_config_rejects_non_md_instruction_files() -> None:
    """Non-.md files in instruction_files are rejected."""
    with pytest.raises(ValidationError):
        ContextConfig(instruction_files=["NEXUS.txt"])

def test_deprecated_include_readme_migration() -> None:
    """Old include_readme field is migrated to instruction_files."""
    data = {
        "context": {
            "include_readme": True,
            "readme_as_fallback": False,
        }
    }
    config = Config.model_validate(data)
    assert "README.md" in config.context.instruction_files

def test_deprecated_fields_removed_when_instruction_files_present() -> None:
    """Old fields are silently removed when instruction_files is set."""
    data = {
        "context": {
            "instruction_files": ["NEXUS.md"],
            "include_readme": True,  # should be ignored
        }
    }
    config = Config.model_validate(data)
    assert config.context.instruction_files == ["NEXUS.md"]
```

### Security Tests

**File: `tests/security/test_p2_18_readme_injection.py`**

Update existing tests to work with the new priority list approach. The core security property remains: README.md content is wrapped with documentation boundaries. Tests should verify:

1. When README.md is found via priority search, it gets `_format_readme_section()` wrapping.
2. When README.md is NOT in the priority list, it is never loaded.
3. Path traversal attempts in `instruction_files` are rejected by the validator.

### Integration Tests

**File: `tests/integration/test_instruction_file_priority.py`** (new)

```python
class TestInstructionFilePriorityE2E:
    """End-to-end tests for instruction file priority."""

    async def test_agent_gets_agents_md_context(self) -> None:
        """Agent created with AGENTS.md in CWD gets its content."""
        # Setup project with .agents/AGENTS.md
        # Create agent, verify system prompt contains AGENTS.md content

    async def test_compaction_reloads_from_priority_search(self) -> None:
        """Context compaction re-discovers instruction file via priority search."""
        # Setup, trigger compaction, verify new prompt found via search

    async def test_subagent_inherits_priority_search(self) -> None:
        """Subagent uses priority search for its own CWD."""
        # Parent in dir with NEXUS.md, child in dir with AGENTS.md
```

### Live Testing Plan

```bash
# 1. Start server
NEXUS_DEV=1 .venv/bin/python -m nexus3 --serve 9000 &

# 2. Create test directory with AGENTS.md
mkdir -p /tmp/test-priority/.agents
echo "# Test AGENTS.md\nYou are a test agent using AGENTS.md." > /tmp/test-priority/.agents/AGENTS.md
mkdir -p /tmp/test-priority/.nexus3

# 3. Create agent with that CWD
.venv/bin/python -m nexus3 rpc create test-agent --preset trusted --cwd /tmp/test-priority --port 9000

# 4. Ask agent what its instructions say
.venv/bin/python -m nexus3 rpc send test-agent "What instruction file were you given? Quote its content." --port 9000

# 5. Verify it sees AGENTS.md content
.venv/bin/python -m nexus3 rpc status test-agent --port 9000

# 6. Test CLAUDE.md in .claude/ directory
mkdir -p /tmp/test-claude/.claude
echo "# CLAUDE.md Test\nClaude-specific instructions." > /tmp/test-claude/.claude/CLAUDE.md
mkdir -p /tmp/test-claude/.nexus3
.venv/bin/python -m nexus3 rpc create claude-test --preset trusted --cwd /tmp/test-claude --port 9000
.venv/bin/python -m nexus3 rpc send claude-test "What project instructions do you see?" --port 9000

# 7. Test priority: NEXUS.md wins over AGENTS.md
mkdir -p /tmp/test-both/.nexus3
echo "NEXUS wins" > /tmp/test-both/.nexus3/NEXUS.md
echo "AGENTS loses" > /tmp/test-both/AGENTS.md
.venv/bin/python -m nexus3 rpc create both-test --preset trusted --cwd /tmp/test-both --port 9000
.venv/bin/python -m nexus3 rpc send both-test "What are your project instructions? Quote them exactly." --port 9000

# 8. Test /init in REPL
nexus3 --fresh
> /cwd /tmp/test-init-default
> /init
# Verify .nexus3/AGENTS.md was created
> /cwd /tmp/test-init-nexus
> /init NEXUS.md
# Verify .nexus3/NEXUS.md was created

# 9. Cleanup
.venv/bin/python -m nexus3 rpc shutdown --port 9000
```

---

## Open Questions

None. All design decisions have been resolved in the spec.

---

## Codebase Validation Notes

*Validated against NEXUS3 codebase on 2026-02-11*

### Confirmed Patterns

| Aspect | Status | Notes |
|--------|--------|-------|
| `ContextConfig` in `config/schema.py` | Confirmed | Pydantic model with `extra="forbid"`, has `include_readme` and `readme_as_fallback` |
| `ContextLoader._load_layer()` | Confirmed | Lines 208-254, hardcodes `NEXUS.md` at lines 221-227 |
| `ContextLoader._load_global_layer()` | Confirmed | Lines 256-303, hardcodes `~/.nexus3/NEXUS.md` at line 282 |
| `ContextLoader._format_prompt_section()` | Confirmed | Lines 329-407, hardcodes `NEXUS.md` in source paths at lines 371-381 |
| `ContextLoader.load_for_subagent()` | Confirmed | Lines 589-647, hardcodes paths at lines 604, 608 |
| `ContextLayer` dataclass | Confirmed | Lines 123-133, has `prompt` and `readme` fields, no source tracking |
| `init_local()` | Confirmed | `nexus3/cli/init_commands.py` lines 142-180, hardcodes `NEXUS.md` |
| `init_global()` | Confirmed | `nexus3/cli/init_commands.py` lines 81-139, hardcodes `NEXUS.md` |
| `cmd_init()` | Confirmed | `nexus3/cli/repl_commands.py` lines 2185-2207, no filename arg support |
| `defaults/config.json` | Confirmed | Has `"include_readme": false, "readme_as_fallback": false` at lines 105-106 |
| `_format_readme_section()` | Confirmed | Lines 305-327, wraps README with security boundaries |
| `Config` root model | Confirmed | `config/schema.py` lines 584-789, has `model_validator(mode="after")` validators |
| `load_json_file_optional` | Confirmed | Used in loader.py for fail-fast config loading |
| `_load_file()` | Confirmed | Line 195, reads with `encoding="utf-8-sig"` |

### Corrections Applied

1. **`ContextLayer` needs new fields** -- Original dataclass has no way to track which instruction file was loaded. Plan adds `prompt_source_path` and `prompt_filename` fields.

2. **`_format_prompt_section()` README logic is coupled to config flags** -- Lines 352-363 check `self._config.readme_as_fallback` and `self._config.include_readme`. These branches must be replaced with a check on `layer.prompt_filename == "README.md"`.

3. **Global layer is exempt** -- `_load_global_layer()` always loads `~/.nexus3/NEXUS.md`. This is intentional and does NOT use the priority list. The plan correctly excludes global from the search.

4. **Legacy root NEXUS.md support** -- `_load_layer()` currently checks `directory.parent / "NEXUS.md"` for legacy support. The new `_find_instruction_file()` subsumes this by checking `.nexus3/{file}` then `./{file}`, so the legacy path is preserved.

5. **Separate README.md loading block** -- Lines 229-238 of `_load_layer()` load README.md independently of the instruction file. This block must be removed since README.md handling is now part of the priority search.

6. **`Config` pre-validator placement** -- The deprecation migration validator must be `mode="before"` on `Config` (root), not on `ContextConfig`, because `extra="forbid"` on `ContextConfig` would reject the old fields before any validator runs.

7. **Downstream ContextLoader consumers verified** -- `rpc/pool.py` (line 487), `rpc/bootstrap.py` (line 284), and `session/session.py` (line 110) all create or store `ContextLoader` with `context_config` from the merged config. The new `instruction_files` field flows through automatically; no code changes needed in these files.

8. **`_find_instruction_file()` uses `_load_file()` for consistency** -- Initial draft inlined `location.read_text(encoding="utf-8-sig")`. Corrected to use `self._load_file(location)` to follow the existing codebase pattern where file reading goes through the centralized `_load_file()` method.

---

## Implementation Checklist

### Phase 1: Config Schema (Required First)
- [ ] **P1.1** Add `instruction_files` field to `ContextConfig` in `nexus3/config/schema.py`
- [ ] **P1.2** Add `validate_instruction_files` field validator (security: no paths, must be .md)
- [ ] **P1.3** Remove `include_readme` and `readme_as_fallback` fields from `ContextConfig`
- [ ] **P1.4** Add `migrate_deprecated_context_fields` pre-validator on `Config` root model
- [ ] **P1.5** Update `nexus3/defaults/config.json` context section
- [ ] **P1.6** Unit tests for new `ContextConfig` validation and migration

### Phase 2: Loader Search Logic (After Phase 1)
- [ ] **P2.1** Add `INSTRUCTION_FILE_SEARCH_DIRS` constant and `InstructionFileResult` dataclass to `loader.py`
- [ ] **P2.2** Add `_get_search_locations()` method to `ContextLoader`
- [ ] **P2.3** Add `_find_instruction_file()` method to `ContextLoader`
- [ ] **P2.4** Add `prompt_source_path` and `prompt_filename` fields to `ContextLayer`
- [ ] **P2.5** Unit tests for `_find_instruction_file()` (all priority scenarios)

### Phase 3: Update `_load_layer()` (After Phase 2)
- [ ] **P3.1** Replace hardcoded NEXUS.md loading with `_find_instruction_file()` call
- [ ] **P3.2** Remove separate README.md loading block (lines 229-238)
- [ ] **P3.3** Update `_format_prompt_section()` to use `layer.prompt_source_path` and check `layer.prompt_filename` for README wrapping
- [ ] **P3.4** Update existing tests in `test_context_loader.py` for new behavior
- [ ] **P3.5** Update security tests in `test_p2_18_readme_injection.py`

### Phase 4: Update `load_for_subagent()` (After Phase 2, can parallel with Phase 3)
- [ ] **P4.1** Replace hardcoded NEXUS.md path resolution with `_find_instruction_file()` call
- [ ] **P4.2** Update subagent context tests

### Phase 5: Update `/init` Command (After Phase 1, can parallel with Phases 2-4)
- [ ] **P5.1** Add `filename` parameter to `init_local()` in `init_commands.py`, default to `AGENTS.md`
- [ ] **P5.2** Update `cmd_init()` in `repl_commands.py` to parse filename argument
- [ ] **P5.3** Update `/init` help text in `cmd_init` docstring
- [ ] **P5.4** Update init command tests in `test_init_commands.py`

### Phase 6: Integration Tests (After Phases 3-5)
- [ ] **P6.1** Create `tests/integration/test_instruction_file_priority.py` with E2E scenarios
- [ ] **P6.2** Verify all existing tests pass with updated code (`pytest tests/ -v`)
- [ ] **P6.3** Verify ruff and mypy pass (`ruff check nexus3/` and `mypy nexus3/`)

### Phase 7: Live Testing (After Phase 6)
- [ ] **P7.1** Live test: agent in dir with only `.agents/AGENTS.md` discovers it
- [ ] **P7.2** Live test: agent in dir with `.claude/CLAUDE.md` discovers it
- [ ] **P7.3** Live test: NEXUS.md wins over AGENTS.md when both exist
- [ ] **P7.4** Live test: `/init` creates `.nexus3/AGENTS.md` by default
- [ ] **P7.5** Live test: `/init NEXUS.md` creates `.nexus3/NEXUS.md`
- [ ] **P7.6** Live test: compaction reloads instruction file via priority search

### Phase 8: Documentation (After Live Testing)
- [ ] **P8.1** Update `CLAUDE.md` Context Loading section: replace NEXUS.md references with instruction_files description
- [ ] **P8.2** Update `CLAUDE.md` Configuration Reference: update context config options
- [ ] **P8.3** Update `CLAUDE.md` `/init` command docs with filename argument
- [ ] **P8.4** Update `nexus3/context/README.md`: loading rules, ContextLayer fields, search logic
- [ ] **P8.5** Update `nexus3/config/README.md`: context config fields
- [ ] **P8.6** Update `nexus3/cli/README.md`: /init command documentation
- [ ] **P8.7** Update `nexus3/defaults/README.md`: context config options

---

## Quick Reference: File Locations

| Component | File Path |
|-----------|-----------|
| ContextConfig (Pydantic) | `nexus3/config/schema.py` (class ContextConfig, ~line 317) |
| Config root model | `nexus3/config/schema.py` (class Config, ~line 584) |
| Config loader | `nexus3/config/loader.py` |
| ContextLoader | `nexus3/context/loader.py` |
| ContextLayer dataclass | `nexus3/context/loader.py` (~line 123) |
| ContextManager | `nexus3/context/manager.py` |
| Init commands | `nexus3/cli/init_commands.py` |
| REPL cmd_init | `nexus3/cli/repl_commands.py` (~line 2185) |
| Defaults config | `nexus3/defaults/config.json` |
| Context module README | `nexus3/context/README.md` |
| Config module README | `nexus3/config/README.md` |
| CLI module README | `nexus3/cli/README.md` |
| Defaults README | `nexus3/defaults/README.md` |
| Constants | `nexus3/core/constants.py` |
| Loader tests | `tests/unit/test_context_loader.py` |
| Init tests | `tests/unit/test_init_commands.py` |
| README security tests | `tests/security/test_p2_18_readme_injection.py` |
| AgentPool (no changes) | `nexus3/rpc/pool.py` (~line 487) |
| Bootstrap (no changes) | `nexus3/rpc/bootstrap.py` (~line 284) |
| Session (no changes) | `nexus3/session/session.py` (~line 110) |

---

## Effort Estimate

| Phase | Description | LOC (approx) |
|-------|-------------|--------------|
| P1 | Config schema changes + deprecation migration | ~60 |
| P2 | Search logic (constants + 2 methods + dataclass) | ~80 |
| P3 | `_load_layer()` + `_format_prompt_section()` updates | ~40 |
| P4 | `load_for_subagent()` update | ~10 |
| P5 | `/init` command changes | ~25 |
| P6 | Integration tests | ~100 |
| P7 | Live testing | 0 (manual) |
| P8 | Documentation updates | ~200 |
| Unit tests | All phases | ~250 |
| **Total** | | **~765 LOC** |

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Breaking existing setups with `include_readme`/`readme_as_fallback` in config | Pre-validator on Config migrates old fields with warning; graceful degradation |
| Loading files from `.claude/` or `.agents/` dirs that contain malicious content | Same risk as loading any NEXUS.md; instruction files are always untrusted user content. README.md wrapping provides extra safety |
| `/init` default change from NEXUS.md to AGENTS.md confusing existing users | Clear help text; user can pass `NEXUS.md` explicitly |
| Performance: checking multiple directories per filename per layer | File existence checks are fast (stat syscall); at most ~15 checks total across all layers |
| `extra="forbid"` on ContextConfig rejecting old config fields | Handled by pre-validator on Config root model that removes old fields before ContextConfig validation |
