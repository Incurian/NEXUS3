"""Tests for session cancellation handling.

These tests verify:
1. Session-level cancellation handling (prevents orphans by early exit)
2. Session adds results for remaining tools when cancelled mid-execution
3. Provider-level synthesis handles any orphans that slip through
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from nexus3.context import ContextConfig, ContextManager
from nexus3.core.cancel import CancellationToken
from nexus3.core.permissions import resolve_preset
from nexus3.core.types import (
    ContentDelta,
    Message,
    Role,
    StreamComplete,
    StreamEvent,
    ToolCall,
    ToolCallStarted,
    ToolResult,
)
from nexus3.session.events import SessionCancelled
from nexus3.session.session import Session
from nexus3.skill.base import BaseSkill
from nexus3.skill.registry import SkillRegistry
from nexus3.skill.services import ServiceContainer


def create_services_with_permissions() -> ServiceContainer:
    """Create a ServiceContainer with YOLO permissions for testing."""
    services = ServiceContainer()
    permissions = resolve_preset("yolo")
    services.register("permissions", permissions)
    return services


class MockProviderForCancellation:
    """Mock provider that returns tool calls for cancellation testing."""

    def __init__(self, tool_calls: list[ToolCall], content: str = "") -> None:
        self.tool_calls = tool_calls
        self.content = content
        self.call_count = 0

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Return a StreamComplete with tool calls."""
        self.call_count += 1
        # First, yield content if any
        if self.content:
            yield ContentDelta(text=self.content)
        # Yield tool call started events
        for idx, tc in enumerate(self.tool_calls):
            yield ToolCallStarted(index=idx, id=tc.id, name=tc.name)
        # Yield final complete
        yield StreamComplete(
            message=Message(
                role=Role.ASSISTANT,
                content=self.content,
                tool_calls=tuple(self.tool_calls),
            )
        )


class SlowSkill(BaseSkill):
    """Skill that can be configured to be slow or raise CancelledError."""

    def __init__(
        self,
        delay: float = 0,
        raise_cancelled: bool = False,
        cancel_token: CancellationToken | None = None,
    ):
        super().__init__(
            name="slow_skill",
            description="A slow skill for testing",
            parameters={"type": "object", "properties": {}},
        )
        self._delay = delay
        self._raise_cancelled = raise_cancelled
        self._cancel_token = cancel_token
        self.execution_count = 0

    async def execute(self, **kwargs: Any) -> ToolResult:
        self.execution_count += 1
        if self._delay > 0:
            await asyncio.sleep(self._delay)
        if self._raise_cancelled:
            raise asyncio.CancelledError()
        if self._cancel_token:
            self._cancel_token.cancel()
        return ToolResult(output=f"Executed {self.execution_count}")


class TestEarlyCancellationPreventsOrphans:
    """Test that cancellation before assistant message prevents orphans."""

    @pytest.mark.asyncio
    async def test_cancellation_before_assistant_message_no_orphans(self):
        """When cancelled before assistant message added, no orphans exist."""
        tool_calls = [
            ToolCall(id="tc1", name="slow_skill", arguments={}),
            ToolCall(id="tc2", name="slow_skill", arguments={}),
            ToolCall(id="tc3", name="slow_skill", arguments={}),
        ]

        provider = MockProviderForCancellation(tool_calls)
        context = ContextManager(config=ContextConfig(max_tokens=10000))
        context.set_system_prompt("System prompt")

        services = create_services_with_permissions()
        registry = SkillRegistry(services=services)
        registry.register("slow_skill", lambda _: SlowSkill())

        session = Session(
            provider=provider,
            context=context,
            registry=registry,
            services=services,
        )

        # Cancel immediately - this will be detected after provider returns
        # but BEFORE the assistant message is added to context
        cancel_token = CancellationToken()
        cancel_token.cancel()

        # Execute
        events = []
        async for event in session.run_turn("Test", cancel_token=cancel_token):
            events.append(event)

        # Verify SessionCancelled was yielded
        assert any(isinstance(e, SessionCancelled) for e in events)

        # Key invariant: NO orphaned tool_use blocks because assistant message
        # was never added to context
        assistant_messages = [
            m for m in context.messages if m.role == Role.ASSISTANT
        ]
        tool_results = [
            m for m in context.messages if m.role == Role.TOOL
        ]

        # Either no assistant message (clean early exit), or if there is one,
        # all its tool_calls have matching results
        if assistant_messages:
            tool_call_ids = set()
            for msg in assistant_messages:
                tool_call_ids.update(tc.id for tc in msg.tool_calls)
            result_ids = {m.tool_call_id for m in tool_results}
            assert result_ids == tool_call_ids
        else:
            # No assistant message = no orphans possible
            assert len(tool_results) == 0


class TestSequentialCancellationAddsResults:
    """Test that sequential cancellation adds results for remaining tools."""

    @pytest.mark.asyncio
    async def test_cancellation_after_first_tool_adds_remaining_results(self):
        """When cancelled after first tool, remaining tools get results."""
        tool_calls = [
            ToolCall(id="tc1", name="slow_skill", arguments={}),
            ToolCall(id="tc2", name="slow_skill", arguments={}),
            ToolCall(id="tc3", name="slow_skill", arguments={}),
        ]

        provider = MockProviderForCancellation(tool_calls)
        context = ContextManager(config=ContextConfig(max_tokens=10000))
        context.set_system_prompt("System prompt")

        cancel_token = CancellationToken()

        services = create_services_with_permissions()
        registry = SkillRegistry(services=services)
        # This skill cancels the token after first execution
        skill = SlowSkill(cancel_token=cancel_token)
        registry.register("slow_skill", lambda _: skill)

        session = Session(
            provider=provider,
            context=context,
            registry=registry,
            services=services,
        )

        # Execute
        events = []
        async for event in session.run_turn("Test", cancel_token=cancel_token):
            events.append(event)

        # Verify SessionCancelled was yielded
        assert any(isinstance(e, SessionCancelled) for e in events)

        # Verify all 3 tools got results in context
        tool_results = [
            m for m in context.messages if m.role == Role.TOOL
        ]
        assert len(tool_results) == 3

        # First tool should have executed successfully
        assert "Executed 1" in tool_results[0].content

        # Remaining tools should have cancelled errors
        assert "Cancelled by user" in tool_results[1].content
        assert "Cancelled by user" in tool_results[2].content


class TestMidExecutionCancellation:
    """Test cancellation during tool execution (CancelledError)."""

    @pytest.mark.asyncio
    async def test_cancelled_error_during_tool_creates_result(self):
        """CancelledError during tool execution creates cancelled result."""
        tool_calls = [
            ToolCall(id="tc1", name="slow_skill", arguments={}),
        ]

        provider = MockProviderForCancellation(tool_calls)
        context = ContextManager(config=ContextConfig(max_tokens=10000))
        context.set_system_prompt("System prompt")

        services = create_services_with_permissions()
        registry = SkillRegistry(services=services)
        # This skill raises CancelledError
        registry.register("slow_skill", lambda _: SlowSkill(raise_cancelled=True))

        session = Session(
            provider=provider,
            context=context,
            registry=registry,
            services=services,
            max_tool_iterations=1,  # Limit to 1 iteration to focus on cancellation
        )

        cancel_token = CancellationToken()

        # Execute
        events = []
        async for event in session.run_turn("Test", cancel_token=cancel_token):
            events.append(event)

        # Tool should have a cancelled result in context (at least one)
        tool_results = [
            m for m in context.messages if m.role == Role.TOOL
        ]
        assert len(tool_results) >= 1
        # First result should be the cancelled one
        assert "Cancelled by user" in tool_results[0].content


class TestToolResultCompleteness:
    """Test that context always has matching tool_use/tool_result pairs."""

    @pytest.mark.asyncio
    async def test_tool_calls_have_results_when_cancelled_mid_execution(self):
        """When cancelled during tool execution, all tool_calls have results."""
        tool_calls = [
            ToolCall(id="tc1", name="slow_skill", arguments={}),
            ToolCall(id="tc2", name="slow_skill", arguments={}),
            ToolCall(id="tc3", name="slow_skill", arguments={}),
        ]
        tool_call_ids = {tc.id for tc in tool_calls}

        provider = MockProviderForCancellation(tool_calls)
        context = ContextManager(config=ContextConfig(max_tokens=10000))
        context.set_system_prompt("System prompt")

        cancel_token = CancellationToken()

        services = create_services_with_permissions()
        registry = SkillRegistry(services=services)
        # Cancel after first tool executes
        skill = SlowSkill(cancel_token=cancel_token)
        registry.register("slow_skill", lambda _: skill)

        session = Session(
            provider=provider,
            context=context,
            registry=registry,
            services=services,
        )

        async for _ in session.run_turn("Test", cancel_token=cancel_token):
            pass

        # Key invariant: every tool_call_id has a corresponding result
        result_ids = {
            m.tool_call_id
            for m in context.messages
            if m.role == Role.TOOL
        }

        assert result_ids == tool_call_ids, (
            f"Missing results for tool_calls: {tool_call_ids - result_ids}"
        )


class TestProviderSynthesizesMissingResults:
    """Test that Anthropic provider synthesizes missing tool_results."""

    def test_provider_synthesizes_orphaned_tool_use_blocks(self):
        """Provider synthesizes results for orphaned tool_use blocks."""
        from nexus3.provider.anthropic import AnthropicProvider
        from nexus3.config.schema import ProviderConfig

        # Create a minimal provider config
        config = ProviderConfig(
            type="anthropic",
            base_url="https://api.anthropic.com",
            api_key_env="ANTHROPIC_API_KEY",
        )

        # We can't fully instantiate without API key, so test the method directly
        # by creating a mock instance
        provider = object.__new__(AnthropicProvider)

        # Create messages with orphaned tool_use blocks (no tool_results)
        messages = [
            Message(role=Role.USER, content="Read some files"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=(
                    ToolCall(id="tc1", name="read_file", arguments={"path": "a.txt"}),
                    ToolCall(id="tc2", name="read_file", arguments={"path": "b.txt"}),
                    ToolCall(id="tc3", name="read_file", arguments={"path": "c.txt"}),
                ),
            ),
            # Only one tool_result - orphaning tc2 and tc3
            Message(role=Role.TOOL, content="contents of a.txt", tool_call_id="tc1"),
        ]

        # Call _convert_messages directly
        result = provider._convert_messages(messages)

        # Should have: user message, assistant message, user message with tool_results
        assert len(result) == 3

        # The last user message should have all 3 tool_results
        last_user = result[-1]
        assert last_user["role"] == "user"

        tool_result_ids = {
            block["tool_use_id"]
            for block in last_user["content"]
            if block["type"] == "tool_result"
        }

        # All 3 tool_use blocks should have results
        assert tool_result_ids == {"tc1", "tc2", "tc3"}

        # The synthetic results should indicate interruption
        for block in last_user["content"]:
            if block["type"] == "tool_result" and block["tool_use_id"] in {"tc2", "tc3"}:
                assert "interrupted" in block["content"].lower()

    def test_provider_no_synthesis_when_all_results_present(self):
        """Provider doesn't synthesize when all tool_results are present."""
        from nexus3.provider.anthropic import AnthropicProvider

        provider = object.__new__(AnthropicProvider)

        # Create messages with complete tool_use/tool_result pairs
        messages = [
            Message(role=Role.USER, content="Read some files"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=(
                    ToolCall(id="tc1", name="read_file", arguments={"path": "a.txt"}),
                    ToolCall(id="tc2", name="read_file", arguments={"path": "b.txt"}),
                ),
            ),
            Message(role=Role.TOOL, content="contents of a.txt", tool_call_id="tc1"),
            Message(role=Role.TOOL, content="contents of b.txt", tool_call_id="tc2"),
        ]

        result = provider._convert_messages(messages)

        # Should have: user message, assistant message, user message with tool_results
        assert len(result) == 3

        # The last user message should have exactly 2 tool_results
        last_user = result[-1]
        tool_results = [
            b for b in last_user["content"] if b["type"] == "tool_result"
        ]
        assert len(tool_results) == 2

        # No synthetic "interrupted" messages
        for block in tool_results:
            assert "interrupted" not in block["content"].lower()
