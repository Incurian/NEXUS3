"""Context compaction via LLM summarization."""

from dataclasses import dataclass
from datetime import datetime

from nexus3.core.types import Message, Role


def get_summary_prefix() -> str:
    """Generate summary prefix with current timestamp.

    Returns:
        Formatted summary prefix including when the compaction occurred.
    """
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M")
    return f"""[CONTEXT SUMMARY - Generated: {timestamp}]
The following is a summary of our previous conversation. It was automatically
generated when the context window needed compaction. Treat this as established
context - you don't need to re-confirm decisions already made.

---
"""

SUMMARIZE_PROMPT = """Summarize this conversation for context continuity.

Preserve:
- Key decisions made and their rationale
- Files created/modified and why
- Current task state and next steps
- Important constraints or requirements mentioned
- Any errors encountered and how they were resolved

Be concise but complete. This summary replaces the full conversation history.

CONVERSATION:
{conversation}

SUMMARY:"""


@dataclass
class CompactionResult:
    """Result of compaction operation."""

    summary_message: Message
    """The summary as a USER message with prefix."""

    preserved_messages: list[Message]
    """Recent messages that were preserved (not summarized)."""

    original_token_count: int
    """Token count before compaction."""

    new_token_count: int
    """Token count after compaction."""


def format_messages_for_summary(messages: list[Message]) -> str:
    """Format messages into text for summarization prompt.

    Args:
        messages: Messages to format

    Returns:
        Formatted conversation text
    """
    lines = []
    for msg in messages:
        role_name = msg.role.value.upper()
        if msg.role == Role.TOOL:
            role_name = f"TOOL[{msg.tool_call_id}]"

        lines.append(f"{role_name}: {msg.content}")

        # Include tool calls if present
        if msg.tool_calls:
            for tc in msg.tool_calls:
                lines.append(f"  → {tc.name}({tc.arguments})")

    return "\n\n".join(lines)


def create_summary_message(summary_text: str) -> Message:
    """Create a USER message containing the summary with timestamped prefix.

    Args:
        summary_text: The generated summary

    Returns:
        Message with role=USER and prefixed content including timestamp
    """
    return Message(
        role=Role.USER,
        content=f"{get_summary_prefix()}{summary_text}"
    )


def build_summarize_prompt(messages: list[Message]) -> str:
    """Build the prompt for the summarization LLM call.

    Args:
        messages: Messages to summarize

    Returns:
        Complete prompt for summarization
    """
    conversation = format_messages_for_summary(messages)
    return SUMMARIZE_PROMPT.format(conversation=conversation)


def select_messages_for_compaction(
    messages: list[Message],
    token_counter,  # TokenCounter protocol
    available_budget: int,
    recent_preserve_ratio: float,
) -> tuple[list[Message], list[Message]]:
    """Select which messages to summarize vs preserve.

    Walks from newest to oldest, keeping recent messages until we hit
    the preserve budget. Everything older gets summarized.

    Args:
        messages: All current messages
        token_counter: Token counter implementation
        available_budget: Total available token budget for messages
        recent_preserve_ratio: Ratio of budget to preserve (e.g., 0.25)

    Returns:
        Tuple of (messages_to_summarize, messages_to_preserve)
    """
    preserve_budget = int(available_budget * recent_preserve_ratio)

    preserved: list[Message] = []
    tokens = 0

    # Walk backwards, keep recent messages
    for msg in reversed(messages):
        msg_tokens = token_counter.count_messages([msg])
        if tokens + msg_tokens > preserve_budget and preserved:
            # Over budget and we have at least one message
            break
        preserved.insert(0, msg)
        tokens += msg_tokens

    # Everything before preserved gets summarized
    summarize_count = len(messages) - len(preserved)
    to_summarize = messages[:summarize_count]

    return to_summarize, preserved
