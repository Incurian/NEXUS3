"""Event hub for SSE pub/sub.

This module provides per-agent event broadcasting for Server-Sent Events (SSE).
It enables multiple clients to subscribe to an agent's events and receive
real-time updates.

Architecture:
    - Each agent can have multiple subscribers (SSE connections)
    - Events are published to all subscribers of an agent
    - Bounded queues with drop policy for slow clients (backpressure)
    - Cleanup of empty agent keys when last subscriber leaves
    - Sequence numbers for ordering and gap detection
    - Ring buffer for event replay on reconnect

Example:
    event_hub = EventHub()

    # Subscribe to an agent's events
    queue = event_hub.subscribe("worker-1")

    # Publish events
    await event_hub.publish("worker-1", {"type": "turn_started", "request_id": "abc"})

    # Consume events
    event = await queue.get()

    # Unsubscribe
    event_hub.unsubscribe("worker-1", queue)

    # Replay events on reconnect
    events = event_hub.get_events_since("worker-1", last_seen_seq=5)
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SubscriberState:
    """Tracks state for an individual subscriber.

    Attributes:
        queue: The asyncio queue for delivering events.
        consecutive_drops: Count of consecutive dropped events (slow client detection).
    """

    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=lambda: asyncio.Queue())
    consecutive_drops: int = 0


class EventHub:
    """Per-agent pub/sub for SSE events.

    Manages subscriptions for multiple agents, where each agent can have
    multiple subscribers (SSE connections). Events published to an agent
    are broadcast to all active subscribers.

    Thread-safe: Uses asyncio primitives, safe for concurrent access.

    Attributes:
        _subscribers: Map from agent_id to dict of queue -> SubscriberState.
        _max_queue_size: Maximum events per subscriber queue before dropping.
        _seq: Per-agent sequence counter for event ordering.
        _history: Ring buffer per agent for event replay on reconnect.
        _history_size: Maximum events to keep in history per agent.
        _drop_limit: Consecutive drops before disconnecting slow client.
    """

    def __init__(
        self,
        max_queue_size: int = 100,
        history_size: int = 100,
        drop_limit: int = 10,
    ) -> None:
        """Initialize the event hub.

        Args:
            max_queue_size: Maximum events per subscriber queue. When full,
                new events are dropped for slow clients (backpressure).
            history_size: Maximum events to keep in ring buffer per agent.
            drop_limit: Consecutive drops before disconnecting slow client.
        """
        # Map from agent_id -> (queue -> SubscriberState)
        self._subscribers: dict[str, dict[asyncio.Queue[dict[str, Any]], SubscriberState]] = (
            defaultdict(dict)
        )
        self._max_queue_size = max_queue_size

        # Per-agent sequence counter (monotonically increasing)
        self._seq: dict[str, int] = defaultdict(int)

        # Ring buffer per agent for event replay
        self._history: dict[str, deque[dict[str, Any]]] = {}
        self._history_size = history_size

        # Slow client detection
        self._drop_limit = drop_limit

    def subscribe(self, agent_id: str) -> asyncio.Queue[dict[str, Any]]:
        """Create a subscription queue for an agent.

        Creates a bounded queue for receiving events from the specified agent.
        The queue should be consumed by the subscriber (e.g., SSE handler).

        Args:
            agent_id: The agent to subscribe to.

        Returns:
            An asyncio.Queue that will receive events for this agent.
        """
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._max_queue_size)
        state = SubscriberState(queue=queue)
        self._subscribers[agent_id][queue] = state
        return queue

    def unsubscribe(self, agent_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove a subscription and cleanup empty agent keys.

        Safe to call even if the queue was never subscribed or already removed.

        Args:
            agent_id: The agent to unsubscribe from.
            queue: The queue to remove.
        """
        # Use .get() to avoid creating empty keys in defaultdict
        subs = self._subscribers.get(agent_id)
        if subs is None:
            return
        subs.pop(queue, None)
        # Cleanup: remove agent key if no subscribers remain
        if not subs:
            del self._subscribers[agent_id]

    async def publish(self, agent_id: str, event: dict[str, Any]) -> None:
        """Publish event to all subscribers for an agent.

        The event is delivered to all active subscribers' queues. If a
        subscriber's queue is full (slow client), the event is dropped
        for that subscriber. After `drop_limit` consecutive drops, the
        subscriber is automatically disconnected.

        Events are assigned a sequence number and stored in the ring buffer
        for replay on reconnect.

        Args:
            agent_id: The agent to publish to.
            event: The event dict to publish.
        """
        # Increment sequence number for this agent
        self._seq[agent_id] += 1
        seq = self._seq[agent_id]

        # Attach seq to event (make a copy to avoid mutating caller's dict)
        event = dict(event)
        event["seq"] = seq

        # Store in ring buffer for replay
        if agent_id not in self._history:
            self._history[agent_id] = deque(maxlen=self._history_size)
        self._history[agent_id].append(event)

        # Use .get() to avoid creating empty keys in defaultdict
        subs = self._subscribers.get(agent_id)
        if not subs:
            return

        # Deliver to all subscribers, track slow clients
        for queue, state in list(subs.items()):  # Copy to avoid mutation during iteration
            try:
                queue.put_nowait(event)
                state.consecutive_drops = 0  # Reset on success
            except asyncio.QueueFull:
                state.consecutive_drops += 1
                if state.consecutive_drops >= self._drop_limit:
                    # Remove slow subscriber
                    subs.pop(queue, None)

    def is_subscribed(self, agent_id: str, queue: asyncio.Queue[dict[str, Any]]) -> bool:
        """Check if a queue is still subscribed to an agent.

        Used by SSE handlers to detect when they've been removed as a slow client.
        When EventHub removes a slow subscriber, the SSE handler should close.

        Args:
            agent_id: The agent to check.
            queue: The queue to check.

        Returns:
            True if the queue is still subscribed to this agent.
        """
        subs = self._subscribers.get(agent_id)
        return subs is not None and queue in subs

    def has_subscribers(self, agent_id: str) -> bool:
        """Check if agent has any active subscribers.

        Args:
            agent_id: The agent to check.

        Returns:
            True if the agent has at least one subscriber.
        """
        return bool(self._subscribers.get(agent_id))

    def subscriber_count(self, agent_id: str) -> int:
        """Count subscribers for an agent.

        Args:
            agent_id: The agent to count subscribers for.

        Returns:
            Number of active subscribers for this agent.
        """
        subs = self._subscribers.get(agent_id)
        return len(subs) if subs else 0

    def total_subscriber_count(self) -> int:
        """Count total subscribers across all agents.

        Useful for idle timeout logic - server shouldn't shut down
        while there are active SSE connections.

        Returns:
            Total number of active subscribers across all agents.
        """
        return sum(len(subs) for subs in self._subscribers.values())

    def get_events_since(self, agent_id: str, since_seq: int) -> list[dict[str, Any]]:
        """Get events from ring buffer since a sequence number.

        Used for replay on reconnect - clients can request all events
        after their last seen sequence number.

        Args:
            agent_id: The agent to get events for.
            since_seq: Return events with seq > since_seq.

        Returns:
            List of events with sequence numbers greater than since_seq,
            in order. Empty list if no events match or agent has no history.
        """
        history = self._history.get(agent_id)
        if not history:
            return []
        return [ev for ev in history if ev.get("seq", 0) > since_seq]

    def latest_seq(self, agent_id: str) -> int:
        """Get the latest sequence number for an agent.

        Useful for clients to know the current sequence before subscribing,
        so they can detect gaps.

        Args:
            agent_id: The agent to check.

        Returns:
            The latest sequence number, or 0 if no events have been published.
        """
        return self._seq.get(agent_id, 0)
