"""Context management for conversation state and token budgets."""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nexus3.clipboard import format_clipboard_context
from nexus3.config.schema import ClipboardConfig
from nexus3.context.git_context import get_git_context
from nexus3.context.token_counter import TokenCounter, get_token_counter
from nexus3.core.types import Message, Role, ToolCall, ToolResult

logger = logging.getLogger(__name__)


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

    def build_dynamic_context(self) -> str | None:
        """Build volatile session context for injection at the conversation edge.

        Dynamic content (datetime, git status, clipboard) is separated from the
        static system prompt so the system prompt remains cacheable. This context
        is injected into the last user message by the provider.

        Returns:
            XML-wrapped string with datetime, git status, clipboard, or None
            if there's nothing to inject.
        """
        parts: list[str] = []
        parts.append(get_current_datetime_str())

        if self._git_context:
            parts.append(self._git_context)

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
                parts.append(clipboard_section)

        if not parts:
            return None

        return "<session-context>\n" + "\n\n".join(parts) + "\n</session-context>"

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
        if not content and not tool_calls:
            logger.warning("Skipping empty assistant message (no content, no tool calls)")
            return

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

    def fix_orphaned_tool_calls(self) -> None:
        """Ensure all tool_use blocks have matching tool_result messages.

        Scans all assistant messages with tool_calls and verifies each batch
        has contiguous tool_result messages immediately after the assistant
        message. Inserts synthetic "cancelled" results for missing tool calls
        before the next non-tool message.

        This prevents API errors (e.g., "Unexpected role 'user' after role
        'tool'") when the conversation is interrupted mid-tool-execution,
        such as when the user presses ESC twice rapidly.
        """
        if not self._messages:
            return

        i = 0
        while i < len(self._messages):
            msg = self._messages[i]
            if not (msg.role == Role.ASSISTANT and msg.tool_calls):
                i += 1
                continue

            expected_ids = {tc.id for tc in msg.tool_calls}
            found_ids: set[str] = set()

            # Tool results must be contiguous after assistant tool_call message.
            j = i + 1
            while j < len(self._messages):
                next_msg = self._messages[j]
                if next_msg.role != Role.TOOL:
                    break
                if next_msg.tool_call_id in expected_ids:
                    found_ids.add(next_msg.tool_call_id)
                j += 1

            missing_ids = expected_ids - found_ids
            if missing_ids:
                insert_pos = j
                for tc in msg.tool_calls:
                    if tc.id not in missing_ids:
                        continue
                    synthetic = Message(
                        role=Role.TOOL,
                        content="Cancelled by user: tool execution was interrupted",
                        tool_call_id=tc.id,
                    )
                    self._messages.insert(insert_pos, synthetic)
                    insert_pos += 1

                logger.warning(
                    "Synthesized %d missing tool result(s) for orphaned "
                    "tool calls: %s",
                    len(missing_ids),
                    list(missing_ids),
                )
                j = insert_pos

            i = j

    def prune_unpaired_tool_results(self) -> int:
        """Remove TOOL messages that are not paired with a preceding assistant tool batch.

        Valid TOOL messages must be contiguous immediately after an assistant
        message with tool_calls and must reference one of that batch's ids.

        Returns:
            Number of TOOL messages removed.
        """
        if not self._messages:
            return 0

        removed = 0
        i = 0
        while i < len(self._messages):
            msg = self._messages[i]

            if msg.role == Role.ASSISTANT and msg.tool_calls:
                expected_ids = {tc.id for tc in msg.tool_calls}
                seen_ids: set[str] = set()
                j = i + 1
                while j < len(self._messages) and self._messages[j].role == Role.TOOL:
                    tool_msg = self._messages[j]
                    tool_id = tool_msg.tool_call_id
                    if tool_id in expected_ids and tool_id not in seen_ids:
                        seen_ids.add(tool_id)
                        j += 1
                        continue

                    # Unknown/duplicate tool_result in this contiguous block.
                    del self._messages[j]
                    removed += 1
                i = j
                continue

            if msg.role == Role.TOOL:
                # TOOL message outside a valid assistant tool_calls block.
                del self._messages[i]
                removed += 1
                continue

            i += 1

        if removed:
            logger.warning(
                "Pruned %d unpaired tool result message(s) from context",
                removed,
            )

        return removed

    def ensure_assistant_after_tool_results(self) -> bool:
        """Ensure a trailing TOOL-result batch is followed by an assistant message.

        Some providers reject a new USER message directly after TOOL messages
        (even when tool_call pairing is valid). If the conversation currently
        ends with TOOL results from a prior interrupted/cancelled turn, append a
        synthetic assistant note so the next USER turn has a safe role sequence.

        Returns:
            True if a synthetic assistant message was appended, False otherwise.
        """
        if not self._messages:
            return False

        if self._messages[-1].role != Role.TOOL:
            return False

        # Find start of trailing contiguous TOOL block.
        start = len(self._messages) - 1
        while start >= 0 and self._messages[start].role == Role.TOOL:
            start -= 1
        start += 1

        assistant_idx = start - 1
        if assistant_idx < 0:
            return False

        assistant_msg = self._messages[assistant_idx]
        if assistant_msg.role != Role.ASSISTANT or not assistant_msg.tool_calls:
            return False

        expected_ids = {tc.id for tc in assistant_msg.tool_calls}
        found_ids = {
            m.tool_call_id for m in self._messages[start:] if m.tool_call_id is not None
        }

        # Only synthesize if this is a valid/repairable tool-result tail.
        if not expected_ids.issubset(found_ids):
            return False

        synthetic = Message(
            role=Role.ASSISTANT,
            content="Previous turn was cancelled after tool execution.",
        )
        self._messages.append(synthetic)
        if self._logger:
            self._logger.log_assistant(synthetic.content)

        logger.warning(
            "Appended synthetic assistant message after trailing tool results "
            "to maintain valid role sequencing"
        )
        return True

    def clear_messages(self) -> None:
        """Clear all messages (keeps system prompt and tools)."""
        self._messages.clear()

    def replace_messages(self, messages: list[Message]) -> None:
        """Replace in-memory conversation history without re-logging messages.

        This is used by preflight normalization paths that repair context state
        before appending the next user turn.
        """
        self._messages = messages.copy()

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

        Uses the static system prompt (without dynamic injections) so it
        remains cacheable. Dynamic context (datetime, git, clipboard) is
        built separately via build_dynamic_context() and injected by the
        provider into the last user message.

        Returns:
            List of messages ready for provider API call
        """
        result: list[Message] = []

        # System prompt is static only (cacheable)
        prompt = self._system_prompt
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
            Dict with keys: system, dynamic, tools, messages, total, budget, available, remaining
            - system: Static system prompt tokens (cacheable)
            - dynamic: Dynamic context tokens (datetime, git, clipboard - per-request)
            - budget: Full context window size
            - available: Budget minus reserve tokens (what's usable for context)
            - remaining: Available minus total (how much space is left)
        """
        # Static system prompt (cacheable)
        system_tokens = self._counter.count(self._system_prompt) if self._system_prompt else 0

        # Dynamic context (injected per-request into last user message)
        dynamic = self.build_dynamic_context()
        dynamic_tokens = self._counter.count(dynamic) if dynamic else 0

        tools_tokens = self._count_tools_tokens()
        message_tokens = self._counter.count_messages(self._messages)
        total = system_tokens + dynamic_tokens + tools_tokens + message_tokens
        available = self.config.max_tokens - self.config.reserve_tokens
        remaining = max(0, available - total)

        return {
            "system": system_tokens,
            "dynamic": dynamic_tokens,
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
        system_tokens = self._counter.count(self._system_prompt) if self._system_prompt else 0
        dynamic = self.build_dynamic_context()
        dynamic_tokens = self._counter.count(dynamic) if dynamic else 0
        tools_tokens = self._count_tools_tokens()
        budget_for_messages = available - system_tokens - dynamic_tokens - tools_tokens

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
        system_tokens = self._counter.count(self._system_prompt) if self._system_prompt else 0
        dynamic = self.build_dynamic_context()
        dynamic_tokens = self._counter.count(dynamic) if dynamic else 0
        tools_tokens = self._count_tools_tokens()
        budget_for_messages = available - system_tokens - dynamic_tokens - tools_tokens

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
