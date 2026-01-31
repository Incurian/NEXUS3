# Plan: Clipboard System - Scoped Copy/Paste for Agents

## Overview

A clipboard system that lets agents move large text chunks without passing content through LLM context twice. Content is stored server-side in SQLite databases with three scope levels (system, project, agent), and clipboard metadata is auto-injected into context for discoverability.

**Core benefit**: Moving 100 lines from file A to file B currently costs ~200 lines of context (read + write). With clipboard tools, it costs ~2 tool calls with minimal token overhead.

**Estimated effort**: ~20-26 hours total
- Phase 1 (Infrastructure + Tags + TTL schema): 5-6 hours
- Phase 2 (Core Skills + tags/ttl params): 3-4 hours
- Phase 3 (Management + Search + Tags + Import/Export): 4-5 hours
- Phase 4 (Service Integration): 1-2 hours
- Phase 5 (Context Injection): 1-2 hours
- Phase 5b (TTL/Expiry Tracking): 1-2 hours
- Phase 6 (Session Persistence): 2-3 hours
- Phases 7-9 (Testing + Docs): 3-4 hours

---

## Architecture

### Storage Locations

| Scope | Database Path | Lifetime | Visibility |
|-------|---------------|----------|------------|
| `system` | `~/.nexus3/clipboard.db` | Persistent | All agents (permission-gated) |
| `project` | `.nexus3/clipboard.db` | Persistent | Agents in this project (permission-gated) |
| `agent` | In-memory dict | Session only | Single agent |

### Module Structure

```
nexus3/clipboard/
├── __init__.py          # Public API exports
├── types.py             # ClipboardEntry, ClipboardScope, ClipboardTag, InsertionMode
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
    PROJECT = "project"  # <agent_cwd>/.nexus3/clipboard.db
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
class ClipboardTag:
    """A tag for organizing clipboard entries."""
    id: int
    name: str
    description: str | None = None
    created_at: float = 0.0


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
    expires_at: float | None = None      # Unix timestamp for TTL expiry (None = permanent)
    ttl_seconds: int | None = None       # TTL in seconds (informational)
    tags: list[str] = field(default_factory=list)  # Tag names

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
        ttl_seconds: int | None = None,
        tags: list[str] | None = None,
    ) -> ClipboardEntry:
        """Create entry from content, computing line/byte counts."""
        import time
        now = time.time()
        expires_at = now + ttl_seconds if ttl_seconds is not None else None
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
            expires_at=expires_at,
            ttl_seconds=ttl_seconds,
            tags=tags or [],
        )

    @property
    def is_expired(self) -> bool:
        """Check if this entry has expired (TTL exceeded)."""
        if self.expires_at is None:
            return False
        import time
        return time.time() >= self.expires_at


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
# Note: This plan assumes the permission presets are `yolo`, `trusted`, and `sandboxed`.
# If legacy preset names exist (e.g. "worker"), treat them as aliases for sandboxed for clipboard purposes.


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
    expires_at REAL,
    ttl_seconds INTEGER,
    UNIQUE(key)
);

CREATE INDEX IF NOT EXISTS idx_clipboard_key ON clipboard(key);
CREATE INDEX IF NOT EXISTS idx_clipboard_expires ON clipboard(expires_at) WHERE expires_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name);

CREATE TABLE IF NOT EXISTS clipboard_tags (
    clipboard_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (clipboard_id, tag_id),
    FOREIGN KEY (clipboard_id) REFERENCES clipboard(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_clipboard_tags_tag ON clipboard_tags(tag_id);

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
        import os

        from nexus3.core.secure_io import SECURE_FILE_MODE, secure_mkdir

        # Create parent directory with secure permissions
        secure_mkdir(self._db_path.parent)

        # TOCTOU protection: atomically create DB file with secure permissions
        # (matches pattern from nexus3/session/storage.py)
        if not self._db_path.exists():
            fd = os.open(
                str(self._db_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                SECURE_FILE_MODE,  # 0o600 rw------- (user only)
            )
            os.close(fd)

        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # Enable foreign keys (required for ON DELETE CASCADE in clipboard_tags)
        self._conn.execute("PRAGMA foreign_keys = ON")
        # WAL is fine here; session storage does not use WAL, but clipboard can.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA_SQL)

        # Optional hardening (mirrors session/storage.py): ensure DB file perms are correct
        # os.chmod(self._db_path, 0o600)

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
        key = row["key"]
        return ClipboardEntry(
            key=key,
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
            expires_at=row["expires_at"],
            ttl_seconds=row["ttl_seconds"],
            tags=self.get_tags(key),
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
                created_by_agent, modified_by_agent, expires_at, ttl_seconds)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.key, entry.content, entry.short_description,
                entry.source_path, entry.source_lines,
                entry.line_count, entry.byte_count,
                entry.created_at, entry.modified_at,
                entry.created_by_agent, entry.modified_by_agent,
                entry.expires_at, entry.ttl_seconds,
            )
        )
        self._conn.commit()

        # Set tags if provided
        if entry.tags:
            self.set_tags(entry.key, entry.tags)

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
        ttl_seconds: int | None = None,
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

        if ttl_seconds is not None:
            updates.extend(["ttl_seconds = ?", "expires_at = ?"])
            params.extend([ttl_seconds, time.time() + ttl_seconds])

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

    def count_expired(self, now: float) -> int:
        """Count entries where expires_at <= now. Does NOT delete them.

        Note: Actual cleanup requires user confirmation - see Future Work.
        """
        assert self._conn is not None
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM clipboard WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (now,)
        )
        return cur.fetchone()[0]

    def get_expired(self, now: float) -> list[ClipboardEntry]:
        """Get all expired entries for review before cleanup."""
        assert self._conn is not None
        cur = self._conn.execute(
            "SELECT * FROM clipboard WHERE expires_at IS NOT NULL AND expires_at <= ? ORDER BY expires_at",
            (now,)
        )
        return [self._row_to_entry(row) for row in cur.fetchall()]

    def set_tags(self, key: str, tags: list[str]) -> None:
        """Set tags for an entry (replaces existing tags)."""
        assert self._conn is not None

        # Get clipboard entry ID
        cur = self._conn.execute("SELECT id FROM clipboard WHERE key = ?", (key,))
        row = cur.fetchone()
        if row is None:
            raise KeyError(f"Key '{key}' not found")
        clipboard_id = row["id"]

        # Remove existing tags for this entry
        self._conn.execute("DELETE FROM clipboard_tags WHERE clipboard_id = ?", (clipboard_id,))

        # Add new tags (creating tags if needed)
        for tag_name in tags:
            # Ensure tag exists
            self._conn.execute(
                "INSERT OR IGNORE INTO tags (name, created_at) VALUES (?, ?)",
                (tag_name, time.time())
            )
            # Get tag ID
            cur = self._conn.execute("SELECT id FROM tags WHERE name = ?", (tag_name,))
            tag_id = cur.fetchone()["id"]
            # Link to clipboard entry
            self._conn.execute(
                "INSERT INTO clipboard_tags (clipboard_id, tag_id) VALUES (?, ?)",
                (clipboard_id, tag_id)
            )

        self._conn.commit()

    def get_tags(self, key: str) -> list[str]:
        """Get tags for an entry."""
        assert self._conn is not None
        cur = self._conn.execute(
            """SELECT t.name FROM tags t
               JOIN clipboard_tags ct ON ct.tag_id = t.id
               JOIN clipboard c ON c.id = ct.clipboard_id
               WHERE c.key = ?
               ORDER BY t.name""",
            (key,)
        )
        return [row["name"] for row in cur.fetchall()]

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
        # NOTE: For system-scope clipboard paths, prefer nexus3.core.constants.get_nexus_dir()
        # rather than hardcoding Path.home() / ".nexus3". Home override remains useful for tests.
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
        tags: list[str] | None = None,
        ttl_seconds: int | None = None,
    ) -> tuple[ClipboardEntry, str | None]:
        """Copy content to clipboard.

        Args:
            key: Clipboard key name
            content: Content to store
            scope: Clipboard scope (agent/project/system)
            short_description: Optional description
            source_path: Original file path
            source_lines: Line range (e.g., "50-150")
            tags: Optional tags for organizing entries
            ttl_seconds: Optional TTL in seconds (None = permanent)

        Returns:
            Tuple of (created entry, warning message or None)

        Raises:
            PermissionError: If scope not accessible
            ValueError: If key already exists or content too large
        """
        self._check_write_permission(scope)
        warning = self._validate_size(content)

        # Apply scope-specific default TTL if not specified
        if ttl_seconds is None:
            ttl_seconds = self._get_ttl_for_scope(scope)

        entry = ClipboardEntry.from_content(
            key=key,
            scope=scope,
            content=content,
            short_description=short_description,
            source_path=source_path,
            source_lines=source_lines,
            agent_id=self._agent_id,
            ttl_seconds=ttl_seconds,
            tags=tags,
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
        ttl_seconds: int | None = None,
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
            if ttl_seconds is not None:
                entry.ttl_seconds = ttl_seconds
                entry.expires_at = time.time() + ttl_seconds
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
                ttl_seconds=ttl_seconds,
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
                ttl_seconds=ttl_seconds,
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

    # --- TTL Support ---

    def _get_ttl_for_scope(self, scope: ClipboardScope) -> int | None:
        """Get default TTL for scope from config, or None for permanent."""
        # In implementation, this reads from ClipboardConfig
        # For now, return None (permanent) - will be wired in Phase 5b
        return None

    def count_expired(self, scope: ClipboardScope | None = None) -> int:
        """Count expired entries (does NOT delete them).

        Args:
            scope: Specific scope to check, or None for all accessible scopes

        Returns count of expired entries. Use get_expired() to see them,
        or a future cleanup command with user confirmation to delete.
        """
        import time
        now = time.time()
        count = 0

        scopes = [scope] if scope else [ClipboardScope.AGENT, ClipboardScope.PROJECT, ClipboardScope.SYSTEM]

        for s in scopes:
            if not self._permissions.can_read(s):
                continue

            if s == ClipboardScope.AGENT:
                count += sum(
                    1 for e in self._agent_clipboard.values()
                    if e.expires_at is not None and e.expires_at <= now
                )
            elif s == ClipboardScope.PROJECT:
                count += self._get_project_storage().count_expired(now)
            elif s == ClipboardScope.SYSTEM:
                count += self._get_system_storage().count_expired(now)

        return count

    def get_expired(self, scope: ClipboardScope | None = None) -> list[ClipboardEntry]:
        """Get all expired entries for review.

        Args:
            scope: Specific scope to check, or None for all accessible scopes

        Returns list of expired entries. User can review before cleanup.
        """
        import time
        now = time.time()
        expired: list[ClipboardEntry] = []

        scopes = [scope] if scope else [ClipboardScope.AGENT, ClipboardScope.PROJECT, ClipboardScope.SYSTEM]

        for s in scopes:
            if not self._permissions.can_read(s):
                continue

            if s == ClipboardScope.AGENT:
                expired.extend(
                    e for e in self._agent_clipboard.values()
                    if e.expires_at is not None and e.expires_at <= now
                )
            elif s == ClipboardScope.PROJECT:
                expired.extend(self._get_project_storage().get_expired(now))
            elif s == ClipboardScope.SYSTEM:
                expired.extend(self._get_system_storage().get_expired(now))

        return expired

    # --- Search Support ---

    def search(
        self,
        query: str,
        scope: ClipboardScope | None = None,
        search_content: bool = True,
        search_keys: bool = True,
        search_descriptions: bool = True,
        tags: list[str] | None = None,
    ) -> list[ClipboardEntry]:
        """Search clipboard entries.

        Args:
            query: Search string (case-insensitive substring match)
            scope: Specific scope to search, or None for all accessible
            search_content: Search in content
            search_keys: Search in keys
            search_descriptions: Search in descriptions
            tags: Filter by tags (entries must have ALL specified tags)

        Returns:
            Matching entries, sorted by relevance (key match > desc > content)
        """
        entries = self.list_entries(scope)  # Already filters by permission
        query_lower = query.lower()
        results = []

        for entry in entries:
            # Filter by tags first (if specified)
            if tags:
                if not all(t in entry.tags for t in tags):
                    continue

            # Search in specified fields
            matches = False
            if search_keys and query_lower in entry.key.lower():
                matches = True
            elif search_descriptions and entry.short_description and query_lower in entry.short_description.lower():
                matches = True
            elif search_content and query_lower in entry.content.lower():
                matches = True

            if matches:
                results.append(entry)

        return results

    # --- Tag Management ---

    def add_tags(self, key: str, scope: ClipboardScope, tags: list[str]) -> ClipboardEntry:
        """Add tags to an entry. Creates tags if they don't exist."""
        self._check_write_permission(scope)
        entry = self._get_from_scope(key, scope)
        if entry is None:
            raise KeyError(f"Key '{key}' not found in {scope.value} scope")

        # Add new tags (avoid duplicates)
        new_tags = list(set(entry.tags + tags))
        entry.tags = new_tags
        entry.modified_at = time.time()
        entry.modified_by_agent = self._agent_id

        # Persist if not agent scope
        if scope != ClipboardScope.AGENT:
            storage = self._get_project_storage() if scope == ClipboardScope.PROJECT else self._get_system_storage()
            storage.set_tags(key, new_tags)

        return entry

    def remove_tags(self, key: str, scope: ClipboardScope, tags: list[str]) -> ClipboardEntry:
        """Remove tags from an entry."""
        self._check_write_permission(scope)
        entry = self._get_from_scope(key, scope)
        if entry is None:
            raise KeyError(f"Key '{key}' not found in {scope.value} scope")

        # Remove specified tags
        entry.tags = [t for t in entry.tags if t not in tags]
        entry.modified_at = time.time()
        entry.modified_by_agent = self._agent_id

        # Persist if not agent scope
        if scope != ClipboardScope.AGENT:
            storage = self._get_project_storage() if scope == ClipboardScope.PROJECT else self._get_system_storage()
            storage.set_tags(key, entry.tags)

        return entry

    def list_tags(self, scope: ClipboardScope | None = None) -> list[str]:
        """List all tags in use across accessible scopes."""
        entries = self.list_entries(scope)
        all_tags = set()
        for entry in entries:
            all_tags.update(entry.tags)
        return sorted(all_tags)
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
    ClipboardTag,
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
    "ClipboardTag",
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

Implementation note (matches current NEXUS3 patterns):
- Consider using `@handle_file_errors` from `nexus3.skill.base` to convert `PathSecurityError`/`ValueError` into `ToolResult` automatically.
- Continue using `asyncio.to_thread(...)` for file I/O, as in other file tools.

```python
"""Copy and cut skills for clipboard operations."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nexus3.clipboard import ClipboardManager, ClipboardScope
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory, handle_file_errors

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
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags for organizing entries (e.g., ['refactor', 'cleanup'])",
                },
                "ttl_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Optional TTL in seconds. Entry auto-expires after this time. Omit for permanent.",
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
        tags: list[str] | None = None,
        ttl_seconds: int | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        # Validate source path (NEXUS3 pattern: try/except, not isinstance)
        try:
            source_path = self._validate_path(source)
        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))

        # Read file content (async file I/O via to_thread)
        try:
            content = await asyncio.to_thread(
                source_path.read_text, encoding="utf-8", errors="replace"
            )
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
                tags=tags,
                ttl_seconds=ttl_seconds,
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
        try:
            source_path = self._validate_path(source)
        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))

        # Re-read to ensure we have current content (async file I/O)
        try:
            content = await asyncio.to_thread(
                source_path.read_text, encoding="utf-8", errors="replace"
            )
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
            await asyncio.to_thread(
                source_path.write_text, new_content, encoding="utf-8"
            )
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

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nexus3.clipboard import ClipboardManager, ClipboardScope, InsertionMode
from nexus3.core.errors import PathSecurityError
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
        # Validate target path (NEXUS3 pattern: try/except)
        try:
            target_path = self._validate_path(target)
        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))

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
                file_content = await asyncio.to_thread(
                    target_path.read_text, encoding="utf-8", errors="replace"
                )
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

        # Write result (async file I/O)
        try:
            await asyncio.to_thread(
                target_path.parent.mkdir, parents=True, exist_ok=True
            )
            await asyncio.to_thread(
                target_path.write_text, new_content, encoding="utf-8"
            )
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
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter to entries having ALL of these tags (AND logic)",
                },
                "any_tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter to entries having ANY of these tags (OR logic)",
                },
            },
        }

    async def execute(
        self,
        scope: str | None = None,
        verbose: bool = False,
        tags: list[str] | None = None,
        any_tags: list[str] | None = None,
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

        # Apply tag filters
        if tags:
            entries = [e for e in entries if all(t in e.tags for t in tags)]
        if any_tags:
            entries = [e for e in entries if any(t in e.tags for t in any_tags)]

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
                "ttl_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Set new TTL in seconds. Entry expires after this time. Omit to keep current TTL.",
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
        ttl_seconds: int | None = None,
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
            import asyncio
            from pathlib import Path
            source_path = Path(source).expanduser().resolve()
            try:
                file_content = await asyncio.to_thread(
                    source_path.read_text, encoding="utf-8", errors="replace"
                )
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
from nexus3.skill.builtin.clipboard_search import clipboard_search_factory
from nexus3.skill.builtin.clipboard_tag import clipboard_tag_factory
from nexus3.skill.builtin.clipboard_export import clipboard_export_factory
from nexus3.skill.builtin.clipboard_import import clipboard_import_factory

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

    registry.register("clipboard_search", clipboard_search_factory)
    registry.register("clipboard_tag", clipboard_tag_factory)
    registry.register("clipboard_export", clipboard_export_factory)
    registry.register("clipboard_import", clipboard_import_factory)
```

---

### Phase 4: Service Integration

#### Update `nexus3/skill/services.py` (Optional)

**Optional:** Add a typed accessor for clipboard manager.

Note: In the current codebase, `ServiceContainer` already supports `.get()` and `.require()` and also has a section for typed accessors (see `nexus3/skill/services.py`). It is perfectly acceptable to just use:

```python
manager = self._services.get("clipboard_manager")
```

If you prefer type hints / discoverability, you may add:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nexus3.clipboard import ClipboardManager


def get_clipboard_manager(self) -> "ClipboardManager | None":
    return self.get("clipboard_manager")
```

#### Update Agent Pool initialization

In `nexus3/rpc/pool.py`, register the clipboard manager after `ServiceContainer` is created (in both `_create_unlocked()` and `_restore_unlocked()`).

```python
# During agent setup, after permissions + agent_cwd are resolved:
from nexus3.clipboard import ClipboardManager, CLIPBOARD_PRESETS
from nexus3.core.permissions import PermissionLevel

# Map AgentPermissions -> clipboard permissions
# (PermissionLevel is available as permissions.effective_policy.level)
permission_level = permissions.effective_policy.level
if permission_level == PermissionLevel.YOLO:
    clipboard_perms = CLIPBOARD_PRESETS["yolo"]
elif permission_level == PermissionLevel.TRUSTED:
    clipboard_perms = CLIPBOARD_PRESETS["trusted"]
else:  # SANDBOXED or unknown - fail safe
    clipboard_perms = CLIPBOARD_PRESETS["sandboxed"]

clipboard_manager = ClipboardManager(
    agent_id=agent_id,
    cwd=agent_cwd,
    permissions=clipboard_perms,
)
services.register("clipboard_manager", clipboard_manager)
```

**Note:** `AgentPermissions.base_preset` exists, but it reflects the named preset string (e.g. `"trusted"`). For gating clipboard scope access, `permissions.effective_policy.level` is the reliable source of truth.

**Location in pool.py:** Add after `services.register("cwd", agent_cwd)` and before skill registry setup.

#### Pass ClipboardManager to ContextManager

The same `ClipboardManager` instance must be passed to `ContextManager` so `build_messages()` can inject the clipboard index per-turn:
```python
# In pool.py, when creating ContextManager for the agent:
context = ContextManager(
    config=context_config,
    logger=logger,
    clipboard_manager=clipboard_manager,                 # Pass the same instance
    clipboard_config=self._shared.config.clipboard,      # NEW (root Config field)
)

# Do the same in _restore_unlocked() when constructing ContextManager.
```




#### Update `nexus3/context/manager.py`

Add clipboard injection to `build_messages()` for **per-turn** injection. This follows the same pattern as datetime injection - the clipboard index must be current every turn, not stale from session start.

**Why `build_messages()` and not `ContextLoader.load()`?**
- `ContextLoader.load()` runs once at agent creation (and on compaction)
- `build_messages()` runs every turn before API calls
- If clipboard injection happened at load time, an agent could `copy()` something and not see it in context until compaction
- Datetime uses this pattern: base prompt is cached, dynamic content injected per-turn

```python
# Add imports at top of manager.py
from typing import TYPE_CHECKING

from nexus3.clipboard import format_clipboard_context
from nexus3.config.schema import ClipboardConfig

if TYPE_CHECKING:
    from nexus3.clipboard import ClipboardManager


# Add agent_id, clipboard_manager and clipboard_config to ContextManager.__init__()
def __init__(
    self,
    config: ContextConfig | None = None,
    token_counter: TokenCounter | None = None,
    logger: "SessionLogger | None" = None,
    agent_id: str | None = None,                           # NEW - needed for clipboard scoping
    clipboard_manager: "ClipboardManager | None" = None,   # NEW
    clipboard_config: ClipboardConfig | None = None,       # NEW
) -> None:
    # ... existing init ...
    self._agent_id = agent_id                              # NEW
    self._clipboard_manager = clipboard_manager            # NEW
    self._clipboard_config = clipboard_config or ClipboardConfig()  # NEW


# In build_messages(), after datetime injection:
def build_messages(self) -> list[Message]:
    result: list[Message] = []

    if self._system_prompt:
        # Inject current date/time (existing code)
        datetime_line = get_current_datetime_str()
        prompt_with_time = inject_datetime_into_prompt(
            self._system_prompt, datetime_line
        )

        # NEW: Inject clipboard index if manager available and has entries
        if self._clipboard_manager is not None and self._clipboard_config.inject_into_context:
            clipboard_section = format_clipboard_context(
                self._clipboard_manager,
                max_entries=self._clipboard_config.max_injected_entries,
                show_source=self._clipboard_config.show_source_in_injection,
            )
            if clipboard_section:
                prompt_with_time += "\n\n" + clipboard_section

        result.append(Message(role=Role.SYSTEM, content=prompt_with_time))

    # ... rest of method unchanged ...
```

**Note:** The `ClipboardManager` reference is passed at `ContextManager` construction time, but the injection happens per-turn. The manager's state (entries) is read fresh each turn.

**Token Counting Consistency:** In the current codebase, truncation happens in `ContextManager._truncate_oldest_first()` and `ContextManager._truncate_middle_out()`.

Today both methods compute:

```python
system_tokens = self._counter.count(self._system_prompt)  # RAW (no datetime injection)
```

But `build_messages()` (and `get_token_usage()`) inject datetime first, so truncation undercounts. When clipboard injection is added, the mismatch gets worse.

**Fix:** centralize dynamic system-prompt construction in a helper (so `build_messages()`, `get_token_usage()`, and both truncation methods all use the same injected prompt):

```python
def _build_system_prompt_for_api_call(self) -> str:
    # Datetime injection (existing)
    datetime_line = get_current_datetime_str()
    prompt = inject_datetime_into_prompt(self._system_prompt, datetime_line)

    # Clipboard injection (NEW)
    if self._clipboard_manager is not None and self._clipboard_config.inject_into_context:
        clipboard_section = format_clipboard_context(
            self._clipboard_manager,
            max_entries=self._clipboard_config.max_injected_entries,
            show_source=self._clipboard_config.show_source_in_injection,
        )
        if clipboard_section:
            prompt += "\n\n" + clipboard_section

    return prompt
```

Then:
- `build_messages()` uses `prompt = self._build_system_prompt_for_api_call()` for the `Role.SYSTEM` message.
- `get_token_usage()` uses `system_tokens = self._counter.count(self._build_system_prompt_for_api_call())`.
- `_truncate_oldest_first()` and `_truncate_middle_out()` use `system_tokens = self._counter.count(self._build_system_prompt_for_api_call())`.

This ensures truncation decisions account for the full system prompt size actually sent to the model.


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

    # TTL settings
    default_ttl_seconds: int | None = Field(
        default=None,
        description="Default TTL for new entries (seconds). None = permanent.",
    )
    per_scope_ttl: dict[str, int | None] = Field(
        default={
            "agent": None,         # Agent scope: permanent (session-only anyway)
            "project": 2592000,    # Project scope: 30 days
            "system": 31536000,    # System scope: 365 days (1 year)
        },
        description="Per-scope TTL overrides (seconds). None = permanent.",
    )


# Add to root Config class (matches existing pattern at lines 569-574 of schema.py)
class Config(BaseModel):
    # ... existing fields ...

    clipboard: ClipboardConfig = ClipboardConfig()  # Direct instantiation pattern
```

---

### Additional Skills (Search, Tags, Import/Export)

#### `clipboard_search` Skill

Simple LIKE-based search across clipboard entries:

```python
class ClipboardSearchSkill(BaseSkill):
    """Search clipboard entries by content substring."""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search substring (case-insensitive)"},
                "scope": {"type": "string", "enum": ["agent", "project", "system"], "description": "Scope to search (omit for all)"},
                "max_results": {"type": "integer", "default": 50, "description": "Maximum results to return"},
            },
            "required": ["query"],
        }

    async def execute(self, query: str, scope: str | None = None, max_results: int = 50, **kwargs) -> ToolResult:
        manager = self._services.get("clipboard_manager")
        results = manager.search(query, scope=scope, limit=max_results)
        # Format results as list with key, scope, line count, description
        ...
```

Storage method uses SQLite LIKE with escaped wildcards:

```sql
SELECT * FROM clipboard
WHERE content LIKE ? ESCAPE '\\' OR short_description LIKE ? ESCAPE '\\'
ORDER BY modified_at DESC LIMIT ?
```

#### `clipboard_tag` Skill

Tag management with action-based dispatch (mirrors `gitlab_label` pattern):

```python
@property
def parameters(self) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "add", "remove", "create", "delete"]},
            "name": {"type": "string", "description": "Tag name"},
            "entry_key": {"type": "string", "description": "Clipboard entry key (for add/remove)"},
            "scope": {"type": "string", "enum": ["agent", "project", "system"], "description": "Entry scope (for add/remove)"},
            "description": {"type": "string", "description": "Tag description (for create)"},
        },
        "required": ["action"],
    }
```

Actions:
- `list`: List all tags (optionally filter by scope)
- `add`: Add tag to entry (`entry_key` + `scope` + `name` required)
- `remove`: Remove tag from entry
- `create`: Create a new tag with optional description
- `delete`: Delete a tag (removes from all entries via CASCADE)

#### `clipboard_export` / `clipboard_import` Skills

**Export:**

```python
async def execute(self, path: str, scope: str = "all", **kwargs) -> ToolResult:
    import asyncio

    entries = manager.list_entries(scope if scope != "all" else None)
    data = {
        "version": "1.0",
        "exported_at": datetime.now().isoformat(),
        "entries": [asdict(e) for e in entries],
    }
    json_content = json.dumps(data, indent=2)

    await asyncio.to_thread(Path(path).write_text, json_content)
    return ToolResult(output=f"Exported {len(entries)} entries to {path}")
```

**Import:**

```python
async def execute(
    self,
    path: str,
    scope: str = "agent",
    conflict: str = "skip",
    dry_run: bool = True,
    **kwargs,
) -> ToolResult:
    import asyncio

    file_content = await asyncio.to_thread(Path(path).read_text)
    data = json.loads(file_content)
    if data.get("version") != "1.0":
        return ToolResult(error="Unsupported export format version")

    imported, skipped = 0, 0
    for entry_dict in data["entries"]:
        if manager.get(entry_dict["key"], scope) and conflict == "skip":
            skipped += 1
            continue
        if not dry_run:
            manager.copy(key=entry_dict["key"], content=entry_dict["content"], scope=scope, ...)
        imported += 1

    if dry_run:
        return ToolResult(output=f"Would import {imported}, skip {skipped}. Run with dry_run=false to import.")
    return ToolResult(output=f"Imported {imported}, skipped {skipped}")
```

---

### Session Persistence Integration

Add `clipboard_agent_entries` to `SavedSession` for agent scope persistence across `--resume`:

```python
# In nexus3/session/persistence.py

@dataclass
class SavedSession:
    # ... existing fields ...
    clipboard_agent_entries: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            # ... existing fields ...
            "clipboard_agent_entries": self.clipboard_agent_entries,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SavedSession:
        return cls(
            # ... existing fields ...
            clipboard_agent_entries=data.get("clipboard_agent_entries", {}),
        )
```

Restoration in `pool.py`:

```python
# In _restore_unlocked(), after creating ClipboardManager:
if saved_session.clipboard_agent_entries:
    for key, entry_dict in saved_session.clipboard_agent_entries.items():
        clipboard_manager._agent_clipboard[key] = ClipboardEntry(**entry_dict)
```

---

## Files to Create/Modify Summary

| File | Change | LOC Est. |
|------|--------|----------|
| `nexus3/clipboard/__init__.py` | **New** - Public API exports | ~40 |
| `nexus3/clipboard/types.py` | **New** - Types, enums, dataclasses (incl. ClipboardTag) | ~180 |
| `nexus3/clipboard/storage.py` | **New** - SQLite operations (incl. tags, TTL, search) | ~280 |
| `nexus3/clipboard/manager.py` | **New** - ClipboardManager (incl. tags, TTL, search) | ~380 |
| `nexus3/clipboard/injection.py` | **New** - Context formatting | ~120 |
| `nexus3/skill/builtin/clipboard_copy.py` | **New** - copy/cut skills (with tags, ttl params) | ~220 |
| `nexus3/skill/builtin/clipboard_paste.py` | **New** - paste skill | ~220 |
| `nexus3/skill/builtin/clipboard_manage.py` | **New** - list/get/update/delete/clear (with tag filters) | ~350 |
| `nexus3/skill/builtin/clipboard_search.py` | **New** - search skill | ~60 |
| `nexus3/skill/builtin/clipboard_tag.py` | **New** - tag management skill | ~120 |
| `nexus3/skill/builtin/clipboard_export.py` | **New** - export to JSON | ~80 |
| `nexus3/skill/builtin/clipboard_import.py` | **New** - import from JSON | ~100 |
| `nexus3/skill/builtin/registration.py` | Add imports + registrations | ~25 |
| `nexus3/skill/services.py` | (Optional) add `get_clipboard_manager()` | ~5 |
| `nexus3/config/schema.py` | Add `ClipboardConfig` (incl. TTL options) | ~60 |
| `nexus3/context/manager.py` | Integrate clipboard injection in `build_messages()` | ~20 |
| `nexus3/session/persistence.py` | Add `clipboard_agent_entries` to SavedSession | ~40 |
| `nexus3/rpc/pool.py` | Register ClipboardManager, TTL expiry tracking, session restore | ~50 |
| **Tests** | | |
| `tests/unit/clipboard/test_types.py` | **New** | ~100 |
| `tests/unit/clipboard/test_storage.py` | **New** (incl. tags, TTL, search) | ~250 |
| `tests/unit/clipboard/test_manager.py` | **New** (incl. tags, TTL, search) | ~300 |
| `tests/unit/skill/test_clipboard_copy.py` | **New** | ~180 |
| `tests/unit/skill/test_clipboard_paste.py` | **New** | ~200 |
| `tests/unit/skill/test_clipboard_manage.py` | **New** | ~200 |
| `tests/unit/skill/test_clipboard_extras.py` | **New** - search, tag, import/export | ~200 |
| `tests/unit/test_clipboard_persistence.py` | **New** - SavedSession serialization of agent clipboard | ~120 |
| `tests/integration/test_clipboard.py` | **New** | ~300 |

**Total new code**: ~3,900 LOC (including tests)

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
> Create a sandboxed agent and verify it cannot see project scope entries
> clipboard_list()  # Should only show agent scope when SANDBOXED
>
> Create a trusted agent and verify it can see project scope entries
> clipboard_list(scope="project")  # Should show entries when TRUSTED allows project_read
>
> (Optional) Create a YOLO agent and verify system scope read/write if enabled by policy
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

- **User-in-the-loop TTL cleanup**: Currently TTL just flags entries as expired but doesn't auto-delete. Need to design a user confirmation flow for cleanup - options include: (1) REPL command `/clipboard cleanup` with confirmation, (2) Agent prompts user when expired entries accumulate, (3) Periodic summary in context injection showing expired count. **TODO: Design this before v2.**
- **Clipboard history**: Track previous versions of entries (separate `clipboard_history` table)
- **Binary support**: Images, compiled files (BLOB column + MIME types)
- **FTS5 search upgrade**: Full-text search for large clipboards (when LIKE becomes slow)

---

## Codebase Validation Notes

*Validated against NEXUS3 codebase on 2026-01-30, 2026-01-31 (three validation passes with explorer agents)*

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

2. **Fixed initialization location** - Changed from `session/session.py` to `rpc/pool.py` (ContextManager is constructed in `_create_unlocked()` / `_restore_unlocked()`).

3. **Fixed permission mapping** - Changed from `agent_permissions.base_preset` (doesn't exist) to `permissions.effective_policy.level` (PermissionLevel enum).

4. **Added tags and TTL to SCHEMA_SQL** - Added `expires_at`, `ttl_seconds` columns to clipboard table; added `tags` and `clipboard_tags` junction tables; added `PRAGMA foreign_keys = ON`.

5. **Added ClipboardTag dataclass** - Defined in types.py with id, name, description, created_at fields.

6. **Added expires_at/ttl_seconds to ClipboardEntry** - Entry now tracks expiration time and original TTL value, plus tags list.

7. **Added tags/ttl_seconds to CopySkill** - Both parameters added to skill with proper JSON Schema definitions.

8. **Fixed path validation pattern** - Prefer `@handle_file_errors` (or try/except) to convert PathSecurityError/ValueError into ToolResult (matches NEXUS3 pattern).

9. **Added async file I/O** - Used `asyncio.to_thread()` for file read operations.

10. **Wired ClipboardConfig into injection** - Removed hardcoded values, now uses `self._clipboard_config.max_injected_entries` etc.

11. **Added token counting fix note** - Documented that truncation methods must account for injected content.

12. **Added TYPE_CHECKING import pattern** - ContextManager uses TYPE_CHECKING for ClipboardManager to avoid circular imports.

13. **Fixed duplicate `field` import** - Removed duplicate import in types.py.

14. **Fixed checklist method names** - Changed `add_tag`/`remove_tag` to `add_tags`/`remove_tags` (plural) to match implementation.

15. **Fixed config patterns** - Changed `Field(default_factory=...)` to direct instantiation for ClipboardConfig, and `default={}` for per_scope_ttl (matches existing schema.py patterns).

16. **Added TOCTOU protection** - Added atomic file creation with secure permissions in `_ensure_db()` (matches session/storage.py pattern).

17. **Updated TTL defaults** - Project scope: 30 days (was 7), System scope: 1 year (was 30 days).

18. **Changed TTL to check-only** - `cleanup_expired()` renamed to `count_expired()`/`get_expired()`. TTL flags entries as expired but does NOT auto-delete. User-in-the-loop cleanup deferred to Future Enhancements.

19. **Added `is_expired` property** - ClipboardEntry now has `is_expired` property for easy expiry checking.

20. **Added agent_id to ContextManager** - Added `agent_id: str | None = None` parameter to `__init__()` for clipboard scoping (identified by validation agents 2026-01-31).

21. **Added tags/any_tags to clipboard_list** - Added `tags` (AND filter) and `any_tags` (OR filter) parameters to ClipboardListSkill to match checklist P3.2 (identified by validation agents 2026-01-31).

22. **Added ttl_seconds to clipboard_update** - Added `ttl_seconds` parameter to ClipboardUpdateSkill, manager.update(), and storage.update() to match checklist P3.3 (identified by validation agents 2026-01-31).

23. **Use SECURE_FILE_MODE constant** - Changed hardcoded `0o600` to `SECURE_FILE_MODE` from `nexus3.core.secure_io` and use `secure_mkdir()` for consistency with session/storage.py (identified by validation agents 2026-01-31).

---

## Recommended Implementation Order (and Parallelization)

This plan touches multiple subsystems (clipboard core, skills, context injection, config, pool integration, persistence, tests). The order below minimizes merge conflicts and keeps each step testable.

### Step 0: Scaffolding / contracts (safe to do first)

- Create `nexus3/clipboard/` package skeleton and minimal exports.
- Decide the public API surface (`ClipboardManager`, `ClipboardScope`, `InsertionMode`, etc.) and keep it stable.

**Parallelizable:** yes (one agent can create the package skeleton while another drafts tests stubs).

### Step 1: Core data model + storage (unblocks everything)

- Implement `nexus3/clipboard/types.py` (ClipboardEntry, ClipboardTag, permissions, size limits).
- Implement `nexus3/clipboard/storage.py` including schema, TOCTOU-safe DB creation, foreign keys, and tag helpers.
- Implement `nexus3/clipboard/manager.py` core CRUD (`copy/get/update/delete/list_entries`) with TTL + tags behavior.

**Why first:** skills, injection, and persistence all depend on these types.

**Parallelizable:** partially.
- Agent A: `types.py`
- Agent B: `storage.py` (once schema shape is agreed)
- Agent C: `manager.py` (can start once types+storage interfaces are stable)

Avoid parallel edits to the same file until interfaces are agreed.

### Step 2: Unit tests for core clipboard modules (stabilizes the API)

- Add `tests/unit/clipboard/test_types.py`, `test_storage.py`, `test_manager.py`.

**Parallelizable:** yes (tests can be written alongside implementation, but expect small follow-up edits).

### Step 3: Skills (copy/cut/paste/manage + extras)

- Implement file I/O skills in `nexus3/skill/builtin/`:
  - `clipboard_copy.py` / `clipboard_paste.py`
  - `clipboard_manage.py`
  - `clipboard_search.py`, `clipboard_tag.py`, `clipboard_export.py`, `clipboard_import.py`

Use repo-native patterns:
- `@handle_file_errors` for path validation errors
- `asyncio.to_thread(...)` for file reads/writes

**Parallelizable:** mostly.
- Agent A: copy/cut
- Agent B: paste
- Agent C: manage (list/get/update/delete/clear)
- Agent D: extras (search/tag/import/export)

These files don’t overlap, but all depend on the core clipboard API.

### Step 4: Register skills

- Update `nexus3/skill/builtin/registration.py` to import and register all clipboard skills.

**Parallelizable:** no (small, centralized edit).

### Step 5: Config + Context injection (per-turn)

- Add `ClipboardConfig` to `nexus3/config/schema.py` and add `clipboard: ClipboardConfig = ClipboardConfig()` to root `Config`.
- Update `nexus3/context/manager.py` to:
  - accept `clipboard_manager` + `clipboard_config`
  - inject clipboard index in `build_messages()`
  - fix truncation token counting by using a shared helper (see Token Counting Consistency section)

**Parallelizable:** limited.
- Agent A: config schema changes
- Agent B: context manager injection + truncation changes

But coordinate carefully because ContextManager will reference ClipboardConfig.

### Step 6: Pool integration

- Update `nexus3/rpc/pool.py`:
  - create/register a `ClipboardManager` in both `_create_unlocked()` and `_restore_unlocked()`
  - pass it + `self._shared.config.clipboard` into `ContextManager(...)`

**Parallelizable:** no (central file).

### Step 7: Session persistence for agent-scope clipboard

- Update `nexus3/session/persistence.py` to include `clipboard_agent_entries` in `SavedSession` and in `to_dict()/from_dict()`.
- Update `pool.py` restore path to repopulate agent clipboard entries.

**Parallelizable:** partially.
- Agent A: persistence.py
- Agent B: pool.py restore wiring

But pool.py is also touched in Step 6; do Step 6 first or coordinate via a single owner.

### Step 8: Skill and integration tests

- Add unit tests under `tests/unit/skill/` for new clipboard skills.
- Add `tests/unit/test_clipboard_persistence.py` for SavedSession serialization.
- Add integration tests `tests/integration/test_clipboard.py` (or split into multiple files if desired).

**Parallelizable:** yes (tests can be split by file/module).

---

## Implementation Checklist

Use this checklist to track implementation progress. Each item can be assigned to a task agent.

### Phase 1: Core Infrastructure

- [ ] **P1.1** Create `nexus3/clipboard/` directory
- [ ] **P1.2** Implement `nexus3/clipboard/types.py` (ClipboardEntry, ClipboardScope, ClipboardPermissions, CLIPBOARD_PRESETS, ClipboardTag)
- [ ] **P1.3** Implement `nexus3/clipboard/storage.py` (ClipboardStorage SQLite operations)
- [ ] **P1.4** Add `tags` + `clipboard_tags` junction tables to schema (for tag support)
- [ ] **P1.5** Add `expires_at` column to schema (for TTL support)
- [ ] **P1.6** Implement `nexus3/clipboard/manager.py` (ClipboardManager with all CRUD operations)
- [ ] **P1.7** Add tag methods to ClipboardManager (`add_tags`, `remove_tags`, `list_tags`)
- [ ] **P1.8** Add TTL methods to ClipboardManager (`count_expired`, `get_expired`, `_get_ttl_for_scope`)
- [ ] **P1.9** Implement `nexus3/clipboard/injection.py` (format_clipboard_context, format_entry_detail)
- [ ] **P1.10** Implement `nexus3/clipboard/__init__.py` (public API exports)
- [ ] **P1.11** Add unit tests for types.py (ClipboardEntry.from_content, permission checks)
- [ ] **P1.12** Add unit tests for storage.py (CRUD operations, key uniqueness, tags, TTL)
- [ ] **P1.13** Add unit tests for manager.py (scope resolution, permission enforcement, tags, TTL)

### Phase 2: Core Skills

- [ ] **P2.1** Implement `nexus3/skill/builtin/clipboard_copy.py` (CopySkill, CutSkill)
- [ ] **P2.2** Add `tags` parameter to CopySkill (optional list of tag names)
- [ ] **P2.3** Add `ttl_seconds` parameter to CopySkill (optional TTL override)
- [ ] **P2.4** Implement `nexus3/skill/builtin/clipboard_paste.py` (PasteSkill)
- [ ] **P2.5** Add unit tests for copy/cut skills (including tags and TTL)
- [ ] **P2.6** Add unit tests for paste skill (all insertion modes)

### Phase 3: Management Skills

- [ ] **P3.1** Implement `nexus3/skill/builtin/clipboard_manage.py` (clipboard_list, clipboard_get, clipboard_update, clipboard_delete, clipboard_clear)
- [ ] **P3.2** Add `tags` and `any_tags` filter parameters to `clipboard_list`
- [ ] **P3.3** Add `ttl_seconds` parameter to `clipboard_update`
- [ ] **P3.4** Implement `nexus3/skill/builtin/clipboard_search.py` (ClipboardSearchSkill - LIKE-based content search)
- [ ] **P3.5** Implement `nexus3/skill/builtin/clipboard_tag.py` (ClipboardTagSkill - list/add/remove/create/delete tags)
- [ ] **P3.6** Implement `nexus3/skill/builtin/clipboard_export.py` (export entries to JSON file)
- [ ] **P3.7** Implement `nexus3/skill/builtin/clipboard_import.py` (import entries from JSON file)
- [ ] **P3.8** Add unit tests for management skills
- [ ] **P3.9** Add unit tests for search, tag, import/export skills
- [ ] **P3.10** Register all clipboard skills in `nexus3/skill/builtin/registration.py`

### Phase 4: Service Integration

- [ ] **P4.1 (Optional)** Add `get_clipboard_manager()` to `nexus3/skill/services.py`
- [ ] **P4.2** Add ClipboardManager registration to `nexus3/rpc/pool.py` in `_create_unlocked()` and `_restore_unlocked()`
- [ ] **P4.3** Pass ClipboardManager (+ ClipboardConfig) into ContextManager constructor in both `_create_unlocked()` and `_restore_unlocked()`
- [ ] **P4.4** Add cleanup logic for ClipboardManager in agent destruction

### Phase 5: Context Injection

- [ ] **P5.1** Integrate `format_clipboard_context()` in `ContextManager.build_messages()` (per-turn injection)
- [ ] **P5.2** Add `ClipboardConfig` to `nexus3/config/schema.py`
- [ ] **P5.3** Wire config options (inject_into_context, max_injected_entries) into injection
- [ ] **P5.4** Add TTL config options (`default_ttl_seconds`, `per_scope_ttl`) to `ClipboardConfig`

### Phase 5b: TTL/Expiry Tracking (No Auto-Delete)

Note: TTL marks entries as expired but does NOT auto-delete. User-in-the-loop cleanup is deferred to Future Enhancements.

- [ ] **P5b.1** Add `is_expired` property to ClipboardEntry (checks expires_at vs now)
- [ ] **P5b.2** Update `list_entries()` to optionally filter/flag expired entries
- [ ] **P5b.3** Add expired count to context injection (e.g., "3 expired entries pending cleanup")
- [ ] **P5b.4** Add unit tests for TTL expiry detection (count_expired, get_expired, is_expired)

### Phase 6: Session Persistence

- [ ] **P6.1** Add `clipboard_agent_entries` field to `SavedSession` in `nexus3/session/persistence.py`
- [ ] **P6.2** Update `SavedSession.to_dict()` / `from_dict()` to include the new field with backwards-compatible defaults (`data.get(...)`).
- [ ] **P6.3** Decide whether to bump `SESSION_SCHEMA_VERSION` (currently `1`) in `nexus3/session/persistence.py`.
      - The existing pattern already uses `data.get("schema_version", 1)` and defaulted fields for backwards compatibility.
      - If you can tolerate older saves silently missing `clipboard_agent_entries`, you may *not* need to bump.
- [ ] **P6.4** Wire restoration in `nexus3/rpc/pool.py` `_restore_unlocked()` method (after `ContextManager` and services are created).
- [ ] **P6.5** Add unit tests for clipboard serialization/deserialization
- [ ] **P6.6** Add integration test: copy → save → resume → verify clipboard intact

### Phase 7: Integration Testing

- [ ] **P7.1** Integration test: copy/paste roundtrip (copy from A, paste to B)
- [ ] **P7.2** Integration test: cut/paste roundtrip (verify source modified)
- [ ] **P7.3** Integration test: cross-agent project scope sharing
- [ ] **P7.4** Integration test: context injection appears in system prompt
- [ ] **P7.5** Integration test: permission boundaries (sandboxed can't access project)
- [ ] **P7.6** Integration test: persistence (project/system entries survive restart)
- [ ] **P7.7** Integration test: search finds entries by content substring
- [ ] **P7.8** Integration test: tags filter entries correctly (AND/OR logic)
- [ ] **P7.9** Integration test: import/export roundtrip preserves entries

### Phase 8: Live Testing

- [ ] **P8.1** Live test with real NEXUS3 REPL (create test files, copy/paste flow)
- [ ] **P8.2** Live test tags workflow (copy with tags, filter by tags)
- [ ] **P8.3** Live test TTL (copy with ttl_seconds, verify expiry flagging - no auto-delete)
- [ ] **P8.4** Live test session persistence (copy, /save, restart, --resume, verify)
- [ ] **P8.5** Verify no regressions in existing skills

### Phase 9: Documentation

- [ ] **P9.1** Add all clipboard skills to `CLAUDE.md` Built-in Skills table
- [ ] **P9.2** Add Clipboard section to `CLAUDE.md` describing the system
- [ ] **P9.3** Add clipboard section to `nexus3/skill/README.md`
- [ ] **P9.4** Create `nexus3/clipboard/README.md` with module documentation
- [ ] **P9.5** Update `CLAUDE.md` Configuration section with clipboard config options (including TTL)
- [ ] **P9.6** Document tags, search, import/export, and TTL features
- [ ] **P9.7** Ensure all skill `description` properties are comprehensive with examples

---

## Quick Reference: File Locations

| Component | File Path |
|-----------|-----------|
| Types & dataclasses | `nexus3/clipboard/types.py` |
| SQLite storage | `nexus3/clipboard/storage.py` |
| Manager (main logic) | `nexus3/clipboard/manager.py` |
| Context formatting | `nexus3/clipboard/injection.py` |
| Per-turn injection | `nexus3/context/manager.py` (`build_messages()`) |
| Public API exports | `nexus3/clipboard/__init__.py` |
| Copy/cut skills | `nexus3/skill/builtin/clipboard_copy.py` |
| Paste skill | `nexus3/skill/builtin/clipboard_paste.py` |
| Management skills | `nexus3/skill/builtin/clipboard_manage.py` |
| Search skill | `nexus3/skill/builtin/clipboard_search.py` |
| Tag skill | `nexus3/skill/builtin/clipboard_tag.py` |
| Export skill | `nexus3/skill/builtin/clipboard_export.py` |
| Import skill | `nexus3/skill/builtin/clipboard_import.py` |
| Skill registration | `nexus3/skill/builtin/registration.py` |
| Service accessor | `nexus3/skill/services.py` |
| Agent creation + TTL expiry tracking | `nexus3/rpc/pool.py` |
| Session persistence | `nexus3/session/persistence.py` |
| Config schema | `nexus3/config/schema.py` |
| Unit tests | `tests/unit/clipboard/` + `tests/unit/skill/` |
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
| expires_at | REAL | Unix timestamp for TTL expiry (NULL = permanent) |
| ttl_seconds | INTEGER | TTL in seconds (informational, NULL = permanent) |

**Tags table:**

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| name | TEXT NOT NULL UNIQUE | Tag name (indexed) |
| description | TEXT | Optional tag description |
| created_at | REAL NOT NULL | Unix timestamp |

**Clipboard-Tags junction table:**

| Column | Type | Description |
|--------|------|-------------|
| clipboard_id | INTEGER NOT NULL | FK to clipboard.id (CASCADE delete) |
| tag_id | INTEGER NOT NULL | FK to tags.id (CASCADE delete) |
| PRIMARY KEY | (clipboard_id, tag_id) | Composite primary key |

**Metadata table:**

| Column | Type | Description |
|--------|------|-------------|
| key | TEXT PRIMARY KEY | Metadata key |
| value | TEXT | Metadata value |

Schema version is stored as `schema_version` → `"1"` in metadata table.
