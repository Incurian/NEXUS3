"""SQLite storage for session data."""

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import Any

# Schema version for future migrations
SCHEMA_VERSION = 2

SCHEMA = """
-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

-- Core message storage
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    name TEXT,
    tool_call_id TEXT,
    tool_calls TEXT,
    tokens INTEGER,
    timestamp REAL NOT NULL,
    in_context INTEGER DEFAULT 1,
    summary_of TEXT
);

-- Session metadata (key-value store)
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Session markers for cleanup (Phase 6)
CREATE TABLE IF NOT EXISTS session_markers (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- Singleton row
    session_type TEXT NOT NULL DEFAULT 'temp',  -- 'saved' | 'temp' | 'subagent'
    session_status TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'destroyed' | 'orphaned'
    parent_agent_id TEXT,  -- Who spawned this agent (nullable)
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

-- Events for verbose logging (thinking, timing, etc.)
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER,
    event_type TEXT NOT NULL,
    data TEXT,
    timestamp REAL NOT NULL,
    FOREIGN KEY (message_id) REFERENCES messages(id)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_messages_in_context ON messages(in_context);
CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_message ON events(message_id);
CREATE INDEX IF NOT EXISTS idx_session_markers_status ON session_markers(session_status);
CREATE INDEX IF NOT EXISTS idx_session_markers_type ON session_markers(session_type);
"""


@dataclass
class SessionMarkers:
    """Session markers for cleanup tracking."""

    session_type: str  # 'saved' | 'temp' | 'subagent'
    session_status: str  # 'active' | 'destroyed' | 'orphaned'
    parent_agent_id: str | None
    created_at: float
    updated_at: float

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "SessionMarkers":
        """Create from database row."""
        return cls(
            session_type=row["session_type"],
            session_status=row["session_status"],
            parent_agent_id=row["parent_agent_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class MessageRow:
    """A message from the database."""

    id: int
    role: str
    content: str
    name: str | None
    tool_call_id: str | None
    tool_calls: list[dict[str, Any]] | None
    tokens: int | None
    timestamp: float
    in_context: bool
    summary_of: list[int] | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "MessageRow":
        """Create from database row."""
        tool_calls = None
        if row["tool_calls"]:
            tool_calls = json.loads(row["tool_calls"])

        summary_of = None
        if row["summary_of"]:
            summary_of = [int(x) for x in row["summary_of"].split(",")]

        return cls(
            id=row["id"],
            role=row["role"],
            content=row["content"],
            name=row["name"],
            tool_call_id=row["tool_call_id"],
            tool_calls=tool_calls,
            tokens=row["tokens"],
            timestamp=row["timestamp"],
            in_context=bool(row["in_context"]),
            summary_of=summary_of,
        )


@dataclass
class EventRow:
    """An event from the database."""

    id: int
    message_id: int | None
    event_type: str
    data: dict[str, Any] | None
    timestamp: float

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "EventRow":
        """Create from database row."""
        data = None
        if row["data"]:
            data = json.loads(row["data"])

        return cls(
            id=row["id"],
            message_id=row["message_id"],
            event_type=row["event_type"],
            data=data,
            timestamp=row["timestamp"],
        )


class SessionStorage:
    """SQLite operations for session data."""

    def __init__(self, db_path: Path) -> None:
        """Initialize storage with database path.

        Creates the database and schema if they don't exist.
        """
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._conn is None:
            # Ensure parent directory exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            # Enable foreign keys
            self._conn.execute("PRAGMA foreign_keys = ON")

        return self._conn

    def _ensure_schema(self) -> None:
        """Create schema if needed."""
        conn = self._get_conn()

        # Check if schema exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        if cursor.fetchone() is None:
            # Fresh database - create schema
            conn.executescript(SCHEMA)
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
            conn.commit()
        else:
            # Check version for future migrations
            cursor = conn.execute("SELECT version FROM schema_version")
            row = cursor.fetchone()
            if row and row[0] < SCHEMA_VERSION:
                self._migrate(row[0], SCHEMA_VERSION)

    def _migrate(self, from_version: int, to_version: int) -> None:
        """Run migrations between versions."""
        conn = self._get_conn()

        if from_version < 2 <= to_version:
            # Migration 1 -> 2: Add session_markers table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_markers (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    session_type TEXT NOT NULL DEFAULT 'temp',
                    session_status TEXT NOT NULL DEFAULT 'active',
                    parent_agent_id TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_session_markers_status "
                "ON session_markers(session_status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_session_markers_type "
                "ON session_markers(session_type)"
            )

            # Initialize with defaults if not exists (for existing DBs)
            ts = time()
            conn.execute(
                """
                INSERT OR IGNORE INTO session_markers
                (id, session_type, session_status, parent_agent_id, created_at, updated_at)
                VALUES (1, 'temp', 'active', NULL, ?, ?)
                """,
                (ts, ts),
            )

            # Update schema version
            conn.execute("UPDATE schema_version SET version = ?", (2,))
            conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # === Message Operations ===

    def insert_message(
        self,
        role: str,
        content: str,
        *,
        name: str | None = None,
        tool_call_id: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        tokens: int | None = None,
        timestamp: float | None = None,
    ) -> int:
        """Insert a message and return its ID."""
        conn = self._get_conn()

        tool_calls_json = json.dumps(tool_calls) if tool_calls else None
        ts = timestamp if timestamp is not None else time()

        cursor = conn.execute(
            """
            INSERT INTO messages (role, content, name, tool_call_id, tool_calls, tokens, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (role, content, name, tool_call_id, tool_calls_json, tokens, ts),
        )
        conn.commit()

        return cursor.lastrowid  # type: ignore[return-value]

    def get_messages(self, in_context_only: bool = True) -> list[MessageRow]:
        """Get messages, optionally filtered to context window."""
        conn = self._get_conn()

        if in_context_only:
            cursor = conn.execute(
                "SELECT * FROM messages WHERE in_context = 1 ORDER BY id"
            )
        else:
            cursor = conn.execute("SELECT * FROM messages ORDER BY id")

        return [MessageRow.from_row(row) for row in cursor.fetchall()]

    def get_message(self, message_id: int) -> MessageRow | None:
        """Get a single message by ID."""
        conn = self._get_conn()
        cursor = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
        row = cursor.fetchone()
        return MessageRow.from_row(row) if row else None

    def update_context_status(
        self,
        message_ids: list[int],
        in_context: bool,
    ) -> None:
        """Batch update in_context flag for messages."""
        if not message_ids:
            return

        conn = self._get_conn()
        placeholders = ",".join("?" for _ in message_ids)
        conn.execute(
            f"UPDATE messages SET in_context = ? WHERE id IN ({placeholders})",
            [int(in_context), *message_ids],
        )
        conn.commit()

    def mark_as_summary(
        self,
        summary_id: int,
        replaced_ids: list[int],
    ) -> None:
        """Mark a message as a summary of other messages.

        Also marks the replaced messages as out of context.
        """
        conn = self._get_conn()

        # Update the summary message
        summary_of = ",".join(str(x) for x in replaced_ids)
        conn.execute(
            "UPDATE messages SET summary_of = ? WHERE id = ?",
            (summary_of, summary_id),
        )

        # Mark replaced messages as out of context
        self.update_context_status(replaced_ids, in_context=False)

    def get_token_count(self) -> int:
        """Get total tokens in current context."""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT COALESCE(SUM(tokens), 0) FROM messages WHERE in_context = 1"
        )
        row = cursor.fetchone()
        return row[0] if row else 0

    # === Metadata Operations ===

    def get_metadata(self, key: str) -> str | None:
        """Get a metadata value."""
        conn = self._get_conn()
        cursor = conn.execute("SELECT value FROM metadata WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else None

    def set_metadata(self, key: str, value: str) -> None:
        """Set a metadata value."""
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()

    def get_all_metadata(self) -> dict[str, str]:
        """Get all metadata as a dictionary."""
        conn = self._get_conn()
        cursor = conn.execute("SELECT key, value FROM metadata")
        return {row["key"]: row["value"] for row in cursor.fetchall()}

    # === Event Operations ===

    def insert_event(
        self,
        event_type: str,
        data: dict[str, Any] | None = None,
        message_id: int | None = None,
        timestamp: float | None = None,
    ) -> int:
        """Insert an event and return its ID."""
        conn = self._get_conn()

        data_json = json.dumps(data) if data else None
        ts = timestamp if timestamp is not None else time()

        cursor = conn.execute(
            """
            INSERT INTO events (message_id, event_type, data, timestamp)
            VALUES (?, ?, ?, ?)
            """,
            (message_id, event_type, data_json, ts),
        )
        conn.commit()

        return cursor.lastrowid  # type: ignore[return-value]

    def get_events(
        self,
        event_type: str | None = None,
        message_id: int | None = None,
    ) -> list[EventRow]:
        """Get events, optionally filtered."""
        conn = self._get_conn()

        conditions = []
        params: list[Any] = []

        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)

        if message_id is not None:
            conditions.append("message_id = ?")
            params.append(message_id)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        cursor = conn.execute(
            f"SELECT * FROM events WHERE {where_clause} ORDER BY id",
            params,
        )

        return [EventRow.from_row(row) for row in cursor.fetchall()]

    # === Session Marker Operations ===

    def init_session_markers(
        self,
        session_type: str = "temp",
        parent_agent_id: str | None = None,
    ) -> None:
        """Initialize session markers for a new session.

        Args:
            session_type: 'saved' | 'temp' | 'subagent'
            parent_agent_id: ID of parent agent (for subagents)
        """
        conn = self._get_conn()
        ts = time()

        conn.execute(
            """
            INSERT OR REPLACE INTO session_markers
            (id, session_type, session_status, parent_agent_id, created_at, updated_at)
            VALUES (1, ?, 'active', ?, ?, ?)
            """,
            (session_type, parent_agent_id, ts, ts),
        )
        conn.commit()

    def get_session_markers(self) -> SessionMarkers | None:
        """Get current session markers.

        Returns:
            SessionMarkers if set, None otherwise.
        """
        conn = self._get_conn()
        cursor = conn.execute("SELECT * FROM session_markers WHERE id = 1")
        row = cursor.fetchone()
        return SessionMarkers.from_row(row) if row else None

    def update_session_metadata(
        self,
        session_type: str | None = None,
        session_status: str | None = None,
        parent_agent_id: str | None = None,
    ) -> None:
        """Update session metadata fields.

        Only updates fields that are provided (not None).

        Args:
            session_type: 'saved' | 'temp' | 'subagent'
            session_status: 'active' | 'destroyed' | 'orphaned'
            parent_agent_id: ID of parent agent
        """
        conn = self._get_conn()
        ts = time()

        updates = ["updated_at = ?"]
        params: list[Any] = [ts]

        if session_type is not None:
            updates.append("session_type = ?")
            params.append(session_type)

        if session_status is not None:
            updates.append("session_status = ?")
            params.append(session_status)

        if parent_agent_id is not None:
            updates.append("parent_agent_id = ?")
            params.append(parent_agent_id)

        set_clause = ", ".join(updates)
        conn.execute(
            f"UPDATE session_markers SET {set_clause} WHERE id = 1",
            params,
        )
        conn.commit()

    def mark_session_destroyed(self) -> None:
        """Mark session as destroyed for cleanup tracking."""
        self.update_session_metadata(session_status="destroyed")

    def get_orphaned_sessions(self, older_than_days: int = 7) -> list[SessionMarkers]:
        """Get sessions that are orphaned and older than specified days.

        This is a placeholder for future cleanup functionality.
        In practice, this would scan multiple session databases.

        Args:
            older_than_days: Only return sessions older than this many days.

        Returns:
            List of orphaned session markers.
        """
        conn = self._get_conn()
        cutoff = time() - (older_than_days * 24 * 60 * 60)

        cursor = conn.execute(
            """
            SELECT * FROM session_markers
            WHERE session_status = 'orphaned'
            AND updated_at < ?
            """,
            (cutoff,),
        )

        return [SessionMarkers.from_row(row) for row in cursor.fetchall()]
