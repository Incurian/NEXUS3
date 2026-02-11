"""Session-level event types for NEXUS3.

This module defines events emitted during session execution. These events flow
from Session to display components, enabling real-time UI updates for tool
execution, confirmations, and iteration progress.

Events are frozen dataclasses following the pattern in core/types.py.
"""

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nexus3.core.types import ToolCall

__all__ = [
    # Base
    "SessionEvent",
    # Content events
    "ContentChunk",
    "ReasoningStarted",
    "ReasoningEnded",
    # Tool detection
    "ToolDetected",
    # Batch lifecycle
    "ToolBatchStarted",
    "ToolStarted",
    "ToolCompleted",
    "ToolBatchHalted",
    "ToolBatchCompleted",
    # Iteration events
    "IterationCompleted",
    "SessionCompleted",
    "SessionCancelled",
]


@dataclass(frozen=True)
class SessionEvent:
    """Base class for session-level events.

    All session events inherit from this class to enable type-based dispatch
    in display components.
    """

    pass


# --- Content Events (pass-through from provider) ---


@dataclass(frozen=True)
class ContentChunk(SessionEvent):
    """Text content to display.

    Attributes:
        text: The text content chunk.
    """

    text: str


@dataclass(frozen=True)
class ReasoningStarted(SessionEvent):
    """Model started extended thinking.

    Emitted when the model begins a reasoning/thinking block.
    Display may show a visual indicator or mute reasoning content.
    """

    pass


@dataclass(frozen=True)
class ReasoningEnded(SessionEvent):
    """Model finished extended thinking.

    Emitted when the model exits a reasoning/thinking block.
    """

    pass


# --- Tool Detection (from stream) ---


@dataclass(frozen=True)
class ToolDetected(SessionEvent):
    """Tool call detected in stream (before execution).

    Emitted as soon as a tool call is parsed from the stream,
    allowing display to show "calling read_file..." immediately.

    Attributes:
        name: Name of the tool being called.
        tool_id: Unique identifier for this tool call.
    """

    name: str
    tool_id: str


# --- Batch Lifecycle ---


@dataclass(frozen=True)
class ToolBatchStarted(SessionEvent):
    """Batch of tools about to execute.

    Emitted before executing a batch of tool calls. The batch may execute
    in parallel or sequentially depending on configuration.

    Attributes:
        tool_calls: Tuple of ToolCall objects to execute.
        parallel: True if batch will execute in parallel.
        timestamp: Unix timestamp when event was created.
    """

    tool_calls: "tuple[ToolCall, ...]"
    parallel: bool = False
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ToolStarted(SessionEvent):
    """Individual tool starting execution.

    Emitted when a specific tool begins executing.

    Attributes:
        name: Name of the tool.
        tool_id: Unique identifier for this tool call.
        timestamp: Unix timestamp when event was created.
    """

    name: str
    tool_id: str
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ToolCompleted(SessionEvent):
    """Tool execution completed.

    Emitted when a tool finishes, whether successfully or with an error.

    Attributes:
        name: Name of the tool.
        tool_id: Unique identifier for this tool call.
        success: True if tool executed without error.
        error: Error message if success is False, empty string otherwise.
        output: Tool output if success is True, empty string otherwise.
        timestamp: Unix timestamp when event was created.
    """

    name: str
    tool_id: str
    success: bool
    error: str = ""
    output: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ToolBatchHalted(SessionEvent):
    """Sequential batch halted due to error.

    Emitted when a tool in a sequential batch fails, causing
    remaining tools in the batch to be skipped.

    Attributes:
        timestamp: Unix timestamp when event was created.
    """

    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ToolBatchCompleted(SessionEvent):
    """All tools in batch finished.

    Emitted after all tools in a batch have completed (or the batch
    was halted due to error).

    Attributes:
        timestamp: Unix timestamp when event was created.
    """

    timestamp: float = field(default_factory=time.time)


# --- Iteration Events ---


@dataclass(frozen=True)
class IterationCompleted(SessionEvent):
    """One tool loop iteration finished.

    Emitted after each iteration of the tool execution loop.

    Attributes:
        iteration: The iteration number (1-indexed).
        will_continue: True if the loop will continue (tools were executed).
    """

    iteration: int
    will_continue: bool


@dataclass(frozen=True)
class SessionCompleted(SessionEvent):
    """Session turn completed.

    Emitted when the session has finished processing a user message,
    either normally or due to hitting iteration limits.

    Attributes:
        halted_at_limit: True if stopped due to max iterations.
    """

    halted_at_limit: bool = False


@dataclass(frozen=True)
class SessionCancelled(SessionEvent):
    """Session turn was cancelled.

    Emitted when the session is cancelled via cancellation token.
    This is a terminal event - no more events will follow.
    """

    pass
