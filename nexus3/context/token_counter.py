"""Token counting with pluggable backends."""

import json
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from nexus3.core.types import Message


class TokenCounter(Protocol):
    """Protocol for token counting implementations."""

    def count(self, text: str) -> int:
        """Count tokens in a text string."""
        ...

    def count_messages(self, messages: list["Message"]) -> int:
        """Count tokens in a list of messages."""
        ...


class SimpleTokenCounter:
    """Simple character-based token estimation.

    Uses a heuristic that ~4 characters = 1 token (common for English text).
    Good enough for rough estimates without external dependencies.

    Note: This is intentionally conservative (overestimates) to avoid
    context overflow.
    """

    CHARS_PER_TOKEN = 4  # ~4 characters per token for English
    OVERHEAD_PER_MESSAGE = 4  # Role, formatting overhead

    def count(self, text: str) -> int:
        """Count tokens using character-based estimation.

        Args:
            text: Text string to count tokens for.

        Returns:
            Estimated token count.
        """
        if not text:
            return 0
        return max(1, len(text) // self.CHARS_PER_TOKEN)

    def count_messages(self, messages: list["Message"]) -> int:
        """Count tokens in messages with overhead per message.

        Args:
            messages: List of Message objects to count.

        Returns:
            Total estimated token count for all messages.
        """
        total = 0
        for msg in messages:
            total += self.count(msg.content) + self.OVERHEAD_PER_MESSAGE

            # Tool calls add overhead
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    total += self.count(tc.name)
                    # Arguments as JSON string
                    args_str = json.dumps(tc.arguments)
                    total += self.count(args_str)

        return total


class TiktokenCounter:
    """Accurate token counting using tiktoken.

    Requires tiktoken package: pip install tiktoken
    Uses cl100k_base encoding (GPT-4, Claude-compatible).
    """

    OVERHEAD_PER_MESSAGE = 4

    def __init__(self, encoding_name: str = "cl100k_base") -> None:
        """Initialize with tiktoken encoding.

        Args:
            encoding_name: Tiktoken encoding name (default: cl100k_base)

        Raises:
            ImportError: If tiktoken is not installed.
        """
        try:
            import tiktoken  # type: ignore[import-not-found]
        except ImportError as e:
            raise ImportError(
                "tiktoken is not installed. "
                "Install it with: pip install tiktoken"
            ) from e

        self._encoder = tiktoken.get_encoding(encoding_name)

    def count(self, text: str) -> int:
        """Count tokens using tiktoken.

        Args:
            text: Text string to count tokens for.

        Returns:
            Accurate token count.
        """
        if not text:
            return 0
        return len(self._encoder.encode(text))

    def count_messages(self, messages: list["Message"]) -> int:
        """Count tokens in messages with accurate encoding.

        Args:
            messages: List of Message objects to count.

        Returns:
            Total token count for all messages.
        """
        total = 0
        for msg in messages:
            total += self.count(msg.content) + self.OVERHEAD_PER_MESSAGE

            if msg.tool_calls:
                for tc in msg.tool_calls:
                    total += self.count(tc.name)
                    args_str = json.dumps(tc.arguments)
                    total += self.count(args_str)

        return total


def get_token_counter(use_tiktoken: bool = True) -> TokenCounter:
    """Factory function to get appropriate token counter.

    Args:
        use_tiktoken: If True (default), try to use tiktoken.
                      Falls back to SimpleTokenCounter if unavailable.

    Returns:
        TokenCounter implementation (TiktokenCounter if available, else SimpleTokenCounter)

    Example:
        >>> counter = get_token_counter()
        >>> tokens = counter.count("Hello, world!")
        >>> print(tokens)  # Accurate token count with tiktoken
    """
    if use_tiktoken:
        try:
            return TiktokenCounter()
        except ImportError:
            pass  # Fall back to simple counter

    return SimpleTokenCounter()
