"""Integration tests for Phase 0 chat functionality.

Tests the Session class with mock providers to verify the streaming and
non-streaming chat flows work correctly end-to-end.
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
)
from nexus3.session.session import Session


class MockProvider:
    """Mock provider that implements AsyncProvider protocol.

    Returns predefined responses for testing without requiring API calls.
    """

    def __init__(
        self,
        stream_chunks: list[str] | None = None,
        complete_content: str = "Hello world!",
    ) -> None:
        """Initialize the mock provider.

        Args:
            stream_chunks: List of chunks to yield. Defaults to ["Hello", " ", "world", "!"].
            complete_content: Content to return. Defaults to "Hello world!".
        """
        default_chunks = ["Hello", " ", "world", "!"]
        self.stream_chunks = stream_chunks if stream_chunks is not None else default_chunks
        self.complete_content = complete_content
        self.last_messages: list[Message] | None = None
        self.stream_call_count = 0
        self.complete_call_count = 0

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Yield predefined chunks as StreamEvents for testing.

        Args:
            messages: The conversation messages (stored for test assertions).
            tools: Optional tool definitions (ignored in mock).

        Yields:
            StreamEvent objects (ContentDelta and StreamComplete).
        """
        self.last_messages = messages
        self.stream_call_count += 1

        # Yield content chunks
        for chunk in self.stream_chunks:
            yield ContentDelta(text=chunk)

        # Yield final StreamComplete with the full message
        full_content = "".join(self.stream_chunks)
        yield StreamComplete(
            message=Message(role=Role.ASSISTANT, content=full_content)
        )

    async def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> Message:
        """Return a predefined Message for testing.

        Args:
            messages: The conversation messages (stored for test assertions).
            tools: Optional tool definitions (ignored in mock).

        Returns:
            A Message with predefined content.
        """
        self.last_messages = messages
        self.complete_call_count += 1
        return Message(role=Role.ASSISTANT, content=self.complete_content)


class TestSessionStreaming:
    """Tests for Session.send() streaming functionality."""

    @pytest.mark.asyncio
    async def test_send_collects_all_chunks(self) -> None:
        """Test that session.send() yields all chunks from the provider."""
        provider = MockProvider()
        session = Session(provider)

        chunks = [chunk async for chunk in session.send("test")]

        assert chunks == ["Hello", " ", "world", "!"]
        assert "".join(chunks) == "Hello world!"

    @pytest.mark.asyncio
    async def test_send_passes_user_message(self) -> None:
        """Test that send() correctly passes user message to provider."""
        provider = MockProvider()
        session = Session(provider)

        # Consume the generator to trigger the call
        _ = [chunk async for chunk in session.send("What is 2+2?")]

        assert provider.last_messages is not None
        assert len(provider.last_messages) == 1
        assert provider.last_messages[0].role == Role.USER
        assert provider.last_messages[0].content == "What is 2+2?"

    @pytest.mark.asyncio
    async def test_send_includes_system_prompt(self) -> None:
        """Test that send() includes system prompt when configured via ContextManager."""
        provider = MockProvider()
        context = ContextManager(config=ContextConfig())
        context.set_system_prompt("You are a helpful assistant.")
        session = Session(provider, context=context)

        # Consume the generator to trigger the call
        _ = [chunk async for chunk in session.send("Hello")]

        assert provider.last_messages is not None
        assert len(provider.last_messages) == 2

        # First message should be system prompt
        assert provider.last_messages[0].role == Role.SYSTEM
        assert provider.last_messages[0].content == "You are a helpful assistant."

        # Second message should be user message
        assert provider.last_messages[1].role == Role.USER
        assert provider.last_messages[1].content == "Hello"

    @pytest.mark.asyncio
    async def test_send_without_system_prompt(self) -> None:
        """Test that send() works correctly without a system prompt (single-turn mode)."""
        provider = MockProvider()
        # No context = single-turn mode (backwards compatible)
        session = Session(provider)

        # Consume the generator to trigger the call
        _ = [chunk async for chunk in session.send("Hi there")]

        assert provider.last_messages is not None
        assert len(provider.last_messages) == 1
        assert provider.last_messages[0].role == Role.USER
        assert provider.last_messages[0].content == "Hi there"

    @pytest.mark.asyncio
    async def test_send_calls_stream_once(self) -> None:
        """Test that send() calls stream() exactly once per call."""
        provider = MockProvider()
        session = Session(provider)

        # First call
        _ = [chunk async for chunk in session.send("test1")]
        assert provider.stream_call_count == 1

        # Second call
        _ = [chunk async for chunk in session.send("test2")]
        assert provider.stream_call_count == 2

    @pytest.mark.asyncio
    async def test_send_with_empty_chunks(self) -> None:
        """Test that send() handles empty chunk list gracefully."""
        provider = MockProvider(stream_chunks=[])
        session = Session(provider)

        chunks = [chunk async for chunk in session.send("test")]

        assert chunks == []
        assert "".join(chunks) == ""

    @pytest.mark.asyncio
    async def test_send_with_single_chunk(self) -> None:
        """Test that send() works with a single chunk."""
        provider = MockProvider(stream_chunks=["Complete response"])
        session = Session(provider)

        chunks = [chunk async for chunk in session.send("test")]

        assert chunks == ["Complete response"]
        assert "".join(chunks) == "Complete response"

    @pytest.mark.asyncio
    async def test_send_with_unicode_content(self) -> None:
        """Test that send() correctly handles unicode content."""
        provider = MockProvider(stream_chunks=["Hello ", "world! ", "Emoji: ", "test"])
        session = Session(provider)

        chunks = [chunk async for chunk in session.send("Say hi in Japanese")]

        assert "".join(chunks) == "Hello world! Emoji: test"


class TestMockProvider:
    """Tests for MockProvider to ensure it correctly implements the protocol."""

    @pytest.mark.asyncio
    async def test_complete_returns_message(self) -> None:
        """Test that complete() returns a valid Message."""
        provider = MockProvider(complete_content="Test response")

        result = await provider.complete([Message(role=Role.USER, content="test")])

        assert isinstance(result, Message)
        assert result.role == Role.ASSISTANT
        assert result.content == "Test response"
        assert result.tool_calls == ()
        assert result.tool_call_id is None

    @pytest.mark.asyncio
    async def test_complete_stores_messages(self) -> None:
        """Test that complete() stores the messages for assertions."""
        provider = MockProvider()
        messages = [
            Message(role=Role.SYSTEM, content="System prompt"),
            Message(role=Role.USER, content="User message"),
        ]

        await provider.complete(messages)

        assert provider.last_messages == messages
        assert provider.complete_call_count == 1


# Tests that would require a real API key
@pytest.mark.skip(reason="Requires API key")
@pytest.mark.integration
class TestRealProviderIntegration:
    """Integration tests that require a real API connection.

    These tests are skipped by default and require OPENROUTER_API_KEY
    to be set in the environment.
    """

    @pytest.mark.asyncio
    async def test_real_streaming_response(self) -> None:
        """Test streaming with a real OpenRouter provider."""
        from nexus3.config.schema import ProviderConfig
        from nexus3.provider.openrouter import OpenRouterProvider

        config = ProviderConfig(
            api_key_env="OPENROUTER_API_KEY",
            model="anthropic/claude-sonnet-4",
        )
        provider = OpenRouterProvider(config)
        session = Session(provider)

        chunks = [chunk async for chunk in session.send("Say 'test' and nothing else")]
        result = "".join(chunks)

        assert len(result) > 0
        assert "test" in result.lower()

    @pytest.mark.asyncio
    async def test_real_complete_response(self) -> None:
        """Test non-streaming completion with a real OpenRouter provider."""
        from nexus3.config.schema import ProviderConfig
        from nexus3.provider.openrouter import OpenRouterProvider

        config = ProviderConfig(
            api_key_env="OPENROUTER_API_KEY",
            model="anthropic/claude-sonnet-4",
        )
        provider = OpenRouterProvider(config)

        messages = [Message(role=Role.USER, content="Say 'hello' and nothing else")]
        result = await provider.complete(messages)

        assert isinstance(result, Message)
        assert result.role == Role.ASSISTANT
        assert len(result.content) > 0
