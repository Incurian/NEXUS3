"""Tests for robust storage decoding - handles corruption gracefully."""

import json

import pytest

from nexus3.session.persistence import SavedSession, SessionPersistenceError
from nexus3.session.storage import MAX_JSON_FIELD_SIZE, EventRow, MessageRow


class TestMessageRowCorruption:
    """MessageRow.from_row handles malformed data gracefully."""

    def test_valid_tool_calls_parsed(self):
        """Valid JSON tool_calls should parse correctly."""

        class MockRow:
            """Mock sqlite3.Row with dict-like access."""

            def __init__(self, data):
                self._data = data

            def __getitem__(self, key):
                return self._data[key]

        row = MockRow(
            {
                "id": 1,
                "role": "assistant",
                "content": "test",
                "name": None,
                "tool_call_id": None,
                "tool_calls": json.dumps(
                    [{"id": "1", "name": "test", "arguments": {}}]
                ),
                "tokens": 10,
                "timestamp": 1705363200.0,
                "in_context": True,
                "summary_of": None,
            }
        )

        msg = MessageRow.from_row(row)
        assert msg.tool_calls is not None
        assert len(msg.tool_calls) == 1

    def test_malformed_json_tool_calls_returns_none(self):
        """Malformed JSON in tool_calls returns None, doesn't crash."""

        class MockRow:
            def __init__(self, data):
                self._data = data

            def __getitem__(self, key):
                return self._data[key]

        row = MockRow(
            {
                "id": 1,
                "role": "assistant",
                "content": "test",
                "name": None,
                "tool_call_id": None,
                "tool_calls": "{invalid json}",  # Malformed
                "tokens": 10,
                "timestamp": 1705363200.0,
                "in_context": True,
                "summary_of": None,
            }
        )

        # Should NOT raise - returns None for tool_calls
        msg = MessageRow.from_row(row)
        assert msg.tool_calls is None

    def test_oversized_tool_calls_returns_none(self):
        """Oversized JSON in tool_calls returns None, doesn't exhaust memory."""

        class MockRow:
            def __init__(self, data):
                self._data = data

            def __getitem__(self, key):
                return self._data[key]

        # Create oversized data (just over limit)
        oversized = "x" * (MAX_JSON_FIELD_SIZE + 1)
        row = MockRow(
            {
                "id": 1,
                "role": "assistant",
                "content": "test",
                "name": None,
                "tool_call_id": None,
                "tool_calls": oversized,
                "tokens": 10,
                "timestamp": 1705363200.0,
                "in_context": True,
                "summary_of": None,
            }
        )

        # Should NOT raise - returns None for tool_calls
        msg = MessageRow.from_row(row)
        assert msg.tool_calls is None

    def test_null_tool_calls_returns_none(self):
        """NULL tool_calls in database returns None."""

        class MockRow:
            def __init__(self, data):
                self._data = data

            def __getitem__(self, key):
                return self._data[key]

        row = MockRow(
            {
                "id": 1,
                "role": "user",
                "content": "test",
                "name": None,
                "tool_call_id": None,
                "tool_calls": None,  # NULL in database
                "tokens": 10,
                "timestamp": 1705363200.0,
                "in_context": True,
                "summary_of": None,
            }
        )

        msg = MessageRow.from_row(row)
        assert msg.tool_calls is None

    def test_empty_string_tool_calls_returns_none(self):
        """Empty string tool_calls returns None."""

        class MockRow:
            def __init__(self, data):
                self._data = data

            def __getitem__(self, key):
                return self._data[key]

        row = MockRow(
            {
                "id": 1,
                "role": "assistant",
                "content": "test",
                "name": None,
                "tool_call_id": None,
                "tool_calls": "",  # Empty string
                "tokens": 10,
                "timestamp": 1705363200.0,
                "in_context": True,
                "summary_of": None,
            }
        )

        msg = MessageRow.from_row(row)
        # Empty string is falsy, so tool_calls won't be parsed
        assert msg.tool_calls is None


class TestEventRowCorruption:
    """EventRow.from_row handles malformed data gracefully."""

    def test_valid_event_data_parsed(self):
        """Valid JSON event data should parse correctly."""

        class MockRow:
            def __init__(self, data):
                self._data = data

            def __getitem__(self, key):
                return self._data[key]

        row = MockRow(
            {
                "id": 1,
                "message_id": 1,
                "event_type": "test",
                "data": json.dumps({"key": "value"}),
                "timestamp": 1705363200.0,
            }
        )

        event = EventRow.from_row(row)
        assert event.data is not None
        assert event.data["key"] == "value"

    def test_malformed_json_event_data_returns_none(self):
        """Malformed JSON in event data returns None, doesn't crash."""

        class MockRow:
            def __init__(self, data):
                self._data = data

            def __getitem__(self, key):
                return self._data[key]

        row = MockRow(
            {
                "id": 1,
                "message_id": 1,
                "event_type": "test",
                "data": "{not valid json",
                "timestamp": 1705363200.0,
            }
        )

        event = EventRow.from_row(row)
        assert event.data is None

    def test_oversized_event_data_returns_none(self):
        """Oversized JSON in event data returns None."""

        class MockRow:
            def __init__(self, data):
                self._data = data

            def __getitem__(self, key):
                return self._data[key]

        oversized = "y" * (MAX_JSON_FIELD_SIZE + 1)
        row = MockRow(
            {
                "id": 1,
                "message_id": 1,
                "event_type": "test",
                "data": oversized,
                "timestamp": 1705363200.0,
            }
        )

        event = EventRow.from_row(row)
        assert event.data is None

    def test_null_event_data_returns_none(self):
        """NULL event data in database returns None."""

        class MockRow:
            def __init__(self, data):
                self._data = data

            def __getitem__(self, key):
                return self._data[key]

        row = MockRow(
            {
                "id": 1,
                "message_id": 1,
                "event_type": "test",
                "data": None,
                "timestamp": 1705363200.0,
            }
        )

        event = EventRow.from_row(row)
        assert event.data is None


class TestSavedSessionCorruption:
    """SavedSession.from_json handles malformed data with clear errors."""

    def test_valid_json_parses(self):
        """Valid session JSON should parse correctly."""
        valid_json = json.dumps(
            {
                "agent_id": "test",
                "created_at": "2026-01-16T00:00:00",
                "modified_at": "2026-01-16T00:00:00",
                "model": "test-model",
                "messages": [],
                "system_prompt": "test prompt",
                "system_prompt_path": None,
                "working_directory": "/tmp",
                "permission_level": "trusted",
                "token_usage": {},
            }
        )

        session = SavedSession.from_json(valid_json)
        assert session.agent_id == "test"

    def test_malformed_json_raises_persistence_error(self):
        """Malformed JSON should raise SessionPersistenceError."""
        with pytest.raises(SessionPersistenceError) as exc_info:
            SavedSession.from_json("{invalid json}")

        assert "Invalid session JSON" in str(exc_info.value)

    def test_truncated_json_raises_persistence_error(self):
        """Truncated JSON should raise SessionPersistenceError."""
        truncated = '{"agent_id": "test", "created_at": "2026-01-16T00:00:00"'

        with pytest.raises(SessionPersistenceError) as exc_info:
            SavedSession.from_json(truncated)

        assert "Invalid session JSON" in str(exc_info.value)

    def test_empty_string_raises_persistence_error(self):
        """Empty string should raise SessionPersistenceError."""
        with pytest.raises(SessionPersistenceError) as exc_info:
            SavedSession.from_json("")

        assert "Invalid session JSON" in str(exc_info.value)

    def test_missing_required_field_raises_error(self):
        """Missing required field should raise an error."""
        # Missing agent_id
        incomplete = json.dumps(
            {
                "created_at": "2026-01-16T00:00:00",
                "modified_at": "2026-01-16T00:00:00",
                "messages": [],
                "system_prompt": "test",
                "working_directory": "/tmp",
                "permission_level": "trusted",
            }
        )

        with pytest.raises(KeyError):
            SavedSession.from_json(incomplete)

    def test_invalid_datetime_raises_error(self):
        """Invalid datetime format should raise an error."""
        invalid_date = json.dumps(
            {
                "agent_id": "test",
                "created_at": "not-a-date",  # Invalid
                "modified_at": "2026-01-16T00:00:00",
                "messages": [],
                "system_prompt": "test",
                "working_directory": "/tmp",
                "permission_level": "trusted",
            }
        )

        with pytest.raises(ValueError):
            SavedSession.from_json(invalid_date)


class TestStorageLimitsConstants:
    """Test that storage limit constants are properly defined."""

    def test_max_json_field_size_is_reasonable(self):
        """MAX_JSON_FIELD_SIZE should be a reasonable value (10MB)."""
        assert MAX_JSON_FIELD_SIZE == 10 * 1024 * 1024  # 10MB
        assert MAX_JSON_FIELD_SIZE > 1024 * 1024  # At least 1MB
        assert MAX_JSON_FIELD_SIZE < 100 * 1024 * 1024  # Less than 100MB


class TestMessageRowRobustness:
    """Additional robustness tests for MessageRow."""

    def test_valid_summary_of_parsed(self):
        """Valid summary_of field should parse correctly."""

        class MockRow:
            def __init__(self, data):
                self._data = data

            def __getitem__(self, key):
                return self._data[key]

        row = MockRow(
            {
                "id": 10,
                "role": "assistant",
                "content": "Summary",
                "name": None,
                "tool_call_id": None,
                "tool_calls": None,
                "tokens": 100,
                "timestamp": 1705363200.0,
                "in_context": True,
                "summary_of": "1,2,3,4,5",  # Comma-separated IDs
            }
        )

        msg = MessageRow.from_row(row)
        assert msg.summary_of == [1, 2, 3, 4, 5]

    def test_empty_summary_of_returns_none(self):
        """Empty summary_of field returns None."""

        class MockRow:
            def __init__(self, data):
                self._data = data

            def __getitem__(self, key):
                return self._data[key]

        row = MockRow(
            {
                "id": 10,
                "role": "assistant",
                "content": "test",
                "name": None,
                "tool_call_id": None,
                "tool_calls": None,
                "tokens": 100,
                "timestamp": 1705363200.0,
                "in_context": True,
                "summary_of": None,
            }
        )

        msg = MessageRow.from_row(row)
        assert msg.summary_of is None

    def test_tool_result_fields_preserved(self):
        """Tool result fields (name, tool_call_id) are preserved."""

        class MockRow:
            def __init__(self, data):
                self._data = data

            def __getitem__(self, key):
                return self._data[key]

        row = MockRow(
            {
                "id": 5,
                "role": "tool",
                "content": "tool output",
                "name": "read_file",
                "tool_call_id": "call_abc123",
                "tool_calls": None,
                "tokens": 50,
                "timestamp": 1705363200.0,
                "in_context": True,
                "summary_of": None,
            }
        )

        msg = MessageRow.from_row(row)
        assert msg.name == "read_file"
        assert msg.tool_call_id == "call_abc123"
        assert msg.role == "tool"
