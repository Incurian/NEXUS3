"""Unit tests for clipboard management skills."""
from __future__ import annotations

import pytest

from nexus3.clipboard import ClipboardManager, ClipboardScope, CLIPBOARD_PRESETS
from nexus3.skill.builtin.clipboard_manage import (
    clipboard_list_factory,
    clipboard_get_factory,
    clipboard_update_factory,
    clipboard_delete_factory,
    clipboard_clear_factory,
)
from nexus3.skill.services import ServiceContainer


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def clipboard_manager(tmp_path):
    """Create a ClipboardManager with full permissions for testing."""
    return ClipboardManager(
        agent_id="test-agent",
        cwd=tmp_path,
        permissions=CLIPBOARD_PRESETS["yolo"],
        home_dir=tmp_path,
    )


@pytest.fixture
def services(tmp_path, clipboard_manager):
    """Create ServiceContainer with clipboard manager registered."""
    container = ServiceContainer()
    container.register("cwd", str(tmp_path))
    container.register("clipboard_manager", clipboard_manager)
    return container


@pytest.fixture
def list_skill(services):
    """Create clipboard list skill instance."""
    return clipboard_list_factory(services)


@pytest.fixture
def get_skill(services):
    """Create clipboard get skill instance."""
    return clipboard_get_factory(services)


@pytest.fixture
def update_skill(services):
    """Create clipboard update skill instance."""
    return clipboard_update_factory(services)


@pytest.fixture
def delete_skill(services):
    """Create clipboard delete skill instance."""
    return clipboard_delete_factory(services)


@pytest.fixture
def clear_skill(services):
    """Create clipboard clear skill instance."""
    return clipboard_clear_factory(services)


# =============================================================================
# ClipboardListSkill Tests
# =============================================================================


class TestClipboardListSkill:
    """Tests for ClipboardListSkill."""

    @pytest.mark.asyncio
    async def test_list_empty(self, list_skill):
        """Test listing with no entries."""
        result = await list_skill.execute()

        assert result.success
        assert "No clipboard entries" in result.output

    @pytest.mark.asyncio
    async def test_list_with_entries(self, list_skill, clipboard_manager):
        """Test listing with entries present."""
        clipboard_manager.copy(key="test1", content="content1", scope=ClipboardScope.AGENT)
        clipboard_manager.copy(key="test2", content="content2", scope=ClipboardScope.AGENT)

        result = await list_skill.execute()

        assert result.success
        assert "test1" in result.output
        assert "test2" in result.output

    @pytest.mark.asyncio
    async def test_list_verbose(self, list_skill, clipboard_manager):
        """Test listing with verbose mode shows content preview."""
        clipboard_manager.copy(
            key="test1",
            content="line1\nline2\nline3\nline4\nline5",
            scope=ClipboardScope.AGENT,
        )

        result = await list_skill.execute(verbose=True)

        assert result.success
        assert "test1" in result.output
        # Verbose mode should show content preview
        assert "5 lines" in result.output or "line" in result.output.lower()

    @pytest.mark.asyncio
    async def test_list_with_tag_filter(self, list_skill, clipboard_manager):
        """Test filtering by tags (AND logic)."""
        clipboard_manager.copy(
            key="tagged", content="content", scope=ClipboardScope.AGENT, tags=["important"]
        )
        clipboard_manager.copy(key="untagged", content="content2", scope=ClipboardScope.AGENT)

        result = await list_skill.execute(tags=["important"])

        assert result.success
        assert "tagged" in result.output
        assert "untagged" not in result.output

    @pytest.mark.asyncio
    async def test_list_any_tags_filter(self, list_skill, clipboard_manager):
        """Test filtering by any_tags (OR logic)."""
        clipboard_manager.copy(key="entry-a", content="c", scope=ClipboardScope.AGENT, tags=["tag1"])
        clipboard_manager.copy(key="entry-b", content="c", scope=ClipboardScope.AGENT, tags=["tag2"])
        clipboard_manager.copy(key="entry-c", content="c", scope=ClipboardScope.AGENT, tags=["other"])

        result = await list_skill.execute(any_tags=["tag1", "tag2"])

        assert result.success
        assert "entry-a" in result.output
        assert "entry-b" in result.output
        # entry-c should not be in output since it only has "other" tag
        assert "entry-c" not in result.output

    @pytest.mark.asyncio
    async def test_list_invalid_scope(self, list_skill):
        """Test error on invalid scope value."""
        result = await list_skill.execute(scope="invalid")

        assert not result.success
        assert result.error
        # Validation layer catches invalid enum values
        assert "scope" in result.error.lower()

    @pytest.mark.asyncio
    async def test_list_specific_scope_empty(self, list_skill):
        """Test listing specific scope with no entries."""
        result = await list_skill.execute(scope="agent")

        assert result.success
        assert "No clipboard entries" in result.output

    @pytest.mark.asyncio
    async def test_list_missing_clipboard_manager(self, tmp_path):
        """Test error when clipboard manager not available."""
        container = ServiceContainer()
        container.register("cwd", str(tmp_path))
        skill = clipboard_list_factory(container)

        result = await skill.execute()

        assert not result.success
        assert "not available" in result.error.lower()


# =============================================================================
# ClipboardGetSkill Tests
# =============================================================================


class TestClipboardGetSkill:
    """Tests for ClipboardGetSkill."""

    @pytest.mark.asyncio
    async def test_get_success(self, get_skill, clipboard_manager):
        """Test successful retrieval of entry content."""
        clipboard_manager.copy(key="test", content="hello world", scope=ClipboardScope.AGENT)

        result = await get_skill.execute(key="test")

        assert result.success
        assert result.output == "hello world"

    @pytest.mark.asyncio
    async def test_get_not_found(self, get_skill):
        """Test error when key doesn't exist."""
        result = await get_skill.execute(key="nonexistent")

        assert not result.success
        assert result.error is not None
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_get_line_range(self, get_skill, clipboard_manager):
        """Test getting specific line range from entry."""
        clipboard_manager.copy(
            key="test", content="line1\nline2\nline3\nline4\n", scope=ClipboardScope.AGENT
        )

        result = await get_skill.execute(key="test", start_line=2, end_line=3)

        assert result.success
        assert "line2" in result.output
        assert "line3" in result.output
        assert "line1" not in result.output
        assert "line4" not in result.output

    @pytest.mark.asyncio
    async def test_get_invalid_line_range_start_too_high(self, get_skill, clipboard_manager):
        """Test error when start_line exceeds content length."""
        clipboard_manager.copy(key="test", content="line1\nline2\n", scope=ClipboardScope.AGENT)

        result = await get_skill.execute(key="test", start_line=10)

        assert not result.success
        assert result.error is not None
        assert "out of range" in result.error.lower()

    @pytest.mark.asyncio
    async def test_get_invalid_line_range_end_too_high(self, get_skill, clipboard_manager):
        """Test error when end_line exceeds content length."""
        clipboard_manager.copy(key="test", content="line1\nline2\n", scope=ClipboardScope.AGENT)

        result = await get_skill.execute(key="test", start_line=1, end_line=100)

        assert not result.success
        assert result.error is not None
        assert "out of range" in result.error.lower()

    @pytest.mark.asyncio
    async def test_get_invalid_line_range_end_before_start(self, get_skill, clipboard_manager):
        """Test error when end_line is less than start_line."""
        clipboard_manager.copy(
            key="test", content="line1\nline2\nline3\n", scope=ClipboardScope.AGENT
        )

        result = await get_skill.execute(key="test", start_line=3, end_line=1)

        assert not result.success
        assert result.error is not None
        # Error message should indicate the invalid range

    @pytest.mark.asyncio
    async def test_get_with_specific_scope(self, get_skill, clipboard_manager):
        """Test getting entry from specific scope."""
        clipboard_manager.copy(key="project-key", content="project content", scope=ClipboardScope.PROJECT)

        result = await get_skill.execute(key="project-key", scope="project")

        assert result.success
        assert result.output == "project content"

    @pytest.mark.asyncio
    async def test_get_not_found_in_specific_scope(self, get_skill, clipboard_manager):
        """Test error when key exists in different scope."""
        clipboard_manager.copy(key="agent-key", content="agent content", scope=ClipboardScope.AGENT)

        result = await get_skill.execute(key="agent-key", scope="project")

        assert not result.success
        assert "not found" in result.error.lower()
        assert "project" in result.error.lower()

    @pytest.mark.asyncio
    async def test_get_missing_clipboard_manager(self, tmp_path):
        """Test error when clipboard manager not available."""
        container = ServiceContainer()
        container.register("cwd", str(tmp_path))
        skill = clipboard_get_factory(container)

        result = await skill.execute(key="test")

        assert not result.success
        assert "not available" in result.error.lower()


# =============================================================================
# ClipboardUpdateSkill Tests
# =============================================================================


class TestClipboardUpdateSkill:
    """Tests for ClipboardUpdateSkill."""

    @pytest.mark.asyncio
    async def test_update_description(self, update_skill, clipboard_manager):
        """Test updating entry description."""
        clipboard_manager.copy(key="test", content="content", scope=ClipboardScope.AGENT)

        result = await update_skill.execute(key="test", scope="agent", short_description="new desc")

        assert result.success

        entry = clipboard_manager.get("test", ClipboardScope.AGENT)
        assert entry is not None
        assert entry.short_description == "new desc"

    @pytest.mark.asyncio
    async def test_update_content_from_file(self, update_skill, clipboard_manager, tmp_path):
        """Test updating entry content from file."""
        clipboard_manager.copy(key="test", content="old", scope=ClipboardScope.AGENT)

        # Create source file
        source = tmp_path / "source.txt"
        source.write_text("new content from file")

        result = await update_skill.execute(key="test", scope="agent", source=str(source))

        assert result.success

        entry = clipboard_manager.get("test", ClipboardScope.AGENT)
        assert entry is not None
        assert entry.content == "new content from file"

    @pytest.mark.asyncio
    async def test_update_rename_key(self, update_skill, clipboard_manager):
        """Test renaming entry key."""
        clipboard_manager.copy(key="old_key", content="content", scope=ClipboardScope.AGENT)

        result = await update_skill.execute(key="old_key", scope="agent", new_key="new_key")

        assert result.success

        # Old key should be gone
        assert clipboard_manager.get("old_key", ClipboardScope.AGENT) is None
        # New key should exist
        assert clipboard_manager.get("new_key", ClipboardScope.AGENT) is not None

    @pytest.mark.asyncio
    async def test_update_ttl_seconds(self, update_skill, clipboard_manager):
        """Test setting TTL on entry."""
        clipboard_manager.copy(key="test", content="content", scope=ClipboardScope.AGENT)

        result = await update_skill.execute(key="test", scope="agent", ttl_seconds=3600)

        assert result.success

        entry = clipboard_manager.get("test", ClipboardScope.AGENT)
        assert entry is not None
        assert entry.ttl_seconds == 3600
        assert entry.expires_at is not None

    @pytest.mark.asyncio
    async def test_update_not_found(self, update_skill):
        """Test error when updating nonexistent entry."""
        result = await update_skill.execute(key="nonexistent", scope="agent", short_description="desc")

        assert not result.success
        assert result.error is not None
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_update_with_line_range(self, update_skill, clipboard_manager, tmp_path):
        """Test updating content from file with line range."""
        clipboard_manager.copy(key="test", content="old", scope=ClipboardScope.AGENT)

        # Create source file with multiple lines
        source = tmp_path / "source.txt"
        source.write_text("line1\nline2\nline3\nline4\nline5\n")

        result = await update_skill.execute(
            key="test", scope="agent", source=str(source), start_line=2, end_line=4
        )

        assert result.success
        entry = clipboard_manager.get("test", ClipboardScope.AGENT)
        assert entry is not None
        assert "line2" in entry.content
        assert "line3" in entry.content
        assert "line4" in entry.content
        assert "line1" not in entry.content
        assert "line5" not in entry.content

    @pytest.mark.asyncio
    async def test_update_invalid_scope(self, update_skill, clipboard_manager):
        """Test error on invalid scope."""
        result = await update_skill.execute(key="test", scope="invalid", short_description="desc")

        assert not result.success
        # Validation layer catches invalid enum values
        assert "scope" in result.error.lower()

    @pytest.mark.asyncio
    async def test_update_missing_clipboard_manager(self, tmp_path):
        """Test error when clipboard manager not available."""
        container = ServiceContainer()
        container.register("cwd", str(tmp_path))
        skill = clipboard_update_factory(container)

        result = await skill.execute(key="test", scope="agent", short_description="desc")

        assert not result.success
        assert "not available" in result.error.lower()


# =============================================================================
# ClipboardDeleteSkill Tests
# =============================================================================


class TestClipboardDeleteSkill:
    """Tests for ClipboardDeleteSkill."""

    @pytest.mark.asyncio
    async def test_delete_success(self, delete_skill, clipboard_manager):
        """Test successful deletion."""
        clipboard_manager.copy(key="test", content="content", scope=ClipboardScope.AGENT)

        result = await delete_skill.execute(key="test", scope="agent")

        assert result.success
        assert "Deleted" in result.output
        assert clipboard_manager.get("test", ClipboardScope.AGENT) is None

    @pytest.mark.asyncio
    async def test_delete_not_found(self, delete_skill):
        """Test error when deleting nonexistent entry."""
        result = await delete_skill.execute(key="nonexistent", scope="agent")

        assert not result.success
        assert result.error is not None
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_delete_invalid_scope(self, delete_skill):
        """Test error on invalid scope."""
        result = await delete_skill.execute(key="test", scope="invalid")

        assert not result.success
        assert result.error
        # Validation layer catches invalid enum values
        assert "scope" in result.error.lower()

    @pytest.mark.asyncio
    async def test_delete_from_project_scope(self, delete_skill, clipboard_manager):
        """Test deleting from project scope."""
        clipboard_manager.copy(key="project-key", content="content", scope=ClipboardScope.PROJECT)

        result = await delete_skill.execute(key="project-key", scope="project")

        assert result.success
        assert "project" in result.output.lower()
        assert clipboard_manager.get("project-key", ClipboardScope.PROJECT) is None

    @pytest.mark.asyncio
    async def test_delete_missing_clipboard_manager(self, tmp_path):
        """Test error when clipboard manager not available."""
        container = ServiceContainer()
        container.register("cwd", str(tmp_path))
        skill = clipboard_delete_factory(container)

        result = await skill.execute(key="test", scope="agent")

        assert not result.success
        assert "not available" in result.error.lower()


# =============================================================================
# ClipboardClearSkill Tests
# =============================================================================


class TestClipboardClearSkill:
    """Tests for ClipboardClearSkill."""

    @pytest.mark.asyncio
    async def test_clear_success(self, clear_skill, clipboard_manager):
        """Test successful clear with confirmation."""
        clipboard_manager.copy(key="test1", content="c1", scope=ClipboardScope.AGENT)
        clipboard_manager.copy(key="test2", content="c2", scope=ClipboardScope.AGENT)

        result = await clear_skill.execute(scope="agent", confirm=True)

        assert result.success
        assert "Cleared 2 entries" in result.output
        assert len(clipboard_manager.list_entries(ClipboardScope.AGENT)) == 0

    @pytest.mark.asyncio
    async def test_clear_without_confirm(self, clear_skill, clipboard_manager):
        """Test error when confirm=False."""
        clipboard_manager.copy(key="test", content="c", scope=ClipboardScope.AGENT)

        result = await clear_skill.execute(scope="agent", confirm=False)

        assert not result.success
        assert result.error is not None
        assert "confirm=True" in result.error or "confirm" in result.error.lower()
        # Entry should still exist
        assert clipboard_manager.get("test", ClipboardScope.AGENT) is not None

    @pytest.mark.asyncio
    async def test_clear_empty_scope(self, clear_skill):
        """Test clearing empty scope."""
        result = await clear_skill.execute(scope="agent", confirm=True)

        assert result.success
        assert "Cleared 0 entries" in result.output

    @pytest.mark.asyncio
    async def test_clear_invalid_scope(self, clear_skill):
        """Test error on invalid scope."""
        result = await clear_skill.execute(scope="invalid", confirm=True)

        assert not result.success
        assert result.error
        # Validation layer catches invalid enum values
        assert "scope" in result.error.lower()

    @pytest.mark.asyncio
    async def test_clear_project_scope(self, clear_skill, clipboard_manager):
        """Test clearing project scope."""
        clipboard_manager.copy(key="p1", content="c1", scope=ClipboardScope.PROJECT)
        clipboard_manager.copy(key="p2", content="c2", scope=ClipboardScope.PROJECT)

        result = await clear_skill.execute(scope="project", confirm=True)

        assert result.success
        assert "Cleared 2 entries" in result.output
        assert len(clipboard_manager.list_entries(ClipboardScope.PROJECT)) == 0

    @pytest.mark.asyncio
    async def test_clear_missing_clipboard_manager(self, tmp_path):
        """Test error when clipboard manager not available."""
        container = ServiceContainer()
        container.register("cwd", str(tmp_path))
        skill = clipboard_clear_factory(container)

        result = await skill.execute(scope="agent", confirm=True)

        assert not result.success
        assert "not available" in result.error.lower()


# =============================================================================
# Integration Tests
# =============================================================================


class TestClipboardManageIntegration:
    """Integration tests for clipboard management workflow."""

    @pytest.mark.asyncio
    async def test_create_list_get_delete_workflow(self, list_skill, get_skill, delete_skill, clipboard_manager):
        """Test full CRUD workflow."""
        # Create entry via manager
        clipboard_manager.copy(
            key="workflow-test",
            content="test content\nwith multiple lines",
            scope=ClipboardScope.AGENT,
            short_description="Test entry",
        )

        # List should show entry
        list_result = await list_skill.execute()
        assert "workflow-test" in list_result.output

        # Get should return content
        get_result = await get_skill.execute(key="workflow-test")
        assert get_result.output == "test content\nwith multiple lines"

        # Delete should succeed
        delete_result = await delete_skill.execute(key="workflow-test", scope="agent")
        assert delete_result.success

        # Get should now fail
        get_result_after = await get_skill.execute(key="workflow-test")
        assert not get_result_after.success

    @pytest.mark.asyncio
    async def test_update_then_verify(self, update_skill, get_skill, clipboard_manager):
        """Test update followed by get to verify changes."""
        clipboard_manager.copy(
            key="update-test",
            content="original",
            scope=ClipboardScope.AGENT,
            short_description="Original desc",
        )

        # Update description and content
        await update_skill.execute(
            key="update-test",
            scope="agent",
            content="updated content",
            short_description="Updated desc",
        )

        # Verify via get
        get_result = await get_skill.execute(key="update-test")
        assert get_result.output == "updated content"

        # Verify description via manager
        entry = clipboard_manager.get("update-test", ClipboardScope.AGENT)
        assert entry.short_description == "Updated desc"
