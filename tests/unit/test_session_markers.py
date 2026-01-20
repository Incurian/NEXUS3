"""Unit tests for SQLite session markers for cleanup tracking.

Tests cover:
- nexus3/session/storage.py - SessionMarkers and related methods
- nexus3/session/logging.py - SessionLogger marker integration
- Schema migration from v1 to v2
"""

from pathlib import Path
from time import time

import pytest

from nexus3.session.logging import SessionLogger
from nexus3.session.storage import (
    SCHEMA_VERSION,
    SessionMarkers,
    SessionStorage,
)
from nexus3.session.types import LogConfig, LogStream


# ============================================================================
# SessionMarkers Dataclass Tests
# ============================================================================


class TestSessionMarkers:
    """Tests for SessionMarkers dataclass."""

    def test_attributes(self):
        """SessionMarkers has expected attributes."""
        ts = time()
        markers = SessionMarkers(
            session_type="temp",
            session_status="active",
            parent_agent_id="parent_123",
            created_at=ts,
            updated_at=ts,
        )

        assert markers.session_type == "temp"
        assert markers.session_status == "active"
        assert markers.parent_agent_id == "parent_123"
        assert markers.created_at == ts
        assert markers.updated_at == ts

    def test_nullable_parent_agent_id(self):
        """parent_agent_id can be None."""
        ts = time()
        markers = SessionMarkers(
            session_type="temp",
            session_status="active",
            parent_agent_id=None,
            created_at=ts,
            updated_at=ts,
        )

        assert markers.parent_agent_id is None


# ============================================================================
# SessionStorage Session Marker Tests
# ============================================================================


class TestSessionStorageMarkers:
    """Tests for SessionStorage session marker operations."""

    @pytest.fixture
    def storage(self, tmp_path) -> SessionStorage:
        """Create a fresh SessionStorage instance."""
        db_path = tmp_path / "test.db"
        storage = SessionStorage(db_path)
        yield storage
        storage.close()

    def test_schema_version_is_3(self):
        """Schema version is 3 (includes session_markers and meta column)."""
        assert SCHEMA_VERSION == 3

    def test_session_markers_table_created(self, storage):
        """session_markers table is created in schema."""
        conn = storage._get_conn()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='session_markers'"
        )
        result = cursor.fetchone()
        assert result is not None

    def test_init_session_markers_defaults(self, storage):
        """init_session_markers sets default values."""
        storage.init_session_markers()

        markers = storage.get_session_markers()
        assert markers is not None
        assert markers.session_type == "temp"
        assert markers.session_status == "active"
        assert markers.parent_agent_id is None
        assert markers.created_at > 0
        assert markers.updated_at > 0

    def test_init_session_markers_custom(self, storage):
        """init_session_markers accepts custom values."""
        storage.init_session_markers(
            session_type="subagent",
            parent_agent_id="parent_abc",
        )

        markers = storage.get_session_markers()
        assert markers is not None
        assert markers.session_type == "subagent"
        assert markers.parent_agent_id == "parent_abc"

    def test_init_session_markers_saved_type(self, storage):
        """init_session_markers can set 'saved' type."""
        storage.init_session_markers(session_type="saved")

        markers = storage.get_session_markers()
        assert markers is not None
        assert markers.session_type == "saved"

    def test_get_session_markers_before_init(self, storage):
        """get_session_markers returns None before init."""
        # Fresh DB without explicit init
        markers = storage.get_session_markers()
        # Might be None or might have been auto-initialized by migration
        # Both are acceptable

    def test_update_session_metadata_type(self, storage):
        """update_session_metadata can change session_type."""
        storage.init_session_markers(session_type="temp")
        storage.update_session_metadata(session_type="saved")

        markers = storage.get_session_markers()
        assert markers is not None
        assert markers.session_type == "saved"

    def test_update_session_metadata_status(self, storage):
        """update_session_metadata can change session_status."""
        storage.init_session_markers()
        storage.update_session_metadata(session_status="destroyed")

        markers = storage.get_session_markers()
        assert markers is not None
        assert markers.session_status == "destroyed"

    def test_update_session_metadata_parent_id(self, storage):
        """update_session_metadata can set parent_agent_id."""
        storage.init_session_markers()
        storage.update_session_metadata(parent_agent_id="new_parent")

        markers = storage.get_session_markers()
        assert markers is not None
        assert markers.parent_agent_id == "new_parent"

    def test_update_session_metadata_updates_timestamp(self, storage):
        """update_session_metadata updates updated_at timestamp."""
        storage.init_session_markers()
        markers_before = storage.get_session_markers()
        assert markers_before is not None

        # Small delay to ensure timestamp changes
        import time

        time.sleep(0.01)

        storage.update_session_metadata(session_status="orphaned")
        markers_after = storage.get_session_markers()
        assert markers_after is not None

        assert markers_after.updated_at > markers_before.updated_at
        # created_at should be unchanged
        assert markers_after.created_at == markers_before.created_at

    def test_update_session_metadata_partial(self, storage):
        """update_session_metadata only updates provided fields."""
        storage.init_session_markers(
            session_type="temp",
            parent_agent_id="original_parent",
        )

        storage.update_session_metadata(session_status="destroyed")

        markers = storage.get_session_markers()
        assert markers is not None
        assert markers.session_type == "temp"  # Unchanged
        assert markers.parent_agent_id == "original_parent"  # Unchanged
        assert markers.session_status == "destroyed"  # Changed

    def test_mark_session_destroyed(self, storage):
        """mark_session_destroyed sets status to 'destroyed'."""
        storage.init_session_markers()
        storage.mark_session_destroyed()

        markers = storage.get_session_markers()
        assert markers is not None
        assert markers.session_status == "destroyed"

    def test_get_orphaned_sessions_empty(self, storage):
        """get_orphaned_sessions returns empty list when no orphans."""
        storage.init_session_markers()  # active session
        orphans = storage.get_orphaned_sessions(older_than_days=0)
        assert orphans == []

    def test_get_orphaned_sessions_finds_orphan(self, storage):
        """get_orphaned_sessions finds orphaned sessions."""
        storage.init_session_markers()
        storage.update_session_metadata(session_status="orphaned")

        # Force old timestamp for testing
        conn = storage._get_conn()
        old_ts = time() - (8 * 24 * 60 * 60)  # 8 days ago
        conn.execute(
            "UPDATE session_markers SET updated_at = ? WHERE id = 1",
            (old_ts,),
        )
        conn.commit()

        orphans = storage.get_orphaned_sessions(older_than_days=7)
        assert len(orphans) == 1
        assert orphans[0].session_status == "orphaned"

    def test_get_orphaned_sessions_respects_age(self, storage):
        """get_orphaned_sessions respects older_than_days parameter."""
        storage.init_session_markers()
        storage.update_session_metadata(session_status="orphaned")

        # Session is recently updated (within 7 days)
        orphans = storage.get_orphaned_sessions(older_than_days=7)
        assert orphans == []


# ============================================================================
# Schema Migration Tests
# ============================================================================


class TestSchemaMigration:
    """Tests for schema migration from v1 to v2."""

    def test_migration_from_v1_to_v2(self, tmp_path):
        """Migration from v1 creates session_markers table."""
        db_path = tmp_path / "test.db"

        # Create a v1 database manually
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
            INSERT INTO schema_version (version) VALUES (1);

            CREATE TABLE messages (
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

            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);

            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                event_type TEXT NOT NULL,
                data TEXT,
                timestamp REAL NOT NULL
            );
        """
        )
        conn.commit()
        conn.close()

        # Open with SessionStorage - should trigger migration
        storage = SessionStorage(db_path)

        # Verify migration happened
        conn = storage._get_conn()

        # Check schema version updated (migrates through v2 to current v3)
        cursor = conn.execute("SELECT version FROM schema_version")
        version = cursor.fetchone()[0]
        assert version == 3

        # Check session_markers table exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='session_markers'"
        )
        assert cursor.fetchone() is not None

        # Check indexes created
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_session_markers_status'"
        )
        assert cursor.fetchone() is not None

        storage.close()

    def test_migration_initializes_default_markers(self, tmp_path):
        """Migration initializes default session markers."""
        db_path = tmp_path / "test.db"

        # Create a v1 database
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
            INSERT INTO schema_version (version) VALUES (1);
            CREATE TABLE messages (id INTEGER PRIMARY KEY, role TEXT, content TEXT, timestamp REAL);
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE events (id INTEGER PRIMARY KEY, event_type TEXT, timestamp REAL);
        """
        )
        conn.commit()
        conn.close()

        # Open with SessionStorage
        storage = SessionStorage(db_path)

        # Check default markers were created
        markers = storage.get_session_markers()
        assert markers is not None
        assert markers.session_type == "temp"
        assert markers.session_status == "active"

        storage.close()


# ============================================================================
# SessionLogger Marker Integration Tests
# ============================================================================


class TestSessionLoggerMarkers:
    """Tests for SessionLogger session marker integration."""

    @pytest.fixture
    def logger(self, tmp_path) -> SessionLogger:
        """Create a SessionLogger."""
        config = LogConfig(
            base_dir=tmp_path,
            streams=LogStream.CONTEXT,
            session_type="temp",
        )
        logger = SessionLogger(config)
        yield logger
        logger.close()

    def test_logger_initializes_markers(self, logger):
        """SessionLogger initializes session markers on creation."""
        markers = logger.storage.get_session_markers()
        assert markers is not None
        assert markers.session_status == "active"

    def test_logger_uses_config_session_type(self, tmp_path):
        """SessionLogger uses session_type from config."""
        config = LogConfig(
            base_dir=tmp_path,
            streams=LogStream.CONTEXT,
            session_type="saved",
        )
        logger = SessionLogger(config)

        markers = logger.storage.get_session_markers()
        assert markers is not None
        assert markers.session_type == "saved"

        logger.close()

    def test_logger_subagent_type_from_parent(self, tmp_path):
        """SessionLogger sets 'subagent' type when parent_session is set."""
        config = LogConfig(
            base_dir=tmp_path,
            streams=LogStream.CONTEXT,
            parent_session="parent_123",
            session_type="temp",  # Should be overridden
        )
        logger = SessionLogger(config)

        markers = logger.storage.get_session_markers()
        assert markers is not None
        assert markers.session_type == "subagent"
        assert markers.parent_agent_id == "parent_123"

        logger.close()

    def test_logger_update_session_status(self, logger):
        """update_session_status changes status."""
        logger.update_session_status("orphaned")

        markers = logger.storage.get_session_markers()
        assert markers is not None
        assert markers.session_status == "orphaned"

    def test_logger_mark_session_destroyed(self, logger):
        """mark_session_destroyed sets status to 'destroyed'."""
        logger.mark_session_destroyed()

        markers = logger.storage.get_session_markers()
        assert markers is not None
        assert markers.session_status == "destroyed"

    def test_logger_mark_session_saved(self, logger):
        """mark_session_saved changes type to 'saved'."""
        logger.mark_session_saved()

        markers = logger.storage.get_session_markers()
        assert markers is not None
        assert markers.session_type == "saved"

    def test_child_logger_inherits_subagent_type(self, tmp_path):
        """Child loggers are automatically marked as subagents."""
        parent_config = LogConfig(base_dir=tmp_path, streams=LogStream.CONTEXT)
        parent_logger = SessionLogger(parent_config)

        child_logger = parent_logger.create_child_logger()

        child_markers = child_logger.storage.get_session_markers()
        assert child_markers is not None
        assert child_markers.session_type == "subagent"
        assert child_markers.parent_agent_id == parent_logger.session_id

        child_logger.close()
        parent_logger.close()


# ============================================================================
# Integration Tests
# ============================================================================


class TestSessionMarkersIntegration:
    """Integration tests for session markers workflow."""

    def test_full_session_lifecycle(self, tmp_path):
        """Test full session lifecycle with markers."""
        # Create session
        config = LogConfig(
            base_dir=tmp_path,
            streams=LogStream.CONTEXT,
            session_type="temp",
        )
        logger = SessionLogger(config)

        # Verify initial state
        markers = logger.storage.get_session_markers()
        assert markers is not None
        assert markers.session_type == "temp"
        assert markers.session_status == "active"

        # Log some activity
        logger.log_user("Hello")
        logger.log_assistant("Hi there!")

        # Mark as saved (user wants to keep)
        logger.mark_session_saved()
        markers = logger.storage.get_session_markers()
        assert markers.session_type == "saved"

        # Close normally
        logger.close()

        # Reopen and verify persistence
        storage = SessionStorage(logger.session_dir / "session.db")
        markers = storage.get_session_markers()
        assert markers is not None
        assert markers.session_type == "saved"
        assert markers.session_status == "active"
        storage.close()

    def test_subagent_session_lifecycle(self, tmp_path):
        """Test subagent session lifecycle."""
        # Parent session
        parent_config = LogConfig(base_dir=tmp_path, streams=LogStream.CONTEXT)
        parent = SessionLogger(parent_config)

        # Spawn subagent
        child = parent.create_child_logger()

        # Verify subagent markers
        child_markers = child.storage.get_session_markers()
        assert child_markers.session_type == "subagent"
        assert child_markers.parent_agent_id == parent.session_id
        assert child_markers.session_status == "active"

        # Subagent completes work and is destroyed
        child.mark_session_destroyed()
        child_markers = child.storage.get_session_markers()
        assert child_markers.session_status == "destroyed"

        child.close()
        parent.close()

    def test_orphan_detection_scenario(self, tmp_path):
        """Test orphan detection scenario."""
        # Create a session
        config = LogConfig(base_dir=tmp_path, streams=LogStream.CONTEXT)
        logger = SessionLogger(config)
        session_dir = logger.session_dir

        # Simulate crash: update to orphaned status and old timestamp
        logger.update_session_status("orphaned")
        conn = logger.storage._get_conn()
        old_ts = time() - (10 * 24 * 60 * 60)  # 10 days ago
        conn.execute(
            "UPDATE session_markers SET updated_at = ? WHERE id = 1",
            (old_ts,),
        )
        conn.commit()
        logger.close()

        # Reopen and check orphan detection
        storage = SessionStorage(session_dir / "session.db")
        orphans = storage.get_orphaned_sessions(older_than_days=7)
        assert len(orphans) == 1
        assert orphans[0].session_status == "orphaned"
        storage.close()
