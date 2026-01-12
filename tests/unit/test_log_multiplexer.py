"""Tests for LogMultiplexer contextvars-based log routing."""

import asyncio
from unittest.mock import MagicMock

import pytest

from nexus3.rpc.log_multiplexer import LogMultiplexer


class TestLogMultiplexerBasics:
    """Test basic LogMultiplexer functionality."""

    def test_register_adds_callback(self):
        """Test that register adds a callback."""
        multiplexer = LogMultiplexer()
        callback = MagicMock()

        multiplexer.register("agent-1", callback)

        assert "agent-1" in multiplexer._callbacks
        assert multiplexer._callbacks["agent-1"] is callback

    def test_unregister_removes_callback(self):
        """Test that unregister removes a callback."""
        multiplexer = LogMultiplexer()
        callback = MagicMock()

        multiplexer.register("agent-1", callback)
        multiplexer.unregister("agent-1")

        assert "agent-1" not in multiplexer._callbacks

    def test_unregister_nonexistent_is_safe(self):
        """Test that unregistering a non-existent agent doesn't raise."""
        multiplexer = LogMultiplexer()

        # Should not raise
        multiplexer.unregister("nonexistent")

    def test_register_overwrites_existing(self):
        """Test that registering same agent_id overwrites."""
        multiplexer = LogMultiplexer()
        callback1 = MagicMock()
        callback2 = MagicMock()

        multiplexer.register("agent-1", callback1)
        multiplexer.register("agent-1", callback2)

        assert multiplexer._callbacks["agent-1"] is callback2


class TestLogMultiplexerContext:
    """Test agent_context routing."""

    def test_on_request_without_context_does_nothing(self):
        """Test that on_request does nothing without agent context."""
        multiplexer = LogMultiplexer()
        callback = MagicMock()
        multiplexer.register("agent-1", callback)

        # No context set
        multiplexer.on_request("/api/chat", {"model": "test"})

        callback.on_request.assert_not_called()

    def test_on_request_with_context_forwards(self):
        """Test that on_request forwards to correct callback."""
        multiplexer = LogMultiplexer()
        callback = MagicMock()
        multiplexer.register("agent-1", callback)

        with multiplexer.agent_context("agent-1"):
            multiplexer.on_request("/api/chat", {"model": "test"})

        callback.on_request.assert_called_once_with("/api/chat", {"model": "test"})

    def test_on_response_with_context_forwards(self):
        """Test that on_response forwards to correct callback."""
        multiplexer = LogMultiplexer()
        callback = MagicMock()
        multiplexer.register("agent-1", callback)

        with multiplexer.agent_context("agent-1"):
            multiplexer.on_response(200, {"result": "ok"})

        callback.on_response.assert_called_once_with(200, {"result": "ok"})

    def test_on_chunk_with_context_forwards(self):
        """Test that on_chunk forwards to correct callback."""
        multiplexer = LogMultiplexer()
        callback = MagicMock()
        multiplexer.register("agent-1", callback)

        with multiplexer.agent_context("agent-1"):
            multiplexer.on_chunk({"delta": "hello"})

        callback.on_chunk.assert_called_once_with({"delta": "hello"})

    def test_context_routes_to_correct_agent(self):
        """Test that context routes to the correct agent's callback."""
        multiplexer = LogMultiplexer()
        callback1 = MagicMock()
        callback2 = MagicMock()
        multiplexer.register("agent-1", callback1)
        multiplexer.register("agent-2", callback2)

        with multiplexer.agent_context("agent-1"):
            multiplexer.on_request("/api", {})

        callback1.on_request.assert_called_once()
        callback2.on_request.assert_not_called()

    def test_context_restores_after_exit(self):
        """Test that context is restored after exiting context manager."""
        multiplexer = LogMultiplexer()
        callback = MagicMock()
        multiplexer.register("agent-1", callback)

        with multiplexer.agent_context("agent-1"):
            pass

        # Outside context, should not forward
        multiplexer.on_request("/api", {})
        callback.on_request.assert_not_called()

    def test_nested_contexts(self):
        """Test that nested contexts work correctly."""
        multiplexer = LogMultiplexer()
        callback1 = MagicMock()
        callback2 = MagicMock()
        multiplexer.register("agent-1", callback1)
        multiplexer.register("agent-2", callback2)

        with multiplexer.agent_context("agent-1"):
            multiplexer.on_request("/outer", {})

            with multiplexer.agent_context("agent-2"):
                multiplexer.on_request("/inner", {})

            multiplexer.on_request("/outer-after", {})

        callback1.on_request.assert_any_call("/outer", {})
        callback1.on_request.assert_any_call("/outer-after", {})
        callback2.on_request.assert_called_once_with("/inner", {})

    def test_context_with_unregistered_agent(self):
        """Test that context with unregistered agent doesn't raise."""
        multiplexer = LogMultiplexer()
        callback = MagicMock()
        multiplexer.register("agent-1", callback)

        # agent-2 is not registered
        with multiplexer.agent_context("agent-2"):
            multiplexer.on_request("/api", {})

        # Should not raise, just silently skip
        callback.on_request.assert_not_called()


class TestLogMultiplexerAsync:
    """Test LogMultiplexer with async tasks."""

    @pytest.mark.asyncio
    async def test_async_context_isolation(self):
        """Test that async tasks have isolated contexts."""
        multiplexer = LogMultiplexer()
        callback1 = MagicMock()
        callback2 = MagicMock()
        multiplexer.register("agent-1", callback1)
        multiplexer.register("agent-2", callback2)

        results = []

        async def task1():
            with multiplexer.agent_context("agent-1"):
                await asyncio.sleep(0.01)  # Yield to other task
                multiplexer.on_request("/task1", {})
                results.append("task1")

        async def task2():
            with multiplexer.agent_context("agent-2"):
                await asyncio.sleep(0.005)  # Yield to other task
                multiplexer.on_request("/task2", {})
                results.append("task2")

        # Run both tasks concurrently
        await asyncio.gather(task1(), task2())

        # Each callback should only see its own agent's logs
        callback1.on_request.assert_called_once_with("/task1", {})
        callback2.on_request.assert_called_once_with("/task2", {})

    @pytest.mark.asyncio
    async def test_concurrent_agents_no_crosstalk(self):
        """Test that concurrent agents don't leak logs to each other."""
        multiplexer = LogMultiplexer()
        callback1 = MagicMock()
        callback2 = MagicMock()
        multiplexer.register("agent-1", callback1)
        multiplexer.register("agent-2", callback2)

        async def simulate_request(agent_id: str, n: int):
            """Simulate multiple log calls with interleaved awaits."""
            callback = multiplexer._callbacks[agent_id]
            with multiplexer.agent_context(agent_id):
                for i in range(n):
                    multiplexer.on_request(f"/{agent_id}/req{i}", {"i": i})
                    await asyncio.sleep(0.001)
                    multiplexer.on_response(200, {"i": i})
                    await asyncio.sleep(0.001)

        # Run 2 agents concurrently, each making 5 request/response pairs
        await asyncio.gather(
            simulate_request("agent-1", 5),
            simulate_request("agent-2", 5),
        )

        # Each callback should have exactly 5 requests and 5 responses
        assert callback1.on_request.call_count == 5
        assert callback1.on_response.call_count == 5
        assert callback2.on_request.call_count == 5
        assert callback2.on_response.call_count == 5

        # Verify no cross-contamination by checking call args
        for call in callback1.on_request.call_args_list:
            assert "/agent-1/" in call[0][0]
        for call in callback2.on_request.call_args_list:
            assert "/agent-2/" in call[0][0]


class TestLogMultiplexerProtocol:
    """Test that LogMultiplexer implements RawLogCallback protocol."""

    def test_has_on_request_method(self):
        """Test that LogMultiplexer has on_request method."""
        multiplexer = LogMultiplexer()
        assert hasattr(multiplexer, "on_request")
        assert callable(multiplexer.on_request)

    def test_has_on_response_method(self):
        """Test that LogMultiplexer has on_response method."""
        multiplexer = LogMultiplexer()
        assert hasattr(multiplexer, "on_response")
        assert callable(multiplexer.on_response)

    def test_has_on_chunk_method(self):
        """Test that LogMultiplexer has on_chunk method."""
        multiplexer = LogMultiplexer()
        assert hasattr(multiplexer, "on_chunk")
        assert callable(multiplexer.on_chunk)
