"""Event hub for SSE pub/sub.

This module provides per-agent event broadcasting for Server-Sent Events (SSE).
It enables multiple clients to subscribe to an agent's events and receive
real-time updates.

Architecture:
    - Each agent can have multiple subscribers (SSE connections)
    - Events are published to all subscribers of an agent
    - Bounded queues with drop policy for slow clients (backpressure)
    - Cleanup of empty agent keys when last subscriber leaves

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
"""

from __future__ import annotations

import asyncio
from collections import defaultdict


class EventHub:
    """Per-agent pub/sub for SSE events.

    Manages subscriptions for multiple agents, where each agent can have
    multiple subscribers (SSE connections). Events published to an agent
    are broadcast to all active subscribers.

    Thread-safe: Uses asyncio primitives, safe for concurrent access.

    Attributes:
        _subscribers: Map from agent_id to set of subscriber queues.
        _max_queue_size: Maximum events per subscriber queue before dropping.
    """

    def __init__(self, max_queue_size: int = 100) -> None:
        """Initialize the event hub.

        Args:
            max_queue_size: Maximum events per subscriber queue. When full,
                new events are dropped for slow clients (backpressure).
        """
        self._subscribers: dict[str, set[asyncio.Queue[dict]]] = defaultdict(set)
        self._max_queue_size = max_queue_size

    def subscribe(self, agent_id: str) -> asyncio.Queue[dict]:
        """Create a subscription queue for an agent.

        Creates a bounded queue for receiving events from the specified agent.
        The queue should be consumed by the subscriber (e.g., SSE handler).

        Args:
            agent_id: The agent to subscribe to.

        Returns:
            An asyncio.Queue that will receive events for this agent.
        """
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=self._max_queue_size)
        self._subscribers[agent_id].add(queue)
        return queue

    def unsubscribe(self, agent_id: str, queue: asyncio.Queue[dict]) -> None:
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
        subs.discard(queue)
        # Cleanup: remove agent key if no subscribers remain
        if not subs:
            del self._subscribers[agent_id]

    async def publish(self, agent_id: str, event: dict) -> None:
        """Publish event to all subscribers for an agent.

        The event is delivered to all active subscribers' queues. If a
        subscriber's queue is full (slow client), the event is dropped
        for that subscriber only (backpressure).

        Args:
            agent_id: The agent to publish to.
            event: The event dict to publish.
        """
        # Use .get() to avoid creating empty keys in defaultdict
        subs = self._subscribers.get(agent_id)
        if not subs:
            return
        for queue in list(subs):  # Copy to avoid mutation during iteration
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop event for slow clients (backpressure)
                pass

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
