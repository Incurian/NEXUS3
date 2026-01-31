"""Tests for clipboard manager module."""

import time

import pytest

from nexus3.clipboard.manager import ClipboardManager
from nexus3.clipboard.types import (
    CLIPBOARD_PRESETS,
    ClipboardEntry,
    ClipboardPermissions,
    ClipboardScope,
)


@pytest.fixture
def tmp_dirs(tmp_path):
    """Create temp directories for home and cwd."""
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    cwd = tmp_path / "project"
    cwd.mkdir()
    return home_dir, cwd


@pytest.fixture
def yolo_manager(tmp_dirs) -> ClipboardManager:
    """Create manager with full permissions (yolo)."""
    home_dir, cwd = tmp_dirs
    manager = ClipboardManager(
        agent_id="test-agent",
        cwd=cwd,
        permissions=CLIPBOARD_PRESETS["yolo"],
        home_dir=home_dir,
    )
    yield manager
    manager.close()


@pytest.fixture
def trusted_manager(tmp_dirs) -> ClipboardManager:
    """Create manager with trusted permissions."""
    home_dir, cwd = tmp_dirs
    manager = ClipboardManager(
        agent_id="test-agent",
        cwd=cwd,
        permissions=CLIPBOARD_PRESETS["trusted"],
        home_dir=home_dir,
    )
    yield manager
    manager.close()


@pytest.fixture
def sandboxed_manager(tmp_dirs) -> ClipboardManager:
    """Create manager with sandboxed permissions (agent-only)."""
    home_dir, cwd = tmp_dirs
    manager = ClipboardManager(
        agent_id="test-agent",
        cwd=cwd,
        permissions=CLIPBOARD_PRESETS["sandboxed"],
        home_dir=home_dir,
    )
    yield manager
    manager.close()


class TestClipboardManagerCopy:
    """Tests for copy operations."""

    def test_copy_to_agent_scope(self, yolo_manager: ClipboardManager) -> None:
        """copy() to agent scope stores in memory."""
        entry, warning = yolo_manager.copy(
            key="test",
            content="hello world",
            scope=ClipboardScope.AGENT,
        )

        assert entry.key == "test"
        assert entry.content == "hello world"
        assert entry.scope == ClipboardScope.AGENT
        assert warning is None

    def test_copy_to_project_scope(self, yolo_manager: ClipboardManager) -> None:
        """copy() to project scope stores in project database."""
        entry, warning = yolo_manager.copy(
            key="project-test",
            content="project data",
            scope=ClipboardScope.PROJECT,
        )

        assert entry.key == "project-test"
        assert entry.scope == ClipboardScope.PROJECT

        # Verify persisted
        retrieved = yolo_manager.get("project-test", scope=ClipboardScope.PROJECT)
        assert retrieved is not None
        assert retrieved.content == "project data"

    def test_copy_to_system_scope(self, yolo_manager: ClipboardManager) -> None:
        """copy() to system scope stores in system database."""
        entry, warning = yolo_manager.copy(
            key="system-test",
            content="system data",
            scope=ClipboardScope.SYSTEM,
        )

        assert entry.key == "system-test"
        assert entry.scope == ClipboardScope.SYSTEM

        # Verify persisted
        retrieved = yolo_manager.get("system-test", scope=ClipboardScope.SYSTEM)
        assert retrieved is not None
        assert retrieved.content == "system data"

    def test_copy_with_metadata(self, yolo_manager: ClipboardManager) -> None:
        """copy() preserves metadata fields."""
        entry, _ = yolo_manager.copy(
            key="metadata-test",
            content="def foo(): pass",
            scope=ClipboardScope.AGENT,
            short_description="A function",
            source_path="/path/to/file.py",
            source_lines="10-15",
            tags=["python", "function"],
            ttl_seconds=3600,
        )

        assert entry.short_description == "A function"
        assert entry.source_path == "/path/to/file.py"
        assert entry.source_lines == "10-15"
        assert entry.tags == ["python", "function"]
        assert entry.ttl_seconds == 3600
        assert entry.expires_at is not None

    def test_copy_duplicate_key_raises(self, yolo_manager: ClipboardManager) -> None:
        """copy() raises ValueError for duplicate key in same scope."""
        yolo_manager.copy(
            key="duplicate",
            content="first",
            scope=ClipboardScope.AGENT,
        )

        with pytest.raises(ValueError) as exc_info:
            yolo_manager.copy(
                key="duplicate",
                content="second",
                scope=ClipboardScope.AGENT,
            )
        assert "already exists" in str(exc_info.value)

    def test_copy_same_key_different_scopes(
        self, yolo_manager: ClipboardManager
    ) -> None:
        """copy() allows same key in different scopes."""
        yolo_manager.copy("shared-key", "agent data", ClipboardScope.AGENT)
        yolo_manager.copy("shared-key", "project data", ClipboardScope.PROJECT)
        yolo_manager.copy("shared-key", "system data", ClipboardScope.SYSTEM)

        # All should exist
        agent = yolo_manager.get("shared-key", ClipboardScope.AGENT)
        project = yolo_manager.get("shared-key", ClipboardScope.PROJECT)
        system = yolo_manager.get("shared-key", ClipboardScope.SYSTEM)

        assert agent.content == "agent data"
        assert project.content == "project data"
        assert system.content == "system data"

    def test_copy_large_content_warning(self, yolo_manager: ClipboardManager) -> None:
        """copy() returns warning for large content."""
        large_content = "x" * (100 * 1024 + 1)  # Just over 100KB

        entry, warning = yolo_manager.copy(
            key="large",
            content=large_content,
            scope=ClipboardScope.AGENT,
        )

        assert warning is not None
        assert "Large clipboard entry" in warning

    def test_copy_oversized_content_raises(
        self, yolo_manager: ClipboardManager
    ) -> None:
        """copy() raises ValueError for content over 1MB."""
        oversized_content = "x" * (1024 * 1024 + 1)  # Just over 1MB

        with pytest.raises(ValueError) as exc_info:
            yolo_manager.copy(
                key="oversized",
                content=oversized_content,
                scope=ClipboardScope.AGENT,
            )
        assert "exceeds maximum" in str(exc_info.value)


class TestClipboardManagerPermissions:
    """Tests for permission enforcement."""

    def test_sandboxed_cannot_read_project(
        self, sandboxed_manager: ClipboardManager
    ) -> None:
        """Sandboxed agents cannot read from project scope."""
        with pytest.raises(PermissionError) as exc_info:
            sandboxed_manager.get("any-key", scope=ClipboardScope.PROJECT)
        assert "No read permission" in str(exc_info.value)

    def test_sandboxed_cannot_read_system(
        self, sandboxed_manager: ClipboardManager
    ) -> None:
        """Sandboxed agents cannot read from system scope."""
        with pytest.raises(PermissionError) as exc_info:
            sandboxed_manager.get("any-key", scope=ClipboardScope.SYSTEM)
        assert "No read permission" in str(exc_info.value)

    def test_sandboxed_cannot_write_project(
        self, sandboxed_manager: ClipboardManager
    ) -> None:
        """Sandboxed agents cannot write to project scope."""
        with pytest.raises(PermissionError) as exc_info:
            sandboxed_manager.copy("key", "content", ClipboardScope.PROJECT)
        assert "No write permission" in str(exc_info.value)

    def test_sandboxed_cannot_write_system(
        self, sandboxed_manager: ClipboardManager
    ) -> None:
        """Sandboxed agents cannot write to system scope."""
        with pytest.raises(PermissionError) as exc_info:
            sandboxed_manager.copy("key", "content", ClipboardScope.SYSTEM)
        assert "No write permission" in str(exc_info.value)

    def test_sandboxed_can_use_agent_scope(
        self, sandboxed_manager: ClipboardManager
    ) -> None:
        """Sandboxed agents can read/write agent scope."""
        sandboxed_manager.copy("key", "content", ClipboardScope.AGENT)
        entry = sandboxed_manager.get("key", ClipboardScope.AGENT)

        assert entry is not None
        assert entry.content == "content"

    def test_trusted_can_read_system(self, trusted_manager: ClipboardManager) -> None:
        """Trusted agents can read from system scope."""
        # First need to write via yolo permissions (create a separate manager)
        # Actually, trusted_manager can't write to system, but we're testing read
        # We can't directly test this without a yolo manager first adding data
        # So we'll test that the get doesn't raise a permission error
        result = trusted_manager.get("nonexistent", scope=ClipboardScope.SYSTEM)
        assert result is None  # Just checking no permission error

    def test_trusted_cannot_write_system(
        self, trusted_manager: ClipboardManager
    ) -> None:
        """Trusted agents cannot write to system scope."""
        with pytest.raises(PermissionError) as exc_info:
            trusted_manager.copy("key", "content", ClipboardScope.SYSTEM)
        assert "No write permission" in str(exc_info.value)

    def test_trusted_can_write_project(
        self, trusted_manager: ClipboardManager
    ) -> None:
        """Trusted agents can write to project scope."""
        entry, _ = trusted_manager.copy("key", "content", ClipboardScope.PROJECT)
        assert entry is not None


class TestClipboardManagerGet:
    """Tests for get operations."""

    def test_get_from_specific_scope(self, yolo_manager: ClipboardManager) -> None:
        """get() with scope parameter searches only that scope."""
        yolo_manager.copy("key", "agent-data", ClipboardScope.AGENT)
        yolo_manager.copy("key", "project-data", ClipboardScope.PROJECT)

        agent_entry = yolo_manager.get("key", ClipboardScope.AGENT)
        project_entry = yolo_manager.get("key", ClipboardScope.PROJECT)

        assert agent_entry.content == "agent-data"
        assert project_entry.content == "project-data"

    def test_get_search_order(self, yolo_manager: ClipboardManager) -> None:
        """get() without scope searches agent -> project -> system."""
        # Only in system
        yolo_manager.copy("system-only", "system", ClipboardScope.SYSTEM)
        result = yolo_manager.get("system-only")
        assert result.content == "system"
        assert result.scope == ClipboardScope.SYSTEM

        # In project and system - should find project first
        yolo_manager.copy("project-and-system", "system", ClipboardScope.SYSTEM)
        yolo_manager.copy("project-and-system", "project", ClipboardScope.PROJECT)
        result = yolo_manager.get("project-and-system")
        assert result.content == "project"
        assert result.scope == ClipboardScope.PROJECT

        # In agent and project - should find agent first
        yolo_manager.copy("agent-and-project", "project", ClipboardScope.PROJECT)
        yolo_manager.copy("agent-and-project", "agent", ClipboardScope.AGENT)
        result = yolo_manager.get("agent-and-project")
        assert result.content == "agent"
        assert result.scope == ClipboardScope.AGENT

    def test_get_not_found(self, yolo_manager: ClipboardManager) -> None:
        """get() returns None when key not found in any scope."""
        result = yolo_manager.get("nonexistent")
        assert result is None

    def test_get_respects_permissions(
        self, sandboxed_manager: ClipboardManager, tmp_dirs
    ) -> None:
        """get() without scope only searches accessible scopes."""
        home_dir, cwd = tmp_dirs

        # First, use yolo manager to add data to project scope
        yolo = ClipboardManager(
            agent_id="setup",
            cwd=cwd,
            permissions=CLIPBOARD_PRESETS["yolo"],
            home_dir=home_dir,
        )
        yolo.copy("key", "project-data", ClipboardScope.PROJECT)
        yolo.close()

        # Sandboxed manager should not find it (can't read project)
        result = sandboxed_manager.get("key")
        assert result is None


class TestClipboardManagerListEntries:
    """Tests for list_entries operations."""

    def test_list_entries_all_scopes(self, yolo_manager: ClipboardManager) -> None:
        """list_entries() returns entries from all accessible scopes."""
        yolo_manager.copy("agent-1", "a1", ClipboardScope.AGENT)
        yolo_manager.copy("project-1", "p1", ClipboardScope.PROJECT)
        yolo_manager.copy("system-1", "s1", ClipboardScope.SYSTEM)

        entries = yolo_manager.list_entries()

        assert len(entries) == 3
        keys = {e.key for e in entries}
        assert keys == {"agent-1", "project-1", "system-1"}

    def test_list_entries_specific_scope(
        self, yolo_manager: ClipboardManager
    ) -> None:
        """list_entries() with scope filters to that scope."""
        yolo_manager.copy("agent-1", "a1", ClipboardScope.AGENT)
        yolo_manager.copy("project-1", "p1", ClipboardScope.PROJECT)

        entries = yolo_manager.list_entries(scope=ClipboardScope.AGENT)

        assert len(entries) == 1
        assert entries[0].key == "agent-1"

    def test_list_entries_sorted_by_modified_at(
        self, yolo_manager: ClipboardManager
    ) -> None:
        """list_entries() returns entries sorted by modified_at desc."""
        yolo_manager.copy("first", "1", ClipboardScope.AGENT)
        time.sleep(0.01)
        yolo_manager.copy("second", "2", ClipboardScope.AGENT)
        time.sleep(0.01)
        yolo_manager.copy("third", "3", ClipboardScope.AGENT)

        entries = yolo_manager.list_entries(scope=ClipboardScope.AGENT)

        assert entries[0].key == "third"
        assert entries[1].key == "second"
        assert entries[2].key == "first"

    def test_list_entries_filter_by_tags_and(
        self, yolo_manager: ClipboardManager
    ) -> None:
        """list_entries() with tags filters by ALL tags (AND logic)."""
        yolo_manager.copy("py-func", "f", ClipboardScope.AGENT, tags=["python", "func"])
        yolo_manager.copy("py-class", "c", ClipboardScope.AGENT, tags=["python", "class"])
        yolo_manager.copy("js-func", "j", ClipboardScope.AGENT, tags=["js", "func"])

        # Filter by python AND func
        entries = yolo_manager.list_entries(tags=["python", "func"])

        assert len(entries) == 1
        assert entries[0].key == "py-func"

    def test_list_entries_filter_by_any_tags(
        self, yolo_manager: ClipboardManager
    ) -> None:
        """list_entries() with any_tags filters by ANY tag (OR logic)."""
        yolo_manager.copy("py-func", "f", ClipboardScope.AGENT, tags=["python", "func"])
        yolo_manager.copy("py-class", "c", ClipboardScope.AGENT, tags=["python", "class"])
        yolo_manager.copy("js-func", "j", ClipboardScope.AGENT, tags=["js", "func"])
        yolo_manager.copy("rust", "r", ClipboardScope.AGENT, tags=["rust"])

        # Filter by python OR class (should match first two)
        entries = yolo_manager.list_entries(any_tags=["python", "class"])

        assert len(entries) == 2
        keys = {e.key for e in entries}
        assert keys == {"py-func", "py-class"}

    def test_list_entries_exclude_expired(
        self, yolo_manager: ClipboardManager
    ) -> None:
        """list_entries() with include_expired=False excludes expired entries."""
        now = time.time()

        # Add valid entry
        yolo_manager.copy("valid", "v", ClipboardScope.AGENT, ttl_seconds=3600)

        # Add expired entry directly to agent clipboard
        expired = ClipboardEntry(
            key="expired",
            scope=ClipboardScope.AGENT,
            content="e",
            line_count=1,
            byte_count=1,
            expires_at=now - 1,
        )
        yolo_manager._agent_clipboard["expired"] = expired

        # With expired
        all_entries = yolo_manager.list_entries(include_expired=True)
        assert len(all_entries) == 2

        # Without expired
        valid_entries = yolo_manager.list_entries(include_expired=False)
        assert len(valid_entries) == 1
        assert valid_entries[0].key == "valid"

    def test_list_entries_respects_permissions(
        self, sandboxed_manager: ClipboardManager
    ) -> None:
        """list_entries() only returns entries from accessible scopes."""
        sandboxed_manager.copy("agent-only", "a", ClipboardScope.AGENT)

        # List without scope should only return agent entries
        entries = sandboxed_manager.list_entries()

        assert len(entries) == 1
        assert entries[0].scope == ClipboardScope.AGENT


class TestClipboardManagerSearch:
    """Tests for search operations."""

    def test_search_by_key(self, yolo_manager: ClipboardManager) -> None:
        """search() finds entries by key match."""
        yolo_manager.copy("python-func", "code", ClipboardScope.AGENT)
        yolo_manager.copy("javascript-func", "code", ClipboardScope.AGENT)
        yolo_manager.copy("rust-struct", "code", ClipboardScope.AGENT)

        results = yolo_manager.search("python")

        assert len(results) == 1
        assert results[0].key == "python-func"

    def test_search_by_description(self, yolo_manager: ClipboardManager) -> None:
        """search() finds entries by description match."""
        yolo_manager.copy(
            "entry1", "code", ClipboardScope.AGENT, short_description="A utility function"
        )
        yolo_manager.copy(
            "entry2", "code", ClipboardScope.AGENT, short_description="A data class"
        )

        results = yolo_manager.search("utility")

        assert len(results) == 1
        assert results[0].key == "entry1"

    def test_search_by_content(self, yolo_manager: ClipboardManager) -> None:
        """search() finds entries by content match."""
        yolo_manager.copy("entry1", "def calculate():", ClipboardScope.AGENT)
        yolo_manager.copy("entry2", "class DataModel:", ClipboardScope.AGENT)

        results = yolo_manager.search("calculate")

        assert len(results) == 1
        assert results[0].key == "entry1"

    def test_search_case_insensitive(self, yolo_manager: ClipboardManager) -> None:
        """search() is case-insensitive."""
        yolo_manager.copy("UPPERCASE", "content", ClipboardScope.AGENT)

        results = yolo_manager.search("uppercase")

        assert len(results) == 1

    def test_search_with_tag_filter(self, yolo_manager: ClipboardManager) -> None:
        """search() with tags filters results."""
        yolo_manager.copy("py1", "python code", ClipboardScope.AGENT, tags=["python"])
        yolo_manager.copy("py2", "python snippet", ClipboardScope.AGENT, tags=["python"])
        yolo_manager.copy("js1", "python polyfill", ClipboardScope.AGENT, tags=["js"])

        # Search for "python" but only in python-tagged entries
        results = yolo_manager.search("python", tags=["python"])

        assert len(results) == 2
        keys = {r.key for r in results}
        assert keys == {"py1", "py2"}

    def test_search_specific_scope(self, yolo_manager: ClipboardManager) -> None:
        """search() with scope only searches that scope."""
        yolo_manager.copy("key", "same content", ClipboardScope.AGENT)
        yolo_manager.copy("key", "same content", ClipboardScope.PROJECT)

        results = yolo_manager.search("same", scope=ClipboardScope.AGENT)

        assert len(results) == 1
        assert results[0].scope == ClipboardScope.AGENT

    def test_search_disable_content_search(
        self, yolo_manager: ClipboardManager
    ) -> None:
        """search() with search_content=False skips content."""
        yolo_manager.copy("my-key", "hidden treasure", ClipboardScope.AGENT)

        results = yolo_manager.search("treasure", search_content=False)

        assert len(results) == 0

    def test_search_disable_key_search(self, yolo_manager: ClipboardManager) -> None:
        """search() with search_keys=False skips keys."""
        yolo_manager.copy("treasure-key", "no match", ClipboardScope.AGENT)

        results = yolo_manager.search("treasure", search_keys=False)

        assert len(results) == 0


class TestClipboardManagerTags:
    """Tests for tag management operations."""

    def test_add_tags(self, yolo_manager: ClipboardManager) -> None:
        """add_tags() adds tags to entry."""
        yolo_manager.copy("entry", "content", ClipboardScope.AGENT, tags=["initial"])

        entry = yolo_manager.add_tags("entry", ClipboardScope.AGENT, ["new1", "new2"])

        assert set(entry.tags) == {"initial", "new1", "new2"}

    def test_add_tags_no_duplicates(self, yolo_manager: ClipboardManager) -> None:
        """add_tags() doesn't create duplicate tags."""
        yolo_manager.copy("entry", "content", ClipboardScope.AGENT, tags=["existing"])

        entry = yolo_manager.add_tags("entry", ClipboardScope.AGENT, ["existing", "new"])

        assert sorted(entry.tags) == ["existing", "new"]

    def test_remove_tags(self, yolo_manager: ClipboardManager) -> None:
        """remove_tags() removes specified tags."""
        yolo_manager.copy(
            "entry", "content", ClipboardScope.AGENT, tags=["keep", "remove1", "remove2"]
        )

        entry = yolo_manager.remove_tags(
            "entry", ClipboardScope.AGENT, ["remove1", "remove2"]
        )

        assert entry.tags == ["keep"]

    def test_remove_tags_nonexistent(self, yolo_manager: ClipboardManager) -> None:
        """remove_tags() silently ignores nonexistent tags."""
        yolo_manager.copy("entry", "content", ClipboardScope.AGENT, tags=["existing"])

        entry = yolo_manager.remove_tags(
            "entry", ClipboardScope.AGENT, ["nonexistent"]
        )

        assert entry.tags == ["existing"]

    def test_list_tags(self, yolo_manager: ClipboardManager) -> None:
        """list_tags() returns all unique tags in use."""
        yolo_manager.copy("e1", "c", ClipboardScope.AGENT, tags=["python", "func"])
        yolo_manager.copy("e2", "c", ClipboardScope.AGENT, tags=["python", "class"])
        yolo_manager.copy("e3", "c", ClipboardScope.AGENT, tags=["js"])

        tags = yolo_manager.list_tags()

        assert set(tags) == {"python", "func", "class", "js"}

    def test_list_tags_specific_scope(self, yolo_manager: ClipboardManager) -> None:
        """list_tags() with scope only returns tags from that scope."""
        yolo_manager.copy("agent", "c", ClipboardScope.AGENT, tags=["agent-tag"])
        yolo_manager.copy("project", "c", ClipboardScope.PROJECT, tags=["project-tag"])

        agent_tags = yolo_manager.list_tags(scope=ClipboardScope.AGENT)
        project_tags = yolo_manager.list_tags(scope=ClipboardScope.PROJECT)

        assert agent_tags == ["agent-tag"]
        assert project_tags == ["project-tag"]

    def test_add_tags_nonexistent_key_raises(
        self, yolo_manager: ClipboardManager
    ) -> None:
        """add_tags() raises KeyError for nonexistent entry."""
        with pytest.raises(KeyError) as exc_info:
            yolo_manager.add_tags("nonexistent", ClipboardScope.AGENT, ["tag"])
        assert "not found" in str(exc_info.value)

    def test_tag_operations_check_permissions(
        self, sandboxed_manager: ClipboardManager
    ) -> None:
        """Tag operations check write permissions."""
        with pytest.raises(PermissionError):
            sandboxed_manager.add_tags("key", ClipboardScope.PROJECT, ["tag"])

        with pytest.raises(PermissionError):
            sandboxed_manager.remove_tags("key", ClipboardScope.PROJECT, ["tag"])


class TestClipboardManagerTTL:
    """Tests for TTL/expiration operations."""

    def test_count_expired_agent(self, yolo_manager: ClipboardManager) -> None:
        """count_expired() counts expired agent entries."""
        now = time.time()

        # Add valid entry
        yolo_manager.copy("valid", "v", ClipboardScope.AGENT, ttl_seconds=3600)

        # Add expired entry directly
        expired = ClipboardEntry(
            key="expired",
            scope=ClipboardScope.AGENT,
            content="e",
            line_count=1,
            byte_count=1,
            expires_at=now - 1,
        )
        yolo_manager._agent_clipboard["expired"] = expired

        count = yolo_manager.count_expired(ClipboardScope.AGENT)

        assert count == 1

    def test_count_expired_all_scopes(self, yolo_manager: ClipboardManager) -> None:
        """count_expired() without scope counts across all accessible scopes."""
        now = time.time()

        # Add expired entries to each scope
        for scope in [ClipboardScope.AGENT, ClipboardScope.PROJECT, ClipboardScope.SYSTEM]:
            expired = ClipboardEntry(
                key=f"expired-{scope.value}",
                scope=scope,
                content="e",
                line_count=1,
                byte_count=1,
                created_at=now - 100,
                modified_at=now - 100,
                expires_at=now - 1,
            )
            if scope == ClipboardScope.AGENT:
                yolo_manager._agent_clipboard[expired.key] = expired
            elif scope == ClipboardScope.PROJECT:
                yolo_manager._get_project_storage().create(expired)
            elif scope == ClipboardScope.SYSTEM:
                yolo_manager._get_system_storage().create(expired)

        count = yolo_manager.count_expired()

        assert count == 3

    def test_get_expired(self, yolo_manager: ClipboardManager) -> None:
        """get_expired() returns list of expired entries."""
        now = time.time()

        # Add expired entries
        for i in range(3):
            expired = ClipboardEntry(
                key=f"expired-{i}",
                scope=ClipboardScope.AGENT,
                content="e",
                line_count=1,
                byte_count=1,
                expires_at=now - 10 + i,
            )
            yolo_manager._agent_clipboard[expired.key] = expired

        # Add valid entry
        yolo_manager.copy("valid", "v", ClipboardScope.AGENT, ttl_seconds=3600)

        expired_list = yolo_manager.get_expired()

        assert len(expired_list) == 3
        expired_keys = {e.key for e in expired_list}
        assert expired_keys == {"expired-0", "expired-1", "expired-2"}


class TestClipboardManagerUpdate:
    """Tests for update operations."""

    def test_update_content(self, yolo_manager: ClipboardManager) -> None:
        """update() can change content."""
        yolo_manager.copy("entry", "original", ClipboardScope.AGENT)

        updated, warning = yolo_manager.update(
            "entry",
            ClipboardScope.AGENT,
            content="modified",
        )

        assert updated.content == "modified"
        assert warning is None

    def test_update_nonexistent_raises(self, yolo_manager: ClipboardManager) -> None:
        """update() raises KeyError for nonexistent entry."""
        with pytest.raises(KeyError) as exc_info:
            yolo_manager.update(
                "nonexistent",
                ClipboardScope.AGENT,
                content="new",
            )
        assert "not found" in str(exc_info.value)

    def test_update_checks_permissions(
        self, sandboxed_manager: ClipboardManager
    ) -> None:
        """update() checks write permissions."""
        with pytest.raises(PermissionError):
            sandboxed_manager.update("key", ClipboardScope.PROJECT, content="new")


class TestClipboardManagerDelete:
    """Tests for delete operations."""

    def test_delete_existing(self, yolo_manager: ClipboardManager) -> None:
        """delete() removes entry and returns True."""
        yolo_manager.copy("entry", "content", ClipboardScope.AGENT)

        result = yolo_manager.delete("entry", ClipboardScope.AGENT)

        assert result is True
        assert yolo_manager.get("entry", ClipboardScope.AGENT) is None

    def test_delete_nonexistent(self, yolo_manager: ClipboardManager) -> None:
        """delete() returns False for nonexistent key."""
        result = yolo_manager.delete("nonexistent", ClipboardScope.AGENT)
        assert result is False

    def test_clear_scope(self, yolo_manager: ClipboardManager) -> None:
        """clear() removes all entries in scope."""
        for i in range(5):
            yolo_manager.copy(f"entry-{i}", f"c{i}", ClipboardScope.AGENT)

        count = yolo_manager.clear(ClipboardScope.AGENT)

        assert count == 5
        assert len(yolo_manager.list_entries(scope=ClipboardScope.AGENT)) == 0


class TestClipboardManagerAgentEntries:
    """Tests for agent entry access (session persistence)."""

    def test_get_agent_entries(self, yolo_manager: ClipboardManager) -> None:
        """get_agent_entries() returns copy of agent clipboard."""
        yolo_manager.copy("e1", "c1", ClipboardScope.AGENT)
        yolo_manager.copy("e2", "c2", ClipboardScope.AGENT)

        entries = yolo_manager.get_agent_entries()

        assert len(entries) == 2
        assert "e1" in entries
        assert "e2" in entries

    def test_restore_agent_entries(self, tmp_dirs) -> None:
        """restore_agent_entries() restores agent clipboard from saved data."""
        home_dir, cwd = tmp_dirs

        # Create manager and add entries
        manager1 = ClipboardManager(
            agent_id="agent1",
            cwd=cwd,
            permissions=CLIPBOARD_PRESETS["yolo"],
            home_dir=home_dir,
        )
        manager1.copy("e1", "c1", ClipboardScope.AGENT)
        manager1.copy("e2", "c2", ClipboardScope.AGENT)
        saved_entries = manager1.get_agent_entries()
        manager1.close()

        # Create new manager and restore
        manager2 = ClipboardManager(
            agent_id="agent2",
            cwd=cwd,
            permissions=CLIPBOARD_PRESETS["yolo"],
            home_dir=home_dir,
        )
        manager2.restore_agent_entries(saved_entries)

        entries = manager2.get_agent_entries()
        assert len(entries) == 2
        assert entries["e1"].content == "c1"
        assert entries["e2"].content == "c2"
        manager2.close()


class TestClipboardManagerDefaults:
    """Tests for default behavior."""

    def test_default_permissions_sandboxed(self, tmp_dirs) -> None:
        """ClipboardManager defaults to sandboxed permissions."""
        home_dir, cwd = tmp_dirs
        manager = ClipboardManager(
            agent_id="test",
            cwd=cwd,
            home_dir=home_dir,
            # No permissions specified
        )

        # Should not be able to access project scope
        with pytest.raises(PermissionError):
            manager.copy("key", "content", ClipboardScope.PROJECT)

        manager.close()
