"""Unit tests for clipboard search, tag, export, import skills."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nexus3.clipboard import ClipboardManager, ClipboardScope, CLIPBOARD_PRESETS
from nexus3.core.types import ToolResult
from nexus3.skill.builtin.clipboard_search import clipboard_search_factory
from nexus3.skill.builtin.clipboard_tag import clipboard_tag_factory
from nexus3.skill.builtin.clipboard_export import clipboard_export_factory
from nexus3.skill.builtin.clipboard_import import clipboard_import_factory
from nexus3.skill.services import ServiceContainer


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def clipboard_manager(tmp_path: Path) -> ClipboardManager:
    """Create a ClipboardManager with full permissions for testing."""
    return ClipboardManager(
        agent_id="test-agent",
        cwd=tmp_path,
        permissions=CLIPBOARD_PRESETS["yolo"],
        home_dir=tmp_path,
    )


@pytest.fixture
def services(tmp_path: Path, clipboard_manager: ClipboardManager) -> ServiceContainer:
    """Create ServiceContainer with clipboard manager registered."""
    container = ServiceContainer()
    container.register("cwd", str(tmp_path))
    container.register("clipboard_manager", clipboard_manager)
    container.register("allowed_paths", [tmp_path])
    return container


@pytest.fixture
def search_skill(services: ServiceContainer):
    """Create search skill instance."""
    return clipboard_search_factory(services)


@pytest.fixture
def tag_skill(services: ServiceContainer):
    """Create tag skill instance."""
    return clipboard_tag_factory(services)


@pytest.fixture
def export_skill(services: ServiceContainer):
    """Create export skill instance."""
    return clipboard_export_factory(services)


@pytest.fixture
def import_skill(services: ServiceContainer):
    """Create import skill instance."""
    return clipboard_import_factory(services)


# =============================================================================
# ClipboardSearchSkill Tests
# =============================================================================


class TestClipboardSearchSkill:
    """Tests for ClipboardSearchSkill."""

    @pytest.mark.asyncio
    async def test_search_found(
        self, search_skill, clipboard_manager: ClipboardManager
    ) -> None:
        """Test search finds matching entry."""
        clipboard_manager.copy(
            key="test",
            content="hello world searchable",
            scope=ClipboardScope.AGENT,
        )

        result = await search_skill.execute(query="searchable")

        assert result.success
        assert "test" in result.output
        assert "1 match" in result.output

    @pytest.mark.asyncio
    async def test_search_not_found(
        self, search_skill, clipboard_manager: ClipboardManager
    ) -> None:
        """Test search with no matches."""
        clipboard_manager.copy(
            key="test",
            content="hello world",
            scope=ClipboardScope.AGENT,
        )

        result = await search_skill.execute(query="notfound")

        assert result.success
        assert "No matches" in result.output

    @pytest.mark.asyncio
    async def test_search_empty_query(self, search_skill) -> None:
        """Test search with empty query returns error."""
        result = await search_skill.execute(query="")

        assert not result.success
        assert "empty" in result.error.lower()

    @pytest.mark.asyncio
    async def test_search_with_scope(
        self, search_skill, clipboard_manager: ClipboardManager
    ) -> None:
        """Test search within a specific scope."""
        clipboard_manager.copy(
            key="test",
            content="searchable content",
            scope=ClipboardScope.AGENT,
        )

        result = await search_skill.execute(query="searchable", scope="agent")

        assert result.success
        assert "test" in result.output

    @pytest.mark.asyncio
    async def test_search_invalid_scope(self, search_skill) -> None:
        """Test search with invalid scope returns error."""
        result = await search_skill.execute(query="test", scope="invalid")

        assert not result.success
        # Validation wrapper catches invalid enum value before execute()
        assert "scope" in result.error.lower()

    @pytest.mark.asyncio
    async def test_search_missing_manager(self, tmp_path: Path) -> None:
        """Test search without clipboard manager returns error."""
        services = ServiceContainer()
        services.register("cwd", str(tmp_path))
        skill = clipboard_search_factory(services)

        result = await skill.execute(query="test")

        assert not result.success
        assert "not available" in result.error.lower()


# =============================================================================
# ClipboardTagSkill Tests
# =============================================================================


class TestClipboardTagSkill:
    """Tests for ClipboardTagSkill."""

    @pytest.mark.asyncio
    async def test_tag_list_empty(self, tag_skill) -> None:
        """Test list action with no tags."""
        result = await tag_skill.execute(action="list")

        assert result.success
        assert "No tags" in result.output

    @pytest.mark.asyncio
    async def test_tag_list_with_tags(
        self, tag_skill, clipboard_manager: ClipboardManager
    ) -> None:
        """Test list action shows existing tags."""
        clipboard_manager.copy(
            key="test",
            content="content",
            scope=ClipboardScope.AGENT,
            tags=["tag1", "tag2"],
        )

        result = await tag_skill.execute(action="list")

        assert result.success
        assert "tag1" in result.output
        assert "tag2" in result.output

    @pytest.mark.asyncio
    async def test_tag_add(
        self, tag_skill, clipboard_manager: ClipboardManager
    ) -> None:
        """Test adding a tag to an entry."""
        clipboard_manager.copy(
            key="test",
            content="content",
            scope=ClipboardScope.AGENT,
        )

        result = await tag_skill.execute(
            action="add",
            name="newtag",
            entry_key="test",
            scope="agent",
        )

        assert result.success
        assert "Added" in result.output

        # Verify tag was added
        entry = clipboard_manager.get("test", ClipboardScope.AGENT)
        assert entry is not None
        assert "newtag" in entry.tags

    @pytest.mark.asyncio
    async def test_tag_remove(
        self, tag_skill, clipboard_manager: ClipboardManager
    ) -> None:
        """Test removing a tag from an entry."""
        clipboard_manager.copy(
            key="test",
            content="content",
            scope=ClipboardScope.AGENT,
            tags=["removeme"],
        )

        result = await tag_skill.execute(
            action="remove",
            name="removeme",
            entry_key="test",
            scope="agent",
        )

        assert result.success
        assert "Removed" in result.output

        # Verify tag was removed
        entry = clipboard_manager.get("test", ClipboardScope.AGENT)
        assert entry is not None
        assert "removeme" not in entry.tags

    @pytest.mark.asyncio
    async def test_tag_missing_params(self, tag_skill) -> None:
        """Test add action without required parameters returns error."""
        result = await tag_skill.execute(action="add")

        assert not result.success
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_tag_add_missing_entry_key(self, tag_skill) -> None:
        """Test add action without entry_key returns error."""
        result = await tag_skill.execute(action="add", name="tag")

        assert not result.success
        assert "entry_key" in result.error.lower()

    @pytest.mark.asyncio
    async def test_tag_add_missing_scope(self, tag_skill) -> None:
        """Test add action without scope returns error."""
        result = await tag_skill.execute(action="add", name="tag", entry_key="test")

        assert not result.success
        assert "scope" in result.error.lower()

    @pytest.mark.asyncio
    async def test_tag_unknown_action(self, tag_skill) -> None:
        """Test unknown action returns error."""
        result = await tag_skill.execute(action="unknown")

        assert not result.success
        # Validation wrapper catches invalid enum value before execute()
        assert "action" in result.error.lower()

    @pytest.mark.asyncio
    async def test_tag_missing_manager(self, tmp_path: Path) -> None:
        """Test tag skill without clipboard manager returns error."""
        services = ServiceContainer()
        services.register("cwd", str(tmp_path))
        skill = clipboard_tag_factory(services)

        result = await skill.execute(action="list")

        assert not result.success
        assert "not available" in result.error.lower()


# =============================================================================
# ClipboardExportSkill Tests
# =============================================================================


class TestClipboardExportSkill:
    """Tests for ClipboardExportSkill."""

    @pytest.mark.asyncio
    async def test_export_success(
        self,
        export_skill,
        clipboard_manager: ClipboardManager,
        tmp_path: Path,
    ) -> None:
        """Test successful export of entries."""
        clipboard_manager.copy(
            key="test1",
            content="content1",
            scope=ClipboardScope.AGENT,
        )
        clipboard_manager.copy(
            key="test2",
            content="content2",
            scope=ClipboardScope.AGENT,
        )

        export_path = tmp_path / "export.json"
        result = await export_skill.execute(path=str(export_path))

        assert result.success
        assert "Exported 2 entries" in result.output
        assert export_path.exists()

        data = json.loads(export_path.read_text())
        assert data["version"] == "1.0"
        assert len(data["entries"]) == 2

    @pytest.mark.asyncio
    async def test_export_empty(
        self,
        export_skill,
        tmp_path: Path,
    ) -> None:
        """Test export with no entries."""
        export_path = tmp_path / "export.json"
        result = await export_skill.execute(path=str(export_path))

        assert result.success
        assert "No entries" in result.output

    @pytest.mark.asyncio
    async def test_export_with_tags_filter(
        self,
        export_skill,
        clipboard_manager: ClipboardManager,
        tmp_path: Path,
    ) -> None:
        """Test export filtered by tags."""
        clipboard_manager.copy(
            key="tagged",
            content="content",
            scope=ClipboardScope.AGENT,
            tags=["export"],
        )
        clipboard_manager.copy(
            key="untagged",
            content="content",
            scope=ClipboardScope.AGENT,
        )

        export_path = tmp_path / "export.json"
        result = await export_skill.execute(
            path=str(export_path),
            tags=["export"],
        )

        assert result.success
        assert "Exported 1 entries" in result.output

        data = json.loads(export_path.read_text())
        assert len(data["entries"]) == 1
        assert data["entries"][0]["key"] == "tagged"

    @pytest.mark.asyncio
    async def test_export_missing_manager(self, tmp_path: Path) -> None:
        """Test export without clipboard manager returns error."""
        services = ServiceContainer()
        services.register("cwd", str(tmp_path))
        services.register("allowed_paths", [tmp_path])
        skill = clipboard_export_factory(services)

        export_path = tmp_path / "export.json"
        result = await skill.execute(path=str(export_path))

        assert not result.success
        assert "not available" in result.error.lower()

    @pytest.mark.asyncio
    async def test_export_invalid_scope(
        self,
        export_skill,
        tmp_path: Path,
    ) -> None:
        """Test export with invalid scope returns error."""
        export_path = tmp_path / "export.json"
        result = await export_skill.execute(path=str(export_path), scope="invalid")

        assert not result.success
        # Validation wrapper catches invalid enum value before execute()
        assert "scope" in result.error.lower()


# =============================================================================
# ClipboardImportSkill Tests
# =============================================================================


class TestClipboardImportSkill:
    """Tests for ClipboardImportSkill."""

    def _create_export_file(self, path: Path, entries: list[dict]) -> None:
        """Helper to create an export file."""
        data = {
            "version": "1.0",
            "exported_at": "2026-01-01T00:00:00",
            "entry_count": len(entries),
            "entries": entries,
        }
        path.write_text(json.dumps(data))

    @pytest.mark.asyncio
    async def test_import_dry_run(
        self,
        import_skill,
        tmp_path: Path,
    ) -> None:
        """Test dry run import shows what would be imported."""
        import_path = tmp_path / "import.json"
        self._create_export_file(
            import_path,
            [
                {"key": "test1", "content": "content1", "scope": "agent"},
                {"key": "test2", "content": "content2", "scope": "agent"},
            ],
        )

        result = await import_skill.execute(path=str(import_path), dry_run=True)

        assert result.success
        assert "Dry run" in result.output
        assert "would import 2" in result.output

    @pytest.mark.asyncio
    async def test_import_execute(
        self,
        import_skill,
        clipboard_manager: ClipboardManager,
        tmp_path: Path,
    ) -> None:
        """Test actual import creates entries."""
        import_path = tmp_path / "import.json"
        self._create_export_file(
            import_path,
            [
                {"key": "imported", "content": "imported content", "scope": "agent"},
            ],
        )

        result = await import_skill.execute(path=str(import_path), dry_run=False)

        assert result.success
        assert "Imported 1" in result.output

        entry = clipboard_manager.get("imported", ClipboardScope.AGENT)
        assert entry is not None
        assert entry.content == "imported content"

    @pytest.mark.asyncio
    async def test_import_skip_existing(
        self,
        import_skill,
        clipboard_manager: ClipboardManager,
        tmp_path: Path,
    ) -> None:
        """Test import skips existing entries with conflict=skip."""
        # Create existing entry
        clipboard_manager.copy(
            key="existing",
            content="original",
            scope=ClipboardScope.AGENT,
        )

        import_path = tmp_path / "import.json"
        self._create_export_file(
            import_path,
            [
                {"key": "existing", "content": "new content", "scope": "agent"},
                {"key": "new", "content": "new entry", "scope": "agent"},
            ],
        )

        result = await import_skill.execute(
            path=str(import_path),
            dry_run=False,
            conflict="skip",
        )

        assert result.success
        assert "skipped 1" in result.output

        # Original should be unchanged
        entry = clipboard_manager.get("existing", ClipboardScope.AGENT)
        assert entry is not None
        assert entry.content == "original"

        # New entry should be imported
        new_entry = clipboard_manager.get("new", ClipboardScope.AGENT)
        assert new_entry is not None
        assert new_entry.content == "new entry"

    @pytest.mark.asyncio
    async def test_import_overwrite_existing(
        self,
        import_skill,
        clipboard_manager: ClipboardManager,
        tmp_path: Path,
    ) -> None:
        """Test import overwrites existing entries with conflict=overwrite."""
        # Create existing entry
        clipboard_manager.copy(
            key="existing",
            content="original",
            scope=ClipboardScope.AGENT,
        )

        import_path = tmp_path / "import.json"
        self._create_export_file(
            import_path,
            [
                {"key": "existing", "content": "new content", "scope": "agent"},
            ],
        )

        result = await import_skill.execute(
            path=str(import_path),
            dry_run=False,
            conflict="overwrite",
        )

        assert result.success
        assert "overwritten" in result.output

        # Entry should be updated
        entry = clipboard_manager.get("existing", ClipboardScope.AGENT)
        assert entry is not None
        assert entry.content == "new content"

    @pytest.mark.asyncio
    async def test_import_invalid_format(
        self,
        import_skill,
        tmp_path: Path,
    ) -> None:
        """Test import with unsupported version returns error."""
        import_path = tmp_path / "import.json"
        import_path.write_text(json.dumps({"version": "2.0", "entries": []}))

        result = await import_skill.execute(path=str(import_path))

        assert not result.success
        assert "Unsupported" in result.error

    @pytest.mark.asyncio
    async def test_import_file_not_found(
        self,
        import_skill,
        tmp_path: Path,
    ) -> None:
        """Test import with missing file returns error."""
        import_path = tmp_path / "nonexistent.json"
        result = await import_skill.execute(path=str(import_path))

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_import_invalid_json(
        self,
        import_skill,
        tmp_path: Path,
    ) -> None:
        """Test import with invalid JSON returns error."""
        import_path = tmp_path / "import.json"
        import_path.write_text("not valid json {")

        result = await import_skill.execute(path=str(import_path))

        assert not result.success
        assert "Invalid JSON" in result.error

    @pytest.mark.asyncio
    async def test_import_empty_entries(
        self,
        import_skill,
        tmp_path: Path,
    ) -> None:
        """Test import with no entries returns message."""
        import_path = tmp_path / "import.json"
        self._create_export_file(import_path, [])

        result = await import_skill.execute(path=str(import_path))

        assert result.success
        assert "No entries" in result.output

    @pytest.mark.asyncio
    async def test_import_missing_manager(self, tmp_path: Path) -> None:
        """Test import without clipboard manager returns error."""
        services = ServiceContainer()
        services.register("cwd", str(tmp_path))
        services.register("allowed_paths", [tmp_path])
        skill = clipboard_import_factory(services)

        import_path = tmp_path / "import.json"
        import_path.write_text(json.dumps({"version": "1.0", "entries": []}))

        result = await skill.execute(path=str(import_path))

        assert not result.success
        assert "not available" in result.error.lower()

    @pytest.mark.asyncio
    async def test_import_with_tags(
        self,
        import_skill,
        clipboard_manager: ClipboardManager,
        tmp_path: Path,
    ) -> None:
        """Test import preserves tags from export."""
        import_path = tmp_path / "import.json"
        self._create_export_file(
            import_path,
            [
                {
                    "key": "tagged",
                    "content": "content",
                    "scope": "agent",
                    "tags": ["tag1", "tag2"],
                },
            ],
        )

        result = await import_skill.execute(path=str(import_path), dry_run=False)

        assert result.success

        entry = clipboard_manager.get("tagged", ClipboardScope.AGENT)
        assert entry is not None
        assert "tag1" in entry.tags
        assert "tag2" in entry.tags
