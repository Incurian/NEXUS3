"""Context management for conversation state and token budgets."""

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from nexus3.context.token_counter import TokenCounter, get_token_counter
from nexus3.core.types import Message, Role, ToolCall, ToolResult


def get_current_datetime_str() -> str:
    """Get current date and time formatted for context injection.

    Returns:
        Formatted string like "Current date: 2026-01-13, Current time: 14:32 (local)"
    """
    now = datetime.now()
    return f"Current date: {now.strftime('%Y-%m-%d')}, Current time: {now.strftime('%H:%M')} (local)"


def get_session_start_str() -> str:
    """Get session start timestamp for history.

    Returns:
        Formatted string for session start message.
    """
    now = datetime.now()
    return f"[Session started: {now.strftime('%Y-%m-%d %H:%M')} (local)]"

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

    def add_session_start_message(self) -> None:
        """Add a session start timestamp message to history.

        This should be called once when a new session begins. The timestamp
        is fixed and marks when the session started.
        """
        start_msg = Message(role=Role.USER, content=get_session_start_str())
        self._messages.append(start_msg)
        if self._logger:
            self._logger.log_user(start_msg.content)

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
    def token_counter(self) -> TokenCounter:
        """Get the token counter instance."""
        return self._counter

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

    def apply_compaction(
        self,
        summary_message: Message,
        preserved_messages: list[Message],
        new_system_prompt: str | None = None,
    ) -> None:
        """Apply compaction result to context.

        Replaces current messages with summary + preserved recent messages.
        Optionally updates system prompt (for picking up NEXUS.md changes).

        Args:
            summary_message: The summary as a Message (from compaction module)
            preserved_messages: Recent messages that were kept
            new_system_prompt: Optional fresh system prompt to use
        """
        # Update system prompt if provided (picks up NEXUS.md changes)
        if new_system_prompt is not None:
            self._system_prompt = new_system_prompt
            if self._logger:
                self._logger.log_system(new_system_prompt)

        # Replace messages: summary + preserved
        self._messages = [summary_message] + preserved_messages

    # === Context Building ===

    def build_messages(self) -> list[Message]:
        """Build message list for API call.

        Includes system prompt (with dynamic date/time) and messages that fit
        in context budget. Applies truncation if over budget.

        The current date/time is injected fresh on every call to ensure the
        agent always has accurate temporal context.

        Returns:
            List of messages ready for provider API call
        """
        result: list[Message] = []

        # System prompt always first, with dynamic date/time injected
        if self._system_prompt:
            # Inject current date/time at the start of the Environment section
            # or at the end of the prompt if no Environment section exists
            datetime_line = get_current_datetime_str()
            if "# Environment" in self._system_prompt:
                # Insert after the "# Environment" header
                prompt_with_time = self._system_prompt.replace(
                    "# Environment\n",
                    f"# Environment\n{datetime_line}\n"
                )
            else:
                # Append to end
                prompt_with_time = f"{self._system_prompt}\n\n{datetime_line}"
            result.append(Message(role=Role.SYSTEM, content=prompt_with_time))

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
        """Get messages that fit in context, with truncation if needed.

        When truncation occurs, _messages is updated to match what's sent.
        This keeps in-memory state synchronized with context - we only track
        what the LLM actually sees.
        """
        if not self.is_over_budget():
            return self._messages.copy()

        # Apply truncation strategy
        if self.config.truncation_strategy == "middle_out":
            truncated = self._truncate_middle_out()
        else:
            # Default: oldest_first
            truncated = self._truncate_oldest_first()

        # Sync _messages with what we're sending - don't keep orphaned messages
        self._messages = truncated

        return truncated

    def _identify_message_groups(self) -> list[list[Message]]:
        """Group messages into atomic units for truncation.

        Groups:
        - Standalone USER/SYSTEM message
        - Standalone ASSISTANT without tool_calls
        - ASSISTANT with tool_calls + all corresponding TOOL results (atomic)

        Returns:
            List of message groups. Each group must be kept or removed together.
        """
        groups: list[list[Message]] = []
        i = 0

        while i < len(self._messages):
            msg = self._messages[i]

            if msg.role == Role.ASSISTANT and msg.tool_calls:
                # Tool call group: assistant + matching results
                group = [msg]
                expected_ids = {tc.id for tc in msg.tool_calls}
                j = i + 1
                while j < len(self._messages) and self._messages[j].role == Role.TOOL:
                    tool_msg = self._messages[j]
                    if tool_msg.tool_call_id in expected_ids:
                        group.append(tool_msg)
                        j += 1
                    else:
                        break
                groups.append(group)
                i = j
            else:
                # Standalone message
                groups.append([msg])
                i += 1

        return groups

    def _count_group_tokens(self, group: list[Message]) -> int:
        """Count tokens for a message group."""
        total = 0
        for msg in group:
            # Use count_messages for accurate token counting including tool_calls
            total += self._counter.count_messages([msg])
        return total

    def _flatten_groups(self, groups: list[list[Message]]) -> list[Message]:
        """Flatten list of groups into single message list."""
        result: list[Message] = []
        for group in groups:
            result.extend(group)
        return result

    def _truncate_oldest_first(self) -> list[Message]:
        """Remove oldest message groups until under budget.

        Preserves tool call/result pairs as atomic units.
        """
        available = self.config.max_tokens - self.config.reserve_tokens
        system_tokens = self._counter.count(self._system_prompt)
        tools_tokens = self._count_tools_tokens()
        budget_for_messages = available - system_tokens - tools_tokens

        if budget_for_messages <= 0:
            # Return most recent group only
            groups = self._identify_message_groups()
            if groups:
                return groups[-1]
            return []

        groups = self._identify_message_groups()

        # Build from newest groups backwards
        result_groups: list[list[Message]] = []
        total = 0

        for group in reversed(groups):
            group_tokens = self._count_group_tokens(group)
            if total + group_tokens > budget_for_messages and result_groups:
                break
            result_groups.insert(0, group)
            total += group_tokens

        return self._flatten_groups(result_groups)

    def _truncate_middle_out(self) -> list[Message]:
        """Keep first and last groups, remove middle groups.

        Preserves tool call/result pairs as atomic units.
        """
        if len(self._messages) <= 2:
            return self._messages.copy()

        groups = self._identify_message_groups()

        if len(groups) <= 2:
            return self._messages.copy()

        available = self.config.max_tokens - self.config.reserve_tokens
        system_tokens = self._counter.count(self._system_prompt)
        tools_tokens = self._count_tools_tokens()
        budget_for_messages = available - system_tokens - tools_tokens

        if budget_for_messages <= 0:
            return groups[-1] if groups else []

        first_group = groups[0]
        last_group = groups[-1]
        first_tokens = self._count_group_tokens(first_group)
        last_tokens = self._count_group_tokens(last_group)

        remaining_budget = budget_for_messages - first_tokens - last_tokens

        if remaining_budget <= 0:
            return self._flatten_groups([first_group, last_group])

        # Add groups from end (before last) until budget exhausted
        middle_groups: list[list[Message]] = []
        total = 0

        for group in reversed(groups[1:-1]):
            group_tokens = self._count_group_tokens(group)
            if total + group_tokens > remaining_budget:
                break
            middle_groups.insert(0, group)
            total += group_tokens

        return self._flatten_groups([first_group] + middle_groups + [last_group])
