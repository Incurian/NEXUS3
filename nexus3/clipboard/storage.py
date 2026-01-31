"""SQLite storage for clipboard entries."""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING

from nexus3.clipboard.types import ClipboardEntry, ClipboardScope
from nexus3.core.secure_io import SECURE_FILE_MODE, secure_mkdir

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

        # Check/set schema version
        cur = self._conn.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        )
        row = cur.fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
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
                entry.key,
                entry.content,
                entry.short_description,
                entry.source_path,
                entry.source_lines,
                entry.line_count,
                entry.byte_count,
                entry.created_at,
                entry.modified_at,
                entry.created_by_agent,
                entry.modified_by_agent,
                entry.expires_at,
                entry.ttl_seconds,
            ),
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
            line_count = content.count("\n") + (
                1 if content and not content.endswith("\n") else 0
            )
            params.extend([content, line_count, len(content.encode("utf-8"))])

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
            f"UPDATE clipboard SET {', '.join(updates)} WHERE key = ?", params
        )
        self._conn.commit()

        result = self.get(new_key if new_key else key)
        assert result is not None  # We just updated it
        return result

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
            (now,),
        )
        return cur.fetchone()[0]

    def get_expired(self, now: float) -> list[ClipboardEntry]:
        """Get all expired entries for review before cleanup."""
        assert self._conn is not None
        cur = self._conn.execute(
            "SELECT * FROM clipboard WHERE expires_at IS NOT NULL AND expires_at <= ? ORDER BY expires_at",
            (now,),
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
        self._conn.execute(
            "DELETE FROM clipboard_tags WHERE clipboard_id = ?", (clipboard_id,)
        )

        # Add new tags (creating tags if needed)
        for tag_name in tags:
            # Ensure tag exists
            self._conn.execute(
                "INSERT OR IGNORE INTO tags (name, created_at) VALUES (?, ?)",
                (tag_name, time.time()),
            )
            # Get tag ID
            cur = self._conn.execute("SELECT id FROM tags WHERE name = ?", (tag_name,))
            tag_id = cur.fetchone()["id"]
            # Link to clipboard entry
            self._conn.execute(
                "INSERT INTO clipboard_tags (clipboard_id, tag_id) VALUES (?, ?)",
                (clipboard_id, tag_id),
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
            (key,),
        )
        return [row["name"] for row in cur.fetchall()]

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
