"""Core types for NEXUS3.

This module defines the fundamental data structures used throughout the NEXUS3
framework: messages, tool calls, tool results, and roles. All dataclasses are
frozen for immutability.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Role(Enum):
    """Message role in a conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True)
class ToolCall:
    """A request to execute a tool.

    Attributes:
        id: Unique identifier for this tool call.
        name: Name of the tool to execute.
        arguments: Arguments to pass to the tool.
        meta: Optional parser/source metadata for diagnostics.
    """

    id: str
    name: str
    arguments: dict[str, Any]
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def raw_arguments(self) -> str | None:
        """Return preserved raw argument text when normalization failed."""
        raw_meta = self.meta.get("raw_arguments")
        if isinstance(raw_meta, str):
            return raw_meta

        if isinstance(self.arguments, dict):
            raw_legacy = self.arguments.get("_raw_arguments")
            if isinstance(raw_legacy, str):
                return raw_legacy

        return None

    @property
    def source_format(self) -> str | None:
        """Return the detected upstream tool-call format when known."""
        value = self.meta.get("source_format")
        return value if isinstance(value, str) else None

    @property
    def argument_format(self) -> str | None:
        """Return the detected argument payload format when known."""
        value = self.meta.get("argument_format")
        return value if isinstance(value, str) else None

    @property
    def normalization_error(self) -> str | None:
        """Return normalization error text when argument parsing failed."""
        value = self.meta.get("normalization_error")
        return value if isinstance(value, str) else None

    @property
    def has_unresolved_arguments(self) -> bool:
        """Return True when the tool-call arguments could not be normalized."""
        unresolved = self.meta.get("arguments_unresolved")
        if isinstance(unresolved, bool):
            return unresolved

        return self.raw_arguments is not None


@dataclass(frozen=True)
class Message:
    """A message in a conversation.

    Attributes:
        role: The role of the message sender.
        content: The text content of the message.
        tool_calls: Tool calls requested by the assistant (if any).
        tool_call_id: ID of the tool call this message is responding to (for tool messages).
        meta: Optional metadata (e.g., source attribution for multi-client sync).
    """

    role: Role
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    """Result of executing a tool.

    Attributes:
        output: The successful output from the tool.
        error: Error message if the tool failed.
    """

    output: str = ""
    error: str = ""

    @property
    def success(self) -> bool:
        """Return True if the tool execution succeeded (no error)."""
        return not self.error


# --- Streaming Types ---
# These types are yielded by provider.stream() to communicate content,
# tool calls, and completion status.


@dataclass(frozen=True)
class StreamEvent:
    """Base class for all streaming events."""

    pass


@dataclass(frozen=True)
class ContentDelta(StreamEvent):
    """A chunk of content text from the stream.

    Attributes:
        text: The text content to display.
    """

    text: str


@dataclass(frozen=True)
class ReasoningDelta(StreamEvent):
    """A chunk of reasoning/thinking content from the stream.

    Yielded when the model is in "thinking" mode. The text is the reasoning
    content, which may be displayed differently (muted) or hidden entirely.

    Attributes:
        text: The reasoning text.
    """

    text: str


@dataclass(frozen=True)
class ToolCallStarted(StreamEvent):
    """Notification that a tool call has been detected in the stream.

    Yielded once per tool call when we first see it, allowing
    display to show "calling read_file..." immediately.

    Attributes:
        index: The index of this tool call (for multiple calls).
        id: The unique ID of this tool call.
        name: The name of the tool being called.
    """

    index: int
    id: str
    name: str


@dataclass(frozen=True)
class StreamComplete(StreamEvent):
    """Signals the stream has ended.

    Contains the final accumulated Message with all content and tool_calls.

    Attributes:
        message: The complete Message with content and any tool_calls.
    """

    message: "Message"
