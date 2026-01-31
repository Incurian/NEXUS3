# nexus3.clipboard - Scoped Clipboard System

**Updated: 2026-01-31**

The clipboard module provides a multi-scope clipboard system for NEXUS3 agents. It enables agents to copy, cut, and paste content between files with persistent storage, tagging, search, and context injection.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Scopes](#scopes)
4. [Core Operations](#core-operations)
5. [Tags](#tags)
6. [Search](#search)
7. [Import/Export](#importexport)
8. [TTL (Time-to-Live)](#ttl-time-to-live)
9. [Context Injection](#context-injection)
10. [Session Persistence](#session-persistence)
11. [Configuration](#configuration)
12. [Permission Model](#permission-model)
13. [Module Exports](#module-exports)
14. [Dependencies](#dependencies)

---

## Overview

The clipboard system provides a structured way for agents to:

- **Copy** file content (or portions) to named entries with metadata
- **Cut** content from files (copy + delete from source)
- **Paste** clipboard content into files (multiple insertion modes)
- **Organize** entries with tags for categorization
- **Search** entries by key, description, or content
- **Import/Export** clipboard entries as JSON for backup or transfer
- **Auto-inject** clipboard contents into system prompt for context

Key features:
- **Three scope levels**: Agent (in-memory), Project (persistent), System (global)
- **Permission-aware**: Sandboxed agents can only use agent scope
- **SQLite storage**: WAL mode, TOCTOU protection, atomic operations
- **Tag system**: Organize entries with named tags
- **TTL support**: Optional expiration for temporary entries
- **Session persistence**: Agent-scope entries saved/restored with sessions

---

## Architecture

```
nexus3/clipboard/
├── __init__.py       # Public API exports
├── types.py          # Core types: ClipboardEntry, ClipboardScope, ClipboardPermissions
├── storage.py        # ClipboardStorage: SQLite backend for PROJECT/SYSTEM scopes
├── manager.py        # ClipboardManager: coordinates storage, permissions, scope resolution
└── injection.py      # Context injection: format_clipboard_context(), format_entry_detail()

nexus3/skill/builtin/
├── clipboard_copy.py    # copy, cut skills
├── clipboard_paste.py   # paste skill
├── clipboard_manage.py  # clipboard_list, clipboard_get, clipboard_update, clipboard_delete, clipboard_clear
├── clipboard_search.py  # clipboard_search skill
├── clipboard_tag.py     # clipboard_tag skill
├── clipboard_export.py  # clipboard_export skill
└── clipboard_import.py  # clipboard_import skill

Storage locations:
├── <cwd>/.nexus3/clipboard.db   # PROJECT scope (SQLite)
└── ~/.nexus3/clipboard.db       # SYSTEM scope (SQLite)
```

---

## Scopes

The clipboard uses three scope levels with different persistence and sharing characteristics:

| Scope | Storage | Persistence | Sharing | Use Case |
|-------|---------|-------------|---------|----------|
| `agent` | In-memory dict | Session only | Single agent | Temporary working data |
| `project` | `<cwd>/.nexus3/clipboard.db` | Persistent | All agents in project | Project-specific snippets |
| `system` | `~/.nexus3/clipboard.db` | Persistent | All agents globally | Reusable templates |

### Scope Resolution

When copying/pasting, specify scope explicitly:

```python
# Skills use scope parameter
copy(path="/src/utils.py", key="helper", scope="project")
paste(key="helper", path="/new/file.py", scope="project")
```

Default scope is `agent` (safest, no persistence).

---

## Core Operations

### Copy

Copy file content to clipboard:

```
copy(path, key, scope?, start_line?, end_line?, description?, tags?, ttl_seconds?)
```

- Reads file content (optionally specific line range)
- Creates clipboard entry with metadata
- Tracks source path and line range for context

### Cut

Like copy, but also removes content from source file:

```
cut(path, key, scope?, start_line?, end_line?, description?, tags?, ttl_seconds?)
```

### Paste

Paste clipboard content into a file:

```
paste(key, path, scope?, mode?, line?, start_line?, end_line?, marker?)
```

**Insertion modes:**

| Mode | Description |
|------|-------------|
| `append` | Add to end of file (default) |
| `prepend` | Add to beginning of file |
| `after_line` | Insert after specified line number |
| `before_line` | Insert before specified line number |
| `replace_lines` | Replace line range with clipboard content |
| `at_marker_replace` | Replace marker text with content |
| `at_marker_after` | Insert after marker text |
| `at_marker_before` | Insert before marker text |

---

## Tags

Tags help organize clipboard entries by category or purpose.

### Tag Management

```
clipboard_tag(action, key?, scope?, tag?, tags?, description?)
```

| Action | Description |
|--------|-------------|
| `list` | List all tags (no key required) |
| `add` | Add tag(s) to an entry |
| `remove` | Remove tag from an entry |
| `create` | Create a named tag with optional description |
| `delete` | Delete a tag (removes from all entries) |

### Tag Filtering

List and search operations support tag filtering:

```
clipboard_list(scope?, tags?, any_tags?)
```

- `tags=["a", "b"]` - entries with ALL specified tags
- `any_tags=True` - entries with ANY of specified tags

---

## Search

Search clipboard entries across keys, descriptions, and content:

```
clipboard_search(query, scope?, search_content?, search_keys?, search_descriptions?, tags?)
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `query` | required | Search string |
| `search_content` | True | Search in entry content |
| `search_keys` | True | Search in entry keys |
| `search_descriptions` | True | Search in descriptions |
| `tags` | None | Filter by tags |

---

## Import/Export

### Export

Export clipboard entries to JSON file:

```
clipboard_export(output_path, scope?, keys?, tags?)
```

- Exports to JSON with full metadata
- Can filter by specific keys or tags
- Useful for backup or sharing snippets

### Import

Import clipboard entries from JSON file:

```
clipboard_import(input_path, scope?, conflict?, dry_run?)
```

**Conflict resolution:**

| Value | Behavior |
|-------|----------|
| `skip` | Keep existing, skip duplicates |
| `overwrite` | Replace existing with imported |
| `rename` | Import as `key_1`, `key_2`, etc. |

Use `dry_run=True` to preview without applying changes.

---

## TTL (Time-to-Live)

Entries can have optional expiration times:

```python
copy(path="file.py", key="temp", ttl_seconds=3600)  # Expires in 1 hour
```

- `expires_at` computed as `created_at + ttl_seconds`
- Expired entries are NOT automatically deleted (requires user confirmation)
- Use `clipboard_list` to see expired entries marked
- `ClipboardEntry.is_expired` property checks expiration

**Why no auto-delete?** Accidental data loss is worse than stale entries. Cleanup should be explicit.

---

## Context Injection

The clipboard system can inject recent entries into the agent's system prompt:

```python
from nexus3.clipboard import format_clipboard_context

# Generate clipboard section for system prompt
section = format_clipboard_context(
    clipboard_manager,
    max_entries=10,      # Limit entries shown
    show_source=True,    # Include source file info
)
```

### Configuration

Context injection is controlled by `ClipboardConfig`:

```json
{
  "clipboard": {
    "inject_into_context": true,
    "max_injected_entries": 10,
    "show_source_in_injection": true
  }
}
```

When enabled, agents see their clipboard contents in the system prompt, helping them track available snippets without needing to call `clipboard_list`.

---

## Session Persistence

Agent-scope entries (in-memory) are saved with the session and restored on resume:

```python
# In SavedSession
clipboard_agent_entries: list[dict[str, Any]]
```

This allows temporary clipboard data to survive session save/restore cycles.

---

## Configuration

Full configuration options in `config.json`:

```json
{
  "clipboard": {
    "enabled": true,
    "inject_into_context": true,
    "max_injected_entries": 10,
    "show_source_in_injection": true,
    "max_entry_bytes": 1048576,
    "warn_entry_bytes": 102400,
    "default_ttl_seconds": null
  }
}
```

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `true` | Enable clipboard system |
| `inject_into_context` | `true` | Add clipboard to system prompt |
| `max_injected_entries` | `10` | Max entries in system prompt |
| `show_source_in_injection` | `true` | Show source file in injection |
| `max_entry_bytes` | 1MB | Hard limit per entry |
| `warn_entry_bytes` | 100KB | Warning threshold |
| `default_ttl_seconds` | `null` | Default TTL (null = permanent) |

---

## Permission Model

Clipboard permissions are derived from agent permission presets:

| Preset | Agent Scope | Project Read | Project Write | System Read | System Write |
|--------|-------------|--------------|---------------|-------------|--------------|
| `yolo` | Yes | Yes | Yes | Yes | Yes |
| `trusted` | Yes | Yes | Yes | Yes | No |
| `sandboxed` | Yes | No | No | No | No |

**Key behaviors:**

- Sandboxed agents can only use agent scope (in-memory, session-only)
- Trusted agents cannot write to system scope (prevents global pollution)
- All agents can use agent scope (safe default)

### ClipboardPermissions Type

```python
@dataclass
class ClipboardPermissions:
    agent_scope: bool = True
    project_read: bool = False
    project_write: bool = False
    system_read: bool = False
    system_write: bool = False

    def can_read(self, scope: ClipboardScope) -> bool: ...
    def can_write(self, scope: ClipboardScope) -> bool: ...
```

---

## Module Exports

### From `nexus3.clipboard`

```python
__all__ = [
    # Manager
    "ClipboardManager",
    # Storage
    "ClipboardStorage",
    # Types
    "ClipboardEntry",
    "ClipboardPermissions",
    "ClipboardScope",
    "ClipboardTag",
    "InsertionMode",
    # Constants
    "CLIPBOARD_PRESETS",
    "MAX_ENTRY_SIZE_BYTES",
    "WARN_ENTRY_SIZE_BYTES",
    # Injection
    "format_clipboard_context",
    "format_entry_detail",
]
```

---

## Dependencies

### Internal Dependencies

| Module | Used For |
|--------|----------|
| `nexus3.core.paths` | Path validation, atomic writes |
| `nexus3.config.schema` | ClipboardConfig |
| `nexus3.session.persistence` | SavedSession clipboard field |

### External Dependencies

| Package | Used For |
|---------|----------|
| `sqlite3` | Persistent storage (stdlib) |

---

## Usage Example

```python
from pathlib import Path
from nexus3.clipboard import ClipboardManager, ClipboardScope, CLIPBOARD_PRESETS

# Create manager for trusted agent
manager = ClipboardManager(
    agent_id="main",
    cwd=Path("/project"),
    permissions=CLIPBOARD_PRESETS["trusted"],
)

# Copy file content
manager.copy(
    key="utils",
    content=Path("utils.py").read_text(),
    scope=ClipboardScope.PROJECT,
    short_description="Utility functions",
    source_path="utils.py",
    tags=["code", "helpers"],
)

# List entries
entries = manager.list_entries(scope=ClipboardScope.PROJECT)
for entry in entries:
    print(f"{entry.key}: {entry.line_count} lines")

# Get and paste
entry = manager.get("utils", scope=ClipboardScope.PROJECT)
if entry:
    print(entry.content)

# Search
results = manager.search("def helper", scope=ClipboardScope.PROJECT)

# Export
manager.export_entries(
    output_path=Path("backup.json"),
    scope=ClipboardScope.PROJECT,
)
```
