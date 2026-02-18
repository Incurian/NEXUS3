"""Log multiplexer for multi-agent raw log routing.

This module provides a contextvars-based log multiplexer that routes raw API
log callbacks to the correct agent's logger based on the current async context.

The Problem:
    Multiple agents share a single provider instance, but each agent has its own
    SessionLogger. Without multiplexing, the provider's raw log callback points
    to whichever agent was created last, causing log entries to be misattributed.

The Solution:
    Use Python's contextvars to track which agent's callback should receive logs.
    Each async task (request) sets its agent's callback in the context, and the
    multiplexer forwards to the correct callback.

Usage:
    # In SharedComponents initialization:
    multiplexer = LogMultiplexer()
    provider.set_raw_log_callback(multiplexer)

    # When creating an agent:
    callback = logger.get_raw_log_callback()
    multiplexer.register(agent_id, callback)

    # In dispatcher, wrap request handling:
    async with multiplexer.agent_context(agent_id):
        await session.send(content)
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nexus3.core.interfaces import RawLogCallback

# Context variable tracking the current agent's ID for log routing
_current_agent_id: ContextVar[str | None] = ContextVar(
    "nexus3_current_agent_id",
    default=None,
)


class LogMultiplexer:
    """Routes raw log callbacks to the correct agent based on async context.

    This class implements the RawLogCallback protocol and forwards calls to
    the appropriate agent's callback based on the contextvars-tracked agent ID.

    Thread Safety:
        This class is safe for concurrent use in asyncio. Each async task has
        its own context, so _current_agent_id is isolated per-task.

    Attributes:
        _callbacks: Mapping of agent_id to their RawLogCallback.
    """

    def __init__(self) -> None:
        """Initialize the multiplexer with empty callback registry."""
        self._callbacks: dict[str, RawLogCallback] = {}

    def register(self, agent_id: str, callback: RawLogCallback) -> None:
        """Register an agent's callback.

        Args:
            agent_id: The agent's unique identifier.
            callback: The agent's RawLogCallback (typically RawLogCallbackAdapter).
        """
        self._callbacks[agent_id] = callback

    def unregister(self, agent_id: str) -> None:
        """Unregister an agent's callback.

        Args:
            agent_id: The agent's unique identifier to remove.
        """
        self._callbacks.pop(agent_id, None)

    @contextmanager
    def agent_context(self, agent_id: str):
        """Context manager to set the current agent for log routing.

        Use this to wrap code that makes provider calls so logs are routed
        to the correct agent's logger.

        Args:
            agent_id: The agent ID to route logs to.

        Yields:
            None. The context is set for the duration of the with block.

        Example:
            with multiplexer.agent_context("worker-1"):
                await session.send(content)  # Logs go to worker-1's logger
        """
        token = _current_agent_id.set(agent_id)
        try:
            yield
        finally:
            _current_agent_id.reset(token)

    def _get_current_callback(self) -> RawLogCallback | None:
        """Get the callback for the current async context.

        Returns:
            The RawLogCallback for the current agent, or None if no agent
            is set in the context or the agent has no registered callback.
        """
        agent_id = _current_agent_id.get()
        if agent_id is None:
            return None
        return self._callbacks.get(agent_id)

    # RawLogCallback protocol implementation

    def on_request(self, endpoint: str, payload: dict[str, Any]) -> None:
        """Forward request log to current agent's callback.

        Args:
            endpoint: The API endpoint URL.
            payload: The request body.
        """
        callback = self._get_current_callback()
        if callback is not None:
            callback.on_request(endpoint, payload)

    def on_response(self, status: int, body: dict[str, Any]) -> None:
        """Forward response log to current agent's callback.

        Args:
            status: The HTTP status code.
            body: The response body.
        """
        callback = self._get_current_callback()
        if callback is not None:
            callback.on_response(status, body)

    def on_chunk(self, chunk: dict[str, Any]) -> None:
        """Forward chunk log to current agent's callback.

        Args:
            chunk: The parsed SSE chunk.
        """
        callback = self._get_current_callback()
        if callback is not None:
            callback.on_chunk(chunk)

    def on_stream_complete(self, summary: dict[str, Any]) -> None:
        """Forward stream completion summary to current agent's callback.

        Args:
            summary: Stream summary dict.
        """
        callback = self._get_current_callback()
        if callback is not None:
            callback.on_stream_complete(summary)
