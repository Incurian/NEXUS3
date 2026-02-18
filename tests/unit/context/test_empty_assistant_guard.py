"""Tests for empty assistant message guard in ContextManager.

Verifies:
- Empty messages (no content, no tool calls) are rejected
- Content-only messages are allowed
- Tool-only messages are allowed
- Warning is logged when empty message is skipped
"""

import pytest

from nexus3.context.manager import ContextManager
from nexus3.core.types import ToolCall


class TestEmptyAssistantGuard:
    """Guard blocks empty assistant messages from entering context."""

    @pytest.fixture
    def ctx(self) -> ContextManager:
        cm = ContextManager()
        cm.set_system_prompt("test")
        return cm

    def test_empty_message_rejected(self, ctx: ContextManager) -> None:
        """Empty content + no tool calls = message not added."""
        initial_count = len(ctx._messages)
        ctx.add_assistant_message("", None)
        assert len(ctx._messages) == initial_count

    def test_empty_content_empty_list_rejected(self, ctx: ContextManager) -> None:
        """Empty content + empty tool_calls list = message not added."""
        initial_count = len(ctx._messages)
        ctx.add_assistant_message("", [])
        assert len(ctx._messages) == initial_count

    def test_content_only_allowed(self, ctx: ContextManager) -> None:
        """Message with content but no tool calls is allowed."""
        initial_count = len(ctx._messages)
        ctx.add_assistant_message("Hello!", None)
        assert len(ctx._messages) == initial_count + 1
        assert ctx._messages[-1].content == "Hello!"

    def test_tool_only_allowed(self, ctx: ContextManager) -> None:
        """Message with tool calls but empty content is allowed."""
        tc = ToolCall(id="call_1", name="test", arguments={"a": 1})
        initial_count = len(ctx._messages)
        ctx.add_assistant_message("", [tc])
        assert len(ctx._messages) == initial_count + 1
        assert len(ctx._messages[-1].tool_calls) == 1

    def test_both_content_and_tools_allowed(self, ctx: ContextManager) -> None:
        """Message with both content and tool calls is allowed."""
        tc = ToolCall(id="call_1", name="test", arguments={})
        initial_count = len(ctx._messages)
        ctx.add_assistant_message("thinking...", [tc])
        assert len(ctx._messages) == initial_count + 1

    def test_logs_warning_on_empty(
        self, ctx: ContextManager, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Warning is logged when empty message is skipped."""
        with caplog.at_level("WARNING", logger="nexus3.context.manager"):
            ctx.add_assistant_message("", None)

        assert any("Skipping empty assistant message" in r.message for r in caplog.records)
