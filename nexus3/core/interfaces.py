"""Core interfaces (protocols) for NEXUS3.

This module defines the Protocol interfaces that components must implement.
Using Protocols enables structural subtyping for better type checking without
requiring inheritance.
"""

from collections.abc import AsyncIterator
from typing import Any, Protocol

from nexus3.core.types import Message, StreamEvent


class RawLogCallback(Protocol):
    """Protocol for raw API logging callbacks.

    Implementations receive raw API requests, responses, and streaming chunks
    for debugging and logging purposes. The provider calls these methods at
    appropriate points without knowing about the logging implementation.

    Example:
        class MyLogger:
            def on_request(self, endpoint: str, payload: dict[str, Any]) -> None:
                print(f"Request to {endpoint}")

            def on_response(self, status: int, body: dict[str, Any]) -> None:
                print(f"Response: {status}")

            def on_chunk(self, chunk: dict[str, Any]) -> None:
                print(f"Chunk: {chunk}")
    """

    def on_request(self, endpoint: str, payload: dict[str, Any]) -> None:
        """Called before making an HTTP request.

        Args:
            endpoint: The API endpoint URL being called.
            payload: The request body as a dictionary.
        """
        ...

    def on_response(self, status: int, body: dict[str, Any]) -> None:
        """Called after receiving a non-streaming response.

        Args:
            status: The HTTP status code.
            body: The response body as a parsed dictionary.
        """
        ...

    def on_chunk(self, chunk: dict[str, Any]) -> None:
        """Called for each parsed SSE chunk during streaming.

        Args:
            chunk: The parsed JSON chunk from the SSE stream.
        """
        ...

    def on_stream_complete(self, summary: dict[str, Any]) -> None:
        """Called when a streaming response finishes.

        Args:
            summary: Stream summary with keys: http_status, event_count,
                content_length, tool_call_count, received_done, finish_reason,
                duration_ms.
        """
        ...


class AsyncProvider(Protocol):
    """Protocol for async LLM providers.

    Implementations must provide both streaming and non-streaming completion
    methods. All providers are async-first per NEXUS3 design principles.

    Example:
        class OpenRouterProvider:
            async def complete(
                self,
                messages: list[Message],
                tools: list[dict[str, Any]] | None = None,
            ) -> Message:
                # Implementation here
                ...

            async def stream(
                self,
                messages: list[Message],
                tools: list[dict[str, Any]] | None = None,
            ) -> AsyncIterator[StreamEvent]:
                # Implementation here
                ...
    """

    async def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> Message:
        """Perform a non-streaming completion.

        Args:
            messages: The conversation history as a list of Messages.
            tools: Optional list of tool definitions in OpenAI function format.

        Returns:
            The assistant's response as a Message, potentially including tool_calls.

        Raises:
            ProviderError: If the API request fails.
        """
        ...

    def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream response with content and tool call detection.

        Args:
            messages: The conversation history as a list of Messages.
            tools: Optional list of tool definitions in OpenAI function format.

        Yields:
            StreamEvent subclasses:
            - ContentDelta: text content chunks (display immediately)
            - ToolCallStarted: notification when a tool call is detected
            - StreamComplete: final event with complete Message (content + tool_calls)

        Raises:
            ProviderError: If the API request fails.

        Example:
            async for event in provider.stream(messages, tools):
                if isinstance(event, ContentDelta):
                    print(event.text, end="")  # Display content
                elif isinstance(event, ToolCallStarted):
                    print(f"Calling {event.name}...")  # Update display
                elif isinstance(event, StreamComplete):
                    if event.message.tool_calls:
                        # Execute tools
                        pass
        """
        ...
