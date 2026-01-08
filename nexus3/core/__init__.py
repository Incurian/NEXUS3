"""Core types and interfaces."""

from nexus3.core.cancel import CancellationToken
from nexus3.core.encoding import ENCODING, ENCODING_ERRORS, configure_stdio
from nexus3.core.errors import ConfigError, NexusError, ProviderError
from nexus3.core.interfaces import AsyncProvider
from nexus3.core.types import (
    ContentDelta,
    Message,
    Role,
    StreamComplete,
    StreamEvent,
    ToolCall,
    ToolCallStarted,
    ToolResult,
)

__all__ = [
    "CancellationToken",
    "ENCODING",
    "ENCODING_ERRORS",
    "configure_stdio",
    "NexusError",
    "ConfigError",
    "ProviderError",
    "AsyncProvider",
    "Message",
    "Role",
    "ToolCall",
    "ToolResult",
    # Streaming types
    "StreamEvent",
    "ContentDelta",
    "ToolCallStarted",
    "StreamComplete",
]
