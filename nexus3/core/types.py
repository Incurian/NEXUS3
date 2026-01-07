"""Core types for NEXUS3.

This module defines the fundamental data structures used throughout the NEXUS3
framework: messages, tool calls, tool results, and roles. All dataclasses are
frozen for immutability.
"""

from dataclasses import dataclass
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
    """

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Message:
    """A message in a conversation.

    Attributes:
        role: The role of the message sender.
        content: The text content of the message.
        tool_calls: Tool calls requested by the assistant (if any).
        tool_call_id: ID of the tool call this message is responding to (for tool messages).
    """

    role: Role
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None


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
