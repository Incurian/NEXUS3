# Plan: Clipboard System - Scoped Copy/Paste for Agents

## Overview

A clipboard system that lets agents move large text chunks without passing content through LLM context twice. Content is stored server-side in SQLite databases with three scope levels (system, project, agent), and clipboard metadata is auto-injected into context for discoverability.

**Core benefit**: Moving 100 lines from file A to file B currently costs ~200 lines of context (read + write). With clipboard tools, it costs ~2 tool calls with minimal token overhead.

**Estimated effort**: ~12-16 hours total
- Phase 1 (Infrastructure): 4-5 hours
- Phase 2 (Core Skills): 3-4 hours
- Phase 3 (Management Skills): 2-3 hours
- Phase 4 (Context Injection): 1-2 hours
- Phase 5 (Permission Integration): 2 hours

---

## Architecture

### Storage Locations

| Scope | Database Path | Lifetime | Visibility |
|-------|---------------|----------|------------|
| `system` | `~/.nexus3/clipboard.db` | Permanent | All agents (permission-gated) |
| `project` | `.nexus3/clipboard.db` | Permanent | Agents in this project (permission-gated) |
| `agent` | In-memory dict | Session only | Single agent |

### Module Structure

```
nexus3/clipboard/
├── __init__.py          # Public API exports
├── types.py             # ClipboardEntry, ClipboardScope, PasteMode, InsertionMode
├── storage.py           # ClipboardStorage - SQLite operations
├── manager.py           # ClipboardManager - coordinates storage + permissions + scopes
└── injection.py         # format_clipboard_context() for system prompt injection
```

---

## Implementation Details

### Phase 1: Core Infrastructure

#### `nexus3/clipboard/types.py`

```python
"""Clipboard system types and dataclasses."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class ClipboardScope(Enum):
    """Clipboard entry scope levels."""
    AGENT = "agent"      # In-memory, session-only
    PROJECT = "project"  # .nexus3/clipboard.db in project root
    SYSTEM = "system"    # ~/.nexus3/clipboard.db


class InsertionMode(Enum):
    """How to insert clipboard content into target file."""
    AFTER_LINE = "after_line"
    BEFORE_LINE = "before_line"
    REPLACE_LINES = "replace_lines"
    AT_MARKER_REPLACE = "at_marker_replace"
    AT_MARKER_AFTER = "at_marker_after"
    AT_MARKER_BEFORE = "at_marker_before"
    APPEND = "append"
    PREPEND = "prepend"


@dataclass
class ClipboardEntry:
    """A single clipboard entry."""
    key: str
    scope: ClipboardScope
    content: str
    line_count: int
    byte_count: int
    short_description: str | None = None
    source_path: str | None = None       # Original file path
    source_lines: str | None = None      # "50-150" or None
    created_at: float = 0.0              # Unix timestamp
    modified_at: float = 0.0             # Unix timestamp
    created_by_agent: str | None = None
    modified_by_agent: str | None = None

    @classmethod
    def from_content(
        cls,
        key: str,
        scope: ClipboardScope,
        content: str,
        *,
        short_description: str | None = None,
        source_path: str | None = None,
        source_lines: str | None = None,
        agent_id: str | None = None,
    ) -> ClipboardEntry:
        """Create entry from content, computing line/byte counts."""
        import time
        now = time.time()
        return cls(
            key=key,
            scope=scope,
            content=content,
            line_count=content.count('\n') + (1 if content and not content.endswith('\n') else 0),
            byte_count=len(content.encode('utf-8')),
            short_description=short_description,
            source_path=source_path,
            source_lines=source_lines,
            created_at=now,
            modified_at=now,
            created_by_agent=agent_id,
            modified_by_agent=agent_id,
        )


@dataclass
class ClipboardPermissions:
    """Clipboard scope access permissions."""
    agent_scope: bool = True       # Can use agent-scoped clipboard
    project_read: bool = False     # Can read from project clipboard
    project_write: bool = False    # Can write to project clipboard
    system_read: bool = False      # Can read from system clipboard
    system_write: bool = False     # Can write to system clipboard

    def can_read(self, scope: ClipboardScope) -> bool:
        """Check if this permission set allows reading from scope."""
        if scope == ClipboardScope.AGENT:
            return self.agent_scope
        elif scope == ClipboardScope.PROJECT:
            return self.project_read
        elif scope == ClipboardScope.SYSTEM:
            return self.system_read
        return False

    def can_write(self, scope: ClipboardScope) -> bool:
        """Check if this permission set allows writing to scope."""
        if scope == ClipboardScope.AGENT:
            return self.agent_scope
        elif scope == ClipboardScope.PROJECT:
            return self.project_write
        elif scope == ClipboardScope.SYSTEM:
            return self.system_write
        return False


# Preset permission configurations
CLIPBOARD_PRESETS: dict[str, ClipboardPermissions] = {
    "yolo": ClipboardPermissions(
        agent_scope=True,
        project_read=True, project_write=True,
        system_read=True, system_write=True,
    ),
    "trusted": ClipboardPermissions(
        agent_scope=True,
        project_read=True, project_write=True,
        system_read=True, system_write=False,  # Can read system, not write
    ),
    "sandboxed": ClipboardPermissions(
        agent_scope=True,
        project_read=False, project_write=False,
        system_read=False, system_write=False,
    ),
    }
# Note: "worker" preset is deprecated and maps to "sandboxed" internally.
# Agents created with preset="worker" will use sandboxed clipboard permissions.


# Size limits
MAX_ENTRY_SIZE_BYTES = 1 * 1024 * 1024  # 1 MB hard limit
WARN_ENTRY_SIZE_BYTES = 100 * 1024       # 100 KB warning threshold
```

#### `nexus3/clipboard/storage.py`

```python
"""SQLite storage for clipboard entries."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING

from nexus3.clipboard.types import ClipboardEntry, ClipboardScope

if TYPE_CHECKING:
    pass

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS clipboard (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    content TEXT NOT NULL,
    short_description TEXT,
    source_path TEXT,
    source_lines TEXT,
    line_count INTEGER NOT NULL,
    byte_count INTEGER NOT NULL,
    created_at REAL NOT NULL,
    modified_at REAL NOT NULL,
    created_by_agent TEXT,
    modified_by_agent TEXT,
    UNIQUE(key)
);

CREATE INDEX IF NOT EXISTS idx_clipboard_key ON clipboard(key);

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class ClipboardStorage:
    """SQLite storage for a single clipboard scope (project or system)."""

    def __init__(self, db_path: Path, scope: ClipboardScope) -> None:
        """Initialize storage.

        Args:
            db_path: Path to SQLite database file
            scope: The scope this storage represents (for entry creation)
        """
        self._db_path = db_path
        self._scope = scope
        self._conn: sqlite3.Connection | None = None
        self._ensure_db()

    def _ensure_db(self) -> None:
        """Create database and tables if they don't exist."""
        # Create parent directory with secure permissions
        self._db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA_SQL)

        # Check/set schema version
        cur = self._conn.execute("SELECT value FROM metadata WHERE key = 'schema_version'")
        row = cur.fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION))
            )
            self._conn.commit()

    def _row_to_entry(self, row: sqlite3.Row) -> ClipboardEntry:
        """Convert database row to ClipboardEntry."""
        return ClipboardEntry(
            key=row["key"],
            scope=self._scope,
            content=row["content"],
            line_count=row["line_count"],
            byte_count=row["byte_count"],
            short_description=row["short_description"],
            source_path=row["source_path"],
            source_lines=row["source_lines"],
            created_at=row["created_at"],
            modified_at=row["modified_at"],
            created_by_agent=row["created_by_agent"],
            modified_by_agent=row["modified_by_agent"],
        )

    def get(self, key: str) -> ClipboardEntry | None:
        """Get entry by key, or None if not found."""
        assert self._conn is not None
        cur = self._conn.execute("SELECT * FROM clipboard WHERE key = ?", (key,))
        row = cur.fetchone()
        return self._row_to_entry(row) if row else None

    def exists(self, key: str) -> bool:
        """Check if key exists."""
        assert self._conn is not None
        cur = self._conn.execute("SELECT 1 FROM clipboard WHERE key = ?", (key,))
        return cur.fetchone() is not None

    def create(self, entry: ClipboardEntry) -> None:
        """Create new entry. Raises ValueError if key exists."""
        assert self._conn is not None
        if self.exists(entry.key):
            raise ValueError(f"Key '{entry.key}' already exists")

        self._conn.execute(
            """INSERT INTO clipboard
               (key, content, short_description, source_path, source_lines,
                line_count, byte_count, created_at, modified_at,
                created_by_agent, modified_by_agent)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.key, entry.content, entry.short_description,
                entry.source_path, entry.source_lines,
                entry.line_count, entry.byte_count,
                entry.created_at, entry.modified_at,
                entry.created_by_agent, entry.modified_by_agent,
            )
        )
        self._conn.commit()

    def update(
        self,
        key: str,
        *,
        content: str | None = None,
        short_description: str | None = None,
        source_path: str | None = None,
        source_lines: str | None = None,
        new_key: str | None = None,
        agent_id: str | None = None,
    ) -> ClipboardEntry:
        """Update existing entry. Returns updated entry. Raises KeyError if not found."""
        assert self._conn is not None

        entry = self.get(key)
        if entry is None:
            raise KeyError(f"Key '{key}' not found")

        if new_key is not None and new_key != key:
            if self.exists(new_key):
                raise ValueError(f"Key '{new_key}' already exists")

        # Build update
        updates: list[str] = []
        params: list[str | int | float | None] = []

        if content is not None:
            updates.extend(["content = ?", "line_count = ?", "byte_count = ?"])
            line_count = content.count('\n') + (1 if content and not content.endswith('\n') else 0)
            params.extend([content, line_count, len(content.encode('utf-8'))])

        if short_description is not None:
            updates.append("short_description = ?")
            params.append(short_description)

        if source_path is not None:
            updates.append("source_path = ?")
            params.append(source_path)

        if source_lines is not None:
            updates.append("source_lines = ?")
            params.append(source_lines)

        if new_key is not None:
            updates.append("key = ?")
            params.append(new_key)

        # Always update modified_at and modified_by_agent
        updates.append("modified_at = ?")
        params.append(time.time())
        updates.append("modified_by_agent = ?")
        params.append(agent_id)

        params.append(key)  # WHERE clause

        self._conn.execute(
            f"UPDATE clipboard SET {', '.join(updates)} WHERE key = ?",
            params
        )
        self._conn.commit()

        return self.get(new_key if new_key else key)  # type: ignore

    def delete(self, key: str) -> bool:
        """Delete entry by key. Returns True if deleted, False if not found."""
        assert self._conn is not None
        cur = self._conn.execute("DELETE FROM clipboard WHERE key = ?", (key,))
        self._conn.commit()
        return cur.rowcount > 0

    def clear(self) -> int:
        """Delete all entries. Returns count of deleted entries."""
        assert self._conn is not None
        cur = self._conn.execute("DELETE FROM clipboard")
        self._conn.commit()
        return cur.rowcount

    def list_all(self) -> list[ClipboardEntry]:
        """List all entries, ordered by modified_at descending."""
        assert self._conn is not None
        cur = self._conn.execute(
            "SELECT * FROM clipboard ORDER BY modified_at DESC"
        )
        return [self._row_to_entry(row) for row in cur.fetchall()]

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
```

#### `nexus3/clipboard/manager.py`

```python
"""ClipboardManager - coordinates storage, permissions, and scope resolution."""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from nexus3.clipboard.storage import ClipboardStorage
from nexus3.clipboard.types import (
    CLIPBOARD_PRESETS,
    MAX_ENTRY_SIZE_BYTES,
    WARN_ENTRY_SIZE_BYTES,
    ClipboardEntry,
    ClipboardPermissions,
    ClipboardScope,
)

if TYPE_CHECKING:
    pass


class ClipboardManager:
    """Manages clipboard operations across all scopes with permission enforcement."""

    def __init__(
        self,
        agent_id: str,
        cwd: Path,
        permissions: ClipboardPermissions | None = None,
        home_dir: Path | None = None,
    ) -> None:
        """Initialize clipboard manager.

        Args:
            agent_id: Current agent's ID (for tracking modifications)
            cwd: Current working directory (for project scope resolution)
            permissions: Clipboard permissions (defaults to sandboxed)
            home_dir: Home directory override (for testing)
        """
        self._agent_id = agent_id
        self._cwd = cwd
        self._permissions = permissions or CLIPBOARD_PRESETS["sandboxed"]
        self._home_dir = home_dir or Path.home()

        # Agent scope: in-memory only
        self._agent_clipboard: dict[str, ClipboardEntry] = {}

        # Lazy-loaded persistent storage
        self._project_storage: ClipboardStorage | None = None
        self._system_storage: ClipboardStorage | None = None

    def _get_project_storage(self) -> ClipboardStorage:
        """Get or create project-scope storage."""
        if self._project_storage is None:
            db_path = self._cwd / ".nexus3" / "clipboard.db"
            self._project_storage = ClipboardStorage(db_path, ClipboardScope.PROJECT)
        return self._project_storage

    def _get_system_storage(self) -> ClipboardStorage:
        """Get or create system-scope storage."""
        if self._system_storage is None:
            db_path = self._home_dir / ".nexus3" / "clipboard.db"
            self._system_storage = ClipboardStorage(db_path, ClipboardScope.SYSTEM)
        return self._system_storage

    def _check_read_permission(self, scope: ClipboardScope) -> None:
        """Raise PermissionError if read not allowed for scope."""
        if not self._permissions.can_read(scope):
            raise PermissionError(f"No read permission for {scope.value} clipboard")

    def _check_write_permission(self, scope: ClipboardScope) -> None:
        """Raise PermissionError if write not allowed for scope."""
        if not self._permissions.can_write(scope):
            raise PermissionError(f"No write permission for {scope.value} clipboard")

    def _validate_size(self, content: str) -> str | None:
        """Validate content size. Returns warning message or None."""
        size = len(content.encode('utf-8'))
        if size > MAX_ENTRY_SIZE_BYTES:
            raise ValueError(
                f"Content size ({size:,} bytes) exceeds maximum ({MAX_ENTRY_SIZE_BYTES:,} bytes)"
            )
        if size > WARN_ENTRY_SIZE_BYTES:
            return f"Warning: Large clipboard entry ({size:,} bytes)"
        return None

    # --- Core Operations ---

    def copy(
        self,
        key: str,
        content: str,
        scope: ClipboardScope = ClipboardScope.AGENT,
        *,
        short_description: str | None = None,
        source_path: str | None = None,
        source_lines: str | None = None,
    ) -> tuple[ClipboardEntry, str | None]:
        """Copy content to clipboard.

        Returns:
            Tuple of (created entry, warning message or None)

        Raises:
            PermissionError: If scope not accessible
            ValueError: If key already exists or content too large
        """
        self._check_write_permission(scope)
        warning = self._validate_size(content)

        entry = ClipboardEntry.from_content(
            key=key,
            scope=scope,
            content=content,
            short_description=short_description,
            source_path=source_path,
            source_lines=source_lines,
            agent_id=self._agent_id,
        )

        if scope == ClipboardScope.AGENT:
            if key in self._agent_clipboard:
                raise ValueError(
                    f"Key '{key}' already exists in agent scope. "
                    "Use clipboard_update to modify or choose a different key."
                )
            self._agent_clipboard[key] = entry
        elif scope == ClipboardScope.PROJECT:
            try:
                self._get_project_storage().create(entry)
            except ValueError:
                raise ValueError(
                    f"Key '{key}' already exists in project scope. "
                    "Use clipboard_update to modify or choose a different key."
                )
        elif scope == ClipboardScope.SYSTEM:
            try:
                self._get_system_storage().create(entry)
            except ValueError:
                raise ValueError(
                    f"Key '{key}' already exists in system scope. "
                    "Use clipboard_update to modify or choose a different key."
                )

        return entry, warning

    def get(
        self,
        key: str,
        scope: ClipboardScope | None = None,
    ) -> ClipboardEntry | None:
        """Get entry by key.

        Args:
            key: Clipboard key
            scope: Specific scope to search, or None to search agent→project→system

        Returns:
            Entry if found, None otherwise

        Raises:
            PermissionError: If scope not accessible
        """
        if scope is not None:
            # Search specific scope
            self._check_read_permission(scope)
            return self._get_from_scope(key, scope)

        # Search all accessible scopes in order: agent → project → system
        for s in [ClipboardScope.AGENT, ClipboardScope.PROJECT, ClipboardScope.SYSTEM]:
            if self._permissions.can_read(s):
                entry = self._get_from_scope(key, s)
                if entry is not None:
                    return entry
        return None

    def _get_from_scope(self, key: str, scope: ClipboardScope) -> ClipboardEntry | None:
        """Get entry from specific scope (no permission check)."""
        if scope == ClipboardScope.AGENT:
            return self._agent_clipboard.get(key)
        elif scope == ClipboardScope.PROJECT:
            return self._get_project_storage().get(key)
        elif scope == ClipboardScope.SYSTEM:
            return self._get_system_storage().get(key)
        return None

    def update(
        self,
        key: str,
        scope: ClipboardScope,
        *,
        content: str | None = None,
        short_description: str | None = None,
        source_path: str | None = None,
        source_lines: str | None = None,
        new_key: str | None = None,
    ) -> tuple[ClipboardEntry, str | None]:
        """Update existing entry.

        Returns:
            Tuple of (updated entry, warning message or None)
        """
        self._check_write_permission(scope)

        warning = None
        if content is not None:
            warning = self._validate_size(content)

        if scope == ClipboardScope.AGENT:
            if key not in self._agent_clipboard:
                raise KeyError(f"Key '{key}' not found in agent scope")
            if new_key is not None and new_key != key and new_key in self._agent_clipboard:
                raise ValueError(f"Key '{new_key}' already exists in agent scope")

            entry = self._agent_clipboard[key]
            if content is not None:
                entry.content = content
                entry.line_count = content.count('\n') + (1 if content and not content.endswith('\n') else 0)
                entry.byte_count = len(content.encode('utf-8'))
            if short_description is not None:
                entry.short_description = short_description
            if source_path is not None:
                entry.source_path = source_path
            if source_lines is not None:
                entry.source_lines = source_lines
            entry.modified_at = time.time()
            entry.modified_by_agent = self._agent_id

            if new_key is not None and new_key != key:
                entry.key = new_key
                del self._agent_clipboard[key]
                self._agent_clipboard[new_key] = entry

            return entry, warning

        elif scope == ClipboardScope.PROJECT:
            entry = self._get_project_storage().update(
                key,
                content=content,
                short_description=short_description,
                source_path=source_path,
                source_lines=source_lines,
                new_key=new_key,
                agent_id=self._agent_id,
            )
            return entry, warning

        elif scope == ClipboardScope.SYSTEM:
            entry = self._get_system_storage().update(
                key,
                content=content,
                short_description=short_description,
                source_path=source_path,
                source_lines=source_lines,
                new_key=new_key,
                agent_id=self._agent_id,
            )
            return entry, warning

        raise ValueError(f"Unknown scope: {scope}")

    def delete(self, key: str, scope: ClipboardScope) -> bool:
        """Delete entry. Returns True if deleted."""
        self._check_write_permission(scope)

        if scope == ClipboardScope.AGENT:
            if key in self._agent_clipboard:
                del self._agent_clipboard[key]
                return True
            return False
        elif scope == ClipboardScope.PROJECT:
            return self._get_project_storage().delete(key)
        elif scope == ClipboardScope.SYSTEM:
            return self._get_system_storage().delete(key)
        return False

    def clear(self, scope: ClipboardScope) -> int:
        """Clear all entries in scope. Returns count deleted."""
        self._check_write_permission(scope)

        if scope == ClipboardScope.AGENT:
            count = len(self._agent_clipboard)
            self._agent_clipboard.clear()
            return count
        elif scope == ClipboardScope.PROJECT:
            return self._get_project_storage().clear()
        elif scope == ClipboardScope.SYSTEM:
            return self._get_system_storage().clear()
        return 0

    def list_entries(
        self,
        scope: ClipboardScope | None = None,
    ) -> list[ClipboardEntry]:
        """List entries, optionally filtered by scope.

        Returns entries sorted by modified_at descending.
        Only includes entries from scopes the agent can read.
        """
        entries: list[ClipboardEntry] = []

        scopes = [scope] if scope else [ClipboardScope.AGENT, ClipboardScope.PROJECT, ClipboardScope.SYSTEM]

        for s in scopes:
            if not self._permissions.can_read(s):
                continue

            if s == ClipboardScope.AGENT:
                entries.extend(self._agent_clipboard.values())
            elif s == ClipboardScope.PROJECT:
                entries.extend(self._get_project_storage().list_all())
            elif s == ClipboardScope.SYSTEM:
                entries.extend(self._get_system_storage().list_all())

        # Sort by modified_at descending
        entries.sort(key=lambda e: e.modified_at, reverse=True)
        return entries

    def close(self) -> None:
        """Close any open database connections."""
        if self._project_storage:
            self._project_storage.close()
        if self._system_storage:
            self._system_storage.close()
```

#### `nexus3/clipboard/injection.py`

```python
"""Context injection for clipboard entries."""
from __future__ import annotations

from typing import TYPE_CHECKING

from nexus3.clipboard.types import ClipboardEntry

if TYPE_CHECKING:
    from nexus3.clipboard.manager import ClipboardManager


def format_clipboard_context(
    manager: ClipboardManager,
    max_entries: int = 10,
    show_source: bool = True,
) -> str | None:
    """Format clipboard entries for system prompt injection.

    Args:
        manager: ClipboardManager to list entries from
        max_entries: Maximum entries to show
        show_source: Include source path/lines info

    Returns:
        Formatted markdown string, or None if no entries
    """
    entries = manager.list_entries()
    if not entries:
        return None

    entries = entries[:max_entries]

    lines = [
        "## Available Clipboard Entries",
        "",
        "| Key | Scope | Lines | Description |",
        "|-----|-------|-------|-------------|",
    ]

    for entry in entries:
        desc = entry.short_description or ""
        if not desc and show_source and entry.source_path:
            desc = f"from {entry.source_path}"
            if entry.source_lines:
                desc += f":{entry.source_lines}"

        lines.append(
            f"| {entry.key} | {entry.scope.value} | {entry.line_count} | {desc} |"
        )

    lines.extend([
        "",
        'Use `paste(key="...")` to insert content. Use `clipboard_list(verbose=True)` to preview.',
    ])

    return "\n".join(lines)


def format_time_ago(timestamp: float) -> str:
    """Format timestamp as relative time (e.g., '2m ago', '3d ago')."""
    import time

    delta = time.time() - timestamp
    if delta < 60:
        return "just now"
    elif delta < 3600:
        return f"{int(delta / 60)}m ago"
    elif delta < 86400:
        return f"{int(delta / 3600)}h ago"
    else:
        return f"{int(delta / 86400)}d ago"


def format_entry_detail(entry: ClipboardEntry, verbose: bool = False) -> str:
    """Format a single entry for clipboard_list output."""
    lines = []

    # Header: [scope] key (lines, size) - description
    size_str = _format_size(entry.byte_count)
    header = f"[{entry.scope.value}] {entry.key} ({entry.line_count} lines, {size_str})"
    if entry.short_description:
        header += f' - "{entry.short_description}"'
    lines.append(header)

    # Source and modification info
    meta_parts = []
    if entry.source_path:
        source = f"Source: {entry.source_path}"
        if entry.source_lines:
            source += f":{entry.source_lines}"
        meta_parts.append(source)

    meta_parts.append(f"Modified: {format_time_ago(entry.modified_at)}")
    if entry.modified_by_agent:
        meta_parts[-1] += f" by {entry.modified_by_agent}"

    lines.append("        " + " | ".join(meta_parts))

    # Content preview if verbose
    if verbose:
        content_lines = entry.content.splitlines()
        preview_lines = []
        if len(content_lines) <= 6:
            preview_lines = content_lines
        else:
            preview_lines = content_lines[:3] + ["..."] + content_lines[-3:]

        lines.append("        ---")
        for pl in preview_lines:
            # Truncate long lines
            if len(pl) > 80:
                pl = pl[:77] + "..."
            lines.append("        " + pl)

    return "\n".join(lines)


def _format_size(byte_count: int) -> str:
    """Format byte count as human-readable size."""
    if byte_count < 1024:
        return f"{byte_count}B"
    elif byte_count < 1024 * 1024:
        return f"{byte_count / 1024:.1f}KB"
    else:
        return f"{byte_count / (1024 * 1024):.1f}MB"
```

#### `nexus3/clipboard/__init__.py`

```python
"""Clipboard system for NEXUS3 agents."""
from nexus3.clipboard.injection import format_clipboard_context, format_entry_detail
from nexus3.clipboard.manager import ClipboardManager
from nexus3.clipboard.storage import ClipboardStorage
from nexus3.clipboard.types import (
    CLIPBOARD_PRESETS,
    ClipboardEntry,
    ClipboardPermissions,
    ClipboardScope,
    InsertionMode,
    MAX_ENTRY_SIZE_BYTES,
    WARN_ENTRY_SIZE_BYTES,
)

__all__ = [
    "ClipboardManager",
    "ClipboardStorage",
    "ClipboardEntry",
    "ClipboardPermissions",
    "ClipboardScope",
    "InsertionMode",
    "CLIPBOARD_PRESETS",
    "MAX_ENTRY_SIZE_BYTES",
    "WARN_ENTRY_SIZE_BYTES",
    "format_clipboard_context",
    "format_entry_detail",
]
```

---

### Phase 2: Core Skills

#### `nexus3/skill/builtin/clipboard_copy.py`

```python
"""Copy and cut skills for clipboard operations."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from nexus3.clipboard import ClipboardManager, ClipboardScope
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory

if TYPE_CHECKING:
    from nexus3.skill.services import ServiceContainer


class CopySkill(FileSkill):
    """Copy file content to clipboard without passing through LLM context."""

    @property
    def name(self) -> str:
        return "copy"

    @property
    def description(self) -> str:
        return (
            "Copy file content to clipboard. Content is stored server-side and "
            "never enters context. Use paste() to insert into another file. "
            "Keys must be unique within scope; use clipboard_update to modify existing."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Path to file to copy from",
                },
                "key": {
                    "type": "string",
                    "description": "Clipboard key name (must be unique in scope)",
                },
                "scope": {
                    "type": "string",
                    "enum": ["agent", "project", "system"],
                    "default": "agent",
                    "description": "Clipboard scope: agent (session-only), project (persistent in .nexus3/), system (persistent in ~/.nexus3/)",
                },
                "start_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "First line to copy (1-indexed, inclusive). Omit for whole file.",
                },
                "end_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Last line to copy (inclusive). Defaults to start_line if start_line provided.",
                },
                "short_description": {
                    "type": "string",
                    "description": "Optional description for clipboard_list display",
                },
            },
            "required": ["source", "key"],
        }

    async def execute(
        self,
        source: str = "",
        key: str = "",
        scope: str = "agent",
        start_line: int | None = None,
        end_line: int | None = None,
        short_description: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        # Validate source path
        validated = self._validate_path(source)
        if isinstance(validated, ToolResult):
            return validated
        source_path: Path = validated

        # Read file content
        try:
            content = source_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return ToolResult(error=f"Cannot read file: {e}")

        # Extract line range if specified
        source_lines_str: str | None = None
        if start_line is not None:
            lines = content.splitlines(keepends=True)
            if start_line < 1 or start_line > len(lines):
                return ToolResult(error=f"start_line {start_line} out of range (file has {len(lines)} lines)")

            end = end_line if end_line is not None else start_line
            if end < start_line:
                return ToolResult(error=f"end_line {end} cannot be less than start_line {start_line}")
            if end > len(lines):
                return ToolResult(error=f"end_line {end} out of range (file has {len(lines)} lines)")

            content = "".join(lines[start_line - 1:end])
            source_lines_str = f"{start_line}-{end}" if end != start_line else str(start_line)

        # Get clipboard manager from services
        manager = self._get_clipboard_manager()
        if manager is None:
            return ToolResult(error="Clipboard service not available")

        # Parse scope
        try:
            clip_scope = ClipboardScope(scope)
        except ValueError:
            return ToolResult(error=f"Invalid scope: {scope}. Use 'agent', 'project', or 'system'.")

        # Copy to clipboard
        try:
            entry, warning = manager.copy(
                key=key,
                content=content,
                scope=clip_scope,
                short_description=short_description,
                source_path=str(source_path),
                source_lines=source_lines_str,
            )
        except PermissionError as e:
            return ToolResult(error=str(e))
        except ValueError as e:
            return ToolResult(error=str(e))

        # Build result message
        msg = f"Copied {entry.line_count} lines from {source_path}"
        if source_lines_str:
            msg = f"Copied {entry.line_count} lines from {source_path}:{source_lines_str}"
        msg += f" to clipboard '{key}' [{scope} scope]"

        if warning:
            msg = f"{warning}\n{msg}"

        return ToolResult(output=msg)

    def _get_clipboard_manager(self) -> ClipboardManager | None:
        """Get ClipboardManager from services."""
        return self._services.get("clipboard_manager")


class CutSkill(CopySkill):
    """Cut (copy + delete) file content to clipboard."""

    @property
    def name(self) -> str:
        return "cut"

    @property
    def description(self) -> str:
        return (
            "Cut file content to clipboard (copy then remove from source). "
            "Content is stored server-side and never enters context. "
            "Use paste() to insert into another file."
        )

    async def execute(
        self,
        source: str = "",
        key: str = "",
        scope: str = "agent",
        start_line: int | None = None,
        end_line: int | None = None,
        short_description: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        # First, do the copy
        result = await super().execute(
            source=source,
            key=key,
            scope=scope,
            start_line=start_line,
            end_line=end_line,
            short_description=short_description,
            **kwargs,
        )

        if result.error:
            return result

        # Now remove the lines from source file
        validated = self._validate_path(source)
        if isinstance(validated, ToolResult):
            return validated
        source_path: Path = validated

        # Check write permission (FileSkill handles allowed_paths)
        # Re-read to ensure we have current content
        try:
            content = source_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return ToolResult(error=f"Cannot read file for cut: {e}")

        if start_line is not None:
            lines = content.splitlines(keepends=True)
            end = end_line if end_line is not None else start_line

            # Remove the lines
            new_lines = lines[:start_line - 1] + lines[end:]
            new_content = "".join(new_lines)
        else:
            # Whole file cut - leave empty file
            new_content = ""

        try:
            source_path.write_text(new_content, encoding="utf-8")
        except OSError as e:
            return ToolResult(error=f"Copied to clipboard but failed to remove from source: {e}")

        # Modify output message
        output = result.output or ""
        output = output.replace("Copied", "Cut")
        return ToolResult(output=output)


copy_skill_factory = file_skill_factory(CopySkill)
cut_skill_factory = file_skill_factory(CutSkill)
```

#### `nexus3/skill/builtin/clipboard_paste.py`

```python
"""Paste skill for clipboard operations."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from nexus3.clipboard import ClipboardManager, ClipboardScope, InsertionMode
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory

if TYPE_CHECKING:
    from nexus3.skill.services import ServiceContainer


class PasteSkill(FileSkill):
    """Paste clipboard content into a file."""

    @property
    def name(self) -> str:
        return "paste"

    @property
    def description(self) -> str:
        return (
            "Paste clipboard content into a file. Content is inserted without "
            "passing through LLM context. Specify exactly one insertion mode."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Clipboard key to paste",
                },
                "target": {
                    "type": "string",
                    "description": "Path to file to paste into",
                },
                "scope": {
                    "type": "string",
                    "enum": ["agent", "project", "system"],
                    "description": "Scope to search for key. If omitted, searches agent→project→system.",
                },
                # Insertion modes (mutually exclusive)
                "after_line": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Insert after this line number (0 = before first line)",
                },
                "before_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Insert before this line number",
                },
                "replace_lines": {
                    "type": "string",
                    "description": 'Line range to replace, e.g., "10-20"',
                },
                "at_marker": {
                    "type": "string",
                    "description": "Text marker to find for insertion point",
                },
                "marker_mode": {
                    "type": "string",
                    "enum": ["replace", "after", "before"],
                    "default": "replace",
                    "description": "How to handle marker: replace it, insert after it, or insert before it",
                },
                "append": {
                    "type": "boolean",
                    "default": False,
                    "description": "Append to end of file",
                },
                "prepend": {
                    "type": "boolean",
                    "default": False,
                    "description": "Prepend to start of file",
                },
            },
            "required": ["key", "target"],
        }

    async def execute(
        self,
        key: str = "",
        target: str = "",
        scope: str | None = None,
        after_line: int | None = None,
        before_line: int | None = None,
        replace_lines: str | None = None,
        at_marker: str | None = None,
        marker_mode: str = "replace",
        append: bool = False,
        prepend: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        # Validate target path
        validated = self._validate_path(target)
        if isinstance(validated, ToolResult):
            return validated
        target_path: Path = validated

        # Determine insertion mode
        mode_count = sum([
            after_line is not None,
            before_line is not None,
            replace_lines is not None,
            at_marker is not None,
            append,
            prepend,
        ])

        if mode_count == 0:
            return ToolResult(
                error="Must specify one insertion mode: after_line, before_line, "
                      "replace_lines, at_marker, append, or prepend"
            )
        if mode_count > 1:
            return ToolResult(
                error="Only one insertion mode allowed. Got multiple of: "
                      "after_line, before_line, replace_lines, at_marker, append, prepend"
            )

        # Get clipboard manager
        manager = self._get_clipboard_manager()
        if manager is None:
            return ToolResult(error="Clipboard service not available")

        # Parse scope
        clip_scope: ClipboardScope | None = None
        if scope is not None:
            try:
                clip_scope = ClipboardScope(scope)
            except ValueError:
                return ToolResult(error=f"Invalid scope: {scope}")

        # Get clipboard entry
        try:
            entry = manager.get(key, clip_scope)
        except PermissionError as e:
            return ToolResult(error=str(e))

        if entry is None:
            if scope:
                return ToolResult(error=f"Key '{key}' not found in {scope} scope")
            return ToolResult(error=f"Key '{key}' not found in any accessible scope")

        clipboard_content = entry.content

        # Read target file (create if doesn't exist for append/prepend)
        if target_path.exists():
            try:
                file_content = target_path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                return ToolResult(error=f"Cannot read target file: {e}")
        else:
            if append or prepend:
                file_content = ""
            else:
                return ToolResult(error=f"Target file does not exist: {target_path}")

        # Apply insertion
        try:
            new_content, desc = self._apply_insertion(
                file_content=file_content,
                clipboard_content=clipboard_content,
                after_line=after_line,
                before_line=before_line,
                replace_lines=replace_lines,
                at_marker=at_marker,
                marker_mode=marker_mode,
                append=append,
                prepend=prepend,
            )
        except ValueError as e:
            return ToolResult(error=str(e))

        # Write result
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(new_content, encoding="utf-8")
        except OSError as e:
            return ToolResult(error=f"Cannot write to target file: {e}")

        return ToolResult(
            output=f"Pasted '{key}' ({entry.line_count} lines) into {target_path} {desc}"
        )

    def _apply_insertion(
        self,
        file_content: str,
        clipboard_content: str,
        after_line: int | None,
        before_line: int | None,
        replace_lines: str | None,
        at_marker: str | None,
        marker_mode: str,
        append: bool,
        prepend: bool,
    ) -> tuple[str, str]:
        """Apply insertion mode. Returns (new_content, description)."""

        # Ensure clipboard content ends with newline for clean insertion
        if clipboard_content and not clipboard_content.endswith('\n'):
            clipboard_content += '\n'

        lines = file_content.splitlines(keepends=True)

        if append:
            # Ensure file ends with newline before appending
            if file_content and not file_content.endswith('\n'):
                return file_content + '\n' + clipboard_content, "at end of file"
            return file_content + clipboard_content, "at end of file"

        if prepend:
            return clipboard_content + file_content, "at start of file"

        if after_line is not None:
            if after_line < 0:
                raise ValueError("after_line cannot be negative")
            if after_line > len(lines):
                raise ValueError(f"after_line {after_line} out of range (file has {len(lines)} lines)")

            new_lines = lines[:after_line] + [clipboard_content] + lines[after_line:]
            return "".join(new_lines), f"after line {after_line}"

        if before_line is not None:
            if before_line < 1:
                raise ValueError("before_line must be >= 1")
            if before_line > len(lines) + 1:
                raise ValueError(f"before_line {before_line} out of range (file has {len(lines)} lines)")

            new_lines = lines[:before_line - 1] + [clipboard_content] + lines[before_line - 1:]
            return "".join(new_lines), f"before line {before_line}"

        if replace_lines is not None:
            # Parse "start-end" format
            if "-" not in replace_lines:
                raise ValueError(f"replace_lines must be 'start-end' format, got: {replace_lines}")
            parts = replace_lines.split("-", 1)
            try:
                start = int(parts[0])
                end = int(parts[1])
            except ValueError:
                raise ValueError(f"Invalid line numbers in replace_lines: {replace_lines}")

            if start < 1:
                raise ValueError("replace_lines start must be >= 1")
            if end < start:
                raise ValueError(f"replace_lines end ({end}) cannot be less than start ({start})")
            if start > len(lines):
                raise ValueError(f"replace_lines start {start} out of range (file has {len(lines)} lines)")
            if end > len(lines):
                raise ValueError(f"replace_lines end {end} out of range (file has {len(lines)} lines)")

            new_lines = lines[:start - 1] + [clipboard_content] + lines[end:]
            return "".join(new_lines), f"replacing lines {start}-{end}"

        if at_marker is not None:
            # Find marker in file
            marker_count = file_content.count(at_marker)
            if marker_count == 0:
                raise ValueError(f"Marker not found: {at_marker}")
            if marker_count > 1:
                raise ValueError(f"Marker found {marker_count} times (must be unique): {at_marker}")

            if marker_mode == "replace":
                new_content = file_content.replace(at_marker, clipboard_content.rstrip('\n'), 1)
                return new_content, f"replacing marker"
            elif marker_mode == "after":
                idx = file_content.find(at_marker)
                insert_pos = idx + len(at_marker)
                # Find end of line
                newline_pos = file_content.find('\n', insert_pos)
                if newline_pos == -1:
                    new_content = file_content + '\n' + clipboard_content
                else:
                    new_content = file_content[:newline_pos + 1] + clipboard_content + file_content[newline_pos + 1:]
                return new_content, f"after marker"
            elif marker_mode == "before":
                idx = file_content.find(at_marker)
                # Find start of line containing marker
                line_start = file_content.rfind('\n', 0, idx)
                if line_start == -1:
                    new_content = clipboard_content + file_content
                else:
                    new_content = file_content[:line_start + 1] + clipboard_content + file_content[line_start + 1:]
                return new_content, f"before marker"
            else:
                raise ValueError(f"Invalid marker_mode: {marker_mode}")

        raise ValueError("No insertion mode specified")

    def _get_clipboard_manager(self) -> ClipboardManager | None:
        """Get ClipboardManager from services."""
        return self._services.get("clipboard_manager")


paste_skill_factory = file_skill_factory(PasteSkill)
```

#### `nexus3/skill/builtin/clipboard_manage.py`

```python
"""Management skills for clipboard: list, get, update, delete, clear."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus3.clipboard import ClipboardManager, ClipboardScope, format_entry_detail
from nexus3.core.types import ToolResult
from nexus3.skill.base import BaseSkill, base_skill_factory

if TYPE_CHECKING:
    from nexus3.skill.services import ServiceContainer


class ClipboardListSkill(BaseSkill):
    """List available clipboard entries."""

    @property
    def name(self) -> str:
        return "clipboard_list"

    @property
    def description(self) -> str:
        return "List clipboard entries across all accessible scopes."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["agent", "project", "system"],
                    "description": "Filter by scope. Omit to show all accessible scopes.",
                },
                "verbose": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include content preview (first/last 3 lines)",
                },
            },
        }

    async def execute(
        self,
        scope: str | None = None,
        verbose: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        manager = self._services.get("clipboard_manager")
        if manager is None:
            return ToolResult(error="Clipboard service not available")

        clip_scope: ClipboardScope | None = None
        if scope is not None:
            try:
                clip_scope = ClipboardScope(scope)
            except ValueError:
                return ToolResult(error=f"Invalid scope: {scope}")

        try:
            entries = manager.list_entries(clip_scope)
        except PermissionError as e:
            return ToolResult(error=str(e))

        if not entries:
            if scope:
                return ToolResult(output=f"No clipboard entries in {scope} scope")
            return ToolResult(output="No clipboard entries")

        lines = ["Clipboard entries:", ""]
        for entry in entries:
            lines.append(format_entry_detail(entry, verbose=verbose))
            lines.append("")

        return ToolResult(output="\n".join(lines))


class ClipboardGetSkill(BaseSkill):
    """Get clipboard entry content."""

    @property
    def name(self) -> str:
        return "clipboard_get"

    @property
    def description(self) -> str:
        return (
            "Get the content of a clipboard entry. Use sparingly for large entries "
            "as content enters LLM context. For inspection, use clipboard_list(verbose=True)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Clipboard key",
                },
                "scope": {
                    "type": "string",
                    "enum": ["agent", "project", "system"],
                    "description": "Scope to search. Omit to search agent→project→system.",
                },
                "start_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Return subset starting at this line",
                },
                "end_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Return subset ending at this line (inclusive)",
                },
            },
            "required": ["key"],
        }

    async def execute(
        self,
        key: str = "",
        scope: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        manager = self._services.get("clipboard_manager")
        if manager is None:
            return ToolResult(error="Clipboard service not available")

        clip_scope: ClipboardScope | None = None
        if scope is not None:
            try:
                clip_scope = ClipboardScope(scope)
            except ValueError:
                return ToolResult(error=f"Invalid scope: {scope}")

        try:
            entry = manager.get(key, clip_scope)
        except PermissionError as e:
            return ToolResult(error=str(e))

        if entry is None:
            if scope:
                return ToolResult(error=f"Key '{key}' not found in {scope} scope")
            return ToolResult(error=f"Key '{key}' not found in any accessible scope")

        content = entry.content

        # Apply line range if specified
        if start_line is not None or end_line is not None:
            lines = content.splitlines(keepends=True)
            start = (start_line or 1) - 1
            end = end_line or len(lines)

            if start < 0 or start >= len(lines):
                return ToolResult(error=f"start_line out of range (entry has {len(lines)} lines)")
            if end > len(lines):
                return ToolResult(error=f"end_line out of range (entry has {len(lines)} lines)")
            if end <= start:
                return ToolResult(error="end_line must be greater than start_line")

            content = "".join(lines[start:end])

        return ToolResult(output=content)


class ClipboardUpdateSkill(BaseSkill):
    """Update an existing clipboard entry."""

    @property
    def name(self) -> str:
        return "clipboard_update"

    @property
    def description(self) -> str:
        return (
            "Update an existing clipboard entry. Can update content from a file, "
            "change description, or rename the key."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Existing clipboard key to update",
                },
                "scope": {
                    "type": "string",
                    "enum": ["agent", "project", "system"],
                    "description": "Scope of the entry (required)",
                },
                "source": {
                    "type": "string",
                    "description": "New file to copy content from",
                },
                "content": {
                    "type": "string",
                    "description": "New content directly (use source for files)",
                },
                "start_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "If source provided, first line to copy",
                },
                "end_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "If source provided, last line to copy",
                },
                "short_description": {
                    "type": "string",
                    "description": "New description",
                },
                "new_key": {
                    "type": "string",
                    "description": "Rename entry to this key",
                },
            },
            "required": ["key", "scope"],
        }

    async def execute(
        self,
        key: str = "",
        scope: str = "",
        source: str | None = None,
        content: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
        short_description: str | None = None,
        new_key: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        manager = self._services.get("clipboard_manager")
        if manager is None:
            return ToolResult(error="Clipboard service not available")

        try:
            clip_scope = ClipboardScope(scope)
        except ValueError:
            return ToolResult(error=f"Invalid scope: {scope}")

        # If source provided, read file content
        new_content = content
        source_path_str: str | None = None
        source_lines_str: str | None = None

        if source is not None:
            from pathlib import Path
            source_path = Path(source).expanduser().resolve()
            try:
                file_content = source_path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                return ToolResult(error=f"Cannot read source file: {e}")

            if start_line is not None:
                lines = file_content.splitlines(keepends=True)
                if start_line < 1 or start_line > len(lines):
                    return ToolResult(error=f"start_line out of range (file has {len(lines)} lines)")
                end = end_line if end_line is not None else start_line
                if end > len(lines):
                    return ToolResult(error=f"end_line out of range (file has {len(lines)} lines)")
                new_content = "".join(lines[start_line - 1:end])
                source_lines_str = f"{start_line}-{end}" if end != start_line else str(start_line)
            else:
                new_content = file_content

            source_path_str = str(source_path)

        try:
            entry, warning = manager.update(
                key,
                clip_scope,
                content=new_content,
                short_description=short_description,
                source_path=source_path_str,
                source_lines=source_lines_str,
                new_key=new_key,
            )
        except (PermissionError, KeyError, ValueError) as e:
            return ToolResult(error=str(e))

        msg = f"Updated clipboard '{entry.key}' [{scope} scope]: {entry.line_count} lines"
        if warning:
            msg = f"{warning}\n{msg}"

        return ToolResult(output=msg)


class ClipboardDeleteSkill(BaseSkill):
    """Delete a clipboard entry."""

    @property
    def name(self) -> str:
        return "clipboard_delete"

    @property
    def description(self) -> str:
        return "Delete a clipboard entry."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Clipboard key to delete",
                },
                "scope": {
                    "type": "string",
                    "enum": ["agent", "project", "system"],
                    "description": "Scope of the entry (required)",
                },
            },
            "required": ["key", "scope"],
        }

    async def execute(
        self,
        key: str = "",
        scope: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        manager = self._services.get("clipboard_manager")
        if manager is None:
            return ToolResult(error="Clipboard service not available")

        try:
            clip_scope = ClipboardScope(scope)
        except ValueError:
            return ToolResult(error=f"Invalid scope: {scope}")

        try:
            deleted = manager.delete(key, clip_scope)
        except PermissionError as e:
            return ToolResult(error=str(e))

        if deleted:
            return ToolResult(output=f"Deleted clipboard '{key}' from {scope} scope")
        else:
            return ToolResult(error=f"Key '{key}' not found in {scope} scope")


class ClipboardClearSkill(BaseSkill):
    """Clear all entries in a clipboard scope."""

    @property
    def name(self) -> str:
        return "clipboard_clear"

    @property
    def description(self) -> str:
        return "Clear all entries in a clipboard scope. Requires confirm=True."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["agent", "project", "system"],
                    "description": "Scope to clear (required)",
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Must be true to proceed",
                },
            },
            "required": ["scope", "confirm"],
        }

    async def execute(
        self,
        scope: str = "",
        confirm: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        if not confirm:
            return ToolResult(error="Must set confirm=True to clear clipboard")

        manager = self._services.get("clipboard_manager")
        if manager is None:
            return ToolResult(error="Clipboard service not available")

        try:
            clip_scope = ClipboardScope(scope)
        except ValueError:
            return ToolResult(error=f"Invalid scope: {scope}")

        try:
            count = manager.clear(clip_scope)
        except PermissionError as e:
            return ToolResult(error=str(e))

        return ToolResult(output=f"Cleared {count} entries from {scope} clipboard")


# Factories
clipboard_list_factory = base_skill_factory(ClipboardListSkill)
clipboard_get_factory = base_skill_factory(ClipboardGetSkill)
clipboard_update_factory = base_skill_factory(ClipboardUpdateSkill)
clipboard_delete_factory = base_skill_factory(ClipboardDeleteSkill)
clipboard_clear_factory = base_skill_factory(ClipboardClearSkill)
```

---

### Phase 3: Registration

#### Update `nexus3/skill/builtin/registration.py`

Add the following imports and registrations:

```python
# Add imports at top of file
from nexus3.skill.builtin.clipboard_copy import copy_skill_factory, cut_skill_factory
from nexus3.skill.builtin.clipboard_paste import paste_skill_factory
from nexus3.skill.builtin.clipboard_manage import (
    clipboard_list_factory,
    clipboard_get_factory,
    clipboard_update_factory,
    clipboard_delete_factory,
    clipboard_clear_factory,
)

# Add registrations in register_builtin_skills():
def register_builtin_skills(registry: SkillRegistry) -> None:
    # ... existing registrations ...

    # Clipboard skills
    registry.register("copy", copy_skill_factory)
    registry.register("cut", cut_skill_factory)
    registry.register("paste", paste_skill_factory)
    registry.register("clipboard_list", clipboard_list_factory)
    registry.register("clipboard_get", clipboard_get_factory)
    registry.register("clipboard_update", clipboard_update_factory)
    registry.register("clipboard_delete", clipboard_delete_factory)
    registry.register("clipboard_clear", clipboard_clear_factory)
```

---

### Phase 4: Service Integration

#### Update `nexus3/skill/services.py`

Add typed accessor for clipboard manager:

```python
# Add import
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nexus3.clipboard import ClipboardManager

# Add method to ServiceContainer class
def get_clipboard_manager(self) -> ClipboardManager | None:
    """Get the clipboard manager for this agent."""
    return self._services.get("clipboard_manager")
```

#### Update Agent Pool initialization

In `nexus3/rpc/pool.py` (in `create_agent()` method), register the clipboard manager after ServiceContainer is created:

```python
# During agent setup, after ServiceContainer is created:
from nexus3.clipboard import ClipboardManager, CLIPBOARD_PRESETS
from nexus3.core.permissions import PermissionLevel

# Map permission level to clipboard permissions
# AgentPermissions doesn't have a base_preset attribute - use the PermissionLevel enum
permission_level = permissions.effective_policy.level
if permission_level == PermissionLevel.YOLO:
    clipboard_perms = CLIPBOARD_PRESETS["yolo"]
elif permission_level == PermissionLevel.TRUSTED:
    clipboard_perms = CLIPBOARD_PRESETS["trusted"]
else:  # SANDBOXED or unknown - use sandboxed (fail-safe)
    clipboard_perms = CLIPBOARD_PRESETS["sandboxed"]

# Create and register clipboard manager
clipboard_manager = ClipboardManager(
    agent_id=agent_id,
    cwd=agent_cwd,  # Use agent_cwd from the pool context
    permissions=clipboard_perms,
)
services.register("clipboard_manager", clipboard_manager)
```

**Location in pool.py:** Add after `services.register("cwd", agent_cwd)` and before skill registry setup.

---

### Phase 5: Context Injection Integration

#### Update `nexus3/context/loader.py`

Add clipboard injection to the context loading process:

```python
# Add import
from nexus3.clipboard import format_clipboard_context

# In ContextLoader or wherever system prompt is assembled:
def build_system_prompt(
    self,
    clipboard_manager: ClipboardManager | None = None,
    # ... other params
) -> str:
    parts = []

    # ... existing system prompt assembly ...

    # Add clipboard context if available and has entries
    if clipboard_manager is not None:
        clipboard_section = format_clipboard_context(
            clipboard_manager,
            max_entries=10,
            show_source=True,
        )
        if clipboard_section:
            parts.append(clipboard_section)

    return "\n\n".join(parts)
```

---

### Phase 6: Config Schema

#### Update `nexus3/config/schema.py`

```python
# Add new config class
class ClipboardConfig(BaseModel):
    """Configuration for clipboard system."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=True,
        description="Enable clipboard tools",
    )
    inject_into_context: bool = Field(
        default=True,
        description="Auto-inject clipboard index into system prompt",
    )
    max_injected_entries: int = Field(
        default=10,
        ge=0,
        le=50,
        description="Maximum entries to show in context injection",
    )
    show_source_in_injection: bool = Field(
        default=True,
        description="Show source path/lines in context injection",
    )
    max_entry_bytes: int = Field(
        default=1 * 1024 * 1024,  # 1 MB
        ge=1024,
        le=10 * 1024 * 1024,
        description="Maximum size of a single clipboard entry",
    )
    warn_entry_bytes: int = Field(
        default=100 * 1024,  # 100 KB
        ge=1024,
        description="Size threshold for warning on large entries",
    )


# Add to root Config class
class Config(BaseModel):
    # ... existing fields ...

    clipboard: ClipboardConfig = Field(
        default_factory=ClipboardConfig,
        description="Clipboard system configuration",
    )
```

---

## Files to Create/Modify Summary

| File | Change | LOC Est. |
|------|--------|----------|
| `nexus3/clipboard/__init__.py` | **New** - Public API exports | ~30 |
| `nexus3/clipboard/types.py` | **New** - Types, enums, dataclasses | ~150 |
| `nexus3/clipboard/storage.py` | **New** - SQLite operations | ~180 |
| `nexus3/clipboard/manager.py` | **New** - ClipboardManager | ~280 |
| `nexus3/clipboard/injection.py` | **New** - Context formatting | ~120 |
| `nexus3/skill/builtin/clipboard_copy.py` | **New** - copy/cut skills | ~200 |
| `nexus3/skill/builtin/clipboard_paste.py` | **New** - paste skill | ~220 |
| `nexus3/skill/builtin/clipboard_manage.py` | **New** - list/get/update/delete/clear | ~300 |
| `nexus3/skill/builtin/registration.py` | Add imports + registrations | ~15 |
| `nexus3/skill/services.py` | Add `get_clipboard_manager()` | ~5 |
| `nexus3/config/schema.py` | Add `ClipboardConfig` | ~40 |
| `nexus3/context/loader.py` | Integrate clipboard injection | ~15 |
| `nexus3/session/session.py` (or similar) | Register ClipboardManager | ~15 |
| **Tests** | | |
| `tests/unit/clipboard/test_types.py` | **New** | ~80 |
| `tests/unit/clipboard/test_storage.py` | **New** | ~150 |
| `tests/unit/clipboard/test_manager.py` | **New** | ~200 |
| `tests/unit/skill/test_clipboard_copy.py` | **New** | ~150 |
| `tests/unit/skill/test_clipboard_paste.py` | **New** | ~200 |
| `tests/unit/skill/test_clipboard_manage.py` | **New** | ~150 |
| `tests/integration/test_clipboard.py` | **New** | ~200 |

**Total new code**: ~2,500 LOC (including tests)

---

## Verification

### Unit Tests

**test_types.py:**
- `test_clipboard_entry_from_content` - line/byte counting
- `test_clipboard_permissions_can_read` - permission checks
- `test_clipboard_permissions_can_write` - permission checks
- `test_clipboard_presets` - preset configurations

**test_storage.py:**
- `test_create_entry` - basic insert
- `test_key_uniqueness` - duplicate key fails
- `test_get_nonexistent` - returns None
- `test_update_entry` - modify existing
- `test_update_rename` - change key
- `test_delete_entry` - remove entry
- `test_clear` - remove all entries
- `test_list_all_ordering` - sorted by modified_at desc

**test_manager.py:**
- `test_scope_resolution` - agent→project→system search
- `test_permission_enforcement` - sandboxed can't access project
- `test_modified_by_tracking` - agent ID recorded
- `test_size_validation_warning` - warning at threshold
- `test_size_validation_error` - error at limit
- `test_agent_scope_in_memory` - no db file for agent scope

**test_clipboard_copy.py:**
- `test_copy_whole_file`
- `test_copy_line_range`
- `test_copy_key_exists_error`
- `test_copy_invalid_scope`
- `test_cut_removes_source_lines`
- `test_cut_whole_file_empties`

**test_clipboard_paste.py:**
- `test_paste_after_line`
- `test_paste_before_line`
- `test_paste_replace_lines`
- `test_paste_at_marker_replace`
- `test_paste_at_marker_after`
- `test_paste_at_marker_before`
- `test_paste_append`
- `test_paste_prepend`
- `test_paste_scope_resolution`
- `test_paste_multiple_modes_error`
- `test_paste_no_mode_error`
- `test_paste_marker_not_found`
- `test_paste_marker_ambiguous`

**test_clipboard_manage.py:**
- `test_list_empty`
- `test_list_with_entries`
- `test_list_verbose`
- `test_get_content`
- `test_get_line_range`
- `test_update_content`
- `test_update_rename`
- `test_delete_success`
- `test_delete_not_found`
- `test_clear_requires_confirm`

### Integration Tests

- `test_copy_paste_roundtrip` - copy from A, paste to B, verify content
- `test_cut_paste_roundtrip` - cut from A, paste to B, verify source modified
- `test_cross_agent_project_scope` - agent A copies to project, agent B pastes
- `test_context_injection` - clipboard index appears in system prompt
- `test_permission_boundaries` - sandboxed agent can't access project
- `test_persistence` - project/system entries survive manager recreation

### Live Testing

```bash
nexus3 --fresh

# Test basic copy/paste
> Create a test file with 20 lines of code
> Copy lines 5-15 to clipboard as "chunk"
> Create another file and paste "chunk" after line 3
> Verify the content matches

# Test scope persistence
> Copy something to project scope: copy(source="...", key="shared", scope="project")
> Exit and restart NEXUS3
> clipboard_list(scope="project")  # Should still be there

# Test cross-agent
> /agent worker
> clipboard_list()  # Should only see agent scope (sandboxed)
> /agent main
> Copy to project scope
> /agent worker --trusted
> clipboard_list()  # Should see project scope now
```

---

## Design Decisions

### Resolved

1. **Key collision handling**: Error with suggestion to use `clipboard_update` or choose new key
2. **Marker mode**: Configurable via `marker_mode` parameter ("replace", "after", "before")
3. **Short description**: Dedicated `short_description` column for user-controlled preview
4. **Cross-agent sharing**: Allowed within same scope if agent has permission
5. **Modification tracking**: `modified_at` + `modified_by_agent` fields
6. **Agent scope storage**: In-memory dict (session-only, dies with agent)
7. **Permission granularity**: Separate read/write permissions per scope
8. **Trusted system scope**: Read-only by default (can paste, can't pollute)

### Implementation Notes

1. **FileSkill for copy/cut/paste**: These need path validation, so they inherit FileSkill
2. **BaseSkill for management**: clipboard_list/get/update/delete/clear don't do file I/O, so BaseSkill
3. **Lazy storage initialization**: Project/system storage only opened when accessed
4. **Clipboard manager in ServiceContainer**: Registered during agent creation, accessible to all skills

---

## Dependencies

- Independent of EDIT-PATCH-PLAN.md
- Uses existing patterns from:
  - `nexus3/skill/base.py` - FileSkill, BaseSkill, factory decorators
  - `nexus3/skill/services.py` - ServiceContainer pattern
  - `nexus3/session/storage.py` - SQLite patterns
  - `nexus3/config/schema.py` - Pydantic config patterns
- No new external dependencies (uses stdlib sqlite3)

---

## Future Enhancements (Out of Scope)

- **Clipboard history**: Track previous versions of entries
- **Expiry/TTL**: Auto-delete old entries
- **Tags**: Categorize entries beyond scope
- **Search**: Find entries by content substring
- **Import/export**: Dump clipboard to file, load from file
- **Binary support**: Images, compiled files, etc.
- **Agent scope persistence**: Save to session JSON for resume

---

## Codebase Validation Notes

*Validated against NEXUS3 codebase on 2026-01-23*

### Confirmed Patterns

| Aspect | Status | Notes |
|--------|--------|-------|
| FileSkill / BaseSkill | ✓ Correct | Uses `@property` for name/description/parameters |
| Factory decorators | ✓ Correct | `file_skill_factory`, `base_skill_factory` exist in base.py |
| ServiceContainer | ✓ Correct | Uses `.get()` for optional services, `.register()` to add |
| ToolResult | ✓ Correct | Constructed with `output=` or `error=` kwargs |
| Config schema | ✓ Correct | Uses Pydantic BaseModel with Field() |
| Skill registration | ✓ Correct | Uses `registry.register(name, factory)` pattern |
| Permission levels | ✓ Correct | YOLO, TRUSTED, SANDBOXED exist |

### Corrections Applied

1. **Removed "worker" preset** - Only `yolo`, `trusted`, `sandboxed` are first-class presets. "worker" is legacy and maps to sandboxed internally.

2. **Fixed initialization location** - Changed from `session/session.py` to `rpc/pool.py` in `create_agent()` method.

3. **Fixed permission mapping** - Changed from `agent_permissions.base_preset` (doesn't exist) to `permissions.effective_policy.level` (PermissionLevel enum).

---

## Implementation Checklist

Use this checklist to track implementation progress. Each item can be assigned to a task agent.

### Phase 1: Core Infrastructure

- [ ] **P1.1** Create `nexus3/clipboard/` directory
- [ ] **P1.2** Implement `nexus3/clipboard/types.py` (ClipboardEntry, ClipboardScope, ClipboardPermissions, CLIPBOARD_PRESETS)
- [ ] **P1.3** Implement `nexus3/clipboard/storage.py` (ClipboardStorage SQLite operations)
- [ ] **P1.4** Implement `nexus3/clipboard/manager.py` (ClipboardManager with all CRUD operations)
- [ ] **P1.5** Implement `nexus3/clipboard/injection.py` (format_clipboard_context, format_entry_detail)
- [ ] **P1.6** Implement `nexus3/clipboard/__init__.py` (public API exports)
- [ ] **P1.7** Add unit tests for types.py (ClipboardEntry.from_content, permission checks)
- [ ] **P1.8** Add unit tests for storage.py (CRUD operations, key uniqueness)
- [ ] **P1.9** Add unit tests for manager.py (scope resolution, permission enforcement)

### Phase 2: Core Skills

- [ ] **P2.1** Implement `nexus3/skill/builtin/clipboard_copy.py` (CopySkill, CutSkill)
- [ ] **P2.2** Implement `nexus3/skill/builtin/clipboard_paste.py` (PasteSkill)
- [ ] **P2.3** Add unit tests for copy/cut skills
- [ ] **P2.4** Add unit tests for paste skill (all insertion modes)

### Phase 3: Management Skills

- [ ] **P3.1** Implement `nexus3/skill/builtin/clipboard_manage.py` (clipboard_list, clipboard_get, clipboard_update, clipboard_delete, clipboard_clear)
- [ ] **P3.2** Add unit tests for management skills
- [ ] **P3.3** Register all clipboard skills in `nexus3/skill/builtin/registration.py`

### Phase 4: Service Integration

- [ ] **P4.1** Add `get_clipboard_manager()` to `nexus3/skill/services.py`
- [ ] **P4.2** Add ClipboardManager registration to `nexus3/rpc/pool.py` in `create_agent()`
- [ ] **P4.3** Add cleanup logic for ClipboardManager in agent destruction

### Phase 5: Context Injection

- [ ] **P5.1** Integrate `format_clipboard_context()` with system prompt assembly
- [ ] **P5.2** Add `ClipboardConfig` to `nexus3/config/schema.py`
- [ ] **P5.3** Wire config options (inject_into_context, max_injected_entries) into injection

### Phase 6: Integration Testing

- [ ] **P6.1** Integration test: copy/paste roundtrip (copy from A, paste to B)
- [ ] **P6.2** Integration test: cut/paste roundtrip (verify source modified)
- [ ] **P6.3** Integration test: cross-agent project scope sharing
- [ ] **P6.4** Integration test: context injection appears in system prompt
- [ ] **P6.5** Integration test: permission boundaries (sandboxed can't access project)
- [ ] **P6.6** Integration test: persistence (project/system entries survive restart)

### Final Integration

- [ ] **F1** Live test with real NEXUS3 REPL (create test files, copy/paste flow)
- [ ] **F2** Update CLAUDE.md with clipboard skills documentation
- [ ] **F3** Add clipboard section to skill/ README
- [ ] **F4** Verify no regressions in existing skills

---

## Quick Reference: File Locations

| Component | File Path |
|-----------|-----------|
| Types & dataclasses | `nexus3/clipboard/types.py` |
| SQLite storage | `nexus3/clipboard/storage.py` |
| Manager (main logic) | `nexus3/clipboard/manager.py` |
| Context injection | `nexus3/clipboard/injection.py` |
| Public API exports | `nexus3/clipboard/__init__.py` |
| Copy/cut skills | `nexus3/skill/builtin/clipboard_copy.py` |
| Paste skill | `nexus3/skill/builtin/clipboard_paste.py` |
| Management skills | `nexus3/skill/builtin/clipboard_manage.py` |
| Skill registration | `nexus3/skill/builtin/registration.py` |
| Service accessor | `nexus3/skill/services.py` |
| Agent creation | `nexus3/rpc/pool.py` |
| Config schema | `nexus3/config/schema.py` |
| Unit tests | `tests/unit/clipboard/` |
| Integration tests | `tests/integration/test_clipboard.py` |

---

## Database Schema Reference

**Clipboard table (in clipboard.db):**

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| key | TEXT NOT NULL UNIQUE | Clipboard key (indexed) |
| content | TEXT NOT NULL | Full content |
| short_description | TEXT | User-provided description |
| source_path | TEXT | Original file path |
| source_lines | TEXT | Line range (e.g., "50-150") |
| line_count | INTEGER NOT NULL | Number of lines |
| byte_count | INTEGER NOT NULL | Size in bytes |
| created_at | REAL NOT NULL | Unix timestamp |
| modified_at | REAL NOT NULL | Unix timestamp |
| created_by_agent | TEXT | Agent ID that created |
| modified_by_agent | TEXT | Agent ID that modified |

**Metadata table:**

| Column | Type | Description |
|--------|------|-------------|
| key | TEXT PRIMARY KEY | Metadata key |
| value | TEXT | Metadata value |

Schema version is stored as `schema_version` → `"1"` in metadata table.
