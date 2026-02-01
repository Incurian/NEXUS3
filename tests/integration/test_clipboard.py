"""Integration tests for the NEXUS3 clipboard system.

Tests cover:
- P7.1 Copy/paste roundtrip
- P7.2 Cut/paste roundtrip
- P7.3 Cross-agent project scope sharing
- P7.4 Context injection in system prompt
- P7.5 Permission boundaries (sandboxed restrictions)
- P7.6 Persistence across ClipboardManager instances
- P7.7 Search finds entries by content substring
- P7.8 Tags filter entries correctly
- P7.9 Import/export roundtrip preserves entries
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from nexus3.clipboard import (
    CLIPBOARD_PRESETS,
    ClipboardEntry,
    ClipboardManager,
    ClipboardPermissions,
    ClipboardScope,
    format_clipboard_context,
)
from nexus3.clipboard.storage import ClipboardStorage
from nexus3.core.permissions import resolve_preset
from nexus3.core.types import ToolResult
from nexus3.skill.builtin.clipboard_copy import CopySkill, CutSkill, copy_factory, cut_factory
from nexus3.skill.builtin.clipboard_export import ClipboardExportSkill, clipboard_export_factory
from nexus3.skill.builtin.clipboard_import import ClipboardImportSkill, clipboard_import_factory
from nexus3.skill.builtin.clipboard_manage import (
    ClipboardListSkill,
    ClipboardGetSkill,
    ClipboardDeleteSkill,
    ClipboardClearSkill,
    clipboard_list_factory,
    clipboard_get_factory,
    clipboard_delete_factory,
    clipboard_clear_factory,
)
from nexus3.skill.builtin.clipboard_paste import PasteSkill, paste_skill_factory
from nexus3.skill.builtin.clipboard_search import ClipboardSearchSkill, clipboard_search_factory
from nexus3.skill.builtin.clipboard_tag import ClipboardTagSkill, clipboard_tag_factory
from nexus3.skill.services import ServiceContainer


def create_services_with_clipboard(
    tmp_path: Path,
    agent_id: str = "test-agent",
    preset: str = "yolo",
) -> ServiceContainer:
    """Create a ServiceContainer with clipboard manager registered.

    Args:
        tmp_path: Temporary directory for project/system clipboard DBs
        agent_id: Agent ID for the clipboard manager
        preset: Permission preset ('yolo', 'trusted', 'sandboxed')

    Returns:
        ServiceContainer with clipboard_manager and permissions
    """
    services = ServiceContainer()

    # Set up permissions
    permissions = resolve_preset(preset)
    services.register("permissions", permissions)
    services.register("cwd", tmp_path)
    services.register("allowed_paths", [tmp_path])

    # Get clipboard permissions from preset
    clipboard_perms = CLIPBOARD_PRESETS.get(preset, CLIPBOARD_PRESETS["sandboxed"])

    # Create clipboard manager
    manager = ClipboardManager(
        agent_id=agent_id,
        cwd=tmp_path,
        permissions=clipboard_perms,
        home_dir=tmp_path / "home",  # Separate system scope dir
    )
    services.register("clipboard_manager", manager)

    return services


class TestCopyPasteRoundtrip:
    """P7.1 - Test copy/paste roundtrip."""

    @pytest.mark.asyncio
    async def test_copy_and_paste_file_content(self, tmp_path: Path) -> None:
        """Copy file content and paste it to a different location."""
        # Create source file
        source_file = tmp_path / "source.txt"
        source_file.write_text("Line 1\nLine 2\nLine 3\n", encoding="utf-8")

        # Create target file
        target_file = tmp_path / "target.txt"
        target_file.write_text("Existing content\n", encoding="utf-8")

        # Set up services
        services = create_services_with_clipboard(tmp_path)

        # Create skills
        copy_skill = copy_factory(services)
        paste_skill = paste_skill_factory(services)

        # Copy file content
        result = await copy_skill.execute(
            source=str(source_file),
            key="test-copy",
            scope="agent",
        )
        assert not result.error, f"Unexpected error: {result.error}"
        assert "Copied to clipboard" in result.output
        assert "3 lines" in result.output

        # Paste to target file
        result = await paste_skill.execute(
            key="test-copy",
            target=str(target_file),
            mode="append",
        )
        assert not result.error, f"Unexpected error: {result.error}"
        assert "Pasted 3 lines" in result.output

        # Verify target file content
        target_content = target_file.read_text(encoding="utf-8")
        assert "Existing content" in target_content
        assert "Line 1" in target_content
        assert "Line 3" in target_content

    @pytest.mark.asyncio
    async def test_copy_line_range_and_paste(self, tmp_path: Path) -> None:
        """Copy specific lines and paste them."""
        # Create source file
        source_file = tmp_path / "source.txt"
        source_file.write_text("Header\nLine A\nLine B\nLine C\nFooter\n", encoding="utf-8")

        # Create target file
        target_file = tmp_path / "target.txt"
        target_file.write_text("Before\n", encoding="utf-8")

        services = create_services_with_clipboard(tmp_path)
        copy_skill = copy_factory(services)
        paste_skill = paste_skill_factory(services)

        # Copy lines 2-4 only
        result = await copy_skill.execute(
            source=str(source_file),
            key="lines-only",
            scope="agent",
            start_line=2,
            end_line=4,
        )
        assert not result.error, f"Unexpected error: {result.error}"
        assert "Lines: 2-4" in result.output

        # Paste and verify
        result = await paste_skill.execute(
            key="lines-only",
            target=str(target_file),
            mode="append",
        )
        assert not result.error, f"Unexpected error: {result.error}"

        target_content = target_file.read_text(encoding="utf-8")
        assert "Line A" in target_content
        assert "Line B" in target_content
        assert "Line C" in target_content
        assert "Header" not in target_content
        assert "Footer" not in target_content


class TestCutPasteRoundtrip:
    """P7.2 - Test cut/paste roundtrip."""

    @pytest.mark.asyncio
    async def test_cut_removes_from_source(self, tmp_path: Path) -> None:
        """Cut should remove content from source file."""
        # Create source file
        source_file = tmp_path / "source.txt"
        source_file.write_text("Keep\nRemove Me\nAlso Keep\n", encoding="utf-8")

        services = create_services_with_clipboard(tmp_path)
        cut_skill = cut_factory(services)

        # Cut middle line
        result = await cut_skill.execute(
            source=str(source_file),
            key="cut-content",
            scope="agent",
            start_line=2,
            end_line=2,
        )
        assert not result.error, f"Unexpected error: {result.error}"
        assert "Cut to clipboard" in result.output

        # Verify source file has content removed
        source_content = source_file.read_text(encoding="utf-8")
        assert "Keep" in source_content
        assert "Also Keep" in source_content
        assert "Remove Me" not in source_content

    @pytest.mark.asyncio
    async def test_cut_and_paste_moves_content(self, tmp_path: Path) -> None:
        """Cut content from one file and paste to another."""
        # Create source and target files
        source_file = tmp_path / "source.txt"
        source_file.write_text("Header\nMove This\nFooter\n", encoding="utf-8")

        target_file = tmp_path / "target.txt"
        target_file.write_text("", encoding="utf-8")

        services = create_services_with_clipboard(tmp_path)
        cut_skill = cut_factory(services)
        paste_skill = paste_skill_factory(services)

        # Cut middle line
        result = await cut_skill.execute(
            source=str(source_file),
            key="moved",
            scope="agent",
            start_line=2,
            end_line=2,
        )
        assert not result.error, f"Unexpected error: {result.error}"

        # Paste to target
        result = await paste_skill.execute(
            key="moved",
            target=str(target_file),
            mode="append",
        )
        assert not result.error, f"Unexpected error: {result.error}"

        # Verify content was moved
        source_content = source_file.read_text(encoding="utf-8")
        target_content = target_file.read_text(encoding="utf-8")

        assert "Move This" not in source_content
        assert "Move This" in target_content


class TestCrossAgentProjectScope:
    """P7.3 - Test cross-agent project scope sharing."""

    @pytest.mark.asyncio
    async def test_two_agents_share_project_clipboard(self, tmp_path: Path) -> None:
        """Two agents with project scope can share clipboard entries."""
        # Create two clipboard managers for different agents
        perms = CLIPBOARD_PRESETS["yolo"]

        manager1 = ClipboardManager(
            agent_id="agent-1",
            cwd=tmp_path,
            permissions=perms,
            home_dir=tmp_path / "home",
        )

        manager2 = ClipboardManager(
            agent_id="agent-2",
            cwd=tmp_path,  # Same project directory
            permissions=perms,
            home_dir=tmp_path / "home",
        )

        # Agent 1 copies to project scope
        entry, _ = manager1.copy(
            key="shared-entry",
            content="Shared content from agent-1",
            scope=ClipboardScope.PROJECT,
            short_description="Shared data",
        )

        # Agent 2 should be able to read it
        retrieved = manager2.get("shared-entry", ClipboardScope.PROJECT)
        assert retrieved is not None
        assert retrieved.content == "Shared content from agent-1"
        assert retrieved.created_by_agent == "agent-1"

        # Clean up
        manager1.close()
        manager2.close()

    @pytest.mark.asyncio
    async def test_agent_scope_not_shared(self, tmp_path: Path) -> None:
        """Agent scope entries are not shared between agents."""
        perms = CLIPBOARD_PRESETS["yolo"]

        manager1 = ClipboardManager(
            agent_id="agent-1",
            cwd=tmp_path,
            permissions=perms,
            home_dir=tmp_path / "home",
        )

        manager2 = ClipboardManager(
            agent_id="agent-2",
            cwd=tmp_path,
            permissions=perms,
            home_dir=tmp_path / "home",
        )

        # Agent 1 copies to agent scope
        manager1.copy(
            key="private-entry",
            content="Private to agent-1",
            scope=ClipboardScope.AGENT,
        )

        # Agent 2 should NOT see it
        retrieved = manager2.get("private-entry", ClipboardScope.AGENT)
        assert retrieved is None

        manager1.close()
        manager2.close()


class TestContextInjection:
    """P7.4 - Test context injection appears in system prompt."""

    def test_format_clipboard_context_with_entries(self, tmp_path: Path) -> None:
        """format_clipboard_context includes entries in markdown format."""
        perms = CLIPBOARD_PRESETS["yolo"]
        manager = ClipboardManager(
            agent_id="test",
            cwd=tmp_path,
            permissions=perms,
            home_dir=tmp_path / "home",
        )

        # Add some entries
        manager.copy("entry1", "Content 1\nLine 2", scope=ClipboardScope.AGENT)
        manager.copy("entry2", "Content 2", scope=ClipboardScope.AGENT, short_description="Second entry")

        # Get context injection
        context = format_clipboard_context(manager)

        assert context is not None
        assert "## Available Clipboard Entries" in context
        assert "entry1" in context
        assert "entry2" in context
        assert "Second entry" in context
        assert 'paste(key="...")' in context

        manager.close()

    def test_format_clipboard_context_empty(self, tmp_path: Path) -> None:
        """format_clipboard_context returns None when no entries."""
        perms = CLIPBOARD_PRESETS["yolo"]
        manager = ClipboardManager(
            agent_id="test",
            cwd=tmp_path,
            permissions=perms,
            home_dir=tmp_path / "home",
        )

        context = format_clipboard_context(manager)
        assert context is None

        manager.close()


class TestPermissionBoundaries:
    """P7.5 - Test permission boundaries for sandboxed agents."""

    def test_sandboxed_cannot_access_project_scope(self, tmp_path: Path) -> None:
        """Sandboxed agents cannot read from project scope."""
        perms = CLIPBOARD_PRESETS["sandboxed"]
        manager = ClipboardManager(
            agent_id="sandboxed-agent",
            cwd=tmp_path,
            permissions=perms,
            home_dir=tmp_path / "home",
        )

        # Should raise PermissionError when trying to write to project scope
        with pytest.raises(PermissionError) as exc:
            manager.copy("test", "content", scope=ClipboardScope.PROJECT)
        assert "No write permission" in str(exc.value)

        manager.close()

    def test_sandboxed_cannot_access_system_scope(self, tmp_path: Path) -> None:
        """Sandboxed agents cannot read from system scope."""
        perms = CLIPBOARD_PRESETS["sandboxed"]
        manager = ClipboardManager(
            agent_id="sandboxed-agent",
            cwd=tmp_path,
            permissions=perms,
            home_dir=tmp_path / "home",
        )

        # Should raise PermissionError when trying to write to system scope
        with pytest.raises(PermissionError) as exc:
            manager.copy("test", "content", scope=ClipboardScope.SYSTEM)
        assert "No write permission" in str(exc.value)

        manager.close()

    def test_sandboxed_can_use_agent_scope(self, tmp_path: Path) -> None:
        """Sandboxed agents can use agent scope."""
        perms = CLIPBOARD_PRESETS["sandboxed"]
        manager = ClipboardManager(
            agent_id="sandboxed-agent",
            cwd=tmp_path,
            permissions=perms,
            home_dir=tmp_path / "home",
        )

        # Should succeed for agent scope
        entry, _ = manager.copy("test", "content", scope=ClipboardScope.AGENT)
        assert entry.key == "test"

        # Can also read it back
        retrieved = manager.get("test", ClipboardScope.AGENT)
        assert retrieved is not None
        assert retrieved.content == "content"

        manager.close()

    def test_trusted_can_read_system_not_write(self, tmp_path: Path) -> None:
        """Trusted agents can read system scope but not write."""
        perms = CLIPBOARD_PRESETS["trusted"]

        # Can read system (empty is fine)
        manager = ClipboardManager(
            agent_id="trusted-agent",
            cwd=tmp_path,
            permissions=perms,
            home_dir=tmp_path / "home",
        )

        # Should be able to list system scope (returns empty)
        entries = manager.list_entries(ClipboardScope.SYSTEM)
        assert entries == []

        # But should NOT be able to write
        with pytest.raises(PermissionError) as exc:
            manager.copy("test", "content", scope=ClipboardScope.SYSTEM)
        assert "No write permission" in str(exc.value)

        manager.close()


class TestPersistence:
    """P7.6 - Test persistence across ClipboardManager instances."""

    def test_project_scope_persists(self, tmp_path: Path) -> None:
        """Project scope entries persist across manager instances."""
        perms = CLIPBOARD_PRESETS["yolo"]

        # First manager creates entry
        manager1 = ClipboardManager(
            agent_id="agent-1",
            cwd=tmp_path,
            permissions=perms,
            home_dir=tmp_path / "home",
        )
        manager1.copy(
            key="persistent",
            content="Persistent content",
            scope=ClipboardScope.PROJECT,
        )
        manager1.close()

        # New manager should see the entry
        manager2 = ClipboardManager(
            agent_id="agent-2",
            cwd=tmp_path,
            permissions=perms,
            home_dir=tmp_path / "home",
        )

        retrieved = manager2.get("persistent", ClipboardScope.PROJECT)
        assert retrieved is not None
        assert retrieved.content == "Persistent content"
        manager2.close()

    def test_system_scope_persists(self, tmp_path: Path) -> None:
        """System scope entries persist across manager instances."""
        perms = CLIPBOARD_PRESETS["yolo"]
        home_dir = tmp_path / "home"

        # First manager creates entry
        manager1 = ClipboardManager(
            agent_id="agent-1",
            cwd=tmp_path,
            permissions=perms,
            home_dir=home_dir,
        )
        manager1.copy(
            key="system-persistent",
            content="System content",
            scope=ClipboardScope.SYSTEM,
        )
        manager1.close()

        # New manager with different cwd but same home should see it
        manager2 = ClipboardManager(
            agent_id="agent-2",
            cwd=tmp_path / "subdir",
            permissions=perms,
            home_dir=home_dir,
        )

        retrieved = manager2.get("system-persistent", ClipboardScope.SYSTEM)
        assert retrieved is not None
        assert retrieved.content == "System content"
        manager2.close()

    def test_agent_scope_not_persistent(self, tmp_path: Path) -> None:
        """Agent scope entries do NOT persist across instances."""
        perms = CLIPBOARD_PRESETS["yolo"]

        # First manager creates entry
        manager1 = ClipboardManager(
            agent_id="agent-1",
            cwd=tmp_path,
            permissions=perms,
            home_dir=tmp_path / "home",
        )
        manager1.copy(
            key="ephemeral",
            content="Ephemeral content",
            scope=ClipboardScope.AGENT,
        )
        manager1.close()

        # New manager (even same agent_id) should NOT see it
        manager2 = ClipboardManager(
            agent_id="agent-1",
            cwd=tmp_path,
            permissions=perms,
            home_dir=tmp_path / "home",
        )

        retrieved = manager2.get("ephemeral", ClipboardScope.AGENT)
        assert retrieved is None
        manager2.close()


class TestSearch:
    """P7.7 - Test search finds entries by content substring."""

    @pytest.mark.asyncio
    async def test_search_finds_by_content(self, tmp_path: Path) -> None:
        """Search finds entries matching content."""
        services = create_services_with_clipboard(tmp_path)
        manager = services.get("clipboard_manager")

        # Create entries with different content
        manager.copy("entry1", "Hello World", scope=ClipboardScope.AGENT)
        manager.copy("entry2", "Goodbye Moon", scope=ClipboardScope.AGENT)
        manager.copy("entry3", "Hello Again", scope=ClipboardScope.AGENT)

        # Search for "Hello"
        results = manager.search("Hello")
        assert len(results) == 2
        keys = [r.key for r in results]
        assert "entry1" in keys
        assert "entry3" in keys
        assert "entry2" not in keys

    @pytest.mark.asyncio
    async def test_search_finds_by_key(self, tmp_path: Path) -> None:
        """Search finds entries matching key name."""
        services = create_services_with_clipboard(tmp_path)
        manager = services.get("clipboard_manager")

        manager.copy("config-file", "Some content", scope=ClipboardScope.AGENT)
        manager.copy("data-file", "Other content", scope=ClipboardScope.AGENT)

        results = manager.search("config")
        assert len(results) == 1
        assert results[0].key == "config-file"

    @pytest.mark.asyncio
    async def test_search_finds_by_description(self, tmp_path: Path) -> None:
        """Search finds entries matching description."""
        services = create_services_with_clipboard(tmp_path)
        manager = services.get("clipboard_manager")

        manager.copy("entry1", "Content", scope=ClipboardScope.AGENT, short_description="Important data")
        manager.copy("entry2", "Content", scope=ClipboardScope.AGENT, short_description="Unrelated stuff")

        results = manager.search("Important")
        assert len(results) == 1
        assert results[0].key == "entry1"

    @pytest.mark.asyncio
    async def test_search_skill_integration(self, tmp_path: Path) -> None:
        """Search skill returns formatted results."""
        services = create_services_with_clipboard(tmp_path)
        manager = services.get("clipboard_manager")

        manager.copy("test-entry", "Searchable content", scope=ClipboardScope.AGENT)

        search_skill = clipboard_search_factory(services)
        result = await search_skill.execute(query="Searchable")

        assert not result.error, f"Unexpected error: {result.error}"
        assert "Found 1 match" in result.output
        assert "test-entry" in result.output


class TestTags:
    """P7.8 - Test tags filter entries correctly."""

    def test_filter_by_single_tag(self, tmp_path: Path) -> None:
        """Filter entries by a single tag."""
        perms = CLIPBOARD_PRESETS["yolo"]
        manager = ClipboardManager(
            agent_id="test",
            cwd=tmp_path,
            permissions=perms,
            home_dir=tmp_path / "home",
        )

        manager.copy("entry1", "Content 1", scope=ClipboardScope.AGENT, tags=["important"])
        manager.copy("entry2", "Content 2", scope=ClipboardScope.AGENT, tags=["urgent"])
        manager.copy("entry3", "Content 3", scope=ClipboardScope.AGENT, tags=["important", "urgent"])

        # Filter by "important" tag
        results = manager.list_entries(tags=["important"])
        assert len(results) == 2
        keys = [r.key for r in results]
        assert "entry1" in keys
        assert "entry3" in keys

        manager.close()

    def test_filter_by_multiple_tags_and_logic(self, tmp_path: Path) -> None:
        """Filter by multiple tags uses AND logic."""
        perms = CLIPBOARD_PRESETS["yolo"]
        manager = ClipboardManager(
            agent_id="test",
            cwd=tmp_path,
            permissions=perms,
            home_dir=tmp_path / "home",
        )

        manager.copy("entry1", "Content 1", scope=ClipboardScope.AGENT, tags=["important"])
        manager.copy("entry2", "Content 2", scope=ClipboardScope.AGENT, tags=["urgent"])
        manager.copy("entry3", "Content 3", scope=ClipboardScope.AGENT, tags=["important", "urgent"])

        # Filter by both tags (AND logic - must have ALL)
        results = manager.list_entries(tags=["important", "urgent"])
        assert len(results) == 1
        assert results[0].key == "entry3"

        manager.close()

    def test_filter_by_any_tags_or_logic(self, tmp_path: Path) -> None:
        """Filter by any_tags uses OR logic."""
        perms = CLIPBOARD_PRESETS["yolo"]
        manager = ClipboardManager(
            agent_id="test",
            cwd=tmp_path,
            permissions=perms,
            home_dir=tmp_path / "home",
        )

        manager.copy("entry1", "Content 1", scope=ClipboardScope.AGENT, tags=["alpha"])
        manager.copy("entry2", "Content 2", scope=ClipboardScope.AGENT, tags=["beta"])
        manager.copy("entry3", "Content 3", scope=ClipboardScope.AGENT, tags=["gamma"])

        # Filter by any of alpha OR beta
        results = manager.list_entries(any_tags=["alpha", "beta"])
        assert len(results) == 2
        keys = [r.key for r in results]
        assert "entry1" in keys
        assert "entry2" in keys

        manager.close()

    @pytest.mark.asyncio
    async def test_tag_skill_add_remove(self, tmp_path: Path) -> None:
        """Tag skill can add and remove tags."""
        services = create_services_with_clipboard(tmp_path)
        manager = services.get("clipboard_manager")

        # Create entry without tags
        manager.copy("test-entry", "Content", scope=ClipboardScope.AGENT)

        tag_skill = clipboard_tag_factory(services)

        # Add a tag
        result = await tag_skill.execute(
            action="add",
            name="new-tag",
            entry_key="test-entry",
            scope="agent",
        )
        assert not result.error, f"Unexpected error: {result.error}"

        # Verify tag was added
        entry = manager.get("test-entry")
        assert "new-tag" in entry.tags

        # Remove the tag
        result = await tag_skill.execute(
            action="remove",
            name="new-tag",
            entry_key="test-entry",
            scope="agent",
        )
        assert not result.error, f"Unexpected error: {result.error}"

        # Verify tag was removed
        entry = manager.get("test-entry")
        assert "new-tag" not in entry.tags


class TestImportExport:
    """P7.9 - Test import/export roundtrip preserves entries."""

    @pytest.mark.asyncio
    async def test_export_creates_valid_json(self, tmp_path: Path) -> None:
        """Export creates valid JSON file with entries."""
        services = create_services_with_clipboard(tmp_path)
        manager = services.get("clipboard_manager")

        # Create some entries
        manager.copy("entry1", "Content 1", scope=ClipboardScope.AGENT, short_description="First")
        manager.copy("entry2", "Content 2", scope=ClipboardScope.AGENT, tags=["tag1"])

        export_skill = clipboard_export_factory(services)
        export_path = tmp_path / "export.json"

        result = await export_skill.execute(path=str(export_path), scope="agent")
        assert not result.error, f"Unexpected error: {result.error}"
        assert "Exported 2 entries" in result.output

        # Verify JSON is valid
        data = json.loads(export_path.read_text(encoding="utf-8"))
        assert data["version"] == "1.0"
        assert data["entry_count"] == 2
        assert len(data["entries"]) == 2

    @pytest.mark.asyncio
    async def test_import_export_roundtrip(self, tmp_path: Path) -> None:
        """Export entries and import them back preserves all fields."""
        services = create_services_with_clipboard(tmp_path)
        manager = services.get("clipboard_manager")

        # Create entries with various fields
        manager.copy(
            "roundtrip-entry",
            "Test content\nWith multiple lines",
            scope=ClipboardScope.AGENT,
            short_description="Test description",
            tags=["tag1", "tag2"],
        )

        export_skill = clipboard_export_factory(services)
        import_skill = clipboard_import_factory(services)

        export_path = tmp_path / "roundtrip.json"

        # Export
        result = await export_skill.execute(path=str(export_path), scope="agent")
        assert not result.error, f"Unexpected error: {result.error}"

        # Clear clipboard
        manager.clear(ClipboardScope.AGENT)
        assert manager.get("roundtrip-entry") is None

        # Import back (dry_run=false to actually import)
        result = await import_skill.execute(
            path=str(export_path),
            scope="agent",
            dry_run=False,
        )
        assert not result.error, f"Unexpected error: {result.error}"
        assert "Imported 1 entries" in result.output

        # Verify entry is restored with all fields
        restored = manager.get("roundtrip-entry")
        assert restored is not None
        assert restored.content == "Test content\nWith multiple lines"
        assert restored.short_description == "Test description"
        assert "tag1" in restored.tags
        assert "tag2" in restored.tags

    @pytest.mark.asyncio
    async def test_import_dry_run(self, tmp_path: Path) -> None:
        """Import with dry_run=True shows what would be imported."""
        services = create_services_with_clipboard(tmp_path)
        manager = services.get("clipboard_manager")

        # Create and export an entry
        manager.copy("dry-run-test", "Content", scope=ClipboardScope.AGENT)

        export_skill = clipboard_export_factory(services)
        import_skill = clipboard_import_factory(services)

        export_path = tmp_path / "dry_run.json"
        await export_skill.execute(path=str(export_path), scope="agent")

        # Clear and import with dry_run=True (default)
        manager.clear(ClipboardScope.AGENT)

        result = await import_skill.execute(path=str(export_path), scope="agent")

        assert not result.error, f"Unexpected error: {result.error}"
        assert "Dry run" in result.output
        assert "would import 1 entries" in result.output

        # Entry should NOT actually be imported
        assert manager.get("dry-run-test") is None

    @pytest.mark.asyncio
    async def test_import_conflict_skip(self, tmp_path: Path) -> None:
        """Import with conflict=skip skips existing entries."""
        services = create_services_with_clipboard(tmp_path)
        manager = services.get("clipboard_manager")

        # Create entry
        manager.copy("existing", "Original content", scope=ClipboardScope.AGENT)

        export_skill = clipboard_export_factory(services)
        import_skill = clipboard_import_factory(services)

        export_path = tmp_path / "conflict.json"
        await export_skill.execute(path=str(export_path), scope="agent")

        # Modify the entry
        manager.delete("existing", ClipboardScope.AGENT)
        manager.copy("existing", "Modified content", scope=ClipboardScope.AGENT)

        # Import with skip - should skip the existing entry
        result = await import_skill.execute(
            path=str(export_path),
            scope="agent",
            conflict="skip",
            dry_run=False,
        )

        assert not result.error, f"Unexpected error: {result.error}"
        assert "skipped 1" in result.output

        # Original modified content should remain
        entry = manager.get("existing")
        assert entry.content == "Modified content"

    @pytest.mark.asyncio
    async def test_import_conflict_overwrite(self, tmp_path: Path) -> None:
        """Import with conflict=overwrite replaces existing entries."""
        services = create_services_with_clipboard(tmp_path)
        manager = services.get("clipboard_manager")

        # Create entry
        manager.copy("to-overwrite", "Original content", scope=ClipboardScope.AGENT)

        export_skill = clipboard_export_factory(services)
        import_skill = clipboard_import_factory(services)

        export_path = tmp_path / "overwrite.json"
        await export_skill.execute(path=str(export_path), scope="agent")

        # Modify the entry
        manager.delete("to-overwrite", ClipboardScope.AGENT)
        manager.copy("to-overwrite", "Modified content", scope=ClipboardScope.AGENT)

        # Import with overwrite - should replace
        result = await import_skill.execute(
            path=str(export_path),
            scope="agent",
            conflict="overwrite",
            dry_run=False,
        )

        assert not result.error, f"Unexpected error: {result.error}"
        assert "1 overwritten" in result.output

        # Original exported content should be restored
        entry = manager.get("to-overwrite")
        assert entry.content == "Original content"


class TestPasteInsertionModes:
    """Additional tests for paste insertion modes."""

    @pytest.mark.asyncio
    async def test_paste_prepend(self, tmp_path: Path) -> None:
        """Paste with prepend mode adds to beginning."""
        services = create_services_with_clipboard(tmp_path)
        manager = services.get("clipboard_manager")

        # Create clipboard entry
        manager.copy("prepend-test", "New Header\n", scope=ClipboardScope.AGENT)

        # Create target file
        target = tmp_path / "target.txt"
        target.write_text("Existing content\n", encoding="utf-8")

        paste_skill = paste_skill_factory(services)
        result = await paste_skill.execute(
            key="prepend-test",
            target=str(target),
            mode="prepend",
        )

        assert not result.error, f"Unexpected error: {result.error}"
        content = target.read_text(encoding="utf-8")
        assert content.startswith("New Header")

    @pytest.mark.asyncio
    async def test_paste_after_line(self, tmp_path: Path) -> None:
        """Paste with after_line mode inserts after specified line."""
        services = create_services_with_clipboard(tmp_path)
        manager = services.get("clipboard_manager")

        manager.copy("insert-test", "Inserted line", scope=ClipboardScope.AGENT)

        target = tmp_path / "target.txt"
        target.write_text("Line 1\nLine 2\nLine 3\n", encoding="utf-8")

        paste_skill = paste_skill_factory(services)
        result = await paste_skill.execute(
            key="insert-test",
            target=str(target),
            mode="after_line",
            line_number=1,
        )

        assert not result.error, f"Unexpected error: {result.error}"
        lines = target.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "Line 1"
        assert lines[1] == "Inserted line"
        assert lines[2] == "Line 2"

    @pytest.mark.asyncio
    async def test_paste_replace_lines(self, tmp_path: Path) -> None:
        """Paste with replace_lines mode replaces specified range."""
        services = create_services_with_clipboard(tmp_path)
        manager = services.get("clipboard_manager")

        manager.copy("replace-test", "Replacement", scope=ClipboardScope.AGENT)

        target = tmp_path / "target.txt"
        target.write_text("Keep\nReplace 1\nReplace 2\nKeep too\n", encoding="utf-8")

        paste_skill = paste_skill_factory(services)
        result = await paste_skill.execute(
            key="replace-test",
            target=str(target),
            mode="replace_lines",
            start_line=2,
            end_line=3,
        )

        assert not result.error, f"Unexpected error: {result.error}"
        content = target.read_text(encoding="utf-8")
        assert "Keep" in content
        assert "Replacement" in content
        assert "Keep too" in content
        assert "Replace 1" not in content
        assert "Replace 2" not in content


class TestEdgeCases:
    """Edge case and error handling tests."""

    @pytest.mark.asyncio
    async def test_copy_nonexistent_file(self, tmp_path: Path) -> None:
        """Copy from nonexistent file returns error."""
        services = create_services_with_clipboard(tmp_path)
        copy_skill = copy_factory(services)

        result = await copy_skill.execute(
            source=str(tmp_path / "nonexistent.txt"),
            key="fail",
            scope="agent",
        )

        assert result.error
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_paste_nonexistent_key(self, tmp_path: Path) -> None:
        """Paste with nonexistent key returns error."""
        services = create_services_with_clipboard(tmp_path)
        paste_skill = paste_skill_factory(services)

        target = tmp_path / "target.txt"
        target.write_text("Content", encoding="utf-8")

        result = await paste_skill.execute(
            key="nonexistent",
            target=str(target),
        )

        assert result.error
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_duplicate_key_error(self, tmp_path: Path) -> None:
        """Copying with duplicate key returns error."""
        services = create_services_with_clipboard(tmp_path)

        source = tmp_path / "source.txt"
        source.write_text("Content", encoding="utf-8")

        copy_skill = copy_factory(services)

        # First copy succeeds
        result = await copy_skill.execute(
            source=str(source),
            key="duplicate",
            scope="agent",
        )
        assert not result.error, f"Unexpected error: {result.error}"

        # Second copy with same key fails
        result = await copy_skill.execute(
            source=str(source),
            key="duplicate",
            scope="agent",
        )
        assert result.error
        assert "already exists" in result.error.lower()

    def test_clipboard_manager_no_service(self) -> None:
        """Skills handle missing clipboard_manager gracefully."""
        services = ServiceContainer()
        # No clipboard_manager registered

        # Skills should return error, not crash
        skill = ClipboardListSkill(services)

        async def run_test() -> ToolResult:
            return await skill.execute()

        result = asyncio.get_event_loop().run_until_complete(run_test())
        assert result.error
        assert "not available" in result.error.lower()
