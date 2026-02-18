"""Tests for empty assistant message filtering during session deserialization.

Verifies:
- Empty assistant messages are filtered out on deserialize
- Non-empty assistant messages pass through
- Non-assistant messages (user, tool) pass through regardless
- Warning is logged for filtered messages
"""

import pytest

from nexus3.core.types import Role
from nexus3.session.persistence import deserialize_message, deserialize_messages


class TestDeserializeMessageEmptyGuard:
    """Empty assistant messages filtered during deserialization."""

    def test_empty_assistant_returns_none(self) -> None:
        """Empty assistant message (no content, no tools) returns None."""
        data = {"role": "assistant", "content": ""}
        result = deserialize_message(data)
        assert result is None

    def test_empty_assistant_with_empty_tool_calls_returns_none(self) -> None:
        """Empty assistant message with empty tool_calls list returns None."""
        data = {"role": "assistant", "content": "", "tool_calls": []}
        result = deserialize_message(data)
        assert result is None

    def test_assistant_with_content_passes(self) -> None:
        """Assistant message with content passes through."""
        data = {"role": "assistant", "content": "Hello!"}
        result = deserialize_message(data)
        assert result is not None
        assert result.content == "Hello!"

    def test_assistant_with_tool_calls_passes(self) -> None:
        """Assistant message with tool calls (empty content) passes through."""
        data = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "name": "test", "arguments": {"a": 1}}
            ],
        }
        result = deserialize_message(data)
        assert result is not None
        assert len(result.tool_calls) == 1

    def test_user_message_always_passes(self) -> None:
        """User messages pass through regardless of content."""
        data = {"role": "user", "content": ""}
        result = deserialize_message(data)
        assert result is not None
        assert result.role == Role.USER

    def test_tool_message_always_passes(self) -> None:
        """Tool result messages pass through regardless of content."""
        data = {"role": "tool", "content": "", "tool_call_id": "call_1"}
        result = deserialize_message(data)
        assert result is not None
        assert result.role == Role.TOOL

    def test_logs_warning_on_filter(self, caplog: pytest.LogCaptureFixture) -> None:
        """Warning logged when empty assistant message is filtered."""
        data = {"role": "assistant", "content": ""}
        with caplog.at_level("WARNING", logger="nexus3.session.persistence"):
            deserialize_message(data)

        assert any("Skipping empty assistant message" in r.message for r in caplog.records)


class TestDeserializeMessagesFiltering:
    """deserialize_messages() filters out empty assistant messages."""

    def test_filters_empty_assistant_from_list(self) -> None:
        """Empty assistant messages are excluded from the result list."""
        data = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": ""},  # empty — should be filtered
            {"role": "user", "content": "hello?"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        messages = deserialize_messages(data)
        assert len(messages) == 3
        assert messages[0].role == Role.USER
        assert messages[1].role == Role.USER
        assert messages[2].role == Role.ASSISTANT
        assert messages[2].content == "Hi there!"

    def test_all_valid_messages_pass(self) -> None:
        """When no empty messages, all pass through."""
        data = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        messages = deserialize_messages(data)
        assert len(messages) == 2

    def test_empty_list(self) -> None:
        """Empty input returns empty output."""
        assert deserialize_messages([]) == []
