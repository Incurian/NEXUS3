"""Tests for session cancellation handling.

These tests verify:
1. Session-level cancellation handling (prevents orphans by early exit)
2. Session adds results for remaining tools when cancelled mid-execution
3. Compiler-backed preflight normalization preserves role-sequence invariants
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from nexus3.context import ContextConfig, ContextManager
from nexus3.context.compiler import validate_compiled_message_invariants
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
from nexus3.session.tool_loop_events_runtime import execute_tool_loop_events
from nexus3.skill.base import BaseSkill
from nexus3.skill.registry import SkillRegistry
from nexus3.skill.services import ServiceContainer


def create_services_with_permissions() -> ServiceContainer:
    """Create a ServiceContainer with YOLO permissions for testing."""
    services = ServiceContainer()
    permissions = resolve_preset("yolo")
    services.set_permissions(permissions)
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
        dynamic_context: str | None = None,
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


class MockProviderWithoutStreamComplete:
    """Mock provider that emits an event but never yields StreamComplete."""

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        dynamic_context: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        yield ToolCallStarted(index=0, id="tc1", name="slow_skill")
        return


class MockProviderRejectToolThenUser:
    """Provider that fails if TOOL is immediately followed by USER."""

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        dynamic_context: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        for i in range(len(messages) - 1):
            if messages[i].role == Role.TOOL and messages[i + 1].role == Role.USER:
                raise AssertionError("Unexpected role 'user' after role 'tool'")
        yield StreamComplete(
            message=Message(role=Role.ASSISTANT, content="ok", tool_calls=())
        )


class MockProviderCapturePreflight:
    """Provider that captures request messages for invariant assertions."""

    def __init__(self, response_text: str = "ok") -> None:
        self.response_text = response_text
        self.captured_messages: list[list[Message]] = []

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        dynamic_context: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        self.captured_messages.append(list(messages))
        yield StreamComplete(
            message=Message(role=Role.ASSISTANT, content=self.response_text, tool_calls=())
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

    @pytest.mark.asyncio
    async def test_cancel_mid_stream_before_stream_complete_reports_cancelled(self):
        """Cancellation after non-content stream event yields SessionCancelled."""
        provider = MockProviderWithoutStreamComplete()
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

        cancel_token = CancellationToken()
        events = []
        async for event in session.run_turn("Test", use_tools=True, cancel_token=cancel_token):
            events.append(event)
            # Simulate ESC after first stream event, before any StreamComplete.
            if len(events) == 1:
                cancel_token.cancel()

        assert any(isinstance(e, SessionCancelled) for e in events)


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


class TestProviderCompilerIntegration:
    """Anthropic request shaping now relies on compiler-driven repair."""

    def test_convert_messages_does_not_synthesize_orphaned_tool_use_blocks(self):
        """Local Anthropic conversion should not synthesize missing tool results."""
        from nexus3.provider.anthropic import AnthropicProvider

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

        # The last user message should contain only existing tool_results.
        last_user = result[-1]
        assert last_user["role"] == "user"

        tool_result_ids = {
            block["tool_use_id"]
            for block in last_user["content"]
            if block["type"] == "tool_result"
        }

        assert tool_result_ids == {"tc1"}

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

    def test_build_request_body_synthesizes_missing_results_via_compiler(self):
        """Compiler integration should synthesize missing tool results before conversion."""
        from nexus3.config.schema import ProviderConfig
        from nexus3.provider.anthropic import AnthropicProvider

        provider = object.__new__(AnthropicProvider)
        provider._config = ProviderConfig(
            type="anthropic",
            api_key_env="ANTHROPIC_API_KEY",
            prompt_caching=False,
        )
        provider._model = "claude-haiku-4-5"

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
        ]

        body = provider._build_request_body(messages, tools=None, stream=False)
        trailing_user = body["messages"][-1]
        tool_results = [
            block for block in trailing_user["content"] if block["type"] == "tool_result"
        ]
        tool_ids = {block["tool_use_id"] for block in tool_results}

        assert tool_ids == {"tc1", "tc2"}
        assert any(
            block["tool_use_id"] == "tc2" and "interrupted" in block["content"].lower()
            for block in tool_results
        )


class TestCancelledToolFlushSafety:
    """Ensure pending cancelled tools do not create orphan TOOL messages."""

    @pytest.mark.asyncio
    async def test_stale_cancelled_tools_are_dropped(self):
        """Cancelled tool IDs without matching assistant tool_call are ignored."""
        provider = MockProviderForCancellation(tool_calls=[], content="ok")
        context = ContextManager(config=ContextConfig(max_tokens=10000))
        context.set_system_prompt("System prompt")

        services = create_services_with_permissions()
        session = Session(
            provider=provider,
            context=context,
            registry=None,
            services=services,
        )

        # Simulate stale pending cancellation from an interrupted turn where no
        # assistant tool_call message was persisted.
        session.add_cancelled_tools([("stale-tool-id", "read_file")])

        chunks = []
        async for chunk in session.send("hello"):
            chunks.append(chunk)

        assert "".join(chunks) == "ok"
        assert not any(m.role == Role.TOOL for m in context.messages)

    @pytest.mark.asyncio
    async def test_cancelled_tool_tail_repaired_before_next_user_turn(self):
        """A cancelled tool tail should not produce TOOL->USER sequence next turn."""
        # First provider creates a tool call batch.
        provider = MockProviderForCancellation(
            tool_calls=[ToolCall(id="tc1", name="slow_skill", arguments={})]
        )
        context = ContextManager(config=ContextConfig(max_tokens=10000))
        context.set_system_prompt("System prompt")

        cancel_token = CancellationToken()
        services = create_services_with_permissions()
        registry = SkillRegistry(services=services)
        # This skill executes once and cancels the token, leaving tool-tail state.
        registry.register("slow_skill", lambda _: SlowSkill(cancel_token=cancel_token))

        session = Session(
            provider=provider,
            context=context,
            registry=registry,
            services=services,
        )

        # First turn: cancellation after tool execution.
        async for _ in session.run_turn("first", cancel_token=cancel_token):
            pass

        # Second turn provider asserts no TOOL->USER adjacency.
        session.provider = MockProviderRejectToolThenUser()
        chunks = []
        async for chunk in session.send("second"):
            chunks.append(chunk)

        # No assertion error means no TOOL->USER violation in provider input.
        # Response may arrive as StreamComplete-only (no ContentDelta chunks),
        # so validate persisted assistant message instead.
        assert context.messages[-1].role == Role.ASSISTANT
        assert context.messages[-1].content == "ok"


class TestCompilerBackedPreflightNormalization:
    """Session preflight should normalize context through compiler invariants."""

    @pytest.mark.asyncio
    async def test_preflight_repairs_orphaned_tool_batch_before_user_turn(self) -> None:
        provider = MockProviderCapturePreflight()
        context = ContextManager(config=ContextConfig(max_tokens=10000))
        context.set_system_prompt("System prompt")

        context.add_assistant_message(
            "",
            tool_calls=[
                ToolCall(id="tc1", name="read_file", arguments={"path": "a.txt"}),
                ToolCall(id="tc2", name="read_file", arguments={"path": "b.txt"}),
            ],
        )
        context.add_tool_result("tc1", "read_file", ToolResult(output="a contents"))

        services = create_services_with_permissions()
        session = Session(
            provider=provider,
            context=context,
            registry=None,
            services=services,
        )

        async for _ in session.send("next"):
            pass

        assert provider.captured_messages
        request_messages = provider.captured_messages[-1]
        assert validate_compiled_message_invariants(request_messages) == []

        for i in range(len(request_messages) - 1):
            assert not (
                request_messages[i].role == Role.TOOL
                and request_messages[i + 1].role == Role.USER
            )

        tool_result_ids = {
            msg.tool_call_id
            for msg in request_messages
            if msg.role == Role.TOOL and msg.tool_call_id is not None
        }
        assert tool_result_ids == {"tc1", "tc2"}
        assert any(
            msg.role == Role.ASSISTANT
            and msg.content == "Previous turn was cancelled after tool execution."
            for msg in request_messages
        )

    @pytest.mark.asyncio
    async def test_preflight_prunes_stale_tool_results_before_user_turn(self) -> None:
        provider = MockProviderCapturePreflight()
        context = ContextManager(config=ContextConfig(max_tokens=10000))
        context.set_system_prompt("System prompt")
        context.add_user_message("hello")
        context.add_tool_result("stale-tool-id", "read_file", ToolResult(output="stale"))

        services = create_services_with_permissions()
        session = Session(
            provider=provider,
            context=context,
            registry=None,
            services=services,
        )

        async for _ in session.send("next"):
            pass

        assert provider.captured_messages
        request_messages = provider.captured_messages[-1]
        assert validate_compiled_message_invariants(request_messages) == []
        assert all(
            not (msg.role == Role.TOOL and msg.tool_call_id == "stale-tool-id")
            for msg in request_messages
        )
        assert all(
            not (msg.role == Role.TOOL and msg.tool_call_id == "stale-tool-id")
            for msg in context.messages
        )


class MockProviderDetectConcurrentTurns:
    """Provider that records whether two Session.send() calls overlap."""

    def __init__(self) -> None:
        self.active_calls = 0
        self.overlap_detected = False
        self.inputs: list[str] = []

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        dynamic_context: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        user_text = messages[-1].content
        self.inputs.append(user_text)
        self.active_calls += 1
        if self.active_calls > 1:
            self.overlap_detected = True

        try:
            await asyncio.sleep(0.05)
            yield ContentDelta(text=f"{user_text}-ok")
            yield StreamComplete(
                message=Message(role=Role.ASSISTANT, content=f"{user_text}-ok", tool_calls=())
            )
        finally:
            self.active_calls -= 1


class TestSessionTurnSerialization:
    """Concurrent turn entrypoints should serialize on one session."""

    @pytest.mark.asyncio
    async def test_send_calls_do_not_overlap_on_same_session(self) -> None:
        provider = MockProviderDetectConcurrentTurns()
        session = Session(provider=provider)

        async def collect(prompt: str) -> str:
            chunks: list[str] = []
            async for chunk in session.send(prompt):
                chunks.append(chunk)
            return "".join(chunks)

        first, second = await asyncio.gather(
            asyncio.create_task(collect("first")),
            asyncio.create_task(collect("second")),
        )

        assert first == "first-ok"
        assert second == "second-ok"
        assert provider.inputs == ["first", "second"]
        assert provider.overlap_detected is False

    @pytest.mark.asyncio
    async def test_compact_waits_for_reserved_turn(self) -> None:
        session = Session(provider=MockProviderCapturePreflight())

        started = asyncio.Event()
        finished = asyncio.Event()

        async def fake_compact_locked(force: bool = False) -> None:
            assert force is True
            started.set()
            finished.set()
            return None

        session.compact_locked = fake_compact_locked  # type: ignore[method-assign]

        async with session.reserve_turn():
            task = asyncio.create_task(session.compact(force=True))
            await asyncio.sleep(0)
            assert started.is_set() is False
            assert task.done() is False

        await task
        assert started.is_set() is True
        assert finished.is_set() is True


class _ToolLoopCompactionProvider:
    async def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        dynamic_context: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        yield StreamComplete(
            message=Message(role=Role.ASSISTANT, content="ok", tool_calls=())
        )


class _ToolLoopCompactionSession:
    def __init__(self) -> None:
        self.provider = _ToolLoopCompactionProvider()
        self.context = ContextManager(config=ContextConfig(max_tokens=10000))
        self.context.set_system_prompt("System prompt")
        self.context.add_user_message("hello")
        self._services: ServiceContainer | None = None
        self._config: Any = None
        self.max_tool_iterations = 1
        self._last_iteration_count = 0
        self._last_action_at = None
        self._halted_at_iteration_limit = False
        self.compact_locked_calls = 0
        self._should_compact_calls = 0

    def _should_compact(self) -> bool:
        self._should_compact_calls += 1
        return self._should_compact_calls == 1

    async def compact(self, force: bool = False) -> None:
        raise AssertionError("tool loop should use compact_locked() inside a turn")

    async def compact_locked(self, force: bool = False) -> None:
        assert force is False
        self.compact_locked_calls += 1
        return None

    def _log_provider_preflight(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        dynamic_context: str | None,
        *,
        path: str,
    ) -> None:
        return None

    def _log_event(self, event: Any) -> None:
        return None


class TestToolLoopCompaction:
    @pytest.mark.asyncio
    async def test_in_turn_compaction_uses_compact_locked(self) -> None:
        session = _ToolLoopCompactionSession()

        events = [
            event
            async for event in execute_tool_loop_events(
                session,
                execute_tools_parallel=lambda tool_calls: asyncio.sleep(0),
                execute_single_tool=lambda tool_call: asyncio.sleep(0),
            )
        ]

        assert session.compact_locked_calls == 1
        assert any(event.__class__.__name__ == "SessionCompleted" for event in events)
