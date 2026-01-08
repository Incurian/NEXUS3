"""Context management for conversation state and token budgets."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nexus3.context.token_counter import TokenCounter, get_token_counter
from nexus3.core.types import Message, Role, ToolCall, ToolResult

if TYPE_CHECKING:
    from nexus3.session.logging import SessionLogger


@dataclass
class ContextConfig:
    """Configuration for context management."""

    max_tokens: int = 8000
    """Maximum tokens for context window."""

    reserve_tokens: int = 2000
    """Tokens to reserve for response generation."""

    truncation_strategy: str = "oldest_first"
    """Strategy for truncation: 'oldest_first' or 'middle_out'."""


class ContextManager:
    """Manages conversation context, token budget, and truncation.

    The ContextManager is responsible for:
    - Maintaining conversation history (messages)
    - Tracking token usage
    - Truncating old messages when over budget
    - Building message lists for API calls

    Example:
        config = ContextConfig(max_tokens=8000)
        context = ContextManager(config)
        context.set_system_prompt("You are helpful.")

        context.add_user_message("Hello!")
        messages = context.build_messages()  # For API call

        context.add_assistant_message("Hi there!")
    """

    def __init__(
        self,
        config: ContextConfig | None = None,
        token_counter: TokenCounter | None = None,
        logger: "SessionLogger | None" = None,
    ) -> None:
        """Initialize context manager.

        Args:
            config: Context configuration (uses defaults if None)
            token_counter: Token counter implementation (uses SimpleTokenCounter if None)
            logger: Optional session logger for context logging
        """
        self.config = config or ContextConfig()
        self._counter = token_counter or get_token_counter()
        self._logger = logger

        # Context state
        self._system_prompt: str = ""
        self._tool_definitions: list[dict[str, Any]] = []
        self._messages: list[Message] = []

    # === Setup ===

    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt.

        Args:
            prompt: System prompt content (from NEXUS.md or similar)
        """
        self._system_prompt = prompt
        if self._logger:
            self._logger.log_system(prompt)

    def set_tool_definitions(self, tools: list[dict[str, Any]]) -> None:
        """Set available tool definitions for context.

        Args:
            tools: List of tool definitions in OpenAI function format
        """
        self._tool_definitions = tools

    @property
    def system_prompt(self) -> str:
        """Get the current system prompt."""
        return self._system_prompt

    @property
    def messages(self) -> list[Message]:
        """Get all messages (read-only copy)."""
        return self._messages.copy()

    # === Message Management ===

    def add_user_message(self, content: str) -> None:
        """Add a user message to context.

        Args:
            content: User message content
        """
        msg = Message(role=Role.USER, content=content)
        self._messages.append(msg)
        if self._logger:
            self._logger.log_user(content)

    def add_assistant_message(
        self,
        content: str,
        tool_calls: list[ToolCall] | None = None,
    ) -> None:
        """Add an assistant message to context.

        Args:
            content: Assistant response content
            tool_calls: Optional list of tool calls made
        """
        msg = Message(
            role=Role.ASSISTANT,
            content=content,
            tool_calls=tuple(tool_calls) if tool_calls else (),
        )
        self._messages.append(msg)
        if self._logger:
            self._logger.log_assistant(content, tool_calls)

    def add_tool_result(
        self,
        tool_call_id: str,
        name: str,
        result: ToolResult,
    ) -> None:
        """Add a tool result to context.

        Args:
            tool_call_id: ID of the tool call this is responding to
            name: Name of the tool
            result: Tool execution result
        """
        content = result.error if result.error else result.output
        msg = Message(
            role=Role.TOOL,
            content=content,
            tool_call_id=tool_call_id,
        )
        self._messages.append(msg)
        if self._logger:
            self._logger.log_tool_result(tool_call_id, name, result)

    def clear_messages(self) -> None:
        """Clear all messages (keeps system prompt and tools)."""
        self._messages.clear()

    # === Context Building ===

    def build_messages(self) -> list[Message]:
        """Build message list for API call.

        Includes system prompt and messages that fit in context budget.
        Applies truncation if over budget.

        Returns:
            List of messages ready for provider API call
        """
        result: list[Message] = []

        # System prompt always first
        if self._system_prompt:
            result.append(Message(role=Role.SYSTEM, content=self._system_prompt))

        # Get messages that fit (with truncation if needed)
        context_messages = self._get_context_messages()
        result.extend(context_messages)

        return result

    def get_tool_definitions(self) -> list[dict[str, Any]] | None:
        """Get tool definitions for API call.

        Returns:
            List of tool definitions, or None if no tools configured
        """
        return self._tool_definitions if self._tool_definitions else None

    # === Token Tracking ===

    def get_token_usage(self) -> dict[str, int]:
        """Get current token usage breakdown.

        Returns:
            Dict with keys: system, tools, messages, total, budget, available
        """
        system_tokens = self._counter.count(self._system_prompt)
        tools_tokens = self._count_tools_tokens()
        message_tokens = self._counter.count_messages(self._messages)
        total = system_tokens + tools_tokens + message_tokens

        return {
            "system": system_tokens,
            "tools": tools_tokens,
            "messages": message_tokens,
            "total": total,
            "budget": self.config.max_tokens,
            "available": self.config.max_tokens - self.config.reserve_tokens,
        }

    def _count_tools_tokens(self) -> int:
        """Count tokens used by tool definitions."""
        if not self._tool_definitions:
            return 0

        import json

        tools_str = json.dumps(self._tool_definitions)
        return self._counter.count(tools_str)

    def is_over_budget(self) -> bool:
        """Check if context exceeds available token budget.

        Returns:
            True if total tokens > (max_tokens - reserve_tokens)
        """
        usage = self.get_token_usage()
        return usage["total"] > usage["available"]

    # === Truncation ===

    def _get_context_messages(self) -> list[Message]:
        """Get messages that fit in context, with truncation if needed."""
        if not self.is_over_budget():
            return self._messages.copy()

        # Apply truncation strategy
        if self.config.truncation_strategy == "middle_out":
            return self._truncate_middle_out()
        else:
            # Default: oldest_first
            return self._truncate_oldest_first()

    def _truncate_oldest_first(self) -> list[Message]:
        """Remove oldest messages until under budget.

        Always keeps at least the most recent message.
        """
        available = self.config.max_tokens - self.config.reserve_tokens
        system_tokens = self._counter.count(self._system_prompt)
        tools_tokens = self._count_tools_tokens()
        budget_for_messages = available - system_tokens - tools_tokens

        if budget_for_messages <= 0:
            # System + tools alone exceed budget, return only most recent
            return self._messages[-1:] if self._messages else []

        # Build from newest, stop when over budget
        result: list[Message] = []
        total = 0

        for msg in reversed(self._messages):
            msg_tokens = self._counter.count(msg.content) + 4  # overhead
            if total + msg_tokens > budget_for_messages and result:
                break  # Over budget, but keep at least one
            result.insert(0, msg)
            total += msg_tokens

        return result

    def _truncate_middle_out(self) -> list[Message]:
        """Keep first and last messages, remove middle.

        Preserves initial context and recent conversation.
        """
        if len(self._messages) <= 2:
            return self._messages.copy()

        available = self.config.max_tokens - self.config.reserve_tokens
        system_tokens = self._counter.count(self._system_prompt)
        tools_tokens = self._count_tools_tokens()
        budget_for_messages = available - system_tokens - tools_tokens

        if budget_for_messages <= 0:
            return self._messages[-1:] if self._messages else []

        # Always keep first and last
        first = self._messages[0]
        last = self._messages[-1]
        first_tokens = self._counter.count(first.content) + 4
        last_tokens = self._counter.count(last.content) + 4

        remaining_budget = budget_for_messages - first_tokens - last_tokens

        if remaining_budget <= 0:
            # Can only fit first and last
            return [first, last]

        # Add messages from the end (before last) until budget exhausted
        middle_messages: list[Message] = []
        total = 0

        for msg in reversed(self._messages[1:-1]):
            msg_tokens = self._counter.count(msg.content) + 4
            if total + msg_tokens > remaining_budget:
                break
            middle_messages.insert(0, msg)
            total += msg_tokens

        return [first] + middle_messages + [last]
