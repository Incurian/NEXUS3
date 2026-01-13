"""Integration tests for skill execution in Session.

Tests the tool execution loop in Session class, verifying that:
1. Session works without tools (backwards compatible)
2. Tool calls are properly executed via registry
3. The tool loop correctly handles multi-step tool use
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from nexus3.context import ContextConfig, ContextManager
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
from nexus3.session.session import Session
from nexus3.skill.base import BaseSkill
from nexus3.skill.registry import SkillRegistry
from nexus3.skill.services import ServiceContainer


class MockProviderWithTools:
    """Mock provider that returns predefined Messages, supporting tool calls.

    This provider returns responses from a queue, allowing tests to simulate
    multi-step tool interactions where the provider first returns tool calls,
    then returns a final response.
    """

    def __init__(self, responses: list[Message]) -> None:
        """Initialize with a list of responses to return in order.

        Args:
            responses: List of Messages to return. Each call to stream()
                      returns the next message in the list as StreamEvents.
        """
        self.responses = responses
        self.call_count = 0
        self.last_messages: list[Message] | None = None
        self.last_tools: list[dict[str, Any]] | None = None
        self.all_messages_history: list[list[Message]] = []

    async def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> Message:
        """Return the next predefined response.

        Args:
            messages: The conversation messages (stored for assertions).
            tools: Tool definitions (stored for assertions).

        Returns:
            Next Message from the response queue, or a default "Done" message
            if the queue is exhausted.
        """
        self.last_messages = messages
        self.last_tools = tools
        self.all_messages_history.append(list(messages))
        self.call_count += 1

        if self.call_count <= len(self.responses):
            return self.responses[self.call_count - 1]

        # Default response when queue exhausted
        return Message(role=Role.ASSISTANT, content="Done")

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream response as StreamEvents.

        Uses the responses queue to return appropriate events.
        For tool-based tests, this consumes from the same queue as complete().

        Args:
            messages: The conversation messages.
            tools: Tool definitions (stored for assertions).

        Yields:
            StreamEvent objects based on the next queued response.
        """
        self.last_messages = messages
        self.last_tools = tools
        self.all_messages_history.append(list(messages))
        self.call_count += 1

        # Get the next response from queue
        if self.call_count <= len(self.responses):
            response = self.responses[self.call_count - 1]
        else:
            # Default response
            response = Message(role=Role.ASSISTANT, content="Hello there")

        # Yield content as ContentDelta if present
        if response.content:
            # Split content into chunks for realistic streaming
            content = response.content
            chunk_size = max(len(content) // 3, 1)
            for i in range(0, len(content), chunk_size):
                yield ContentDelta(text=content[i : i + chunk_size])

        # Yield ToolCallStarted for each tool call
        for idx, tc in enumerate(response.tool_calls):
            yield ToolCallStarted(index=idx, id=tc.id, name=tc.name)

        # Yield final StreamComplete with the full message
        yield StreamComplete(message=response)


class EchoSkill(BaseSkill):
    """Simple test skill that echoes back the message."""

    def __init__(self) -> None:
        super().__init__(
            name="echo",
            description="Echo back the input message",
            parameters={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Message to echo back",
                    }
                },
                "required": ["message"],
            },
        )
        self.call_count = 0
        self.last_message: str | None = None

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Echo the message back.

        Args:
            **kwargs: Must include 'message' key.

        Returns:
            ToolResult with the echoed message.
        """
        self.call_count += 1
        self.last_message = kwargs.get("message", "")
        return ToolResult(output=f"Echo: {self.last_message}")


class FailingSkill(BaseSkill):
    """Test skill that always returns an error."""

    def __init__(self) -> None:
        super().__init__(
            name="failing",
            description="A skill that always fails",
            parameters={
                "type": "object",
                "properties": {},
            },
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Always return an error.

        Returns:
            ToolResult with error message.
        """
        return ToolResult(error="This skill always fails")


class TestSessionWithoutTools:
    """Tests verifying Session works without a registry (backwards compatibility)."""

    @pytest.mark.asyncio
    async def test_session_streams_without_registry(self) -> None:
        """Session should stream normally when no registry is provided."""
        provider = MockProviderWithTools([])
        session = Session(provider)

        chunks = [chunk async for chunk in session.send("Hello")]

        assert "".join(chunks) == "Hello there"
        assert provider.last_messages is not None
        assert len(provider.last_messages) == 1
        assert provider.last_messages[0].content == "Hello"

    @pytest.mark.asyncio
    async def test_session_with_context_but_no_registry(self) -> None:
        """Session with context but no registry should stream normally."""
        provider = MockProviderWithTools([])
        context = ContextManager(config=ContextConfig())
        context.set_system_prompt("You are helpful.")
        session = Session(provider, context=context)

        chunks = [chunk async for chunk in session.send("Hi")]

        assert "".join(chunks) == "Hello there"
        # Context should have user message added
        assert len(context.messages) == 2  # user + assistant
        assert context.messages[0].role == Role.USER
        assert context.messages[1].role == Role.ASSISTANT

    @pytest.mark.asyncio
    async def test_session_with_empty_registry(self) -> None:
        """Session with empty registry should stream normally."""
        provider = MockProviderWithTools([])
        context = ContextManager(config=ContextConfig())
        registry = SkillRegistry()
        session = Session(provider, context=context, registry=registry)

        chunks = [chunk async for chunk in session.send("Hello")]

        # Empty registry means no tools, so should stream
        assert "".join(chunks) == "Hello there"


class TestSessionWithEchoTool:
    """Tests for Session executing a simple echo tool."""

    @pytest.mark.asyncio
    async def test_tool_call_executes_skill(self) -> None:
        """Provider returns tool call, skill executes, final response returned."""
        # Setup: Provider returns tool call, then final response
        responses = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=(
                    ToolCall(id="call_1", name="echo", arguments={"message": "test"}),
                ),
            ),
            Message(
                role=Role.ASSISTANT,
                content="The echo result was received.",
            ),
        ]
        provider = MockProviderWithTools(responses)

        # Create context, registry, and session
        context = ContextManager(config=ContextConfig())
        registry = SkillRegistry()
        echo_skill = EchoSkill()
        registry.register("echo", lambda _: echo_skill)
        session = Session(provider, context=context, registry=registry)

        # Execute
        result = [chunk async for chunk in session.send("Say test")]

        # Verify skill was called
        assert echo_skill.call_count == 1
        assert echo_skill.last_message == "test"

        # Verify final response (chunks joined)
        assert "".join(result) == "The echo result was received."

        # Verify provider was called twice (tool call + final)
        assert provider.call_count == 2

    @pytest.mark.asyncio
    async def test_tool_result_added_to_context(self) -> None:
        """Tool results should be added to context for the next provider call."""
        responses = [
            Message(
                role=Role.ASSISTANT,
                content="Calling tool",
                tool_calls=(
                    ToolCall(id="call_1", name="echo", arguments={"message": "hello"}),
                ),
            ),
            Message(
                role=Role.ASSISTANT,
                content="Done",
            ),
        ]
        provider = MockProviderWithTools(responses)

        context = ContextManager(config=ContextConfig())
        registry = SkillRegistry()
        echo_skill = EchoSkill()
        registry.register("echo", lambda _: echo_skill)
        session = Session(provider, context=context, registry=registry)

        _ = [chunk async for chunk in session.send("Test")]

        # Check context has all messages
        messages = context.messages
        assert len(messages) == 4  # user, assistant+tool_call, tool_result, final_assistant

        # Verify tool result message
        tool_result_msg = messages[2]
        assert tool_result_msg.role == Role.TOOL
        assert tool_result_msg.tool_call_id == "call_1"
        assert "Echo: hello" in tool_result_msg.content

    @pytest.mark.asyncio
    async def test_provider_receives_tool_definitions(self) -> None:
        """Provider should receive tool definitions when registry has tools."""
        responses = [
            Message(role=Role.ASSISTANT, content="No tools needed"),
        ]
        provider = MockProviderWithTools(responses)

        context = ContextManager(config=ContextConfig())
        registry = SkillRegistry()
        registry.register("echo", lambda _: EchoSkill())

        # Set tool definitions on context (normally done by AgentPool)
        tool_defs = registry.get_definitions()
        context.set_tool_definitions(tool_defs)

        session = Session(provider, context=context, registry=registry)

        _ = [chunk async for chunk in session.send("Hi")]

        # Provider should have received tool definitions
        assert provider.last_tools is not None
        assert len(provider.last_tools) == 1
        assert provider.last_tools[0]["function"]["name"] == "echo"


class TestToolLoopCompletes:
    """Tests for the complete tool execution loop."""

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_in_sequence(self) -> None:
        """Provider can make multiple sequential tool calls before final response."""
        responses = [
            # First response: one tool call
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=(
                    ToolCall(id="call_1", name="echo", arguments={"message": "first"}),
                ),
            ),
            # Second response: another tool call
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=(
                    ToolCall(id="call_2", name="echo", arguments={"message": "second"}),
                ),
            ),
            # Final response: no tool calls
            Message(
                role=Role.ASSISTANT,
                content="Both echoes completed",
            ),
        ]
        provider = MockProviderWithTools(responses)

        context = ContextManager(config=ContextConfig())
        registry = SkillRegistry()
        echo_skill = EchoSkill()
        registry.register("echo", lambda _: echo_skill)
        session = Session(provider, context=context, registry=registry)

        result = [chunk async for chunk in session.send("Test")]

        # Verify skill was called twice
        assert echo_skill.call_count == 2

        # Verify final response (chunks joined)
        assert "".join(result) == "Both echoes completed"

        # Verify provider was called three times
        assert provider.call_count == 3

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_in_parallel(self) -> None:
        """Single response can contain multiple tool calls to execute in parallel."""
        responses = [
            # First response: two tool calls at once
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=(
                    ToolCall(id="call_1", name="echo", arguments={"message": "one"}),
                    ToolCall(id="call_2", name="echo", arguments={"message": "two"}),
                ),
            ),
            # Final response
            Message(
                role=Role.ASSISTANT,
                content="Both done",
            ),
        ]
        provider = MockProviderWithTools(responses)

        context = ContextManager(config=ContextConfig())
        registry = SkillRegistry()
        echo_skill = EchoSkill()
        registry.register("echo", lambda _: echo_skill)
        session = Session(provider, context=context, registry=registry)

        result = [chunk async for chunk in session.send("Test")]

        # Verify skill was called twice
        assert echo_skill.call_count == 2

        # Verify both tool results in context
        messages = context.messages
        tool_results = [m for m in messages if m.role == Role.TOOL]
        assert len(tool_results) == 2

        # Verify final response (chunks joined)
        assert "".join(result) == "Both done"

    @pytest.mark.asyncio
    async def test_unknown_skill_returns_error(self) -> None:
        """Calling unknown skill should return error result."""
        responses = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=(
                    ToolCall(
                        id="call_1", name="nonexistent", arguments={"foo": "bar"}
                    ),
                ),
            ),
            Message(
                role=Role.ASSISTANT,
                content="Tool not found",
            ),
        ]
        provider = MockProviderWithTools(responses)

        context = ContextManager(config=ContextConfig())
        registry = SkillRegistry()
        registry.register("echo", lambda _: EchoSkill())
        session = Session(provider, context=context, registry=registry)

        result = [chunk async for chunk in session.send("Test")]

        # Should still complete with final response (chunks joined)
        assert "".join(result) == "Tool not found"

        # Context should have error message for the unknown tool
        messages = context.messages
        tool_results = [m for m in messages if m.role == Role.TOOL]
        assert len(tool_results) == 1
        assert "Unknown skill: nonexistent" in tool_results[0].content

    @pytest.mark.asyncio
    async def test_failing_skill_error_in_context(self) -> None:
        """Skill returning error should have error in context."""
        responses = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=(
                    ToolCall(id="call_1", name="failing", arguments={}),
                ),
            ),
            Message(
                role=Role.ASSISTANT,
                content="Tool failed as expected",
            ),
        ]
        provider = MockProviderWithTools(responses)

        context = ContextManager(config=ContextConfig())
        registry = SkillRegistry()
        registry.register("failing", lambda _: FailingSkill())
        session = Session(provider, context=context, registry=registry)

        result = [chunk async for chunk in session.send("Test")]

        # Should complete with final response (chunks joined)
        assert "".join(result) == "Tool failed as expected"

        # Context should have error from failing skill
        messages = context.messages
        tool_results = [m for m in messages if m.role == Role.TOOL]
        assert len(tool_results) == 1
        assert "This skill always fails" in tool_results[0].content

    @pytest.mark.asyncio
    async def test_max_iterations_prevents_infinite_loop(self) -> None:
        """Tool loop should stop after max iterations to prevent infinite loops."""
        # Create responses that always return tool calls (would loop forever)
        responses = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=(
                    ToolCall(id=f"call_{i}", name="echo", arguments={"message": "loop"}),
                ),
            )
            for i in range(15)  # More than max_iterations (10)
        ]
        provider = MockProviderWithTools(responses)

        context = ContextManager(config=ContextConfig())
        registry = SkillRegistry()
        registry.register("echo", lambda _: EchoSkill())
        session = Session(provider, context=context, registry=registry)

        result = [chunk async for chunk in session.send("Test")]

        # Should return max iterations message
        assert result == ["[Max tool iterations reached]"]

        # Should have stopped at 10 iterations
        assert provider.call_count == 10

    @pytest.mark.asyncio
    async def test_tool_loop_builds_correct_messages(self) -> None:
        """Verify the messages sent to provider include tool results."""
        responses = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=(
                    ToolCall(id="call_1", name="echo", arguments={"message": "test"}),
                ),
            ),
            Message(
                role=Role.ASSISTANT,
                content="Final",
            ),
        ]
        provider = MockProviderWithTools(responses)

        context = ContextManager(config=ContextConfig())
        registry = SkillRegistry()
        registry.register("echo", lambda _: EchoSkill())
        session = Session(provider, context=context, registry=registry)

        _ = [chunk async for chunk in session.send("Hello")]

        # First call should have just user message
        first_call_messages = provider.all_messages_history[0]
        assert len(first_call_messages) == 1
        assert first_call_messages[0].role == Role.USER

        # Second call should have user, assistant (with tool calls), and tool result
        second_call_messages = provider.all_messages_history[1]
        assert len(second_call_messages) == 3

        # Verify message roles
        assert second_call_messages[0].role == Role.USER
        assert second_call_messages[1].role == Role.ASSISTANT
        assert second_call_messages[1].tool_calls  # Has tool calls
        assert second_call_messages[2].role == Role.TOOL
        assert second_call_messages[2].tool_call_id == "call_1"
