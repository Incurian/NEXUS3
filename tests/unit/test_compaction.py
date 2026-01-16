"""Tests for nexus3.context.compaction module."""

import pytest

from nexus3.context.compaction import (
    SUMMARIZE_PROMPT,
    build_summarize_prompt,
    create_summary_message,
    format_messages_for_summary,
    get_summary_prefix,
    select_messages_for_compaction,
)
from nexus3.core.types import Message, Role, ToolCall


class MockTokenCounter:
    """Mock token counter for testing."""

    def __init__(self, tokens_per_message: int = 10):
        self.tokens_per_message = tokens_per_message

    def count(self, text: str) -> int:
        return len(text)

    def count_messages(self, messages: list) -> int:
        return len(messages) * self.tokens_per_message


class TestFormatMessagesForSummary:
    """Tests for format_messages_for_summary()."""

    def test_simple_user_message(self):
        """Test formatting a simple user message."""
        messages = [Message(role=Role.USER, content="Hello world")]
        result = format_messages_for_summary(messages)
        assert result == "USER: Hello world"

    def test_simple_assistant_message(self):
        """Test formatting a simple assistant message."""
        messages = [Message(role=Role.ASSISTANT, content="Hi there")]
        result = format_messages_for_summary(messages)
        assert result == "ASSISTANT: Hi there"

    def test_system_message(self):
        """Test formatting a system message."""
        messages = [Message(role=Role.SYSTEM, content="You are helpful")]
        result = format_messages_for_summary(messages)
        assert result == "SYSTEM: You are helpful"

    def test_multiple_messages(self):
        """Test formatting multiple messages."""
        messages = [
            Message(role=Role.USER, content="Question?"),
            Message(role=Role.ASSISTANT, content="Answer!"),
        ]
        result = format_messages_for_summary(messages)
        assert result == "USER: Question?\n\nASSISTANT: Answer!"

    def test_tool_message_includes_tool_call_id(self):
        """Test that tool messages include tool_call_id in the role."""
        messages = [
            Message(
                role=Role.TOOL,
                content="File contents here",
                tool_call_id="call_abc123",
            )
        ]
        result = format_messages_for_summary(messages)
        assert result == "TOOL[call_abc123]: File contents here"

    def test_tool_message_without_tool_call_id(self):
        """Test tool message without tool_call_id (edge case)."""
        messages = [Message(role=Role.TOOL, content="Result")]
        result = format_messages_for_summary(messages)
        # tool_call_id defaults to None
        assert result == "TOOL[None]: Result"

    def test_message_with_tool_calls(self):
        """Test that assistant messages with tool_calls show tool call details."""
        tool_call = ToolCall(
            id="call_xyz789",
            name="read_file",
            arguments='{"path": "/tmp/test.txt"}',
        )
        messages = [
            Message(
                role=Role.ASSISTANT,
                content="Let me read that file",
                tool_calls=[tool_call],
            )
        ]
        result = format_messages_for_summary(messages)
        # Note: tool calls are appended with \n (single newline) per tool call,
        # then entire message block is joined with \n\n
        assert "ASSISTANT: Let me read that file" in result
        assert '-> read_file(' in result  # Tool call with redacted args

    def test_message_with_multiple_tool_calls(self):
        """Test assistant message with multiple tool calls."""
        tool_calls = [
            ToolCall(id="call_1", name="read_file", arguments='{"path": "a.txt"}'),
            ToolCall(id="call_2", name="write_file", arguments='{"path": "b.txt"}'),
        ]
        messages = [
            Message(
                role=Role.ASSISTANT,
                content="Doing both",
                tool_calls=tool_calls,
            )
        ]
        result = format_messages_for_summary(messages)
        assert "read_file" in result
        assert "write_file" in result
        assert result.count("->") == 2  # Two tool calls

    def test_full_conversation_with_tools(self):
        """Test a realistic conversation with tool usage."""
        messages = [
            Message(role=Role.USER, content="Read the config file"),
            Message(
                role=Role.ASSISTANT,
                content="I'll read it",
                tool_calls=[
                    ToolCall(
                        id="call_read",
                        name="read_file",
                        arguments='{"path": "config.json"}',
                    )
                ],
            ),
            Message(
                role=Role.TOOL,
                content='{"key": "value"}',
                tool_call_id="call_read",
            ),
            Message(role=Role.ASSISTANT, content="The config contains key=value"),
        ]
        result = format_messages_for_summary(messages)

        # Check all parts are present
        assert "USER: Read the config file" in result
        assert "ASSISTANT: I'll read it" in result
        assert "read_file" in result
        assert "TOOL[call_read]:" in result
        assert "ASSISTANT: The config contains key=value" in result

    def test_empty_messages(self):
        """Test with empty message list."""
        result = format_messages_for_summary([])
        assert result == ""

    def test_message_with_empty_content(self):
        """Test message with empty content."""
        messages = [Message(role=Role.ASSISTANT, content="")]
        result = format_messages_for_summary(messages)
        assert result == "ASSISTANT: "


class TestCreateSummaryMessage:
    """Tests for create_summary_message()."""

    def test_creates_user_role_message(self):
        """Test that the summary message has USER role."""
        result = create_summary_message("This is a summary")
        assert result.role == Role.USER

    def test_includes_summary_prefix(self):
        """Test that the message includes the summary prefix with timestamp."""
        result = create_summary_message("This is a summary")
        # Check for constant parts of the prefix (timestamp varies)
        assert "[CONTEXT SUMMARY - Generated:" in result.content
        assert "automatically" in result.content
        assert "generated when the context window needed compaction" in result.content

    def test_summary_text_follows_prefix(self):
        """Test that the summary text appears after the prefix."""
        summary_text = "Key decisions were made about X"
        result = create_summary_message(summary_text)
        # Check prefix starts the content and summary text is at the end
        assert result.content.startswith("[CONTEXT SUMMARY")
        assert result.content.endswith(summary_text)

    def test_empty_summary(self):
        """Test with empty summary text."""
        result = create_summary_message("")
        assert result.role == Role.USER
        # Content should just be the prefix (with timestamp)
        assert "[CONTEXT SUMMARY - Generated:" in result.content

    def test_multiline_summary(self):
        """Test with multiline summary text."""
        summary_text = "Line 1\nLine 2\nLine 3"
        result = create_summary_message(summary_text)
        assert summary_text in result.content
        assert result.content.startswith("[CONTEXT SUMMARY")


class TestBuildSummarizePrompt:
    """Tests for build_summarize_prompt()."""

    def test_includes_conversation(self):
        """Test that the prompt includes the formatted conversation."""
        messages = [
            Message(role=Role.USER, content="Hello"),
            Message(role=Role.ASSISTANT, content="Hi there"),
        ]
        result = build_summarize_prompt(messages)
        assert "USER: Hello" in result
        assert "ASSISTANT: Hi there" in result

    def test_uses_summarize_prompt_template(self):
        """Test that the result uses the SUMMARIZE_PROMPT template structure."""
        messages = [Message(role=Role.USER, content="Test")]
        result = build_summarize_prompt(messages)

        # Check that key parts of the template are present
        assert "Summarize this conversation" in result
        assert "Preserve:" in result
        assert "Key decisions" in result
        assert "Files created/modified" in result
        assert "CONVERSATION:" in result
        assert "SUMMARY:" in result

    def test_conversation_in_correct_location(self):
        """Test that conversation appears between CONVERSATION: and SUMMARY:."""
        messages = [Message(role=Role.USER, content="UNIQUE_MARKER_TEXT")]
        result = build_summarize_prompt(messages)

        conv_pos = result.find("CONVERSATION:")
        summary_pos = result.find("SUMMARY:")
        marker_pos = result.find("UNIQUE_MARKER_TEXT")

        assert conv_pos < marker_pos < summary_pos

    def test_empty_messages(self):
        """Test with empty message list."""
        result = build_summarize_prompt([])
        assert "CONVERSATION:" in result
        assert "SUMMARY:" in result

    def test_complex_conversation(self):
        """Test with a complex conversation including tools."""
        messages = [
            Message(role=Role.USER, content="Create a file"),
            Message(
                role=Role.ASSISTANT,
                content="Creating",
                tool_calls=[
                    ToolCall(id="c1", name="write_file", arguments='{"path": "x.txt"}')
                ],
            ),
            Message(role=Role.TOOL, content="Done", tool_call_id="c1"),
        ]
        result = build_summarize_prompt(messages)
        assert "write_file" in result
        assert "TOOL[c1]" in result


class TestSelectMessagesForCompaction:
    """Tests for select_messages_for_compaction()."""

    def test_messages_under_budget_nothing_to_summarize(self):
        """When all messages fit in budget, nothing should be summarized."""
        messages = [
            Message(role=Role.USER, content="Hello"),
            Message(role=Role.ASSISTANT, content="Hi"),
        ]
        counter = MockTokenCounter(tokens_per_message=10)

        # Budget of 100 tokens, 2 messages at 10 tokens each = 20 tokens
        # Well under budget
        to_summarize, preserved = select_messages_for_compaction(
            messages=messages,
            token_counter=counter,
            available_budget=100,
            recent_preserve_ratio=0.5,
        )

        assert len(to_summarize) == 0
        assert len(preserved) == 2
        assert preserved == messages

    def test_recent_messages_preserved(self):
        """Recent messages should be preserved, older ones summarized."""
        messages = [
            Message(role=Role.USER, content="Old message 1"),
            Message(role=Role.ASSISTANT, content="Old message 2"),
            Message(role=Role.USER, content="Recent message 1"),
            Message(role=Role.ASSISTANT, content="Recent message 2"),
        ]
        counter = MockTokenCounter(tokens_per_message=10)

        # Budget of 40, preserve ratio 0.5 = 20 tokens for preserved
        # 20 tokens = 2 messages, so 2 recent should be preserved
        to_summarize, preserved = select_messages_for_compaction(
            messages=messages,
            token_counter=counter,
            available_budget=40,
            recent_preserve_ratio=0.5,
        )

        assert len(to_summarize) == 2
        assert len(preserved) == 2
        # Preserved should be the most recent
        assert preserved[0].content == "Recent message 1"
        assert preserved[1].content == "Recent message 2"
        # Summarized should be the oldest
        assert to_summarize[0].content == "Old message 1"
        assert to_summarize[1].content == "Old message 2"

    def test_older_messages_selected_for_summarization(self):
        """Older messages should be selected for summarization."""
        messages = [
            Message(role=Role.USER, content="Very old"),
            Message(role=Role.ASSISTANT, content="Old"),
            Message(role=Role.USER, content="Less old"),
            Message(role=Role.ASSISTANT, content="Recent"),
        ]
        counter = MockTokenCounter(tokens_per_message=10)

        # Preserve budget = 10 tokens = 1 message
        to_summarize, preserved = select_messages_for_compaction(
            messages=messages,
            token_counter=counter,
            available_budget=40,
            recent_preserve_ratio=0.25,
        )

        assert len(preserved) == 1
        assert preserved[0].content == "Recent"
        assert len(to_summarize) == 3
        assert to_summarize[0].content == "Very old"

    def test_different_preserve_ratios_high(self):
        """Test with high preserve ratio (0.75)."""
        messages = [
            Message(role=Role.USER, content=f"Message {i}") for i in range(4)
        ]
        counter = MockTokenCounter(tokens_per_message=10)

        # 100 budget, 0.75 ratio = 75 tokens = 7 messages preserved
        # But we only have 4 messages (40 tokens), so all preserved
        to_summarize, preserved = select_messages_for_compaction(
            messages=messages,
            token_counter=counter,
            available_budget=100,
            recent_preserve_ratio=0.75,
        )

        assert len(to_summarize) == 0
        assert len(preserved) == 4

    def test_different_preserve_ratios_low(self):
        """Test with low preserve ratio (0.1)."""
        messages = [
            Message(role=Role.USER, content=f"Message {i}") for i in range(10)
        ]
        counter = MockTokenCounter(tokens_per_message=10)

        # 100 budget, 0.1 ratio = 10 tokens = 1 message preserved
        to_summarize, preserved = select_messages_for_compaction(
            messages=messages,
            token_counter=counter,
            available_budget=100,
            recent_preserve_ratio=0.1,
        )

        assert len(preserved) == 1
        assert preserved[0].content == "Message 9"  # Most recent
        assert len(to_summarize) == 9

    def test_preserves_at_least_one_message(self):
        """Even with tiny budget, at least one message should be preserved."""
        messages = [
            Message(role=Role.USER, content="Only message"),
        ]
        counter = MockTokenCounter(tokens_per_message=10)

        # Very small budget
        to_summarize, preserved = select_messages_for_compaction(
            messages=messages,
            token_counter=counter,
            available_budget=5,
            recent_preserve_ratio=0.1,
        )

        # First message is always preserved (condition: preserved must not be empty)
        assert len(preserved) == 1
        assert len(to_summarize) == 0

    def test_empty_messages(self):
        """Test with empty message list."""
        to_summarize, preserved = select_messages_for_compaction(
            messages=[],
            token_counter=MockTokenCounter(),
            available_budget=100,
            recent_preserve_ratio=0.5,
        )

        assert len(to_summarize) == 0
        assert len(preserved) == 0

    def test_single_message_preserved(self):
        """Single message should be preserved, not summarized."""
        messages = [Message(role=Role.USER, content="Only one")]
        counter = MockTokenCounter(tokens_per_message=10)

        to_summarize, preserved = select_messages_for_compaction(
            messages=messages,
            token_counter=counter,
            available_budget=50,
            recent_preserve_ratio=0.5,
        )

        assert len(preserved) == 1
        assert len(to_summarize) == 0

    def test_message_order_preserved(self):
        """Verify message order is preserved in both lists."""
        messages = [
            Message(role=Role.USER, content="1"),
            Message(role=Role.ASSISTANT, content="2"),
            Message(role=Role.USER, content="3"),
            Message(role=Role.ASSISTANT, content="4"),
        ]
        counter = MockTokenCounter(tokens_per_message=10)

        to_summarize, preserved = select_messages_for_compaction(
            messages=messages,
            token_counter=counter,
            available_budget=40,
            recent_preserve_ratio=0.5,
        )

        # Order in to_summarize should be 1, 2 (oldest first)
        assert [m.content for m in to_summarize] == ["1", "2"]
        # Order in preserved should be 3, 4 (oldest first within preserved)
        assert [m.content for m in preserved] == ["3", "4"]

    def test_respects_token_counter(self):
        """Test that actual token counts are used."""
        messages = [
            Message(role=Role.USER, content="Short"),
            Message(role=Role.ASSISTANT, content="Also short"),
            Message(role=Role.USER, content="Recent"),
        ]

        # Use a counter where each message is 50 tokens
        counter = MockTokenCounter(tokens_per_message=50)

        # Budget 100, ratio 0.5 = 50 tokens preserved = 1 message
        to_summarize, preserved = select_messages_for_compaction(
            messages=messages,
            token_counter=counter,
            available_budget=100,
            recent_preserve_ratio=0.5,
        )

        assert len(preserved) == 1
        assert len(to_summarize) == 2

    def test_boundary_condition_exact_budget(self):
        """Test when messages exactly fit the budget."""
        messages = [
            Message(role=Role.USER, content="A"),
            Message(role=Role.ASSISTANT, content="B"),
        ]
        counter = MockTokenCounter(tokens_per_message=10)

        # 40 budget, 0.5 ratio = 20 tokens = exactly 2 messages
        to_summarize, preserved = select_messages_for_compaction(
            messages=messages,
            token_counter=counter,
            available_budget=40,
            recent_preserve_ratio=0.5,
        )

        assert len(preserved) == 2
        assert len(to_summarize) == 0

    def test_zero_preserve_ratio(self):
        """Test with zero preserve ratio - should still preserve first message."""
        messages = [
            Message(role=Role.USER, content="1"),
            Message(role=Role.ASSISTANT, content="2"),
        ]
        counter = MockTokenCounter(tokens_per_message=10)

        # 0 preserve ratio = 0 budget, but first message always preserved
        to_summarize, preserved = select_messages_for_compaction(
            messages=messages,
            token_counter=counter,
            available_budget=100,
            recent_preserve_ratio=0.0,
        )

        # Implementation preserves at least one if preserved list is empty
        assert len(preserved) == 1
        assert preserved[0].content == "2"
