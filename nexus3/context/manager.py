"""Context management for conversation state and token budgets."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nexus3.clipboard import format_clipboard_context
from nexus3.config.schema import ClipboardConfig
from nexus3.context.git_context import get_git_context
from nexus3.context.token_counter import TokenCounter, get_token_counter
from nexus3.core.types import Message, Role, ToolCall, ToolResult


def get_current_datetime_str() -> str:
    """Get current date and time formatted for context injection.

    Returns:
        Formatted string like "Current date: 2026-01-13, Current time: 14:32 (local)"
    """
    now = datetime.now()
    return (
        f"Current date: {now.strftime('%Y-%m-%d')},"
        f" Current time: {now.strftime('%H:%M')} (local)"
    )


def get_session_start_str(
    agent_id: str | None = None,
    preset: str | None = None,
    cwd: str | None = None,
    write_paths: list[str] | None = None,
    has_confirmation_ui: bool = False,
) -> str:
    """Get session start message with agent metadata for history.

    Args:
        agent_id: Agent identifier.
        preset: Permission preset name (e.g., "trusted", "sandboxed").
        cwd: Working directory path.
        write_paths: Allowed write paths (for sandboxed agents).
        has_confirmation_ui: Whether a confirmation UI is available (REPL mode).
            When False, trusted agents can only write within CWD.

    Returns:
        Formatted string for session start message.
    """
    now = datetime.now()
    parts = [f"[Session started: {now.strftime('%Y-%m-%d %H:%M')} (local)"]

    if agent_id:
        parts.append(f" | Agent: {agent_id}")
    if preset:
        parts.append(f" | Preset: {preset}")
    if cwd:
        parts.append(f" | CWD: {cwd}")
    if write_paths:
        parts.append(f" | Write paths: {', '.join(write_paths)}")
    elif preset == "trusted" and not has_confirmation_ui:
        parts.append(" | Writes: CWD only (no confirmation UI)")
    elif preset == "trusted" and has_confirmation_ui:
        parts.append(" | Writes: CWD unrestricted, elsewhere with user confirmation")

    parts.append("]")
    return "".join(parts)


# Maximum length for tool result prefix (tool name + args)
TOOL_RESULT_PREFIX_MAX_LEN = 120


def format_tool_result_prefix(
    call_index: int,
    name: str,
    arguments: dict[str, Any] | None,
) -> str:
    """Format a prefix for tool results to help models correlate calls with results.

    Args:
        call_index: 1-based index of this call in the batch
        name: Tool name
        arguments: Tool arguments (will be truncated if too long)

    Returns:
        Formatted prefix like "[#1: list_directory(path="nexus3/core/")]"
    """
    if not arguments:
        return f"[#{call_index}: {name}()]\n"

    # Format arguments, skipping internal ones like _parallel
    # Also skip 'content' for write operations (too long, potentially sensitive)
    skip_keys = {"_parallel", "content", "new_content", "code"}
    args_parts = []
    for k, v in arguments.items():
        if k in skip_keys:
            continue
        # Truncate long values
        v_str = str(v)
        if len(v_str) > 50:
            v_str = v_str[:47] + "..."
        args_parts.append(f'{k}="{v_str}"')

    args_str = ", ".join(args_parts)

    # Build prefix and truncate if needed
    prefix = f"[#{call_index}: {name}({args_str})]"
    if len(prefix) > TOOL_RESULT_PREFIX_MAX_LEN:
        prefix = prefix[: TOOL_RESULT_PREFIX_MAX_LEN - 4] + "...)]"

    return prefix + "\n"


def inject_datetime_into_prompt(prompt: str, datetime_line: str) -> str:
    """Inject datetime line into prompt at the Environment section.

    This function uses explicit section boundary detection rather than
    simple str.replace() to avoid issues where the marker might appear
    elsewhere in the prompt content.

    Strategy:
    1. Find "# Environment" at the start of a line (section header)
    2. Verify it's a standalone header (followed by newline or EOF)
    3. Insert datetime_line after the header line

    If no "# Environment" section is found, appends to the end.

    Args:
        prompt: The system prompt to inject into.
        datetime_line: The formatted datetime string to inject.

    Returns:
        Prompt with datetime injected at the appropriate location.
    """
    # Look for "# Environment" as a section header (at line start)
    # This is more robust than str.replace which could match anywhere
    env_marker = "# Environment"
    marker_len = len(env_marker)

    # Find the marker at the start of a line
    search_start = 0
    while True:
        pos = prompt.find(env_marker, search_start)
        if pos == -1:
            # No marker found - append to end
            return f"{prompt}\n\n{datetime_line}"

        # Check if this is at the start of a line (pos == 0 or preceded by newline)
        at_line_start = pos == 0 or prompt[pos - 1] == "\n"

        # Check if it's a standalone header (followed by newline or EOF)
        # This avoids matching "# Environment Variables" etc.
        end_pos = pos + marker_len
        is_standalone = end_pos >= len(prompt) or prompt[end_pos] == "\n"

        if at_line_start and is_standalone:
            # Found valid section header - find the end of this line
            newline_pos = prompt.find("\n", pos)
            if newline_pos == -1:
                # Header is at EOF - append datetime after it
                return f"{prompt}\n{datetime_line}"

            # Insert datetime after the header line
            before = prompt[: newline_pos + 1]
            after = prompt[newline_pos + 1 :]
            return f"{before}{datetime_line}\n{after}"

        # Not a valid standalone header - continue searching
        search_start = pos + 1


if TYPE_CHECKING:
    from nexus3.clipboard import ClipboardManager
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
        agent_id: str | None = None,
        clipboard_manager: "ClipboardManager | None" = None,
        clipboard_config: ClipboardConfig | None = None,
    ) -> None:
        """Initialize context manager.

        Args:
            config: Context configuration (uses defaults if None)
            token_counter: Token counter implementation (uses SimpleTokenCounter if None)
            logger: Optional session logger for context logging
            agent_id: Agent ID for clipboard scoping
            clipboard_manager: Optional clipboard manager for context injection
            clipboard_config: Clipboard configuration (uses defaults if None)
        """
        self.config = config or ContextConfig()
        self._counter = token_counter or get_token_counter()
        self._logger = logger
        self._agent_id = agent_id
        self._clipboard_manager = clipboard_manager
        self._clipboard_config = clipboard_config or ClipboardConfig()

        # Context state
        self._system_prompt: str = ""
        self._tool_definitions: list[dict[str, Any]] = []
        self._messages: list[Message] = []
        self._git_context: str | None = None

    # === Setup ===

    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt.

        Args:
            prompt: System prompt content (from NEXUS.md or similar)
        """
        self._system_prompt = prompt
        if self._logger:
            self._logger.log_system(prompt)

    def refresh_git_context(self, cwd: str | Path) -> None:
        """Refresh cached git repository context for the given directory.

        Args:
            cwd: Working directory to check for git repository.
        """
        self._git_context = get_git_context(cwd)

    def add_session_start_message(
        self,
        agent_id: str | None = None,
        preset: str | None = None,
        cwd: str | None = None,
        write_paths: list[str] | None = None,
        has_confirmation_ui: bool = False,
    ) -> None:
        """Add a session start message with agent metadata to history.

        This should be called once when a new session begins. Includes
        agent identity, permissions, and working directory so the agent
        has self-knowledge from the start.

        Args:
            agent_id: Agent identifier.
            preset: Permission preset name.
            cwd: Working directory path.
            write_paths: Allowed write paths (for sandboxed agents).
            has_confirmation_ui: Whether a confirmation UI is available.
        """
        start_msg = Message(
            role=Role.USER,
            content=get_session_start_str(
                agent_id=agent_id,
                preset=preset,
                cwd=cwd,
                write_paths=write_paths,
                has_confirmation_ui=has_confirmation_ui,
            ),
        )
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

    def _build_system_prompt_for_api_call(self) -> str:
        """Build the full system prompt with all dynamic injections.

        This centralizes all system prompt modifications:
        1. Inject current date/time at the Environment section
        2. Inject git repository context if available
        3. Inject clipboard context if enabled

        Returns:
            The fully constructed system prompt ready for API calls.
        """
        if not self._system_prompt:
            return ""

        # Start with datetime injection
        datetime_line = get_current_datetime_str()
        prompt = inject_datetime_into_prompt(self._system_prompt, datetime_line)

        # Add git context if available
        if self._git_context:
            prompt = f"{prompt}\n\n{self._git_context}"

        # Add clipboard context if enabled and manager is available
        if (
            self._clipboard_manager is not None
            and self._clipboard_config.inject_into_context
        ):
            clipboard_section = format_clipboard_context(
                self._clipboard_manager,
                max_entries=self._clipboard_config.max_injected_entries,
                show_source=self._clipboard_config.show_source_in_injection,
            )
            if clipboard_section:
                prompt = f"{prompt}\n\n{clipboard_section}"

        return prompt

    @property
    def token_counter(self) -> TokenCounter:
        """Get the token counter instance."""
        return self._counter

    @property
    def messages(self) -> list[Message]:
        """Get all messages (read-only copy)."""
        return self._messages.copy()

    # === Message Management ===

    def add_user_message(self, content: str, meta: dict[str, Any] | None = None) -> None:
        """Add a user message to context.

        Args:
            content: User message content
            meta: Optional metadata dict (e.g., source attribution)
        """
        msg = Message(role=Role.USER, content=content, meta=meta or {})
        self._messages.append(msg)
        if self._logger:
            self._logger.log_user(content, meta=meta)

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
        call_index: int | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> None:
        """Add a tool result to context.

        Args:
            tool_call_id: ID of the tool call this is responding to
            name: Name of the tool
            result: Tool execution result
            call_index: 1-based index of this call in the batch (for correlation prefix)
            arguments: Original arguments (for correlation prefix)
        """
        content = result.error if result.error else result.output

        # Add correlation prefix if index provided
        if call_index is not None:
            prefix = format_tool_result_prefix(call_index, name, arguments)
            content = prefix + content

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

        Includes system prompt (with dynamic date/time and clipboard context)
        and messages that fit in context budget. Applies truncation if over budget.

        The current date/time is injected fresh on every call to ensure the
        agent always has accurate temporal context.

        Returns:
            List of messages ready for provider API call
        """
        result: list[Message] = []

        # System prompt always first, with all dynamic injections
        prompt = self._build_system_prompt_for_api_call()
        if prompt:
            result.append(Message(role=Role.SYSTEM, content=prompt))

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
            Dict with keys: system, tools, messages, total, budget, available, remaining
            - budget: Full context window size
            - available: Budget minus reserve tokens (what's usable for context)
            - remaining: Available minus total (how much space is left)
        """
        # Count system prompt with all dynamic injections (matches build_messages)
        prompt = self._build_system_prompt_for_api_call()
        system_tokens = self._counter.count(prompt) if prompt else 0

        tools_tokens = self._count_tools_tokens()
        message_tokens = self._counter.count_messages(self._messages)
        total = system_tokens + tools_tokens + message_tokens
        available = self.config.max_tokens - self.config.reserve_tokens
        remaining = max(0, available - total)

        return {
            "system": system_tokens,
            "tools": tools_tokens,
            "messages": message_tokens,
            "total": total,
            "budget": self.config.max_tokens,
            "available": available,
            "remaining": remaining,
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
        prompt = self._build_system_prompt_for_api_call()
        system_tokens = self._counter.count(prompt) if prompt else 0
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
        prompt = self._build_system_prompt_for_api_call()
        system_tokens = self._counter.count(prompt) if prompt else 0
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
