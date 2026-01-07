"""Unit tests for the session logging system.

Tests cover:
- nexus3/session/types.py - LogStream, LogConfig, SessionInfo
- nexus3/session/storage.py - SessionStorage (SQLite operations)
- nexus3/session/markdown.py - MarkdownWriter, RawWriter
- nexus3/session/logging.py - SessionLogger
"""

import json
import re
from datetime import datetime
from pathlib import Path
from time import time

import pytest

from nexus3.core.types import Message, Role, ToolCall, ToolResult
from nexus3.session.logging import SessionLogger
from nexus3.session.markdown import MarkdownWriter, RawWriter
from nexus3.session.storage import (
    EventRow,
    MessageRow,
    SessionStorage,
)
from nexus3.session.types import LogConfig, LogStream, SessionInfo


# ============================================================================
# LogStream Tests
# ============================================================================


class TestLogStream:
    """Tests for LogStream flag combinations."""

    def test_none_value(self):
        """NONE has value 0."""
        assert LogStream.NONE.value == 0
        # Flag enums don't compare equal to int, but value does
        assert not LogStream.NONE  # NONE is falsy

    def test_individual_flags_are_powers_of_two(self):
        """Individual flags are distinct powers of two."""
        context = LogStream.CONTEXT.value
        verbose = LogStream.VERBOSE.value
        raw = LogStream.RAW.value

        # Each should be a single bit
        assert context > 0
        assert verbose > 0
        assert raw > 0

        # Should be distinct
        assert context != verbose
        assert verbose != raw
        assert context != raw

    def test_all_combines_all_flags(self):
        """ALL is a combination of CONTEXT, VERBOSE, and RAW."""
        all_streams = LogStream.ALL
        assert LogStream.CONTEXT in all_streams
        assert LogStream.VERBOSE in all_streams
        assert LogStream.RAW in all_streams

    def test_flag_combination_with_or(self):
        """Flags can be combined with | operator."""
        combined = LogStream.CONTEXT | LogStream.VERBOSE
        assert LogStream.CONTEXT in combined
        assert LogStream.VERBOSE in combined
        assert LogStream.RAW not in combined

    def test_flag_combination_with_raw(self):
        """CONTEXT and RAW can be combined without VERBOSE."""
        combined = LogStream.CONTEXT | LogStream.RAW
        assert LogStream.CONTEXT in combined
        assert LogStream.RAW in combined
        assert LogStream.VERBOSE not in combined

    def test_none_contains_nothing(self):
        """NONE contains no flags."""
        assert LogStream.CONTEXT not in LogStream.NONE
        assert LogStream.VERBOSE not in LogStream.NONE
        assert LogStream.RAW not in LogStream.NONE


# ============================================================================
# LogConfig Tests
# ============================================================================


class TestLogConfig:
    """Tests for LogConfig dataclass."""

    def test_default_values(self):
        """LogConfig has expected defaults."""
        config = LogConfig()
        assert config.base_dir == Path(".nexus3/logs")
        assert config.streams == LogStream.CONTEXT
        assert config.parent_session is None

    def test_custom_base_dir(self, tmp_path):
        """LogConfig accepts custom base_dir as Path."""
        config = LogConfig(base_dir=tmp_path / "custom_logs")
        assert config.base_dir == tmp_path / "custom_logs"

    def test_string_base_dir_converted_to_path(self):
        """LogConfig converts string base_dir to Path."""
        config = LogConfig(base_dir="/tmp/logs")  # type: ignore[arg-type]
        assert isinstance(config.base_dir, Path)
        assert config.base_dir == Path("/tmp/logs")

    def test_custom_streams(self):
        """LogConfig accepts custom streams."""
        config = LogConfig(streams=LogStream.ALL)
        assert config.streams == LogStream.ALL
        assert LogStream.VERBOSE in config.streams

    def test_parent_session(self):
        """LogConfig accepts parent_session."""
        config = LogConfig(parent_session="parent_123")
        assert config.parent_session == "parent_123"


# ============================================================================
# SessionInfo Tests
# ============================================================================


class TestSessionInfo:
    """Tests for SessionInfo dataclass."""

    def test_create_generates_valid_session_id(self, tmp_path):
        """SessionInfo.create() generates ID with timestamp and hex suffix."""
        info = SessionInfo.create(base_dir=tmp_path)

        # Session ID format: YYYY-MM-DD_HHMMSS_xxxxxx
        pattern = r"^\d{4}-\d{2}-\d{2}_\d{6}_[a-f0-9]{6}$"
        assert re.match(pattern, info.session_id), f"Invalid ID format: {info.session_id}"

    def test_create_generates_unique_ids(self, tmp_path):
        """Multiple calls generate different session IDs."""
        ids = {SessionInfo.create(base_dir=tmp_path).session_id for _ in range(10)}
        # Due to hex suffix, all should be unique (vanishingly small collision chance)
        assert len(ids) == 10

    def test_create_session_dir_for_top_level(self, tmp_path):
        """Top-level session dir is base_dir/session_id."""
        info = SessionInfo.create(base_dir=tmp_path)
        assert info.session_dir == tmp_path / info.session_id

    def test_create_session_dir_for_subagent(self, tmp_path):
        """Subagent session dir is nested under parent session dir.

        When creating a subagent, base_dir should be the parent's session_dir,
        and the subagent folder is created directly under it.
        """
        parent_session_dir = tmp_path / "2024-01-15_120000_abc123"
        parent_session_dir.mkdir(parents=True)
        parent_id = "2024-01-15_120000_abc123"

        info = SessionInfo.create(base_dir=parent_session_dir, parent_id=parent_id)

        assert info.parent_id == parent_id
        # Should be nested: parent_session_dir/subagent_xxxxxx
        assert info.session_dir.parent == parent_session_dir
        assert info.session_dir.name.startswith("subagent_")

    def test_create_sets_created_at(self, tmp_path):
        """SessionInfo.create() sets created_at to current time."""
        before = datetime.now()
        info = SessionInfo.create(base_dir=tmp_path)
        after = datetime.now()

        assert before <= info.created_at <= after

    def test_session_info_attributes(self, tmp_path):
        """SessionInfo has all expected attributes."""
        info = SessionInfo.create(base_dir=tmp_path, parent_id="parent_123")

        assert isinstance(info.session_id, str)
        assert isinstance(info.session_dir, Path)
        assert info.parent_id == "parent_123"
        assert isinstance(info.created_at, datetime)


# ============================================================================
# SessionStorage Tests
# ============================================================================


class TestSessionStorage:
    """Tests for SessionStorage SQLite operations."""

    @pytest.fixture
    def storage(self, tmp_path) -> SessionStorage:
        """Create a fresh SessionStorage instance."""
        db_path = tmp_path / "test.db"
        storage = SessionStorage(db_path)
        yield storage
        storage.close()

    def test_creates_database_file(self, tmp_path):
        """SessionStorage creates database file."""
        db_path = tmp_path / "subdir" / "test.db"
        storage = SessionStorage(db_path)

        assert db_path.exists()
        storage.close()

    def test_creates_schema(self, storage):
        """SessionStorage creates all expected tables."""
        conn = storage._get_conn()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}

        assert "messages" in tables
        assert "metadata" in tables
        assert "events" in tables
        assert "schema_version" in tables

    # --- Message Operations ---

    def test_insert_message_returns_id(self, storage):
        """insert_message returns the message ID."""
        msg_id = storage.insert_message(role="user", content="Hello")
        assert isinstance(msg_id, int)
        assert msg_id > 0

    def test_insert_message_sequential_ids(self, storage):
        """Sequential inserts produce sequential IDs."""
        id1 = storage.insert_message(role="user", content="First")
        id2 = storage.insert_message(role="assistant", content="Second")
        assert id2 == id1 + 1

    def test_insert_message_with_all_fields(self, storage):
        """insert_message stores all fields correctly."""
        tool_calls = [{"id": "tc1", "name": "test", "arguments": {"arg": "val"}}]
        ts = time()

        msg_id = storage.insert_message(
            role="assistant",
            content="Response",
            name="assistant_name",
            tool_call_id="call_123",
            tool_calls=tool_calls,
            tokens=150,
            timestamp=ts,
        )

        msg = storage.get_message(msg_id)
        assert msg is not None
        assert msg.role == "assistant"
        assert msg.content == "Response"
        assert msg.name == "assistant_name"
        assert msg.tool_call_id == "call_123"
        assert msg.tool_calls == tool_calls
        assert msg.tokens == 150
        assert msg.timestamp == ts
        assert msg.in_context is True

    def test_get_messages_in_context_only(self, storage):
        """get_messages with in_context_only=True filters correctly."""
        id1 = storage.insert_message(role="user", content="In context")
        id2 = storage.insert_message(role="assistant", content="Also in context")

        # Mark one as out of context
        storage.update_context_status([id1], in_context=False)

        messages = storage.get_messages(in_context_only=True)
        assert len(messages) == 1
        assert messages[0].content == "Also in context"

    def test_get_messages_all(self, storage):
        """get_messages with in_context_only=False returns all."""
        id1 = storage.insert_message(role="user", content="In context")
        storage.insert_message(role="assistant", content="Also in context")
        storage.update_context_status([id1], in_context=False)

        messages = storage.get_messages(in_context_only=False)
        assert len(messages) == 2

    def test_get_message_nonexistent(self, storage):
        """get_message returns None for nonexistent ID."""
        msg = storage.get_message(999)
        assert msg is None

    def test_update_context_status(self, storage):
        """update_context_status changes in_context flag."""
        id1 = storage.insert_message(role="user", content="Test1")
        id2 = storage.insert_message(role="user", content="Test2")

        storage.update_context_status([id1, id2], in_context=False)

        msg1 = storage.get_message(id1)
        msg2 = storage.get_message(id2)
        assert msg1 is not None and msg1.in_context is False
        assert msg2 is not None and msg2.in_context is False

    def test_update_context_status_empty_list(self, storage):
        """update_context_status handles empty list gracefully."""
        storage.update_context_status([], in_context=False)
        # Should not raise

    def test_mark_as_summary(self, storage):
        """mark_as_summary updates summary_of and marks replaced as out of context."""
        id1 = storage.insert_message(role="user", content="Old message 1")
        id2 = storage.insert_message(role="assistant", content="Old message 2")
        summary_id = storage.insert_message(role="assistant", content="Summary")

        storage.mark_as_summary(summary_id, replaced_ids=[id1, id2])

        summary = storage.get_message(summary_id)
        old1 = storage.get_message(id1)
        old2 = storage.get_message(id2)

        assert summary is not None and summary.summary_of == [id1, id2]
        assert old1 is not None and old1.in_context is False
        assert old2 is not None and old2.in_context is False

    def test_get_token_count(self, storage):
        """get_token_count sums tokens for in-context messages."""
        storage.insert_message(role="user", content="Test", tokens=100)
        storage.insert_message(role="assistant", content="Response", tokens=200)

        assert storage.get_token_count() == 300

    def test_get_token_count_excludes_out_of_context(self, storage):
        """get_token_count excludes out-of-context messages."""
        id1 = storage.insert_message(role="user", content="Test", tokens=100)
        storage.insert_message(role="assistant", content="Response", tokens=200)

        storage.update_context_status([id1], in_context=False)
        assert storage.get_token_count() == 200

    def test_get_token_count_handles_null(self, storage):
        """get_token_count handles messages without token counts."""
        storage.insert_message(role="user", content="Test")  # No tokens
        storage.insert_message(role="assistant", content="Response", tokens=200)

        assert storage.get_token_count() == 200

    # --- Metadata Operations ---

    def test_set_and_get_metadata(self, storage):
        """set_metadata and get_metadata work correctly."""
        storage.set_metadata("key1", "value1")
        assert storage.get_metadata("key1") == "value1"

    def test_get_metadata_nonexistent(self, storage):
        """get_metadata returns None for nonexistent key."""
        assert storage.get_metadata("nonexistent") is None

    def test_set_metadata_overwrites(self, storage):
        """set_metadata overwrites existing values."""
        storage.set_metadata("key", "original")
        storage.set_metadata("key", "updated")
        assert storage.get_metadata("key") == "updated"

    def test_get_all_metadata(self, storage):
        """get_all_metadata returns all key-value pairs."""
        storage.set_metadata("key1", "val1")
        storage.set_metadata("key2", "val2")

        metadata = storage.get_all_metadata()
        assert metadata == {"key1": "val1", "key2": "val2"}

    def test_get_all_metadata_empty(self, storage):
        """get_all_metadata returns empty dict when no metadata."""
        assert storage.get_all_metadata() == {}

    # --- Event Operations ---

    def test_insert_event_returns_id(self, storage):
        """insert_event returns the event ID."""
        event_id = storage.insert_event(event_type="test")
        assert isinstance(event_id, int)
        assert event_id > 0

    def test_insert_event_with_all_fields(self, storage):
        """insert_event stores all fields correctly."""
        msg_id = storage.insert_message(role="user", content="Test")
        ts = time()

        event_id = storage.insert_event(
            event_type="thinking",
            data={"content": "reasoning..."},
            message_id=msg_id,
            timestamp=ts,
        )

        events = storage.get_events()
        assert len(events) == 1
        assert events[0].id == event_id
        assert events[0].event_type == "thinking"
        assert events[0].data == {"content": "reasoning..."}
        assert events[0].message_id == msg_id
        assert events[0].timestamp == ts

    def test_get_events_filter_by_type(self, storage):
        """get_events filters by event_type."""
        storage.insert_event(event_type="thinking", data={"x": 1})
        storage.insert_event(event_type="timing", data={"x": 2})
        storage.insert_event(event_type="thinking", data={"x": 3})

        events = storage.get_events(event_type="thinking")
        assert len(events) == 2
        assert all(e.event_type == "thinking" for e in events)

    def test_get_events_filter_by_message_id(self, storage):
        """get_events filters by message_id."""
        msg_id = storage.insert_message(role="user", content="Test")
        storage.insert_event(event_type="event1", message_id=msg_id)
        storage.insert_event(event_type="event2", message_id=None)

        events = storage.get_events(message_id=msg_id)
        assert len(events) == 1
        assert events[0].message_id == msg_id

    def test_get_events_no_filter(self, storage):
        """get_events returns all events when no filter."""
        storage.insert_event(event_type="type1")
        storage.insert_event(event_type="type2")

        events = storage.get_events()
        assert len(events) == 2

    # --- Connection Management ---

    def test_close_and_reopen(self, tmp_path):
        """Storage persists data across close/reopen."""
        db_path = tmp_path / "test.db"

        storage1 = SessionStorage(db_path)
        storage1.insert_message(role="user", content="Persisted")
        storage1.close()

        storage2 = SessionStorage(db_path)
        messages = storage2.get_messages()
        assert len(messages) == 1
        assert messages[0].content == "Persisted"
        storage2.close()


# ============================================================================
# MessageRow and EventRow Tests
# ============================================================================


class TestMessageRow:
    """Tests for MessageRow dataclass."""

    def test_from_row_basic(self, tmp_path):
        """MessageRow.from_row creates instance from db row."""
        storage = SessionStorage(tmp_path / "test.db")
        msg_id = storage.insert_message(role="user", content="Test")

        conn = storage._get_conn()
        cursor = conn.execute("SELECT * FROM messages WHERE id = ?", (msg_id,))
        row = cursor.fetchone()

        msg_row = MessageRow.from_row(row)
        assert msg_row.id == msg_id
        assert msg_row.role == "user"
        assert msg_row.content == "Test"
        assert msg_row.tool_calls is None
        assert msg_row.summary_of is None
        storage.close()

    def test_from_row_with_tool_calls(self, tmp_path):
        """MessageRow.from_row parses tool_calls JSON."""
        storage = SessionStorage(tmp_path / "test.db")
        tool_calls = [{"id": "tc1", "name": "test", "arguments": {}}]
        msg_id = storage.insert_message(
            role="assistant", content="", tool_calls=tool_calls
        )

        msg = storage.get_message(msg_id)
        assert msg is not None
        assert msg.tool_calls == tool_calls
        storage.close()


class TestEventRow:
    """Tests for EventRow dataclass."""

    def test_from_row_basic(self, tmp_path):
        """EventRow.from_row creates instance from db row."""
        storage = SessionStorage(tmp_path / "test.db")
        event_id = storage.insert_event(event_type="test", data={"key": "value"})

        conn = storage._get_conn()
        cursor = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,))
        row = cursor.fetchone()

        event_row = EventRow.from_row(row)
        assert event_row.id == event_id
        assert event_row.event_type == "test"
        assert event_row.data == {"key": "value"}
        storage.close()


# ============================================================================
# MarkdownWriter Tests
# ============================================================================


class TestMarkdownWriter:
    """Tests for MarkdownWriter."""

    @pytest.fixture
    def writer(self, tmp_path) -> MarkdownWriter:
        """Create a MarkdownWriter instance."""
        return MarkdownWriter(tmp_path, verbose_enabled=False)

    @pytest.fixture
    def verbose_writer(self, tmp_path) -> MarkdownWriter:
        """Create a MarkdownWriter with verbose enabled."""
        return MarkdownWriter(tmp_path, verbose_enabled=True)

    def test_creates_session_directory(self, tmp_path):
        """MarkdownWriter creates session directory."""
        subdir = tmp_path / "new_session"
        MarkdownWriter(subdir)
        assert subdir.exists()

    def test_initializes_context_file(self, writer, tmp_path):
        """MarkdownWriter creates context.md with header."""
        context_path = tmp_path / "context.md"
        assert context_path.exists()

        content = context_path.read_text()
        assert content.startswith("# Session Log")
        assert "Started:" in content

    def test_context_file_not_overwritten(self, tmp_path):
        """Existing context.md is not overwritten."""
        context_path = tmp_path / "context.md"
        context_path.write_text("Existing content")

        MarkdownWriter(tmp_path)
        assert context_path.read_text() == "Existing content"

    def test_verbose_file_created_when_enabled(self, verbose_writer, tmp_path):
        """verbose.md is created when verbose_enabled=True."""
        verbose_path = tmp_path / "verbose.md"
        assert verbose_path.exists()
        assert "Verbose Log" in verbose_path.read_text()

    def test_verbose_file_not_created_when_disabled(self, writer, tmp_path):
        """verbose.md is not created when verbose_enabled=False."""
        verbose_path = tmp_path / "verbose.md"
        assert not verbose_path.exists()

    def test_write_system(self, writer, tmp_path):
        """write_system appends system prompt."""
        writer.write_system("You are a helpful assistant.")

        content = (tmp_path / "context.md").read_text()
        assert "## System" in content
        assert "You are a helpful assistant." in content

    def test_write_user(self, writer, tmp_path):
        """write_user appends user message with timestamp."""
        writer.write_user("Hello there!")

        content = (tmp_path / "context.md").read_text()
        assert "## User [" in content
        assert "Hello there!" in content

    def test_write_assistant(self, writer, tmp_path):
        """write_assistant appends assistant response."""
        writer.write_assistant("Hello! How can I help?")

        content = (tmp_path / "context.md").read_text()
        assert "## Assistant [" in content
        assert "Hello! How can I help?" in content

    def test_write_assistant_with_tool_calls(self, writer, tmp_path):
        """write_assistant includes tool calls."""
        tool_calls = [{"name": "read_file", "arguments": {"path": "/tmp/test.txt"}}]
        writer.write_assistant("Let me read that file.", tool_calls=tool_calls)

        content = (tmp_path / "context.md").read_text()
        assert "### Tool Calls" in content
        assert "**read_file**" in content
        assert "/tmp/test.txt" in content

    def test_write_tool_result_success(self, writer, tmp_path):
        """write_tool_result formats success correctly."""
        writer.write_tool_result("read_file", "file contents here", error=None)

        content = (tmp_path / "context.md").read_text()
        assert "### Tool Result: read_file (success)" in content
        assert "file contents here" in content

    def test_write_tool_result_error(self, writer, tmp_path):
        """write_tool_result formats error correctly."""
        writer.write_tool_result("read_file", "", error="File not found")

        content = (tmp_path / "context.md").read_text()
        assert "### Tool Result: read_file (error)" in content
        assert "File not found" in content

    def test_write_tool_result_truncates_long_output(self, writer, tmp_path):
        """write_tool_result truncates very long output."""
        long_content = "x" * 3000
        writer.write_tool_result("read_file", long_content)

        content = (tmp_path / "context.md").read_text()
        assert "... (truncated)" in content

    def test_write_separator(self, writer, tmp_path):
        """write_separator adds horizontal rule."""
        writer.write_separator()

        content = (tmp_path / "context.md").read_text()
        # Should have at least 2 "---" (one from header, one from separator)
        assert content.count("---") >= 2

    def test_write_thinking_when_verbose_disabled(self, writer, tmp_path):
        """write_thinking does nothing when verbose disabled."""
        writer.write_thinking("Deep thoughts...")
        verbose_path = tmp_path / "verbose.md"
        assert not verbose_path.exists()

    def test_write_thinking_when_verbose_enabled(self, verbose_writer, tmp_path):
        """write_thinking writes to verbose.md."""
        verbose_writer.write_thinking("Analyzing the problem...")

        content = (tmp_path / "verbose.md").read_text()
        assert "### Thinking [" in content
        assert "Analyzing the problem..." in content

    def test_write_timing(self, verbose_writer, tmp_path):
        """write_timing writes timing info."""
        verbose_writer.write_timing("API call", 125.5, {"tokens": 100})

        content = (tmp_path / "verbose.md").read_text()
        assert "**API call**" in content
        assert "125.5ms" in content
        assert "tokens=100" in content

    def test_write_token_count(self, verbose_writer, tmp_path):
        """write_token_count writes token usage."""
        verbose_writer.write_token_count(100, 50, 150)

        content = (tmp_path / "verbose.md").read_text()
        assert "**Tokens**" in content
        assert "prompt=100" in content
        assert "completion=50" in content
        assert "total=150" in content

    def test_write_event(self, verbose_writer, tmp_path):
        """write_event writes generic event."""
        verbose_writer.write_event("custom_event", {"data": "value"})

        content = (tmp_path / "verbose.md").read_text()
        assert "**custom_event**" in content
        assert '"data": "value"' in content


# ============================================================================
# RawWriter Tests
# ============================================================================


class TestRawWriter:
    """Tests for RawWriter."""

    @pytest.fixture
    def writer(self, tmp_path) -> RawWriter:
        """Create a RawWriter instance."""
        return RawWriter(tmp_path)

    def test_creates_session_directory(self, tmp_path):
        """RawWriter creates session directory."""
        subdir = tmp_path / "new_session"
        RawWriter(subdir)
        assert subdir.exists()

    def test_write_request(self, writer, tmp_path):
        """write_request appends request to raw.jsonl."""
        writer.write_request("/chat/completions", {"model": "test", "messages": []})

        raw_path = tmp_path / "raw.jsonl"
        assert raw_path.exists()

        line = raw_path.read_text().strip()
        data = json.loads(line)

        assert data["type"] == "request"
        assert data["endpoint"] == "/chat/completions"
        assert data["payload"]["model"] == "test"
        assert "timestamp" in data

    def test_write_response(self, writer, tmp_path):
        """write_response appends response to raw.jsonl."""
        writer.write_response(200, {"choices": []})

        raw_path = tmp_path / "raw.jsonl"
        line = raw_path.read_text().strip()
        data = json.loads(line)

        assert data["type"] == "response"
        assert data["status"] == 200
        assert data["body"] == {"choices": []}

    def test_write_stream_chunk(self, writer, tmp_path):
        """write_stream_chunk appends chunk to raw.jsonl."""
        writer.write_stream_chunk({"delta": {"content": "Hello"}})

        raw_path = tmp_path / "raw.jsonl"
        line = raw_path.read_text().strip()
        data = json.loads(line)

        assert data["type"] == "stream_chunk"
        assert data["chunk"]["delta"]["content"] == "Hello"

    def test_multiple_writes(self, writer, tmp_path):
        """Multiple writes create multiple lines."""
        writer.write_request("/test", {})
        writer.write_response(200, {})
        writer.write_stream_chunk({})

        raw_path = tmp_path / "raw.jsonl"
        lines = raw_path.read_text().strip().split("\n")

        assert len(lines) == 3
        assert json.loads(lines[0])["type"] == "request"
        assert json.loads(lines[1])["type"] == "response"
        assert json.loads(lines[2])["type"] == "stream_chunk"

    def test_custom_timestamp(self, writer, tmp_path):
        """Custom timestamp is used when provided."""
        ts = 1234567890.123
        writer.write_request("/test", {}, timestamp=ts)

        raw_path = tmp_path / "raw.jsonl"
        data = json.loads(raw_path.read_text().strip())

        assert data["timestamp"] == ts


# ============================================================================
# SessionLogger Tests
# ============================================================================


class TestSessionLogger:
    """Tests for SessionLogger."""

    @pytest.fixture
    def logger(self, tmp_path) -> SessionLogger:
        """Create a SessionLogger with CONTEXT stream only."""
        config = LogConfig(base_dir=tmp_path, streams=LogStream.CONTEXT)
        logger = SessionLogger(config)
        yield logger
        logger.close()

    @pytest.fixture
    def verbose_logger(self, tmp_path) -> SessionLogger:
        """Create a SessionLogger with CONTEXT | VERBOSE streams."""
        config = LogConfig(
            base_dir=tmp_path, streams=LogStream.CONTEXT | LogStream.VERBOSE
        )
        logger = SessionLogger(config)
        yield logger
        logger.close()

    @pytest.fixture
    def full_logger(self, tmp_path) -> SessionLogger:
        """Create a SessionLogger with ALL streams."""
        config = LogConfig(base_dir=tmp_path, streams=LogStream.ALL)
        logger = SessionLogger(config)
        yield logger
        logger.close()

    def test_creates_session_directory(self, logger):
        """SessionLogger creates session directory."""
        assert logger.session_dir.exists()

    def test_creates_database(self, logger):
        """SessionLogger creates session.db."""
        db_path = logger.session_dir / "session.db"
        assert db_path.exists()

    def test_stores_session_metadata(self, logger):
        """SessionLogger stores session metadata in database."""
        metadata = logger.storage.get_all_metadata()

        assert "session_id" in metadata
        assert "created_at" in metadata
        assert metadata["session_id"] == logger.session_id

    def test_session_id_property(self, logger):
        """session_id property returns the session ID."""
        assert logger.session_id == logger.info.session_id

    def test_session_dir_property(self, logger):
        """session_dir property returns the session directory."""
        assert logger.session_dir == logger.info.session_dir

    # --- Message Logging ---

    def test_log_system(self, logger):
        """log_system stores and writes system message."""
        msg_id = logger.log_system("You are helpful.")

        # Check storage
        msg = logger.storage.get_message(msg_id)
        assert msg is not None
        assert msg.role == "system"
        assert msg.content == "You are helpful."

        # Check markdown
        content = (logger.session_dir / "context.md").read_text()
        assert "## System" in content
        assert "You are helpful." in content

    def test_log_user(self, logger):
        """log_user stores and writes user message."""
        msg_id = logger.log_user("Hello!")

        msg = logger.storage.get_message(msg_id)
        assert msg is not None
        assert msg.role == "user"
        assert msg.content == "Hello!"

    def test_log_assistant(self, logger):
        """log_assistant stores and writes assistant message."""
        msg_id = logger.log_assistant("Hi there!", tokens=50)

        msg = logger.storage.get_message(msg_id)
        assert msg is not None
        assert msg.role == "assistant"
        assert msg.content == "Hi there!"
        assert msg.tokens == 50

    def test_log_assistant_with_tool_calls(self, logger):
        """log_assistant stores tool calls."""
        tool_calls = [ToolCall(id="tc1", name="read_file", arguments={"path": "/test"})]
        msg_id = logger.log_assistant("Reading file...", tool_calls=tool_calls)

        msg = logger.storage.get_message(msg_id)
        assert msg is not None
        assert msg.tool_calls is not None
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0]["name"] == "read_file"

    def test_log_assistant_with_thinking_verbose_disabled(self, logger):
        """log_assistant ignores thinking when verbose disabled."""
        logger.log_assistant("Response", thinking="Thinking...")

        events = logger.storage.get_events(event_type="thinking")
        assert len(events) == 0

    def test_log_assistant_with_thinking_verbose_enabled(self, verbose_logger):
        """log_assistant logs thinking when verbose enabled."""
        msg_id = verbose_logger.log_assistant("Response", thinking="Analyzing...")

        events = verbose_logger.storage.get_events(event_type="thinking")
        assert len(events) == 1
        assert events[0].data["content"] == "Analyzing..."
        assert events[0].message_id == msg_id

    def test_log_tool_result_success(self, logger):
        """log_tool_result stores successful result."""
        result = ToolResult(output="File contents")
        msg_id = logger.log_tool_result("tc1", "read_file", result)

        msg = logger.storage.get_message(msg_id)
        assert msg is not None
        assert msg.role == "tool"
        assert msg.content == "File contents"
        assert msg.name == "read_file"
        assert msg.tool_call_id == "tc1"

    def test_log_tool_result_error(self, logger):
        """log_tool_result stores error result."""
        result = ToolResult(error="File not found")
        msg_id = logger.log_tool_result("tc1", "read_file", result)

        msg = logger.storage.get_message(msg_id)
        assert msg is not None
        assert msg.content == "File not found"

    # --- Verbose Stream ---

    def test_log_thinking_verbose_disabled(self, logger):
        """log_thinking does nothing when verbose disabled."""
        logger.log_thinking("Deep thoughts")
        events = logger.storage.get_events(event_type="thinking")
        assert len(events) == 0

    def test_log_thinking_verbose_enabled(self, verbose_logger):
        """log_thinking stores event when verbose enabled."""
        verbose_logger.log_thinking("Analyzing...")

        events = verbose_logger.storage.get_events(event_type="thinking")
        assert len(events) == 1
        assert events[0].data["content"] == "Analyzing..."

    def test_log_timing(self, verbose_logger):
        """log_timing stores timing event."""
        verbose_logger.log_timing("API call", 125.5, {"model": "test"})

        events = verbose_logger.storage.get_events(event_type="timing")
        assert len(events) == 1
        assert events[0].data["operation"] == "API call"
        assert events[0].data["duration_ms"] == 125.5
        assert events[0].data["model"] == "test"

    def test_log_token_count(self, verbose_logger):
        """log_token_count stores token usage event."""
        verbose_logger.log_token_count(100, 50, 150)

        events = verbose_logger.storage.get_events(event_type="token_usage")
        assert len(events) == 1
        assert events[0].data["prompt_tokens"] == 100
        assert events[0].data["completion_tokens"] == 50
        assert events[0].data["total_tokens"] == 150

    # --- Raw Stream ---

    def test_log_raw_request_disabled(self, logger):
        """log_raw_request does nothing when RAW disabled."""
        logger.log_raw_request("/test", {})
        raw_path = logger.session_dir / "raw.jsonl"
        assert not raw_path.exists()

    def test_log_raw_request_enabled(self, full_logger):
        """log_raw_request writes to raw.jsonl when enabled."""
        full_logger.log_raw_request("/chat/completions", {"model": "test"})

        raw_path = full_logger.session_dir / "raw.jsonl"
        assert raw_path.exists()

        data = json.loads(raw_path.read_text().strip())
        assert data["type"] == "request"
        assert data["endpoint"] == "/chat/completions"

    def test_log_raw_response(self, full_logger):
        """log_raw_response writes to raw.jsonl."""
        full_logger.log_raw_response(200, {"choices": []})

        raw_path = full_logger.session_dir / "raw.jsonl"
        data = json.loads(raw_path.read_text().strip())
        assert data["type"] == "response"
        assert data["status"] == 200

    def test_log_raw_chunk(self, full_logger):
        """log_raw_chunk writes to raw.jsonl."""
        full_logger.log_raw_chunk({"delta": {"content": "Hello"}})

        raw_path = full_logger.session_dir / "raw.jsonl"
        data = json.loads(raw_path.read_text().strip())
        assert data["type"] == "stream_chunk"

    # --- Context Management ---

    def test_get_context_messages(self, logger):
        """get_context_messages returns Message objects."""
        logger.log_system("System prompt")
        logger.log_user("Hello")
        tool_calls = [ToolCall(id="tc1", name="test", arguments={})]
        logger.log_assistant("Response", tool_calls=tool_calls)

        messages = logger.get_context_messages()

        assert len(messages) == 3
        assert messages[0].role == Role.SYSTEM
        assert messages[1].role == Role.USER
        assert messages[2].role == Role.ASSISTANT
        assert len(messages[2].tool_calls) == 1

    def test_get_token_count(self, logger):
        """get_token_count returns total tokens."""
        logger.log_assistant("Response 1", tokens=100)
        logger.log_assistant("Response 2", tokens=200)

        assert logger.get_token_count() == 300

    def test_mark_compacted(self, logger):
        """mark_compacted updates storage."""
        id1 = logger.log_user("Old message 1")
        id2 = logger.log_assistant("Old message 2")
        summary_id = logger.log_assistant("Summary")

        logger.mark_compacted([id1, id2], summary_id)

        summary = logger.storage.get_message(summary_id)
        assert summary is not None
        assert summary.summary_of == [id1, id2]

        old1 = logger.storage.get_message(id1)
        assert old1 is not None and old1.in_context is False

    # --- Subagent Support ---

    def test_create_child_logger(self, logger):
        """create_child_logger creates nested logger."""
        child = logger.create_child_logger()

        assert child.info.parent_id == logger.session_id
        # Child's session_dir is nested under parent's session_dir
        # Structure: parent_session_dir / parent_id / subagent_xxx
        # (base_dir for child = parent's session_dir)
        assert logger.session_dir in child.session_dir.parents
        assert child.session_dir.name.startswith("subagent_")
        assert child.config.streams == logger.config.streams

        child.close()

    def test_child_logger_inherits_streams(self, full_logger):
        """Child logger inherits stream configuration."""
        child = full_logger.create_child_logger()

        assert child.config.streams == LogStream.ALL
        child.close()

    # --- Lifecycle ---

    def test_close(self, tmp_path):
        """close releases resources."""
        config = LogConfig(base_dir=tmp_path, streams=LogStream.CONTEXT)
        logger = SessionLogger(config)

        logger.log_user("Test")
        logger.close()

        # Storage should be closed (connection is None)
        assert logger.storage._conn is None


# ============================================================================
# Integration Tests
# ============================================================================


class TestSessionLoggingIntegration:
    """Integration tests for the session logging system."""

    def test_full_conversation_flow(self, tmp_path):
        """Test a complete conversation logging flow."""
        config = LogConfig(base_dir=tmp_path, streams=LogStream.ALL)
        logger = SessionLogger(config)

        # Log a system prompt
        logger.log_system("You are a helpful assistant.")

        # Log user message
        logger.log_user("What is 2+2?")

        # Log assistant with thinking
        logger.log_assistant(
            "The answer is 4.",
            thinking="Let me calculate: 2+2 equals 4.",
            tokens=25,
        )

        # Log timing
        logger.log_timing("completion", 150.0, {"model": "test"})

        # Log token usage
        logger.log_token_count(10, 15, 25)

        # Log raw API data
        logger.log_raw_request("/chat/completions", {"model": "test"})
        logger.log_raw_response(200, {"choices": [{"message": {"content": "4"}}]})

        # Verify everything was logged
        messages = logger.get_context_messages()
        assert len(messages) == 3

        events = logger.storage.get_events()
        assert len(events) >= 3  # thinking, timing, token_usage

        # Verify files exist
        assert (logger.session_dir / "context.md").exists()
        assert (logger.session_dir / "verbose.md").exists()
        assert (logger.session_dir / "raw.jsonl").exists()

        logger.close()

    def test_tool_call_flow(self, tmp_path):
        """Test a conversation with tool calls."""
        config = LogConfig(base_dir=tmp_path, streams=LogStream.CONTEXT)
        logger = SessionLogger(config)

        logger.log_user("Read the file test.txt")

        tool_calls = [
            ToolCall(id="call_001", name="read_file", arguments={"path": "test.txt"})
        ]
        logger.log_assistant("Let me read that file.", tool_calls=tool_calls)

        logger.log_tool_result(
            "call_001", "read_file", ToolResult(output="File contents here")
        )

        logger.log_assistant("The file contains: File contents here")

        messages = logger.get_context_messages()
        assert len(messages) == 4

        # Verify tool call structure
        assert messages[1].role == Role.ASSISTANT
        assert len(messages[1].tool_calls) == 1
        assert messages[1].tool_calls[0].id == "call_001"

        assert messages[2].role == Role.TOOL
        assert messages[2].tool_call_id == "call_001"

        logger.close()
