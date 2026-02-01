"""Tests for clipboard storage module."""

import time

import pytest

from nexus3.clipboard.storage import ClipboardStorage
from nexus3.clipboard.types import ClipboardEntry, ClipboardScope


@pytest.fixture
def storage(tmp_path) -> ClipboardStorage:
    """Create a temporary ClipboardStorage for testing."""
    db_path = tmp_path / ".nexus3" / "clipboard.db"
    storage = ClipboardStorage(db_path, ClipboardScope.PROJECT)
    yield storage
    storage.close()


class TestClipboardStorageBasic:
    """Tests for basic ClipboardStorage operations."""

    def test_create_storage(self, tmp_path) -> None:
        """ClipboardStorage creates database file and tables."""
        db_path = tmp_path / ".nexus3" / "clipboard.db"
        storage = ClipboardStorage(db_path, ClipboardScope.PROJECT)

        # Database file should exist
        assert db_path.exists()
        storage.close()

    def test_create_and_get_entry(self, storage: ClipboardStorage) -> None:
        """create() adds entry and get() retrieves it."""
        entry = ClipboardEntry.from_content(
            key="test-key",
            scope=ClipboardScope.PROJECT,
            content="test content",
            short_description="A test entry",
            source_path="/path/to/file.txt",
            source_lines="1-10",
            agent_id="test-agent",
        )

        storage.create(entry)
        retrieved = storage.get("test-key")

        assert retrieved is not None
        assert retrieved.key == "test-key"
        assert retrieved.content == "test content"
        assert retrieved.short_description == "A test entry"
        assert retrieved.source_path == "/path/to/file.txt"
        assert retrieved.source_lines == "1-10"
        assert retrieved.created_by_agent == "test-agent"
        assert retrieved.line_count == 1
        assert retrieved.byte_count == 12  # len("test content")

    def test_get_nonexistent_returns_none(self, storage: ClipboardStorage) -> None:
        """get() returns None for nonexistent key."""
        result = storage.get("nonexistent")
        assert result is None

    def test_exists_true(self, storage: ClipboardStorage) -> None:
        """exists() returns True for existing key."""
        entry = ClipboardEntry.from_content(
            key="exists-test",
            scope=ClipboardScope.PROJECT,
            content="data",
        )
        storage.create(entry)

        assert storage.exists("exists-test") is True

    def test_exists_false(self, storage: ClipboardStorage) -> None:
        """exists() returns False for nonexistent key."""
        assert storage.exists("nonexistent") is False


class TestClipboardStorageConstraints:
    """Tests for storage constraints and error handling."""

    def test_create_duplicate_key_raises(self, storage: ClipboardStorage) -> None:
        """create() raises ValueError for duplicate key."""
        entry1 = ClipboardEntry.from_content(
            key="duplicate",
            scope=ClipboardScope.PROJECT,
            content="first",
        )
        entry2 = ClipboardEntry.from_content(
            key="duplicate",
            scope=ClipboardScope.PROJECT,
            content="second",
        )

        storage.create(entry1)

        with pytest.raises(ValueError) as exc_info:
            storage.create(entry2)
        assert "already exists" in str(exc_info.value)

    def test_update_nonexistent_raises(self, storage: ClipboardStorage) -> None:
        """update() raises KeyError for nonexistent key."""
        with pytest.raises(KeyError) as exc_info:
            storage.update("nonexistent", content="new content")
        assert "not found" in str(exc_info.value)


class TestClipboardStorageUpdate:
    """Tests for update operations."""

    def test_update_content(self, storage: ClipboardStorage) -> None:
        """update() can change content."""
        entry = ClipboardEntry.from_content(
            key="update-test",
            scope=ClipboardScope.PROJECT,
            content="original",
        )
        storage.create(entry)

        updated = storage.update("update-test", content="modified")

        assert updated.content == "modified"
        assert updated.line_count == 1
        assert updated.byte_count == 8

    def test_update_description(self, storage: ClipboardStorage) -> None:
        """update() can change short_description."""
        entry = ClipboardEntry.from_content(
            key="update-test",
            scope=ClipboardScope.PROJECT,
            content="data",
        )
        storage.create(entry)

        updated = storage.update("update-test", short_description="New description")

        assert updated.short_description == "New description"

    def test_update_modified_at(self, storage: ClipboardStorage) -> None:
        """update() changes modified_at timestamp."""
        entry = ClipboardEntry.from_content(
            key="update-test",
            scope=ClipboardScope.PROJECT,
            content="data",
        )
        storage.create(entry)
        original_modified = entry.modified_at

        time.sleep(0.01)  # Ensure time difference
        updated = storage.update("update-test", content="new data")

        assert updated.modified_at > original_modified

    def test_update_agent_id(self, storage: ClipboardStorage) -> None:
        """update() sets modified_by_agent."""
        entry = ClipboardEntry.from_content(
            key="update-test",
            scope=ClipboardScope.PROJECT,
            content="data",
            agent_id="agent-1",
        )
        storage.create(entry)

        updated = storage.update("update-test", content="new", agent_id="agent-2")

        assert updated.created_by_agent == "agent-1"
        assert updated.modified_by_agent == "agent-2"

    def test_update_rename_key(self, storage: ClipboardStorage) -> None:
        """update() can rename the key."""
        entry = ClipboardEntry.from_content(
            key="old-name",
            scope=ClipboardScope.PROJECT,
            content="data",
        )
        storage.create(entry)

        updated = storage.update("old-name", new_key="new-name")

        assert updated.key == "new-name"
        assert storage.get("old-name") is None
        assert storage.get("new-name") is not None

    def test_update_rename_to_existing_raises(self, storage: ClipboardStorage) -> None:
        """update() raises ValueError when renaming to existing key."""
        entry1 = ClipboardEntry.from_content(
            key="key1",
            scope=ClipboardScope.PROJECT,
            content="data1",
        )
        entry2 = ClipboardEntry.from_content(
            key="key2",
            scope=ClipboardScope.PROJECT,
            content="data2",
        )
        storage.create(entry1)
        storage.create(entry2)

        with pytest.raises(ValueError) as exc_info:
            storage.update("key1", new_key="key2")
        assert "already exists" in str(exc_info.value)

    def test_update_ttl(self, storage: ClipboardStorage) -> None:
        """update() can set ttl_seconds and expires_at."""
        entry = ClipboardEntry.from_content(
            key="ttl-test",
            scope=ClipboardScope.PROJECT,
            content="data",
        )
        storage.create(entry)

        before = time.time()
        updated = storage.update("ttl-test", ttl_seconds=3600)
        after = time.time()

        assert updated.ttl_seconds == 3600
        assert updated.expires_at is not None
        assert before + 3600 <= updated.expires_at <= after + 3600


class TestClipboardStorageDelete:
    """Tests for delete operations."""

    def test_delete_existing(self, storage: ClipboardStorage) -> None:
        """delete() removes existing entry and returns True."""
        entry = ClipboardEntry.from_content(
            key="delete-me",
            scope=ClipboardScope.PROJECT,
            content="data",
        )
        storage.create(entry)

        result = storage.delete("delete-me")

        assert result is True
        assert storage.get("delete-me") is None

    def test_delete_nonexistent(self, storage: ClipboardStorage) -> None:
        """delete() returns False for nonexistent key."""
        result = storage.delete("nonexistent")
        assert result is False

    def test_clear_all(self, storage: ClipboardStorage) -> None:
        """clear() removes all entries and returns count."""
        for i in range(5):
            entry = ClipboardEntry.from_content(
                key=f"entry-{i}",
                scope=ClipboardScope.PROJECT,
                content=f"data-{i}",
            )
            storage.create(entry)

        count = storage.clear()

        assert count == 5
        assert len(storage.list_all()) == 0

    def test_clear_empty(self, storage: ClipboardStorage) -> None:
        """clear() returns 0 when storage is empty."""
        count = storage.clear()
        assert count == 0


class TestClipboardStorageList:
    """Tests for list operations."""

    def test_list_all_empty(self, storage: ClipboardStorage) -> None:
        """list_all() returns empty list when no entries."""
        entries = storage.list_all()
        assert entries == []

    def test_list_all_returns_entries(self, storage: ClipboardStorage) -> None:
        """list_all() returns all entries."""
        for i in range(3):
            entry = ClipboardEntry.from_content(
                key=f"entry-{i}",
                scope=ClipboardScope.PROJECT,
                content=f"data-{i}",
            )
            storage.create(entry)

        entries = storage.list_all()

        assert len(entries) == 3
        keys = {e.key for e in entries}
        assert keys == {"entry-0", "entry-1", "entry-2"}

    def test_list_all_sorted_by_modified_at_desc(
        self, storage: ClipboardStorage
    ) -> None:
        """list_all() returns entries sorted by modified_at descending."""
        for i in range(3):
            entry = ClipboardEntry.from_content(
                key=f"entry-{i}",
                scope=ClipboardScope.PROJECT,
                content=f"data-{i}",
            )
            storage.create(entry)
            time.sleep(0.01)  # Ensure different timestamps

        entries = storage.list_all()

        # Most recently modified first
        assert entries[0].key == "entry-2"
        assert entries[1].key == "entry-1"
        assert entries[2].key == "entry-0"


class TestClipboardStorageTags:
    """Tests for tag operations."""

    def test_set_tags(self, storage: ClipboardStorage) -> None:
        """set_tags() adds tags to entry."""
        entry = ClipboardEntry.from_content(
            key="tagged",
            scope=ClipboardScope.PROJECT,
            content="data",
        )
        storage.create(entry)

        storage.set_tags("tagged", ["python", "code"])
        tags = storage.get_tags("tagged")

        assert set(tags) == {"python", "code"}

    def test_get_tags_empty(self, storage: ClipboardStorage) -> None:
        """get_tags() returns empty list when no tags."""
        entry = ClipboardEntry.from_content(
            key="untagged",
            scope=ClipboardScope.PROJECT,
            content="data",
        )
        storage.create(entry)

        tags = storage.get_tags("untagged")

        assert tags == []

    def test_set_tags_replaces_existing(self, storage: ClipboardStorage) -> None:
        """set_tags() replaces all existing tags."""
        entry = ClipboardEntry.from_content(
            key="tagged",
            scope=ClipboardScope.PROJECT,
            content="data",
        )
        storage.create(entry)

        storage.set_tags("tagged", ["old1", "old2"])
        storage.set_tags("tagged", ["new1", "new2", "new3"])
        tags = storage.get_tags("tagged")

        assert set(tags) == {"new1", "new2", "new3"}

    def test_set_tags_nonexistent_key_raises(self, storage: ClipboardStorage) -> None:
        """set_tags() raises KeyError for nonexistent entry."""
        with pytest.raises(KeyError) as exc_info:
            storage.set_tags("nonexistent", ["tag"])
        assert "not found" in str(exc_info.value)

    def test_tags_included_in_get(self, storage: ClipboardStorage) -> None:
        """get() returns entry with tags populated."""
        entry = ClipboardEntry.from_content(
            key="tagged",
            scope=ClipboardScope.PROJECT,
            content="data",
            tags=["initial"],
        )
        storage.create(entry)
        storage.set_tags("tagged", ["final1", "final2"])

        retrieved = storage.get("tagged")

        assert retrieved is not None
        assert set(retrieved.tags) == {"final1", "final2"}

    def test_tags_cascade_delete(self, storage: ClipboardStorage) -> None:
        """Deleting entry removes associated tag links (ON DELETE CASCADE)."""
        entry = ClipboardEntry.from_content(
            key="cascade-test",
            scope=ClipboardScope.PROJECT,
            content="data",
        )
        storage.create(entry)
        storage.set_tags("cascade-test", ["tag1", "tag2"])

        # Delete the entry
        storage.delete("cascade-test")

        # Entry and tag associations should be gone
        assert storage.get("cascade-test") is None


class TestClipboardStorageTTL:
    """Tests for TTL/expiration operations."""

    def test_create_with_ttl(self, storage: ClipboardStorage) -> None:
        """create() stores TTL and expires_at."""
        entry = ClipboardEntry.from_content(
            key="ttl-test",
            scope=ClipboardScope.PROJECT,
            content="data",
            ttl_seconds=3600,
        )
        storage.create(entry)

        retrieved = storage.get("ttl-test")

        assert retrieved is not None
        assert retrieved.ttl_seconds == 3600
        assert retrieved.expires_at is not None

    def test_count_expired_none(self, storage: ClipboardStorage) -> None:
        """count_expired() returns 0 when no expired entries."""
        entry = ClipboardEntry.from_content(
            key="not-expired",
            scope=ClipboardScope.PROJECT,
            content="data",
            ttl_seconds=3600,  # 1 hour from now
        )
        storage.create(entry)

        count = storage.count_expired(time.time())

        assert count == 0

    def test_count_expired_some(self, storage: ClipboardStorage) -> None:
        """count_expired() returns count of expired entries."""
        now = time.time()

        # Create expired entry (expires 1 second ago)
        expired_entry = ClipboardEntry(
            key="expired",
            scope=ClipboardScope.PROJECT,
            content="data",
            line_count=1,
            byte_count=4,
            created_at=now - 3600,
            modified_at=now - 3600,
            expires_at=now - 1,
        )
        storage.create(expired_entry)

        # Create non-expired entry (expires in 1 hour)
        valid_entry = ClipboardEntry.from_content(
            key="valid",
            scope=ClipboardScope.PROJECT,
            content="data",
            ttl_seconds=3600,
        )
        storage.create(valid_entry)

        count = storage.count_expired(now)

        assert count == 1

    def test_get_expired(self, storage: ClipboardStorage) -> None:
        """get_expired() returns list of expired entries."""
        now = time.time()

        # Create expired entries
        for i in range(3):
            expired_entry = ClipboardEntry(
                key=f"expired-{i}",
                scope=ClipboardScope.PROJECT,
                content="data",
                line_count=1,
                byte_count=4,
                created_at=now - 3600,
                modified_at=now - 3600,
                expires_at=now - 10 + i,  # All expired
            )
            storage.create(expired_entry)

        # Create non-expired entry
        valid_entry = ClipboardEntry.from_content(
            key="valid",
            scope=ClipboardScope.PROJECT,
            content="data",
            ttl_seconds=3600,
        )
        storage.create(valid_entry)

        expired = storage.get_expired(now)

        assert len(expired) == 3
        expired_keys = {e.key for e in expired}
        assert expired_keys == {"expired-0", "expired-1", "expired-2"}

    def test_get_expired_sorted_by_expires_at(self, storage: ClipboardStorage) -> None:
        """get_expired() returns entries sorted by expires_at."""
        now = time.time()

        # Create entries with different expiry times
        for i, offset in enumerate([5, 1, 3]):  # Out of order
            entry = ClipboardEntry(
                key=f"entry-{i}",
                scope=ClipboardScope.PROJECT,
                content="data",
                line_count=1,
                byte_count=4,
                created_at=now - 100,
                modified_at=now - 100,
                expires_at=now - 10 + offset,
            )
            storage.create(entry)

        expired = storage.get_expired(now)

        # Should be sorted by expires_at ascending
        assert len(expired) == 3
        assert expired[0].key == "entry-1"  # offset=1, expired earliest
        assert expired[1].key == "entry-2"  # offset=3
        assert expired[2].key == "entry-0"  # offset=5, expired most recently

    def test_permanent_entries_not_expired(self, storage: ClipboardStorage) -> None:
        """Entries without expires_at are never expired."""
        entry = ClipboardEntry.from_content(
            key="permanent",
            scope=ClipboardScope.PROJECT,
            content="data",
            # No ttl_seconds = permanent
        )
        storage.create(entry)

        # Far future time
        count = storage.count_expired(time.time() + 1000000)
        expired = storage.get_expired(time.time() + 1000000)

        assert count == 0
        assert expired == []


class TestClipboardStorageClose:
    """Tests for storage cleanup."""

    def test_close_idempotent(self, tmp_path) -> None:
        """close() can be called multiple times safely."""
        db_path = tmp_path / ".nexus3" / "clipboard.db"
        storage = ClipboardStorage(db_path, ClipboardScope.PROJECT)

        storage.close()
        storage.close()  # Should not raise
