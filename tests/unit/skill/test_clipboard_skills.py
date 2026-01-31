"""Tests for copy, cut, and paste clipboard skills."""

import pytest

from nexus3.clipboard import ClipboardManager, ClipboardScope, CLIPBOARD_PRESETS
from nexus3.core.types import ToolResult
from nexus3.skill.builtin.clipboard_copy import copy_factory, cut_factory
from nexus3.skill.builtin.clipboard_paste import paste_skill_factory
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
def copy_skill(services):
    """Create copy skill instance."""
    return copy_factory(services)


@pytest.fixture
def cut_skill(services):
    """Create cut skill instance."""
    return cut_factory(services)


@pytest.fixture
def paste_skill(services):
    """Create paste skill instance."""
    return paste_skill_factory(services)


@pytest.fixture
def test_file(tmp_path):
    """Create a test file with multiple lines."""
    content = """line 1
line 2
line 3
line 4
line 5
"""
    test_file = tmp_path / "test.txt"
    test_file.write_text(content)
    return test_file


@pytest.fixture
def source_file(tmp_path):
    """Create a source file for copy/cut operations."""
    content = """def hello():
    print("Hello, World!")

def goodbye():
    print("Goodbye!")
"""
    f = tmp_path / "source.py"
    f.write_text(content)
    return f


@pytest.fixture
def target_file(tmp_path):
    """Create a target file for paste operations."""
    content = """# Header comment
# Another comment

def existing():
    pass
"""
    f = tmp_path / "target.py"
    f.write_text(content)
    return f


# =============================================================================
# CopySkill Tests
# =============================================================================


class TestCopySkill:
    """Tests for CopySkill."""

    @pytest.mark.asyncio
    async def test_copy_whole_file(self, copy_skill, source_file, clipboard_manager):
        """Test copying entire file to clipboard."""
        result = await copy_skill.execute(
            source=str(source_file),
            key="whole-file",
        )

        assert result.success
        assert "Copied to clipboard 'whole-file'" in result.output
        assert "agent scope" in result.output

        # Verify clipboard content
        entry = clipboard_manager.get("whole-file")
        assert entry is not None
        assert "def hello():" in entry.content
        assert "def goodbye():" in entry.content

    @pytest.mark.asyncio
    async def test_copy_line_range(self, copy_skill, source_file, clipboard_manager):
        """Test copying specific line range."""
        result = await copy_skill.execute(
            source=str(source_file),
            key="line-range",
            start_line=1,
            end_line=2,
        )

        assert result.success
        assert "Lines: 1-2" in result.output

        entry = clipboard_manager.get("line-range")
        assert entry is not None
        assert "def hello():" in entry.content
        assert '    print("Hello, World!")' in entry.content
        assert "def goodbye():" not in entry.content

    @pytest.mark.asyncio
    async def test_copy_with_tags_and_ttl(self, copy_skill, source_file, clipboard_manager):
        """Test copying with tags and TTL."""
        result = await copy_skill.execute(
            source=str(source_file),
            key="tagged-entry",
            tags=["refactor", "python"],
            ttl_seconds=3600,
            short_description="Function definitions",
        )

        assert result.success

        entry = clipboard_manager.get("tagged-entry")
        assert entry is not None
        assert "refactor" in entry.tags
        assert "python" in entry.tags
        assert entry.ttl_seconds == 3600
        assert entry.short_description == "Function definitions"

    @pytest.mark.asyncio
    async def test_copy_invalid_path_returns_error(self, copy_skill):
        """Test that invalid path returns error."""
        result = await copy_skill.execute(
            source="/nonexistent/path/file.txt",
            key="invalid",
        )

        assert not result.success
        assert "not found" in result.error.lower() or "no such file" in result.error.lower()

    @pytest.mark.asyncio
    async def test_copy_missing_clipboard_manager_returns_error(self, tmp_path):
        """Test that missing clipboard manager returns error."""
        # Create services without clipboard manager
        services = ServiceContainer()
        services.register("cwd", str(tmp_path))
        skill = copy_factory(services)

        # Create a temp file
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        result = await skill.execute(
            source=str(test_file),
            key="test",
        )

        assert not result.success
        assert "not available" in result.error.lower()

    @pytest.mark.asyncio
    async def test_copy_duplicate_key_returns_error(self, copy_skill, source_file, clipboard_manager):
        """Test that duplicate key returns error."""
        # First copy succeeds
        result1 = await copy_skill.execute(
            source=str(source_file),
            key="duplicate-key",
        )
        assert result1.success

        # Second copy with same key fails
        result2 = await copy_skill.execute(
            source=str(source_file),
            key="duplicate-key",
        )
        assert not result2.success
        assert "already exists" in result2.error.lower()

    @pytest.mark.asyncio
    async def test_copy_empty_file_returns_error(self, copy_skill, tmp_path):
        """Test that copying empty file returns error."""
        empty_file = tmp_path / "empty.txt"
        empty_file.write_text("")

        result = await copy_skill.execute(
            source=str(empty_file),
            key="empty",
        )

        assert not result.success
        assert "empty" in result.error.lower()

    @pytest.mark.asyncio
    async def test_copy_missing_key_returns_error(self, copy_skill, source_file):
        """Test that missing key parameter returns error."""
        result = await copy_skill.execute(
            source=str(source_file),
            key="",
        )

        assert not result.success
        assert "required" in result.error.lower() or "key" in result.error.lower()

    @pytest.mark.asyncio
    async def test_copy_to_project_scope(self, copy_skill, source_file, clipboard_manager):
        """Test copying to project scope."""
        result = await copy_skill.execute(
            source=str(source_file),
            key="project-entry",
            scope="project",
        )

        assert result.success
        assert "project scope" in result.output

        entry = clipboard_manager.get("project-entry", ClipboardScope.PROJECT)
        assert entry is not None

    @pytest.mark.asyncio
    async def test_copy_invalid_line_range(self, copy_skill, source_file):
        """Test error on invalid line range."""
        result = await copy_skill.execute(
            source=str(source_file),
            key="bad-range",
            start_line=100,  # Beyond file length
        )

        assert not result.success
        assert "exceeds" in result.error.lower() or "line" in result.error.lower()


# =============================================================================
# CutSkill Tests
# =============================================================================


class TestCutSkill:
    """Tests for CutSkill."""

    @pytest.mark.asyncio
    async def test_cut_line_range_removes_lines(self, cut_skill, source_file, clipboard_manager):
        """Test cutting line range removes lines from source."""
        original_content = source_file.read_text()
        assert "def hello():" in original_content

        result = await cut_skill.execute(
            source=str(source_file),
            key="cut-lines",
            start_line=1,
            end_line=2,
        )

        assert result.success
        assert "Lines removed: 1-2" in result.output

        # Verify clipboard has the cut content
        entry = clipboard_manager.get("cut-lines")
        assert entry is not None
        assert "def hello():" in entry.content

        # Verify source file no longer has cut lines
        new_content = source_file.read_text()
        assert "def hello():" not in new_content
        assert "def goodbye():" in new_content  # Rest preserved

    @pytest.mark.asyncio
    async def test_cut_whole_file_clears_content(self, cut_skill, source_file, clipboard_manager):
        """Test cutting whole file clears content but keeps file."""
        result = await cut_skill.execute(
            source=str(source_file),
            key="cut-all",
        )

        assert result.success
        assert "content cleared" in result.output.lower()

        # Verify clipboard has all content
        entry = clipboard_manager.get("cut-all")
        assert entry is not None
        assert "def hello():" in entry.content
        assert "def goodbye():" in entry.content

        # Verify file exists but is empty
        assert source_file.exists()
        assert source_file.read_text() == ""

    @pytest.mark.asyncio
    async def test_cut_with_tags(self, cut_skill, source_file, clipboard_manager):
        """Test cutting with tags."""
        result = await cut_skill.execute(
            source=str(source_file),
            key="tagged-cut",
            start_line=1,
            end_line=2,
            tags=["move", "refactor"],
        )

        assert result.success

        entry = clipboard_manager.get("tagged-cut")
        assert entry is not None
        assert "move" in entry.tags
        assert "refactor" in entry.tags

    @pytest.mark.asyncio
    async def test_cut_preserves_remaining_lines(self, cut_skill, test_file, clipboard_manager):
        """Test that cut preserves lines before and after cut range."""
        # test_file has lines 1-5
        result = await cut_skill.execute(
            source=str(test_file),
            key="middle-cut",
            start_line=2,
            end_line=4,
        )

        assert result.success

        # Verify clipboard has lines 2-4
        entry = clipboard_manager.get("middle-cut")
        assert "line 2" in entry.content
        assert "line 3" in entry.content
        assert "line 4" in entry.content

        # Verify file has only lines 1 and 5
        remaining = test_file.read_text()
        assert "line 1" in remaining
        assert "line 5" in remaining
        assert "line 2" not in remaining
        assert "line 3" not in remaining
        assert "line 4" not in remaining

    @pytest.mark.asyncio
    async def test_cut_missing_file_returns_error(self, cut_skill):
        """Test that cutting missing file returns error."""
        result = await cut_skill.execute(
            source="/nonexistent/file.txt",
            key="missing",
        )

        assert not result.success
        assert "not found" in result.error.lower()


# =============================================================================
# PasteSkill Tests
# =============================================================================


class TestPasteSkill:
    """Tests for PasteSkill."""

    @pytest.fixture
    def setup_clipboard(self, clipboard_manager):
        """Add some entries to clipboard for paste tests."""
        clipboard_manager.copy(
            key="snippet",
            content="# Pasted content\ndef pasted():\n    pass\n",
            scope=ClipboardScope.AGENT,
        )
        clipboard_manager.copy(
            key="single-line",
            content="# Single line",
            scope=ClipboardScope.AGENT,
        )
        return clipboard_manager

    @pytest.mark.asyncio
    async def test_paste_append_mode(self, paste_skill, target_file, setup_clipboard):
        """Test paste with append mode (default)."""
        result = await paste_skill.execute(
            key="snippet",
            target=str(target_file),
            mode="append",
        )

        assert result.success
        assert "appended" in result.output

        content = target_file.read_text()
        assert "def existing():" in content
        assert "def pasted():" in content
        # Pasted content should be at the end
        assert content.index("def existing():") < content.index("def pasted():")

    @pytest.mark.asyncio
    async def test_paste_prepend_mode(self, paste_skill, target_file, setup_clipboard):
        """Test paste with prepend mode."""
        result = await paste_skill.execute(
            key="snippet",
            target=str(target_file),
            mode="prepend",
        )

        assert result.success
        assert "prepended" in result.output

        content = target_file.read_text()
        assert "def existing():" in content
        assert "def pasted():" in content
        # Pasted content should be at the beginning
        assert content.index("def pasted():") < content.index("def existing():")

    @pytest.mark.asyncio
    async def test_paste_after_line_mode(self, paste_skill, target_file, setup_clipboard):
        """Test paste with after_line mode."""
        result = await paste_skill.execute(
            key="single-line",
            target=str(target_file),
            mode="after_line",
            line_number=2,
        )

        assert result.success
        assert "after line 2" in result.output

        content = target_file.read_text()
        lines = content.split("\n")
        # Line 2 is "# Another comment", pasted content should be after it
        assert lines[0] == "# Header comment"
        assert lines[1] == "# Another comment"
        assert lines[2] == "# Single line"

    @pytest.mark.asyncio
    async def test_paste_before_line_mode(self, paste_skill, target_file, setup_clipboard):
        """Test paste with before_line mode."""
        result = await paste_skill.execute(
            key="single-line",
            target=str(target_file),
            mode="before_line",
            line_number=1,
        )

        assert result.success
        assert "before line 1" in result.output

        content = target_file.read_text()
        lines = content.split("\n")
        # Pasted content should be first
        assert lines[0] == "# Single line"
        assert lines[1] == "# Header comment"

    @pytest.mark.asyncio
    async def test_paste_replace_lines_mode(self, paste_skill, target_file, setup_clipboard):
        """Test paste with replace_lines mode."""
        result = await paste_skill.execute(
            key="single-line",
            target=str(target_file),
            mode="replace_lines",
            start_line=1,
            end_line=2,
        )

        assert result.success
        assert "replaced lines 1-2" in result.output

        content = target_file.read_text()
        # Lines 1-2 were comment headers, now replaced
        assert "# Header comment" not in content
        assert "# Another comment" not in content
        assert "# Single line" in content
        assert "def existing():" in content  # Rest preserved

    @pytest.mark.asyncio
    async def test_paste_at_marker_replace_mode(self, paste_skill, tmp_path, setup_clipboard):
        """Test paste with at_marker_replace mode."""
        marker_file = tmp_path / "marker.txt"
        marker_file.write_text("before\n{{MARKER}}\nafter\n")

        result = await paste_skill.execute(
            key="single-line",
            target=str(marker_file),
            mode="at_marker_replace",
            marker="{{MARKER}}",
        )

        assert result.success
        assert "replaced marker" in result.output

        content = marker_file.read_text()
        assert "{{MARKER}}" not in content
        assert "# Single line" in content
        assert "before" in content
        assert "after" in content

    @pytest.mark.asyncio
    async def test_paste_at_marker_after_mode(self, paste_skill, tmp_path, setup_clipboard):
        """Test paste with at_marker_after mode."""
        marker_file = tmp_path / "marker.txt"
        marker_file.write_text("line with MARKER here\nfinal line\n")

        result = await paste_skill.execute(
            key="single-line",
            target=str(marker_file),
            mode="at_marker_after",
            marker="MARKER",
        )

        assert result.success
        assert "after marker" in result.output

        content = marker_file.read_text()
        lines = content.split("\n")
        # Pasted after line containing MARKER
        assert "MARKER" in lines[0]
        assert lines[1] == "# Single line"

    @pytest.mark.asyncio
    async def test_paste_key_not_found_returns_error(self, paste_skill, target_file, clipboard_manager):
        """Test that missing key returns error."""
        result = await paste_skill.execute(
            key="nonexistent-key",
            target=str(target_file),
        )

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_paste_create_if_missing(self, paste_skill, tmp_path, setup_clipboard):
        """Test create_if_missing creates new file."""
        new_file = tmp_path / "new_file.txt"
        assert not new_file.exists()

        result = await paste_skill.execute(
            key="snippet",
            target=str(new_file),
            mode="append",
            create_if_missing=True,
        )

        assert result.success
        assert new_file.exists()
        content = new_file.read_text()
        assert "def pasted():" in content

    @pytest.mark.asyncio
    async def test_paste_file_not_found_without_create(self, paste_skill, tmp_path, setup_clipboard):
        """Test error when file doesn't exist and create_if_missing is False."""
        new_file = tmp_path / "missing.txt"

        result = await paste_skill.execute(
            key="snippet",
            target=str(new_file),
        )

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_paste_invalid_mode_returns_error(self, paste_skill, target_file, setup_clipboard):
        """Test that invalid mode returns error."""
        result = await paste_skill.execute(
            key="snippet",
            target=str(target_file),
            mode="invalid_mode",
        )

        assert not result.success
        # Error may come from JSON schema validation or skill logic
        assert "mode" in result.error.lower()

    @pytest.mark.asyncio
    async def test_paste_missing_line_number_for_after_line(self, paste_skill, target_file, setup_clipboard):
        """Test error when line_number missing for after_line mode."""
        result = await paste_skill.execute(
            key="snippet",
            target=str(target_file),
            mode="after_line",
            # line_number missing
        )

        assert not result.success
        assert "line_number" in result.error.lower()

    @pytest.mark.asyncio
    async def test_paste_missing_marker_for_marker_mode(self, paste_skill, target_file, setup_clipboard):
        """Test error when marker missing for at_marker_* mode."""
        result = await paste_skill.execute(
            key="snippet",
            target=str(target_file),
            mode="at_marker_replace",
            # marker missing
        )

        assert not result.success
        assert "marker" in result.error.lower()

    @pytest.mark.asyncio
    async def test_paste_marker_not_found_returns_error(self, paste_skill, target_file, setup_clipboard):
        """Test error when marker not in file."""
        result = await paste_skill.execute(
            key="snippet",
            target=str(target_file),
            mode="at_marker_replace",
            marker="{{NONEXISTENT}}",
        )

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_paste_missing_clipboard_manager(self, tmp_path, target_file):
        """Test error when clipboard manager not available."""
        services = ServiceContainer()
        services.register("cwd", str(tmp_path))
        skill = paste_skill_factory(services)

        result = await skill.execute(
            key="test",
            target=str(target_file),
        )

        assert not result.success
        assert "not available" in result.error.lower()

    @pytest.mark.asyncio
    async def test_paste_with_explicit_scope(self, paste_skill, target_file, clipboard_manager):
        """Test paste with explicit scope specified."""
        # Add entry to project scope
        clipboard_manager.copy(
            key="project-snippet",
            content="# Project content\n",
            scope=ClipboardScope.PROJECT,
        )

        result = await paste_skill.execute(
            key="project-snippet",
            target=str(target_file),
            scope="project",
            mode="append",
        )

        assert result.success
        assert "project scope" in result.output

    @pytest.mark.asyncio
    async def test_paste_line_number_exceeds_file_length(self, paste_skill, target_file, setup_clipboard):
        """Test error when line number exceeds file length."""
        result = await paste_skill.execute(
            key="snippet",
            target=str(target_file),
            mode="after_line",
            line_number=1000,  # Way beyond file length
        )

        assert not result.success
        assert "exceeds" in result.error.lower()

    @pytest.mark.asyncio
    async def test_paste_replace_lines_end_before_start(self, paste_skill, target_file, setup_clipboard):
        """Test error when end_line < start_line in replace_lines mode."""
        result = await paste_skill.execute(
            key="snippet",
            target=str(target_file),
            mode="replace_lines",
            start_line=5,
            end_line=2,
        )

        assert not result.success
        assert "end_line" in result.error.lower()


# =============================================================================
# Integration Tests
# =============================================================================


class TestCopyPasteIntegration:
    """Integration tests for copy/paste workflow."""

    @pytest.mark.asyncio
    async def test_copy_then_paste(self, copy_skill, paste_skill, source_file, target_file, clipboard_manager):
        """Test full copy-paste workflow."""
        # Copy function from source
        copy_result = await copy_skill.execute(
            source=str(source_file),
            key="func",
            start_line=1,
            end_line=2,
        )
        assert copy_result.success

        # Paste into target
        paste_result = await paste_skill.execute(
            key="func",
            target=str(target_file),
            mode="append",
        )
        assert paste_result.success

        # Verify
        target_content = target_file.read_text()
        assert "def hello():" in target_content
        assert "def existing():" in target_content

    @pytest.mark.asyncio
    async def test_cut_then_paste_moves_content(
        self, cut_skill, paste_skill, source_file, target_file, clipboard_manager
    ):
        """Test full cut-paste workflow (move content)."""
        original_source = source_file.read_text()
        assert "def hello():" in original_source

        # Cut function from source
        cut_result = await cut_skill.execute(
            source=str(source_file),
            key="moved-func",
            start_line=1,
            end_line=2,
        )
        assert cut_result.success

        # Paste into target
        paste_result = await paste_skill.execute(
            key="moved-func",
            target=str(target_file),
            mode="prepend",
        )
        assert paste_result.success

        # Verify source no longer has the function
        source_content = source_file.read_text()
        assert "def hello():" not in source_content

        # Verify target has the function
        target_content = target_file.read_text()
        assert "def hello():" in target_content
