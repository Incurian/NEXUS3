# Context Management Plan

This document details the planned context management system for NEXUS3, covering system prompts (NEXUS.md), configuration, and MCP server configuration.

## Overview

Context is loaded from multiple layers and merged together. Each layer extends the previous one. The model sees clearly labeled sections indicating where each piece of context originated.

## Architecture

### Layer Hierarchy (Load Order)

```
LAYER 1: Install Defaults (templates, never read at runtime)
    ↓
LAYER 2: Global (~/.nexus3/)
    ↓
LAYER 3: Ancestors (up to 2 levels above CWD)
    ↓
LAYER 4: Local (CWD)
```

### Directory Structure

```
~/.nexus3/                          # Global (user defaults)
├── NEXUS.md                        # Personal system prompt
├── config.json                     # Personal configuration
└── mcp.json                        # Personal MCP servers

../../.nexus3/                      # Grandparent (2 levels up)
├── NEXUS.md
├── config.json
└── mcp.json

../.nexus3/                         # Parent (1 level up)
├── NEXUS.md
├── config.json
└── mcp.json

./.nexus3/                          # Local (CWD)
├── NEXUS.md
├── config.json
└── mcp.json
```

### Fallback Chain

```
Global: ~/.nexus3/ → <install>/defaults/ → Pydantic defaults
Local:  ./.nexus3/ → ../.nexus3/ → ../../.nexus3/ → (nothing)
```

---

## Current State

### Prompt Loading (`context/prompt_loader.py`)

**Current behavior:**
- Loads personal: `~/.nexus3/NEXUS.md` OR `defaults/NEXUS.md`
- Loads project: `./NEXUS.md` (optional)
- Combines with headers: `# Personal Configuration`, `# Project Configuration`
- Appends `# Environment` section with system info
- Returns `LoadedPrompt(content, personal_path, project_path)`

**Gaps:**
- No ancestor directory traversal
- Only looks in CWD for project config
- Headers are basic (no indication of file paths)

### Config Loading (`config/loader.py`)

**Current behavior:**
- Loads ONE file (first found): `./.nexus3/config.json` → `~/.nexus3/config.json` → `defaults/config.json`
- No merging between files
- Pydantic validation with `extra="forbid"`
- Fail-fast on errors

**Gaps:**
- No layered merging (only loads first found)
- No ancestor directory traversal
- Can't extend global with local overrides

### MCP Config (`config/schema.py`)

**Current behavior:**
- `mcp_servers: list[MCPServerConfig]` in config schema
- `MCPServerConfig`: `name`, `command` (stdio), `url` (HTTP), `env`, `enabled`
- MCP module exists (`nexus3/mcp/`) with full implementation
- Connected via `/mcp connect <name>` REPL command

**Gaps:**
- No separate `mcp.json` file
- MCP config embedded in main config.json
- No layered MCP server discovery

---

## Proposed Changes

### 1. Context Loading Flow

```python
class ContextLoader:
    """Unified loader for all context types."""

    def load(self, cwd: Path) -> LoadedContext:
        """Load and merge all context layers."""
        # 1. Load global (with fallback to defaults)
        global_ctx = self._load_global()

        # 2. Load ancestors (configurable depth, default 2)
        max_ancestor_depth = config.get("context", {}).get("ancestor_depth", 2)
        ancestor_dirs = self._find_ancestor_configs(cwd, max_levels=max_ancestor_depth)
        ancestor_ctx = [self._load_layer(d) for d in ancestor_dirs]

        # 3. Load local
        local_ctx = self._load_local(cwd)

        # 4. Merge all layers
        return self._merge_layers(global_ctx, ancestor_ctx, local_ctx)
```

### 2. Ancestor Directory Traversal

```python
def _find_ancestor_configs(self, cwd: Path, max_levels: int = 2) -> list[Path]:
    """Find .nexus3 directories in ancestor paths."""
    ancestors = []
    current = cwd.parent

    for _ in range(max_levels):
        if current == current.parent:  # Reached root
            break
        config_dir = current / ".nexus3"
        if config_dir.exists():
            ancestors.append(config_dir)
        current = current.parent

    # Return in order: grandparent first, then parent (for correct merge order)
    return list(reversed(ancestors))
```

### 3. Layered Config Merging

```python
def _merge_configs(self, layers: list[dict]) -> dict:
    """Deep merge config layers. Later layers extend earlier ones."""
    result = {}
    for layer in layers:
        result = deep_merge(result, layer)
    return result

def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge dicts. Lists are concatenated, not replaced."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            result[key] = result[key] + value  # Extend lists
        else:
            result[key] = value
    return result
```

### 4. Labeled Context Output

The model should see clearly labeled sections showing where each piece of context came from:

```markdown
# System Configuration

## Global Configuration
Source: ~/.nexus3/NEXUS.md

[content from global NEXUS.md]

## Ancestor Configuration (company/)
Source: /home/user/projects/company/.nexus3/NEXUS.md

[content from company-level NEXUS.md]

## Ancestor Configuration (backend/)
Source: /home/user/projects/company/backend/.nexus3/NEXUS.md

[content from backend-level NEXUS.md]

## Project Configuration
Source: /home/user/projects/company/backend/auth-service/.nexus3/NEXUS.md

[content from local NEXUS.md]

## Environment
Working directory: /home/user/projects/company/backend/auth-service
Operating system: Linux (WSL2 on Windows)
Mode: Interactive REPL

## Active MCP Servers
- filesystem (global): stdio, enabled
- database (project): http://localhost:5432, enabled
```

### 5. MCP Configuration

**Separate mcp.json file:**

```json
{
  "servers": [
    {
      "name": "filesystem",
      "command": ["npx", "@anthropic/mcp-server-filesystem"],
      "env": {"ALLOWED_PATHS": "/home/user"},
      "enabled": true
    },
    {
      "name": "postgres",
      "url": "http://localhost:9000",
      "enabled": true
    }
  ]
}
```

**Empty template (for `/init`):**

```json
{
  "servers": []
}
```

**Parser handling:**
- Empty file → treat as `{"servers": []}`
- Missing file → skip (no error)
- Invalid JSON → fail fast with clear error message

---

## Setup Scripts

### 1. Install Defaults (Git Hook)

```bash
#!/bin/bash
# post-install hook: copy defaults to package install directory
cp -r defaults/ $INSTALL_DIR/nexus3/defaults/
```

**Files in defaults/:**
- `NEXUS.md` - Full default system prompt
- `config.json` - Default configuration
- `mcp.json` - Empty `{"servers": []}`

### 2. Global Init Script

```bash
nexus --init-global
```

**Creates:**
```
~/.nexus3/
├── NEXUS.md      # Copy of defaults/NEXUS.md
├── config.json   # Copy of defaults/config.json
└── mcp.json      # Copy of defaults/mcp.json (empty)
```

**Behavior:**
- Fails if `~/.nexus3/` already exists (use `--force` to overwrite)
- Copies current testing MCP config to global if available

### 3. Local Init Command

```
/init
```

**Creates:**
```
./.nexus3/
├── NEXUS.md      # Blank template with section headers
├── config.json   # Minimal valid JSON with comments-as-keys
└── mcp.json      # Empty {"servers": []}
```

**NEXUS.md template:**

```markdown
# Project Configuration

## Overview
<!-- Describe this project and how the agent should approach it -->

## Key Files
<!-- List important files and their purposes -->

## Conventions
<!-- Project-specific conventions, coding standards, etc. -->

## Notes
<!-- Any other context the agent should know -->
```

**config.json template:**

```json
{
  "_comment": "Project-specific NEXUS3 configuration. All fields optional - extends global config.",
  "provider": {
    "_comment": "Override model settings for this project"
  },
  "permissions": {
    "_comment": "Project-specific permission overrides"
  }
}
```

---

## Reload Triggers

Context is reloaded on:
1. **Startup** - Full reload of all layers
2. **`/compact`** - Reload during context compaction (picks up NEXUS.md changes)

---

## Error Handling

| Error | Behavior |
|-------|----------|
| Missing global config | Fall back to install defaults |
| Missing local config | Skip (no error) |
| Missing ancestor config | Skip that level |
| Malformed JSON | Fail fast with clear error: file path, line number, parse error |
| Invalid schema | Fail fast with Pydantic validation error |
| Empty file | Treat as minimal valid (`{}` or `{"servers": []}`) |

**Example error message:**

```
Configuration Error: Invalid JSON in /home/user/projects/.nexus3/config.json

  Line 15, Column 3: Expecting property name enclosed in double quotes

  14 |   "model": "claude-3",
  15 |   trailing_comma: true,
       ^
  16 | }

Fix the JSON syntax error and try again.
```

---

## Implementation Plan

### Phase 1: Core Infrastructure

1. **Create `ContextLoader` class** (`context/loader.py`)
   - Unified loading for NEXUS.md, config.json, mcp.json
   - Ancestor directory traversal
   - Layer merging logic

2. **Update `PromptLoader`**
   - Use new ContextLoader
   - Generate labeled sections with source paths
   - Support ancestor layers

3. **Update `load_config()`**
   - Support layered merging
   - Use ContextLoader for path resolution

### Phase 2: MCP Separation

4. **Create separate mcp.json handling**
   - New `MCPConfigLoader` or integrate into ContextLoader
   - Merge MCP servers from all layers
   - Track server origin (global vs local)

5. **Update MCP registry**
   - Load from merged mcp.json
   - Support per-layer server discovery

### Phase 3: Setup Scripts

6. **Implement `--init-global`**
   - CLI flag in repl.py
   - Copy defaults to ~/.nexus3/

7. **Implement `/init` command**
   - Slash command in repl_commands.py
   - Generate blank templates in CWD

### Phase 4: Polish

8. **Error handling improvements**
   - Clear error messages with file paths
   - Line numbers for JSON parse errors
   - Helpful suggestions

9. **Documentation**
   - Update CLAUDE.md
   - Update module READMEs
   - Add user guide for context configuration

---

## Data Structures

### LoadedContext

```python
@dataclass
class LoadedContext:
    """Result of loading all context layers."""

    # Prompt content (already merged and labeled)
    system_prompt: str

    # Merged configuration
    config: Config

    # Merged MCP servers (with origin tracking)
    mcp_servers: list[MCPServerWithOrigin]

    # Source tracking for debugging
    sources: ContextSources

@dataclass
class ContextSources:
    """Tracks where each piece of context came from."""
    global_dir: Path | None
    ancestor_dirs: list[Path]
    local_dir: Path | None

    prompt_sources: list[PromptSource]  # (path, layer_name)
    config_sources: list[Path]
    mcp_sources: list[Path]

@dataclass
class MCPServerWithOrigin:
    """MCP server config with its origin layer."""
    config: MCPServerConfig
    origin: str  # "global", "ancestor:company", "local"
    source_path: Path
```

### ContextLayer

```python
@dataclass
class ContextLayer:
    """A single layer of context (global, ancestor, or local)."""

    name: str              # "global", "ancestor:company", "local"
    path: Path             # Directory path

    prompt: str | None     # NEXUS.md content
    config: dict | None    # config.json content (pre-validation)
    mcp: dict | None       # mcp.json content
```

---

## Example: Full Context Output

For a project at `/home/user/projects/company/backend/auth-service`:

```markdown
# System Configuration

## Global Configuration
Source: /home/user/.nexus3/NEXUS.md

You are NEXUS3, an AI-powered CLI agent...
[rest of global prompt]

## Ancestor Configuration (company)
Source: /home/user/projects/company/.nexus3/NEXUS.md

You work at Acme Corp. Our codebase uses:
- Python 3.11+ with type hints
- PostgreSQL for data storage
- Docker for deployment

## Ancestor Configuration (backend)
Source: /home/user/projects/company/backend/.nexus3/NEXUS.md

This is the backend monorepo. Key services:
- auth-service: OAuth2/OIDC
- api-gateway: GraphQL federation
- user-service: User management

## Project Configuration
Source: /home/user/projects/company/backend/auth-service/.nexus3/NEXUS.md

The auth-service handles authentication:
- JWT token issuance
- OAuth2 provider integration
- Session management

## Environment
Working directory: /home/user/projects/company/backend/auth-service
Operating system: Linux (WSL2 on Windows)
Terminal: vscode (xterm-256color)
Mode: Interactive REPL

## Active Configuration
Model: anthropic/claude-sonnet-4
Context window: 200000 tokens
Permission level: trusted

## MCP Servers
| Server | Type | Origin | Status |
|--------|------|--------|--------|
| filesystem | stdio | global | enabled |
| postgres | http | ancestor:company | enabled |
| auth-tools | stdio | local | enabled |
```

---

## Critical Fix: Subagent Context Loading

### Current Problem

Subagents created via `nexus_create(cwd="/some/project")` do **NOT** get context from that directory:

```python
# Current behavior (WRONG)
AgentConfig.cwd → Only affects permissions
                → Does NOT affect prompt/context loading
                → All agents use server's original CWD for context
```

### Required Behavior

```python
# Desired behavior (TO IMPLEMENT)
nexus_create(agent_id="worker", cwd="/project/auth")
    → Load context from /project/auth/.nexus3/
    → Including ancestor traversal from that path
    → Agent sees "Project Configuration: /project/auth/.nexus3/NEXUS.md"
```

### Implementation

In `AgentPool.create()`:

```python
# Current (shared prompt loader, ignores agent cwd)
if agent_config.system_prompt is not None:
    system_prompt = agent_config.system_prompt
else:
    loaded_prompt = shared.prompt_loader.load(is_repl=False)  # Uses server CWD
    system_prompt = loaded_prompt.content

# Proposed (per-agent context loading)
if agent_config.system_prompt is not None:
    system_prompt = agent_config.system_prompt
else:
    # Create loader for agent's specific cwd
    effective_cwd = agent_config.cwd or Path.cwd()
    context_loader = ContextLoader(effective_cwd)
    loaded_context = context_loader.load()
    system_prompt = loaded_context.system_prompt
```

### Subagent Context Inheritance (DECIDED)

**Rule:** Subagents get their cwd's NEXUS.md + parent's context, non-redundantly.

```python
def load_subagent_context(agent_cwd: Path, parent_context: LoadedContext) -> str:
    """Load context for subagent, avoiding duplication with parent."""

    # Check if agent's cwd NEXUS.md is already in parent's context
    agent_nexus = agent_cwd / ".nexus3" / "NEXUS.md"
    if agent_nexus in parent_context.sources.prompt_sources:
        # Already loaded by parent - use parent context as-is
        return parent_context.system_prompt

    # Load agent's cwd NEXUS.md and prepend to parent context
    if agent_nexus.exists():
        agent_prompt = agent_nexus.read_text()
        return f"""## Subagent Configuration
Source: {agent_nexus}

{agent_prompt}

{parent_context.system_prompt}"""

    # No local NEXUS.md - use parent context
    return parent_context.system_prompt
```

**MCP for subagents:** Not applicable. Only TRUSTED+ can use MCP, and only in REPL mode. Subagents (typically sandboxed/worker) won't have MCP access.

---

## Decisions Made

1. **Subagent context**: NEXUS.md only from cwd, non-redundantly merged with parent context
2. **MCP for subagents**: N/A (only TRUSTED+ in REPL mode can use MCP)
3. **Ancestor depth**: Configurable, default 2
4. **README.md inclusion**: Optional, off by default, can be used as fallback when no NEXUS.md exists
5. **Config key conflicts**: Deep merge - local values override specific keys, global values preserved for unspecified keys
6. **MCP server name conflicts**: Local wins - if same name in global and local, local config takes precedence
7. **Performance/caching**: No cache for now - always reload on startup and `/compact`, premature optimization

---

## New Config Schema

Add to `config/schema.py`:

```python
class ContextConfig(BaseModel):
    """Configuration for context loading."""

    ancestor_depth: int = Field(
        default=2,
        ge=0,
        le=10,
        description="How many directory levels above CWD to search for .nexus3/"
    )
    include_readme: bool = Field(
        default=False,
        description="Always include README.md in context alongside NEXUS.md"
    )
    readme_as_fallback: bool = Field(
        default=True,
        description="Use README.md as context when no NEXUS.md exists"
    )

class Config(BaseModel):
    # ... existing fields ...
    context: ContextConfig = Field(default_factory=ContextConfig)
```

**Example config.json:**

```json
{
  "context": {
    "ancestor_depth": 3,
    "include_readme": false,
    "readme_as_fallback": true
  }
}
```

**README.md behavior:**

| `include_readme` | `readme_as_fallback` | Result |
|------------------|---------------------|--------|
| false | false | Never include README |
| false | true | Include README only if no NEXUS.md (default) |
| true | - | Always include README after NEXUS.md |

---

## Dependencies

- No new external dependencies
- Uses existing: Pydantic, pathlib, json

## Testing Strategy

1. **Unit tests**: Layer merging, path resolution, error handling
2. **Integration tests**: Full context loading with real file structures
3. **Manual tests**: `/init` command, `--init-global` flag
