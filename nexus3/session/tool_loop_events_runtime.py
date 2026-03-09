"""Tool-loop event runtime helpers extracted from Session."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from nexus3.context.compaction import CompactionResult
from nexus3.context.git_context import should_refresh_git_context
from nexus3.core.interfaces import AsyncProvider
from nexus3.core.types import (
    ContentDelta,
    Message,
    ReasoningDelta,
    StreamComplete,
    ToolCall,
    ToolCallStarted,
    ToolResult,
)
from nexus3.session.events import (
    ContentChunk,
    IterationCompleted,
    ReasoningEnded,
    ReasoningStarted,
    SessionCancelled,
    SessionCompleted,
    SessionEvent,
    ToolBatchCompleted,
    ToolBatchHalted,
    ToolBatchStarted,
    ToolCompleted,
    ToolDetected,
    ToolStarted,
)

if TYPE_CHECKING:
    from nexus3.config.schema import Config
    from nexus3.context.manager import ContextManager
    from nexus3.core.cancel import CancellationToken
    from nexus3.skill.services import ServiceContainer


class _ToolLoopEventsSession(Protocol):
    provider: AsyncProvider
    context: ContextManager | None
    _services: ServiceContainer | None
    _config: Config | None
    max_tool_iterations: int
    _last_iteration_count: int
    _last_action_at: datetime | None
    _halted_at_iteration_limit: bool

    def _should_compact(self) -> bool: ...

    def compact(self, force: bool = False) -> Awaitable[CompactionResult | None]: ...

    def _log_provider_preflight(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        dynamic_context: str | None,
        *,
        path: str,
    ) -> None: ...

    def _log_event(self, event: SessionEvent) -> None: ...

    def _execute_tools_parallel(
        self,
        tool_calls: tuple[ToolCall, ...],
    ) -> Awaitable[list[ToolResult]]: ...

    def _execute_single_tool(
        self,
        tool_call: ToolCall,
    ) -> Awaitable[ToolResult]: ...


async def execute_tool_loop_events(
    session: _ToolLoopEventsSession,
    *,
    cancel_token: CancellationToken | None = None,
) -> AsyncIterator[SessionEvent]:
    """Execute tools yielding SessionEvent objects."""
    consecutive_empty = 0
    for iteration_num in range(session.max_tool_iterations):
        session._last_iteration_count = iteration_num + 1

        # Check for compaction BEFORE build_messages() to avoid truncation
        if session._should_compact():
            compact_result = await session.compact(force=False)
            if compact_result:
                saved = compact_result.original_token_count - compact_result.new_token_count
                yield ContentChunk(
                    text=f"\n[Context compacted: {saved:,} tokens reclaimed]\n\n"
                )

        # Type narrowing: run_turn() requires context, so it's guaranteed here
        assert session.context is not None
        messages = session.context.build_messages()
        tools = session.context.get_tool_definitions()
        dynamic_context = session.context.build_dynamic_context()

        # Stream response, accumulating content and detecting tool calls
        final_message: Message | None = None
        is_reasoning = False
        show_reasoning = False
        runtime_model = session._services.get_model() if session._services else None
        if runtime_model is not None:
            show_reasoning = runtime_model.reasoning
        elif session._config:
            default_model = session._config.resolve_model()
            show_reasoning = default_model.reasoning

        session._log_provider_preflight(
            messages, tools, dynamic_context, path="run_turn.tools.iteration",
        )
        async for event in session.provider.stream(
            messages, tools, dynamic_context=dynamic_context,
        ):
            if cancel_token and cancel_token.is_cancelled:
                yield SessionCancelled()
                return
            if isinstance(event, ReasoningDelta):
                if show_reasoning and not is_reasoning:
                    yield ReasoningStarted()
                is_reasoning = True
            elif isinstance(event, ContentDelta):
                if show_reasoning and is_reasoning:
                    yield ReasoningEnded()
                is_reasoning = False
                yield ContentChunk(text=event.text)
                if cancel_token and cancel_token.is_cancelled:
                    yield SessionCancelled()
                    return
            elif isinstance(event, ToolCallStarted):
                if show_reasoning and is_reasoning:
                    yield ReasoningEnded()
                is_reasoning = False
                yield ToolDetected(name=event.name, tool_id=event.id)
            elif isinstance(event, StreamComplete):
                if show_reasoning and is_reasoning:
                    yield ReasoningEnded()
                is_reasoning = False
                final_message = event.message

        if cancel_token and cancel_token.is_cancelled:
            yield SessionCancelled()
            return

        if final_message is None:
            yield SessionCompleted(halted_at_limit=False)
            return

        # Check cancellation before adding assistant message with tool_calls
        # This prevents orphaned tool_use blocks if cancelled during streaming
        if cancel_token and cancel_token.is_cancelled:
            yield SessionCancelled()
            return

        if final_message.tool_calls:
            consecutive_empty = 0
            # Add assistant message with tool calls
            session.context.add_assistant_message(
                final_message.content, list(final_message.tool_calls)
            )

            # Check if parallel execution requested
            parallel = any(
                tc.arguments.get("_parallel", False)
                for tc in final_message.tool_calls
            )

            # Yield batch start event with parallel flag
            batch_start = ToolBatchStarted(
                tool_calls=final_message.tool_calls, parallel=parallel
            )
            session._log_event(batch_start)
            yield batch_start

            if parallel:
                if cancel_token and cancel_token.is_cancelled:
                    yield SessionCancelled()
                    return
                # Parallel execution - all tools active at once
                for tc in final_message.tool_calls:
                    tool_start = ToolStarted(name=tc.name, tool_id=tc.id)
                    session._log_event(tool_start)
                    yield tool_start
                tool_results = await session._execute_tools_parallel(final_message.tool_calls)
                for i, (tc, tool_result) in enumerate(
                    zip(final_message.tool_calls, tool_results, strict=True), start=1
                ):
                    session.context.add_tool_result(
                        tc.id, tc.name, tool_result,
                        call_index=i, arguments=tc.arguments,
                    )
                    tool_complete = ToolCompleted(
                        name=tc.name,
                        tool_id=tc.id,
                        success=tool_result.success,
                        error=tool_result.error,
                        output=tool_result.output if tool_result.success else "",
                    )
                    session._log_event(tool_complete)
                    yield tool_complete
            else:
                # Sequential execution - halts on first error or cancellation
                error_index = -1
                cancel_index = -1
                for i, tc in enumerate(final_message.tool_calls):
                    # Check cancellation before starting each tool
                    if cancel_token and cancel_token.is_cancelled:
                        cancel_index = i
                        break
                    tool_start = ToolStarted(name=tc.name, tool_id=tc.id)
                    session._log_event(tool_start)
                    yield tool_start
                    # Handle mid-execution cancellation
                    try:
                        tool_result = await session._execute_single_tool(tc)
                    except asyncio.CancelledError:
                        # Tool was interrupted mid-execution
                        tool_result = ToolResult(
                            error="Cancelled by user: tool execution was interrupted"
                        )
                    session.context.add_tool_result(
                        tc.id, tc.name, tool_result,
                        call_index=i + 1, arguments=tc.arguments,
                    )
                    tool_complete = ToolCompleted(
                        name=tc.name,
                        tool_id=tc.id,
                        success=tool_result.success,
                        error=tool_result.error,
                        output=tool_result.output if tool_result.success else "",
                    )
                    session._log_event(tool_complete)
                    yield tool_complete
                    # Check cancellation after tool completes (for next iteration)
                    if cancel_token and cancel_token.is_cancelled:
                        cancel_index = i + 1  # This tool finished, cancel starts after
                        break
                    if not tool_result.success:
                        error_index = i
                        batch_halted = ToolBatchHalted()
                        session._log_event(batch_halted)
                        yield batch_halted
                        break

                # Add cancelled results for remaining tools (ensures Anthropic
                # API gets matching tool_result for every tool_use block)
                if cancel_index >= 0:
                    for j, tc in enumerate(
                        final_message.tool_calls[cancel_index:],
                        start=cancel_index,
                    ):
                        cancelled_result = ToolResult(
                            error="Cancelled by user: tool execution was interrupted"
                        )
                        session.context.add_tool_result(
                            tc.id, tc.name, cancelled_result,
                            call_index=j + 1, arguments=tc.arguments,
                        )
                    yield SessionCancelled()
                    return

                # Add halted results for remaining tools
                if error_index >= 0:
                    for tc in final_message.tool_calls[error_index + 1:]:
                        halted_result = ToolResult(
                            error="Did not execute: halted due to error in previous tool"
                        )
                        session.context.add_tool_result(tc.id, tc.name, halted_result)

            # Yield batch complete and iteration complete
            batch_complete = ToolBatchCompleted()
            session._log_event(batch_complete)
            yield batch_complete

            # Refresh git context if any tool in batch could change git state
            if session.context and any(
                should_refresh_git_context(tc.name)
                for tc in final_message.tool_calls
            ):
                cwd = session._services.get_cwd() if session._services else Path.cwd()
                session.context.refresh_git_context(cwd)

            yield IterationCompleted(
                iteration=iteration_num + 1,
                will_continue=True,
            )

            # Update last action timestamp
            session._last_action_at = datetime.now()
        else:
            # No tool calls - this is the final response
            if not final_message.content:
                # Empty response — don't save, warn user
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    yield ContentChunk(
                        text="[Stopping: provider returned multiple empty responses in a row]"
                    )
                    yield SessionCompleted(halted_at_limit=False)
                    return
                yield ContentChunk(text="[Provider returned an empty response]")
                continue

            consecutive_empty = 0
            session.context.add_assistant_message(final_message.content)
            session._last_action_at = datetime.now()

            # Check for auto-compaction after response
            if session._should_compact():
                compact_result = await session.compact(force=False)
                if compact_result:
                    saved = compact_result.original_token_count - compact_result.new_token_count
                    yield ContentChunk(
                        text=f"\n\n[Context compacted: {saved:,} tokens reclaimed]"
                    )

            yield SessionCompleted(halted_at_limit=False)
            return

    # Max iterations reached
    session._halted_at_iteration_limit = True
    yield ContentChunk(text="[Max tool iterations reached]")
    yield SessionCompleted(halted_at_limit=True)
