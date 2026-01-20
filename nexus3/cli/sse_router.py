"""SSE event routing for multi-client sync.

This module provides the EventRouter class that routes events from a single
long-lived SSE stream into per-request queues, enabling multiple concurrent
turns to receive their respective events without missing early events.

Usage:
    router = EventRouter()
    pump_task = asyncio.create_task(router.pump(client.iter_events()))

    # Subscribe BEFORE calling send() to avoid missing early events
    q = await router.subscribe(request_id)
    send_task = asyncio.create_task(client.send(message, request_id=request_id))

    # Consume events until terminal event
    async for event in consume_queue(q):
        if event["type"] in TERMINAL_EVENTS:
            break
        # Handle event...

    await router.unsubscribe(request_id, q)

    # Cleanup
    pump_task.cancel()
    await pump_task
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, AsyncIterator


# Events that indicate the end of a turn
TERMINAL_EVENTS: frozenset[str] = frozenset({"turn_completed", "turn_cancelled"})


class EventRouter:
    """Route events from ONE long-lived SSE stream into per-request queues.

    This class solves the race condition where per-turn SSE subscriptions
    risk missing early events. Instead, one long-lived stream feeds all
    request-specific queues, and clients subscribe before sending requests.

    Features:
        - Thread-safe with asyncio.Lock
        - Bounded queues with drop-on-full backpressure
        - Graceful close that wakes all subscribers with stream_error
        - Ignores events without request_id (e.g., pings)

    Attributes:
        max_queue_size: Maximum events per subscriber queue before dropping.
    """

    def __init__(self, *, max_queue_size: int = 2000) -> None:
        """Initialize the EventRouter.

        Args:
            max_queue_size: Maximum size for subscriber queues. Events are
                dropped silently when a queue is full (backpressure).
        """
        self._subs: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._max_queue_size = max_queue_size
        self._closed = False
        self._close_exc: Exception | None = None
        self._lock = asyncio.Lock()
        # Global queue for background watchers (receives ALL events including pings)
        self._global_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=max_queue_size
        )

    @property
    def is_closed(self) -> bool:
        """Return True if the router has been closed."""
        return self._closed

    @property
    def global_queue(self) -> asyncio.Queue[dict[str, Any]]:
        """Get the global event queue for background watching.

        This queue receives ALL events (including pings) for background
        watchers to observe other clients' activity.
        """
        return self._global_queue

    async def subscribe(self, request_id: str) -> asyncio.Queue[dict[str, Any]]:
        """Subscribe to events for a specific request_id.

        Call this BEFORE sending the request to avoid missing early events.

        Args:
            request_id: The request identifier to subscribe to.

        Returns:
            A bounded asyncio.Queue that will receive events for this request_id.

        Raises:
            ValueError: If request_id is empty or None.

        Note:
            If the router is already closed, the returned queue will immediately
            contain a stream_error event.
        """
        if not request_id:
            raise ValueError("request_id is required")

        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._max_queue_size)
        async with self._lock:
            if self._closed:
                q.put_nowait(
                    {"type": "stream_error", "error": str(self._close_exc or "closed")}
                )
                return q
            self._subs[request_id].add(q)
        return q

    async def unsubscribe(
        self, request_id: str, q: asyncio.Queue[dict[str, Any]]
    ) -> None:
        """Unsubscribe a queue from a request_id.

        Safe to call multiple times or with an already-removed queue.

        Args:
            request_id: The request identifier to unsubscribe from.
            q: The queue to remove from the subscription set.
        """
        async with self._lock:
            subs = self._subs.get(request_id)
            if not subs:
                return
            subs.discard(q)
            if not subs:
                self._subs.pop(request_id, None)

    async def publish(self, event: dict[str, Any]) -> None:
        """Publish one event to subscribers.

        Called internally by pump(). Events without a request_id are routed
        only to the global queue (e.g., ping events).

        Args:
            event: The event dict to publish. Events with a "request_id" field
                are routed to both request-specific subscribers and the global queue.

        Note:
            Events are dropped silently if subscriber queues are full
            (backpressure mechanism).
        """
        # Always publish to global queue for background watchers
        try:
            self._global_queue.put_nowait(event)
        except asyncio.QueueFull:
            pass  # Drop for slow consumer

        rid = event.get("request_id")
        if not rid:
            return  # No request-specific routing for pings etc.

        async with self._lock:
            queues = list(self._subs.get(rid, ()))
        if not queues:
            return

        for q in queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # Drop for slow consumer (backpressure)

    async def close(self, exc: Exception | None = None) -> None:
        """Close the router and wake any subscribers with a stream_error event.

        After close(), new subscriptions immediately receive a stream_error.
        Safe to call multiple times.

        Args:
            exc: Optional exception that caused the close. This is included
                in the stream_error event sent to subscribers.
        """
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            self._close_exc = exc
            subs_snapshot = {rid: list(qs) for rid, qs in self._subs.items()}
            self._subs.clear()

        wake = {"type": "stream_error", "error": str(exc or "SSE stream closed")}
        for qs in subs_snapshot.values():
            for q in qs:
                try:
                    q.put_nowait(wake)
                except asyncio.QueueFull:
                    pass

    async def pump(self, events: AsyncIterator[dict[str, Any]]) -> None:
        """Consume events from an async iterator and route them to subscribers.

        This should be run as a background task. It will run until the
        iterator is exhausted or an exception occurs.

        Args:
            events: An async iterator yielding event dicts (e.g., from
                NexusClient.iter_events()).

        Raises:
            asyncio.CancelledError: If the task is cancelled.
            Exception: Any exception from the event iterator is re-raised
                after closing the router.

        Example:
            pump_task = asyncio.create_task(router.pump(client.iter_events()))
            # ... use router ...
            pump_task.cancel()
            try:
                await pump_task
            except asyncio.CancelledError:
                pass
        """
        try:
            async for ev in events:
                await self.publish(ev)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self.close(e)
            raise
        else:
            await self.close(None)
