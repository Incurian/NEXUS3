"""Core interfaces (protocols) for NEXUS3.

This module defines the Protocol interfaces that components must implement.
Using Protocols enables structural subtyping for better type checking without
requiring inheritance.
"""

from collections.abc import AsyncIterator
from typing import Any, Protocol

from nexus3.core.types import Message


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
            ) -> AsyncIterator[str]:
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
    ) -> AsyncIterator[str]:
        """Stream response tokens from a completion.

        Args:
            messages: The conversation history as a list of Messages.
            tools: Optional list of tool definitions in OpenAI function format.

        Yields:
            String chunks of the response as they arrive.

        Raises:
            ProviderError: If the API request fails.

        Note:
            When tools are provided and the model decides to call a tool,
            the stream may end early and the caller should use complete()
            to get the full tool call information.
        """
        ...
