"""Tests for ContextManager."""

import pytest

from nexus3.context.manager import ContextConfig, ContextManager
from nexus3.core.types import Message, Role, ToolCall


class TestContextManagerBasics:
    """Test basic ContextManager functionality."""

    def test_add_user_message(self):
        """Test adding a user message."""
        ctx = ContextManager()
        ctx.add_user_message("Hello")

        assert len(ctx.messages) == 1
        assert ctx.messages[0].role == Role.USER
        assert ctx.messages[0].content == "Hello"

    def test_add_assistant_message(self):
        """Test adding an assistant message."""
        ctx = ContextManager()
        ctx.add_assistant_message("Hi there")

        assert len(ctx.messages) == 1
        assert ctx.messages[0].role == Role.ASSISTANT
        assert ctx.messages[0].content == "Hi there"

    def test_add_tool_result(self):
        """Test adding a tool result."""
        from nexus3.core.types import ToolResult

        ctx = ContextManager()
        ctx.add_tool_result("call-123", "my_tool", ToolResult(output="result"))

        assert len(ctx.messages) == 1
        assert ctx.messages[0].role == Role.TOOL
        assert ctx.messages[0].content == "result"
        assert ctx.messages[0].tool_call_id == "call-123"

    def test_set_system_prompt(self):
        """Test setting system prompt."""
        ctx = ContextManager()
        ctx.set_system_prompt("You are helpful.")

        assert ctx.system_prompt == "You are helpful."

    def test_build_messages_includes_system_prompt(self):
        """Test that build_messages includes system prompt first."""
        ctx = ContextManager()
        ctx.set_system_prompt("System prompt")
        ctx.add_user_message("Hello")

        messages = ctx.build_messages()

        assert len(messages) == 2
        assert messages[0].role == Role.SYSTEM
        assert messages[0].content == "System prompt"
        assert messages[1].role == Role.USER

    def test_clear_messages(self):
        """Test clearing messages."""
        ctx = ContextManager()
        ctx.add_user_message("Hello")
        ctx.add_assistant_message("Hi")
        ctx.clear_messages()

        assert len(ctx.messages) == 0


class TestContextManagerTruncation:
    """Test truncation behavior."""

    def test_no_truncation_when_under_budget(self):
        """Test that messages aren't truncated when under budget."""
        config = ContextConfig(max_tokens=10000, reserve_tokens=2000)
        ctx = ContextManager(config=config)

        ctx.add_user_message("Short message")
        ctx.add_assistant_message("Short response")

        messages = ctx.build_messages()
        assert len(messages) == 2
        assert len(ctx.messages) == 2  # _messages unchanged

    def test_truncation_syncs_messages(self):
        """Test that _messages is synced after truncation."""
        # Very small budget to force truncation
        config = ContextConfig(max_tokens=200, reserve_tokens=50)
        ctx = ContextManager(config=config)

        # Add many messages to exceed budget
        for i in range(20):
            ctx.add_user_message(f"Message {i} with some content to use tokens")
            ctx.add_assistant_message(f"Response {i} with some content")

        original_count = len(ctx.messages)
        assert original_count == 40

        # Build messages triggers truncation
        messages = ctx.build_messages()

        # _messages should now be synced with what was sent
        assert len(ctx.messages) == len(messages)
        assert len(ctx.messages) < original_count

    def test_truncation_preserves_tool_call_groups(self):
        """Test that truncation keeps tool_call + result together."""
        config = ContextConfig(max_tokens=500, reserve_tokens=100)
        ctx = ContextManager(config=config)

        # Add messages including tool calls
        ctx.add_user_message("Do something")
        ctx.add_assistant_message(
            "I'll use a tool",
            tool_calls=[ToolCall(id="call-1", name="my_tool", arguments="{}")]
        )
        from nexus3.core.types import ToolResult
        ctx.add_tool_result("call-1", "my_tool", ToolResult(output="result"))
        ctx.add_assistant_message("Done!")

        # Add more to force truncation
        for i in range(20):
            ctx.add_user_message(f"Extra message {i} " * 10)

        messages = ctx.build_messages()

        # Check that if any assistant with tool_calls exists, its results do too
        for i, msg in enumerate(messages):
            if msg.role == Role.ASSISTANT and msg.tool_calls:
                expected_ids = {tc.id for tc in msg.tool_calls}
                # Next messages should be the tool results
                j = i + 1
                found_ids = set()
                while j < len(messages) and messages[j].role == Role.TOOL:
                    found_ids.add(messages[j].tool_call_id)
                    j += 1
                assert expected_ids == found_ids, "Tool call/result pairs must stay together"

    def test_multiple_truncations_converge(self):
        """Test that repeated builds don't keep shrinking."""
        config = ContextConfig(max_tokens=300, reserve_tokens=50)
        ctx = ContextManager(config=config)

        # Add messages to exceed budget
        for i in range(10):
            ctx.add_user_message(f"Message {i} with content")
            ctx.add_assistant_message(f"Response {i}")

        # First build - triggers truncation
        messages1 = ctx.build_messages()
        count1 = len(ctx.messages)

        # Second build - should be stable (no further truncation)
        messages2 = ctx.build_messages()
        count2 = len(ctx.messages)

        assert count1 == count2
        assert messages1 == messages2

    def test_truncation_oldest_first_removes_oldest(self):
        """Test that oldest_first strategy removes oldest messages."""
        config = ContextConfig(
            max_tokens=150,  # Very small to force truncation
            reserve_tokens=50,
            truncation_strategy="oldest_first"
        )
        ctx = ContextManager(config=config)

        # Add numbered messages with enough content to exceed budget
        for i in range(10):
            ctx.add_user_message(f"Message number {i} with extra padding content here")

        original_count = len(ctx.messages)
        ctx.build_messages()

        # Should have truncated
        assert len(ctx.messages) < original_count, "Should have truncated some messages"

        # Most recent messages should be kept, oldest removed
        contents = [m.content for m in ctx.messages]
        # Message 9 (newest) should be present
        assert any("9" in c for c in contents), "Newest message should be kept"
        # Message 0 (oldest) should be gone
        assert not any("number 0 " in c for c in contents), "Oldest message should be removed"


class TestContextManagerTokenTracking:
    """Test token tracking."""

    def test_get_token_usage(self):
        """Test token usage reporting."""
        config = ContextConfig(max_tokens=8000, reserve_tokens=2000)
        ctx = ContextManager(config=config)
        ctx.set_system_prompt("System prompt")
        ctx.add_user_message("Hello")

        usage = ctx.get_token_usage()

        assert "system" in usage
        assert "messages" in usage
        assert "total" in usage
        assert "budget" in usage
        assert "available" in usage
        assert usage["budget"] == 8000
        assert usage["available"] == 6000

    def test_is_over_budget(self):
        """Test over budget detection."""
        config = ContextConfig(max_tokens=100, reserve_tokens=50)
        ctx = ContextManager(config=config)

        # Should not be over budget initially
        assert not ctx.is_over_budget()

        # Add lots of content to exceed budget
        ctx.add_user_message("x" * 1000)

        assert ctx.is_over_budget()
