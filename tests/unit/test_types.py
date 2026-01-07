"""Unit tests for nexus3.core.types module."""

from dataclasses import FrozenInstanceError

import pytest

from nexus3.core.types import Message, Role, ToolCall, ToolResult


class TestRole:
    """Tests for Role enum."""

    def test_role_values(self):
        """Role enum has expected values."""
        assert Role.SYSTEM.value == "system"
        assert Role.USER.value == "user"
        assert Role.ASSISTANT.value == "assistant"
        assert Role.TOOL.value == "tool"

    def test_role_members(self):
        """Role enum has exactly 4 members."""
        assert len(Role) == 4


class TestToolCall:
    """Tests for ToolCall dataclass."""

    def test_toolcall_creation(self):
        """ToolCall can be created with required fields."""
        tc = ToolCall(id="call_123", name="read_file", arguments={"path": "/tmp/test.txt"})
        assert tc.id == "call_123"
        assert tc.name == "read_file"
        assert tc.arguments == {"path": "/tmp/test.txt"}

    def test_toolcall_is_frozen(self):
        """ToolCall is immutable (frozen)."""
        tc = ToolCall(id="call_123", name="read_file", arguments={})
        with pytest.raises(FrozenInstanceError):
            tc.id = "different_id"


class TestMessage:
    """Tests for Message dataclass."""

    def test_message_creation_with_required_fields(self):
        """Message can be created with just role and content."""
        msg = Message(role=Role.USER, content="Hello, world!")
        assert msg.role == Role.USER
        assert msg.content == "Hello, world!"
        assert msg.tool_calls == ()
        assert msg.tool_call_id is None

    def test_message_with_tool_calls(self):
        """Message can include tool calls."""
        tc = ToolCall(id="call_1", name="test_tool", arguments={"arg": "value"})
        msg = Message(role=Role.ASSISTANT, content="", tool_calls=(tc,))
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].name == "test_tool"

    def test_message_with_tool_call_id(self):
        """Message can include tool_call_id for tool responses."""
        msg = Message(role=Role.TOOL, content="Tool result", tool_call_id="call_123")
        assert msg.tool_call_id == "call_123"

    def test_message_is_frozen(self):
        """Message is immutable (frozen)."""
        msg = Message(role=Role.USER, content="Hello")
        with pytest.raises(FrozenInstanceError):
            msg.content = "Different content"


class TestToolResult:
    """Tests for ToolResult dataclass."""

    def test_toolresult_defaults(self):
        """ToolResult has empty defaults for output and error."""
        tr = ToolResult()
        assert tr.output == ""
        assert tr.error == ""

    def test_toolresult_success_when_no_error(self):
        """ToolResult.success is True when error is empty."""
        tr = ToolResult(output="Some output")
        assert tr.success is True

    def test_toolresult_failure_when_error(self):
        """ToolResult.success is False when error is not empty."""
        tr = ToolResult(error="Something went wrong")
        assert tr.success is False

    def test_toolresult_with_both_output_and_error(self):
        """ToolResult.success is False even with output if error exists."""
        tr = ToolResult(output="Partial output", error="But also an error")
        assert tr.success is False

    def test_toolresult_is_frozen(self):
        """ToolResult is immutable (frozen)."""
        tr = ToolResult(output="test")
        with pytest.raises(FrozenInstanceError):
            tr.output = "different"
