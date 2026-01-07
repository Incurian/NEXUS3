"""Chat session coordinator for NEXUS3.

This module provides the Session class, which coordinates communication between
the CLI and an LLM provider. For Phase 0, this is a minimal implementation that
handles single-turn streaming chat without history persistence or tool handling.
"""

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from nexus3.core.interfaces import AsyncProvider
from nexus3.core.types import Message, Role

if TYPE_CHECKING:
    from nexus3.session.logging import SessionLogger


class Session:
    """Coordinator between CLI and LLM provider.

    The Session class is a thin coordinator that manages the conversation flow
    between user input and provider responses. It is intentionally minimal for
    Phase 0, handling only single-turn streaming chat.

    Attributes:
        provider: The async LLM provider to use for completions.
        system_prompt: Optional system prompt to include in all requests.
        logger: Optional session logger for context logging.

    Example:
        provider = OpenRouterProvider(config)
        session = Session(provider, system_prompt="You are a helpful assistant.")

        async for chunk in session.send("Hello!"):
            print(chunk, end="", flush=True)
    """

    def __init__(
        self,
        provider: AsyncProvider,
        system_prompt: str | None = None,
        logger: "SessionLogger | None" = None,
    ) -> None:
        """Initialize a new session.

        Args:
            provider: The async LLM provider to use for completions.
            system_prompt: Optional system prompt to prepend to all conversations.
            logger: Optional session logger for context and verbose logging.
        """
        self.provider = provider
        self.system_prompt = system_prompt
        self.logger = logger

        # Log system prompt if logger provided
        if logger and system_prompt:
            logger.log_system(system_prompt)

    async def send(self, user_input: str) -> AsyncIterator[str]:
        """Send a message and stream the response.

        Creates a user message from the input, builds the messages list
        (including system prompt if configured), and streams the response
        from the provider.

        Args:
            user_input: The user's message text.

        Yields:
            String chunks of the assistant's response as they arrive.

        Raises:
            ProviderError: If the provider request fails.

        Note:
            Phase 0: This method does not persist history. Each call is
            a single-turn conversation. History will be added in Phase 2.
        """
        # Log user message
        if self.logger:
            self.logger.log_user(user_input)

        # Build messages list
        messages: list[Message] = []

        # Add system prompt if configured
        if self.system_prompt:
            messages.append(Message(role=Role.SYSTEM, content=self.system_prompt))

        # Add user message
        messages.append(Message(role=Role.USER, content=user_input))

        # Stream response from provider, accumulating for logging
        response_chunks: list[str] = []
        async for chunk in self.provider.stream(messages):
            response_chunks.append(chunk)
            yield chunk

        # Log complete assistant response
        if self.logger:
            full_response = "".join(response_chunks)
            self.logger.log_assistant(full_response)
