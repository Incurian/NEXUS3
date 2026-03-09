"""Streaming runtime helpers extracted from Session."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING

from nexus3.core.types import ToolCall
from nexus3.session.events import (
    ContentChunk,
    ReasoningEnded,
    ReasoningStarted,
    SessionEvent,
    ToolBatchCompleted,
    ToolBatchHalted,
    ToolBatchStarted,
    ToolCompleted,
    ToolDetected,
    ToolStarted,
)

if TYPE_CHECKING:
    from nexus3.core.cancel import CancellationToken


ToolCallCallback = Callable[[str, str], None]
ToolCompleteCallback = Callable[[str, str, bool], None]
ReasoningCallback = Callable[[bool], None]
BatchStartCallback = Callable[[tuple[ToolCall, ...]], None]
ToolActiveCallback = Callable[[str, str], None]
BatchProgressCallback = Callable[[str, str, bool, str, str], None]
BatchHaltCallback = Callable[[], None]
BatchCompleteCallback = Callable[[], None]
ExecuteToolLoopEvents = Callable[
    ["CancellationToken | None"],
    AsyncIterator[SessionEvent],
]


def _dispatch_streaming_event(
    event: SessionEvent,
    *,
    on_tool_call: ToolCallCallback | None,
    on_tool_complete: ToolCompleteCallback | None,
    on_reasoning: ReasoningCallback | None,
    on_batch_start: BatchStartCallback | None,
    on_tool_active: ToolActiveCallback | None,
    on_batch_progress: BatchProgressCallback | None,
    on_batch_halt: BatchHaltCallback | None,
    on_batch_complete: BatchCompleteCallback | None,
) -> str | None:
    """Map a Session event to callbacks and/or a streaming content chunk."""
    if isinstance(event, ContentChunk):
        return event.text
    if isinstance(event, ReasoningStarted):
        if on_reasoning:
            on_reasoning(True)
        return None
    if isinstance(event, ReasoningEnded):
        if on_reasoning:
            on_reasoning(False)
        return None
    if isinstance(event, ToolDetected):
        if on_tool_call:
            on_tool_call(event.name, event.tool_id)
        return None
    if isinstance(event, ToolBatchStarted):
        if on_batch_start:
            on_batch_start(event.tool_calls)
        return None
    if isinstance(event, ToolStarted):
        if on_tool_active:
            on_tool_active(event.name, event.tool_id)
        return None
    if isinstance(event, ToolCompleted):
        if on_batch_progress:
            on_batch_progress(
                event.name,
                event.tool_id,
                event.success,
                event.error,
                event.output,
            )
        # Legacy callback (deprecated)
        if on_tool_complete:
            on_tool_complete(event.name, event.tool_id, event.success)
        return None
    if isinstance(event, ToolBatchHalted):
        if on_batch_halt:
            on_batch_halt()
        return None
    if isinstance(event, ToolBatchCompleted):
        if on_batch_complete:
            on_batch_complete()
        return None
    # IterationCompleted, SessionCompleted, and SessionCancelled are internal
    # events and do not map to callbacks in the legacy streaming interface.
    return None


async def execute_tool_loop_streaming(
    *,
    execute_tool_loop_events: ExecuteToolLoopEvents,
    cancel_token: CancellationToken | None = None,
    on_tool_call: ToolCallCallback | None = None,
    on_tool_complete: ToolCompleteCallback | None = None,
    on_reasoning: ReasoningCallback | None = None,
    on_batch_start: BatchStartCallback | None = None,
    on_tool_active: ToolActiveCallback | None = None,
    on_batch_progress: BatchProgressCallback | None = None,
    on_batch_halt: BatchHaltCallback | None = None,
    on_batch_complete: BatchCompleteCallback | None = None,
) -> AsyncIterator[str]:
    """Execute tool-loop events and adapt them to legacy streaming callbacks."""
    async for event in execute_tool_loop_events(cancel_token):
        chunk = _dispatch_streaming_event(
            event,
            on_tool_call=on_tool_call,
            on_tool_complete=on_tool_complete,
            on_reasoning=on_reasoning,
            on_batch_start=on_batch_start,
            on_tool_active=on_tool_active,
            on_batch_progress=on_batch_progress,
            on_batch_halt=on_batch_halt,
            on_batch_complete=on_batch_complete,
        )
        if chunk is not None:
            yield chunk
