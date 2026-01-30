"""Tests for session cancellation handling.

These tests verify that when tool execution is cancelled, all tool_use blocks
get matching tool_result blocks to satisfy Anthropic API protocol requirements.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

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


class TestSequentialCancellationAddsResults:
    """Test that sequential cancellation adds results for remaining tools."""

    @pytest.mark.asyncio
    async def test_cancellation_before_first_tool_adds_all_results(self):
        """When cancelled before any tool executes, all tools get results."""
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

        # Cancel immediately
        cancel_token = CancellationToken()
        cancel_token.cancel()

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
        for result in tool_results:
            assert "Cancelled by user" in result.content

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
    async def test_all_tool_calls_have_results_after_cancellation(self):
        """After any cancellation scenario, all tool_calls have results."""
        tool_calls = [
            ToolCall(id="tc1", name="slow_skill", arguments={}),
            ToolCall(id="tc2", name="slow_skill", arguments={}),
            ToolCall(id="tc3", name="slow_skill", arguments={}),
        ]
        tool_call_ids = {tc.id for tc in tool_calls}

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

        # Cancel immediately
        cancel_token = CancellationToken()
        cancel_token.cancel()

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
