"""Tests for clipboard types module."""

import time
from unittest.mock import patch

import pytest

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


class TestClipboardScope:
    """Tests for ClipboardScope enum."""

    def test_scope_values(self) -> None:
        """ClipboardScope enum has expected values."""
        assert ClipboardScope.AGENT.value == "agent"
        assert ClipboardScope.PROJECT.value == "project"
        assert ClipboardScope.SYSTEM.value == "system"

    def test_scope_members(self) -> None:
        """ClipboardScope enum has exactly 3 members."""
        assert len(ClipboardScope) == 3


class TestInsertionMode:
    """Tests for InsertionMode enum."""

    def test_insertion_mode_values(self) -> None:
        """InsertionMode enum has expected values."""
        assert InsertionMode.AFTER_LINE.value == "after_line"
        assert InsertionMode.BEFORE_LINE.value == "before_line"
        assert InsertionMode.REPLACE_LINES.value == "replace_lines"
        assert InsertionMode.AT_MARKER_REPLACE.value == "at_marker_replace"
        assert InsertionMode.AT_MARKER_AFTER.value == "at_marker_after"
        assert InsertionMode.AT_MARKER_BEFORE.value == "at_marker_before"
        assert InsertionMode.APPEND.value == "append"
        assert InsertionMode.PREPEND.value == "prepend"

    def test_insertion_mode_members(self) -> None:
        """InsertionMode enum has exactly 8 members."""
        assert len(InsertionMode) == 8


class TestClipboardTag:
    """Tests for ClipboardTag dataclass."""

    def test_create_tag(self) -> None:
        """ClipboardTag can be created with required fields."""
        tag = ClipboardTag(id=1, name="important")
        assert tag.id == 1
        assert tag.name == "important"
        assert tag.description is None
        assert tag.created_at == 0.0

    def test_create_tag_with_optional_fields(self) -> None:
        """ClipboardTag can be created with optional fields."""
        now = time.time()
        tag = ClipboardTag(
            id=42,
            name="work",
            description="Work-related snippets",
            created_at=now,
        )
        assert tag.id == 42
        assert tag.name == "work"
        assert tag.description == "Work-related snippets"
        assert tag.created_at == now


class TestClipboardEntry:
    """Tests for ClipboardEntry dataclass."""

    def test_create_entry_minimal(self) -> None:
        """ClipboardEntry can be created with required fields."""
        entry = ClipboardEntry(
            key="my-snippet",
            scope=ClipboardScope.AGENT,
            content="hello world",
            line_count=1,
            byte_count=11,
        )
        assert entry.key == "my-snippet"
        assert entry.scope == ClipboardScope.AGENT
        assert entry.content == "hello world"
        assert entry.line_count == 1
        assert entry.byte_count == 11
        assert entry.tags == []

    def test_from_content_single_line(self) -> None:
        """from_content() correctly computes line/byte counts for single line."""
        entry = ClipboardEntry.from_content(
            key="test",
            scope=ClipboardScope.PROJECT,
            content="hello world",
        )
        assert entry.key == "test"
        assert entry.scope == ClipboardScope.PROJECT
        assert entry.content == "hello world"
        assert entry.line_count == 1
        assert entry.byte_count == 11

    def test_from_content_multiple_lines(self) -> None:
        """from_content() correctly computes line count for multi-line content."""
        content = "line1\nline2\nline3\n"
        entry = ClipboardEntry.from_content(
            key="multi",
            scope=ClipboardScope.SYSTEM,
            content=content,
        )
        # 3 lines ending with newline
        assert entry.line_count == 3
        assert entry.byte_count == len(content.encode("utf-8"))

    def test_from_content_no_trailing_newline(self) -> None:
        """from_content() counts final line without trailing newline."""
        content = "line1\nline2\nline3"  # No trailing newline
        entry = ClipboardEntry.from_content(
            key="multi",
            scope=ClipboardScope.AGENT,
            content=content,
        )
        # 3 lines (2 newlines + 1 for content after last newline)
        assert entry.line_count == 3

    def test_from_content_empty_content(self) -> None:
        """from_content() handles empty content."""
        entry = ClipboardEntry.from_content(
            key="empty",
            scope=ClipboardScope.AGENT,
            content="",
        )
        assert entry.line_count == 0
        assert entry.byte_count == 0

    def test_from_content_unicode(self) -> None:
        """from_content() correctly computes byte count for unicode content."""
        content = "Hello, \u4e16\u754c!"  # "Hello, world!" in Chinese
        entry = ClipboardEntry.from_content(
            key="unicode",
            scope=ClipboardScope.AGENT,
            content=content,
        )
        assert entry.line_count == 1
        # UTF-8 encoding: 7 ASCII + 6 bytes for 2 Chinese chars + 1 byte for !
        assert entry.byte_count == len(content.encode("utf-8"))

    def test_from_content_with_metadata(self) -> None:
        """from_content() sets optional metadata fields."""
        entry = ClipboardEntry.from_content(
            key="snippet",
            scope=ClipboardScope.PROJECT,
            content="def foo(): pass",
            short_description="A simple function",
            source_path="/path/to/file.py",
            source_lines="10-15",
            agent_id="test-agent",
            tags=["python", "function"],
        )
        assert entry.short_description == "A simple function"
        assert entry.source_path == "/path/to/file.py"
        assert entry.source_lines == "10-15"
        assert entry.created_by_agent == "test-agent"
        assert entry.modified_by_agent == "test-agent"
        assert entry.tags == ["python", "function"]

    def test_from_content_sets_timestamps(self) -> None:
        """from_content() sets created_at and modified_at to current time."""
        before = time.time()
        entry = ClipboardEntry.from_content(
            key="test",
            scope=ClipboardScope.AGENT,
            content="data",
        )
        after = time.time()

        assert before <= entry.created_at <= after
        assert before <= entry.modified_at <= after
        assert entry.created_at == entry.modified_at

    def test_from_content_with_ttl(self) -> None:
        """from_content() sets expires_at when ttl_seconds provided."""
        before = time.time()
        entry = ClipboardEntry.from_content(
            key="temp",
            scope=ClipboardScope.AGENT,
            content="temporary",
            ttl_seconds=3600,
        )
        after = time.time()

        assert entry.ttl_seconds == 3600
        assert entry.expires_at is not None
        assert before + 3600 <= entry.expires_at <= after + 3600

    def test_from_content_no_ttl(self) -> None:
        """from_content() sets expires_at to None when no ttl_seconds."""
        entry = ClipboardEntry.from_content(
            key="permanent",
            scope=ClipboardScope.AGENT,
            content="permanent",
        )
        assert entry.ttl_seconds is None
        assert entry.expires_at is None

    def test_is_expired_without_ttl(self) -> None:
        """is_expired returns False when no expires_at set."""
        entry = ClipboardEntry.from_content(
            key="test",
            scope=ClipboardScope.AGENT,
            content="data",
        )
        assert entry.is_expired is False

    def test_is_expired_not_yet(self) -> None:
        """is_expired returns False when expires_at is in the future."""
        entry = ClipboardEntry.from_content(
            key="test",
            scope=ClipboardScope.AGENT,
            content="data",
            ttl_seconds=3600,  # 1 hour from now
        )
        assert entry.is_expired is False

    def test_is_expired_past(self) -> None:
        """is_expired returns True when expires_at is in the past."""
        entry = ClipboardEntry(
            key="test",
            scope=ClipboardScope.AGENT,
            content="data",
            line_count=1,
            byte_count=4,
            expires_at=time.time() - 1,  # 1 second ago
        )
        assert entry.is_expired is True

    def test_is_expired_mocked_time(self) -> None:
        """is_expired correctly compares against current time (mocked)."""
        # Create entry that expires at t=1000
        entry = ClipboardEntry(
            key="test",
            scope=ClipboardScope.AGENT,
            content="data",
            line_count=1,
            byte_count=4,
            expires_at=1000.0,
        )

        # Before expiry
        with patch("time.time", return_value=999.0):
            assert entry.is_expired is False

        # At exact expiry time
        with patch("time.time", return_value=1000.0):
            assert entry.is_expired is True

        # After expiry
        with patch("time.time", return_value=1001.0):
            assert entry.is_expired is True


class TestClipboardPermissions:
    """Tests for ClipboardPermissions dataclass."""

    def test_default_permissions(self) -> None:
        """Default permissions only allow agent scope."""
        perms = ClipboardPermissions()
        assert perms.agent_scope is True
        assert perms.project_read is False
        assert perms.project_write is False
        assert perms.system_read is False
        assert perms.system_write is False

    def test_can_read_agent_scope(self) -> None:
        """can_read() returns correct value for agent scope."""
        perms_enabled = ClipboardPermissions(agent_scope=True)
        assert perms_enabled.can_read(ClipboardScope.AGENT) is True

        perms_disabled = ClipboardPermissions(agent_scope=False)
        assert perms_disabled.can_read(ClipboardScope.AGENT) is False

    def test_can_read_project_scope(self) -> None:
        """can_read() returns correct value for project scope."""
        perms_enabled = ClipboardPermissions(project_read=True)
        assert perms_enabled.can_read(ClipboardScope.PROJECT) is True

        perms_disabled = ClipboardPermissions(project_read=False)
        assert perms_disabled.can_read(ClipboardScope.PROJECT) is False

    def test_can_read_system_scope(self) -> None:
        """can_read() returns correct value for system scope."""
        perms_enabled = ClipboardPermissions(system_read=True)
        assert perms_enabled.can_read(ClipboardScope.SYSTEM) is True

        perms_disabled = ClipboardPermissions(system_read=False)
        assert perms_disabled.can_read(ClipboardScope.SYSTEM) is False

    def test_can_write_agent_scope(self) -> None:
        """can_write() returns correct value for agent scope."""
        perms_enabled = ClipboardPermissions(agent_scope=True)
        assert perms_enabled.can_write(ClipboardScope.AGENT) is True

        perms_disabled = ClipboardPermissions(agent_scope=False)
        assert perms_disabled.can_write(ClipboardScope.AGENT) is False

    def test_can_write_project_scope(self) -> None:
        """can_write() returns correct value for project scope."""
        perms_enabled = ClipboardPermissions(project_write=True)
        assert perms_enabled.can_write(ClipboardScope.PROJECT) is True

        perms_disabled = ClipboardPermissions(project_write=False)
        assert perms_disabled.can_write(ClipboardScope.PROJECT) is False

    def test_can_write_system_scope(self) -> None:
        """can_write() returns correct value for system scope."""
        perms_enabled = ClipboardPermissions(system_write=True)
        assert perms_enabled.can_write(ClipboardScope.SYSTEM) is True

        perms_disabled = ClipboardPermissions(system_write=False)
        assert perms_disabled.can_write(ClipboardScope.SYSTEM) is False

    def test_read_write_independent(self) -> None:
        """Read and write permissions are independent."""
        perms = ClipboardPermissions(
            project_read=True,
            project_write=False,
            system_read=False,
            system_write=True,
        )
        # Can read project but not write
        assert perms.can_read(ClipboardScope.PROJECT) is True
        assert perms.can_write(ClipboardScope.PROJECT) is False
        # Can write system but not read
        assert perms.can_read(ClipboardScope.SYSTEM) is False
        assert perms.can_write(ClipboardScope.SYSTEM) is True


class TestClipboardPresets:
    """Tests for CLIPBOARD_PRESETS configuration."""

    def test_presets_exist(self) -> None:
        """All expected presets are defined."""
        assert "yolo" in CLIPBOARD_PRESETS
        assert "trusted" in CLIPBOARD_PRESETS
        assert "sandboxed" in CLIPBOARD_PRESETS

    def test_yolo_preset_full_access(self) -> None:
        """YOLO preset has full access to all scopes."""
        yolo = CLIPBOARD_PRESETS["yolo"]
        assert yolo.agent_scope is True
        assert yolo.project_read is True
        assert yolo.project_write is True
        assert yolo.system_read is True
        assert yolo.system_write is True

    def test_trusted_preset(self) -> None:
        """Trusted preset can read/write project, read system (not write)."""
        trusted = CLIPBOARD_PRESETS["trusted"]
        assert trusted.agent_scope is True
        assert trusted.project_read is True
        assert trusted.project_write is True
        assert trusted.system_read is True
        assert trusted.system_write is False  # Cannot write to system

    def test_sandboxed_preset_agent_only(self) -> None:
        """Sandboxed preset only has agent scope access."""
        sandboxed = CLIPBOARD_PRESETS["sandboxed"]
        assert sandboxed.agent_scope is True
        assert sandboxed.project_read is False
        assert sandboxed.project_write is False
        assert sandboxed.system_read is False
        assert sandboxed.system_write is False


class TestSizeLimits:
    """Tests for clipboard size limit constants."""

    def test_max_entry_size(self) -> None:
        """MAX_ENTRY_SIZE_BYTES is 1 MB."""
        assert MAX_ENTRY_SIZE_BYTES == 1 * 1024 * 1024

    def test_warn_entry_size(self) -> None:
        """WARN_ENTRY_SIZE_BYTES is 100 KB."""
        assert WARN_ENTRY_SIZE_BYTES == 100 * 1024

    def test_warn_less_than_max(self) -> None:
        """Warning threshold is less than max size."""
        assert WARN_ENTRY_SIZE_BYTES < MAX_ENTRY_SIZE_BYTES
