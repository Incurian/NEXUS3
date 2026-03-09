"""Simple non-tool turn runtime helpers extracted from Session."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any, Protocol

from nexus3.core.types import ContentDelta, Message, StreamComplete, ToolCallStarted
from nexus3.session.events import (
    ContentChunk,
    SessionCancelled,
    SessionCompleted,
    SessionEvent,
    ToolDetected,
)

if TYPE_CHECKING:
    from nexus3.context.manager import ContextManager
    from nexus3.core.cancel import CancellationToken
    from nexus3.core.interfaces import AsyncProvider
    from nexus3.session.logging import SessionLogger


ToolCallCallback = Callable[[str, str], None]


class _SimpleTurnSession(Protocol):
    provider: AsyncProvider
    context: ContextManager | None
    logger: SessionLogger | None
    on_tool_call: ToolCallCallback | None

    def _log_provider_preflight(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        dynamic_context: str | None,
        *,
        path: str,
    ) -> None: ...


async def execute_simple_send(
    session: _SimpleTurnSession,
    *,
    messages: list[Message],
    tools: list[dict[str, Any]] | None,
    dynamic_context: str | None,
    preflight_path: str,
    cancel_token: CancellationToken | None = None,
) -> AsyncIterator[str]:
    """Stream a simple non-tool response for Session.send()."""
    final_message: Message | None = None

    session._log_provider_preflight(
        messages,
        tools,
        dynamic_context,
        path=preflight_path,
    )
    async for event in session.provider.stream(
        messages,
        tools,
        dynamic_context=dynamic_context,
    ):
        if cancel_token and cancel_token.is_cancelled:
            return
        if isinstance(event, ContentDelta):
            yield event.text
            if cancel_token and cancel_token.is_cancelled:
                return
        elif isinstance(event, ToolCallStarted):
            # Notify callback if set (for display updates)
            if session.on_tool_call:
                session.on_tool_call(event.name, event.id)
        elif isinstance(event, StreamComplete):
            final_message = event.message

    # If cancellation arrived mid-stream before StreamComplete,
    # exit quietly instead of treating as empty provider output.
    if cancel_token and cancel_token.is_cancelled:
        return

    # Log/store assistant response
    if final_message:
        if not final_message.content and not final_message.tool_calls:
            yield "[Provider returned an empty response]"
        elif session.context:
            session.context.add_assistant_message(
                final_message.content,
                list(final_message.tool_calls),
            )
        elif session.logger:
            session.logger.log_assistant(final_message.content)


async def execute_simple_run_turn(
    session: _SimpleTurnSession,
    *,
    messages: list[Message],
    tools: list[dict[str, Any]] | None,
    dynamic_context: str | None,
    preflight_path: str,
    cancel_token: CancellationToken | None = None,
) -> AsyncIterator[SessionEvent]:
    """Stream a simple non-tool response for Session.run_turn()."""
    context = session.context
    if context is None:
        raise RuntimeError("execute_simple_run_turn() requires context mode")

    final_message: Message | None = None
    session._log_provider_preflight(
        messages,
        tools,
        dynamic_context,
        path=preflight_path,
    )
    async for stream_event in session.provider.stream(
        messages,
        tools,
        dynamic_context=dynamic_context,
    ):
        if cancel_token and cancel_token.is_cancelled:
            yield SessionCancelled()
            return
        if isinstance(stream_event, ContentDelta):
            yield ContentChunk(text=stream_event.text)
            if cancel_token and cancel_token.is_cancelled:
                yield SessionCancelled()
                return
        elif isinstance(stream_event, ToolCallStarted):
            yield ToolDetected(name=stream_event.name, tool_id=stream_event.id)
        elif isinstance(stream_event, StreamComplete):
            final_message = stream_event.message

    if cancel_token and cancel_token.is_cancelled:
        yield SessionCancelled()
        return

    # Store assistant response
    if final_message:
        if not final_message.content and not final_message.tool_calls:
            yield ContentChunk(text="[Provider returned an empty response]")
        else:
            context.add_assistant_message(
                final_message.content,
                list(final_message.tool_calls),
            )

    yield SessionCompleted(halted_at_limit=False)
